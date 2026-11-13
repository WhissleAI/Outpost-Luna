"""/ws/listen forwards the {"t":"context"} side channel to the model server stream and relays its ack."""
import asyncio
import json
import threading

import pytest
import websockets
from fastapi.testclient import TestClient

from app import listen
from app.config import settings
from app.main import app


@pytest.fixture
def fakes(monkeypatch):
    loop = asyncio.new_event_loop()
    got = {"context": [], "flux_text": []}
    servers = []

    async def flux(ws):
        async for m in ws:
            if isinstance(m, str):
                got["flux_text"].append(json.loads(m))
                if json.loads(m).get("type") == "CloseStream":
                    return

    async def meta(ws):
        async for m in ws:
            if isinstance(m, str):
                d = json.loads(m)
                if d.get("t") == "context":
                    got["context"].append(d)
                    await ws.send(json.dumps({"t": "context_ack", "v": len(got["context"]), "names": len(d.get("names", []))}))

    async def start():
        a = await websockets.serve(flux, "127.0.0.1", 0)
        b = await websockets.serve(meta, "127.0.0.1", 0)
        servers.extend([a, b])
        return a.sockets[0].getsockname()[1], b.sockets[0].getsockname()[1]

    async def stop():
        for srv in servers:
            srv.close()
        await asyncio.sleep(0.2)

    threading.Thread(target=loop.run_forever, daemon=True).start()
    pf, pm = asyncio.run_coroutine_threadsafe(start(), loop).result(5)
    monkeypatch.setattr(settings, "deepgram_api_key", "test")
    monkeypatch.setattr(settings, "flux_url", f"ws://127.0.0.1:{pf}")
    monkeypatch.setattr(settings, "model_stream_url", f"ws://127.0.0.1:{pm}")
    yield got
    asyncio.run_coroutine_threadsafe(stop(), loop).result(5)
    loop.call_soon_threadsafe(loop.stop)


def test_context_forwarded_and_acked(fakes):
    ctx = {"t": "context", "mission": {"power_pct": 72, "dose_msv": 14.2, "storm": True},
           "names": ["Shackleton", {"name": "Houston", "aliases": ["mission control"]}], "terms": ["mSv", "rover"],
           "junk": "dropped"}
    with TestClient(app) as c, c.websocket_connect("/ws/listen") as ws:
        assert ws.receive_json() == {"t": "ready"}
        ws.send_text(json.dumps(ctx))
        ack = ws.receive_json()
        ws.send_text(json.dumps({"t": "stop"}))
    assert ack == {"t": "context_ack", "v": 1, "names": 2}
    sent = fakes["context"][0]
    assert sent == {"t": "context", "mission": ctx["mission"], "names": ctx["names"], "terms": ctx["terms"]}
    assert not any(m.get("t") == "context" for m in fakes["flux_text"])   # never sent to Deepgram


def test_context_message_limits():
    m = listen.context_message({"t": "context", "names": ["a" * 200, 5, None, {"x": 1}], "terms": "not a list"})
    assert m == {"t": "context", "names": ["a" * 80, "5"], "terms": []}


def test_context_before_and_after_ready_does_not_break_audio(fakes):
    """The UI sends context right away and again after `ready`; audio and stop still work, junk is ignored."""
    with TestClient(app) as c, c.websocket_connect("/ws/listen") as ws:
        ws.send_text(json.dumps({"t": "context", "names": ["Shackleton"]}))
        assert ws.receive_json() == {"t": "ready"}
        ws.send_text("[1, 2]")
        ws.send_text("not json")
        ws.send_text(json.dumps({"t": "context", "names": ["Shackleton"], "mission": {"power_pct": 70}}))
        ws.send_bytes(bytes(2560))
        acks = [ws.receive_json(), ws.receive_json()]
        ws.send_text(json.dumps({"t": "stop"}))
    assert [a["t"] for a in acks] == ["context_ack", "context_ack"] and len(fakes["context"]) == 2
