"""School network mode (app/netgate.py, docs/SCHOOL_IT.md): the policy, the outbound gate, loopback-only listening.

"A blocked request never leaves" is checked with our own audit hook: it records every socket.connect / sendto to a
non-loopback address the process attempts. The gate raises before any of them happens.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import socket
import sys
import threading
from pathlib import Path

import httpx
import pytest

from app import netgate

ROOT = Path(__file__).resolve().parents[2]
_SEEN: list = []
_REC = {"on": False}


def _recorder(event, args):
    if _REC["on"] and event in ("socket.connect", "socket.sendto") and len(args) > 1 and isinstance(args[1], tuple):
        if not netgate.is_loopback(str(args[1][0])):
            _SEEN.append((event, args[1][0]))


sys.addaudithook(_recorder)   # added before the gate's own hook in this test: it sees every attempt


@pytest.fixture
def school(monkeypatch, tmp_path):
    """School network on (machine policy, no hosts allowed); the user file in a temp folder."""
    netgate.install()
    netgate.set_user_file(tmp_path / "network.json")
    monkeypatch.setenv("LUNA_NET_POLICY", json.dumps({"school_network": True, "allow_hosts": [], "source": "test"}))
    netgate.reset_cache()
    _SEEN.clear()
    _REC["on"] = True
    yield
    _REC["on"] = False
    monkeypatch.delenv("LUNA_NET_POLICY")
    netgate.reset_cache()
    netgate.set_user_file(None)


@pytest.fixture
def off(monkeypatch, tmp_path):
    netgate.install()
    netgate.set_user_file(tmp_path / "network.json")
    monkeypatch.delenv("LUNA_NET_POLICY", raising=False)
    netgate.reset_cache()
    yield tmp_path / "network.json"
    netgate.reset_cache()
    netgate.set_user_file(None)


def test_the_two_copies_match():
    assert (ROOT / "backend/app/netgate.py").read_bytes() == (ROOT / "model_server/app/netgate.py").read_bytes()


# ---------------------------------------------------------------- policy ---------------------------------------------
def test_machine_policy_file_env_and_fail_closed(tmp_path):
    f = tmp_path / "policy.json"
    env = {"OUTPOST_POLICY_FILE": str(f), "OUTPOST_POLICY_SEARCH": "0"}
    assert netgate.read_machine("darwin", env)["school_network"] is False            # no file: off
    f.write_text(json.dumps({"school_network": True, "allow_hosts": ["*.NASA.gov", "bad host!", "github.io."]}))
    p = netgate.read_machine("darwin", env)
    assert p["school_network"] is True and p["allow_hosts"] == ["nasa.gov", "github.io"] and p["source"] == str(f)
    f.write_text("{ not json")                                                         # a typo never opens the network
    p = netgate.read_machine("darwin", env)
    assert p["school_network"] is True and p["allow_hosts"] == [] and "unreadable" in p["source"]
    f.unlink()
    p = netgate.read_machine("win32", {**env, "OUTPOST_SCHOOL_NETWORK": "1", "OUTPOST_ALLOW_HOSTS": "example.org"})
    assert p["school_network"] is True and p["allow_hosts"] == ["example.org"]
    # the shell's resolved policy wins over everything else
    p = netgate.read_machine("darwin", {"LUNA_NET_POLICY": json.dumps({"school_network": False}), "OUTPOST_SCHOOL_NETWORK": "1"})
    assert p["school_network"] is False


def test_machine_paths_per_os():
    assert str(netgate.machine_paths("darwin", {})[0]) == "/Library/Application Support/Outpost Luna/policy.json"
    w = netgate.machine_paths("win32", {"ProgramData": r"C:\ProgramData"})[0]
    assert str(w).replace("\\", "/").endswith("ProgramData/Outpost Luna/policy.json")
    assert netgate.machine_paths("darwin", {"OUTPOST_POLICY_SEARCH": "0"}) == []


def test_effective_locked_and_user():
    m_on = {"school_network": True, "allow_hosts": ["nasa.gov"]}
    m_off = {"school_network": False, "allow_hosts": ["nasa.gov"]}
    e = netgate.effective(m_on, False)
    assert e["school_network"] and e["locked"] and e["source"] == "machine" and e["allow_hosts"] == ["nasa.gov"]
    e = netgate.effective(m_off, True)
    assert e["school_network"] and not e["locked"] and e["source"] == "user"
    assert netgate.effective(m_off, False)["school_network"] is False


def test_host_matching():
    pol = {"school_network": True, "allow_hosts": ["nasa.gov"]}
    assert netgate.host_allowed("images-api.nasa.gov", pol) and netgate.host_allowed("nasa.gov", pol)
    assert not netgate.host_allowed("evilnasa.gov", pol) and not netgate.host_allowed("nasa.gov.evil.example", pol)
    for h in ("127.0.0.1", "localhost", "::1", "[::1]", "127.8.9.10"):
        assert netgate.host_allowed(h, pol)
    assert netgate.host_allowed("example.org", {"school_network": False, "allow_hosts": []})


# ---------------------------------------------------------------- the gate -------------------------------------------
def test_httpx_blocked_before_any_socket(school):
    # BlockedConnect comes from the transport guard: raised before name lookup, before any socket exists
    with pytest.raises(httpx.ConnectError, match="School network") as e:
        httpx.get("https://images-api.nasa.gov/", timeout=2)
    assert type(e.value).__name__ == "BlockedConnect"
    with pytest.raises(httpx.ConnectError, match="School network") as e:
        with httpx.Client(follow_redirects=True) as c:
            c.head("http://example.org/")
    assert type(e.value).__name__ == "BlockedConnect"

    async def a():
        async with httpx.AsyncClient() as c:
            await c.get("https://api.github.com/repos/WhissleAI/Outpost-Luna/releases/latest")
    with pytest.raises(httpx.ConnectError, match="School network") as e:
        asyncio.run(a())
    assert type(e.value).__name__ == "BlockedConnect"
    assert _SEEN == []


def test_socket_backstop(school):
    # a library that skips httpx: the name lookup is refused, and so is a connect / sendto to a bare address (the gate's
    # audit hook raises Blocked before the system call: a real attempt would time out or fail differently)
    with pytest.raises(socket.gaierror, match="School network"):
        socket.getaddrinfo("example.org", 443)
    with pytest.raises(socket.gaierror, match="School network"):
        socket.create_connection(("93.184.215.14", 80), timeout=1)
    t = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        t.settimeout(1)
        with pytest.raises(netgate.Blocked):
            t.connect(("93.184.215.14", 80))
    finally:
        t.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(netgate.Blocked):     # mDNS / Bonjour: multicast to 224.0.0.251:5353
            s.sendto(b"\0" * 12, ("224.0.0.251", 5353))
        with pytest.raises(netgate.Blocked):     # SSDP / UPnP discovery
            s.sendto(b"M-SEARCH * HTTP/1.1\r\n\r\n", ("239.255.255.250", 1900))
    finally:
        s.close()


def test_websockets_blocked(school):
    import websockets
    with pytest.raises(ConnectionRefusedError, match="School network"):
        websockets.connect("wss://api.deepgram.com/v2/listen")


def test_loopback_still_works(school):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        assert httpx.get(f"http://127.0.0.1:{srv.server_address[1]}/", timeout=5).status_code in (200, 404)
    finally:
        srv.shutdown()
        srv.server_close()
    assert _SEEN == []


def test_off_does_not_stand_in_the_way(off):
    assert netgate.host_allowed("example.org") and netgate._addr_allowed("93.184.215.14")
    netgate.check_url("https://example.org/")   # no raise


def test_user_toggle_applies_without_restart(off):
    assert not netgate.enforcing()
    netgate.set_user(True)
    assert netgate.enforcing() and json.loads(off.read_text())["school_network"] is True
    with pytest.raises(netgate.Blocked):
        netgate.check_url("https://example.org/")
    netgate.set_user(False)
    assert not netgate.enforcing()


def test_listening_on_the_network_is_refused():
    netgate.install()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(PermissionError, match="loopback only"):
            s.bind(("0.0.0.0", _free_port()))
    finally:
        s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))   # loopback: fine
    finally:
        s.close()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------------------------------------------------------- the API + what uses the internet -------------------
def test_api_get_and_set(off):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    r = c.get("/api/network").json()
    assert r["school_network"] is False and r["off"] == [] and r["locked"] is False
    r = c.post("/api/network", json={"school_network": True}).json()
    assert r["school_network"] is True and r["source"] == "user" and set(r["off"]) == {"videos", "downloads", "updates"}
    assert c.post("/api/network", json={"school_network": False}).json()["school_network"] is False


def test_api_locked_by_machine_policy(school):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/api/network").json()["locked"] is True
    assert c.post("/api/network", json={"school_network": False}).status_code == 409


def test_video_probe_not_even_tried(school, monkeypatch):
    from app import video
    called = []
    monkeypatch.setattr(video.httpx, "head", lambda *a, **k: called.append(a))
    video._probe.clear()
    assert video.online("nasa") is False and video.online("youtube") is False
    assert called == []
