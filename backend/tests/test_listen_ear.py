"""/ws/listen EAR switch: arc (local, default) relays the model server's Arc ear; fallback to Deepgram or `error`."""
import asyncio
import json
import threading

import pytest
import websockets
from fastapi.testclient import TestClient

from app import listen
from app.config import settings
from app.main import app

ARC_TURN = [{"t": "turn", "state": "start", "text": "shields"}, {"t": "words", "text": "shields to 40", "final": False},
            {"t": "turn", "state": "eager", "text": "shields to 40"},
            {"t": "words", "text": "shields to 40", "final": True}, {"t": "turn", "state": "end", "text": "shields to 40"},
            {"t": "arc", "command_complete": 0.8}, {"t": "internal"}]


@pytest.fixture
def servers(monkeypatch):
    loop = asyncio.new_event_loop()
    got = {"arc_ctx": [], "arc_bytes": 0, "flux": 0, "arc_q": [], "available": True}
    srv = []

    async def model(ws):
        got["arc_q"].append(ws.request.path)
        if not got["available"]:
            await ws.send(json.dumps({"t": "ear", "available": False, "reason": "META_MAX_SESSIONS reached"}))
            return
        await ws.send(json.dumps({"t": "ear", "available": True, "ear": "arc"}))
        async for m in ws:
            if isinstance(m, bytes):
                got["arc_bytes"] += 1
                if got["arc_bytes"] == 2:
                    for x in ARC_TURN:
                        await ws.send(json.dumps(x))
            else:
                d = json.loads(m)
                if d["t"] == "context":
                    got["arc_ctx"].append(d)
                    await ws.send(json.dumps({"t": "context_ack", "v": len(got["arc_ctx"])}))
                elif d["t"] == "stop":
                    return

    async def flux(ws):
        async for m in ws:
            if isinstance(m, bytes):
                got["flux"] += 1
                if got["flux"] == 2:
                    await ws.send(json.dumps({"type": "TurnInfo", "event": "EndOfTurn", "transcript": "hello moon"}))
            elif json.loads(m).get("type") == "CloseStream":
                return

    async def start():
        a = await websockets.serve(model, "127.0.0.1", 0)
        b = await websockets.serve(flux, "127.0.0.1", 0)
        srv.extend([a, b])
        return a.sockets[0].getsockname()[1], b.sockets[0].getsockname()[1]

    threading.Thread(target=loop.run_forever, daemon=True).start()
    pm, pf = asyncio.run_coroutine_threadsafe(start(), loop).result(5)
    monkeypatch.setattr(listen.ear_settings, "ear", "arc")
    monkeypatch.setattr(listen.ear_settings, "ear_connect_s", 1.0)
    monkeypatch.setattr(settings, "model_stream_url", f"ws://127.0.0.1:{pm}/v1/stream")
    monkeypatch.setattr(settings, "flux_url", f"ws://127.0.0.1:{pf}")
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    yield got

    async def stop():
        for s in srv:
            s.close()
        await asyncio.sleep(0.2)
    asyncio.run_coroutine_threadsafe(stop(), loop).result(5)
    loop.call_soon_threadsafe(loop.stop)


def collect_until_end(ws):
    out = []
    while not (out and out[-1].get("t") in ("turn", "error") and out[-1].get("state", "end") == "end"):
        out.append(ws.receive_json())
    return out


def test_arc_ear_relays_unchanged_and_sends_tier_a(servers):
    with TestClient(app) as c, c.websocket_connect("/ws/listen") as ws:
        assert ws.receive_json() == {"t": "ready"}
        assert ws.receive_json()["ear"] == "arc"
        ack0 = ws.receive_json()                                 # Tier A context ack
        ws.send_text(json.dumps({"t": "context", "names": ["Malapert"], "terms": ["shields"]}))
        ack1 = ws.receive_json()
        ws.send_bytes(bytes(2560))
        ws.send_bytes(bytes(2560))
        out = collect_until_end(ws)
        ws.send_text(json.dumps({"t": "stop"}))
    assert ack0["t"] == ack1["t"] == "context_ack"
    assert out == ARC_TURN[:5]                                   # relayed unchanged, in order
    assert servers["flux"] == 0 and "ear=arc" in servers["arc_q"][0]
    tier, client = servers["arc_ctx"]
    assert "Shackleton" in tier["names"] and "Apollo 16 rover" in tier["names"]
    assert client["names"][0] == "Malapert" and "Shackleton" in client["names"] and client["terms"] == ["shields"]


def test_arc_full_falls_back_to_deepgram_with_key(servers, monkeypatch):
    servers["available"] = False
    monkeypatch.setattr(settings, "deepgram_api_key", "test")
    with TestClient(app) as c, c.websocket_connect("/ws/listen") as ws:
        assert ws.receive_json() == {"t": "ready"}
        info = ws.receive_json()
        ws.send_bytes(bytes(2560))
        ws.send_bytes(bytes(2560))
        out = collect_until_end(ws)
        ws.send_text(json.dumps({"t": "stop"}))
    assert info["t"] == "ear" and info["ear"] == "deepgram" and "META_MAX" in info["fallback"]["reason"]
    assert out[-1] == {"t": "turn", "state": "end", "text": "hello moon"}


def test_arc_full_without_key_sends_error(servers):
    servers["available"] = False
    with TestClient(app) as c, c.websocket_connect("/ws/listen") as ws:
        m = ws.receive_json()
    assert m["t"] == "error" and "local ear unavailable" in m["message"]


def test_model_server_down_without_key_sends_error(servers, monkeypatch):
    monkeypatch.setattr(settings, "model_stream_url", "ws://127.0.0.1:9/v1/stream")
    with TestClient(app) as c, c.websocket_connect("/ws/listen") as ws:
        m = ws.receive_json()
    assert m["t"] == "error" and "unreachable" in m["message"]


def test_arc_context_merge_and_url(monkeypatch):
    m = listen.arc_context({"t": "context", "names": ["Shackleton"], "terms": ["rover"]}, ("Shackleton", "Cabeus", "Rover"))
    assert m["names"] == ["Shackleton", "Cabeus"] and m["terms"] == ["rover"]
    assert listen.arc_context({"t": "context", "mission": {"a": 1}}, ("X",)) == {"t": "context", "mission": {"a": 1}}
    monkeypatch.setattr(settings, "model_stream_url", "ws://h:1/v1/stream")
    assert listen.arc_ear_url() == "ws://h:1/v1/stream?ear=arc&domain=assistant"
