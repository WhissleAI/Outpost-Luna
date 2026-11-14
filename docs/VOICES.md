# Settings: voices, rate, expressiveness, listening filter, level

The kid's Settings panel (UI: `feat/ux-v3`) picks the guide's voice, how fast and how lively it talks, how picky the
always-open mic is, the kid's level and whether the mic is hands-free or push-to-talk. The backend serves the voice list
and applies the rest on the session. **Nothing about the child is stored server-side**: the client keeps the Settings
and sends them on every connect.

## Contract

```
GET /api/voices                      → [{id, name, desc, preview_url}]          (10 voices)
GET /api/voices/preview/<id>.wav     → the preview clip (16 kHz mono PCM16, 1.5–1.9 s, −14 LUFS; static, offline)

WS /ws/session, after hello and on every change:
  {t: "prefs", type: "prefs", voice, voice_all, rate, expressiveness, filter, level, listen, volume}
  ← {t: "prefs", applied: {voice, voice_all, rate, expressiveness, filter, level, listen, volume}}
```

Either `t` or `type` works. Every field is optional (a partial update keeps the others); an invalid value is ignored
and the ack shows what is in force. `prefs` may also ride on `hello` as `hello.prefs`.

| field | values | default | effect |
| --- | --- | --- | --- |
| `voice` | an id from `/api/voices` (or `null` / `"default"`) | `null` (the guide's own `voice_0644`) | the guide's Steer voice |
| `voice_all` | bool | `false` | `true`: CAPCOM, Houston and the story voice use it too; otherwise they keep their own voices |
| `rate` | 0.6–1.6 (UI: 0.75 / 1 / 1.25 / 1.5) | 1 = the new, faster default | `steering.delivery`: the 1× baseline (rate +1.0, pause −1.5) plus 4 rate z per octave; 0.75× is slower than the old 1× (VOICE_STEERING.md §4d) |
| `expressiveness` | 0–1 | 0.5 (today's delivery) | melody range, the performance director's strength, calmer tags at the low end (below) |
| `filter` | `relaxed` / `normal` / `strict` | `normal` | the router's device-directed thresholds (below) |
| `level` | `cadet` / `commander` | `cadet` | passed through to the Director, mission sim and Academy; no behaviour change yet |
| `volume` | 0–2 (UI 100% = 1) | 1 = −14 LUFS | master volume, applied on the server before the limiter: 20·log10(volume) dB, so 2 = +6 dB into the −1 dBTP limiter (louder but not clipped) and below 1 is a plain cut. Send it here, not as client gain: client gain above 100% would clip |
| `listen` | `handsfree` / `ptt` | `handsfree` | `ptt`: open-mic turns from the ear relay (and the client's `source:"voice"` copy) are ignored and never take the floor or barge in; only push-to-talk (`source:"ptt"`) and typed turns count |

### How the voice, rate and expressiveness reach the TTS

Every `say` decision the session emits gets them on its `style`, declaratively: `style.steer_voice` (the persona's voice
or the chosen one), `style.speed` (the rate), `style.expr` (expressiveness) and `style.volume`. The client already forwards
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
| 0 (calm) | −1.4 on top of the situation | 0.4 | excited / amazement → interest; happiness / pride / ecstasy → contentment |
| 0.25 | −0.7 | 0.55 | unchanged |
| 0.5 | ±0 | 0.7 (today) | unchanged |
| 0.75 | +0.4 | 0.85 | unchanged |
| 1 (lively) | +0.8 | 1.0 | unchanged |

Re-checked at the faster delivery (guide, the two eval lines): melody range (f0 IQR) is 3.1 / 3.9 / 4.1 / 5.5 / 6.0
semitones at e = 0 / 0.25 / 0.5 / 0.75 / 1; words/s stays at 3.56–3.60 and loudness at −14.1 LUFS throughout. The calm
end was −0.8, which only reached 3.7 st, so it is now −1.4 to make the two ends symmetric.

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

Selected on the raw renders (method below), then **re-calibrated** through the louder, faster `/api/tts` pipeline
(VOICE_STEERING.md §4d) and re-checked with the Arc ear. Twinkle was swapped: `voice_2423` went from 0.20 to 0.32 noisy
WER at the faster delivery, over the 0.25 bar, so it was replaced by the closest clear high female voice, `voice_0840`
(212 Hz, noisy 0.08 after).

| name | id | desc | profile (catalog) | f0 median | f0 IQR (st) |
| --- | --- | --- | --- | --- | --- |
| Beacon | `voice_0644` | Warm, clear guide; the default voice. | female, mid, average | 188 Hz | 4.11 |
| Meteor | `voice_1439` | Lively, bouncy voice with big melody. | male, mid, average | 108 Hz | **6.29** |
| Crater | `voice_1207` | Deep, steady voice, calm and low. | male, low, average | **87 Hz** | 5.16 |
| Thruster | `voice_1059` | Quick, bright voice that keeps moving. | male, mid, fast | 113 Hz | 4.97 |
| Nebula | `voice_1035` | Soft, unhurried voice, gentle and warm. | female, low, slow | 174 Hz | 4.54 |
| Zippy | `voice_1627` | High, quick voice full of energy. | female, high, fast | 211 Hz | 4.81 |
| Twinkle | `voice_0840` | High, light voice, soft and clear. | female, high, slow | **212 Hz** | 4.78 |
| Drifter | `voice_1442` | Relaxed voice that takes its time. | male, mid, slow | 126 Hz | 4.78 |
| Lander | `voice_0762` | Friendly, upbeat voice, clear and even. | male, mid, average | 121 Hz | 5.57 |
| Aurora | `voice_1085` | Crisp, clear voice that cuts noise. | female, low, fast | 162 Hz | 4.87 |

### Before / after the louder, faster calibration

`tools/voice_calibrate.py`: the two eval lines per voice. **Before** is the raw render with the persona's style (what
`/api/tts` sent until now). **After** goes through `/api/tts` in process. LUFS is the mean of the two lines and TP the
max (dBTP). Words/s is over the speech span. WER is from the Arc ear, clean / 5 dB pink noise.

| voice | LUFS before → after | TP before → after | words/s before → after | WER clean before → after | WER noisy before → after |
| --- | --- | --- | --- | --- | --- |
| **guide persona** = Beacon `voice_0644` | −23.8 → **−14.1** | −9.2 → −1.4 | 2.95 → **3.58** | 0.04 → 0.00 | 0.44 → 0.60¹ |
| **CAPCOM** `voice_0213` | −25.8 → −14.2 | −11.4 → −1.5 | 2.98 → 3.79² | 0.00 → 0.00 | 0.16 → 0.16 |
| **Houston** `voice_0272` | −25.2 → −14.1 | −9.5 → −1.3 | 2.36 → 3.01³ | 0.04 → 0.00 | 0.08 → 0.04 |
| **story** `voice_0602` | −25.4 → −14.1 | −9.9 → −1.4 | 2.69 → 3.37 | 0.00 → 0.00 | 0.08 → 0.04 |
| Meteor `voice_1439` | −25.7 → −14.1 | −7.1 → −1.3 | 3.00 → 3.57 | 0.00 → 0.04 | 0.04 → 0.04 |
| Crater `voice_1207` | −25.5 → −14.3 | −7.1 → −1.3 | 3.19 → 3.80 | 0.00 → 0.04 | 0.16 → 0.08 |
| Thruster `voice_1059` | −25.8 → −14.2 | −9.1 → −1.4 | 2.93 → 3.54 | 0.00 → 0.08 | 0.04 → 0.16 |
| Nebula `voice_1035` | −25.0 → −14.2 | −10.1 → −1.4 | 2.80 → 3.34 | 0.00 → 0.00 | 0.04 → 0.08 |
| Zippy `voice_1627` | −24.8 → −14.2 | −8.3 → −1.4 | 3.03 → 3.61 | 0.00 → 0.00 | 0.16 → 0.12 |
| Twinkle `voice_0840` (new) | −24.7 → −14.1 | −8.9 → −1.3 | 2.94 → 3.54 | 0.00 → 0.00 | 0.04 → 0.08 |
| ~~Twinkle `voice_2423`~~ (swapped out) | −24.2 → −14.1 | −9.3 → −1.4 | 2.80 → 3.39 | 0.00 → 0.04 | 0.20 → **0.32** |
| Drifter `voice_1442` | −25.6 → −14.1 | −8.6 → −1.4 | 2.85 → 3.34 | 0.00 → 0.00 | 0.16 → 0.04 |
| Lander `voice_0762` | −26.0 → −14.1 | −10.1 → −1.3 | 2.97 → 3.59 | 0.00 → 0.00 | 0.12 → 0.20 |
| Aurora `voice_1085` | −25.4 → −14.1 | −10.1 → −1.4 | 2.94 → 3.58 | 0.00 → 0.00 | 0.00 → 0.12 |

Every voice now lands at −14.1 ± 0.2 LUFS, so the spread between voices dropped from 2.2 LU to 0.2 LU. Every true peak is
≤ −1.26 dBTP. Pace is 3.34–3.61 words/s for the ten voices. Clarity holds: across the 14 rows,
summed clean WER errors are 2 → 4 of 350 words, and the extra errors are all "ice" heard as "eyes". Noisy WER averages
0.12 → 0.14 (the noise pass is coarse: one word is 0.04). The one voice that crossed the bar was swapped.

¹ The default guide voice was already the weakest in noise and gets a little worse when faster. Clean, it is perfect.
It is still always offered, because it is what the kid hears before choosing. **Aurora (`voice_1085`) is the
recommended default**: 0.00 clean and 0.12 noisy, at the same pace and loudness. Switching it is one line in
`steering.VOICES["guide"]` and needs a product decision.
² CAPCOM keeps its persona offset (rate +0.3): crisp radio procedure, a little faster than the guide.
³ Houston's base rate went from −0.2 to +1.2. It was 2.1 words/s and is still the steadiest voice (tag `enunciated`).

The previews are "Hello! Ready to fly?" rendered through the pipeline, resampled to 16 kHz and re-mastered. All ten measure
−13.9 to −14.5 LUFS (ffmpeg ebur128) and −1.2 to −1.5 dBTP, at 1.5–1.9 s each and **552 KB** for all ten (was 772 KB at
−16.7 to −20.9 LUFS).

The default voice is always offered. CAPCOM (`voice_0213`), Houston (`voice_0272`) and story (`voice_0602`) are never
offered as the guide's voice, so the guide never sounds like them. With `voice_all` the kid's pick replaces them as well.

`backend/data/voices.json` holds each voice's full scores (`wer`, `wer_noisy`, `rms_dbfs`, `peak_dbfs`, `clip_pct`,
`dur_s`, `words_per_s`, `f0_med_hz`, `f0_iqr_st`, `f0_range_st`), its catalog profile, the run's settings, and `calibration.before` / `calibration.after` (LUFS, TP, words/s, WER).

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

Re-calibrate after any change to the delivery or the mastering:

```bash
uv run python tools/voice_calibrate.py --out /tmp/calib.json --previews      # before/after table + previews
uv run python tools/voice_calibrate.py --after-only --ids voice_0840,voice_1274 --out /tmp/swap.json   # swap candidates
```

## Bundling

`backend/data/voices.json` and `backend/data/voice_previews/` are part of `backend/data`, which
`desktop/scripts/build_python.py` copies into the app bundle. The build now fails if `voices.json` or any curated
voice's preview is missing.
