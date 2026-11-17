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
| RNNT n-best (`nbest = 4`) | `EAR_NBEST=4` | `words.nbest`, `words.walts` (the words stay the greedy decode's) |
| Per-word / utterance confidence | always | `words.wconf`, `uconf`, `min_wconf` |
| Typed quantities | always | `words.quantities` → mission NLU amounts when the words have no number (`nlu._number`) |
| Disfluencies, `clean_text` | always | `words.disfl`, `words.clean_text` → mission parsing (`director._mission_turn`) |
| Live stream (`live = 1`) | `EAR_LIVE=1` | partial words from `PARTIAL` events (no re-decoding), `{"t":"entity"}`, `{"t":"eot"}` |
| Mid-stream names | always (live) | `arc_nft2_stream_set_names` on every list change (`EarStream.set_names`) |
| Echo reference | live + the app's playback (`EAR_PLAYBACK_THRESHOLD` 0.4) | `frontend/src/echoref.js` → `/ws/listen {"t":"ref"}` → `arc_nft2_stream_feed_ref`; `playback_leak`, `playback`, `{"t":"barge_in"}` |
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
turn close (VAD) ─► end_turn (the stream's echo leak for the turn) + ONE clip decode of the segment ─► final words
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
- **Policy (Arc's limits):** a turn is dropped as our own playback only when Arc flags it (`playback_leak >=
  EAR_PLAYBACK_THRESHOLD`, 0.4) **and** no barge-in was heard during it (`session.ear_playback`). A barge-in in the last
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
- **Next:** calibrate `EAR_PLAYBACK_THRESHOLD` and the barge-in rule on real laptop echo
  (`tools/arc_collect` echo mode), and send Arc the barge-in-on-reverberant-echo finding.

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
