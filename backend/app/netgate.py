"""School network mode: the one outbound gate of this process (docs/SCHOOL_IT.md). The same file in backend/app and
model_server/app (a test fails if the copies drift).

Outpost Luna works offline once it is set up. A few things can use the internet: NASA videos that are not saved on this
computer, downloads of the optional parts, and the update checks. With School network mode on, nothing leaves this
computer except to the hosts an IT admin allowed (none by default). Loopback (127.0.0.1, ::1, localhost) is always
allowed: that is how the app talks to itself.

Who turns it on (the strongest wins):
  machine  an IT admin, for every account on the computer. The desktop shell resolves the policy (a policy.json in the
           install folder or the machine-wide folder, or the OUTPOST_SCHOOL_NETWORK / OUTPOST_ALLOW_HOSTS variables) and
           hands it to both servers as LUNA_NET_POLICY (JSON). Without the shell (make dev) this module looks in the same
           places itself. A machine policy that turns it on is locked: the app cannot turn it off.
  user     a grown-up in Settings -> For grown-ups -> School network: <LUNA_DATA_DIR>/network.json {"school_network": true}
           (set_user()). It can turn the mode on, never add hosts.
A policy file that is there but cannot be read fails closed: the mode is on, with no hosts allowed.

Enforced in one place per process, install(), at three depths:
  1. httpx: every HTTPTransport / AsyncHTTPTransport request (each redirect hop too) -> httpx.ConnectError before any
     socket is opened, so callers see exactly what an offline computer gives them.
  2. websockets: websockets.connect to a blocked host raises ConnectionRefusedError before connecting.
  3. sockets: socket.getaddrinfo refuses blocked names, and an audit hook (sys.addaudithook, cannot be removed) refuses
     socket.connect / sendto to a non-loopback address that no allowed name resolved to: a library that skips 1 and 2
     is still stopped. mDNS / SSDP multicast is a sendto to a non-loopback address, so it is refused too.
And always, school network or not: a listening socket may only bind a loopback address (LUNA_ALLOW_LAN_BIND=1 lifts
that for a developer who really means it). The servers never listen on the network.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

LOG = logging.getLogger("netgate")
LOOPBACK_NAMES = frozenset({"localhost", "localhost.", "ip6-localhost"})
USER_FILE_NAME = "network.json"
CHECK_EVERY_S = 1.0


class Blocked(ConnectionRefusedError):
    """Raised instead of opening a connection School network mode does not allow."""

    def __init__(self, host: str):
        super().__init__(f"School network mode: {host} is not on the allow list")
        self.host = host


# ---------------------------------------------------------------- policy ---------------------------------------------
def machine_paths(platform: str = sys.platform, env=os.environ) -> list[Path]:
    """Where an IT admin puts policy.json, in the order they are read (docs/SCHOOL_IT.md)."""
    out = []
    if env.get("OUTPOST_POLICY_FILE"):
        out.append(Path(env["OUTPOST_POLICY_FILE"]))
    if env.get("OUTPOST_POLICY_SEARCH") == "0":   # the test suites: never the developer's machine policy
        return out
    if platform == "darwin":
        out.append(Path("/Library/Application Support/Outpost Luna/policy.json"))
    elif platform == "win32":
        out.append(Path(env.get("ProgramData") or env.get("PROGRAMDATA") or r"C:\ProgramData") / "Outpost Luna" / "policy.json")
    else:
        out.append(Path("/etc/outpost-luna/policy.json"))
    return out


def _hosts(v) -> list[str]:
    if isinstance(v, str):
        v = v.split(",")
    out = []
    for h in v if isinstance(v, (list, tuple)) else []:
        h = str(h).strip().lower().rstrip(".")
        if h.startswith("*."):
            h = h[2:]
        h = h.lstrip(".")
        if h and h not in out and all(c.isalnum() or c in "-.:" for c in h):
            out.append(h)
    return out


def _on(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def read_machine(platform: str = sys.platform, env=os.environ) -> dict:
    """The machine policy -> {school_network, allow_hosts, open_links, source}. LUNA_NET_POLICY (from the shell) wins."""
    if env.get("LUNA_NET_POLICY"):
        try:
            p = json.loads(env["LUNA_NET_POLICY"])
            return {"school_network": bool(p.get("school_network")), "allow_hosts": _hosts(p.get("allow_hosts", [])),
                    "open_links": p.get("open_links", True) is not False, "source": str(p.get("source") or "shell")}
        except (ValueError, AttributeError):
            return {"school_network": True, "allow_hosts": [], "open_links": False, "source": "LUNA_NET_POLICY unreadable"}
    pol = {"school_network": False, "allow_hosts": [], "open_links": True, "source": ""}
    for f in machine_paths(platform, env):
        if not f.is_file():
            continue
        try:
            p = json.loads(f.read_text(encoding="utf-8-sig"))
            if not isinstance(p, dict):
                raise ValueError("not an object")
        except (OSError, ValueError):
            pol = {"school_network": True, "allow_hosts": [], "open_links": False, "source": f"{f} (unreadable: on, nothing allowed)"}
            break
        pol = {"school_network": p.get("school_network", True) is not False, "allow_hosts": _hosts(p.get("allow_hosts", [])),
               "open_links": p.get("open_links", True) is not False, "source": str(f)}
        break
    if _on(env.get("OUTPOST_SCHOOL_NETWORK", "")):
        pol["school_network"] = True
        pol["source"] = pol["source"] or "OUTPOST_SCHOOL_NETWORK"
    if env.get("OUTPOST_ALLOW_HOSTS"):
        pol["allow_hosts"] = _hosts(pol["allow_hosts"] + _hosts(env["OUTPOST_ALLOW_HOSTS"]))
    return pol


_user_file: list = []


def user_file() -> Path | None:
    """<LUNA_DATA_DIR>/network.json (the desktop app's per-user folder), or the one set_user_file() named (make dev)."""
    if _user_file:
        return _user_file[0]
    d = os.environ.get("LUNA_DATA_DIR")
    return Path(d) / USER_FILE_NAME if d else None


def set_user_file(path: Path | None) -> None:
    _user_file[:] = [Path(path)] if path else []
    _cache["at"] = 0.0


def read_user(path: Path | None = None) -> bool:
    f = path or user_file()
    if not f:
        return False
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("school_network") is True
    except (OSError, ValueError, AttributeError):
        return False


def set_user(on: bool, path: Path | None = None) -> None:
    """Settings -> School network: write the per-user choice (atomic)."""
    f = path or user_file()
    if not f:
        raise RuntimeError("no place to keep the setting (LUNA_DATA_DIR unset)")
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({"school_network": bool(on), "changed_at": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
    os.replace(tmp, f)
    _cache["at"] = 0.0


def effective(machine: dict, user_on: bool) -> dict:
    on = bool(machine.get("school_network")) or bool(user_on)
    return {"school_network": on, "locked": bool(machine.get("school_network")),
            "allow_hosts": list(machine.get("allow_hosts") or []) if on else [],
            "open_links": machine.get("open_links", True) is not False,
            "source": "machine" if machine.get("school_network") else "user" if user_on else "off",
            "machine_source": machine.get("source") or ""}


_cache: dict = {"at": 0.0, "pol": None, "machine": None}
_lock = threading.Lock()


def policy() -> dict:
    """The policy now (re-read at most once a second, so a change in Settings applies at once in every process)."""
    now = time.monotonic()
    if _cache["pol"] is not None and now - _cache["at"] < CHECK_EVERY_S:
        return _cache["pol"]
    with _lock:
        if _cache["machine"] is None or now - _cache["at"] >= 30.0:
            _cache["machine"] = read_machine()
        _cache["pol"] = effective(_cache["machine"], read_user())
        _cache["at"] = now
        return _cache["pol"]


def reset_cache() -> None:
    _cache.update(at=0.0, pol=None, machine=None)


# ---------------------------------------------------------------- the checks (pure) ----------------------------------
def is_loopback(host: str) -> bool:
    h = (host or "").strip().lower().strip("[]")
    if h in LOOPBACK_NAMES or h.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(h.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def host_matches(host: str, allow) -> bool:
    h = (host or "").strip().lower().strip("[]").rstrip(".")
    return any(h == a or h.endswith("." + a) for a in allow or ())


def host_allowed(host: str, pol: dict | None = None) -> bool:
    pol = pol if pol is not None else policy()
    if not pol["school_network"] or is_loopback(host):
        return True
    return host_matches(host, pol["allow_hosts"])


def url_host(url: str) -> str:
    try:
        return (urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def url_allowed(url: str, pol: dict | None = None) -> bool:
    return host_allowed(url_host(url), pol)


_told: set = set()


def _tell(host: str, how: str) -> None:
    if host not in _told and len(_told) < 200:
        _told.add(host)
        LOG.warning("school network: blocked %s (%s)", host, how)


def check_url(url: str) -> None:
    """Raise Blocked when School network mode does not allow this URL's host."""
    h = url_host(url)
    if not host_allowed(h):
        _tell(h, "request")
        raise Blocked(h)


def enforcing() -> bool:
    return policy()["school_network"]


# ---------------------------------------------------------------- install --------------------------------------------
_resolved: set = set()      # addresses an allowed name resolved to (the socket backstop lets these through)
_state = {"installed": False}


def _ip(host) -> str | None:
    try:
        return str(ipaddress.ip_address(str(host).split("%", 1)[0].strip("[]")))
    except ValueError:
        return None


def _addr_allowed(host) -> bool:
    """socket.connect / sendto target: loopback, an allowed name, or an address an allowed name resolved to."""
    pol = policy()
    if not pol["school_network"]:
        return True
    if is_loopback(str(host)):
        return True
    ip = _ip(host)
    if ip is None:
        return host_matches(str(host), pol["allow_hosts"])
    return ip in _resolved or host_matches(ip, pol["allow_hosts"])


def _audit(event: str, args) -> None:
    if not event.startswith("socket."):
        return
    if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
        addr = args[1] if len(args) > 1 else None
        if isinstance(addr, tuple) and addr and not _addr_allowed(addr[0]):
            _tell(str(addr[0]), event)
            raise Blocked(str(addr[0]))
    elif event == "socket.bind":
        addr = args[1] if len(args) > 1 else None
        if (isinstance(addr, tuple) and len(addr) >= 2 and addr[1] and not is_loopback(str(addr[0]))
                and os.environ.get("LUNA_ALLOW_LAN_BIND") != "1"):
            LOG.error("refused to listen on %s:%s: Outpost Luna listens on loopback only", addr[0], addr[1])
            raise PermissionError(f"Outpost Luna listens on loopback only, not {addr[0]}:{addr[1]}")


def install() -> None:
    """Put the gate in front of every outbound path of this process. Idempotent; call it before serving."""
    if _state["installed"]:
        return
    _state["installed"] = True

    real_gai = socket.getaddrinfo

    def getaddrinfo(host, *a, **k):
        h = host.decode() if isinstance(host, bytes) else (host or "")
        if h and not host_allowed(h):
            _tell(h, "lookup")
            raise socket.gaierror(socket.EAI_NONAME, f"School network mode: {h} is not on the allow list")
        res = real_gai(host, *a, **k)
        if h and enforcing() and not is_loopback(h):
            for r in res:
                with _lock:
                    if len(_resolved) < 4096:
                        _resolved.add(_ip(r[4][0]) or r[4][0])
        return res

    getaddrinfo.__wrapped__ = real_gai   # type: ignore[attr-defined]
    socket.getaddrinfo = getaddrinfo
    sys.addaudithook(_audit)

    try:
        import httpx

        class BlockedConnect(httpx.ConnectError):
            pass

        def guard(request):
            h = (request.url.host or "").lower()
            if not host_allowed(h):
                _tell(h, "request")
                raise BlockedConnect(f"School network mode: {h} is not on the allow list", request=request)

        sync_send = httpx.HTTPTransport.handle_request
        async_send = httpx.AsyncHTTPTransport.handle_async_request

        def handle_request(self, request):
            guard(request)
            return sync_send(self, request)

        async def handle_async_request(self, request):
            guard(request)
            return await async_send(self, request)

        httpx.HTTPTransport.handle_request = handle_request
        httpx.AsyncHTTPTransport.handle_async_request = handle_async_request
    except ImportError:
        pass

    try:
        from websockets.asyncio import client as wsc
        real_init = wsc.connect.__init__

        def init(self, uri, *a, **k):
            check_url(uri)
            real_init(self, uri, *a, **k)

        wsc.connect.__init__ = init
    except ImportError:
        pass
