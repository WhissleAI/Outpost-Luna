# Whissle Engine: a shared, per-user speech engine for Whissle's desktop apps

Status: **design, for review** (issue #90). Builds on #84–#88 (local-access security, pinned ONNX Runtime + model
checksums, libarc ABI version + generated bindings, supervision, free ports / discovery file) and feeds #91 (local
release gates), #92 (local metrics + diagnostics) and #93 (static libarc for in-process embedding).

**Scope decision (owner):** the engine serves **Whissle's own apps only**. Third-party clients are not supported, so
there is no public SDK, no third-party consent flow, and no licensing conflict: libarc and the models stay CC BY-NC 4.0.

*Measured* = `docs/LOCAL_EAR.md` / `docs/DESKTOP.md`; *estimate* = to measure in Phase 2.

## 0. Today

```
Outpost Luna.app (Electron main: desktop/main/main.js)
 ├─ renderer ── ws /ws/listen ──▶ backend (Python; backend/app/listen.py relays ear messages unchanged)
 └─ spawns + supervises ───────▶ model_server (Python)
                                   WS /v1/stream?ear=arc (live ear) · WS /v1/stream (metadata only) · POST /v1/meta
                                   POST /v1/tag, WS /v1/tag/stream · POST /v1/tts[/steer] · POST /v1/embed
                                   one Nft2 (libarc + ORT) under one RLock: ONE model call at a time
```

What the design has to respect:

- **One model call at a time** (`Nft2.lock`, libarc's rule): live streams (`META_MAX_SESSIONS=4`) and `/v1/meta`
  queue in arrival order, so a 20 s offline clip can block a kid's live final.
- **Partials re-decode the whole open segment** every 0.3 s: cost grows quadratically with turn length (*measured*
  RTF 0.50 with partials, 0.3 without; 4 threads, arm64).
- **Memory:** the ear is 460 MB on disk (`encoder.weights` 282 MB). *Measured* RSS is 578 MB steady (packaged) to
  955–985 MB (`ear_compare`). Each extra `arc_nft2_create` is another full copy.
- **Names are per model:** two streams with different lists thrash the bias state on every call.
- **The app owns the mic:** the renderer captures with `getUserMedia` (with echo cancellation of its own audio) and
  sends PCM16 mono 16 kHz in ~80 ms frames.

## 1. Goals and non-goals

**Goals**

1. One per-user install of the engine and its models on a Mac or Windows PC, shared by every Whissle app on it.
   Outpost Luna is the first client; Head Start (`MODELS=host`, already on `/v1/tag/stream`) is the second.
2. Weights loaded once per user. Each additional session costs only its own state and some worker scratch.
3. Live speech always beats batch work, and Whissle apps share fairly. Under overload, partials degrade first, never
   finals, and the engine reports it.
4. A versioned `/v1` protocol with JSON Schemas and internal JS + Python client libraries. Outpost Luna's current
   messages keep their names and shapes.
5. Signed, atomic updates with automatic rollback, built and gated on our own machines (#91).
6. Nothing leaves the machine and no audio is stored. Metrics stay local (#92).

**Non-goals (v1)**

- **Third-party apps**, a public SDK or protocol, and websites as clients.
- Mobile, and the browser without an install. Those embed libarc in-process (#93). The C API is the shared contract.
- Per-machine or system services, and network clients.
- The engine opening the microphone, wake word (§4.3).
- Cloud fallback inside the engine. Deepgram fallback stays the app's decision.
- GPU/NPU execution providers. `/v1/embed` stays in the app.

**Capabilities in v1:** `ear` (live: words, turns, names, events, device-directed), `meta` (whole clip), `tag` (Arc
Tagger), `tts` (OS voices + Steer TTS Edge). If a model is not installed, that capability is absent; the engine does
not fail.

## 2. Install layout and lifecycle

### 2.1 Layout

```
Mac:     ~/Library/Application Support/Whissle/Engine/   (0700)
Windows: %LOCALAPPDATA%\Whissle\Engine\                   (owner-only DACL, does not roam)

  bin/whissle-engine-launcher[.exe]  stable path; reads active.json, execs that version; verifies its signature
  active.json                        {"version":"1.3.0","previous":"1.2.4","trial":false}   (atomic replace)
  versions/<v>/                      signed engine builds (current + previous kept for rollback)
  models/<model_id>/<sha256[0:12]>/  content-addressed, read-only once installed;  models/index.json
  apps/<app_id>.json                 what each Whissle app declared at hello: models, engine range, last_seen
  run/engine.json  run/engine.sock  run/engine.lock     discovery (0600), Mac UDS (0600), single-instance lock
  logs/  metrics/  diag/  staging/  .dl/
```

`assets.js` and `updates.js` already implement most of this for one app: sha256-pinned tars, atomic install by
staging and rename, resumable downloads, trial and rollback. The engine takes that code over, and from then on the
engine, not each app, writes `models/`.

### 2.2 Shared models: leases, not refcounts

Each app's `hello` declares the models it needs (`{"id":"arc-space-nft2","range":"^1"}`), and the engine records that
in `apps/<app_id>.json` with `last_seen`. The set of apps using a model is **derived** from those files whenever it is
needed. Nothing increments or decrements a stored counter. A Mac app is uninstalled by dragging it to the Trash, so no
code would ever run to decrement one, and a crash in the middle of an update would leave a counter wrong for good.

GC rule: delete a model version when none of the apps seen in the last **90 days** references it, no session is using
it, and either a newer version is installed or the user removes it.

### 2.3 Launch on macOS: a socket-activated LaunchAgent

The engine runs as `~/Library/LaunchAgents/ai.whissle.engine.plist`, bootstrapped into `gui/$UID`, with
`Sockets.engine.SockPathName = run/engine.sock` (mode 0600), `RunAtLoad false`, `KeepAlive false`,
`ProcessType Interactive`, and `ThrottleInterval 10`.

- **Started on first connect.** No engine process exists until a client connects to the socket. The engine then takes
  the socket over with `launch_activate_socket`.
- **launchd does the supervision.** It guarantees a single instance and restarts the engine after a crash on the next
  connect. Idle shutdown is just `exit(0)`.
- **No throttling.** `ProcessType Interactive` keeps a windowless agent from being throttled on the live path.
- **Rejected: spawn by the first client.** It races, and the engine dies with whichever app started it (Electron's
  `killTree`). This stays only as the dev-build fallback.
- **Rejected: `SMAppService.agent`.** It binds the engine to a plist inside one app's bundle, so deleting that app
  removes the engine for all the others. Q10 asks whether to ship a separate helper app instead.

### 2.4 Launch on Windows: on-demand spawn, single instance enforced by the engine

1. The client library connects to the engine, or reads `engine.json` and finds it stale.
2. It takes the mutex `Local\Whissle.Engine.Launch.<sid-hash>`, checks again, then starts the launcher with
   `DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB`, and waits up to 30 s for a live `engine.json`.
   - Breakaway is required. Electron's job objects kill their children on close, which would take the engine down with
     the first app that quits.
   - If a job forbids breakaway, the library falls back to `schtasks /run` on a per-user task registered at install.
     No admin rights are needed.
3. The engine holds `Local\Whissle.Engine.Instance.<sid-hash>` and opens its pipe with `FILE_FLAG_FIRST_PIPE_INSTANCE`,
   so a second copy exits.
4. Live worker threads opt out of EcoQoS: `SetThreadInformation(ThreadPowerThrottling)` with
   `ControlMask = EXECUTION_SPEED` and `StateMask = 0`. Windows 11 throttles windowless processes otherwise.

Rejected: per-user services (the template needs admin) and a logon task (0.6–1 GB resident all day).

### 2.5 Idle shutdown and memory pressure

- **Idle shutdown.** After **10 min** with no session and an empty queue, the engine flushes metrics, deletes
  `engine.json` and exits. The cost is a reload on the next turn: *measured* 0.9–3.3 s warm, 5–23 s cold. A foreground
  app holds a zero-cost `presence` session to keep the engine warm.
- **Memory pressure.** The engine listens to Mac `DISPATCH_SOURCE_TYPE_MEMORYPRESSURE` and Windows
  `CreateMemoryResourceNotification`.
  - *Warn:* stop admitting batch work, trim worker arenas, and unload model versions no session is using.
  - *Critical:* also refuse new live sessions (`busy`, `reason:"memory"`). Running live sessions are never dropped.

### 2.6 The engine process

Phases 1–4 reuse `model_server` as the engine host, packaged the way `make desktop-python` does it today, with
libarc and the pinned ORT from #85. uvicorn serves HTTP/WS over the UDS (`--uds`) and loopback TCP, and ctypes calls
release the GIL, so workers decode in parallel.

A native host (Rust or C++, on the #86 bindings) is a **Phase 5 decision**, made on Python's RSS (~100–150 MB,
*estimate*), live-path jitter, and Windows named pipes (uvicorn lacks them).

## 3. Transport and discovery

### 3.1 Transports

| | Mac | Windows |
|---|---|---|
| **IPC** (preferred) | UDS `run/engine.sock`, 0600, in a 0700 directory | named pipe with a DACL for the user's SID, `PIPE_REJECT_REMOTE_CLIENTS` (Phase 5) |
| **Loopback TCP** | `127.0.0.1:<ephemeral>`: only for clients that cannot do IPC | same; on Windows every client uses it until the pipe ships |

Both transports carry the same HTTP + WebSocket protocol. TCP binds `127.0.0.1` only, on a port picked at each start
(#88). Outpost Luna's renderer never talks to the engine: Luna's backend is the engine client, and the renderer keeps
using `/ws/listen`.

### 3.2 Discovery file `run/engine.json`

The engine writes this file atomically (temp file + rename) once it is listening, with mode 0600 or an owner-only
DACL, and deletes it on a clean exit. #88's file is the first subset of it; if #88 ships different field names, #88's
names win.

```json
{ "schema": 1, "instance": "6f1c…", "pid": 41234, "started_at": "2026-11-16T10:02:11Z",
  "engine": { "version": "1.3.0", "abi": 3, "ort": "1.23.2" }, "protocols": [1],
  "endpoints": { "uds": ".../run/engine.sock", "pipe": "\\\\.\\pipe\\whissle-engine-3f9a…", "tcp": "127.0.0.1:53817" },
  "token": "base64url(32 bytes)",          // #84's per-launch token: required on TCP, in addition to §4.1
  "capabilities": ["ear", "meta", "tag", "tts"] }
```

The file is **stale** if its `pid` is dead or its `instance` does not match what `GET /v1/info` returns. Clients then
launch the engine as in §2.3/§2.4. A port number is never trusted without this check, because the OS reuses ports.

### 3.3 Browser-shaped clients and `Origin`

Browsers apply no CORS to WebSockets (#84). Every request and every WS upgrade is checked as follows:

1. **`Host`** must be `127.0.0.1:<port>` or `localhost:<port>`, otherwise the engine returns 421. This stops DNS
   rebinding.
2. **An `Origin` header** must be on a fixed allow-list compiled into the engine for Whissle apps: loopback origins
   with any port (Luna's backend port changes) and our Electron custom schemes. `null` and every public web origin
   are refused.
3. **Credentials for a page.** A page cannot set headers on a WebSocket, so it presents a **ticket** in
   `Sec-WebSocket-Protocol: whissle.v1, ticket.<t>`. A ticket is minted by its app's signed native side, is single-use,
   lives 60 s, and is bound to one origin and one capability. Tickets never go in the query string, which ends up in
   logs.

## 4. Identity and permissions

### 4.1 Identity: only Whissle-signed clients

The engine accepts a connection only if the **peer process is signed by Whissle**: our Apple Team ID on Mac, our
Authenticode subject on Windows. Unsigned and third-party clients are refused with `4403 forbidden`.

How the engine finds the peer process:

- **Mac UDS:** `getsockopt(LOCAL_PEERTOKEN)` gives the audit token, then `SecCodeCopyGuestWithAttributes` +
  `SecCodeCheckValidity` check it against the requirement `anchor apple generic and certificate leaf[subject.OU] =
  <TeamID>`.
- **Windows pipe:** `GetNamedPipeClientProcessId`, then `WinVerifyTrust` on the client's exe and a check of the signer.
- **TCP (both OSes):** the owning PID of the client's end of the connection, from `GetExtendedTcpTable` on Windows or
  `proc_pidfdinfo` on Mac, gets the same signature check. TCP also requires `engine.json`'s `token`, or a ticket for
  pages (§3.3).

**app_id** is the signed identity: the bundle id (Mac) or the exe name under our signer (Windows). It is never a
value
the client claims.

**Interpreters.** Luna's backend is a Python interpreter, so the signature describes the interpreter, not the script.
It is accepted because it is a Whissle-signed interpreter inside a Whissle-signed app bundle: the engine checks both
the binary's signature and that its path lies inside a valid Whissle bundle. Q7 asks whether that is enough.

Only a *development* engine build accepts unsigned clients.

**Per-app keys are dropped.** With the signature as identity, keys would add nothing. Identity is used for
**attribution and quotas among Whissle apps** (§5.2) and for metrics. It is not a security boundary against code
running as the same user (§9).

### 4.2 Settings

The engine has no window. Each Whissle app's settings page opens an **Engine** pane, served by the engine and shown
in the app. The pane lists:

- the Whissle apps seen, with version, last seen, and audio minutes;
- installed models, their sizes, and which apps use them, with **Remove**;
- version, update state, and **Check for updates**;
- **Diagnostics** (§8).

There are no consent prompts, because every client is ours.

### 4.3 Who owns the microphone: the app

**Apps capture audio and send it. The engine never opens an input device.**

1. **OS permissions are per app.** macOS TCC gives mic access to the *responsible* process. A launchd agent asking for
   the mic would prompt as "Whissle Engine", once for every app, and the mic indicator would name the wrong app. The
   per-app switches in Windows Privacy settings would stop meaning anything.
2. **Least privilege.** An engine that cannot open the mic cannot become a listening post through a bug or a tampered
   model. It hears only what an app chose to send.
3. **Echo cancellation lives with playback.** Luna's barge-in depends on the browser cancelling the echo of its own
   in-page audio (`SESSION_CONTRACT.md` §2–4). Only the app also knows its own push-to-talk, mute and focus state.
4. **The cost is tiny.** One stream is 32 KB/s over IPC.

This gives up a shared, engine-owned wake word, and means two apps listening at once cost two decodes. Both are
non-goals (Q6).

## 5. Concurrency and scheduling

### 5.1 What libarc must expose

Today one `arc_nft2*` bundles the weights, the scratch memory, the names, the context and the stream state. These are
the proposed additions to `arc.h`, versioned with `arc_abi_version()` (#86):

```c
/* One ORT env with a GLOBAL intra-op pool (OrtThreadingOptions + DisablePerSessionThreads) and one
 * prepacked-weights container: N sessions neither spin N pools nor prepack N copies. */
arc_runtime*    arc_runtime_create(int intra_threads, int inter_threads, char* err, size_t err_len);
void            arc_runtime_destroy(arc_runtime*);

/* Immutable, refcounted, safe for concurrent reads (ORT Run() is thread-safe; q4 decoder, adapters, tokenizer,
 * tag tables read-only; safetensors mmap'd). */
arc_nft2_model* arc_nft2_model_load(arc_runtime*, const char* dir, char* err, size_t err_len);
void            arc_nft2_model_retain(arc_nft2_model*);
void            arc_nft2_model_release(arc_nft2_model*);
size_t          arc_nft2_model_bytes(const arc_nft2_model*);

/* Per-session context: names + RNNT bias trie, decoder context, auto_prev history, streaming encoder cache,
 * scratch. Target < 5 ms and < 5 MB to create. One call at a time PER CONTEXT; many contexts run on one model. */
arc_nft2*       arc_nft2_create_from(arc_nft2_model*, char* err, size_t err_len);
size_t          arc_nft2_ctx_bytes(const arc_nft2*);

/* Any thread: the in-flight call returns ARC_ECANCELED at its next checkpoint (encoder chunk / decoder step),
 * target <= 20 ms. */
int             arc_nft2_cancel(arc_nft2*);

/* RNNT streaming partials for the open utterance (no segment re-decode), and a cap on retained audio
 * (today the stream keeps all its audio until closed). */
int             arc_nft2_stream_set_partials(arc_nft2_stream*, int every_ms);
int             arc_nft2_stream_set_max_audio_s(arc_nft2_stream*, float seconds);
```

`arc_nft2_create` stays, as `model_load` + `create_from`, for in-process users (#93). Two of these changes matter most:

- **The model/context split plus the global thread pool.** Without them, each extra session costs another
  ~0.6–0.9 GB and adds its own thread pool, oversubscribing the CPU.
- **Streaming partials.** The RNNT is streaming by construction, so its partials are nearly free. They remove the
  quadratic re-decode that dominates the live load today. Finals stay the full Arc decode at the endpoint.

Arc Tagger (12 MB, a handle per stream) needs no split. Steer TTS stays serialized on its lock and shares the
ORT runtime.

### 5.2 Scheduler

```
 sessions ─▶ admission (caps) ─▶  P0 live final    FIFO                    ─▶ W0 reserved for P0/P1
                                  P1 live partial  latest-wins per stream  ─▶    while any live session is open
                                  P2 batch         chunks ≤ 4 s audio      ─▶ W1…  take P2/P3 only when P0/P1 are empty
                                  P3 background    warm-up, self-test
            within a priority: deficit round-robin across apps by audio-seconds, then FIFO per app
```

- **The unit of work is a job:** one libarc call on one session's context; sessions compete only for workers.
- **Priorities are strict:** P0 live final, then P1 live partial, then P2 batch, then P3. When a stream's final is
  queued, its pending partial is dropped. Each stream has at most one pending partial, and a newer one replaces it.
- **Calls can't be interrupted, so they are kept short:**
  - batch work is cut into chunks of 4 s of audio or less at segmenter boundaries (≤ ~1.2 s of compute, *estimate*);
  - one worker is reserved for live work while any live session is open;
  - a batch chunk running longer than 300 ms is cancelled and requeued when a live final has no free worker.
- **Fairness among Whissle apps:** deficit round-robin within each priority. Defaults: `max_live_per_app` 2,
  `max_batch_inflight_per_app` 1.
- **Threads:** `W × T ≤ physical cores − 1`. Defaults: W = 2, T = 3 on machines with ≤ 8 cores; W = 3 on ≥ 10 cores.
  Live workers run at `USER_INTERACTIVE` QoS on Mac and unthrottled on Windows; batch workers at `UTILITY` or with
  EcoQoS.

### 5.3 Admission and backpressure

| Situation | Engine | Client sees |
|---|---|---|
| live cap reached (total or per app) | refuses at `hello` | `busy`, close 1013, `retry_after_ms` |
| live stream > 2 s behind | drops its partials, keeps finals | `{"t":"lag","behind_s"}` once per episode |
| > 30 s of audio queued on a live stream | closes it | `overloaded`, 1013 |
| client not reading (> 1 MB buffered) | drops pending partials and frames, keeps finals | > 8 MB: `slow_consumer`, 1013 |
| batch | queued; stops reading the request body while queued (TCP flow control) | latency only |

### 5.4 Memory math

These are *estimates* (Phase 2 replaces them), anchored on the *measured* 578 MB steady and 955–985 MB peak process
RSS:

| Symbol | What | Estimate |
|---|---|---|
| `M` | ear weights + ORT arenas | 0.55–0.70 GB |
| `w` | scratch per worker | 80–150 MB |
| `s` | per session | 3–6 MB + ≤ 1 MB audio (15 s cap) |
| `h` | host runtime | 0.10–0.15 GB |

| Config | Shared `h + M + W·w + S·s` | One copy per app |
|---|---|---|
| 1 live session, W = 2 | ≈ 0.85–1.0 GB | ≈ 0.6–0.95 GB |
| 8 GB machine: 4 live, W = 2 | **≈ 0.9–1.05 GB** | **2.4–3.8 GB** |
| 16 GB machine: 8 live, W = 3 | ≈ 1.0–1.2 GB | 4.8–7.6 GB |

On an 8 GB machine the OS, a browser and the apps take ~5–6 GB, so the engine's budget is ~1.2 GB. That gives
defaults of **`max_live` 4 on 8 GB and 8 on 16 GB+**, scaled at start from physical RAM.

Compute limits how many sessions can be *speaking at once*, not how many are open. One T = 3 worker at RTF ~0.3
sustains ~3 continuous speakers. Kids' sessions are an estimated 10–25% speech (Q8).

Sharing must be in-process: mmap'd safetensors are shared across processes anyway, but ORT prepacks weights into
private memory per session, and `encoder.weights` is the bulk (Q1).

## 6. Protocol `/v1` (internal)

### 6.1 Surface

| Endpoint | From today |
|---|---|
| `GET /v1/info`: instance, versions, capabilities, models | `/health` (kept as an alias) |
| `WS /v1/ear` (`?mode=metadata` for the metadata-only form) | `WS /v1/stream?ear=arc` / `WS /v1/stream` (aliases through v1) |
| `POST /v1/meta`, `POST /v1/tag`, `WS /v1/tag/stream`, `POST /v1/tts[/steer]`, `GET /v1/tts/voices` | unchanged |
| `POST /v1/tickets` (signed native client → ticket for its page) | new |
| `GET /v1/metrics` | new (#92) |

Schemas live in `protocol/v1/*.schema.json` (JSON Schema 2020-12), one per message `t`. They are the source for the
client-library types and for the protocol fuzzer (#91). `make protocol-check` validates recorded sessions against
them.

### 6.2 Ear stream

**Audio** is sent as binary frames: PCM16 LE, mono, 16 kHz, 20–500 ms each. Every server message carries `at`, in
audio-seconds since the first sample.

**Client → engine:**

```
  {"t":"hello","protocol":[1],"app":{"version":"0.4.0"},"engine":">=1.2 <2",
   "models":[{"id":"arc-space-nft2","range":"^1"}],
   "want":{"domain":"assistant","partials":true,"names":true,"events":true,"frames":false},
   "priority":"live","names":[{"name":"Artemis II","kind":"mission","aliases":["Artemis 2"]}]}
  {"t":"context","names":[…],"terms":[…],"topic":"…","mission":{…},"telemetry":{…}}      as today (STREAMS.md)
  {"t":"end_turn"}  {"t":"stop"}  {"t":"ping","id":n}
```

**Engine → client:**

```
  {"t":"ready","protocol":1,"session":"s_…","engine":"1.3.0","model":{"id":"arc-space-nft2","revision":"176d324"},
   "granted":{…},"limits":{"max_names":40,"max_turn_s":15},"deprecations":[]}
  turn / words (partial, final) / arc / context_ack                                        unchanged shapes, + "at"
  {"t":"lag","behind_s"}  {"t":"pong","id"}  {"t":"error","code","message","retry_after_ms"?}
```

The engine fills in `app_id` from the peer's signature (§4.1); the client never sends it.

**Legacy mode.** A client that sends audio or `context` without a `hello` gets today's `ear` and `emotion` greetings
and default settings, so `listen.py` keeps working until Phase 2. Legacy mode is removed in v2.

**Names are per session.** Each session's context holds its own list, so two apps or two screens no longer thrash
each other.

### 6.3 Error codes

| `code` | WS close | HTTP | Retry |
|---|---|---|---|
| `bad_request` (schema, framing) | 1008 | 400 | no |
| `forbidden`: not Whissle-signed, bad token/ticket, origin not allowed | 4403 | 403 | no |
| `protocol_unsupported` (no common major; `message` has the engine range) | 4426 | 426 | no |
| `model_unavailable` (not installed / failed load check) | 4404 | 404 | after install |
| `busy` (cap or memory) · `overloaded` · `slow_consumer` | 1013 | 503 | yes, back off |
| `shutting_down` (idle exit or update swap raced the connect) | 1001 | 503 | yes, at once |
| `internal` | 1011 | 500 | yes, back off |

1008, 1011 and 1013 keep the meanings they have in `tag_stream.py` and `routes_meta.py` today.

### 6.4 Internal client libraries

There is one library for JS (Electron main / Node) and one for Python. Both are internal and live in this repo
(`clients/js`, `clients/python`); neither is published. Message types are generated from the schemas. Each library
also handles:

- discovery and the staleness check on `engine.json`;
- launching the engine (§2.3/§2.4);
- trying IPC first, then TCP;
- `hello` and the version check;
- reconnecting with jittered back-off (250 ms → 8 s) on 1013, 1001 and engine restarts;
- delivering `lag` and `busy` as events, not exceptions.

### 6.5 Deprecation

- **Additive only within v1.** Both sides ignore unknown fields and unknown `t`, and the schemas allow additional
  properties.
- **Removal only in a new major.** `/v2` is served alongside `/v1` until every shipped Whissle app that speaks only v1
  is past its supported window, with a minimum of 12 months.
- **Announcing.** Deprecated items appear in `ready.deprecations` and are counted in local metrics.

## 7. Updates

**What gets signed:**
- **Engine builds:** Developer ID + notarization on Mac, Authenticode on Windows (#89).
- **Models:** sha256-pinned tars, as today.
- **The release manifest** lists both. It extends `updates.js`'s schema 2 with `engine` entries and `protocols`, and
  is **signed with Ed25519 (minisign)**. That signature was "future hardening" in `docs/DESKTOP.md`; here it is
  required.
- **Keys:** the launcher carries two public keys; the second is kept offline for rotation. A manifest with a bad
  signature is ignored as a whole.

**How an update goes:**

1. **Check.** Daily while the engine runs, and from Settings. Offline means nothing changes. The offline pack carries
   its own signed manifest.
2. **Stage.** Downloads resume, then every file is checked against its sha256 and unpacked into `staging/` or
   `models/<id>/<sha>/` (#85).
3. **Swap the engine only when idle.** The engine writes `active.json` = `{"version":new,"previous":old,"trial":true}`
   atomically and exits. The next connect starts the new version.
4. **Confirm or roll back, within 60 s.**
   - Checks: `/v1/info` responds, each model passes its load check, and a **3 s golden clip** produces the expected
     text and names.
   - Pass: `trial` becomes false.
   - Fail, or a crash during the trial: the engine reverts to `previous` and that version is never offered again.
5. **Models update apart from the engine.** A new model version installs next to the old one and is used from the
   next `hello`, never in the middle of a stream. At most two versions of one model are resident at a time.

**Compatibility.** Apps declare engine and model ranges in `hello`; models declare `min_engine`. The engine never
downgrades: an app installs its bundled engine payload only when it is newer than the installed one, or none is
installed.

**Releases are built locally (#91)** on the Mac and Windows build machines. `make release-check` gates signing:
golden-audio WER/latency, C API + protocol fuzzing, a 24 h soak, and a 4-session soak with an update-and-rollback
drill. Signing keys sit on a hardware token; publishing is unchanged.

## 8. Observability and privacy

- **What is never stored.** No audio: there is no capture mode at all. No transcript text in logs, which carry only
  lengths, timings, codes and model ids. Dev builds of the engine may log text; release builds cannot.
- **Logs.** JSON lines in `logs/engine.log`, rotated 5 × 10 MB.
- **Metrics (#92).** 30 days of minute buckets per app and model: sessions, audio-seconds, queue wait and decode
  p50/p95 per priority, turn-end latency, partial drops, `busy`/`overloaded`, crashes, RSS. Served at
  `GET /v1/metrics`, sent nowhere.
- **Diagnostics zip (#92).** Only on request, into `diag/`: logs, metrics, `engine.json` without the token,
  `active.json`, model hashes and load checks, OS/hardware summary, app list, and **minimal crash dumps**
  (`MiniDumpNormal` without heap; Mac `.ips`), since a full dump would hold live audio buffers.

## 9. Threat model

| Adversary | Attack | Mitigation | Residual |
|---|---|---|---|
| **Other OS user** | connect, read files, hear audio | per-user engine; 0700 dir / owner-only DACL; UDS 0600; pipe DACL + reject remote; TCP needs the 0600 token | admin/root (out of scope) |
| **Website** | WS to loopback (no CORS), DNS rebinding | `Host` check; fixed `Origin` allow-list (no public origins); ticket from a signed app's native side; token unreachable from a page; random port | can detect that the engine is running |
| **Non-Whissle local app** | use or exhaust the engine | refused: peer must be Whissle-signed (§4.1) | same-user code can still use the mic itself, or inject into a Whissle process; the engine adds no capability it lacked |
| **Tampered files** | swap weights or graphs to crash or exploit parsers; swap the engine build | sha256 of every model file at install and load (#85); pinned ORT; the launcher verifies the build's signature; ONNX/safetensors parsing fuzzed (#91) | same-user write access remains powerful; signing raises the bar |
| **Update path** | MITM, a substituted artifact | https + host allow-list + Ed25519-signed manifest + sha256 + code signing | key theft: hardware token, offline rotation key |
| **Malformed client input** | crash libarc | schemas, frame limits, fuzzing, decode watchdog (#87) | an engine crash drops every session; clients reconnect, live audio in flight is lost |

## 10. Migration

| Phase | Work | Acceptance |
|---|---|---|
| **0** (#84–#88, in progress) | origin + token; pinned ORT + sha256; ABI version + generated bindings; supervision + watchdog; free ports + discovery file | the issues' tests: hostile-origin WS refused, tampered model refused, ABI mismatch fails loudly, mid-turn kill recovers, no fixed ports |
| **1: protocol** | schemas; `hello`/`ready`, error codes, `lag`, legacy mode; `/v1/ear` + aliases; JS + Python client libraries; Luna's backend on the Python library | replaying a recorded session gives the same client-visible messages as today; every recorded session validates against the schemas; 1 h protocol fuzz with no crash |
| **2: pool + scheduler** (still embedded) | libarc split, runtime, cancel, streaming partials; per-session contexts, priority queues, coalescing, caps, memory pressure, metrics | 8 GB M1 and 8-core Windows, 4 live streams + 1 batch: RSS ≤ 1.2 GB; live turn-end p95 ≤ single-stream p95 + 150 ms; no live final waits behind batch; first-words p50 ≤ 800 ms (today 1059); golden WER ±0.3 pt; 24 h soak, RSS growth < 5% |
| **3: engine install** | engine dir, launcher, `active.json`; LaunchAgent (Mac) / spawn (Windows); `engine.json`; signature checks; Settings pane; model leases. Luna uses the engine, with the embedded server as automatic fallback for one release | Luna + Head Start (or a test client) on one engine with one copy of the weights; quitting or deleting Luna leaves the other working; idle exit frees memory; warm reconnect after a crash ≤ 5 s; an unsigned client, another user, or a hostile origin is refused |
| **4: updates + cleanup** | signed manifest, self-update with trial and rollback, side-by-side model versions; remove Luna's embedded server | a broken build rolls back on its own within 60 s; an unsigned manifest is ignored; a model update does not touch a live session |
| **5: native host** (decision) | replace the Python host if measurements justify it; Windows named pipe | the protocol suite passes unchanged; RSS down ≥ 100 MB; live p95 no worse |

Until the phase after next, Luna keeps the previous path behind `EAR_ENGINE=embedded|shared`.

## 11. Open questions for review

*Q7 from the first draft (licensing) is resolved by the owner's scope decision: Whissle apps only.*

1. **Weight sharing.** In-process contexts on one model, or processes sharing mmap'd pages? Since ORT prepacks per
   session, would you serialize prepacked weights to disk once and mmap them?
2. **Preemption.** We plan a reserved live worker, chunked batch work, and cooperative cancel. Is a 20 ms decoder
   checkpoint realistic, or are resumable jobs better than cancel-and-redo?
3. **Partials.** RNNT partials with an Arc-decoder final can diverge. How much divergence did users tolerate, and did
   you gate partials on stability?
4. **Threads and QoS.** One global ORT pool, or one per worker? Is `USER_INTERACTIVE` QoS for a windowless agent
   defensible on battery, and is opting out of EcoQoS enough on Windows?
5. **Release cadence and size.** Should models update independently of the engine, or in lock-step? And is an int8
   `encoder.weights` (282 of 460 MB) worth its accuracy cost?
6. **Wake word.** "The engine never opens the mic" rules out a shared wake word. Where did keyword spotting live in
   your stack?
7. **Interpreter identity.** Is "Whissle-signed interpreter inside a Whissle-signed bundle" a sound identity for
   Luna's Python backend, or should the backend get a ticket from Electron's main process?
8. **Capacity.** `max_live` assumes kids speak 10–25% of the time. What duty and concurrency figures did you size
   against?
9. **Shipping the engine.** Each app carries the full engine payload (~0.5 GB, works offline), or a small
   bootstrapper (smaller apps, but it breaks offline installs for schools)?
10. **Mac IPC.** UDS + socket-activated LaunchAgent (same design on both OSes), or an XPC Mach service in a separate
    helper app registered with `SMAppService`?
11. **Per-user or per-machine.** On shared family and school PCs, each user loads their own copy of the weights. Is a
    per-machine read-only model store worth the admin install it needs?
