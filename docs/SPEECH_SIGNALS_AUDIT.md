# Speech signals audit: names lists, the ear's outputs, calibration (2026-11-16)

Question from the owner: are we using the names lists, the ear's tags, entities and dynamic name linking well across
the whole app, and are Arc Tagger, the ear and the Director calibrated together?

Short answer: **no, not before this change.**
- The names lists left most hardware out. On the library screen, 57 % of the names kids say could never be linked.
- The ear's link confidence was ignored.
- Half of what the ear and the tagger send is dropped, or is never produced at all.
- Six Director features read 0 because they were built for the previous ear.
- One feature (`cc`) is fabricated in training and absent in the app.

This document gives the evidence (code references and numbers), what was fixed in this PR, and what is left for
round 12 and for the Arc team.

Data:
- **Round-11 decodes** (`wt-moon-r11/director_model/cache/real_ear_r11`, read-only): 5,338 Mac-voice kid turns through
  the real ear (Arc Transcriber Space nft2, libarc, `arc_ear.EarStream`), each with its screen's names list. The
  audio is synthetic (macOS `say` voices pitched toward a child, mic chain, noise beds); see the round-11
  `ear_analysis.md` caveats.
- **Paired re-decode** (this audit, §5): 830 of those clips rendered again (same seeds, silent, in memory) and
  decoded twice, once with the old names list and once with the new one. The ear is deterministic: on 259 clips
  decoded twice with the same list, the output was identical 259 / 259. So the two runs differ only by the list.
- Setup: `nice`, 2 processes, `EAR_PARTIAL_EVERY_S=0` (partials do not change the final decode), libarc from
  `wt-moon-v03/desktop/build`, the nft2 model from `wt-moon-steer/model_server/models`. The installed app and ports
  47310 / 47210 were never touched.

## 1. Names lists, per screen

### What is sent and when

| | before (origin/main) | after (this PR) |
|---|---|---|
| Builder | `names_list.screen_names(frame, step, last_place)` via `session.ear_names()` | same, plus `recent` (the last 2 lines we spoke) |
| Sent by | `listen.names_loop` (`listen.py:236`): polls the session every 0.25 s and sends `{"t":"context","names"}` when the list changes | unchanged |
| Client names | `mission/ui.js:1051` pushes `[CAPCOM, Houston, site, Shackleton, Cabeus]`; `listen.arc_context` puts them first | unchanged |
| Cap | 40 everywhere (`names_list.MAX`, `listen.arc_context [:40]`, `arc_ear.ear_max_names`) | 40 on focused screens; **80 on the Moon screens** (`MAX_MOON`, `MAX_EAR`, `ear_max_names=80`) |
| Library | gazetteer places (24) + crew + Artemis + Orion / SLS + 3 sites + **3 of 36 hardware entries** (cut by the cap) | hardware first (36), then places, crew, missions, craft, sites, old crew (80) |
| Map | same as library | places first, then hardware, ... (80) |
| Cabin / brief / debrief | sites, crew, Houston / CAPCOM / NASA, Artemis I-III, Orion / SLS / LM, then places (40). `Shackleton` was an alias of both Shackleton sites; `de Gerlache` and `Malapert` existed twice (site alias + lunar-feature entry) | sites own their short names (`de Gerlache`, `Malapert`, `Shackleton rim`); the twin lunar-feature entries are dropped; the crater `Shackleton` stays |
| Lesson / ride | the step's options and proper names, then places, crew[:4], Artemis II / III (30-40) | unchanged, plus `recent` |
| Video, callsign, prep | crew-first lists | unchanged |
| Settings, voice bar | no list of their own (the map's list) | unchanged; see §6 for controls |

### Ordering and weighting

The ear has no weights or tiers. arc.h `arc_nft2_set_names` uses order in three ways:
- The first entries go into the decoder's kb prompt (about 56 tokens, so the first ~10-15 names).
- Every entry and alias is used for RNNT biasing.
- Every entry is used for linking.

So order is the only weight. Before this PR, the library put the 24 map places first, but kids on the library screen
mostly ask about hardware. In the round-11 texts:

| Screen | Catalogue mentions | Of those, in the list sent |
|---|---|---|
| Library | 1,051 | 456 (43 %) |
| Map | 135 | 55 (41 %) |
| Cabin | 521 | 220 (42 %, mostly "moon buggy" → Lunar Roving Vehicle, a control: see below) |
| Lesson | 80 | 80 (100 %) |

The names kids said on the library and map screens were mostly Apollo / Surveyor / Ranger / LCROSS / GRAIL / Luna
hardware.

`recent` adds a context weight that did not exist before. Names in what we just said go first. A kid usually asks
about the place the guide just named, and this also puts that name into the decoder prompt.

### Aliases and spoken forms

- Already there: Roman numerals, Latin / English names (`Sea of Rains` ⇄ `Mare Imbrium`), letters and acronyms
  (`L cross`, `S 4 B`, `al sep`), parenthesised names.
- Added: the spoken forms the ear actually produced in round 11 (`Sea of Rain` ×5, `Sea of Crisis`, `Byrgius`, `Ohm
  crater`, `Pythagoras crater`, `de Gerlache rim`).
- **Aliases do link.** A probe linked `Mare Imbrium` → `Sea of Rains` (state linked, p 1.0). So an alias must name
  exactly one entry. `dedupe_aliases` now drops aliases that equal another entry's name, aliases shared by two
  entries, and generic aliases (`descent stage` was on three lunar modules).
- The `south pole` alias on Shackleton was dropped: the `South Pole` entry covers it, and the director maps it to
  Shackleton.

### What was missing, stale or too long

- **Missing (the big one):** 33 of 36 hardware entries on the library and map screens. Apollo missions are covered
  only as aliases of their landers. Old crew (Neil Armstrong, John Young) are now at the end of the Moon lists.
- **Too long:** not an issue at 40. At 80 see §5: decode time and spurious links.
- **Stale:** none. The catalogue is built from data files (places.json, artifacts.json, sites.json).
- **Not names:** controls. A test list with `Lunar Roving Vehicle` (`moon buggy`, `the rover`, `buggy`) on the
  cabin made the ear rewrite "send the rover" as "send Lunar Roving Vehicle". On the 135 cabin clips first
  re-decoded that way, cabin WER went from 37.2 % to 47.1 %. **Controls stay out of the
  names list** until Arc has bias-only entries (Arc asks).

### What the Arc ear supports (arc.h + `model_server/app/nft2.py`)

| Capability | nft2 (the ear we ship) |
|---|---|
| List size | No hard limit in the header. The model card says "<= 30-50, most relevant first"; the kb prompt holds ~56 tokens |
| Tiers / weights | None. Order only (kb prompt); `arc_set_bias_strength` exists for the Arc Mini engine only, not nft2 |
| Aliases | Yes: `arc_name_entry.aliases`. Used for biasing **and linking**; the wrapper caps them at 12 |
| Kinds | lunar_feature, site, celestial, spacecraft, vehicle, mission, crew, person, place, organization, product, team, law |
| Mid-stream update | Yes. "Kept until changed; names and context are the model's at the time each utterance closes." `EarStream` re-decodes the whole segment on every partial and on the final, and `Nft2.transcribe` calls `set_names` whenever the list changed. A list sent mid-turn applies to that turn's final decode. Nothing to add; the 0.25 s poll is the only latency |
| Context prompt | `arc_nft2_set_context` (dom, prev, session entities). Never called by the app (`set_context` exists in nft2.py, unused): see Arc asks / round 12 |
| Bias-only phrases | No (`arc_set_bias` is Arc Mini only) |

## 2. The ear's and the tagger's outputs, field by field

Legend: R = router (`turn_router.py`), D = Director rules (`director.py`), M = Director model features, N = mission
NLU, UI = frontend, S = safety, L = turn log.

### Ear (`arc_ear.EarStream` → `listen.py` relay → `session.on_listen`, frontend `voice.js`)

| Field | Produced? | Consumers before | After this PR |
|---|---|---|---|
| `words.text` (written, linked names in list spelling) | yes | R, D, N, UI, L, M (words) | same |
| `words.spoken` | yes | stored in `k["ear"]`, **unused** | D: `_link` re-matches what the ear heard when a link is unsure |
| `words.names[]` `{heard, entity, state, p, tag, kind}` | yes | D `_link`: linked entity first, **at any p** (`director.py:221`); nothing else | D gates on p (§3); M: appended `ear_*link*` features; UI marks linked names; adds `t0/t1/src/via/model_entity/model_p/span_p` |
| `words.tags` (inline entity tags) | yes | none | none (round 12 / M) |
| `words.alts`, `words.conf` | always `[]` / `null` | M (`ear_alts`, `ear_conf`, `ear_alt_hot`): 0 | unchanged on purpose (§4) |
| Arc decoder text (`utts[].decoder_text`) | in the wrapper, **dropped by arc_ear** | none | sent as `decoder_text` + `agree` (RNNT ⇄ decoder word agreement); M: `ear_dec_*`, `ear_agree` |
| `numbers` (values, kinds) | wrapper has them, **dropped by arc_ear** | none (mission NLU uses the tagger's `numbers` instead) | unchanged (round 12) |
| `arc.device_directed` (head remapped by `app_dd`) | yes | R (every dd gate, §3), barge (server and `barge.js`), UI room-talk gate, M `dd`, L `arc.dd` | same |
| `arc.directed_head` (raw), `arc.directed` | yes | none | none (monotone with dd) |
| `arc.command_complete` | **always None** (nft2 has no cc head: probe) | M `cc`: see §4, skew | unchanged |
| `arc.act` / `arc.intent` | **always None** (nft2 has no trunk act / intent: probe) | R `clear_question(act)` and `route(act=)` read None | unchanged |
| `arc.audio_events` (p ≥ 0.3) | yes | **none** (not stored, not logged) | none (round 12) |
| `{"t":"emotion"}` | always `available:false` (no head, `arcmeta.py:13`) | the `emo_*` features, `ALARM_EMOTIONS`, `_tone`, steering: **all dead** | unchanged |

### Arc Tagger (`POST /v1/tag`, `readout.summarize`)

| Field | Consumers |
|---|---|
| `mentions` (entity spans, type dropped) | D `_link` (fuzzy against the gazetteer), UI `highlight.noteReadout` (/api/ask answers only), M `tag_mentions` |
| `numbers` | N `_number` fallback (`nlu.py:187`), M `tag_numbers` |
| `pii`, `hard_pii`, `pii_spans` | D guard (`director.py:150`, `:281`), session guard |
| `act`, `intent`, `complete` | M only (`tag_q/cmd/stmt/dd`, `tag_complete`) |
| `safety` `[{tag, p, thr, on}]` | S `safety.classify` via `tagger_read` on **every** heard turn (blocking, ≤ 0.3 s); the ear's `arc.safety` is never sent (only Head Start's `/v1/tag/stream` has it), so `k["safety"]` is always None |

`tag_avail` is non-zero on only 52 % of turn ends because `summarize(tag(...))` runs only in `_direct_turn` (router
outcome question / order) and in `/api/ask`. Turns routed ignore / navigate / answer call the Director with
`{"available": False}` (`session.py:617`). It is also False when the tag call fails or times out (2 s). This is by
design, not a bug: the model sees the tagger only where the rules ask for it.

### Does the router use the ear's linked entity ID?

No. `turn_router` has no names field. Mission NLU re-matches the text with regexes. Its dispatch `target` is the raw
1-2 words after "to" (`nlu.py:281`), and `sim.py` ignores it. "Explore de Gerlache" gets target None: three words, so
the regex misses it.

Only `director._link` uses the link, and indirectly the whole app does: the written text carries the list's
spelling, so every text matcher downstream sees the linked name. That is also why a wrong link becomes a wrong
action. "Fly Tycho pelicus" is how the ear heard "fly to Copernicus" (linked Tycho, p 1.0), and the turn flew to
Tycho.

## 3. Calibration

### Every threshold on these signals

| Threshold | Value | Where | Source |
|---|---|---|---|
| `DD_MIN` / `DD_STRONG` | 0.5 / 0.7 (relaxed 0.35 / 0.55, strict 0.65 / 0.85) | `turn_router.py:43`, `FILTERS` | hand-set (round 6); the ear's head is remapped onto this scale |
| `ear_dd_knee` / `ear_dd_strong_at` | head 0.05 → 0.5, head 0.5 → 0.7 | `arc_ear.py` `app_dd` | SLURP + crew clips (`tools/ear_compare.py`), "to be calibrated on real kids" |
| `CHATTER_DD` | 0.5, not filter-aware | `director.py:410`, `:517` | hand-set |
| `BARGE` | relaxed [0.35, 0.55], normal [0.5, 0.7], strict [0.65, 0.85] | `floor.js:175` | mirrors the router |
| Ear link | none before; **`LINK_ACT_P = 0.99`** now | `director.py` | this audit |
| Sound-alike confirm | **`NEAR_SCORE = 0.8`** (new) | `director.py` | this audit (`soundalike.MIN_SCORE` is also 0.8) |
| `ACCEPT / ASK_LO / ASK_MARGIN` | 89 / 82 / 5 (rapidfuzz ratio) | `director.py:158` | unstated |
| `EVENT_MIN_P` | 0.3 | `arcmeta.py:169` | unstated; no consumer |
| Tagger safety | the tagger's own per-tag `thr` | `safety.tags_on` | Arc Tagger; word list and CRISIS regex added where it missed (ARC_FEEDBACK.md) |
| `TAGGER_BUDGET_S` | 0.3 s | `safety.py:81` | latency budget |
| cc | none: never available | | |
| Emotion | none: never produced | | |
| Director policy (r10 xl) | `ignore 0.95`, `cmd / ask 1.01` (off), `ignore_min_words 3`, classes hot + echo | `weights.json` | fit on val, round 10 gate |

### device_directed (round-11 decodes, kid turns with a gold act; max dd per clip)

| dd ≥ | Directed turns kept (n = 1,545) | Room talk kept (n = 409) | Echo-bank clips kept (n = 165) |
|---|---|---|---|
| 0.35 (relaxed) | 94.6 % | 80.4 % | 72.7 % |
| **0.5 (DD_MIN)** | 93.2 % | 78.5 % | 66.7 % |
| 0.55 | 88.6 % | 68.5 % | 50.9 % |
| 0.6 | 83.2 % | 61.9 % | 45.5 % |
| **0.7 (DD_STRONG)** | 74.3 % | 49.9 % | 33.9 % |
| 0.8 | 67.3 % | 40.3 % | 20.6 % |

AUC is 0.70. **No threshold change is supported.**
- Moving DD_MIN from 0.5 to 0.55 drops 4.6 points of directed speech to cut 10 points of room talk.
- The room talk here is synthetic text in TTS voices.
- DD_STRONG (0.7) already discards 26 % of directed turns wherever it gates: questions, notices, yes / no on predict
  steps, the "I don't know" fallback.

Both are policy trade-offs to make on real kid recordings, not on this bank. Left as they are, numbers recorded.

### Is link_p calibrated? (round-11 decodes, old lists; a link is "right" when the reference names that entry)

| Link p | Links | Right |
|---|---|---|
| ≥ 0.999 (rounds to 1.0) | 414 | 85.5 % |
| 0.9-0.999 | 155 | 47.7 % |
| 0.8-0.9 | 48 | 43.8 % |
| 0.7-0.8 | 34 | 52.9 % |
| < 0.7 | 16 | ~30 % |

With the new lists (§5): ≥ 0.999: 93 % right (190 links); 0.99-0.999: 79 % (33); 0.95-0.99: 65 % (23); 0.9-0.95: 100 % (18, small); < 0.9: 63 % (99).

**Not calibrated as a probability.** It is close to bimodal: p = 1.0 is a strong signal, and anything under it is a
coin flip. Even p = 1.0 is wrong one time in seven, mostly when the decode itself is wrong ("C. Orion" for "Sea of
Rains"). `abstain` comes with p from 0.3 to 1.0 (60 of 264 abstains at p 1.0), so p is the rescorer's confidence in
its decision, not in the entity. And because `guard_names` can turn a link into abstain, an abstain's p is meaningless.

### The Director's tagger / ear inputs together

The Director model sees:
- `dd`;
- `cc`, which training fabricates (§4);
- the tagger read-out on 52 % of turn ends;
- nothing from the names linker until the round-12 features below.

The rules see:
- dd (router);
- the link at any p (director);
- tagger safety on every turn.

So before this PR, the three were not calibrated against each other at all. The ear's link and the tagger's mentions
both feed `_link` with independent fuzzy thresholds.

## 4. Director feature wiring bugs

| Feature | Reads 0 because | What the ear provides |
|---|---|---|
| `ear_conf` | `k["ear"]["conf"]` is set only when the words carry `conf`. Round 7's Arc Mini sent an n-best confidence; nft2 sends `conf: null` (`arc_ear.py`) | No confidence (no per-word confidence, no utterance confidence). The closest thing is RNNT ⇄ decoder word agreement (§5: mean WER 62 % when agreement < 0.5, 33 % at 0.5-0.8, 13 % at 0.8-0.99, 6 % when they agree) |
| `ear_alts`, `ear_alt_hot` | `len(alts)`: nft2 sends `alts: []`. libarc's `arc_utt.n_alts` is 0 for nft2 (probe) | One alternative: the Arc decoder's own text (`decoder_text`), which differs from the words on 78 % (635 of 810) of finals |
| `ear_rescored` | the round-7 hot-list rescorer (Arc Mini) is gone | none |
| `ear_tier_step`, `ear_tier_screen` | `ear["hot"]["tier"]`: nft2 takes no hot lists (`listen.py` never sends `hot`; `hotlist.py` feeds only the `hot_*` features, which match text and so are non-zero) | The names linker (link_state, link_p, kb_index) is the only per-entry signal. Round 9 planned to map it onto these slots; that was never wired |
| `cc` / `cc_avail` | Not 0 in training: **84.8 % non-zero**. `gen_sessions.py:471` posts `command_complete = uniform(0.5, 0.95)` on every turn, while the live ear always sends None. **Train / serve skew**: the shipped r10 weights see `cc_avail = 0` on every live turn, a state they barely saw in training | nothing (nft2 has no cc head) |
| `emo_*` | the ear has no emotion head (emotion is always unavailable) | nothing |

**Fix in this PR (append-only, `features.py` round-12 block, F 242 → 253):**
- `ear_names_avail`, `ear_linked`, `ear_link_p`, `ear_link_sure` (p ≥ `LINK_ACT_P`), `ear_abstain`,
  `ear_not_in_list`;
- `ear_link_step` (the linked entry is one of the step's options) and `ear_link_screen` (linked, but only on the
  screen list): these are the "tiers" round 9 meant;
- `ear_dec_avail`, `ear_agree`, `ear_dec_name` (the decoder text names a list entry or a gazetteer place that the
  words lack).

The round-7 slots stay 0. They sit inside the shipped weights' 242-wide prefix, and r10 was trained with them at 0.
Filling them with different signals would move the shipped model's inputs. The same reasoning applies to cc: wiring a
real cc (none exists) or zeroing it in the generator changes what r10 sees. That is a round-12 retrain decision.

**Shipped decisions unchanged:**
- `runtime.Model.step` slices `feats[:F]` with F = 242 from `weights.json`.
- `test_speech_signals.py::test_new_features_never_reach_the_shipped_weights` runs the shipped r10 weights on the
  same turn end with and without the round-12 read-out. Every head's output is bit-identical.
- `situation()` (the guarded classes) reads `hot`, which comes from `hotlist.py`. That file is untouched.
- The gate sets (ds_r10 npz) are precomputed 242-wide features.

What does change is the **rules**, by design: `_link`'s p gate and the confirm. In guarded mode the model acts only
in the hot / echo classes and the rules decide everywhere else, so those changes show up as rules outcomes. That is
what §5 measures.

Round 12 must also make `gen_sessions.py` replay the ear's `names` / `spoken` / `decoder_text` into the final words.
The r11 cache already stores them in `x`. Until then the new features are 0 in training data.

## 5. Measurements: before and after

### Paired re-decode (830 clips: library / map / cabin / lesson turns that name a catalogue entry, plus 300 turns that name none)

A mention counts as "linked right" when the ear linked that entry (or one whose form overlaps it). "Wrong" means a
linked entity the reference does not name. "Spurious" means a link on a turn that names nothing.

| screen | list | mentions | in the list sent | linked right | linked WRONG | no link | link precision | spurious links (turns naming nothing) | WER | decode ms / final |
|---|---|---|---|---|---|---|---|---|---|---|
| **all** | old | 684 | 44.4 % | 28.4 % | 7.3 % | 64.3 % | 78.9 % of 251 | 4 / 166 | 35.0 % | 813 |
| | **new** | 684 | **83.0 %** | **43.1 %** | 8.5 % | **48.4 %** | 81.8 % of 363 | 4 / 166 | **32.5 %** | 783 |
| library | old | 404 | 42.8 % | 27.0 % | 7.9 % | 65.1 % | 78.6 % of 140 | 0 / 12 | 36.3 % | 876 |
| | **new** | 404 | **99.3 %** | **48.0 %** | 10.1 % | 41.8 % | 81.2 % of 239 | 0 / 12 | **32.0 %** | 976 |
| map | old | 46 | 39.1 % | 10.9 % | 13.0 % | 76.1 % | 45.5 % of 11 | 0 / 3 | 37.4 % | 879 |
| | **new** | 46 | **100 %** | **41.3 %** | 19.6 % | 39.1 % | 67.9 % of 28 | 0 / 3 | **32.8 %** | 943 |
| cabin | old | 200 | 41.5 % | 31.5 % | 4.5 % | 64.0 % | 85.7 % of 77 | 1 / 108 | 33.1 % | 770 |
| | **new** | 200 | 43.5 % | 31.5 % | 4.0 % | 64.5 % | 87.8 % of 74 | 1 / 108 | 33.3 % | 572 |
| lesson | old | 34 | 88.2 % | 50.0 % | 8.8 % | 41.2 % | 73.9 % of 23 | 3 / 43 | 30.9 % | 595 |
| | **new** | 34 | 100 % | 55.9 % | 0.0 % | 44.1 % | 86.4 % of 22 | 3 / 43 | 32.6 % | 464 |

The denominator here is every catalogue name the reference says, including the ones the old list did not carry (the
round-11 analysis counted only names in the list sent, which hid the hardware gap). The 80-entry Moon lists raised
library / map linking from 27 % / 11 % to 48 % / 41 % and cut WER by 4-5 points. The cost: slightly more wrong
links (more candidates; the p gate below handles most of them), no more spurious links, and roughly +100 ms per
final decode on the library (976 vs 876 ms under a load average of ~26). The cabin is unchanged by design (its list
was right; only the twin entries and the shared alias changed). Cabin WER is 33.1 → 33.3 % with the final list. With
the discarded rover-as-a-name list (135 clips) it was 37.2 → 47.1 %.

### What the app does with it (`director._link` outcomes on the explorer screens, gold = the gazetteer place the reference names)

| explorer screens (library / map / lesson), 528 turns | act right | act WRONG | act spurious | Did-you-mean right | Did-you-mean wrong / spurious | ask (2 options) | miss | quiet ok |
|---|---|---|---|---|---|---|---|---|
| before: old list, act on any link | 199 | **119** | 6 | 0 | 0 | 2 + 3 wrong | 117 | 85 |
| **after: new list, LINK_ACT_P 0.99, near 0.8** | **212** | **52** | 5 | **86** | 11 + 2 | 1 | **78** | 84 |

Wrong actions drop 56 % (119 → 52). Right actions rise (199 → 212). 86 turns that used to fly to the wrong place or
do nothing now get a "Did you mean X?" that is right; 13 get a wrong one, and a wrong offer never acts. The
"Did you mean" rate is 99 of 528 explorer turns (18.8 %), 87 % of them right. On the cabin (299 turns: the mission
layer answers first), outcomes are unchanged except 5 new offers (2 right, 3 wrong) and 6 fewer misses.

On the round-11 cache (old lists, 3,283 library / map / lesson turns), the p gate alone and the sound-alike threshold
compare as follows:

| Policy | Act right | Act wrong | Confirm right | Confirm wrong / spurious | Miss |
|---|---|---|---|---|---|
| before (act on any link) | 485 | 323 + 121 spurious | 0 | 0 | 333 |
| LINK_ACT_P 0.95 | 442 | 306 + 116 | 45 | 15 + 5 | 333 |
| **LINK_ACT_P 0.99** | 427 | 294 + 116 | 60 | 27 + 5 | 333 |
| LINK_ACT_P 0.999 | 413 | 287 + 109 | 73 | 35 + 12 | 333 |
| **0.99 + near 0.8** | 427 | 294 + 116 | 89 | 47 + 14 | 284 |
| 0.99 + near 0.85 | 427 | 294 + 116 | 75 | 41 + 12 | 304 |
| 0.99 + near 0.9 | 427 | 294 + 116 | 71 | 41 + 8 | 308 |

Choices:
- **0.99.** At 0.95, 69 % of the changed turns are right; at 0.99, 65 %, and it catches more wrong actions; 0.999
  starts asking on mostly-right links.
- **Near 0.8.** Its precision is about the same as 0.85-0.9 (~50-60 %), and it recovers the most misses.

Asking "Did you mean X?" costs one "yes" when right and one "no" when wrong, and a wrong confirm never acts. A
sound-alike confirm is also spoken only for a clear device-directed question or request (`_gate_fallback`, like the
brain's guesses). A low-p link confirm is dropped when dd < dd_min.

Most remaining wrong actions are **not** linker errors. They are numbers misheard inside names ("Apollo 16" heard as
"Apollo 14", "Apollo eleventeen"), and then the gazetteer's text alias acts on the wrong lander (264 of 294 wrong acts
come from the `alias` path). That is an ear (numbers) problem: see the Arc asks.

## 6. What changed in this PR

- `backend/app/names_list.py`: Moon screens carry every place and every piece of hardware (cap 80; library is
  hardware-first, map places-first); the cabin's sites own their short names; spoken forms; `dedupe_aliases`;
  `recent_names` (what we just said goes first); controls kept out of the list.
- `backend/app/listen.py`, `model_server/app/arc_ear.py`: caps raised consistently to 80 (`MAX_EAR`,
  `ear_max_names`).
- `model_server/app/nft2.py`, `arc_ear.py`: the linker's evidence on each name (`t0/t1/src/via/model_entity/
  model_p/span_p`); the Arc decoder's text and RNNT ⇄ decoder agreement on the final words (`decoder_text`, `agree`).
  `alts` / `conf` stay empty (§4).
- `backend/app/director.py` `_link`:
  - acts on an ear link only at `p ≥ LINK_ACT_P`;
  - below that, acts on what the ear heard if that names *another* place, else asks "Did you mean X?";
  - new "almost linked" fallback (`near_name`, soundalike against every catalogue name the gazetteer resolves) asks
    instead of staying silent.
- `backend/app/session.py`:
  - passes the ear's `spoken` to the director;
  - keeps `decoder_text` / `agree`;
  - a "yes" within 20 s of the ear's confirm becomes the named place (as if its option was tapped);
  - the confirm is gated like the brain's guesses;
  - `ear_names()` passes the last 2 spoken lines.
- `backend/app/director_model/features.py`: the round-12 block (§4), append-only, `F_R11 = 242`.
- Frontend: the kid's words in the voice bar mark linked names (`highlight.linkSegments` / `paintLinked`): a solid
  underline when sure, a dotted underline + "?" when the director will ask.
- Tests: `backend/tests/test_speech_signals.py` (18), `frontend/tests/ear_links.test.js` (4), updated
  `test_arc_ear.py` and `test_listen_ear.py`.

## 7. Left for round 12 (app side)

1. **Retrain with the round-12 features.** `gen_sessions.py` must replay `x.names / spoken / decoder_text / agree`
   from the r11 cache into the final words event.
2. **Fix the cc skew.** Either stop fabricating `command_complete` in `gen_sessions.py:471` when the decode has none,
   or retire the cc feature. This needs a retrain; the r10 weights see `cc_avail = 0` live.
3. Emotion features and consumers are dead code until an emotion source exists. Either drop them in the next
   feature version or wire Arc Tagger emotion (it emits none today).
4. Mission NLU should take the linked site (`ear_names` → `sites.json` id) instead of the 1-2 words after "to"; the
   dispatch target should reach `sim.py` if it is meant to matter.
5. Use the ear's `numbers` (values) instead of the tagger's for amounts. Measure on the "a command lost" turns (50 %
   in round 11).
6. Turn log: log the link decision (state counts, p, how), with no words, so real-kid sessions can recalibrate
   `LINK_ACT_P` / `NEAR_SCORE`.
7. dd: recalibrate `app_dd`, DD_MIN and DD_STRONG on real kid recordings (the table in §3 is the synthetic baseline).
8. `audio_events`: nothing consumes them (no laughter / cheer reactions, no noise-aware gating). Either use them or
   stop computing them in the live path.
9. Call `arc_nft2_set_context` with `prev` (our last line) and session entities. Unmeasured; it needs its own A/B,
   since it changes the decoder prompt.

## 8. Arc asks from the signals audit

For the Arc team. Concrete, in priority order, with the evidence above.

1. **Numbers inside names.** "Apollo 16 Lunar Module Orion" is heard as "Apollo 14 ...", "Apollo eleventeen", "Apollo
   70". With the list loaded, the number in a listed name should be biased like its words. 264 of 294 wrong actions
   on the explorer screens trace back to a misheard number or word inside a hardware name.
2. **Calibrated link_p.** Today p is ~bimodal: 1.0 is 85-92 % right, 0.9-0.999 is ~48 %, and abstain carries p up
   to 1.0. We want p ≈ P(entity is what was said), so the app can set one threshold, plus a separate `p_state` for
   the linked / abstain / not_in_list decision.
3. **Per-word confidence** (and an utterance confidence) on the RNNT words. Today `conf` is null and the only proxy is
   RNNT ⇄ decoder agreement (mean WER 6 % when the two agree, 62 % below 0.5 agreement).
4. **n-best for nft2.** `arc_utt.n_alts` is 0. Even 2-3 RNNT beams would let the app keep "fly to Tycho" when the top
   beam dropped the name. The decoder text already shows the value: it names a place the words lack on 87 of 830 clips, the right place on 49.
5. **Bias-only entries** (`arc_name_entry.link = 0`), or `arc_set_bias` for nft2: command words and controls ("the
   rover", "shields", "end shift") biased without being linked and rewritten in the list spelling. Adding the rover
   to the cabin list raised cabin WER 37.2 % → 47.1 %.
6. **Weights or tiers per entry** (or `arc_set_bias_strength` for nft2): the step's options should pull harder than
   the screen's world. Today order is the only lever, and it only reaches the kb prompt.
7. **List size guidance at 80.** The Moon screens now send 80 entries with up to 12 aliases each. Please confirm the
   linker's and the RNNT bias's cost and accuracy at 80-120, and publish the kb prompt budget in entries. Our numbers:
   decode ms per final 813 → 783 overall (library 876 → 976); spurious links 4 / 166 → 4 / 166 on turns that name nothing.
8. **Mid-stream list update:** supported (names apply when each utterance closes). Please keep that contract, and
   document whether a list change between partials resets anything (we saw no effect).
9. **command_complete, act, intent and emotion on nft2.** The utterance trunk readouts are None on Arc Transcriber
   Space (probe), so the app's cc / act / intent / emotion consumers are dead. A cc head is the most useful of these
   (end of turn on a kid's slow command).
10. **Kid speech data.** All of the above is on synthetic Mac voices (WER 30-48 % on natural / eloquence voices; 1-2
    word turns are 24-53 % empty). Short answers ("hmm", "help", "this one") are the worst bucket.

## 9. Update: libarc ABI 2 (16 Nov 2026)

Arc answered asks 3-4 (per-word confidence, n-best), the "almost linked" state, numbers (typed quantities), streaming
and the echo reference. What the app switched on, before / after numbers and the round-13 feature block:
`docs/ARC_ABI2.md`. The round-7 slots stay 0 for the shipped weights; the new read-outs have their own keys and slots.

## 10. Update: Arc Transcriber Space v2 (17 Nov 2026)

Measured on our sets and kept off as the ear (Director wrong actions up, directed head shifted, own-voice echo
transcribed more); its room read-outs ride along in shadow: `docs/ARC_V2.md`.
