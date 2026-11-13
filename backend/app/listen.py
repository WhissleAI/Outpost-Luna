"""Live kid speech: browser mic -> Deepgram Flux (words + turns) and the model server (Arc metadata + emotion).

WebSocket /ws/listen
  client -> server: binary PCM16 mono 16 kHz frames (~80 ms each); text {"t":"stop"} ends the session.
  server -> client: {"t":"ready"}
                    {"t":"words","text":str,"final":bool}           every Flux TurnInfo (the whole current turn)
                    {"t":"turn","state":"start"|"eager"|"end"|"resumed","text":str}
                    {"t":"arc",...} / {"t":"emotion","label":str,"p":float}   relayed from the model server stream
                    {"t":"error","message":str}
The model server stream (ws://.../v1/stream) is optional: if it doesn't connect, metadata is skipped (fail open).
Flux protocol: developers.deepgram.com/reference/speech-to-text/listen-flux.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from functools import lru_cache
from urllib.parse import urlencode

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .config import settings
from .gazetteer import Gazetteer
from .keyterms import base_keyterms

log = logging.getLogger(__name__)
router = APIRouter()

FLUX = {"model": "flux-general-en", "encoding": "linear16", "sample_rate": 16000, "eot_threshold": 0.7,
        "eager_eot_threshold": 0.3}
TURN_STATE = {"StartOfTurn": "start", "EagerEndOfTurn": "eager", "EndOfTurn": "end", "TurnResumed": "resumed"}
FORCE_END = json.dumps({"type": "ForceEndTurn"})
CLOSE_STREAM = json.dumps({"type": "CloseStream"})
STOP_WAIT_S = 2.0


@lru_cache(maxsize=1)
def keyterms() -> tuple[str, ...]:
    return tuple(base_keyterms(Gazetteer(settings.data_dir / "places.json")))


def flux_url() -> str:
    q = list(FLUX.items()) + [("keyterm", k) for k in keyterms()]
    return settings.flux_url + "?" + urlencode(q)


def model_stream_url() -> str:
    if settings.model_stream_url:
        return settings.model_stream_url
    return settings.model_server_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/v1/stream"


def flux_messages(d: dict) -> list[dict]:
    """One Flux server message -> the client messages it produces."""
    if d.get("type") == "TurnInfo":
        ev, text = d.get("event"), (d.get("transcript") or "").strip()
        out = []
        if text or ev == "EndOfTurn":
            out.append({"t": "words", "text": text, "final": ev == "EndOfTurn"})
        if ev in TURN_STATE:
            out.append({"t": "turn", "state": TURN_STATE[ev], "text": text})
        return out
    if d.get("type") in ("Error", "ConfigureFailure"):
        return [{"t": "error", "message": f"deepgram: {d.get('code') or ''} {d.get('description') or ''}".strip()}]
    return []


@router.websocket("/ws/listen")
async def listen(ws: WebSocket):
    await ws.accept()
    lock = asyncio.Lock()

    async def send(m: dict):
        with contextlib.suppress(Exception):
            async with lock:
                await ws.send_json(m)

    if not settings.deepgram_api_key:
        await send({"t": "error", "message": "DEEPGRAM_API_KEY is not set on the backend"})
        await ws.close()
        return
    try:
        dg = await asyncio.wait_for(websockets.connect(
            flux_url(), additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"}), 5)
    except Exception as e:  # noqa: BLE001
        await send({"t": "error", "message": f"could not reach Deepgram: {e}"[:200]})
        await ws.close()
        return
    meta = None
    with contextlib.suppress(Exception):  # Arc metadata is optional
        meta = await asyncio.wait_for(websockets.connect(model_stream_url()), 1.0)

    turn_open = False
    ended = asyncio.Event()

    async def from_flux():
        nonlocal turn_open
        async for raw in dg:
            if not isinstance(raw, str):
                continue
            with contextlib.suppress(ValueError):
                d = json.loads(raw)
                if d.get("type") == "TurnInfo":
                    ev = d.get("event")
                    if ev == "EndOfTurn":
                        turn_open = False
                        ended.set()
                    elif ev in ("StartOfTurn", "Update", "EagerEndOfTurn", "TurnResumed"):
                        turn_open = True
                for m in flux_messages(d):
                    await send(m)

    async def from_meta():
        nonlocal meta
        try:
            async for raw in meta:
                with contextlib.suppress(ValueError):
                    d = json.loads(raw)
                    if isinstance(d, dict) and d.get("t") in ("arc", "emotion"):
                        await send(d)
        except Exception:  # noqa: BLE001
            pass
        meta = None

    async def tee_meta(data):
        nonlocal meta
        if meta is not None:
            try:
                await meta.send(data)
            except Exception:  # noqa: BLE001 (metadata never breaks the words path)
                meta = None

    tasks = [asyncio.create_task(from_flux())]
    if meta is not None:
        tasks.append(asyncio.create_task(from_meta()))
    await send({"t": "ready"})
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await dg.send(msg["bytes"])
                await tee_meta(msg["bytes"])
            elif msg.get("text"):
                with contextlib.suppress(ValueError):
                    if json.loads(msg["text"]).get("t") == "stop":
                        await tee_meta(msg["text"])
                        if turn_open:
                            ended.clear()
                            await dg.send(FORCE_END)
                            with contextlib.suppress(asyncio.TimeoutError):
                                await asyncio.wait_for(ended.wait(), STOP_WAIT_S)
                        break
    except WebSocketDisconnect:
        pass
    except websockets.ConnectionClosed as e:
        await send({"t": "error", "message": f"deepgram closed: {e}"[:200]})
    finally:
        with contextlib.suppress(Exception):
            await dg.send(CLOSE_STREAM)
        for t in tasks:
            t.cancel()
        for c in (dg, meta):
            if c is not None:
                with contextlib.suppress(Exception):
                    await c.close()
        with contextlib.suppress(Exception):
            await ws.close()
