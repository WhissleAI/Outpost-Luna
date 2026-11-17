# On-device learning

The installed app gets better for each child on their own computer. Nothing leaves the device, no audio is kept, and
only small learned settings are stored. There is no retraining: the shipped models and weights never change; a few
thresholds move inside fixed bounds, and a cadet's own way of saying a name becomes a private alias.

Code: `backend/app/learn/` (app-agnostic, like the entity layer: it needs a `Registry` and nothing of Outpost Luna's),
`backend/app/learn/live.py` (the session's side), `model_server/app/echo_delay.py` (the speaker → mic delay),
`model_server/app/arc_ear.py` (`{"t":"tune"}`, pace and pauses on the final words), `frontend/src/learning_ui.js`
(Settings). Tests: `backend/tests/test_learn.py`, `model_server/tests/test_echo_delay.py`,
`frontend/tests/learning_ui.test.js`. Switch it off with `LEARN=0`.

## 1. What it learns

| | learned from | changes | bounds |
|---|---|---|---|
| **Echo, per computer** (`echo.py`) | each line we play: GCC-PHAT of the reference against the mic, in memory in the ear (`echo_delay.py`) → `{"t":"echo_delay","ms","peak"}`; each heard turn's `playback_leak`, labelled without the leak (our line = the router's text echo; the kid = a routed turn with a barge-in that is not a text echo) | the speaker → mic delay (median, p10-p90, drift per hour) for the view; the playback-leak threshold the echo rule uses (`session.ear_playback`) | threshold 0.75-0.95 (shipped 0.85), only when both sides have evidence (20 / 5) and separate; else the shipped value |
| **Personal name aliases** (`aliases.py`) | a "Did you mean X?" answered yes (or X tapped on the card) | the heard form ("ticko") links to the entity (`tycho`) directly next time (`director._link`, after the ear's sure links) | below |
| **Speech habits** (`habits.py`) | every routed kid turn: words, speech seconds and the longest pause inside it (the ear sends `speech_s`, `max_pause_s`); a turn that turned out cut off (the next one followed within 1 s and its end-of-turn p was < 0.5); the answers to offers | end-of-turn silence (`EAR_END_SILENCE_S`, sent to the ear as `{"t":"tune"}`); this kid's own yes / no words; the "Did you mean" thresholds (`NEAR_SCORE`, `ALMOST_MIN_P`) | silence 0.5-0.8 s (shipped 0.5); near 0.76-0.86 (0.8); almost 0.45-0.6 (0.5); at most 8 yes and 8 no words |
| **Director thresholds** (`policy.py`) | offers made for low-p ear links; a turn the guarded model silenced that the kid said again within 8 s | `LINK_ACT_P` per cadet; the guarded policy's `ignore` bar (`runtime.learned_thr`) | link 0.97-0.99 (shipped 0.99; one "no" in the band → back to 0.99); ignore 0.95-0.99, **up only** |

### Alias guards (each is a test)

- **Evidence:** 2 confirmations of the same heard form → the same entity, or 1 when Arc's sound-alike rated the offer
  p ≥ 0.85.
- **Never** a common word / filler / yes-no word (a form made only of them), more than 3 words, a form that already names
  an entity (another's name, alias or spoken form, or this one's), a form containing another entity's name, a known
  mishearing of another entity, or a learned alias of another entity.
- **Never from a "no"** (it blocks the heard form for good), **never from an echo turn** (the offer's turn or the
  answer was our own voice: the ear's playback flag or the router's text echo check).
- **Cap** 24 aliases (the weakest goes). **Decay:** strength = confirmations × ½^(days unused / 45); dropped under 0.5.
- **Removal:** Settings → What the app has learned → Remove (it is then blocked), or Reset learning.

### The shipped Director stays the shipped Director

- With nothing learned, every threshold is exactly the shipped value and the learned keys are absent from the read:
  the rules and the guarded r10 model decide exactly as before.
- The learned aliases and thresholds are added to the read **after** the Director model's step, so its features never
  see them (`test_learned_extras_never_reach_the_director_features`).
- The guarded policy's `ignore` bar can only rise, to at most 0.99: a decision changes only for a turn whose p(ignore)
  lies in [0.95, learned), and it changes to "the rules decide" (`test_policy_bounds_keep_shipped_decisions` checks
  400 random turns plus the edges with the bar at its bound).

### Priming the canceller

libarc's API has no way to set or keep the echo filter (`arc_nft2_stream_feed_ref` only takes audio and a time). The
app measures this computer's delay and can stamp the reference that much later (`{"t":"tune","ref_shift_s"}`, 0-0.25 s),
but on the real laptop recording that raised kid-over-playback leaks as much as our own (docs/ARC_ABI2.md §8), so the
shift stays off (`echo.USE_SHIFT = False`). Asked of the Arc team: get / set of the filter state.

## 2. Storage

`<cache_dir>/learning/` in the app (`~/Library/Application Support/Outpost Luna/cache/learning/`,
`%APPDATA%\Outpost Luna\cache\learning\`); `backend/data/learning_state/` in a dev checkout; `LEARN_DIR` overrides.

- `profile-<id>.json` per cadet profile (the client sends the active profile id, `p1`..`p6`, with its prefs; never the
  call sign), `device.json` for the computer. A few KB each, at most 64 KB.
- Atomic writes (temp file + rename), mode 0600; a file that does not parse is treated as empty.
- `store.clean()` keeps only the allowed keys before every write: numbers, counters, entity ids, and the heard forms of
  confirmed names (≤ 40 characters of `[a-z0-9 ']`) and the kid's own yes / no words. No audio, no transcripts, no call
  sign. Anything else a bug adds is dropped (`test_storage_holds_numbers_and_confirmed_names_only`).
- Cleared with the save data: Settings → Reset (both levels: `reset.targets` and the shell's `cache/learning`), and
  Settings → What the app has learned → Reset learning (this cadet + this computer's echo numbers).

## 3. Seeing it, resetting it, diagnostics

- **Settings → What the app has learned** (`learning_ui.js`, `GET /api/learn`, token required): plain sentences
  ("Names you say your way: “ticko” means Tycho.", "It waits a little longer before answering (0.7 s)…", "This
  computer's speakers reach its microphone in about 148 ms…", "Nothing leaves this computer. No recordings are kept.")
  and each learned name with Remove (`POST /api/learn/forget`).
- **Reset learning:** two taps ("Reset learning", "Yes, forget it"; `POST /api/learn/reset` with `X-Outpost-Reset`).
- **Diagnostics file:** `learning.json` with the numbers; the learned names and yes / no words only when the grown-up
  ticks "Include the names the app learned" (docs/DIAGNOSTICS.md). Logs never hold any of it.

## 4. Measured

Synthetic voices throughout (macOS `say`, pitched toward a child, round-11 chain): directional, not a child benchmark.
`nice`, at most 2 decode processes. Scripts and outputs: the PR description.

**Names and "Did you mean" (a simulated week per child, then a held-out day).** Six children, each one round-11
voice (Junior, Kathy, Fred, Tara, Sandy, Flo), each with 8 favourite places, 4 of them always said their own way ("tie
ko", "hurts spring", "copper nickus", ...). 7 days × 14 turns of play, then a held-out day of 20 turns; 708 turns
rendered from seeds (round-11 noise beds) and decoded by the app's ear with the map screen's names list, then replayed
through `director._link` with the learner in the loop. The simulated kid says yes to a right offer 85 % of the time
(in their own word: two of them use "yesh" / "ya", unknown to the router, and then tap the option), no to a wrong one
70 % of the time.

| held-out day (120 turns) | before | after a week |
|---|---|---|
| names linked right | 52 | **53** |
| names linked wrong | 10 | 10 |
| "Did you mean" asked (rate) | 5 (4.2 %) | 4 (3.3 %) |
| name said, nothing done | 53 | 53 |
| aliases learned (6 children) | | 10 (e.g. "erisarkus" → Aristarchus, "earthspring" → Hertzsprung, "crisi" → Sea of Crises) |
| own yes words learned | | 1 ("ya") |

Small, and never worse: aliases only come from "Did you mean" offers, and on these voices the ear offers back only
4-5 % of turns; 44 % of named turns are plain misses (no link, no offer), which this learner cannot see. Learning from
"a miss, then the kid taps the place" would reach far more turns; it is not built (it was not asked for, and the heard
form is less certain there).

**Safety (the same simulation):** 24 "no" answers in play, plus per child 12 probe offers with p 0.99 that were either
made on an echo turn or answered by an echo "yes", and 6 probe "no"s: **0 aliases** from any of them (the unit tests
cover each guard).

**End-of-turn cut-offs (VAD only, semi-synthetic).** The rendered kid turns with one pause inserted at the quietest point
of their middle, on the real recording's noise floor, through the ear's own VAD and onset / end-silence rules (no
decode). Two children pause 0.55-0.95 s in half their turns, two in a quarter, two rarely. A week of 98 turns each,
then 20 held-out turns:

| held-out (120 turns) | shipped 0.5 s | learned (0.75-0.8 s) |
|---|---|---|
| turns cut in two | 42 (35 %) | **20 (17 %)** |

Every child moved up (even the rare pausers, whose synthetic turns still had 15 % cut-offs at 0.5 s); the cost is
0.25-0.3 s more before the app answers those children. Pauses over 0.8 s still cut (the bound).

**Own-line turns (per-computer threshold, real echo + kid mix).** The first 60 % of the real recording with kid turns
mixed in teaches `DeviceEcho` (40 echo labels, 17 kid labels); on this laptop the two sides overlap, so the learned
threshold stays at the shipped 0.85: own-line turns and kid turns lost are unchanged on the held-out 40 % (0 and 0).
The learner moves only on a computer where they separate.

**This computer's delay.** The ear's per-line estimate on the real recording: 294 of 295 lines, 141-159 ms, the same
steps as the kit's chirps (141 → 154 → 159 → 148 ms). The smoke run measured one line live through `/ws/listen`.
