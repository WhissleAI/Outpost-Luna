# Input streams to the models (what is passed today)

Short and factual. The long plan for using game telemetry as model input is written separately.

## The ear: `EAR=arc` (default) or `EAR=deepgram`

With **`EAR=arc`** (local; see `docs/LOCAL_EAR.md`) `/ws/listen` opens one model-server stream, `WS /v1/stream?ear=arc`,
and nothing else: Arc v1.1 Mini's own decoder gives the words (`words`, written form, revisions), the turns
(`turn start|eager|resumed|end`) and the metadata (`arc`, `emotion`). The backend sends the lunar Tier A list
(`keyterms.tier_a`, ~74 names) as context first and puts a client context frame's names in front of it. If the Arc
ear is down or full the session uses Deepgram Flux when a key is set (`{"t":"ear","ear":"deepgram","fallback":…}`), else
sends `error` (the browser falls back to Web Speech push-to-talk). The table below is the **`EAR=deepgram`** path.

In ear mode `names`, `terms` and `topic` reach Arc's **decoder context memory** (`Stream.set_context`, ack
`terms_to_arc: true`) and `names` also its name linker (`set_names`). The decoder prompt keeps only ~40 tokens of
names + terms (in order: ~10–12 names), so order matters; all names reach the linker, whose matches rewrite the final
text to the list's spelling (`transcript_written`).

## The streams (EAR=deepgram)

| Stream | From | Path | Reaches |
| --- | --- | --- | --- |
| Mic audio, PCM16 mono 16 kHz, ~80 ms frames | browser | `/ws/listen` → Deepgram Flux **and** model server `WS /v1/stream` | Flux (words, turns); Arc v1.1 Mini (act, intent, device_directed, command_complete, speaker, audio events) |
| Words | Deepgram Flux | backend → client (`words`, `turn`) | Director via `/api/ask` text; not fed back to Arc's stream today |
| **Context** `{"t":"context","mission":{…},"names":[…],"terms":[…],"telemetry":{…}\|[…]}` | browser, any time | `/ws/listen` → model server `/v1/stream` (keys limited to `mission names terms telemetry topic`; names/terms ≤ 200 items) | see below |
| Ack `{"t":"context_ack","v","names","terms","names_to_arc","terms_to_arc","at_audio_s"}` | model server | → `/ws/listen` → browser | client |

Context is never sent to Deepgram. `/v1/stream` keeps only the latest context per connection
(`model_server/app/stream_context.py`) plus a ring of the last 600 telemetry / mission frames.

## What Arc can and can't use today

Arc runs in external-transcript mode (`transcript="external"`, `load_decoder=False`, `fallback=None`; see `arcmeta.MetaStream`).

| Field | What happens | Arc uses it? |
| --- | --- | --- |
| `names` | `Stream.set_names(names)` on the live Arc stream (strings or `{"name","aliases","kind"}`) | **Yes, for name linking**: the linker / snap checks name spans in the incoming words against the list. But `MetaStream` does not emit Arc's `names` records yet, so nothing downstream sees the links. Verified live on :8242: `names_to_arc: true`. |
| `terms` | recorded | **No.** Terms, topic and previous text are *decoder* context (`Stream.set_context`); the decoder isn't loaded here, so the call would be a no-op. They'd matter with `backbone="full"` / builtin transcript. |
| `mission`, `telemetry` | recorded, stamped with `at_audio_s` (seconds of audio fed so far) and wall time | **No.** No Arc head takes non-audio input. It is a time-aligned side channel. |
| (all) | the latest context is attached to every emitted `{"t":"arc"}` message as `context: {v, names, terms, telemetry}` | for consumers joining model output with game state |

Before the mission frames can affect what the models hear, one of these has to happen: (1) emit Arc's linked `names` from
`MetaStream`, (2) load the decoder so `terms`/topic bias recognition, or (3) train a head that takes telemetry as input.
Today the game state changes what the **Director** does (`context.mission` on `/api/ask`), not what Arc hears.

## Telemetry frames

The sim's `WS /ws/mission/{mid}` frame (`docs/MISSION_CONTRACT.md`) can be forwarded as `telemetry` unchanged:
`mission_time_h, power, life_support, dose_msv, dose_rate, sun_elev_deg, earth_elev_deg, comm, loads, alerts`.
Send one frame per second at most; the server keeps 600.
