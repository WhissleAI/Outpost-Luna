"""POST /v1/meta (whole clip) and WS /v1/stream (live): the ear (?ear=arc) and its metadata-only form. See app/arcmeta.py
and app/arc_ear.py."""
from __future__ import annotations

import asyncio
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from . import arc_ear, arcmeta, diag
from .decode_watchdog import DecodeTimeout, guarded
from .stream_context import StreamContext

router = APIRouter()


def _decode(data: bytes) -> np.ndarray:
    """Any file soundfile reads (wav, flac, mp3 via libsndfile >= 1.1), or raw PCM16 mono 16 kHz, -> float32 16 kHz."""
    try:
        import soundfile as sf
        x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
        x = x.mean(axis=1)
    except Exception:  # noqa: BLE001
        x, sr = np.frombuffer(data[: len(data) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0, arcmeta.SR
    if sr != arcmeta.SR:
        from math import gcd

        from scipy.signal import resample_poly
        g = gcd(int(sr), arcmeta.SR)
        x = resample_poly(x, arcmeta.SR // g, int(sr) // g).astype(np.float32)
    return np.ascontiguousarray(x, dtype=np.float32)


@router.post("/v1/meta")
async def meta(audio: UploadFile = File(...), words: str | None = Form(None), domain: str = Form("assistant"),
               events: str = Form("default"), names: str | None = Form(None)):
    if arcmeta.STATE["arc"] is None:
        raise HTTPException(503, f"Arc metadata not loaded: {arcmeta.STATE['error']}")
    try:
        ws = json.loads(words) if words else []
        assert isinstance(ws, list)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, 'words must be a JSON list of {"w","t0","t1"}')
    try:
        ns = json.loads(names) if names else []
        assert isinstance(ns, list)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, 'names must be a JSON list of {"name","kind","aliases"}')
    wav = _decode(await audio.read())
    if len(wav) < arcmeta.SR // 10:
        raise HTTPException(400, "audio shorter than 100 ms or unreadable")
    try:
        return await run_in_threadpool(arcmeta.predict, wav, ws, domain, events, ns)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.websocket("/v1/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    domain = ws.query_params.get("domain", "assistant")
    if ws.query_params.get("ear") == "arc":
        return await ear_stream(ws, domain)
    await ws.send_json({"t": "emotion", "available": False, "reason": arcmeta.EMOTION_REASON})
    ctx = StreamContext()   # {"t":"context"} side channel (app/stream_context.py, docs/STREAMS.md)
    if not arcmeta.admit():
        # fail open: the client keeps working without metadata
        await ws.send_json({"t": "arc", "available": False,
                            "reason": arcmeta.STATE["error"] or "META_MAX_SESSIONS reached"})
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect" or (m.get("text") and '"stop"' in m["text"]):
                    break
                if m.get("text") and '"context"' in m["text"]:
                    await ws.send_json(ctx.update(json.loads(m["text"])))
        except WebSocketDisconnect:
            pass
        return
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arcmeta-ws")   # Arc calls in order, off the loop
    loop = asyncio.get_running_loop()
    ms = None
    try:
        ms = await loop.run_in_executor(pool, lambda: arc_ear.EarStream(domain, metadata_only=True))
        await ws.send_json({"t": "arc", "available": True, "model": arcmeta.MODEL, "domain": domain})
        buf = b""
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            if m.get("bytes"):
                buf += m["bytes"]
                if len(buf) >= 2560:          # >= 80 ms
                    n = len(buf) // 2 * 2
                    chunk, buf = buf[:n], buf[n:]
                    for o in await guarded(loop, pool, ms.feed_all, chunk):
                        await ws.send_json(ctx.decorate(o))
            elif m.get("text"):
                try:
                    msg = json.loads(m["text"])
                except ValueError:
                    continue
                t = msg.get("t")
                if t == "context":
                    await ws.send_json(await guarded(loop, pool, ctx.update, msg, ms))
                elif t == "words":
                    pass        # the external words are not needed: the model hears the audio itself
                elif t == "end_turn":
                    for o in await guarded(loop, pool, ms.end_turn_all):
                        await ws.send_json(ctx.decorate(o))
                elif t == "stop":
                    outs = [o for o in await guarded(loop, pool, ms.flush_all) if o.get("t") == "arc"]
                    outs = outs or [{"t": "arc", "at": round(ms.audio_s, 2), "device_directed": None, "speech": False,
                                     "audio_events": [], "bio_events": [], "names": [],
                                     "rtf": round(ms.compute_s / ms.audio_s, 3) if ms.audio_s else None}]
                    for o in outs:
                        o["final"] = True
                        await ws.send_json(ctx.decorate(o))
                    break
    except WebSocketDisconnect:
        pass
    except DecodeTimeout as e:
        await _hung(ws, ms, str(e))
        ms = None               # its worker is stuck: never queue close() behind it
    finally:
        if ms is not None:
            await loop.run_in_executor(pool, ms.close)
        pool.shutdown(wait=False)
        arcmeta.release()
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


async def _hung(ws: WebSocket, stream, why: str) -> None:
    """The decode watchdog fired (app/decode_watchdog.py): tell the client, reset the model handle, close (1011)."""
    model = getattr(stream, "m", None)
    reset = arcmeta.reset_after_hang(model, why)
    try:
        await ws.send_json({"t": "error", "code": "decode_timeout", "message": f"the ear stopped responding ({why})",
                            "reset": reset})
        await ws.close(code=1011)
    except Exception:  # noqa: BLE001 (the client may be gone already)
        pass


def _ear_unavailable() -> str | None:
    if arcmeta.STATE["arc"] is None:
        return f"Arc not loaded: {arcmeta.STATE['error']}"
    return None


async def ear_stream(ws: WebSocket, domain: str):
    """WS /v1/stream?ear=arc: Arc Transcriber Space's words + turns + names + metadata (app/arc_ear.py). Unlike metadata mode this does not
    fail open: when the ear can't be served the client is told at once ({"t":"ear","available":false}) and the socket
    closes (1013), so it can pick another ear."""
    why = _ear_unavailable()
    if why is None and not arcmeta.admit():
        why = "META_MAX_SESSIONS reached"
    if why:
        diag.METRICS.error("ear_unavailable")
        diag.LOG.warning("ear_unavailable", reason=why)
        await ws.send_json({"t": "ear", "available": False, "ear": "arc", "reason": why})
        await ws.close(code=1013)
        return
    ctx = StreamContext()
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arcear-ws")
    loop = asyncio.get_running_loop()
    es = seen = None
    opened = time.perf_counter()

    async def send_all(msgs):
        for m in msgs:
            await ws.send_json(ctx.decorate(m))

    try:
        es = seen = await loop.run_in_executor(pool, arc_ear.EarStream, domain)
        diag.METRICS.inc("ear_streams")
        diag.LOG.event("ear_stream_open", domain=domain, sessions=arcmeta.STATE["sessions"])
        await ws.send_json({"t": "ear", "available": True, "ear": "arc", "model": arcmeta.MODEL, "domain": domain})
        await ws.send_json({"t": "emotion", "available": False, "reason": arcmeta.EMOTION_REASON})
        buf = b""
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            if m.get("bytes"):
                buf += m["bytes"]
                if len(buf) >= 2560:          # >= 80 ms
                    n = len(buf) // 2 * 2
                    chunk, buf = buf[:n], buf[n:]
                    await send_all(await guarded(loop, pool, es.feed_all, chunk))
            elif m.get("text"):
                try:
                    msg = json.loads(m["text"])
                except ValueError:
                    continue
                t = msg.get("t")
                if t == "context":
                    await ws.send_json(await guarded(loop, pool, ctx.update, msg, es))
                elif t == "end_turn":
                    await send_all(await guarded(loop, pool, es.end_turn_all))
                elif t == "stop":
                    await send_all(await guarded(loop, pool, es.flush_all))
                    break
    except WebSocketDisconnect:
        pass
    except DecodeTimeout as e:
        await _hung(ws, es, str(e))
        es = None               # its worker is stuck: never queue close() behind it
    finally:
        if seen is not None:    # [#92] one line per stream: how much audio, how fast, how many turns (no words)
            a_s, c_s = getattr(seen, "audio_s", 0.0) or 0.0, getattr(seen, "compute_s", 0.0) or 0.0
            diag.LOG.event("ear_stream_close", audio_s=round(a_s, 2), compute_s=round(c_s, 3),
                           rtf=round(c_s / a_s, 3) if a_s else None, turns=len(getattr(seen, "ends", []) or []),
                           open_s=round(time.perf_counter() - opened, 1), hung=es is None)
        if es is not None:
            await loop.run_in_executor(pool, es.close)
        pool.shutdown(wait=False)
        arcmeta.release()
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
