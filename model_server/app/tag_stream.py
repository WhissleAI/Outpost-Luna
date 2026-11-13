"""Streaming Arc Tagger over a WebSocket: one dedicated native handle per connection.

This is what lets another app on the machine (Head Start, `MODELS=host`) drop its own copy of the tagger and use
this server's. The protocol mirrors Head Start's `server/tagger.py` `Tagger` one op per method:

    WS /v1/tag/stream?domain=assistant&emit=entity,number,...&asr=unknown

    server -> {"op":"ready","domain":...}                 once the handle exists (or close 1013 when full, 1008 on a
                                                          bad domain/option)
    {"op":"push","words":[...],"from":int|null,"endpoint":bool}   no reply
    {"op":"endpoint"}                                     no reply
    {"op":"reset"}                                        no reply
    {"op":"set","key":k,"value":v}                        no reply
    {"op":"poll"}                                         -> the poll JSON
    {"op":"tag_text","text":...}                          -> the tag JSON
    {"op":"info"}                                         -> the info JSON

Ops without a reply are pipelined (the client doesn't wait for them). If one fails, the error is held and returned
as `{"op":"error","error":...}` in place of the next reply, so the caller sees it on its next poll / tag_text.
The handle is created on connect and destroyed on close; `TAG_STREAM_MAX` caps live handles.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .config import settings

router = APIRouter()
ACTIVE = {"n": 0}  # live stream handles; only touched on the event loop, so no lock


def _state():
    from .main import STATE  # late import: main includes this router
    return STATE


@router.websocket("/v1/tag/stream")
async def tag_stream(ws: WebSocket, domain: str = "assistant", emit: str | None = None, asr: str = "unknown"):
    await ws.accept()
    tg = _state()["tagger"]
    if tg is None:
        await ws.close(code=1011, reason=f"Arc Tagger not loaded: {_state()['tagger_error']}"[:120])
        return
    if ACTIVE["n"] >= settings.tag_stream_max:
        await ws.close(code=1013, reason=f"tag stream limit reached ({settings.tag_stream_max})")
        return
    ACTIVE["n"] += 1
    h = None
    try:
        try:
            h = await asyncio.to_thread(tg.open_stream, domain, emit)
            if asr != "unknown":
                tg.set_option(h, "asr", asr)
        except (KeyError, ValueError, RuntimeError) as e:
            await ws.close(code=1008, reason=str(e)[:120])
            return
        await ws.send_text(json.dumps({"op": "ready", "domain": domain}))
        held: str | None = None
        while True:
            m = json.loads(await ws.receive_text())
            op = m.get("op")
            try:
                if op == "push":
                    if m.get("from") is None and not m.get("endpoint"):
                        payload = m.get("words") or []
                    else:
                        payload = {"words": m.get("words") or []}
                        if m.get("from") is not None:
                            payload["from"] = int(m["from"])
                        if m.get("endpoint"):
                            payload["endpoint"] = True
                    await asyncio.to_thread(tg.push_words, h, json.dumps(payload).encode())
                    continue
                if op == "endpoint":
                    await asyncio.to_thread(tg.push_words, h, b'{"endpoint": true}')
                    continue
                if op == "reset":
                    tg.reset(h)
                    continue
                if op == "set":
                    tg.set_option(h, m["key"], m["value"])
                    continue
                if held is not None:
                    out, held = {"op": "error", "error": held}, None
                elif op == "poll":
                    out = tg.poll(h)   # cheap (~0.02 ms): inference happens in push, so no thread hop
                elif op == "tag_text":
                    out = await asyncio.to_thread(tg.tag_text_on, h, m.get("text") or "")
                elif op == "info":
                    out = tg.info_on(h)
                else:
                    out = {"op": "error", "error": f"unknown op {op!r}"}
            except (ValueError, RuntimeError, KeyError) as e:
                if op in ("push", "endpoint", "reset", "set"):
                    held = held or str(e)
                    continue
                out = {"op": "error", "error": str(e)}
            await ws.send_text(json.dumps(out))
    except WebSocketDisconnect:
        pass
    finally:
        ACTIVE["n"] -= 1
        if h is not None:
            tg.close_stream(h)
