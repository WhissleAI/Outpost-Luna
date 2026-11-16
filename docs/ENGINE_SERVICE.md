# Whissle Engine: a shared, per-user speech engine for desktop apps

Status: **design, for review** (issue #90). Builds on #84–#88 (local-access security, pinned ONNX Runtime + model
checksums, libarc ABI version + generated bindings, supervision, free ports / discovery file) and feeds #91 (local
release gates), #92 (local metrics + diagnostics) and #93 (static libarc for in-process embedding).

Numbers marked *measured* come from `docs/LOCAL_EAR.md` and `docs/DESKTOP.md`. Numbers marked *estimate* are to be
measured in Phase 2 before any default below is frozen.

## 0. Today, in one picture

```
Outpost Luna.app (Electron main: desktop/main/main.js)
 ├─ renderer (page) ── ws /ws/listen ──▶ backend (Python, :47310 or free port)
 │                                          │  backend/app/listen.py: relays ear messages unchanged
 │                                          ▼
 └─ spawns + supervises ───────────────▶ model_server (Python, :47210 or free port)
                                          ├─ WS  /v1/stream?ear=arc   live ear (arc_ear.EarStream, one per socket)
                                          ├─ WS  /v1/stream           metadata-only form (Deepgram fallback path)
                                          ├─ POST /v1/meta            whole clip (offline pipeline)
                                          ├─ POST /v1/tag, WS /v1/tag/stream   Arc Tagger (handle pool / handle per WS)
                                          ├─ POST /v1/tts[, /steer]   OS voices, Steer TTS Edge
                                          └─ POST /v1/embed
                                          one Nft2 (libarc + ORT) under one RLock: ONE model call at a time
```

Facts the design has to respect:

- **One model, one call at a time.** `nft2.Nft2.transcribe` takes `self.lock`; libarc's rule is "one model runs one
  call at a time" (`arc.h`). Every live stream (`META_MAX_SESSIONS=4`) and every `/v1/meta` call queue on that lock in
  arrival order. There is no priority: a 20 s offline clip blocks a kid's live final.
- **Partials re-decode the whole open segment** every `EAR_PARTIAL_EVERY_S` (0.3 s, backing off to 1.25× its own
  cost, none past 8 s). Cost grows quadratically with turn length. Measured RTF 0.50 with partials, 0.3 without
  (4 threads, arm64).
- **Memory (measured):** ear assets 460 MB on disk (`encoder.weights` 282 MB, decoder 96 MB, `model.q4` 37 MB,
  adapters 19 MB, ONNX graphs ~23 MB). The model-server process sits at 578 MB steady in the packaged app and
  955–985 MB RSS (after load / peak) in `ear_compare`. A second `arc_nft2_create` today means a second full copy.
- **Names and context are per model, not per stream.** `arc_nft2_set_names` sets state on the model.
  `Nft2.transcribe` re-sets the names whenever the caller's list differs (`_names_key`), so two streams with different
  lists thrash the RNNT bias trie and the kb prompt on every call.
- **The app owns the mic.** The renderer captures (`getUserMedia`, with the browser's echo cancellation of our own
  in-page audio, `SESSION_CONTRACT.md` §4) and sends PCM16 mono 16 kHz in ~80 ms frames.

## 1. Goals and non-goals

**Goals**

1. One per-user install of the Whissle engine and its models on a Mac or Windows PC. Any number of desktop apps use it.
   Outpost Luna is the first client, Head Start (`MODELS=host`, which already uses `/v1/tag/stream`) the second.
2. Weights loaded once per user session, shared by every client. Memory grows with active sessions only by per-session
   state and per-worker scratch.
3. Live speech always beats batch. Within a priority, apps share fairly. Overload degrades partials first, never
   finals, and is reported, not hidden.
4. A versioned `/v1` protocol with JSON Schemas and JS + Python SDKs. Outpost Luna's current messages keep their names
   and shapes.
5. Signed, atomic engine and model updates with automatic rollback, built and gated on our own machines (#91).
6. Nothing leaves the machine. No audio stored. Local metrics only (#92).

**Non-goals (v1)**

- Mobile and the browser without an install. Those embed libarc in-process (#93). The C API stays the contract
  between them and this engine, so both share one model format.
- Per-machine or system services, and network or LAN clients. The engine serves one OS user over loopback/IPC.
- The engine opening the microphone, wake word, always-on listening (see §4.4).
- Cloud fallback inside the engine. Deepgram fallback stays an app decision (`listen.py`).
- GPU / NPU execution providers (CoreML, DirectML). CPU only in v1; the pool design does not preclude them.
- Embeddings (`/v1/embed`): not speech. They stay in the app for now.

**Engine capabilities in v1:** `ear` (live stream: words, turns, names, events, device-directed), `meta` (whole
clip), `tag` (Arc Tagger, text), `tts` (OS voices + Steer TTS Edge). Each is optional, so a model that is not
installed means a capability is absent, not a failed engine.

## 2. Install layout and lifecycle

### 2.1 Layout

```
Mac:     ~/Library/Application Support/Whissle/Engine/       (0700)
Windows: %LOCALAPPDATA%\Whissle\Engine\                       (owner-only DACL; LOCALAPPDATA: does not roam)

Engine/
  bin/whissle-engine-launcher[.exe]   stable path, tiny, rarely changes: reads active.json, execs the version
  active.json                         {"version":"1.3.0","previous":"1.2.4","trial":false}  (atomic replace)
  versions/1.3.0/                     signed engine build (Python runtime + app in Phases 1–4; see §2.6)
  versions/1.2.4/                     kept for rollback; older ones GC'd
  models/<model_id>/<sha256[0:12]>/   content-addressed, read-only once installed (e.g. arc-space-nft2/ea1b54f07b6e/)
  models/index.json                   installed models: id, version, sha256, size, installed_at, last_used_at
  apps/<app_id>.json                  registrations (§4.1): identity, models wanted, engine range, last_seen, grants
  run/engine.json                     discovery file (0600), §3.2
  run/engine.sock                     Mac UDS (0600)
  run/engine.lock                     single-instance lock
  logs/  metrics/  diag/              §8
  staging/  .dl/                      update downloads and unpacking (§7)
```

`assets.js` / `updates.js` already do most of the model-store work for one app: manifest schema 2, sha256-pinned tars,
atomic install via staging and rename, resumable downloads, trial and rollback. The engine takes this code over
rather than writing a second implementation. What changes is ownership: the engine, not the app, writes `models/`.

### 2.2 Shared model store: leases, not counters

Each app's registration lists the models it needs (`{"id":"arc-space-nft2","range":"^1"}`). A model's reference set is
**derived** from `apps/*.json` every time it is needed. No stored refcount is incremented or decremented.

Why: a Mac app is uninstalled by dragging it to the Trash, so no code runs and nothing can decrement a counter. A
crash between "install" and "count++" also leaves counters wrong forever. Derived references cannot drift.

GC rule: a model version is deleted when no registration that has been seen in the last **90 days** references it,
no session uses it, and a newer version of that model is installed or the user removes it in Settings. A model that
only stale apps reference is kept until the user removes it or 90 days pass. Disk cost of being wrong: ~0.5 GB per
stale ear.

### 2.3 How the engine is launched: macOS

**Choice: a per-user launchd LaunchAgent with socket activation on the UDS.**
`~/Library/LaunchAgents/ai.whissle.engine.plist`, loaded with `launchctl bootstrap gui/$UID`:

```
Label ai.whissle.engine
Program  .../Engine/bin/whissle-engine-launcher
Sockets  { engine = { SockPathName = .../Engine/run/engine.sock; SockPathMode = 384 (0600) } }
RunAtLoad false   KeepAlive false   ProcessType Interactive   ThrottleInterval 10
```

- The process does not exist until a client connects to `engine.sock`. launchd holds the listening socket and starts
  the engine on the first connect; the engine takes it over with `launch_activate_socket("engine")`.
- launchd guarantees a single instance and restarts the engine after a crash on the next connect, throttled. No
  supervisor process of our own.
- Idle shutdown (§2.5) is just `exit(0)`. The socket stays bound in launchd, so the next client starts it again.
- `ProcessType Interactive` keeps launchd from treating the engine as background work. The default (`Standard`)
  allows CPU and I/O throttling of a windowless process, which would land on the live path.

Rejected:

- *On-demand spawn by the first client* (as on Windows). It works and is the dev-build fallback in the SDK, but it
  races (two apps start at once), needs our own lock and crash recovery, and leaves the engine as the child of
  whichever app came first. Electron kills its process group on quit (`killTree`), so the engine needs a `setsid`
  escape.
- *`SMAppService.agent`* (macOS 13+). It is the modern API, but it binds the agent to a plist inside one app's bundle.
  When that app is deleted, the engine disappears for every other app. Shipping the engine as its own helper app
  would fix that, and is open question Q12.
- *XPC Mach service.* The native Mac IPC, with peer audit tokens, but Mac-only, and browser-shaped clients still need
  TCP. UDS gives the same peer-identity check (§4.2) with one code path on both OSes. See Q12.

macOS 13+ shows a "Background Items Added" notice the first time, attributed to our Developer ID. That is expected,
and the engine's Settings page explains it.

### 2.4 How the engine is launched: Windows

**Choice: on-demand spawn by the client SDK, single instance enforced by the engine.** Windows has no per-user socket
activation.

1. The SDK opens `\\.\pipe\whissle-engine-<hash(user SID)>`, or reads `engine.json` and connects over TCP (Phase 1–3).
2. If the engine is not running, the SDK takes the named mutex `Local\Whissle.Engine.Launch.<sid-hash>` and checks
   again. If the engine is still absent, it starts `bin\whissle-engine-launcher.exe` with `DETACHED_PROCESS |
   CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB`, then waits up to 30 s for `engine.json` with a live `instance`.
3. The engine itself holds `Local\Whissle.Engine.Instance.<sid-hash>` and creates its pipe with
   `FILE_FLAG_FIRST_PIPE_INSTANCE`. A second engine exits at once.

`CREATE_BREAKAWAY_FROM_JOB` matters: Electron, and Chromium's own children, run inside job objects with
kill-on-close, so without it the engine dies when the first app quits. If a job forbids breakaway, the SDK falls back
to starting the launcher through a one-shot `schtasks /run` of a task registered at install (no admin needed for a
per-user task).

The engine also has to opt out of power throttling on its live worker threads (`SetThreadInformation(...,
ThreadPowerThrottling, ...)` with `ControlMask = THREAD_POWER_THROTTLING_EXECUTION_SPEED`, `StateMask = 0`). Windows 11 applies EcoQoS to
windowless background processes, and Phase 2 measures the latency cost of not doing this.

Rejected:

- *Per-user services* (Windows 10 1709+). The service template has to be installed by an administrator. The engine
  installs per user without admin, as Outpost Luna does now.
- *Scheduled task at logon.* Keeps ~0.6–1 GB resident all day for an app a kid opens twice a week, and still needs a
  spawn path for the first install.

### 2.5 Single instance, idle shutdown, memory pressure

- **Single instance:** launchd (Mac) or the instance mutex plus the first pipe instance (Windows), with `run/engine.lock`
  (`flock` / `LockFileEx`) as a second guard on both. The holder writes `engine.json`.
- **Idle shutdown:** after **10 min** with no open session and an empty queue (`ENGINE_IDLE_S`), the engine flushes
  metrics, deletes `engine.json` and exits. Trade-off: the first turn after idle pays a model load, *measured* 0.9–3.3 s
  warm and 5–23 s cold. An app in the foreground holds a `presence` session, which costs nothing but keeps the engine
  warm. An app that is not on screen does not.
- **Memory pressure:** Mac `DISPATCH_SOURCE_TYPE_MEMORYPRESSURE` and Windows `CreateMemoryResourceNotification`.
  *Warn:* stop admitting batch work, trim worker arenas to the floor, unload model versions with no session.
  *Critical:* also refuse new live sessions with `busy` (`reason:"memory"`). Live sessions already running are never
  dropped for pressure.

### 2.6 What the engine process is

Phases 1–4 reuse `model_server` as the engine host: the same Python app, packaged like `make desktop-python`
(python-build-standalone 3.11, frozen `uv` lock), with libarc + pinned ORT (#85). uvicorn serves HTTP/WS on a UDS
(`--uds`) and on loopback TCP. ctypes calls release the GIL, so decode workers run in parallel.

A native host (Rust or C++, linking libarc through the #86 generated bindings) is a **Phase 5 decision**, gated by
measurement: Python's own RSS (~100–150 MB, *estimate*), event-loop jitter on the live path, and named-pipe support.
The protocol and the on-disk layout do not depend on which host it is.

## 3. Transport and discovery

### 3.1 Transports

| | Mac | Windows | Who uses it |
|---|---|---|---|
| **IPC (preferred)** | UDS `run/engine.sock`, 0600, in a 0700 dir | named pipe, DACL = the user's SID only, `PIPE_REJECT_REMOTE_CLIENTS` | native clients: an app's main process, a Python backend, CLIs |
| **Loopback TCP** | `127.0.0.1:<ephemeral>` | same | clients that cannot do IPC: browser-shaped renderers, and every Windows client until the named pipe ships |

Both carry the same HTTP + WebSocket protocol. IPC is preferred because it gives the engine the **peer's identity
from the kernel** (§4.2). TCP gives only a bearer credential. TCP binds `127.0.0.1` only, never `0.0.0.0` or `::`,
on a port chosen at start (#88). No fixed port, and the port is never reused across launches on purpose.

For Outpost Luna specifically, the renderer never talks to the engine. It keeps talking to Luna's backend
(`/ws/listen`), and the backend is the engine client over IPC. Browser-shaped access exists only for future apps.

### 3.2 Discovery file `run/engine.json`

Written atomically (temp file + rename) by the engine once it is listening, mode 0600 or an owner-only DACL. Deleted
on clean exit. #88's discovery file is the first subset of this (endpoints, token, pid). If #88 lands with different
field names, #88 wins and this section follows it.

```json
{
  "schema": 1,
  "instance": "6f1c…",                       // random per launch; GET /v1/info must return the same value
  "pid": 41234,
  "started_at": "2026-11-16T10:02:11Z",
  "engine": { "version": "1.3.0", "abi": 3, "ort": "1.23.2" },
  "protocols": [1],
  "endpoints": {
    "uds":  "/Users/u/Library/Application Support/Whissle/Engine/run/engine.sock",
    "pipe": "\\\\.\\pipe\\whissle-engine-3f9a…",
    "tcp":  "127.0.0.1:53817"
  },
  "bootstrap_token": "base64url(32 bytes)",   // #84's per-launch token, see §4.1 for what it grants
  "capabilities": ["ear", "meta", "tag", "tts"]
}
```

Client rule: a file whose `pid` is dead, or whose `instance` does not match `GET /v1/info`, is stale. The client then
treats the engine as not running and goes through launch (§2.3 / §2.4). Clients never trust the port without that
check, because ports are reused by other processes.

### 3.3 Versioning on the wire

- The path carries the major version: `/v1/...`. A breaking change means `/v2`, served next to `/v1` (§6.5).
- `hello` names the protocol majors the client speaks and the engine range it needs (`"engine": ">=1.2 <2"`). The
  engine answers with what it grants (§6.2). Minor features are negotiated as capabilities, never inferred from
  version numbers.

### 3.4 Browser-shaped clients and `Origin`

Browsers apply no CORS to WebSockets, so any page can open `ws://127.0.0.1:<port>/...`. That is #84's finding. The
engine enforces, on every HTTP request and every WS upgrade:

1. **`Host` must be `127.0.0.1:<port>` or `localhost:<port>`**, otherwise 421. This defeats DNS rebinding, where
   `evil.example` resolves to 127.0.0.1 and the browser sends `Host: evil.example`.
2. **No `Origin` header:** a native client. It must authenticate with an app key or a peer identity (§4.2).
3. **`Origin` present:** it must exactly match an origin the authenticating app registered. Loopback origins may use a
   port wildcard (`http://127.0.0.1:*`), because Luna's backend port changes. Electron custom schemes
   (`app://outpost-luna`) are matched literally. `null` (`file://`) is refused. **Public web origins are refused in
   v1.** Allowing one later needs a per-origin user approval in Settings, and Chrome's Private Network Access
   preflight (`Access-Control-Allow-Private-Network`) on HTTP.
4. **Credentials:** a WS from a page cannot set `Authorization`, so it carries a **ticket** in
   `Sec-WebSocket-Protocol: whissle.v1, ticket.<ticket>` (never in the query string, which ends up in logs). Tickets are
   minted by the app's native side (§4.1): single use, 60 s TTL, bound to origin + capability. The page never holds
   the long-lived app key.

## 4. Identity and permissions

### 4.1 Registration and keys

```
POST /v1/apps/register   (IPC: peer identity; TCP: Authorization: Bearer <bootstrap_token>)
  { "app_id": "ai.whissle.outpost-luna", "name": "Outpost Luna", "version": "0.4.0",
    "engine": ">=1.2 <2", "models": [{"id":"arc-space-nft2","range":"^1"}],
    "origins": ["http://127.0.0.1:*"], "capabilities": ["ear","meta","tag","tts"] }
→ { "app_key": "wek_…", "status": "approved" | "pending_consent" }

POST /v1/tickets         (Authorization: Bearer <app_key>)  { "capability":"ear", "origin":"http://127.0.0.1:47310" }
→ { "ticket": "…", "expires_in": 60 }
```

- **`app_key`:** 32 random bytes, stored by the app in the Keychain (Mac) or DPAPI (Windows). The engine stores only
  its hash in `apps/<app_id>.json`. One key per app identity, rotated by re-registering.
- **What the `bootstrap_token` grants:** `register` and `GET /v1/info`, nothing else. Any same-user process can read
  `engine.json`, so the token proves only "same user, not a website". That is exactly the #84 boundary.
- **Being honest about same-user code:** a malicious process running as the same user can read another app's key
  (Keychain ACLs aside), ptrace it, or simply open the mic itself. Per-app keys give **attribution, quotas, consent
  and revocation**. They are not a security boundary against same-user malware, and the doc does not claim one. The
  security boundaries are other users, websites and tampered files (§9).

### 4.2 Peer identity on IPC (stronger than keys)

On a UDS, the engine reads the peer's audit token (`getsockopt(LOCAL_PEERTOKEN)`) and checks the peer's code signature
(`SecCodeCopyGuestWithAttributes` + `SecCodeCheckValidity` against a requirement). On a named pipe it uses
`GetNamedPipeClientProcessId` and checks the client exe's Authenticode chain (`WinVerifyTrust`) and its signer.

- Signed by **Whissle's Team ID / Authenticode subject:** first-party. Approved without a prompt, and the identity is
  `team_id + bundle_id` (Mac) or `signer + exe name` (Windows).
- Signed by **someone else:** the identity is that signer + bundle. One consent prompt (§4.3).
- **Unsigned** (dev builds, scripts): app key only, and allowed only when "Developer mode" is on in engine Settings.
- **Interpreters** (`python`, `node`): the peer is the interpreter, so the signature says nothing about the script.
  These are treated as unsigned. Outpost Luna's embedded Python backend is a **Whissle-signed** interpreter inside a
  Whissle-signed bundle, so it is identified as first-party by its path inside a valid signed bundle. Q9 asks whether
  that is good enough.

### 4.3 Consent and revocation

The engine has no window. It ships a small **Whissle Engine Settings** UI: a tiny Electron or native helper in
`versions/<v>/`, started on demand by the engine or from any client app's settings link. It shows:

- registered apps (name, signer, first and last seen, audio minutes this week, models used);
- an **Allow / Block** per app, and **Remove** (deletes the registration and lets its models' leases lapse);
- models on disk with sizes and which apps reference them;
- Developer mode, diagnostics (§8), version, and update state.

First-party apps never prompt. A third-party app's first `register` returns `pending_consent`, and the engine opens
Settings with an "Allow *X* to use Whissle speech on this computer?" sheet. **Revocation takes effect at once:** open
sessions of that app close with `4403 revoked`, its key hash is deleted, its tickets die. Re-allowing requires
re-registration.

### 4.4 Who owns the microphone: the app, always

**Recommendation: apps capture audio and send it. The engine never opens an input device.**

1. **The OS permission model is per app, and it should stay that way.** macOS TCC attributes mic access to the
   *responsible* process. A launchd agent asking for the mic gets a prompt reading "Whissle Engine would like to access
   the microphone", once, for every app that will ever use it. The user's per-app control in System Settings and in
   Windows Privacy → Microphone stops meaning anything, and the orange mic indicator names the wrong app.
2. **Least privilege.** An engine that cannot open the mic cannot be turned into a listening post by a bug, a
   malicious client or a tampered model. It hears only what an app chose to send, while the app shows its own
   indicator.
3. **Echo cancellation lives where the playback is.** Outpost Luna relies on the browser's AEC against its own in-page
   audio, and barge-in depends on it (`SESSION_CONTRACT.md` §2–4). An engine-side capture would get raw mic audio
   without a far-end reference. Each app also knows its own push-to-talk, mute and focus state. The engine does not.
4. **The cost is negligible.** PCM16 mono 16 kHz is 32 KB/s per stream over IPC.

What this gives up: an engine-owned always-on wake word shared by all apps, and capturing once when two apps listen to
the same mic (two apps means two streams and two decodes). Both are non-goals. A wake word, if wanted later, belongs
in the OS or DSP layer, or in an app (Q8).

## 5. Concurrency and scheduling

### 5.1 What libarc has to expose (requirements on the C API)

Today one `arc_nft2*` is weights + scratch + names + context + stream state, and one call runs at a time. Sharing
needs a split. The new calls are proposed for `arc.h`, versioned through `arc_abi_version()` (#86):

```c
/* Shared runtime: one ORT environment with a GLOBAL intra-op thread pool (OrtThreadingOptions,
 * DisablePerSessionThreads) and one prepacked-weights container, so N sessions do not each spin their own pool or
 * prepack their own copy of the weights. */
arc_runtime*    arc_runtime_create(int intra_threads, int inter_threads, char* err, size_t err_len);
void            arc_runtime_destroy(arc_runtime*);

/* Immutable, refcounted, thread-safe for concurrent reads: ORT sessions (Run() is thread-safe), the q4 decoder
 * weights, adapters, tokenizer, tag tables. safetensors mmap'd read-only. */
arc_nft2_model* arc_nft2_model_load(arc_runtime*, const char* dir, char* err, size_t err_len);
void            arc_nft2_model_retain(arc_nft2_model*);
void            arc_nft2_model_release(arc_nft2_model*);
size_t          arc_nft2_model_bytes(const arc_nft2_model*);      /* resident estimate, for accounting */

/* Per-session context: names list + RNNT bias trie, decoder context prompt, auto_prev history, streaming encoder
 * cache, scratch. Cheap to create (target < 5 ms, < 5 MB without audio). One call at a time PER CONTEXT;
 * many contexts may run at once on one model. */
arc_nft2*       arc_nft2_create_from(arc_nft2_model*, char* err, size_t err_len);
size_t          arc_nft2_ctx_bytes(const arc_nft2*);

/* Cooperative cancel, callable from any thread: the in-flight call returns NULL / ARC_ECANCELED at its next
 * checkpoint (between encoder chunks, between decoder steps). Target: back within 20 ms. */
int             arc_nft2_cancel(arc_nft2*);

/* Streaming partials from the cache-aware encoder + RNNT greedy path, without re-decoding the segment:
 * arc_nft2_stream_feed returns PARTIAL words for the open utterance as well as closed ones. And a cap on the
 * audio a stream keeps (today: "the stream keeps its audio until closed"). */
int             arc_nft2_stream_set_partials(arc_nft2_stream*, int every_ms);
int             arc_nft2_stream_set_max_audio_s(arc_nft2_stream*, float seconds);
```

The existing `arc_nft2_create` stays as `model_load + create_from` for in-process users (#93). Two items matter most:

- **Model/context split + global thread pool.** Without them a second session is a second ~0.6–0.9 GB, and N
  sessions each create their own ORT pool, oversubscribing the CPU.
- **Streaming partials.** The RNNT is streaming by construction, so partials from it are nearly free. That removes
  the quadratic re-decode that dominates the live load today (RTF 0.5 with partials vs 0.3 without). Final text
  stays the full Arc decode at the endpoint, unchanged.

Arc Tagger (`arctag`) already works this way: one handle per stream, a small pool for `tag_text`. Its weights are
12 MB, so it does not need the split. Steer TTS serializes on one lock, which is acceptable for v1 (TTS is short and
not on the ASR critical path), and it uses the same shared ORT runtime.

### 5.2 Engine scheduler

```
 sessions (per app)            job queues (engine-wide)                     workers (W, each T intra-op threads)
 ear A1 ─┐                     P0 live-final     FIFO            ─────▶   W0  reserved for P0/P1 while any live
 ear A2 ─┼─▶ admission ──▶     P1 live-partial   latest-wins/stream ───▶   W1  session is open
 meta B1 ─┘   (caps)           P2 batch          chunked ≤ 4 s audio  ─▶   W2 …  P2/P3 only when P0/P1 are empty
                               P3 background     warmup, self-test
                 within a priority: deficit round-robin across apps by audio-seconds, then FIFO per app
```

- **Jobs, not streams, are scheduled.** A job is one libarc call on one session context: a final decode, a partial,
  or a batch chunk. With one context per session, two sessions never contend for a lock. They contend only for workers.
- **Priorities.** `P0` live final (an utterance closed: the kid is waiting) > `P1` live partial > `P2` batch
  (`/v1/meta`, offline pipelines) > `P3` background. Strict between P0/P1 and the rest. Between P0 and P1, a final
  always goes first, and partials of a stream whose final is queued are dropped.
- **Partials are coalescable.** Each live stream has at most one pending partial job. A newer one replaces it
  (latest wins). Under load, partials thin out before anything else happens.
- **No preemption inside a call, so bound the calls.** Batch work is cut into ≤ 4 s audio chunks at segmenter
  boundaries (*estimate*: ≤ 1.2 s compute at RTF 0.3). While any live session is open, one worker is reserved for
  P0/P1. With `arc_nft2_cancel`, a P2 chunk older than 300 ms can also be cancelled and requeued when a P0 job has no
  free worker. Worst-case P0 queue wait: one live job, not one batch job.
- **Fairness.** Deficit round-robin by audio-seconds per app within a priority, so one app with 4 streams cannot
  starve another app's single stream. Per-app caps: `max_live_per_app` (default 2), `max_batch_inflight_per_app`
  (default 1).
- **Thread placement.** `W × T ≤ physical cores − 1`. Defaults: ≤ 8 cores: W = 2, T = 3; ≥ 10 cores: W = 3, T = 3.
  Live workers run at QoS `USER_INTERACTIVE` (Mac) or with power throttling disabled (Windows). Batch workers run at
  `UTILITY` (Mac) or with EcoQoS allowed (Windows).

### 5.3 Admission and backpressure

| Situation | Engine does | Client sees |
|---|---|---|
| live session cap reached (`max_live`, total or per app) | refuse at `hello` | `error busy` + close `1013` (as today), `retry_after_ms` |
| live stream falls behind (queued audio > 2 s) | drop its partials, keep finals | `{"t":"lag","behind_s":…}` once per episode |
| queued audio > 30 s on a live stream | close it | `error overloaded` + `1013` |
| client not reading (server send buffer > 1 MB) | drop pending `words final:false` and `frame`, keep finals | if > 8 MB: `error slow_consumer` + `1013` |
| batch | admitted, queued; the engine stops reading the request body while queued (TCP flow control) | latency, never an error unless memory pressure |
| memory pressure warn / critical | §2.5 | `error busy` with `reason:"memory"` |

### 5.4 Memory math

Inputs: *measured* process RSS 578 MB steady (packaged app: Python + ear + tagger + embedder + OS TTS) and 955–985 MB
(ear_compare, after load / peak). *Estimates*, to be replaced by Phase 2 measurements: ear weights + ORT arenas
resident ≈ 0.55–0.70 GB (`M`); per-worker scratch for a 15 s decode ≈ 80–150 MB (`w`); per-session context ≈ 3–6 MB
plus ≤ 1 MB audio (15 s float32 segment cap) (`s`); host runtime ≈ 0.10–0.15 GB (`h`).

| Config | Shared engine `h + M + W·w + S·s` | One engine per app (today's model ×N) |
|---|---|---|
| 1 app, 1 live session, W = 2 | 0.65 + 0.16–0.30 ≈ **0.85–1.0 GB** | ≈ 0.6–0.95 GB |
| 8 GB machine: 4 live sessions, W = 2 | ≈ **0.9–1.05 GB** | 4 × 0.6–0.95 ≈ **2.4–3.8 GB** |
| 16 GB machine: 8 live sessions, W = 3 | ≈ **1.0–1.2 GB** | ≈ 4.8–7.6 GB |

On an 8 GB machine the OS, a browser and the client apps already use ~5–6 GB. The engine's budget is ~1.2 GB, which
the shared design fits and per-app copies do not. Default caps follow from that: **8 GB → `max_live` 4; 16 GB+ →
`max_live` 8**, scaled down by RAM at start (`physical_ram − 6 GB`, clamped to 0.9–2 GB, divided by the per-session
cost).

Compute caps the number of sessions *speaking at once*, not the number open. One T = 3 worker at RTF ~0.3 (streaming
partials) sustains ~3 continuous speakers. Kids' sessions run at ~10–25% speech duty (Q11: measure it), so 4–8 open
streams per 2–3 workers holds, with the P0 reservation absorbing bursts.

mmap side note: libarc's own safetensors (q4 decoder, adapters) mapped read-only are shared page cache, even across
processes. ORT, though, prepacks MatMul weights into private memory per session, and `encoder.weights` (282 MB) is
the bulk. So per-process copies still pay most of the cost. That is why sharing has to happen inside one process (Q1).

## 6. Protocol `/v1`

### 6.1 Surface

| Endpoint | Kind | From today |
|---|---|---|
| `GET /v1/info` | instance, versions, capabilities, models (no auth beyond §3.4 rules; no app data) | `/health` (kept as alias) |
| `POST /v1/apps/register`, `POST /v1/tickets` | §4.1 | new |
| `WS /v1/ear` | live ear | `WS /v1/stream?ear=arc` (kept as alias through v1) |
| `WS /v1/ear?mode=metadata` | metadata-only form | `WS /v1/stream` |
| `POST /v1/meta` | whole clip | unchanged |
| `POST /v1/tag`, `WS /v1/tag/stream` | Arc Tagger | unchanged (`op` protocol) |
| `POST /v1/tts`, `GET /v1/tts/voices` | speech out | unchanged (+ `/steer`) |
| `GET /v1/metrics` | local metrics for this app (or all, for Settings) | new (#92) |

Schemas live in `protocol/v1/*.schema.json` (JSON Schema 2020-12), one per message `t`. They are the source for SDK
types and for the protocol fuzzer (#91). `make protocol-check` validates recorded sessions against them locally.

### 6.2 Ear stream messages

Audio: binary frames, PCM16 LE mono 16 kHz, any length. 80 ms recommended, 20–500 ms accepted. Time on every server
message is **audio-seconds since the first sample** (`at`), which is the engine's only clock.

```
client → engine
  {"t":"hello","protocol":[1],"app":{"id":"ai.whissle.outpost-luna","version":"0.4.0"},
   "engine":">=1.2 <2",
   "want":{"model":"arc-space-nft2@^1","domain":"assistant","partials":true,"names":true,
           "events":true,"frames":false},
   "priority":"live",                          // live | batch
   "names":[{"name":"Artemis II","kind":"mission","aliases":["Artemis 2"]}]}   // optional, same as a context frame
  {"t":"context","names":[…],"terms":[…],"topic":"…","mission":{…},"telemetry":{…}}   // as today, STREAMS.md
  {"t":"end_turn"}  {"t":"stop"}  {"t":"ping","id":n}

engine → client
  {"t":"ready","protocol":1,"session":"s_…","engine":"1.3.0",
   "model":{"id":"arc-space-nft2","revision":"176d324"},
   "granted":{"partials":true,"names":true,"events":true,"frames":false},
   "limits":{"max_names":40,"max_turn_s":15,"max_frame_ms":500},
   "deprecations":[]}
  {"t":"turn","state":"start"|"end","text","at"}                         // unchanged
  {"t":"words","text","final":false,"at"}                                // unchanged
  {"t":"arc","device_directed","directed_head","directed","names",…,"at"}   // unchanged
  {"t":"words","text","final":true,"spoken","names","tags","conf","alts","at"}   // unchanged
  {"t":"context_ack","v","names","names_to_arc",…}                       // unchanged
  {"t":"lag","behind_s"}  {"t":"pong","id"}
  {"t":"error","code","message","retry_after_ms"?}                       // then close, if fatal
```

Compatibility: a client that sends audio or `context` without `hello` gets **legacy mode**: today's `ear` and
`emotion` greeting frames, defaults for everything, and `app_id = "legacy"` with the lowest fairness weight. This mode
exists so `listen.py` keeps working unchanged through Phase 2. It is removed in v2.

Names are now **per session**. Each session context holds its own list, so two apps (or two screens) with different
lists no longer thrash the model's bias state, which they do today.

### 6.3 Error codes

| `code` | WS close | HTTP | Meaning | Retry? |
|---|---|---|---|---|
| `bad_request` | 1008 | 400 | schema violation, bad audio framing | no |
| `unauthorized` | 4401 | 401 | missing/invalid key, ticket, or peer identity | after re-register |
| `forbidden` / `revoked` | 4403 | 403 | app blocked or revoked; origin not allowed | no |
| `pending_consent` | 4403 | 403 | waiting for the user (§4.3) | after consent |
| `protocol_unsupported` | 4426 | 426 | no common protocol major; `ready` never sent | no; engine range in `message` |
| `model_unavailable` | 4404 | 404 | requested model/range not installed or failed its load check | after install |
| `busy` | 1013 | 503 | admission refused (cap or memory) | yes, `retry_after_ms` |
| `overloaded` / `slow_consumer` | 1013 | — | §5.3 | yes, back off |
| `shutting_down` | 1001 | 503 | update swap / idle exit raced the connect | yes, at once (new instance) |
| `internal` | 1011 | 500 | engine bug; a diagnostics hint is logged | yes, with back-off |

1008, 1011 and 1013 keep the meaning they have in `tag_stream.py` and `routes_meta.py` today.

### 6.4 SDKs

Both SDKs are thin and generated where possible: types come from the schemas, and the rest is discovery, launch,
reconnect and error mapping. They live in this repo (`sdk/js`, `sdk/python`) until a second app depends on them,
then move to their own repo.

```ts
// JS (Node / Electron main). Browser builds take a ticket instead of an app key.
import { Engine } from "@whissle/engine";
const eng = await Engine.connect({ app: { id: "ai.whissle.outpost-luna", version }, engine: ">=1.2 <2" });
const ear = await eng.ear({ domain: "assistant", names, partials: true, priority: "live" });
ear.on("words", (m) => …); ear.on("turn", …); ear.on("arc", …); ear.on("lag", …);
ear.push(pcm16); ear.context({ names }); ear.endTurn(); await ear.stop();
const ticket = await eng.ticket({ capability: "ear", origin });     // hand to a renderer
```

```python
# Python (Luna's backend replaces its hand-rolled websockets client in listen.py with this)
async with Engine.connect(app_id="ai.whissle.outpost-luna", engine=">=1.2 <2") as eng:
    async with eng.ear(domain="assistant", names=names, priority="live") as ear:
        await ear.push(pcm16)
        async for msg in ear:            # typed messages (pydantic, generated)
            ...
```

What the SDKs handle: reading `engine.json` and validating staleness, launching the engine (§2.3 / §2.4), IPC first
with TCP as fallback, `hello` and the version check, reconnecting with jittered back-off (250 ms → 8 s) on `1013` or
`1001` and on engine restarts, and surfacing `lag` and `busy` as events rather than exceptions.

### 6.5 Deprecation policy

- **Within v1 only additive changes:** new optional fields, new message types, new capabilities. Clients must ignore
  unknown fields and unknown `t`. The engine must ignore unknown client fields. The schemas use
  `additionalProperties: true` for exactly this reason.
- A field or message is removed only in a new major. `/v2` ships alongside `/v1`, and `/v1` is served for **≥ 12
  months and ≥ 2 engine minor releases after v2 is final**, whichever is longer.
- Deprecated items are announced in `ready.deprecations` (`{"feature","sunset":"2027-11-01","use":"…"}`), counted in
  local metrics, and listed in Settings per app, so the user can see which installed app will break.

## 7. Updates

**Artifacts.** Engine build = a signed bundle per OS (Developer ID + notarization on Mac; Authenticode on Windows,
#89). Models = sha256-pinned tars, as today. Both are listed in one **release manifest** (schema 3 = the schema 2 of
`updates.js` + `engine` entries + `protocols`), **signed with Ed25519 (minisign)**. That is the "future hardening" in
`docs/DESKTOP.md`, now required. The public keys ship in the launcher: two keys, the second kept offline for rotation.
A manifest that fails the signature check is ignored as a whole, like a manifest that fails validation today.

**Flow** (`updates.js`'s check → stage → swap → confirm or roll back, moved into the engine):

1. **Check** daily while the engine runs, and on demand from Settings. Offline means nothing changes. The offline
   pack keeps working, with its manifest signed too.
2. **Stage** in the background: download into `.dl/` (resumable), verify the sha256, unpack into `staging/<v>/` or
   `models/<id>/<sha>/`, then verify every file against the manifest (#85).
3. **Swap engine** only when idle (no sessions): replace `active.json` atomically with `{"version":new,
   "previous":old, "trial":true}`, exit, and the next connect starts the new version.
4. **Confirm**, within 60 s of the trial start: protocol self-test (`/v1/info`), every installed model's load check,
   and a **golden clip** (a 3 s embedded clip whose transcript and names must match) on the ear. Pass → `trial:false`,
   old version kept as `previous`. Fail, or a crash during trial → `active.json` back to `previous`, the new version
   marked rejected and never offered again. Same as the asset rollback today.
5. **Models** update separately from the engine. A new model version is installed next to the old one, and sessions
   pick it up on their next `hello`. A session never changes model mid-stream. At most two versions of one model may be
   resident; past that, a session pinned to an older range gets `model_unavailable` with the installed range in
   `message`.

**Compatibility declarations.** An app declares `engine: ">=1.2 <2"` and model ranges at registration. The engine
manifest declares `min_engine` per model, and the engine's protocol majors. **The engine never downgrades.** Each
client app ships an engine payload. If the installed engine is older than the app needs (or absent), the SDK installs
the bundled one, and only when it is newer than what is installed. If the installed engine is a newer major the app
does not speak, `/v1` is still served (§6.5).

**No paid CI** (#91). Releases are built on the Mac and Windows build machines. `make release-check` must pass before
anything is signed: golden-audio WER and latency gates, the C API and protocol fuzz run, the 24 h soak, and here a
4-session concurrency soak with an update and rollback drill. Signing keys stay on a hardware token attached to the
build machine. The manifest is published as now (`scripts/publish_site.sh` → GitHub Pages).

## 8. Observability and privacy

- **Never stored:** audio (no capture-to-disk mode in v1, no debug flag that writes audio), and transcripts in logs.
  Logs carry lengths, timings, codes and model ids, never text. A `log_text` switch exists in Developer mode only,
  expires after 24 h, and says so in Settings.
- **Logs:** JSON lines, `logs/engine.log`, rotated 5 × 10 MB.
- **Local metrics** (#92): `metrics/` holds minute buckets for 30 days (SQLite or rotated JSONL), per app and per
  model: sessions, audio-seconds, queue wait p50/p95 per priority, decode ms p50/p95, turn-end latency, partial drop
  rate, `busy` / `overloaded` counts, crashes, crash-free session rate, RSS. Served at `GET /v1/metrics` (an app sees
  its own; Settings sees all). Nothing is sent anywhere.
- **Diagnostics bundle** (#92): user-initiated from Settings or any client's "Send diagnostics". A zip in `diag/`,
  shown in Finder/Explorer. The user decides where it goes. Contents: logs, metrics, `engine.json` **without the
  token**, `active.json`, model ids + sha256s + load-check results, hardware/OS summary, app registry (ids, signers,
  versions; no keys), and crash reports. **Crash dumps are minimal** (Windows `MiniDumpNormal` without heap; Mac
  `.ips` reports without memory). A full heap dump would contain live audio buffers.

## 9. Threat model

| Adversary | Attack | Mitigation | Residual |
|---|---|---|---|
| **Other local OS user** | connect to the engine, read its files, hear another user's audio | per-user engine; dir 0700 / owner-only DACL; UDS 0600; pipe DACL = user SID + `PIPE_REJECT_REMOTE_CLIENTS`; TCP needs key/ticket from 0600 files | root/admin can read anything (out of scope) |
| **Malicious website** | `ws://127.0.0.1:port` from a page (no CORS on WS); DNS rebinding; port scan | §3.4: `Host` check, exact `Origin` allow-list (public origins refused), ticket in subprotocol, no key reachable from a page; random port per launch | a page can learn the engine is running from timing or refusals; it gets nothing else |
| **Malicious local app, same user** | use the engine, exhaust it, impersonate Outpost Luna | peer signature on IPC (it cannot claim Whissle's Team ID); per-app caps and fair scheduling; consent + revocation; attribution in metrics | **not a boundary**: same-user code can read keys or use the mic directly. The engine adds no capability it lacked (it cannot hear anything no app sent) |
| **Sandboxed local app** (MAS, AppContainer) | — | cannot reach the UDS or pipe without entitlements, so it cannot use the engine (Q12) | functional gap, not a security one |
| **Tampered models on disk** | swap `encoder.weights` / ONNX graphs to crash or exploit the parser | sha256 of every file checked at install and at load (#85); ORT pinned (#85); models dir writable only by the engine; ONNX/safetensors parsing fuzzed (#91) | an attacker with same-user write access can also replace the engine binary. Code signing + a launcher signature check on `versions/<v>` raises the bar (Mac: notarized; Windows: Authenticode check in the launcher) |
| **Network attacker / compromised host** | MITM or replace update artifacts | https + host allow-list (as today) **and** Ed25519 signature over the manifest; sha256 per artifact; engine code signing | a stolen signing key: two keys, offline rotation key, hardware token |
| **Malformed input from a client** | crafted audio or JSON to crash libarc | schema validation; frame size limits; C API + protocol fuzzing (#91); a decode watchdog (#87) cancels a hung call and kills the worker | an engine crash drops every client's session. Clients reconnect; the scheduler requeues nothing (live audio is gone) |
| **Privacy leak through the engine's own outputs** | transcripts in logs, audio in crash dumps or diagnostics | §8: no text in logs, minimal dumps, no audio anywhere | Developer-mode `log_text`, time-boxed and visible |

## 10. Migration from today's embedded model_server

| Phase | Work | Acceptance criteria |
|---|---|---|
| **0: now** (#84–#88) | Origin + token on every endpoint; pinned ORT + model sha256 at load; `arc_abi_version()` + generated bindings; supervision + watchdog; free ports + discovery file | the issues' tests: hostile-origin WS refused; a tampered model file is refused; ABI mismatch fails loudly; killing the model server mid-turn shows "ear restarting" and recovers; no fixed port |
| **1: protocol** | `protocol/v1/*.schema.json`; `hello`/`ready`, error codes, `lag`, legacy mode in `model_server`; `/v1/ear` + aliases; JS + Python SDKs; Luna's backend moves to the Python SDK | `listen.py` behaviour unchanged (existing tests + a recorded-session replay byte-compares the client-visible messages); every recorded session validates against the schemas; protocol fuzz 1 h with no crash |
| **2: pool + scheduler** (still embedded) | libarc: `arc_runtime`, `model_load` / `create_from`, `cancel`, streaming partials. Engine: per-session contexts, priority queues, coalescing, caps, memory-pressure handling, metrics | on an 8 GB M1 and an 8-core Windows laptop with 4 concurrent live streams + 1 batch job: RSS ≤ 1.2 GB; **live turn-end p95 ≤ single-stream p95 + 150 ms**; no live final waits behind batch (max P0 queue wait ≤ one live job); first-words p50 ≤ 800 ms (today 1059 ms); WER unchanged on the golden set (±0.3 pt); 24 h soak with no RSS growth > 5% |
| **3: engine install** | per-user engine dir, launcher, `active.json`; launchd agent with socket activation (Mac), spawn + mutex (Windows); `engine.json` schema 1; registration, app keys, peer identity on UDS; Settings UI; model store with leases. Luna installs the engine from its bundle and uses it; the embedded server stays as an automatic fallback for this one release | Luna + a second client (Head Start, or the SDK's sample CLI) run at once against one engine with one copy of the weights (RSS check); quitting Luna does not stop the other client's session; deleting Luna leaves the engine working; idle shutdown frees all memory after 10 min; a crash mid-session recovers on reconnect in ≤ 5 s (warm); hostile-origin and other-user tests pass against the engine |
| **4: updates + cleanup** | signed release manifest, engine self-update with trial + rollback, model side-by-side versions; remove Luna's embedded model server and its fallback; third-party consent flow | update drill: a deliberately broken engine build rolls back on its own within 60 s with no user action; unsigned manifest ignored; a model update while a session is live does not affect that session; Luna's installer shrinks by the engine payload when an engine is already installed (Q10) |
| **5: native host** (decision) | replace the Python host if Phase 2–4 measurements justify it; Windows named pipe + peer identity | same protocol tests pass unchanged; RSS −100 MB or more; live p95 no worse |

Rollback at every phase: Luna keeps the previous path behind a setting (`EAR_ENGINE=embedded|shared`) until the phase
after next.

## 11. Open questions for review

1. **Weight sharing.** In-process contexts on one model (this design) vs. per-app processes sharing mmap'd weight pages.
   ORT's per-session prepacking makes the second path cost most of the memory anyway. Did you see a better split,
   e.g. prepacked weights serialized once to disk and mmap'd?
2. **Preemption.** Reserved live worker + chunked batch + cooperative cancel at encoder-chunk/decoder-step boundaries.
   Is 20 ms checkpoint granularity realistic for the decoder? Would you rather have resumable jobs than cancel + redo?
3. **Partials.** RNNT streaming partials with the Arc decoder only at the endpoint means partial and final text come
   from different decoders and can diverge. What divergence did users tolerate, and did you gate partials on stability?
4. **Threads.** One global ORT intra-op pool shared by W workers vs. W pools of T threads. And on QoS: is
   `USER_INTERACTIVE` for a windowless agent defensible on battery? Is disabling EcoQoS on Windows enough?
5. **Model vs. engine release cadence.** Independent model updates with side-by-side versions, or lock-step releases?
   How large was your compatibility matrix in practice?
6. **Quantization.** `encoder.weights` is 282 MB of the 460 MB. Is an int8 encoder worth its accuracy cost for this
   memory budget, given that the decoder is already q4?
7. **Licensing.** libarc and the model releases are CC BY-NC 4.0 (`arc.h`). A shared engine that third-party
   commercial apps can call needs a different licence or a gated registration. That is a business decision this design
   depends on.
8. **Wake word / always-on.** "The engine never opens the mic" rules out a shared wake word. Where did keyword
   spotting live in your stack (DSP, app, OS service), and would you keep this rule?
9. **Identity.** Code signature via peer audit token (Mac) / Authenticode of the pipe client (Windows) as the app
   identity, with keys as the fallback. Is the "signed interpreter inside a signed bundle" rule for Luna's Python
   backend sound, or should the backend get a ticket from Electron's main process instead?
10. **Who installs the engine.** Apps carry the engine payload (~0.5 GB with Python today) vs. a small bootstrapper
    that downloads it. The second keeps each app small but breaks offline-first install, which matters for schools.
11. **Capacity defaults.** The `max_live` defaults rest on a speech-duty estimate of 10–25% for kids' sessions. What
    duty and concurrency distributions did you size against for multi-app desktops?
12. **Mac IPC.** UDS + socket-activated LaunchAgent (cross-platform parity) vs. an XPC Mach service in a helper app
    registered with `SMAppService` (native, survives app deletion if the helper is its own bundle, reachable from
    sandboxed apps through an entitlement). Which would you ship?
13. **Per-user vs. per-machine.** Family and school PCs with fast user switching run two engines with two copies of
    the weights. Is a per-machine model store (read-only, shared) with per-user engines worth the admin install it needs?
