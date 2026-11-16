"""Local access guard (issue #84, docs/SECURITY.md). One pure ASGI middleware, the same file in backend/app and
model_server/app (tests check they stay identical).

Both servers listen on 127.0.0.1 only, but that alone does not keep a web page out: browsers apply CORS to fetch, not to
WebSockets, so any site the kid visits could open ws://127.0.0.1:<port>/ws/listen. And any other local account could
call the API. Three checks, on every HTTP request and every WebSocket handshake:

  Host     must be a loopback name (127.0.0.1, localhost, [::1]) or one of LUNA_ALLOWED_HOSTS. Stops DNS rebinding
           (evil.example resolving to 127.0.0.1 makes the page "same-origin" with us; its Host header still says so).
  Origin   when present, must be one of the allowed origins (LUNA_ORIGINS + the backend's CORS_ORIGINS) or the
           request's own origin (http://<allowed Host>). A WebSocket from anywhere else is closed with 1008 before it
           is accepted; an HTTP request gets 403. No Origin = not a browser page (curl, the backend's own relay).
  Token    LUNA_TOKEN, a per-launch secret the desktop shell generates (desktop/main/main.js). Required on every
           WebSocket and every state-changing HTTP request (anything but GET / HEAD / OPTIONS), as the `luna_token`
           cookie (what the app page sends: the shell sets it HttpOnly + SameSite=Strict for our origin), an
           `X-Luna-Token` header, or `Authorization: Bearer <token>` (other local clients, the backend's calls to the
           model server). Unset (a bare `make backend` / `make models`, the test suites): not required; Host and
           Origin are still checked.

LUNA_DEV_COOKIE=1 (`make dev` only, never the desktop app): the server hands the token cookie to a page it serves
itself, so a normal browser on the dev setup works with the token on. The desktop app does not do this: there the
cookie comes from the shell, never from an HTTP response another local process could read.
"""
from __future__ import annotations

import hmac
import json
import os
from http.cookies import CookieError, SimpleCookie

COOKIE = "luna_token"
HEADER = "x-luna-token"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
POLICY_VIOLATION = 1008


def _split(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def host_name(host: str) -> str:
    """'127.0.0.1:8100' -> '127.0.0.1', '[::1]:8100' -> '::1', 'localhost' -> 'localhost' (lower case)."""
    h = (host or "").strip().lower()
    if h.startswith("["):
        return h[1:h.find("]")] if "]" in h else h[1:]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


class LocalGuard:
    """ASGI middleware: Host + Origin + token checks (module docstring). Lifespan and other scopes pass through."""

    def __init__(self, app, *, token: str | None = None, origins=(), allowed_hosts=(), dev_cookie: bool = False):
        self.app = app
        self.token = token or ""
        self.origins = {o.rstrip("/").lower() for o in origins if o}
        self.hosts = LOOPBACK | {h.strip().lower() for h in allowed_hosts if h}
        self.dev_cookie = bool(dev_cookie and self.token)

    # ---- the checks (pure; unit-tested) ----
    def host_ok(self, headers: dict) -> bool:
        return host_name(headers.get("host", "")) in self.hosts

    def origin_ok(self, headers: dict, scheme: str) -> bool:
        origin = headers.get("origin")
        if origin is None:
            return True
        o = origin.strip().rstrip("/").lower()
        if o in self.origins:
            return True
        host = headers.get("host", "").strip().lower()
        own = {"http": "http", "https": "https", "ws": "http", "wss": "https"}.get(scheme, "http")
        return bool(host) and host_name(host) in self.hosts and o == f"{own}://{host}"

    def token_ok(self, headers: dict) -> bool:
        if not self.token:
            return True
        got = headers.get(HEADER, "")
        auth = headers.get("authorization", "")
        if not got and auth.lower().startswith("bearer "):
            got = auth[7:].strip()
        if not got and headers.get("cookie"):
            try:
                c = SimpleCookie()
                c.load(headers["cookie"])
                got = c[COOKIE].value if COOKIE in c else ""
            except CookieError:
                got = ""
        return bool(got) and hmac.compare_digest(got.encode(), self.token.encode())

    def verdict(self, scope) -> str | None:
        """None = let it through, else why not (logged by nobody: the reason goes back in the 403 / close reason)."""
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        if not self.host_ok(headers):
            return "host not allowed"
        if not self.origin_ok(headers, scope.get("scheme", "http")):
            return "origin not allowed"
        needs_token = scope["type"] == "websocket" or scope.get("method", "GET").upper() not in SAFE_METHODS
        if needs_token and not self.token_ok(headers):
            return "missing or wrong local token"
        return None

    # ---- ASGI ----
    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        why = self.verdict(scope)
        if why and scope["type"] == "websocket":
            msg = await receive()          # websocket.connect
            if msg.get("type") == "websocket.connect":
                await send({"type": "websocket.close", "code": POLICY_VIOLATION, "reason": why})
            return
        if why:
            body = json.dumps({"detail": why}).encode()
            status = 401 if why.startswith("missing") else 403
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        if self.dev_cookie and scope["type"] == "http" and self._is_page(scope):
            return await self.app(scope, receive, self._with_cookie(send))
        return await self.app(scope, receive, send)

    @staticmethod
    def _is_page(scope) -> bool:
        if scope.get("method") != "GET":
            return False
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers") or []}
        if headers.get("sec-fetch-site", "none") not in ("none", "same-origin"):
            return False        # a page some other site opened in a frame or a new tab never gets the cookie
        p = scope.get("path", "")
        return p == "/" or p.endswith(".html")

    def _with_cookie(self, send):
        cookie = f"{COOKIE}={self.token}; Path=/; HttpOnly; SameSite=Strict".encode()

        async def wrapped(msg):
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": [*msg.get("headers", []), (b"set-cookie", cookie)]}
            await send(msg)
        return wrapped


def env_options(origins=(), env=os.environ) -> dict:
    """LocalGuard's keyword arguments from the environment: LUNA_TOKEN, LUNA_ORIGINS (+ `origins`, e.g. the backend's
    CORS_ORIGINS), LUNA_ALLOWED_HOSTS, LUNA_DEV_COOKIE. Usage: app.add_middleware(LocalGuard, **env_options())."""
    return {"token": env.get("LUNA_TOKEN", ""), "origins": [*_split(env.get("LUNA_ORIGINS")), *origins],
            "allowed_hosts": _split(env.get("LUNA_ALLOWED_HOSTS")), "dev_cookie": env.get("LUNA_DEV_COOKIE") == "1"}


def auth_headers(env=os.environ) -> dict:
    """Headers for a server-side call to the other local server (the backend -> the model server)."""
    t = env.get("LUNA_TOKEN", "")
    return {"X-Luna-Token": t} if t else {}
