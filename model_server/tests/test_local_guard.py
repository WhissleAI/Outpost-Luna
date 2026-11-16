"""[#84] The model server's WebSockets and POSTs refuse hostile origins and missing / wrong tokens; [#87] the decode
watchdog abandons a hung decode, tells the client and resets the model handle. No models are loaded (no lifespan)."""
from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import arc_ear, arcmeta, decode_watchdog
from app.local_guard import LocalGuard, host_name
from app.main import app

TOKEN = "t0k3n-for-tests"


def guarded_client(**kw):
    return TestClient(LocalGuard(app, token=TOKEN, allowed_hosts=["testserver"], **kw))


def refused(client, path, headers=None):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(path, headers=headers or {}) as ws:
            ws.receive_json()
    return e.value.code


@pytest.mark.parametrize("path", ["/v1/stream", "/v1/stream?ear=arc", "/v1/tag/stream"])
def test_hostile_origin_websocket_is_refused(path):
    c = TestClient(app)     # no token configured: the Origin check alone
    assert refused(c, path, {"origin": "https://evil.example"}) == 1008
    assert refused(c, path, {"origin": "null"}) == 1008


@pytest.mark.parametrize("path", ["/v1/stream", "/v1/tag/stream"])
def test_websocket_needs_the_token(path):
    c = guarded_client()
    assert refused(c, path) == 1008
    assert refused(c, path, {"x-luna-token": "wrong"}) == 1008
    assert refused(c, path, {"origin": "https://evil.example", "x-luna-token": TOKEN}) == 1008


def test_websocket_with_the_token_is_served(monkeypatch):
    """The backend's relay: server side, no Origin, the token header (app/listen.py, auth_headers)."""
    monkeypatch.setitem(arcmeta.STATE, "arc", None)
    monkeypatch.setitem(arcmeta.STATE, "error", "not loaded (test)")
    c = guarded_client()
    for h in ({"x-luna-token": TOKEN}, {"authorization": f"Bearer {TOKEN}"}, {"cookie": f"luna_token={TOKEN}"}):
        with c.websocket_connect("/v1/stream?ear=arc", headers=h) as ws:
            m = ws.receive_json()
            assert m["t"] == "ear" and m["available"] is False


def test_post_needs_the_token_get_health_does_not(monkeypatch):
    from app import main
    monkeypatch.setitem(main.STATE, "tagger", None)    # never call a (possibly closed) native tagger from here
    c = guarded_client()
    assert c.post("/v1/embed", json={"texts": ["x"]}).status_code == 401
    assert c.post("/v1/tag", json={"text": "x"}, headers={"x-luna-token": "nope"}).status_code == 401
    r = c.post("/v1/tag", json={"text": "x"}, headers={"x-luna-token": TOKEN})
    assert r.status_code == 503      # through the guard, to the route (no tagger loaded here)
    assert c.get("/health").status_code == 200


def test_rebinding_host_is_refused():
    c = TestClient(app, base_url="http://evil.example:47210")
    assert c.get("/health").status_code == 403


def test_host_name():
    assert host_name("127.0.0.1:47210") == "127.0.0.1"
    assert host_name("[::1]:8200") == "::1"
    assert host_name("LOCALHOST") == "localhost"
    assert host_name("evil.example:80") == "evil.example"


def test_same_file_as_the_backend():
    """One guard, two copies (the servers are separate packages in the desktop bundle): they must not drift."""
    from pathlib import Path
    here = Path(__file__).resolve().parents[1] / "app/local_guard.py"
    there = Path(__file__).resolve().parents[2] / "backend/app/local_guard.py"
    if not there.exists():
        pytest.skip("no backend checkout next to this model server")
    assert here.read_text() == there.read_text()


# ---- [#87] the decode watchdog ---------------------------------------------------------------------------------------
class HungStream:
    """An EarStream whose decode never returns (until the test lets it go)."""
    release = threading.Event()

    def __init__(self, domain="assistant", **kw):
        self.m = arcmeta.STATE["arc"]
        self.closed = False

    def feed_all(self, pcm):
        HungStream.release.wait(10)
        return []

    def close(self):
        self.closed = True


@pytest.mark.parametrize("ear", [True, False])
def test_hung_decode_is_abandoned_and_the_model_reset(monkeypatch, ear):
    model = object()
    reloads = []
    monkeypatch.setitem(arcmeta.STATE, "arc", model)
    monkeypatch.setitem(arcmeta.STATE, "error", None)
    monkeypatch.setitem(arcmeta.STATE, "sessions", 0)
    monkeypatch.setitem(arcmeta.STATE, "resets", 0)
    monkeypatch.setattr(arcmeta, "load", lambda: reloads.append(time.time()))
    monkeypatch.setattr(arc_ear, "EarStream", HungStream)
    monkeypatch.setattr(decode_watchdog.watchdog_settings, "ear_decode_timeout_s", 0.4)
    HungStream.release.clear()
    c = TestClient(app)
    t0 = time.time()
    got = []
    try:
        with c.websocket_connect("/v1/stream" + ("?ear=arc" if ear else "")) as ws:
            ws.send_bytes(bytes(3200))
            while True:
                try:
                    got.append(ws.receive_json())
                except WebSocketDisconnect:
                    break
                if got[-1]["t"] == "error":
                    break
    finally:
        HungStream.release.set()
    err = [m for m in got if m["t"] == "error"]
    assert err and err[0]["code"] == "decode_timeout" and err[0]["reset"] is True, got
    assert time.time() - t0 < 5
    assert arcmeta.STATE["arc"] is None and arcmeta.STATE["resets"] == 1
    assert "hung decode" in arcmeta.STATE["error"]
    for _ in range(50):
        if reloads:
            break
        time.sleep(0.02)
    assert reloads, "the model handle is loaded again in the background"
    assert arcmeta.STATE["sessions"] == 0          # the session slot is given back
    assert c.get("/health").json()["models"]["watchdog"]["resets"] == 1


def test_reset_only_once_per_handle(monkeypatch):
    m = object()
    monkeypatch.setitem(arcmeta.STATE, "arc", m)
    monkeypatch.setitem(arcmeta.STATE, "resets", 0)
    assert arcmeta.reset_after_hang(m, "x", reload=lambda: None) is True
    assert arcmeta.reset_after_hang(m, "x", reload=lambda: None) is False
    assert arcmeta.STATE["resets"] == 1
