"""[#84] Every backend WebSocket and state-changing route refuses a hostile Origin and a missing / wrong per-launch
token (app/local_guard.py); the app's own page (the token cookie, its own origin) still gets through."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import local_guard
from app.local_guard import LocalGuard, auth_headers, env_options
from app.main import app

TOKEN = "per-launch-test-token"
WS = ["/ws/session", "/ws/listen", "/ws/mission/m1"]
OWN = "http://127.0.0.1:47310"


def guarded(**kw):
    """The backend as the desktop app runs it: a token, its own origin, Host 127.0.0.1:47310."""
    return TestClient(LocalGuard(app, token=TOKEN, origins=[OWN], **kw), base_url=OWN)


def ws_url(client, path):
    """TestClient.websocket_connect uses Host: testserver for a bare path; the client's own host instead."""
    return str(client.base_url).replace("http", "ws", 1).rstrip("/") + path


def code_of(client, path, headers=None):
    """1008 when refused before accept, else None (the socket opened)."""
    try:
        with client.websocket_connect(ws_url(client, path), headers=headers or {}):
            return None
    except WebSocketDisconnect as e:
        return e.code


@pytest.mark.parametrize("path", WS)
def test_hostile_origin_websocket_is_refused(path):
    c = TestClient(app)   # the suite's app: no token, Origin + Host still checked
    assert code_of(c, path, {"origin": "https://evil.example"}) == 1008
    assert code_of(c, path, {"origin": "http://127.0.0.1.evil.example"}) == 1008
    assert code_of(c, path, {"origin": "null"}) == 1008


@pytest.mark.parametrize("path", WS)
def test_hostile_origin_refused_even_with_the_token(path):
    c = guarded()
    assert code_of(c, path, {"origin": "https://evil.example", "cookie": f"luna_token={TOKEN}"}) == 1008


@pytest.mark.parametrize("path", WS)
def test_missing_or_wrong_token_is_refused(path):
    c = guarded()
    assert code_of(c, path, {"origin": OWN}) == 1008
    assert code_of(c, path, {"origin": OWN, "cookie": "luna_token=wrong"}) == 1008
    assert code_of(c, path, {"origin": OWN, "x-luna-token": TOKEN[:-1]}) == 1008


def test_the_app_page_gets_through():
    """The page's own origin + the cookie the desktop shell set: the session socket opens and answers."""
    c = guarded()
    with c.websocket_connect(ws_url(c, "/ws/session"), headers={"origin": OWN, "cookie": f"luna_token={TOKEN}"}) as ws:
        ws.send_json({"t": "hello"})
    with c.websocket_connect(ws_url(c, "/ws/session"), headers={"cookie": f"other=1; luna_token={TOKEN}"}):
        pass


def test_dev_origin_is_allowed():
    c = TestClient(LocalGuard(app, token=TOKEN, origins=["http://localhost:5173"]), base_url="http://127.0.0.1:8100")
    with c.websocket_connect(ws_url(c, "/ws/session"), headers={"origin": "http://localhost:5173", "cookie": f"luna_token={TOKEN}"}):
        pass
    # Vite on another port proxies with Host = the page's own host: same-origin, allowed
    c2 = TestClient(LocalGuard(app, token=TOKEN), base_url="http://localhost:5205")
    with c2.websocket_connect(ws_url(c2, "/ws/session"), headers={"origin": "http://localhost:5205", "cookie": f"luna_token={TOKEN}"}):
        pass


def test_state_changing_http_needs_the_token():
    with guarded() as c:
        _http_checks(c)


def _http_checks(c):
    assert c.post("/api/ask", json={"text": "hi"}).status_code == 401
    assert c.post("/api/ask", json={"text": "hi"}, headers={"x-luna-token": "nope"}).status_code == 401
    assert c.delete("/api/turnlog").status_code == 401
    assert c.post("/api/ask", json={"text": "hi"}, headers={"origin": "https://evil.example",
                                                           "cookie": f"luna_token={TOKEN}"}).status_code == 403
    r = c.post("/api/ask", json={"text": "hi"}, headers={"cookie": f"luna_token={TOKEN}"})
    assert r.status_code not in (401, 403)
    r = c.post("/api/ask", json={"text": "hi"}, headers={"authorization": f"Bearer {TOKEN}"})
    assert r.status_code not in (401, 403)


def test_reads_stay_open_on_loopback_but_not_for_a_rebound_host():
    with guarded() as c:
        assert c.get("/api/places").status_code == 200
    rebound = TestClient(LocalGuard(app, token=TOKEN), base_url="http://evil.example:47310")
    assert rebound.get("/api/places").status_code == 403
    assert code_of(rebound, "/ws/session", {"origin": "http://evil.example:47310", "cookie": f"luna_token={TOKEN}"}) == 1008


def test_no_token_configured_is_open_for_loopback():
    c = TestClient(LocalGuard(app, token=""), base_url="http://127.0.0.1:8100")
    with c.websocket_connect(ws_url(c, "/ws/session")):
        pass


def _page_app(dev_cookie):
    a = FastAPI()

    @a.get("/")
    def index():
        return HTMLResponse("<html></html>")

    @a.get("/api/x")
    def x():
        return {"ok": True}
    return TestClient(LocalGuard(a, token=TOKEN, dev_cookie=dev_cookie), base_url="http://127.0.0.1:8100")


def test_dev_cookie_only_for_our_own_page():
    c = _page_app(True)
    r = c.get("/", headers={"sec-fetch-site": "none"})
    assert f"luna_token={TOKEN}" in r.headers.get("set-cookie", "")
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=Strict" in r.headers["set-cookie"]
    assert "set-cookie" not in c.get("/", headers={"sec-fetch-site": "cross-site"}).headers
    assert "set-cookie" not in c.get("/api/x").headers
    assert "set-cookie" not in _page_app(False).get("/").headers   # the desktop app: the shell sets the cookie


def test_env_options_and_auth_headers():
    o = env_options(["http://127.0.0.1:47310"], env={"LUNA_TOKEN": "abc", "LUNA_ORIGINS": "http://a, http://b",
                                                    "LUNA_ALLOWED_HOSTS": "testserver", "LUNA_DEV_COOKIE": "1"})
    assert o == {"token": "abc", "origins": ["http://a", "http://b", "http://127.0.0.1:47310"],
                 "allowed_hosts": ["testserver"], "dev_cookie": True}
    assert auth_headers({"LUNA_TOKEN": "abc"}) == {"X-Luna-Token": "abc"}
    assert auth_headers({}) == {}


def test_relay_sends_the_token_to_the_model_server(monkeypatch):
    """The backend's /ws/listen opens the model server's Arc ear server side: no Origin, the token header."""
    import asyncio

    from app import listen
    seen = {}

    async def fake_connect(url, **kw):
        seen.update(kw)
        raise OSError("no model server in this test")
    monkeypatch.setenv("LUNA_TOKEN", "relay-token")
    monkeypatch.setattr(listen.websockets, "connect", fake_connect)
    conn, why = asyncio.run(listen.open_arc_ear())
    assert conn is None and "unreachable" in why
    assert seen["additional_headers"] == {"X-Luna-Token": "relay-token"}
    assert local_guard.COOKIE == "luna_token"
