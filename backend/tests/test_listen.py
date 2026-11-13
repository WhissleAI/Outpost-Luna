"""/ws/listen with fake Flux and model-server streams (no network, no key)."""
import asyncio
import json
import threading

import pytest
import websockets
from fastapi.testclient import TestClient

from app import listen
from app.config import settings
from app.main import app

TURN = [("StartOfTurn", "show"), ("Update", "show me the"), ("EagerEndOfTurn", "show me the giant bullseye"),
        ("EndOfTurn", "show me the giant bullseye")]


def test_flux_messages_mapping():
    m = listen.flux_messages({"type": "TurnInfo", "event": "EagerEndOfTurn", "transcript": "hi moon"})
    assert m == [{"t": "words", "text": "hi moon", "final": False}, {"t": "turn", "state": "eager", "text": "hi moon"}]
    assert listen.flux_messages({"type": "TurnInfo", "event": "Update", "transcript": ""}) == []
    assert listen.flux_messages({"type": "Error", "code": "X", "description": "bad"})[0]["t"] == "error"
    assert "keyterm=Orientale" in listen.flux_url() and "eager_eot_threshold=0.3" in listen.flux_url()


@pytest.fixture
def fakes(monkeypatch):
    loop = asyncio.new_event_loop()
    got = {"flux": 0, "meta": 0}
    servers = []

    async def flux(ws):
        async for m in ws:
            if isinstance(m, bytes):
                got["flux"] += 1
                if got["flux"] == 3:
                    for ev, text in TURN:
                        await ws.send(json.dumps({"type": "TurnInfo", "event": ev, "transcript": text}))
            elif json.loads(m).get("type") == "CloseStream":
                return

    async def meta(ws):
        async for m in ws:
            if isinstance(m, bytes):
                got["meta"] += 1
                if got["meta"] == 2:
                    await ws.send(json.dumps({"t": "emotion", "label": "curious", "p": 0.8}))
                    await ws.send(json.dumps({"t": "other"}))

    async def start():
        a = await websockets.serve(flux, "127.0.0.1", 0)
        b = await websockets.serve(meta, "127.0.0.1", 0)
        servers.extend([a, b])
        return a.sockets[0].getsockname()[1], b.sockets[0].getsockname()[1]

    async def stop():
        for srv in servers:
            srv.close()
        await asyncio.sleep(0.2)  # let the closing handshakes finish before the loop stops


    threading.Thread(target=loop.run_forever, daemon=True).start()
    pf, pm = asyncio.run_coroutine_threadsafe(start(), loop).result(5)
    monkeypatch.setattr(settings, "deepgram_api_key", "test")
    monkeypatch.setattr(settings, "flux_url", f"ws://127.0.0.1:{pf}")
    monkeypatch.setattr(settings, "model_stream_url", f"ws://127.0.0.1:{pm}")
    yield got
    asyncio.run_coroutine_threadsafe(stop(), loop).result(5)
    loop.call_soon_threadsafe(loop.stop)


def test_listen_relays_words_turns_and_emotion(fakes):
    with TestClient(app) as c, c.websocket_connect("/ws/listen") as ws:
        assert ws.receive_json() == {"t": "ready"}
        for _ in range(4):
            ws.send_bytes(bytes(2560))
        out = []
        while not (out and out[-1].get("state") == "end"):
            out.append(ws.receive_json())
        ws.send_text(json.dumps({"t": "stop"}))
    turns = [m["state"] for m in out if m["t"] == "turn"]
    assert turns == ["start", "eager", "end"]
    assert [m for m in out if m["t"] == "words"][-1] == {"t": "words", "text": "show me the giant bullseye", "final": True}
    assert {"t": "emotion", "label": "curious", "p": 0.8} in out
    assert not [m for m in out if m["t"] == "other"]


def test_listen_without_key_reports_error(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    with TestClient(app) as c, c.websocket_connect("/ws/listen") as ws:
        assert ws.receive_json()["t"] == "error"
