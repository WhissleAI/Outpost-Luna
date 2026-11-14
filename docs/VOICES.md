# Settings: voices, rate, expressiveness, listening filter, level

The kid's Settings panel (UI: `feat/ux-v3`) picks the guide's voice, how fast and how lively it talks, how picky the
always-open mic is, the kid's level and whether the mic is hands-free or push-to-talk. The backend serves the voice list
and applies the rest on the session. **Nothing about the child is stored server-side**: the client keeps the Settings
and sends them on every connect.

## Contract

```
GET /api/voices                      → [{id, name, desc, preview_url}]          (10 voices)
GET /api/voices/preview/<id>.wav     → the preview clip (16 kHz mono PCM16, ~2.4 s, ~77 KB; static, offline)

WS /ws/session, after hello and on every change:
  {t: "prefs", type: "prefs", voice, voice_all, rate, expressiveness, filter, level, listen}
  ← {t: "prefs", applied: {voice, voice_all, rate, expressiveness, filter, level, listen}}
```

Either `t` or `type` works. Every field is optional (a partial update keeps the others); an invalid value is ignored
and the ack shows what is in force. `prefs` may also ride on `hello` as `hello.prefs`.

| field | values | default | effect |
| --- | --- | --- | --- |
| `voice` | an id from `/api/voices` (or `null` / `"default"`) | `null` (the guide's own `voice_0644`) | the guide's Steer voice |
| `voice_all` | bool | `false` | `true`: CAPCOM, Houston and the story voice use it too; otherwise they keep their own voices |
| `rate` | 0.6–1.6 (UI: 0.75 / 1 / 1.25 / 1.5) | 1 | `steering.speed_steer`: rate z-offset + Steer `pace` (VOICE_STEERING.md §4b) |
| `expressiveness` | 0–1 | 0.5 (today's delivery) | melody range, the performance director's strength, calmer tags at the low end (below) |
| `filter` | `relaxed` / `normal` / `strict` | `normal` | the router's device-directed thresholds (below) |
| `level` | `cadet` / `commander` | `cadet` | passed through to the Director, mission sim and Academy; no behaviour change yet |
| `listen` | `handsfree` / `ptt` | `handsfree` | `ptt`: open-mic turns from the ear relay (and the client's `source:"voice"` copy) are ignored and never take the floor or barge in; only push-to-talk (`source:"ptt"`) and typed turns count |

### How the voice, rate and expressiveness reach the TTS

Every `say` decision the session emits gets them on its `style`, declaratively: `style.steer_voice` (the persona's voice
or the chosen one), `style.speed` (the rate) and `style.expr` (expressiveness). The client already forwards
`say.style` to `/api/tts`, and `tts.clean_style` applies them there, in one place:

- `steer_voice` is used only when it's a curated or persona voice (`voices.allowed`); otherwise the persona's voice.
- `speed` goes through `speed_steer`. An explicit `/api/tts?speed=` wins over `style.speed`.
- `expr` goes through `steering.with_expressiveness`.

Lines the client writes itself (lesson brief, badge, Academy replies) should add the same keys to the style they send.
A style made only of these keys, such as `{"steer_voice": "voice_1439", "speed": 1.25}`, means the persona's default
style plus them. The rule for which persona gets the chosen voice is the guide only, or every persona when `voice_all`
is set (`steering.pref_voice`). With default Settings the decisions are byte-for-byte what they were.

### Expressiveness → Steer (`steering.with_expressiveness`)

k = 2·(e − 0.5), from −1 to +1. At e = 0.5 nothing changes.

| e | f0_iqr (melody range, z) | performance-director strength | tags |
| --- | --- | --- | --- |
| 0 (calm) | −0.8 on top of the situation | 0.4 | excited / amazement → interest; happiness / pride / ecstasy → contentment |
| 0.25 | −0.4 | 0.55 | unchanged |
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

## The 10 voices

| name | id | desc | profile (catalog) | WER clean | WER noisy | f0 median | f0 IQR (st) | words/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Beacon | `voice_0644` | Warm, clear guide; the default voice. | female, mid, average | 0.04 | 0.44¹ | 188 Hz | 4.11 | 2.88 |
| Meteor | `voice_1439` | Lively, bouncy voice with big melody. | male, mid, average | 0.00 | 0.04 | 108 Hz | **6.29** | 2.94 |
| Crater | `voice_1207` | Deep, steady voice, calm and low. | male, low, average | 0.00 | 0.16 | **87 Hz** | 5.16 | **3.12** |
| Thruster | `voice_1059` | Quick, bright voice that keeps moving. | male, mid, fast | 0.00 | 0.04 | 113 Hz | 4.97 | 2.93 |
| Nebula | `voice_1035` | Soft, unhurried voice, gentle and warm. | female, low, slow | 0.00 | 0.04 | 174 Hz | 4.54 | **2.75** |
| Zippy | `voice_1627` | High, quick voice full of energy. | female, high, fast | 0.00 | 0.16 | 211 Hz | 4.81 | 2.97 |
| Twinkle | `voice_2423` | High, light voice, calm and sweet. | female, high, average | 0.00 | 0.20 | **218 Hz** | **3.56** | 2.78 |
| Drifter | `voice_1442` | Relaxed voice that takes its time. | male, mid, slow | 0.00 | 0.16 | 126 Hz | 4.78 | 2.82 |
| Lander | `voice_0762` | Friendly, upbeat voice, clear and even. | male, mid, average | 0.00 | 0.12 | 121 Hz | 5.57 | 2.90 |
| Aurora | `voice_1085` | Crisp, clear voice that cuts noise. | female, low, fast | 0.00 | **0.00** | 162 Hz | 4.87 | 2.88 |

Every voice has no clipping. Active-speech loudness is −22.6 to −24.8 dBFS and peaks are −7 to −11 dBFS. The range covers
87–218 Hz (about 16 semitones), melody (f0 IQR) 3.6–6.3 st, and pace 2.75–3.12 words/s, with 6 male and 4 female voices. Each
preview is "Hello! Ready to fly?": 2.3–2.6 s at 16 kHz mono PCM16, peak-normalised to −3 dBFS, about 77 KB each and
**772 KB** for all ten.

¹ The current guide voice is always offered (it is what the kid hears before choosing), even though it misses the noisy
bar. Clean, it is fine (WER 0.04: "shields" heard as "shoots"). In 5 dB pink noise it loses words. It's worth
revisiting the default: Aurora (`voice_1085`) is the closest clear alternative (female, 162 Hz, noisy WER 0.00).
CAPCOM (`voice_0213`, noisy 0.28), Houston (`voice_0272`) and story (`voice_0602`, noisy 0.56) are never offered as
the guide's voice, so the guide never sounds like them. With `voice_all` the kid's pick replaces them as well.

`backend/data/voices.json` holds each voice's full scores (`wer`, `wer_noisy`, `rms_dbfs`, `peak_dbfs`, `clip_pct`,
`dur_s`, `words_per_s`, `f0_med_hz`, `f0_iqr_st`, `f0_range_st`), its catalog profile and the run's settings.

## Method (`backend/tools/voice_curate.py`)

```bash
cd backend && uv run python tools/voice_curate.py --models http://127.0.0.1:8200 --raw /tmp/scores.json
# re-pick / re-render previews from saved scores (no ear pass):
uv run python tools/voice_curate.py --from-scores /tmp/scores.json --raw /tmp/scores2.json
```

The tool only reads from the model server (`POST /v1/tts` and `WS /v1/stream?ear=arc`) and sends one request at a time.

1. **Candidates (38).** Steer TTS Edge has 200 voices (`GET /v1/tts/voices`, i.e. the package's `voices.json`). They fall into 18
   strata of gender × pitch register × pace. From each stratum the tool takes the lowest-f0 and the highest-f0 voice, plus the four persona
   voices.
2. **Render.** Two kid-facing lines with the guide's base style (tag `interest`, performance director `children`
   0.7): "Good morning, Commander! The rover found ice near the south pole crater." and "Set the shields to forty
   percent, then check the battery before the storm."
3. **Intelligibility.** Each render is resampled to 16 kHz and streamed through the Arc ear with no context. It is
   scored with the ear eval's normaliser (`tests/fixtures/ear_eval/score.py`, the same WER as `LOCAL_EAR.md`). Clean
   speech is near the ceiling (36 of 38 at WER 0), so the same audio is run again with seeded pink noise at 5 dB SNR,
   and that is what separates the voices (0.00–0.68).
4. **Acoustics.** Active-speech RMS (dBFS), peak, the share of clipped samples, trimmed duration and words/s. Pitch comes from a
   small normalised-autocorrelation tracker (40 ms frames): f0 median, IQR and 5–95 % range in semitones. Its medians
   match the catalog's within a few Hz for the persona voices.
5. **Clear.** Clean WER ≤ 0.10, noisy WER ≤ 0.25, no clipping, and loudness within 6 dB of the median. 33 of 38 pass.
6. **Varied.** Farthest-point selection over z-scored (f0 median in semitones, f0 IQR, words/s), seeded with the
   default guide voice. Near-ties go to the lower clean + noisy WER. The other personas' voices are excluded.
7. **Names and descriptions** are written by hand from the profile and the scores: space words, no real-person names,
   and no clash with the call signs.

Gaps: two sentences per voice, synthetic noise rather than classroom babble, the guide's style only, and no listening panel with
kids yet.

## Bundling

`backend/data/voices.json` and `backend/data/voice_previews/` are part of `backend/data`, which
`desktop/scripts/build_python.py` copies into the app bundle. The build now fails if `voices.json` or any curated
voice's preview is missing.
