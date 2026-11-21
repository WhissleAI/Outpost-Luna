# Local access: who may talk to the engine

Outpost Luna runs two local servers: the backend (the page, the API, `/ws/listen`, `/ws/session`, `/ws/mission/{id}`)
and the model server (`/v1/*`, `/v1/stream`, `/v1/tag/stream`). Binding them to `127.0.0.1` keeps the network out,
but not the web pages the kid opens in a browser: browsers apply CORS to `fetch`, **not to WebSockets**, so any site
could open `ws://127.0.0.1:47310/ws/listen`. Nor other accounts on the same computer. Issues #84 and #88.

## The rules (`backend/app/local_guard.py` = `model_server/app/local_guard.py`)

One ASGI middleware, the same file in both servers (a test fails if the copies drift). On every HTTP request and every
WebSocket handshake:

| Check | Passes | Otherwise |
|---|---|---|
| Bind | `uvicorn --host 127.0.0.1` (`desktop/runtime/launch.py`, the Makefile, `Procfile.dev`) | not reachable off the machine |
| Host | `127.0.0.1`, `localhost`, `[::1]` (any port), or `LUNA_ALLOWED_HOSTS` | 403 / WebSocket closed 1008. Stops DNS rebinding |
| Origin | absent (not a browser page), one of `LUNA_ORIGINS` + the backend's `CORS_ORIGINS` (dev: `http://localhost:5173`), or the request's own origin (`http://<Host>`) | 403 / WebSocket closed **1008 before it is accepted** |
| Token | every WebSocket and every non-GET/HEAD/OPTIONS request carries `LUNA_TOKEN` as the `luna_token` cookie, an `X-Luna-Token` header, or `Authorization: Bearer` | 401 / WebSocket closed 1008 |

Reads (`GET`) stay open to loopback without the token, except the metrics (`/metrics`, `/api/metrics`), the
learning view (`/api/learn`) and the diagnostics contents, which need it like a POST (`docs/DIAGNOSTICS.md`): the page's `<audio>`, `<video>` and images, and `GET /health`
in a browser. Cross-origin pages cannot read them (CORS) and a rebinding page fails the Host check.
With no `LUNA_TOKEN` set (a bare `make backend` / `make models`, the pipelines, the test suites) the token is not
required; Host and Origin still are.

## Where the token comes from

- **Desktop app.** `desktop/main/main.js` makes a new 32-byte random token at every launch (`engine.js newToken`) and
  passes it to both children as `LUNA_TOKEN`. The page gets it as a cookie the shell sets on its own origin before
  loading it: `luna_token`, `HttpOnly` (page scripts never see it), `SameSite=Strict` (no other site's request carries
  it). The browser attaches it to every `fetch` and WebSocket from the page, so the frontend has no token code at all.
  No server ever hands the token out in this mode. The shell's own calls (health checks, reset confirm) send the header.
- **Backend → model server.** Server side, no Origin: `X-Luna-Token` on every call (`local_guard.auth_headers()`:
  `models_client`, `tts.py`, `voices.py`, and the `/ws/listen` relay's `websockets.connect`).
- **`make dev`.** The Makefile makes one token per run (or uses `LUNA_TOKEN` from the shell) and sets
  `LUNA_DEV_COOKIE=1`. The Vite dev server (`frontend/vite.config.js`) and the backend serving a page itself set the
  same cookie on the page, so a normal browser works with the token on. Never set `LUNA_DEV_COOKIE` in the app.
  The Vite proxy keeps the page's own Host (`changeOrigin: false`), so the page's Origin is same-origin for the
  backend on any Vite port (the e2e suites use 5205, 5297, ...).
- **Tests.** `backend/tests` and `model_server/tests` run without a token (`conftest.py` allows `Host: testserver`);
  `test_local_guard.py` in each wraps the app in a guard with a token and checks hostile origins, missing and wrong
  tokens, the cookie, the header, the dev cookie, and rebinding.

## `engine.json`: finding the running engine (#88)

Written by the desktop shell once both children are healthy, removed when it quits (a crash leaves a stale one: check
`pid` or call `/health`). One per user, readable by that user only.

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Outpost Luna/engine.json` (mode 0600) |
| Windows | `%APPDATA%\Outpost Luna\engine.json` (the per-user profile's ACL; no chmod on Windows) |
| Linux | `~/.config/Outpost Luna/engine.json` (0600) |

```json
{
 "format": 1,
 "backend": "http://127.0.0.1:47310",
 "model_server": "http://127.0.0.1:47210",
 "token": "<43 URL-safe characters, new every launch>",
 "pid": 12345,
 "version": "0.3.3",
 "started_at": "2026-11-16T18:00:00.000Z"
}
```

A local client reads it, then calls the API with `X-Luna-Token: <token>` (or `Authorization: Bearer <token>`) and no
Origin header. `desktop/scripts/smoke.py` does exactly that. `pid` is the Electron main process. The ports are the
ones this launch picked: usually 47310 / 47210, but never assume them (`docs/DESKTOP.md` "Process supervision").

## Logs, metrics and the diagnostics file (#92)

Local only, never uploaded, and never holding audio, transcripts, names or the token: the structured logs are scrubbed
when written, the metrics endpoints need the token, and the diagnostics file (Settings → Help & diagnostics) is a zip the
user saves where they choose, with `engine.json` minus its token. Details: [`docs/DIAGNOSTICS.md`](DIAGNOSTICS.md).

## On-device learning

`GET /api/learn` (the Settings view) needs the token like the diagnostics contents (the learned names are the
kid's words); `POST /api/learn/reset` and `/api/learn/forget` need
the token and the page's `X-Outpost-Reset: 1` header. What is stored, and where: `docs/ON_DEVICE_LEARNING.md` (one small
JSON per cadet and one per computer, 0600, no audio, no transcripts).

## Retention: what we keep about a child, for how long, and how it is destroyed

This is the app's written data-retention policy. It covers everything Outpost Luna keeps on the computer about a child
(per cadet profile). Nothing in it is sent to Whissle or anyone else; there are no accounts and no server copy.

**Policy.**

1. **Keep only what a feature needs, only on this computer.** Words a child said are kept only in the redacted turn
   log (below), never in the Brain, the safety ledger, logs, metrics or the diagnostics file.
2. **Every behaviour and safety record expires on a clock, not only a size cap.** The turn log keeps 30 days
   (`backend/app/turnlog.py` `RETAIN_DAYS`; lines older than that are dropped once a day, Playtest clips too); the
   safety ledger keeps care entries 30 days and every other kind 60 days (`backend/app/safety_ledger.py`); the Brain's
   practice days keep 60 (`frontend/src/brain_store.js` `MAX_DAYS`).
3. **A grown-up can destroy it all at once, at any time.** Settings → For grown-ups → Reset Outpost Luna ("Start
   over" deletes the turn log, Playtest audio, the safety ledger, on-device learning and the spoken-line cache; "Erase
   progress too" also deletes lesson progress and the Brain's practice counts; "Reset everything" also deletes the
   downloads). The desktop shell deletes the folders after stopping the engine (`desktop/main/reset.js`), so no file
   survives on Windows because it was open. "Delete what's saved" (Voice log and playtest) deletes the turn log alone.
   Uninstall + deleting the user folder (`docs/SCHOOL_IT.md` "Uninstall cleanly") removes everything.
4. **Destruction is deletion of the file**, not a flag. There is no backup, cloud copy or recycle step inside the app.
   (An OS-level backup a family or school runs, such as Time Machine or a disk image, is outside the app.)
5. **Exports are a grown-up's explicit act.** A Playtest export (turn log + audio) is a zip a grown-up saves where
   they choose; the safety ledger is never in it. A diagnostics file never holds words or audio.

**Per-data-element table** (what, purpose, where, retention, how deleted): `docs/SCHOOL_IT.md` "Data we keep about a
child". That table is the plain-language disclosure for schools (for example under Colorado's Student Data Transparency
and Security Act, C.R.S. 22-16-101 et seq.).

**Security program for this data** (the amended COPPA rule's written-program requirement, compliance date 2026-04-22):
the data never leaves the device (loopback-only servers, the `LocalGuard` Host / Origin / token checks above, no
accounts); the files that hold a child's data are in the per-user folder, and the learning and safety files are mode
0600 on macOS (Windows: the user's own `%APPDATA%` ACLs); every API that returns per-child counts needs the per-launch
token (`diag.authorized`: `/api/brain/summary`, `/api/safety/flags`, `/api/learn`); words are redacted before they are
written and private turns are stored as `<private>`; tests assert that no words, names or call signs reach the Brain
or the ledger (`backend/tests/test_brain.py`, `backend/tests/test_brain_signals.py`). Who reviews it, how often, and
the vendor list (none receive child data today) are for the owner and counsel to fill in.

**Open for legal review.**
- The Playtest export's consent wording ("I'm the parent or guardian, or I have their permission.",
  `frontend/src/playtest_ui.js`) and whether a school setting needs a different consent path before audio is recorded
  and exported. Behaviour is unchanged in this release, apart from keeping the safety ledger out of the export.
- Whether the turn log should stay on by default (`frontend/src/prefs.js` `improve: true`) for school installs.
- Lesson progress and practice counts (not the dated behaviour records) are kept until a grown-up erases them, like a
  gradebook. Whether a school needs an automatic end-of-year destruction date for these.
- The US-centric help line in the care banner (988).

## Check for updates

The one request the app makes to the internet on its own behalf after setup, and only when asked (Settings → App
version → Check for updates) or, if a grown-up opted in, once a day on launch: the **main process** (never the page,
which stays locked to its origin) GETs GitHub's latest-release API with no auth and no user data. The page can only ask
for a check or name what to open (`download` / `release` / `site`); the URL comes from the main process's own result
and must be https on `github.com/WhissleAI/Outpost-Luna` or `whissleai.github.io/Outpost-Luna` before
`shell.openExternal`. Nothing is installed. Details: [`docs/DESKTOP.md`](DESKTOP.md) "App updates".

## The desktop shell: hardening in one place (`desktop/main/hardening.js`)

| What | How | Test |
|---|---|---|
| Every window | `WEB_PREFS`: `sandbox`, `contextIsolation`, no `nodeIntegration` (page, workers, subframes), no `<webview>`, no spell-check (Windows would download dictionaries from Google), `webSecurity` on. No remote module anywhere. `web-contents-created` refuses `<webview>` and new windows for every web contents | `hardening.test.js` reads `main.js` and `gate.js`: every `webPreferences` is `...WEB_PREFS` |
| The page's CSP | added by the session to every response from our origin (`permissions.js`, replacing any the server sent): scripts from our origin only (+ `'wasm-unsafe-eval'` for the gesture models), no inline script (the theme scripts are files: `frontend/public/theme-*.js`), frames only `https://www.youtube-nocookie.com`, connections only to our origin, `object-src 'none'`, `frame-ancestors 'none'` | `hardening.test.js`, `permissions.test.js` |
| Navigation and new windows | `navigation()`: our origin stays; a YouTube link goes behind the grown-up gate; another link opens in the system browser only when `linkAllowed()` (the science and NASA sites the app cites; our repo and site over https); anything else (another loopback port, `file:`, a custom scheme, an unknown host) is refused and logged. The window is never replaced or opened | `hardening.test.js` |
| Devices on the network | Chromium's media router (Cast / DIAL discovery over mDNS and SSDP) is off by switch | `hardening.test.js` |
| Listening | both servers on `127.0.0.1` (`launch.py HOST`); `app/netgate.py` refuses any listening socket on a non-loopback address in either server | `test_loopback_only.py` (backend and model server, started exactly as the app starts them: not reachable on this computer's network address; `lsof` shows `127.0.0.1` only), `test_school_network.py` |

## School network mode (`docs/SCHOOL_IT.md`)

No outbound connection except to an IT admin's allow list (none by default). Turned on by a machine policy (a
`policy.json` in the machine-wide folder or the install folder, or `OUTPOST_SCHOOL_NETWORK=1`; locked on) or by a
grown-up in Settings → For grown-ups → School network (`<userData>/network.json`). Enforced in one place per process:

| Process | Where | A blocked request |
|---|---|---|
| The page | `session.webRequest.onBeforeRequest` (`permissions.js`, `policy`) | cancelled before it leaves, logged `blocked (school network)` |
| The shell | `globalThis.fetch` = `netpolicy.gateFetch` (first-run and optional assets, asset and app update checks); each redirect hop checked | throws `{kind: "school", offline: true}` before the real fetch is called |
| Backend, model server | `app/netgate.py install()`: httpx transports (each hop), `websockets.connect`, `socket.getaddrinfo`, and a `sys.addaudithook` on `socket.connect` / `sendto` (mDNS / SSDP multicast included). With the mode on at launch, uvicorn runs the plain asyncio loop so the audit hook sees every connect | `httpx.ConnectError` / `ConnectionRefusedError` before any socket: callers behave as offline |

Tests: `backend/tests/test_school_network.py` (a blocked request raises before name lookup, socket backstop, mDNS / SSDP
sends refused, loopback still works, the switch applies without a restart, a machine policy locks it, a broken policy
file fails closed, the two `netgate.py` copies match), `desktop/main/netpolicy.test.js` (policy files per OS, the gated
fetch never calls the real one for a blocked host, redirects), `permissions.test.js` (the session filter).
