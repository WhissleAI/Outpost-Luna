# Input streams to the models (what is passed today)

Short and factual. The long plan for using game telemetry as model input is written separately.

## The streams

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
