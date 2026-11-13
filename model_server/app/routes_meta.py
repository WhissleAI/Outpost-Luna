"""POST /v1/meta (whole clip) and WS /v1/stream (live) for Arc audio metadata. See app/arcmeta.py."""
from __future__ import annotations

import asyncio
import io
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from . import arcmeta

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
               events: str = Form("default")):
    if arcmeta.STATE["arc"] is None:
        raise HTTPException(503, f"Arc metadata not loaded: {arcmeta.STATE['error']}")
    try:
        ws = json.loads(words) if words else []
        assert isinstance(ws, list)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, 'words must be a JSON list of {"w","t0","t1"}')
    wav = _decode(await audio.read())
    if len(wav) < arcmeta.SR // 10:
        raise HTTPException(400, "audio shorter than 100 ms or unreadable")
    try:
        return await run_in_threadpool(arcmeta.predict, wav, ws, domain, events)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.websocket("/v1/stream")
async def stream(ws: WebSocket):
    await ws.accept()
    domain = ws.query_params.get("domain", "assistant")
    await ws.send_json({"t": "emotion", "available": False, "reason": arcmeta.EMOTION_REASON})
    if not arcmeta.admit():
        # fail open: the client keeps working without metadata
        await ws.send_json({"t": "arc", "available": False,
                            "reason": arcmeta.STATE["error"] or "META_MAX_SESSIONS reached"})
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect" or (m.get("text") and '"stop"' in m["text"]):
                    break
        except WebSocketDisconnect:
            pass
        return
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arcmeta-ws")   # Arc calls in order, off the loop
    loop = asyncio.get_running_loop()
    ms = None
    try:
        ms = await loop.run_in_executor(pool, arcmeta.MetaStream, domain)
        await ws.send_json({"t": "arc", "available": True, "model": "arc-v1.1 mini", "domain": domain})
        buf = b""
        while True:
            m = await ws.receive()
            if m["type"] == "websocket.disconnect":
                break
            out = None
            if m.get("bytes"):
                buf += m["bytes"]
                if len(buf) >= 2560:          # >= 80 ms
                    n = len(buf) // 2 * 2
                    chunk, buf = buf[:n], buf[n:]
                    out = await loop.run_in_executor(pool, ms.feed, chunk)
            elif m.get("text"):
                try:
                    msg = json.loads(m["text"])
                except ValueError:
                    continue
                t = msg.get("t")
                if t == "words":
                    await loop.run_in_executor(pool, ms.add_words, msg.get("words") or [])
                elif t == "end_turn":
                    out = await loop.run_in_executor(pool, ms.end_turn)
                elif t == "stop":
                    out = await loop.run_in_executor(pool, ms.flush)
                    if out:
                        out["final"] = True
                        await ws.send_json(out)
                    break
            if out:
                await ws.send_json(out)
    except WebSocketDisconnect:
        pass
    finally:
        if ms is not None:
            await loop.run_in_executor(pool, ms.close)
        pool.shutdown(wait=False)
        arcmeta.release()
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
