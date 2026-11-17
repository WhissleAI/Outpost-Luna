# libarc ABI 2: what is switched on, and what it changed (2026-11-16)

The Arc team's update (arc_transcriber `0aa792f`, PR #18; "Arc update for Outpost Luna", 16 Nov 2026) answers most of
our asks in `docs/SPEECH_SIGNALS_AUDIT.md` §8. This document records how the app uses each piece, what was measured
before and after, what the Director sees, and what round 13 should train on.

Code: `desktop/vendor/libarc` (ABI 2, `"1.3.0-outpost.1"`), `model_server/app/nft2.py` (binding: read-outs, options,
`Nft2Stream`), `model_server/app/arc_ear.py` (the ear), `backend/app/{session,director,listen}.py`,
`backend/app/mission/nlu.py`, `frontend/src/echoref.js`, `backend/app/director_model/features.py` (round-13 block).

## 1. Switched on

| Arc feature | Setting | Where it goes |
|---|---|---|
| Tail / repetition guard, no-speech gate | on (libarc default) | every decode; `n_dropped` per turn |
| Sound-alike names (`almost`) | `EAR_ALMOST=1` | `words.almost` → `director._link` "Did you mean …?" (`ALMOST_POLICY`, §3) |
| RNNT n-best (`nbest = 4`) | **off** since the 0.3.10 gate (`EAR_NBEST=0`; §9): it moves no shipped decision and cost ~0.1 s per close | `words.nbest`, `words.walts` empty (the words stay the greedy decode's) |
| Per-word / utterance confidence | always | `words.wconf`, `uconf`, `min_wconf` |
| Typed quantities | always | `words.quantities` → mission NLU amounts when the words have no number (`nlu._number`) |
| Disfluencies, `clean_text` | always | `words.disfl`, `words.clean_text` → mission parsing (`director._mission_turn`) |
| Live stream (`live = 1`) | `EAR_LIVE=1` | partial words from `PARTIAL` events (no re-decoding), `{"t":"entity"}`, `{"t":"eot"}` |
| Mid-stream names | always (live) | `arc_nft2_stream_set_names` on every list change (`EarStream.set_names`) |
| Echo reference | live + the app's playback (leak ≥ 0.85 = our own audio, §8) | `frontend/src/echoref.js` → `/ws/listen {"t":"ref"}` → `arc_nft2_stream_feed_ref`; `playback_leak`, `playback`, `{"t":"barge_in"}` |
| `echo_decode` | `EAR_ECHO_DECODE` (off; §4) | finals decoded from the echo-cancelled audio |
| ORT telemetry | libarc disables it | `ORT_DISABLE_TELEMETRY=1` kept as well |
| Arc Tagger in libarc (`ARC_WITH_ARCTAG`) | not built | the model server already runs Arc Tagger 0.5 (kids domain) itself |

Not changed: the names lists, `LINK_ACT_P`, the dd thresholds, the turn contract (the ear's own VAD still opens and
closes turns; the stream supplies partials, events, echo and the final read-out).

### How a turn is heard now (live)

```
mic 80 ms ─► EarStream.feed_all ─► VAD (turn open / close, unchanged)
                 │
                 └─► Nft2Stream.feed (libarc stream, live=1) ─► PARTIAL ─► {"t":"words","final":false,"n_stable","eot"}
                        ▲                                       ENTITY  ─► {"t":"entity", kind name|almost|quantity}
   app playback ─► feed_ref(pcm, mic time)                      EOT     ─► {"t":"eot","p"}  (every 0.25 s at most)
   (echoref.js)                                                 BARGE_IN ─► {"t":"barge_in"} (not in the echo tail)
turn close (VAD) ─► ONE clip decode of the segment ─► final words ─► (then) the held pause + the stream's end_turn
                    (playback in the turn: end_turn first, for its echo leak, then the clip decode)
```

The final read (words, names, sound events, the directed head) is the classic clip decode of the segment, as before.
A first version took it from the stream's flush instead: the same words and links and a faster close, but the
directed head reads the stream's own utterances and context, and 29 of 672 turns crossed DD_MIN (directed commands lost
6-11 points), which would move the router and the Director's `dd` input. The stream keeps its audio, so it is reopened
when idle and quiet past `EAR_STREAM_MAX_S` (60 s; not while we play), and the reference still in flight is fed to the
new one.

## 2. Measurements

Set-up: the round-11 kid turns of the signals-audit re-decode (`SPEECH_SIGNALS_AUDIT.md` §5) plus 1-2-word turns and
the echo bank, rendered once from their seeds (macOS `say -o`, nothing played) with the playback reference kept for
every bed that is the app's own audio; each clip decoded through the app's own `EarStream` with its screen's names list.
Before = `origin/main` (libarc ABI 1); after = this PR. 758 kid turns (491 on the explorer screens, 249 of 1-2 words),
258 echo-bank clips. `nice`, 2 decode processes, on a machine at load average ~40 (round-12 training and two browser
test agents): absolute times are inflated, compare within a row. Synthetic voices: directional, not a child benchmark.

| | before (ABI 1) | **after (ABI 2, live, shipped)** |
|---|---|---|
| WER | 34.9 % | 34.6 % |
| Names in the list (372): linked right | 48.9 % | **56.7 %** |
| linked WRONG | 10.8 % | **5.6 %** |
| no link | 40.3 % | 37.6 % |
| Explorer turns (491): act right / act WRONG | 156 / 31 | 137 / 31 |
| "Did you mean": right / wrong + spurious | 44 / 8 + 1 | **68 / 8 + 1** |
| "Did you mean" accuracy | 83.0 % | **88.3 %** |
| Name said, nothing done (miss) | 49 | **45** |
| Numbers said that the turn carries (215) | 53.5 % | **62.8 %** in the words, **68.8 %** with the typed quantities |
| Empty decodes, 1-word turns (84) | 27.4 % | 26.2 % |
| Empty decodes, 2-word turns (165) | 26.1 % | 23.6 % |
| Device-directed read (685 turns) | | identical to the clip decode (max difference 0.0000) |

Partials, CPU and latency (190 turns, each mode with its own partials, same load; the machine was at load ~40, so
absolute times are inflated):

| | before: re-decode loop (0.3 s, back-off) | **after: live stream** |
|---|---|---|
| First partial after speech starts, p50 / p90 | 1.07 / 1.68 s | **0.93 / 1.40 s** |
| Partials per turn | 2.5 | 3.0 |
| CPU seconds per audio second (the ear, all threads) | 1.55 | **1.02** (-34 %) |
| Final words after the turn closes, p50 | 602 ms | 795 ms (+190 ms: the stream's `end_turn` before the clip decode) |
| Final decode alone (no partials, 758 turns), p50 / p90 | 1,443 / 2,931 ms | 1,676 / 3,100 ms (the n-best beam: +16 %) |

So live mode replaces the re-decode loop (`EAR_LIVE=1`): partials 0.14 s earlier, a third less CPU, the same final
read. The final is ~0.2 s later (end_turn) and the n-best beam costs ~16 % of a final decode; both are knobs
(`EAR_NBEST=0`) if the close latency matters more than the n-best on slow PCs.

Echo bank (258 clips of our own audio alone, speaker → mic, reference fed): clips that put words into the app 51.2 %
→ **47.7 %** (2.47 → 2.30 words per clip); 51 of 143 finals flagged as playback at 0.4. §4 has why it is not more.

What did not move: short turns (about a quarter of 1-2-word turns are still empty: "help", "yeah" need Arc's next
ear), and 19 explorer turns that used to act on a high-p link now get a "Did you mean" first (act right 156 → 137,
"Did you mean" right 44 → 68: mostly the same places, one "yes" more). `LINK_ACT_P` 0.95 / 0.9 would act on them again
but also act wrong 34 times instead of 31, so 0.99 stays.

## 3. "Did you mean": Arc's sound-alike names vs ours

Same turns, ABI 2 decodes; `director._link` with each policy (`ALMOST_POLICY`). Our fallback = `near_name`
(soundalike over the gazetteer, 0.8); Arc's = the best `almost` record that is a place (p >= 0.5).

| policy | "Did you mean" right | wrong + spurious | miss |
|---|---|---|---|
| ours only | 64 | 8 + 1 | 49 |
| **Arc's first, then ours (shipped)** | **68** | 8 + 1 | **45** |
| Arc's only | 68 | 7 + 1 | 46 |
| ours first, then Arc's | 68 | 8 + 1 | 45 |

Arc's sound-alike adds right offers that ours misses (4 more right, 4 fewer misses) at the same error count; "Arc
only" is one wrong offer fewer but one more miss. We keep ours as the fallback: it covers names
missing from the screen's list (Arc only matches the list). An "almost" record is only ever offered back, never acted
on.

## 4. Echo

- **Where playback happens:** every app voice (OS voice, the Nora pack, Steer) is a WAV blob played by the guide
  `<audio>` element (`floor.js`); crew clips go through a Web Audio graph (`player.js`). `echoref.js` sends the guide
  blob (decoded at 16 kHz when it starts playing) and taps the crew graph's output (80 ms frames as they play) to
  `/ws/listen` as `{"t":"ref","at","pcm"}`, stamped with the mic socket's sample clock (`listen.js clock()`); the
  backend relays it, the model server calls `arc_nft2_stream_feed_ref`. **Not covered:** NASA videos (`<video>`, no
  Web Audio graph), YouTube (iframe), the browser-voice fallback, UI beeps.
- **Policy (until §8, the simulation's):** a turn was dropped as our own playback only when Arc flagged it (`playback_leak
  >= EAR_PLAYBACK_THRESHOLD`, 0.4) **and** no barge-in was heard during it. **Since the real-laptop calibration (§8):**
  dropped when `playback_leak >= 0.85` (`session.PLAYBACK_THRESHOLD`), barge-in or not. A barge-in in the last
  0.15 s of our playback is ignored (it is the speaker's echo tail: it fired at the end of every clean echo in tests).
- **Measured (simulated laptop path: 250 Hz high-pass, room reverb RT60 0.25-0.7 s, 0.1-0.4 s output latency):**
  - leak separates our audio from a kid talking over it well: AUC 0.95 (echo-bank clips with words, median leak
    0.31, vs kid turns over playback, median 0.01). Flagged at 0.4: 35 % of echo, 1 % of kid turns; at 0.7 (libarc's
    default): 2 % of echo.
  - but with Arc's barge-in rule the drop rarely happens: BARGE_IN fires on 94 % of pure-echo clips, because our
    simulated echo path is longer than the canceller's 512 ms (heavy reverb) and so much of it is "unexplained".
    Echo-bank clips that put words into the app: 51 % before, 48 % after (the text echo check, `turn_router.echo_of`,
    stays the main defence). On the flag alone at 0.5 it would be 43 % with no kid turn lost here, but the Arc team
    measured 22 % of merged kid turns flagged, so we follow their rule until real laptops say otherwise.
  - `echo_decode` (finals from the cancelled audio): kid turns with our voice underneath get fewer inserted words
    (≥ 2 inserted: 9.4 % → 3.9 %) but much worse words (WER 37 → 54 %): **off**.
- **Done (§8):** calibrated on a real laptop echo recording (`tools/arc_collect` echo mode).

## 5. The Director: shipped decisions unchanged

- The ear's final words still carry `conf: null` and `alts: []`: the round-7 slots (`ear_conf`, `ear_alts`,
  `ear_alt_hot`, `ear_rescored`, `ear_tier_*`) stay 0, as r10 was trained. Every ABI 2 read-out travels under its own
  key (`uconf`, `nbest`, `almost`, ...) and `names[]` keeps its meaning (`almost` records are split out of it).
- The new read-outs feed only appended slots: the round-13 block `e13_*` (F 261 → 275). r10 reads `feats[:242]`.
- `backend/tests/test_arc_abi2.py::test_abi2_never_reaches_the_shipped_weights` runs the shipped r10 weights on the same
  turn end with and without the ABI 2 read-out: every head is bit-identical, and the prefix up to F_R12 (261, round 12)
  is identical too.
- The Director's Arc Tagger read-out stays on the `assistant` domain (PR #122): byte-identical.
- What does change, by design: the words themselves (the guard drops hallucinated tails; §2 WER), and the rules
  (the "Did you mean" offers, quantities, clean text, echo). Those are the numbers in §2.

## 6. Round 13: what to train on

Round 12 (`../wt-moon-r12`) trains on the round-11 caches, decoded with ABI 1: none of this is in them. Round 13 should:

1. **Re-decode** the round-11 / round-12 turn set with ABI 2 (`EAR_LIVE=1`, `EAR_ALMOST=1`, `EAR_NBEST=4`) so the
   words carry the guard's output, and store per turn: `uconf`, `min_wconf`, `wconf`, `nbest`, `walts`, `almost`,
   `quantities`, `clean_text`, `disfl`, `n_dropped`, and for echo beds the reference-fed `playback_leak`, `playback`,
   `barge`, plus the live `eot` at the close. Feed the playback reference for every bed that is the app's own audio
   (`os_echo`, `crew_echo`, the Nora pack), never for TV / music.
2. **Replay** them in `gen_sessions.py` into the final words event under the same keys the ear sends.
3. **Train on** `F_R13` (275): the round-12 block plus `e13_avail`, `e13_uconf`, `e13_min_wconf`, `e13_nbest`,
   `e13_nbest_name`, `e13_almost`, `e13_almost_p`, `e13_qty`, `e13_disfl`, `e13_dropped`, `e13_leak`, `e13_playback`,
   `e13_barge`, `e13_eot`.
4. **Still ignore** the round-7 slots (`ear_conf`, `ear_alts`, `ear_alt_hot`, `ear_rescored`, `ear_tier_step`,
   `ear_tier_screen`): keep them 0 (or drop them in the next layout); their meaning is now in `e13_*` and `ear_link_*`.
   Do not fill them with the ABI 2 values: a model that reads them would then disagree with r10's training.
5. Fix `cc` first (SPEECH_SIGNALS_AUDIT.md §4: the generator fabricates it; Arc has no cc head yet).
6. Candidate classes for the guarded model: echo (now with `e13_leak` / `e13_playback` / `e13_barge`) and short-turn
   chatter (`e13_uconf`, `e13_eot`).

## 7. Windows (Bryan)

Nothing new to install. `desktop/scripts/build-windows.ps1` builds libarc from `desktop/vendor/libarc` with a CMake
glob, so the new sources (`arc_echo.c`, `arc_post.c`) are picked up; checked here with the mingw-w64 cross-build
(`arc.dll` builds; same warnings as before). After the build, step 6's
`gen_bindings.py --check --lib desktop\resources\native\arc.dll` must print `ABI 2 (matches arc.h)`. Then the
Windows test plan as usual (docs/BUILD_WINDOWS.md), plus: a voice turn shows partial words while speaking (live mode),
and the guide's own voice through the laptop speakers does not become a turn more often than before.

## 8. Real laptop echo: calibration (2026-11-16)

**The recording** (`tools/arc_collect` echo mode, read-only here): MacBook Pro M3 Pro, built-in speakers and microphone,
system volume 75 %, 25 min. 295 played items: 162 Nora voice-pack lines, 110 OS-voice lines (Nora, Daniel, Aman, Karen,
Tara, Samantha), 23 crew clips, 6 chirps, at four levels (0, -6, -12, -18 dB under the -18 dBFS master), 30 noise-floor
stretches. The reference is sample-aligned with the microphone (one duplex stream). Round trip from the chirps: 141,
141, 154, 159, 148, 149 ms (it moves in steps, not smoothly). Echo at the microphone: -29 dBFS (0 dB block) to -44 dBFS
(-18 dB); room floor -57.5 dBFS. No kid speech is in it.

**How it was run:** the whole 25 min through the app's own ear (`arc_ear.EarStream`, ABI 2 live, nft2), 80 ms at a
time, with the reference fed exactly as `echoref.js` does: a guide sentence whole when it starts (stamped with the
moment it was handed to the speaker), a crew clip in 80 ms frames as it plays. The stream is reopened when idle past
`EAR_STREAM_MAX_S` (60 s), as in the app: 24 canceller restarts in 25 min. Each final was routed by the app's own
router (`turn_router.route` with `Spoken` fed the lines' start / end, explorer screen) and then by the drop rule.
`nice`, 2 decode processes, `ARC_THREADS=2`.

**Kid over playback (semi-synthetic):** 165 round-11 kid turns re-rendered from their seeds (#125's `render_kid`, the
round-11 chain, no noise bed) mixed into the real microphone track: 75 % starting 0.3 s into one of our lines and
talking over it, 25 % starting 0.15-0.8 s after a line ended; kid speech level -36 to -24 dBFS (median -30: from 6 dB
under to 5 dB over our loudest echo). The echo, the room and the device are real; the kid is a Mac voice added
digitally (no acoustic coupling, no AGC interaction). 116 of them produced words.

### Results

| | real recording |
|---|---|
| Our own lines that put words into the ear | 180 finals (295 items) |
| ... that the router already ignores (text echo 103, hard mute 55, filler 3 ...) | 165 |
| **... that become turns with no echo rule** | **15** (21 of 295 lines) |
| playback_leak of our own finals, median (0 / -6 / -12 / -18 dB) | 0.75 (0.83 / 0.80 / 0.67 / 0.63) |
| playback_leak of kid-over-playback finals: p10 / median / p90 | 0.00 / 0.43 / 0.77 |
| **AUC, own-line finals vs kid-over-playback finals** | **0.72** (the simulation said 0.95) |
| Flagged at 0.4: own / kid over playback | 76 % / 51 % (Arc measured 22 % of merged kid turns) |
| Flagged at 0.85: own / kid over playback | 26 % / 2 % |
| Arc BARGE_IN on our own lines (no kid anywhere) | on 64 % of own-line finals; 257 events in 25 min, median p 0.71 |
| Turns during the 30 noise-floor stretches ("silence") | 0 |
| Speaker -> mic delay, per line, measured by the app (`echo_delay.py`, GCC-PHAT) | 294 / 295 lines; 141-159 ms, matching every chirp |

The own-line turns the router misses are mostly the en-IN OS voices (Tara, Aman) on long lines, transcribed as
nonsense ("pierre chloe's thermal post philadelph..."), which no text echo check can match, and most of them come with a
barge-in event. That is why the old rule (flag AND no barge-in) dropped only 1 of the 15.

**The drop rule, both sides** (own-line turns that reach the app on the real echo; kid turns heard that the rule throws
away, and kid turns that reach the app, of 116 heard):

| rule | own-line turns | kid turns lost | kid turns that reach the app |
|---|---|---|---|
| no echo rule | 15 | 0 | 60 |
| old: leak >= 0.4 and no barge-in | 14 | 5 | 59 |
| leak >= 0.4 (Arc's barge-in ignored) | 1 | 60 | 39 |
| leak >= 0.7 | 6 | 22 | 51 |
| leak >= 0.8 | 7 | 7 | 56 |
| **leak >= 0.85 (shipped)** | **10** | **2** | **59** |
| leak >= 0.9 | 15 | 1 | 60 |
| leak >= 0.85 unless a barge-in with p >= 0.8 | 12 | 1 | 59 |
| leak >= 0.8 unless a barge-in with p >= 0.9 | 9 | 5 | 57 |

Shipped: `session.PLAYBACK_THRESHOLD = 0.85`, the barge-in no longer keeps a flagged turn (`EAR_PLAYBACK_THRESHOLD`
0.85 too, for the `playback` flag). Better on both sides than before: own-line turns 14 -> 10, kid turns lost 5 -> 2,
the same 59 reaching the app. The optimum is narrow (0.8 loses 7 kid turns; 0.9 keeps all 15 own lines) on one laptop
and 116 kid turns, which is why on-device learning (the next PR, `docs/ON_DEVICE_LEARNING.md`) may move it per computer, but only
within 0.75-0.95, and only with evidence from both sides.

**Warm-up** (own-line finals by seconds of playback the canceller had seen since its stream opened):

| playback seen | finals | leak median | flagged at 0.85 |
|---|---|---|---|
| < 1 s | 7 | 0.29 | 0 / 7 |
| 1-3 s | 11 | 0.69 | |
| 3-10 s | 26 | 0.77 | |
| >= 10 s | 136 | 0.76 | |

So about 1-3 s of playback, close to Arc's "~1 s"; the first sentence after a (re)open is not handled. With the 60 s
reopen this happens about once a minute of idle time; the API has no way to keep or prime the filter (below).

**The measured round trip:** the app stamps the reference when it hands it to the speaker, so the canceller has to model
~150 ms of pure delay inside its 512 ms window. Stamping it 120 ms later (the measured delay minus a margin, what the
learner would do) raises every leak (own-line median 0.75 -> 0.84; the first second after an open 0.29 -> 0.46; barge-in
on own lines 64 -> 57 %) but kid-over-playback leaks rise with it (median 0.43 -> 0.49): AUC 0.72 -> 0.74, and at
the best threshold for it (0.9) 10 own-line turns and 5 kid turns lost. No gain on the decision, so the shift is not
used; the app still measures the delay and its drift per computer (on-device learning) for when Arc can take a hint.

**For the Arc team:**
1. BARGE_IN fires on real, unreverberated laptop echo too (64 % of our own lines, mostly mid-line, not only the tail):
   the 0.3 s window with `max_leak 0.5` is too eager when the canceller is not fully converged or the voice changes.
2. On real echo, playback_leak separates our voice from a kid talking over it with AUC 0.72, not 0.95: a kid over
   loud playback reads 0.43 (median), because the leak is the share of the mixture explained. A per-utterance
   "residual speech" score (speech energy in the cancelled signal, or the ear's own decode of the residual) would help.
3. Keep / prime the canceller: an `arc_nft2_stream_get_echo` / `set_echo` (the 32 x 129 filter, ~66 KB) or an echo
   state that survives `arc_nft2_stream_close`, so a reopened stream (or a new session on the same laptop) starts
   converged; the app can store the per-computer delay (it does now) but has no way to hand it to the canceller.
4. A delay hint (`feed_ref` with a known bulk delay) would leave the 512 ms window for the room.
5. The en-IN OS voices are transcribed as nonsense when they come back through the speakers; the words cannot be
   matched to what we said, so the leak is the only defence for them.

Notes for the Arc team (no personal data) travel with the recording: `echo_set/CALIBRATION_NOTES.md`.

## 9. Close latency: the 0.3.10 release gate (2026-11-17)

The first 0.3.10 build failed the golden gate on latency: p50 1632 ms against a budget of 1519 ms, and +394 ms over
0.3.9 on the same load (1238 ms). Every clip was slower (median +456 ms). This section records the cause and the fix.

**Cause.** In live mode, each turn's close decoded the utterance **twice**, one decode after the other. Arc's
segmenter closes the stream's open utterance at a 0.4 s pause, about 0.1 s before our VAD closes the turn (0.5 s).
That stream final is a full decode with the n-best beam and sound events, and its result is thrown away except for its
`playback_leak`. Our VAD then queued the classic clip decode behind it. The n-best beam (+~30 % of a decode) ran in
both decodes. The in-process trace of one clip ("shields to 40"): the stream's final took 345 ms at 0.40 s of pause,
then the clip decode took 443 ms at 0.56 s.

**Fix** (`model_server/app/arc_ear.py`):
1. **One decode at the close.** When none of our playback overlaps the turn (no reference since 0.3 s before it began,
   and nothing playing), the stream is fed the pause only up to `EAR_STREAM_HOLD_S` (0.24 s). The rest is held, so
   Arc's segmenter cannot close the utterance first. The clip decode runs, the final words go out, and then the held
   audio and the stream's `end_turn` follow on the next call (`_settle`). That stream final has no leak to give
   (`p = -1` without a reference). When our playback does overlap the turn, the old order is kept (`end_turn` first,
   for the leak).
2. **The stream decodes lean.** No n-best and no sound events in the stream's own finals (`EAR_STREAM_NBEST=0`,
   `EAR_STREAM_EVENTS=0`); nothing reads them.
3. **n-best off** (`EAR_NBEST=0`). It moved no shipped decision (below) and cost ~0.1 s per close. Round 13's
   re-decode sets it itself. A model that reads `e13_nbest` must turn it back on when it ships.

**Golden on the source build** (`release_check.golden_run` against a model server and backend from this checkout; the
same machine; two rounds that alternate the configurations; mean of the two p50s and p95s, in ms):

| configuration | p50 | p95 | linked | p50 vs 0.3.10 as built |
|---|---|---|---|---|
| 0.3.10 as built (live, n-best 4 in both decodes, `almost`, 74-name list) | 1139 | 2192 | 23/23 | |
| ... `EAR_NBEST=0` (both decodes) | 902 | 1942 | 23/23 | **-237** |
| ... `EAR_LIVE=0` (the old re-decode partials) | 972 | 2144 | 23/23 | -167 |
| ... `almost` off | 1062 | 2229 | 23/23 | -77 |
| ... names list 40 instead of 74 (`EAR_MAX_NAMES=40`, 0.3.9's cap) | 1163 | 2360 | **20/23** | +24 (noise) |
| ... echo reference | | | | 0: golden plays nothing, so no reference is fed |
| **fix 1+2** (one decode at the close, lean stream; n-best 4 in the clip) | 936 | 1936 | 23/23 | -203 |
| **fix 1+2+3** (shipped) | **836** | **1793** | **23/23** | **-303** |
| 0.3.9-like on this libarc (re-decode partials, n-best off, no `almost`, 40 names) | 863 | 1877 | 20/23 | -276 |

So the shipped close is 3 % faster than the 0.3.9-like path and keeps the 23/23 links: the longer list is what
links them, and it costs no measurable latency. (The installed-dmg A/B against the published 0.3.9 is in the release
notes' gate.)

**#125's set** (§2's 758 kid turns plus 258 echo-bank clips, re-rendered; names lists from this checkout's
`names_list`; each clip fed through `EarStream` in 80 ms frames; "close" is the last voice to the final words going
out, with a worker queue at real-time pace):

| | 0.3.10 as built | fix 1+2 | **fix 1+2+3 (shipped)** |
|---|---|---|---|
| close p50 / p90 | 1585 / 2298 ms | 1122 / 1626 ms | **1010 / 1444 ms** |
| final decode p50 / p90 | 691 / 1220 ms | 528 / 897 ms | 424 / 758 ms |
| WER | 34.2 % | 34.2 % | 34.2 % |
| names in the list (380): linked right / wrong / none | 56.6 / 5.0 / 38.4 % | same | same |
| explorer turns: "Did you mean" right / wrong + spurious (accuracy) | 66 / 5 + 4 (88.0 %) | same | same |
| numbers carried (215): words / + typed quantities | 63.3 / 69.8 % | same | same |

Turn by turn (`parity.py`, all 1,016 clips): the final words, spoken form, decoder text, names, `almost`,
quantities, `uconf`, device-directed read, `playback_leak`, `playback` and `barge` are **identical** between the build
and fix 1+2. Fix 3 changes only `nbest` / `walts` (now empty). The #125 note (29 of 672 turns crossed DD_MIN when
the final came from the stream's flush) does not apply: the final read is still the clip decode.

What does change: the `eot` on the final words is the stream's last in-turn value, read before Arc's own final
(median 0.04 instead of 0.35). It is under 0.5 on 98 % of turns either way (728 → 736 of 745), so the learner's cut-off
rule (`eot < 0.5` and the next turn within 1 s) is driven by the 1 s gap, as before. A round-13 re-decode must use
this code so that `e13_eot` matches. The partial captions lose the updates that the held pause would have given
(2466 → 2319 partials on the set). The final words follow at once.

**The empty "shields to 40"** (c01_0 in the golden rerun, and one noisy clip in other runs): the clip was decoded,
but too late. `/ws/listen` waits `STOP_WAIT_S` (2 s) after the client's `stop` for the ear, then closes. The ear
handles one connection's messages in order on one worker. Each close cost two decodes, and the live stream's
utterance finals cost up to 1.6 s during feeds (`ear_live_feed_ms` max, model server `/metrics`). On a loaded
machine, the backlog at the end of a clip passed 1 s of tail + 2 s, so the final words came after the relay had
closed. In the app the mic stays open, so the words would only be late. With one decode per close the backlog falls
(mean 1.38 → 0.99 s per clip on #125's set), and no golden run of the fix lost a clip.
