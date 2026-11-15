# Settings: voices, rate, expressiveness, listening filter, level

The kid's Settings panel (UI: `feat/ux-v3`) picks the guide's voice (one of this computer's own offline voices, below),
how fast and how lively it talks, how picky the
always-open mic is, the kid's level and whether the mic is hands-free or push-to-talk. The backend serves the voice list
and applies the rest on the session. **Nothing about the child is stored server-side**: the client keeps the Settings
and sends them on every connect.

## Contract

```
GET /api/voices                      → [{id, name, desc, preview_url}]   (this machine's OS voices, best first; ≤ 12)
GET /api/voices/preview/<id>.wav     → "Hello! Ready to fly?" in that voice (rendered on first use through /api/tts,
                                       so it is mastered to −14 LUFS and cached like every line; offline)

WS /ws/session, after hello and on every change:
  {t: "prefs", type: "prefs", voice, voice_all, rate, expressiveness, filter, level, listen, volume}
  ← {t: "prefs", applied: {voice, voice_all, rate, expressiveness, filter, level, listen, volume}}
```

Either `t` or `type` works. Every field is optional (a partial update keeps the others); an invalid value is ignored
and the ack shows what is in force. `prefs` may also ride on `hello` as `hello.prefs`.

| field | values | default | effect |
| --- | --- | --- | --- |
| `voice` | an id from `/api/voices` (or `null` / `"default"`) | `null` (the guide's role: this machine's best voice) | the OS voice of the guide, CAPCOM and the story |
| `voice_all` | bool | `false` | `true`: Houston uses it too; otherwise Houston keeps its own radio voice |
| `pack` | bool | `true` | the recorded guide voice for fixed lines (docs/VOICE_PACK.md); only with the default voice at 1× |
| `rate` | 0.6–1.6 (UI: 0.75 / 1 / 1.25 / 1.5) | 1 = the voice's own pace | `steering.delivery`: no baseline at 1× (the voice's own rate and pauses, no `say -r`; docs/VOICE_PACK.md) plus 4 rate z per octave; 0.75× is slower than the old 1× (VOICE_STEERING.md §4d) |
| `expressiveness` | 0–1 | 0.5 (today's delivery) | carried on the style (melody range, calmer tags at the low end, below); the OS voices have no such control, so today it does not change how they sound |
| `filter` | `relaxed` / `normal` / `strict` | `normal` | the router's device-directed thresholds (below) |
| `level` | `cadet` / `commander` | `cadet` | passed through to the Director, mission sim and Academy; no behaviour change yet |
| `volume` | 0–2 (UI 100% = 1) | 1 = −14 LUFS | master volume, applied on the server before the limiter: 20·log10(volume) dB, so 2 = +6 dB into the −1 dBTP limiter (louder but not clipped) and below 1 is a plain cut. Send it here, not as client gain: client gain above 100% would clip |
| `listen` | `handsfree` / `ptt` | `handsfree` | `ptt`: open-mic turns from the ear relay (and the client's `source:"voice"` copy) are ignored and never take the floor or barge in; only push-to-talk (`source:"ptt"`) and typed turns count |

### How the voice, rate and expressiveness reach the TTS

Every `say` decision the session emits gets them on its `style`, declaratively: `style.tts_voice` (the persona's role
or the chosen one), `style.speed` (the rate), `style.expr` (expressiveness) and `style.volume`. The client already forwards
`say.style` to `/api/tts`, and `tts.clean_style` applies them there, in one place:

- `tts_voice` is used only when it's an installed voice or a persona role (`voices.allowed`); otherwise the persona's
  role. `voices.resolve` then turns a role into the voice the model server gave it, so the TTS cache key names the
  real voice (`voices.cache_tag` adds the voice behind "system"): a newly installed or switched voice never replays
  stale audio.
- `speed` goes through `speed_steer`. An explicit `/api/tts?speed=` wins over `style.speed`.
- `expr` goes through `steering.with_expressiveness`.

Lines the client writes itself (lesson brief, badge, Academy replies) should add the same keys to the style they send.
A style made only of these keys, such as `{"tts_voice": "com.apple.voice.Tara.premium", "speed": 1.25}`, means the persona's default
style plus them. The rule for which persona gets the chosen voice is the guide only, or every persona when `voice_all`
is set (`steering.pref_voice`). With default Settings the decisions are byte-for-byte what they were.

### Expressiveness (`steering.with_expressiveness`)

Kept on the style for an engine that can use it. The OS voices take only the rate and pauses (model_server/app/tts_os.py),
so with them this setting changes the cache key, not the sound. The table is what the style carries:

k = 2·(e − 0.5), from −1 to +1. At e = 0.5 nothing changes.

| e | f0_iqr (melody range, z) | performance-director strength | tags |
| --- | --- | --- | --- |
| 0 (calm) | −1.4 on top of the situation | 0.4 | excited / amazement → interest; happiness / pride / ecstasy → contentment |
| 0.25 | −0.7 | 0.55 | unchanged |
| 0.5 | ±0 | 0.7 (today) | unchanged |
| 0.75 | +0.4 | 0.85 | unchanged |
| 1 (lively) | +0.8 | 1.0 | unchanged |

Rate, pace, loudness and pauses are left alone, because they belong to the situation and the rate setting. A storm
alert stays fast and loud at every expressiveness, and alarm tags are never softened. f0_iqr is clamped at ±2.5, like
every control.

### Filter → the router's device-directed gates (`turn_router.FILTERS`)

| filter | DD_MIN (below: talking to someone else) | DD_STRONG (barge-in while we speak; yes/no questions; the "didn't catch that" notice; the fallback) |
| --- | --- | --- |
| relaxed | 0.35 | 0.55 |
| **normal** | **0.5** | **0.7** (today) |
| strict | 0.65 | 0.85 |

Relaxed suits a shy or quiet kid. Strict suits a noisy room or siblings. Only these two gates move: the echo check, filler and
non-lexical sounds, the 600 ms hard mute after our voice, and the too-short and ramble rules are identical at every
level (`tests/test_settings.py` checks each one at each level). The session's own barge-in check (`_is_barge`) uses the
same DD_MIN. The client's `voice.js` barge-in check has its own thresholds; the UI should mirror these.

### Level

`session.level` (`cadet` | `commander`) goes into the Director's context (`ctx["level"]` and `ctx["mission"]["level"]`)
and onto the mission sim object (`Mission.level`). `POST /api/mission/start` and `POST /api/academy/attempt` take an
optional `level` too. Nothing reads it yet: the learning designer (`feat/learning-v3`) will.

## The OS voices

The app speaks with the operating system's own offline voices; nothing is downloaded or bundled for speech. The model
server owns the engine (`model_server/app/tts_os.py`, pure rules in `os_voices.py`) and lists what this machine has:
`GET /v1/tts/voices` → `{engine, timing, locale, default, roles, voices:[{id, name, locale, gender, quality, desc, rank,
picker}]}`. The backend (`app/voices.py`) caches that for 30 s and serves the `picker` subset as `/api/voices`.

| OS | engine | voices it can use | word timings |
| --- | --- | --- | --- |
| macOS | `/usr/bin/say` to a temp WAV (24 kHz mono 16-bit), no `-r` at 1× (the voice's own pace), else `-r` relative to its measured native words/min, `[[slnc ms]]` for extra sentence pauses | NSSpeechSynthesizer's list (`com.apple.voice.*` premium / enhanced / standard / compact, `com.apple.eloquence.*`), plus **the Spoken Content system voice** (`say` with no `-v`) | estimated: the rendered speech span spread over the words by syllables and characters, with punctuation pauses, and every comma / sentence break snapped to the nearest real silence in the audio (`os_voices.estimate_timings`) |
| Windows 10 / 11 | WinRT `Windows.Media.SpeechSynthesis` in-process (pywinrt 3.2.1), `SpeakingRate` from the rate | the OneCore voices (Zira, David, Mark …; "Natural" ones if Windows exposes them) | real: the voice's word-boundary cues (`IncludeWordBoundaryMetadata`), mapped to the caption words by character position |
| Windows fallback | SAPI 5 (`SAPI.SpVoice` via comtypes, late-bound), when WinRT will not start | the desktop SAPI voices | estimated, as on macOS |

**The system voice (macOS).** Siri voices (System Settings → Accessibility → Spoken Content → System voice) cannot be
named by an app (`say -v com.apple.siri…` fails with -244; NSSpeechSynthesizer does not list them), but `say` without
`-v` speaks with whatever the parent picked there. So "Your Mac's system voice" is its own entry (`id: "system"`). The
voice behind it comes from `com.apple.Accessibility SpokenContentDefaultVoiceSelectionsByLanguage` (read defensively:
a flat `[lang, {voiceId}]` list on macOS 26, or a dict; missing or odd → unknown). Its Settings line names that voice,
e.g. "Nora (Siri)" or "Tara (Premium)". It is **the default** when that voice is a Siri voice or a premium / enhanced
one; otherwise it is listed but the best listed voice is the default.

**Ranking** (`os_voices.rank`): quality first — Siri system voice > premium > enhanced > Windows natural > OneCore /
macOS standard > compact / SAPI > Eloquence — then the kid's locale (the OS's, or `OS_TTS_LOCALE`), then en-US, then
en-GB / AU / IE / IN / CA / NZ, then any other English; ties go to a woman's voice first (the guide has always been one,
CAPCOM a man), then by name. English only. **Never**: the novelty voices (Albert, Bad News, Bahh, Bells, Boing,
Bubbles, Cellos, Wobble, Jester, Organ, Superstar, Zarvox, Trinoids, Whisper, Good News, Fred, Junior, Ralph, Kathy …,
by name and by file id) and any id outside the engine's allowlist. One entry per name + locale (the best quality of it).
Settings shows at most 12 and leaves the Eloquence voices (Eddy, Flo, Reed, Rocko, Sandy, Shelley, Grandma, Grandpa) out
unless fewer than three better voices exist.

**Roles** (`os_voices.assign_roles`):

- **When the system voice is good** (Siri, premium or enhanced), the guide, CAPCOM **and** the story all use `system`.
  Flight School and the Mission talk through CAPCOM, and the recorded voice pack (docs/VOICE_PACK.md) is the system
  voice too. With one shared voice, a character never flips between a live line and a recorded one.
- **Houston** gets a distinct good voice only if one exists in the kid's locale family: the kid's locale, then en-US,
  then en-GB. It is never the voice behind `system`. With no such voice, Houston uses `system` as well.
- **Otherwise**, the ranking applies: the guide gets the best voice. CAPCOM gets a different good voice (at most one
  quality tier lower, the other gender first). Houston gets a third voice, else CAPCOM's. The story voice gets a
  fourth, else the guide's.

With one voice installed, every role uses it. The backend's personas (`steering.VOICES`) are these role names.
**Settings:** a picked voice applies to the guide, CAPCOM and the story together (`steering.pref_voice`,
`floor.js prefStyle`). "Use this voice for everyone" adds Houston.

On the build Mac (macOS 26.2, Siri system voice Nora, two en-IN premium voices installed, kid locale en-US):

| rank | id | Settings name | desc | role |
| --- | --- | --- | --- | --- |
| 0 | `system` | Your Mac's system voice | Nora (Siri) | guide, CAPCOM, story, Houston (no good en-US / en-GB voice) |
| 1 | `com.apple.voice.Tara.premium` | Tara | Premium · India · female | |
| 2 | `com.apple.voice.Aman.premium` | Aman | Premium · India · male | (Houston for an en-IN kid) |
| 3–8 | Samantha (US), Daniel (UK), Karen (AU), Moira (IE), Rishi (IN), Tessa (ZA) | | Compact | |
| 9– | 16 Eloquence voices (US, UK) | not in Settings | Basic | |

**Rate and pauses.** The style's `rate` z-score (with the kid's speed, `steering.delivery`)
and `pace` become one multiplier, `pace · 2^(rate/4)` (`os_voices.rate_factor`): macOS `-r` = the voice's measured native wpm × that (no `-r` within ±8 % of 1×; `OS_TTS_WPM` only as a fallback), WinRT `SpeakingRate` = that, SAPI `Rate` = 10·log3(that). A positive `pause` adds up to 500 ms between
sentences; a sentence with a next one ends on a 220 ms gap. The tag, pitch / loudness controls, guidance and emphasis
markup have no OS equivalent: markup is stripped, the rest ignored (no errors). Loudness is still mastered by the
backend: −14 LUFS with one clean gain and a −1 dBTP ceiling, no limiter. The voice's own pauses are never shortened.

**Latency** (this Mac, warm, per sentence, cache miss; the floor plays sentence 1 while sentence 2 renders): the Siri
system voice 1.2–1.6 s (so ~1.3 s to first audio), a premium voice 0.8–1.0 s, compact ~0.8 s. A repeated line is a
cache hit (~1 ms). The model server renders "Ready." at startup so the first real line is not the cold one.

**Better voices.** Settings → Voice tells parents where to download clearer voices (free, offline once installed):
macOS: System Settings → Accessibility → Spoken Content → System voice → Manage Voices. Windows: Settings → Time &
language → Speech → Manage voices. The list refreshes within 30 s.

**Voice pack (next).** `tts_os.PACK_LOOKUP` is the seam for pre-rendered fixed lines: a callable (voice id,
`os_voices.pack_key(text)`, rate) → WAV or None, asked before the engine. Not wired yet.

## Steer TTS (optional second engine)

Settings → Voice has exactly **two choices**: "Your computer's voice" (the default: Siri / the Mac's system voice, the
best WinRT voice on Windows, picked automatically; no list, a one-line hint about downloading better OS voices) or
"Steer TTS (Whissle)", which shows Steer's voice list with previews. The OS voice grid and "Use this voice for
everyone" are gone (old saved picks are cleared by `normalizePrefs`); "Use the recorded guide voice for story lines"
shows only under the computer's voice.
Steer was the app's voice before the OS voices (commit 7ea1bad); it is restored as an option:

- **Engine**: Steer TTS Edge v1 (`model_server/app/tts_steer.py`, `POST /v1/tts/steer`), the vendored
  `desktop/vendor/wheels/steertts_edge-1.3.0-py3-none-any.whl` (pure Python + ONNX Runtime + numpy + safetensors: the
  same wheel on macOS and Windows; without a libm, as on Windows, its director falls back to numpy). CC BY-NC 4.0.
- **What it adds**: the whole style is honoured (tags, the 12 controls, emphasis markup, the performance director's
  per-sentence plan), and the word timings are the model's own (`X-Steer-Words` → `X-TTS-Words`): captions are exact.
- **Voices**: the 10 curated voices of `backend/data/voices.json` (Aurora first, the default) with their offline
  previews (`backend/data/voice_previews/`); the chosen Steer voice speaks every role (Houston is relayed by CAPCOM).
  Mute covers Steer like every guide line (same `<audio>` path).
- **Voice pack**: never with Steer (`steering.pack_allowed`, `floor.packAllowed`): every line renders live in Steer.
- **Delivery (0.3)**: ON DEMAND, never in the installer: the manifest's `steer` asset (13 MB, `on_demand: true`) downloads
  only when the kid picks Steer in Settings → Voice ("Get the Steer voice (13 MB)" → `POST /api/tts/engines/steer` →
  `<assets>/.want/steer` → the Electron main process, "Downloading Steer voice…", then the voices). Until the asset's
  own Dropbox link exists, its 12 files come out of the public v1 model package (`fallback.kind = "tar_members"`, each
  sha256-checked; LICENSE + NOTICE written from the manifest). The model server loads it on first use once the folder
  is there. (0.1.x bundled it via gather_models.py; that line is retired.)
- **Fallback**: Steer missing, downloading or failing → the line is spoken by the OS voice (`X-TTS-Fallback` says why).
