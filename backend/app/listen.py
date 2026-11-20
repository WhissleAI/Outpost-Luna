"""Live kid speech: browser mic -> the ear (words + turns) and Arc metadata + emotion.

EAR=arc (default, local): one model-server stream, ws://.../v1/stream?ear=arc, gives words, turns, names and metadata
    from Arc Transcriber Space (model_server/app/arc_ear.py). Its messages are relayed unchanged. The session screen's
    NAMES LIST (names_list.py: <= 40 {"name","kind","aliases"}, most relevant first) is sent as context first and again
    on every screen change; a client context frame's names go in front of it.
EAR=deepgram: Deepgram Flux (cloud) for words + turns, the model-server stream for metadata only (the original path).
If the Arc ear isn't available (model server down / full / decoder off), the session falls back to Deepgram when a
DEEPGRAM_API_KEY is set, else sends `error` so the browser falls back to Web Speech push-to-talk.

WebSocket /ws/listen
  client -> server: binary PCM16 mono 16 kHz frames (~80 ms each); text {"t":"stop"} ends the session.
                    text {"t":"context","mission":{...},"names":[...],"terms":[...]} (any time): a side channel of
                    what the app knows (mission State subset, crew/place names, terms). Forwarded to the model server
                    stream as-is (docs/STREAMS.md); its {"t":"context_ack"} comes back to the client.
  server -> client: {"t":"ready"}
                    {"t":"words","text":str,"final":bool}           every Flux TurnInfo (the whole current turn)
                    {"t":"turn","state":"start"|"eager"|"end"|"resumed","text":str}
                    {"t":"arc",...} / {"t":"emotion","label":str,"p":float}   relayed from the model server stream
                    {"t":"context_ack",...}                                   the model server took the context
                    {"t":"error","message":str}
                    {"t":"ear","ear":"arc"|"deepgram",...}                     which ear serves this session (info)
With EAR=deepgram the model server stream (ws://.../v1/stream) is optional: if it doesn't connect, metadata is skipped (fail open).
Flux protocol: developers.deepgram.com/reference/speech-to-text/listen-flux.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from functools import lru_cache
from urllib.parse import urlencode

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import diag, playtest, session as sessions
from .config import settings
from .gazetteer import Gazetteer
from .keyterms import base_keyterms
from .local_guard import auth_headers

log = logging.getLogger(__name__)
router = APIRouter()

FLUX = {"model": "flux-general-en", "encoding": "linear16", "sample_rate": 16000, "eot_threshold": 0.7,
        "eager_eot_threshold": 0.3}
TURN_STATE = {"StartOfTurn": "start", "EagerEndOfTurn": "eager", "EndOfTurn": "end", "TurnResumed": "resumed"}
FORCE_END = json.dumps({"type": "ForceEndTurn"})
CLOSE_STREAM = json.dumps({"type": "CloseStream"})
STOP_WAIT_S = 2.0


class EarSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    ear: str = "arc"               # arc | deepgram
    ear_connect_s: float = 2.0     # model server connect + {"t":"ear"} handshake
    ear_names: bool = True         # send the screen's names list ({"t":"context","names"}) at the start + on every change
    ear_names_every_s: float = 0.25   # how often the relay checks the session's screen for a new list


ear_settings = EarSettings()


def default_names() -> list[dict]:
    """Before the session is known: the Moon map's list."""
    from .names_list import screen_names
    return screen_names({"screen": "map"})


@lru_cache(maxsize=1)
def keyterms() -> tuple[str, ...]:
    """Deepgram keyterms for the active course: its manifest `ear.keyterms`, else (the Moon) the lunar lists."""
    from . import courses
    own = courses.keyterms()
    if own is not None:
        return tuple(own[:50])
    return tuple(base_keyterms(Gazetteer(courses.path("gazetteer") or settings.data_dir / "places.json")))


def flux_url() -> str:
    q = list(FLUX.items()) + [("keyterm", k) for k in keyterms()]
    return settings.flux_url + "?" + urlencode(q)


def model_stream_url() -> str:
    if settings.model_stream_url:
        return settings.model_stream_url
    return settings.model_server_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/v1/stream"


def arc_ear_url() -> str:
    u = model_stream_url()
    return u + ("&" if "?" in u else "?") + "ear=arc&domain=assistant"


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


CONTEXT_KEYS = ("mission", "names", "terms", "telemetry", "topic")


def context_message(d: dict) -> dict:
    """The client's context message, limited to the keys the model server reads (docs/STREAMS.md)."""
    out = {"t": "context"}
    for k in CONTEXT_KEYS:
        if d.get(k) is not None:
            out[k] = d[k]
    for k in ("names", "terms"):
        if k in out:
            xs = out[k] if isinstance(out[k], list) else []
            out[k] = [x if isinstance(x, dict) else str(x)[:80] for x in xs
                      if isinstance(x, (str, int, float)) or (isinstance(x, dict) and x.get("name"))][:200]
    return out


def arc_context(d: dict, base: list | tuple = ()) -> dict:
    """context_message() for the Arc ear: the client's names first (what's on screen now), then the screen's list.
    A client's plain-string names become {"name": s, "kind": "place"} (the model needs a kind); capped at
    names_list.MAX_EAR (the Moon screens' list length)."""
    from .names_list import MAX_EAR
    out = context_message(d)
    out.pop("terms", None)        # Arc Transcriber Space has no free-term slot
    if "names" in out:
        mine = [x if isinstance(x, dict) else {"name": str(x), "kind": "place"} for x in out["names"]]
        seen = {str(x.get("name")).lower() for x in mine}
        out["names"] = (mine + [n for n in base if str(n.get("name")).lower() not in seen])[:MAX_EAR]
    return out


async def open_arc_ear():
    """(connection, None) once the model server says {"t":"ear","available":true}; else (None, reason)."""
    try:
        conn = await asyncio.wait_for(websockets.connect(arc_ear_url(), max_size=2 ** 22,
                                                         additional_headers=auth_headers()), ear_settings.ear_connect_s)
    except Exception as e:  # noqa: BLE001
        return None, f"model server unreachable: {type(e).__name__}"
    try:
        while True:
            d = json.loads(await asyncio.wait_for(conn.recv(), ear_settings.ear_connect_s))
            if d.get("t") == "ear":
                if d.get("available"):
                    return conn, None
                break
        reason = d.get("reason") or "arc ear unavailable"
    except Exception as e:  # noqa: BLE001 (old model server: no ear handshake, or it closed)
        reason = f"no arc ear handshake: {type(e).__name__}"
    with contextlib.suppress(Exception):
        await conn.close()
    return None, reason


@router.websocket("/ws/listen")
async def listen(ws: WebSocket):
    await ws.accept()
    lock = asyncio.Lock()
    # Session Director hook (docs/SESSION_CONTRACT.md §1): ?session=<id>, or `session` in a context frame, makes this
    # relay also post its words / turn / arc / emotion into that session server-side.
    sid = {"id": ws.query_params.get("session")}
    stat = {"ear": None, "turns": 0, "errors": 0, "t0": time.perf_counter()}   # [#92] counts only, never words
    diag.METRICS.inc("listen_sessions")
    # a grown-up's Playtest session (playtest.py): the mic audio this relay already forwards, kept in memory only while
    # one runs, cut per kid turn and handed to the session (never to the client, never in a log line)
    ws.state.playtest = rec = playtest.Recorder()

    async def send(m: dict):
        _count(m, stat)
        with contextlib.suppress(Exception):
            async with lock:
                await ws.send_json(m)
        if sid["id"] and m.get("t") in ("words", "turn", "arc", "emotion", "echo_delay"):
            clip = None
            with contextlib.suppress(Exception):
                clip = rec.mark(m)
            await sessions.post(sid["id"], {**m, "_pcm": clip} if clip else m)

    try:
        await _listen(ws, send, sid)
    finally:
        diag.LOG.event("listen_close", ear=stat["ear"], turns=stat["turns"], errors=stat["errors"],
                       open_s=round(time.perf_counter() - stat["t0"], 1))


def _count(m: dict, stat: dict) -> None:
    """[#92] The relay's metrics: turns per ear, errors by code. Reads only the message type and state."""
    t = m.get("t")
    if t == "ear":
        stat["ear"] = m.get("ear")
    elif t == "turn" and m.get("state") == "end":
        stat["turns"] += 1
        diag.METRICS.inc("turns", ear=stat["ear"] or "unknown")
    elif t == "error":
        stat["errors"] += 1
        code = str(m.get("code") or ("ear_closed" if "closed" in str(m.get("message") or "") else "listen_error"))
        diag.METRICS.error(code)
        diag.LOG.warning("listen_error", code=code, ear=stat["ear"])


async def _listen(ws: WebSocket, send, sid: dict):
    want = ear_settings.ear.strip().lower()
    fallback_from = None
    if want != "deepgram":
        arc, why = await open_arc_ear()
        if arc is not None:
            return await run_arc(ws, send, sid, arc)
        diag.METRICS.error("ear_unavailable")
        diag.LOG.warning("ear_unavailable", reason=why, fallback=bool(settings.deepgram_api_key))
        log.warning("arc ear unavailable (%s)%s", why, "; falling back to Deepgram" if settings.deepgram_api_key else "")
        fallback_from = {"from": "arc", "reason": why}
        if not settings.deepgram_api_key:
            await send({"t": "error", "message": f"local ear unavailable ({why}) and no DEEPGRAM_API_KEY"[:200]})
            await ws.close()
            return
    await run_deepgram(ws, send, sid, fallback_from)


def _keep(ws: WebSocket, b: bytes) -> None:
    """The mic audio, for a running Playtest session only (playtest.Recorder; a no-op otherwise)."""
    with contextlib.suppress(Exception):
        ws.state.playtest.feed(b)


REF_MAX_B64 = 16000 * 2 * 12 * 4 // 3 + 8     # one reference message: at most 12 s of 16 kHz PCM16


def ref_message(d: dict) -> dict | None:
    """A client playback reference {"t":"ref","at","pcm"} (pcm: base64 PCM16 LE mono 16 kHz; at: the mic stream time,
    in seconds of audio this socket has sent, when the first sample plays) -> the model server's form, or None."""
    pcm, at = d.get("pcm"), d.get("at")
    if not isinstance(pcm, str) or not pcm or len(pcm) > REF_MAX_B64:
        return None
    try:
        at = None if at is None else float(at)
    except (TypeError, ValueError):
        return None
    return {"t": "ref", "at": at, "pcm": pcm}


async def run_arc(ws: WebSocket, send, sid: dict, arc):
    """EAR=arc: audio + context to the model server's Arc ear; its words / turn / arc / emotion / context_ack back."""
    base = default_names() if ear_settings.ear_names else []
    if base:
        await arc.send(json.dumps({"t": "context", "names": base}))
    # error: the decode watchdog (#87); entity / eot / barge_in: libarc ABI 2 live events (model_server arc_ear.py)
    # echo_delay / tune_ack: on-device learning (app/learn): this computer's echo delay per line, the applied tuning
    relay = ("words", "turn", "arc", "emotion", "context_ack", "error", "entity", "eot", "barge_in", "echo_delay",
             "tune_ack")

    async def from_arc():
        async for raw in arc:
            with contextlib.suppress(ValueError):
                d = json.loads(raw)
                if isinstance(d, dict) and d.get("t") in relay:
                    await send(d)

    task = asyncio.create_task(from_arc())

    async def names_loop():
        """The session's screen -> the ear's names list (names_list.py), sent whenever it changes."""
        nonlocal base
        last, last_tune = base, None
        while True:
            with contextlib.suppress(Exception):
                s = sessions.get(sid["id"], create=False) if sid["id"] else None
                names = s.ear_names() if s is not None else None
                if names and names != last:
                    await arc.send(json.dumps({"t": "context", "names": names}))
                    last = base = names
                tune = s.ear_tune() if s is not None else None   # on-device learning (app/learn): bounded values
                if tune and tune != last_tune:
                    await arc.send(json.dumps({"t": "tune", **tune}))
                    last_tune = tune
            await asyncio.sleep(ear_settings.ear_names_every_s)

    hot_task = asyncio.create_task(names_loop()) if ear_settings.ear_names else None
    await send({"t": "ready"})
    await send({"t": "ear", "ear": "arc", "model": "arc-transcriber-space nft2"})
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if task.done():
                await send({"t": "error", "message": "local ear closed"})
                break
            if msg.get("bytes") is not None:
                _keep(ws, msg["bytes"])
                await arc.send(msg["bytes"])
            elif msg.get("text"):
                with contextlib.suppress(ValueError, AttributeError):
                    d = json.loads(msg["text"])
                    if d.get("t") == "context":
                        if d.get("session"):
                            sid["id"] = str(d["session"])
                        await arc.send(json.dumps(arc_context(d, base)))
                    elif d.get("t") == "ref":       # what the app plays, for the ear's echo canceller
                        r = ref_message(d)
                        if r is not None:
                            await arc.send(json.dumps(r))
                    elif d.get("t") == "stop":
                        await arc.send(json.dumps({"t": "stop"}))
                        with contextlib.suppress(asyncio.TimeoutError, Exception):
                            await asyncio.wait_for(asyncio.shield(task), STOP_WAIT_S)
                        break
    except WebSocketDisconnect:
        pass
    except websockets.ConnectionClosed as e:
        await send({"t": "error", "message": f"local ear closed: {e}"[:200]})
    finally:
        task.cancel()
        if hot_task is not None:
            hot_task.cancel()
        with contextlib.suppress(Exception):
            await arc.close()
        with contextlib.suppress(Exception):
            await ws.close()


async def run_deepgram(ws: WebSocket, send, sid: dict, fallback_from: dict | None = None):
    """EAR=deepgram (or the Arc ear's fallback): Flux for words + turns, the model server stream for metadata only."""
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
        meta = await asyncio.wait_for(websockets.connect(model_stream_url(), additional_headers=auth_headers()), 1.0)

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
                    if isinstance(d, dict) and d.get("t") in ("arc", "emotion", "context_ack"):
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
    if fallback_from:   # tell the client the local ear wasn't there (info; the browser ignores unknown types)
        await send({"t": "ear", "ear": "deepgram", "model": FLUX["model"], "fallback": fallback_from})
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                _keep(ws, msg["bytes"])
                await dg.send(msg["bytes"])
                await tee_meta(msg["bytes"])
            elif msg.get("text"):
                with contextlib.suppress(ValueError, AttributeError):
                    d = json.loads(msg["text"])
                    if d.get("t") == "context":
                        if d.get("session"):
                            sid["id"] = str(d["session"])
                        await tee_meta(json.dumps(context_message(d)))
                        continue
                    if d.get("t") == "stop":
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
