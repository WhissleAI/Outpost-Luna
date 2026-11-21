# Diagnostics: local logs, local metrics, the diagnostics file

Issue #92. Everything here stays on the computer. Nothing is ever uploaded: no telemetry, no crash reporter, no network
call of any kind. A grown-up can save a **diagnostics file** (a zip) and choose to send it to us; that is the only way any
of this leaves the machine.

Never collected anywhere in this system: audio, what was said or typed (transcripts), names the user said or typed, the
call sign, the turn log (`docs/DIRECTOR_LOOP.md`, on by default since 0.4.3, separate), the per-launch token.

**On-device learning** (`docs/ON_DEVICE_LEARNING.md`): the file has `learning.json` with the learned numbers (echo
delay and threshold for this computer; per cadet: how many names were learned, end-of-turn silence, thresholds). The
learned names themselves (the heard form, e.g. "ticko" -> Tycho) and the kid's own yes / no words are in it **only**
when the grown-up ticks "Include the names the app learned" next to the save button.

## 1. Where it lives

Under the app's per-user folder (`~/Library/Application Support/Outpost Luna/` on macOS, `%APPDATA%\Outpost Luna\` on
Windows, `~/.config/Outpost Luna/` on Linux; `docs/DESKTOP.md` "Where things go at run time"):

| Path | What | Written by |
|---|---|---|
| `logs/main.jsonl` | the shell's structured log | Electron main (`desktop/main/diag.js`) |
| `logs/backend.jsonl` | the backend's structured log | `backend/app/diag.py` |
| `logs/models.jsonl` | the model server's structured log | `model_server/app/diag.py` |
| `logs/{main,backend,models}.log` | the human-readable lines (unchanged; `docs/BUILD_WINDOWS.md` still asks for them) | as before |
| `metrics/daily-{main,backend,models}.json` | one bucket per local day, the last 30 days | each process |
| `metrics/session.json` | the running session (one app launch) | Electron main |

The shell passes the folders to its children as `LUNA_LOG_DIR` and `LUNA_DATA_DIR`. Without them (a bare `make backend`
/ `make models`, the test suites) nothing is written; the metrics still count in memory.

**Size caps.** Each `.jsonl` rotates at 5 MB and keeps 5 files (`main.jsonl`, `main.jsonl.1` … `.4`): at most 75 MB for
all three. The human-readable `.log` files are moved to `<name>.log.1` at launch when they pass 5 MB (one old copy kept).
The daily files keep 30 days (a few KB each). Settings → Reset keeps `logs/` and `metrics/` (`docs/RESET.md`): nothing in
them is about the user.

## 2. The structured logs

One JSON object per line:

```json
{"ts":"2026-11-16T19:42:17.128Z","level":"error","svc":"main","event":"child_exit","child":"models","code":null,"signal":"SIGKILL","up_s":48}
```

`ts` (UTC), `level` (`info` | `warning` | `error`), `svc` (`main` | `backend` | `models`), `event`, then the event's fields.

| svc | events |
|---|---|
| main | `launch` (version, platform, `previous_session`: clean / crashed), `child_start`, `child_exit`, `child_hung`, `child_gave_up`, `session_end` (`crash_free`), `diagnostics_saved`, and `log` (every `main.log` line, scrubbed, as `msg`) |
| backend | `start`, `stop`, `listen_close` (ear, turns, errors, seconds open), `listen_error` (code), `ear_unavailable` (reason), `http_error` (status, path), `unhandled` (exception type, path), `mission_load`, `mission_save_failed`, `mission_load_failed`, `diagnostics_bundle` |
| models | `start`, `stop`, `model_load` (model, ok, seconds, error, ABI), `ear_stream_open`, `ear_stream_close` (audio seconds, compute seconds, RTF, turns), `ear_unavailable`, `decode_timeout`, `model_reset` |

**Scrubbing** (`scrub()` in `diag.py`, `scrub()` in `diag.js`; the same rules, a test checks the key lists match). Every
field passes through it before it is written:

- the value of any key in the sensitive list is replaced with `[scrubbed]`: `text`, `transcript`, `words`, `spoken`,
  `heard`, `entity`, `names`, `name`, `said`, `question`, `answer`, `query`, `prompt`, `message`, `callsign`, `audio`,
  `pcm`, `wav`, `token`, `authorization`, `cookie`, `api_key`, … and any key ending in `token`, `secret`, `password`,
  `_key`, `cookie`, `_text`, `_words`;
- bytes become `[bytes]` (audio never reaches a file);
- in free text: the live token, anything after `Bearer` / `luna_token=` / `X-Luna-Token:` / `token=`, any 32+ character
  token-like run that is not plain hex (a sha256 stays readable), and the home folder (`/Users/<name>` → `~`);
- strings are cut at 300 characters.

The code only ever logs counts, durations, codes and states. The scrubber is the second net, for a field someone adds
later.

## 3. Local metrics

Counters and fixed-bucket histograms in each process (`METRICS` in `diag.py`). Quantiles are estimated inside the bucket
(latency buckets 1 ms … 20 s).

| GET | Answers | Auth |
|---|---|---|
| model server `/metrics` | its counters, histograms (n, p50, p95, p99, mean, max), gauges, RSS | the token, even for a GET |
| backend `/api/metrics` | the same for the backend | the token, even for a GET |

The token rule is the local guard's (`docs/SECURITY.md`): the app's own page sends it as its `luna_token` cookie, a local
tool sends `X-Luna-Token` or `Authorization: Bearer` (from `engine.json`). No token → 401. Host and Origin are checked as
for every request. With no `LUNA_TOKEN` set (dev, tests) the token is not required.

| Metric | Where | What |
|---|---|---|
| `ear_decode_ms{kind=partial\|final}` | models | one decode of the open segment (partials while the kid talks; the final at the turn's end) |
| `ear_rtf{kind=partial\|final}` | models | decode time / audio length of that decode |
| `ear_queue_ms` | models | a stream's call waiting for its worker thread |
| `ear_lock_wait_ms` | models | a decode waiting for the shared model (another stream holds it) |
| `ear_streams`, `ear_turns{end=silence\|end_turn\|stop\|max_turn}`, `ear_segments_no_speech` | models | streams opened, turns closed (and why), noise-only segments |
| `model_resets{model=arc_ear}` | models | the decode watchdog dropped a hung model handle (`docs/ROBUSTNESS.md`) |
| `tag_ms` | models | `POST /v1/tag` |
| `ear_sessions_open`, `ear_loaded` (gauges) | models | live |
| `listen_sessions`, `turns{ear=arc\|deepgram}` | backend | `/ws/listen` sessions, turns relayed to the page |
| `mission_saves`, `mission_save_failures`, `mission_loads`, `mission_load_failures` | backend | the mission auto-save and Continue (counted around `app/mission/registry.py`, which is unchanged) |
| `errors{code=…}` | both | `decode_timeout`, `ear_unavailable`, `ear_load_failed`, `tagger_load_failed`, `http_<5xx>`, `unhandled_<Exception>`, `mission_save_failed`, `mission_load_failed`, relayed `/ws/listen` errors |
| `rss_mb` (`now`, `peak`) | both | resident memory of that process |
| `sessions`, `sessions_crash_free`, `sessions_not_crash_free`, `restarts{child}`, `health_kills{child}`, `gave_up{child}` | main (`daily-main.json`) | see below |

**Crash-free sessions.** A session is one app launch. `metrics/session.json` marks the running one. It is crash-free when
the app quits normally and no child restarted during it. Not crash-free: a child crashed or hung and the supervisor
restarted it (`docs/DESKTOP.md` "Process supervision"), the app failed to start, or the app itself died (the next launch
finds the session unfinished and counts it). The diagnostics file shows the 30-day rate.

**Daily summary.** Every 60 s and at shutdown each process adds what it counted since the last write into today's
bucket of `metrics/daily-<svc>.json` (histograms kept raw so days merge, with their p50 / p95 / p99 alongside). A process
that is killed loses at most the last minute.

## 4. The diagnostics file

Settings → **Help & diagnostics** lists what the file holds, then **Save a diagnostics file…**. The desktop shell opens a
save dialog (the user picks the folder; the default is Downloads, `outpost-luna-diagnostics-YYYY-MM-DD.zip`), the backend
builds the zip (`POST /api/diagnostics/bundle`, token required), the shell writes it there. The page says Saved.

| In the zip | From |
|---|---|
| `README.txt` | what this file is, and what is never in it |
| `system.json` | app version, Electron / Chrome / Node versions, OS name / release / arch, CPU model, cores, memory. No host name, no user name |
| `versions.json` | app, ABI, ONNX Runtime (pinned + wheel), each model's id / revision / load state and its sha256 check (`verify`) |
| `engine.json` | the running engine's `engine.json` without its `token` |
| `health/backend.json`, `health/model_server.json` | `/api/health` and `/health` at that moment |
| `metrics/backend.json`, `metrics/model_server.json`, `metrics/main.json` | the live metrics (main: this session, its restarts, each Electron process's memory) |
| `metrics/daily-*.json` | the 30-day summaries |
| `logs/*.jsonl` | the newest structured logs (at most 8 files, 24 MB) |

Never in it: audio files, transcripts, the turn log, names, the token, the human-readable `.log` files (third-party output
we do not control). Every JSON part goes through the scrubber again, and each log line is re-parsed: a line that is not one
of our JSON objects is dropped. `backend/tests/test_diagnostics.py` plants transcripts, names, a `.wav`, a turn log and the
token in the folders and checks none of them reaches the zip.

**Sharing it.** It is an ordinary zip: open it to see every file before sending. Attach it to a GitHub issue or an email
to the team. Typical size: 10–200 KB.

In a browser (`make dev`), the button downloads the same zip through the browser.

## 5. For developers

```bash
T=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["token"])' "$HOME/Library/Application Support/Outpost Luna/engine.json")
curl -s -H "X-Luna-Token: $T" http://127.0.0.1:47210/metrics | python3 -m json.tool      # ports: engine.json
curl -s -H "X-Luna-Token: $T" http://127.0.0.1:47310/api/metrics | python3 -m json.tool
```

Add a metric: `diag.METRICS.inc("name", label=value)` or `diag.METRICS.observe("name_ms", ms, kind=...)`; an event:
`diag.LOG.event("name", field=value)`. Log counts and codes, never content. `backend/app/diag.py` and
`model_server/app/diag.py` are one file in two places (`model_server/tests/test_diag.py` fails if they drift).

Tests: `backend/tests/test_diagnostics.py` (scrubbing, rotation, daily summary, endpoint auth, bundle contents, mission
counts), `model_server/tests/test_diag.py` (endpoint auth, decode / RTF / queue / reset metrics),
`desktop/main/diag.test.js` (the shell's log, crash-free sessions, the save hand-over), `frontend/tests/diagnostics_ui.test.js`.
