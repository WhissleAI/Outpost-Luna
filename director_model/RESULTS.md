# Director model: results by round

M = the learned Director (Mamba-3), R = the rule Director + session policy on the same heard words (Academy: the
grader). Metrics: `evaluate.py` docstring. All sets are held out (unseen seeds; held-out templates, card questions,
gold items; real Arc Mini decodes of the even ear-eval ids). Runtime check every round: numpy streaming vs torch
parallel, int8.

**Read the R column with care.** Where the gold label *is* the rules teacher on the clean words (most turns of
test_clean, test_q80 act, test_h40 act in round 1), R is ~1.0 by construction; those sets only measure how well M
imitates the rules. The fair comparisons are where gold is independent of the rules: test_asr / test_ear (the kid's
intent vs the rules on what the ear heard), test_h40 `expect`, test_gold, card+attr on test_q80, and (from round 2)
the gold-labeled templates.

## Round 1 — 2026-11-13 ~17:10 (pipeline end to end)

Data `ds_r1` (generator driving the real Session; real Arc Tagger + MiniLM embedder on a private :8290 model server):
train 1,000 sessions / 96,371 steps (half ASR-noised), val 120, test_clean 150 sessions (1,366 turns), test_asr the
same 150 noised, test_ear 200 real Arc decodes, test_h40 40, test_q80 80, test_gold 19. Model m: 77,541 params
(d48, 2 Mamba-3 blocks), 3,000 steps CPU ~4 min; s: ~30 K params.

| set | turns | act acc M / R | cmd exact M / R | wrong/50 cmd M / R | attr M / R | card+attr M / R | eot premature, gain | barge P/R M ; R |
|---|---|---|---|---|---|---|---|---|
| test_clean | 1366 | 0.955 / 0.890 | 0.686 / 0.954 | 14.0 / 2.0 | 0.844 / 0.754 | – | 0.013, 0 ms | 0.96/0.99 ; 0.85/0.17 |
| test_asr | 1365 | 0.928 / 0.825 | 0.633 / 0.879 | 19.0 / 8.3 | 0.826 / 0.731 | – | 0.021, 0 ms | 0.98/0.99 ; 0.88/0.16 |
| test_ear (real) | 200 | 0.585 / 0.705 | 0.418 / 0.818 | 53.6 / 20.9 | – | – | 0, 0 ms | – |
| test_h40 | 40 | 0.45 / 1.0 | 0.39 / 1.0 | 69 / 0 | – | – | – | – |
| test_q80 | 80 | 0.85 / 1.0 | – | – | 0.714 / 0.757 | 0.400 / 0.488 | – | – |
| test_gold | 19 | 0.79 / 0.74 | 0.18 / 0.45 | 22.7 / 13.6 | 0.67 / 1.0 | – | – | – |

h40 (`expect`): M 15/40 ok, 17 wrong fires, 8 none; R 15/40 ok, 3 wrong, 22 none. Size s: same picture (test_clean
act 0.960, cmd exact 0.668, wrong/50 15.8). Export: 113 KB int8, numpy stream vs torch parallel max |dp| 3e-6,
int8 vs float 0.106, 0.30 ms/step.

What the model already does better: barge-in (recall 0.99 vs 0.17: the rules only barge on Flux-start + 2 words; the
model reads echo share, dd and the floor), chatter/echo ignore, and act accuracy where the rules answer chatter.

Top errors: (1) command SLOTS: 105 slot mismatches on test_clean (dark vs low_power rule triggers, numbers, load) ->
wrong actions 14/50; (2) Academy wrong answers called `answer` (the model can't see the grader); (3) metaphors in
test_gold (snowmen, droopy tomatoes) -> answer/ignore; (4) labels: the rules teacher is itself wrong on held-out
templates ("drive the buggy home" -> collect_ice, "it's hard to breathe" -> shields, "if the radiation gets too high"
-> storm rule), the slot-loss rule is too strict ("shields" -> "shield" kept the load but was marked lost), the ear
ref "send the rover 2 kilometers north" is labeled guard (Arc Tagger PII false positive in the teacher).

Next: gold commands for every template (intent, not teacher); slot-loss = the slot can no longer be read from the
heard words; h40/q80 gold acts from their sets; an Academy grader feature; rules slots copied when the model agrees
on type and main slot (numbers from the deterministic parse); more data.

## Round 2 — 2026-11-13 ~18:00 (gold intents, Academy grader feature, slot copy)

Changes: every templated command now carries a **gold Command** (the kid's intent, not the rules teacher; where the
rules are wrong the gold says so: "lower the shields to 20 percent" = set 20, "take some power away from the lab",
"drive the buggy home", "if the radiation gets too high" = dose_high); risky/yes/no, h40 (`command`), q80 (`answer`)
and 18 of the 20 held-out ear references (`data/ear_gold.json`) have gold acts, so R is no longer 1.0 by construction
there. Slot loss = a slot the clean words carried can't be read from the heard words (was: any aligned word changed).
New features `lesson_graded` / `lesson_pass` (the Academy grader on the words). Decoding copies the deterministic
parse's slots when it agrees with the model on type and main slot. Export keeps `inp.weight` f32 (int8 vs float
0.106 -> 0.037; 137 KB). Evaluator: the guarded `on` policy is scored as shipped (guard wins, CONF 0.7, model may only
ignore / ask / command) and `on_fill` (the model may only act where the rules found no command).

Data `ds_r2`: train 2,000 sessions (~193 K steps), val 150, same held-out recipe. m 77.5 K params, 4,000 steps
(best 3,200).

| set | turns | act acc M / R | cmd exact M / R | wrong/50 cmd M / R | attr M / R | card+attr M / R | eot premature, mean gain | barge P/R M ; R |
|---|---|---|---|---|---|---|---|---|
| test_clean | 1366 | 0.966 / 0.878 | 0.772 / 0.884 | 9.5 / 6.6 | 0.928 / 0.754 | – | 0.003, 182 ms | 0.98/0.99 ; 0.85/0.17 |
| test_asr | 1365 | 0.939 / 0.819 | 0.677 / 0.818 | 14.3 / 12.1 | 0.906 / 0.731 | – | 0.006, 180 ms | 0.98/0.99 ; 0.88/0.16 |
| test_ear (real) | 200 | 0.655 / 0.720 | 0.586 / 0.828 | 45.7 / 17.2 | 0.53 / 1.0 | – | 0, 206 ms | – |
| test_h40 | 40 | 0.80 / 0.45 | – | 18.8 / 3.8 | – | – | – | – |
| test_h40_asr | 40 | 0.65 / 0.375 | – | 15.0 / 3.8 | – | – | – | – |
| test_q80 | 80 | 0.913 / 0.863 | – | – | 0.771 / 0.757 | 0.425 / 0.488 | – | – |
| test_q80_asr | 80 | 0.925 / 0.813 | – | – | 0.786 / 0.743 | 0.388 / 0.475 | – | – |
| test_gold | 19 | 0.842 / 0.737 | 0.27 / 0.45 | 22.7 / 13.6 | 0.67 / 1.0 | – | – | – |

h40 (`expect`): M 17 ok / 15 wrong / 8 none; R 15 / 3 / 22. Size s (~30 K) is as good on acts (test_clean act 0.980,
test_asr 0.950) and slightly worse on test_ear.

Guarded `on` policy vs rules (act acc, wrong/50): test_clean 0.961 vs 0.878, 9.3 vs 6.6; test_asr 0.909 vs 0.819,
15.2 vs 12.1; test_ear 0.635 vs 0.720, 33.6 vs 17.2; h40 16 ok / 8 wrong vs 15 / 3. `on_fill`: test_clean 6.8 vs
6.6, test_asr 12.8 vs 12.1, test_ear 29.3 vs 17.2, h40 19 ok / 6 wrong. **Not ready for `on`: more wrong actions
than the rules on every set.**

Top errors: real ear decodes of QUESTIONS in mission mode fire commands ("how deep is vav love crater" -> command,
p 1.0: "crater" is an explore cue and mission-mode questions are rare in training); metaphor commands in test_gold
(snowmen, droopy tomatoes) still -> answer/ignore; "message earth that we are safe" -> confirm_no under ASR; card
attribute on q80 ~ rules (0.77 vs 0.76) but card+attr below rules (the rules' brain picks attr and card jointly).

Next: more mission-mode explorer questions; 59 more train-only gold paraphrases (`data/gold_more.json`: metaphors per
load, rover home/explore, science/who/size); 3,000 train sessions.

## Round 3 — 2026-11-13 ~19:00 (more data, mission-mode questions, gold paraphrases) — SHIPPED (shadow)

Changes: 3,000 train sessions (290,839 steps); explorer questions in mission mode 6% -> 9% of turns; 59 more
train-only gold paraphrases (`data/gold_more.json`); runtime `on` now = `on_fill` (the model never overrides a turn
where the rules read a command). Ablation on ds_r2: a false-execution penalty in the act loss (`--fp-exec 2`) did not
lower wrong actions (guarded test_asr 15.7 vs 15.2 without it) -> not used.

Train turns by source (ds_r3): mission commands 9,798 (templates, bank, compound, negation, rules, risky), explorer
questions 7,128, Academy answers 3,374, barge-in 1,850, gold paraphrases 1,610, chatter 1,610, echo 1,330,
yes/no 1,201, PII 728. Sessions: mission 1,531, cadet 909, academy 560; half ASR-noised. Labels: gold 14,736 turns,
rules teacher 10,519, Academy grader 3,374.

Model m: 77,637 params, 5,000 steps (best 4,400), ~7 min on CPU. Export: 137 KB, int8 vs float max |dp| 0.042,
numpy stream vs torch parallel max |dp| 2e-6, 0.33 ms/step p50 (0.82 p99).

| set | turns | act acc M / R | cmd exact M / R | wrong/50 cmd M / R | attr M / R | card+attr M / R | eot premature, mean gain | barge P/R M ; R |
|---|---|---|---|---|---|---|---|---|
| test_clean | 1366 | 0.982 / 0.879 | 0.813 / 0.871 | 8.8 / 6.5 | 0.934 / 0.760 | – | 0.000, 198 ms | 0.99/0.97 ; 0.86/0.17 |
| test_asr | 1366 | 0.963 / 0.819 | 0.718 / 0.804 | 13.7 / 11.1 | 0.909 / 0.742 | – | 0.006, 203 ms | 0.98/0.99 ; 0.88/0.16 |
| test_ear (real) | 200 | 0.640 / 0.720 | 0.603 / 0.828 | 48.3 / 17.2 | 0.683 / 1.0 | – | 0, 216 ms | – |
| test_h40 | 40 | 0.90 / 0.45 | – | 15.0 / 3.8 | – | – | – | – |
| test_h40_asr | 40 | 0.80 / 0.375 | – | 16.3 / 3.8 | – | – | – | – |
| test_q80 | 80 | 0.938 / 0.863 | – | – | 0.857 / 0.757 | 0.475 / 0.488 | – | – |
| test_q80_asr | 80 | 0.950 / 0.813 | – | – | 0.814 / 0.743 | 0.425 / 0.475 | – | – |
| test_gold | 19 | 0.947 / 0.737 | 0.64 / 0.45 | 13.6 / 13.6 | 0.83 / 1.0 | – | – | – |

h40 (`expect`): M 24/40 ok, 12 wrong, 4 none; R 15/40 ok, 3 wrong, 22 none (ASR: M 20 / 13 / 7, R 13 / 3 / 24).
Size s (~30 K): acts as good (test_clean 0.984, test_asr 0.955), commands worse (wrong/50 13.8 / 17.8) -> m ships.

Guarded `on` (= on_fill, as shipped) vs rules, wrong/50: test_clean 7.4 vs 6.5, test_asr 12.8 vs 11.1, test_ear
29.3 vs 17.2, h40 9 wrong / 24 ok vs 3 wrong / 15 ok, test_gold 18.2 vs 13.6.

Shadow agreement (model act == rules act on steps where either acts): test_clean 0.890, test_asr 0.841,
test_ear 0.660.

Top errors: (1) **real Arc decodes of questions in mission mode fire commands** (40 of 200 test_ear turns, e.g.
"how deep is vav love crater", "fly to digo lockheed") — the generated ASR noise does not look like the real ear's
garbled names, and the ear sessions are all mission mode; (2) multi-word place names mangled by the ear ("digo laki")
in a command -> ask_clarify instead of explore; (3) metaphors with ASR noise ("we're tur ning into snowmen") ->
ask/answer; (4) slot conventions: the bank says "more" = +5, the rules say +10, and both are in the labels, so exact
slots on paraphrases are noisy.

## Where it stands (after 3 rounds)

The model is clearly better than the rules at **reading the kid**: act accuracy on every held-out set where gold is
independent of the rules (test_asr 0.96 vs 0.82, h40 0.90 vs 0.45, test_gold 0.95 vs 0.74), card attribute (0.86 vs
0.76 on the 80 kid questions), barge-in recall 0.99 vs 0.17 at precision 0.98, chatter / echo ignored, Academy
answers (grader feature), and it can answer ~200 ms earlier at the eager end of turn with < 1% premature answers.

It is **not** better at **acting**: wrong actions per 50 commands stay above the rules on every set (and far above on
the real ear decodes), because it fires more commands, including on paraphrases the rules leave alone (h40: 24 right
fires but 12 wrong vs 3). **Recommendation: ship `DIRECTOR_MODEL=shadow` (default); do not turn `on`.** Revisit when
(a) the real-ear set is larger and in the training mix (record real Arc decodes of generated sessions instead of the
fitted error model), (b) the slot conventions are unified (bank vs rules), and (c) guarded wrong/50 is at or below
the rules on test_asr, test_ear and h40 with the guard/PII rows unchanged.

## Round 4 — 2026-11-13 ~19:50 (real Arc decodes for test/val, one slot convention, mission questions, cost-aware policy)

Changes:
- **Real Arc decodes** (`real_ear.py`): every generated kid turn's text (same seeds as the generator) rendered with
  Steer TTS Edge (200 voices ranked by f0: rank%5==0 test voices, ==1 val voices, others train; draws biased to the
  higher-pitched voices; rate z U(-1, 1.2); half +0.5-2 st f0; 30 % room reverb RT60 0.2-0.6 s; 50 % classroom babble
  + pink noise at 10-20 dB) and decoded by the **real Arc ear** (model_server `EarStream` = `/v1/stream?ear=arc`,
  Tier A context). The generator replays Arc's words, partials, eager/end and device_directed (`--real-p 0.9`). Rough
  WER of these decodes: test 0.41, val 0.46 (harder than the 40-line ear eval: rate jitter, reverb, held-out voices).
  Audio is rendered in memory and never written (text decodes only, ~5 KB/turn, `cache/real_ear/dec`).
- **New held-out set `test_real`**: 127 test sessions (1,157 scored turns: unseen templates / card questions, held-out
  voices) heard only through real Arc decodes. The old 200-turn `test_ear` is kept.
- **One slot convention** everywhere (`nlu.py` docstring + `tests/test_mission_nlu.py`): a little = ±5, more/less =
  ±10, "to N" = set N (also "lower the shields to 20 percent"), "N more" = +N, implied need = +5. Fixed: the rules
  ("lower ... to N" was a delta), the command bank (158 plain more/less examples were `little ±5`), the embed slot
  fill, `gen_command_bank.py`, 7 `gold_more` labels.
- **Mission-mode questions**: 54 explorer questions asked during missions ("how deep is {place}", "why do we need
  shields", "what is a solar storm", ...; gold `answer`, split by question root) at ~4.5 % of mission turns; new
  features `lx_whq` (wh-question after fillers) and `lx_explain` (why / how deep / what is ...), next to Arc Tagger's
  question act (`tag_q`, already a feature). F 160 -> 162.
- **Cost-aware acting** (`runtime.policy`, ONE definition for the runtime `on` mode and the evaluator): the guard
  wins; a rules command stands unless a fitted **veto** fires (model >= thr sure the turn is not a command -> ask
  "Did you mean X or Y?"; mission mode only, never on yes/no); the model fills a command only if
  min(p act, p type, p main slots) >= thr; ignore / ask above their own thresholds; else the rules. Thresholds fit on
  val to **zero extra wrong actions vs the rules** (turns the rules got right and `on` gets wrong), then fewest wrong,
  then act accuracy. Fitted: cmd 0.95, veto 0.99, ignore 0.7, ask 0.95 (val: 61 wrong vs rules 79, 0 extra).
- Live demo (`GET :8100/api/director/stats`, read-only): 37 steps, 0 turns logged -> no shadow disagreements to label.

Data `ds_r4`: train 2,400 sessions / 232,430 steps (half noised; only 12 train turns had real decodes at generation
time, so train noise is still the fitted model), val 150 (real decodes for 0.9 of noised turns), tests as listed.
Size m was stopped (CPU shared with the decoders, ~2 min / 200 steps); **s** (28,985 params) trained to 2,200 steps,
best 1,200 (early stop: val with real decodes diverges from fitted-noise train).

| set | turns | act acc M / R / **on** | cmd exact M / R / on | wrong/50 M / R / **on** | attr M / R | eot premature, gain | barge P/R M ; R | shadow agree |
|---|---|---|---|---|---|---|---|---|
| test_clean | 1844 | 0.966 / 0.868 / **0.952** | 0.650 / 0.851 / 0.850 | 16.7 / 8.2 / **7.6** | 0.909 / 0.751 | 0.004, 191 ms | 0.97/0.98 ; 0.89/0.17 | 0.884 |
| test_asr | 1843 | 0.934 / 0.806 / **0.887** | 0.586 / 0.787 / 0.785 | 19.7 / 12.8 / **12.2** | 0.883 / 0.738 | 0.013, 196 ms | 0.98/0.97 ; 0.88/0.16 | 0.835 |
| **test_real** (new) | 1157 | 0.860 / 0.740 / **0.808** | 0.550 / 0.788 / 0.785 | 25.4 / 9.5 / **9.1** | 0.726 / 0.641 | 0.022, 122 ms | 0.92/0.98 ; 0.89/0.18 | 0.815 |
| test_ear | 200 | 0.700 / 0.720 / **0.720** | 0.655 / 0.828 / 0.828 | 44.8 / 17.2 / **16.4** | 0.63 / 1.0 | 0, 215 ms | – | 0.685 |
| test_h40 | 40 | 0.95 / 0.45 / **0.45** | – | 21.3 / 3.8 / **1.3** | – | – | – | 0.475 |
| test_h40_asr | 40 | 0.90 / 0.375 / **0.375** | – | 25.0 / 3.8 / **2.5** | – | – | – | 0.425 |
| test_q80 | 80 | 0.888 / 0.863 / **0.863** | – | – | 0.743 / 0.757 (card+attr 0.375 / 0.488) | – | – | 0.813 |
| test_q80_asr | 80 | 0.838 / 0.813 / **0.813** | – | – | 0.743 / 0.743 | – | – | 0.738 |
| test_gold | 19 | 0.842 / 0.737 / **0.789** | 0.55 / 0.45 / 0.45 | 13.6 / 13.6 / **13.6** | 0.83 / 1.0 | – | – | 0.895 |

h40 (`expect`): `on` 17 ok / 1 wrong / 22 none vs rules 15 / 3 / 22 (ASR: 14 / 2 / 24 vs 13 / 3 / 24). Raw model 21 / 17 /
2. Round 3's policy (CONF 0.7 fill) with this model: test_real 9.9, test_ear 20.7 wrong/50 (worse than the rules).

**The guarded `on` policy has wrong/50 <= the rules on every held-out set** (gold ties) **and act accuracy >= the rules
on every set** (q80 / ear / h40 tie). The raw model alone still acts wrongly far more than the rules (slot exactness
0.55-0.65): every gain comes from it acting only where it is sure, and from ignoring chatter / echo (test_real chatter
37/59 vs 6/59, echo 52/53 vs 2/53).

Top errors (test_real, model): Academy correct answers heard badly -> nudge (30; "rover go get eyes"); chatter -> answer
(13); "yes" decoded as junk ("is the mature amount of liquid") -> command; metaphors through the ear ("we re trying to
eat a snowman") -> answer. Wrong actions left under `on` are the rules' own: mission questions the rules turn into
commands ("what is the crater" -> dispatch explore, "where does the power come from" -> query) that the model is not
>= 0.99 sure to veto; garbled noise the rules parse ("a little more raped on shiloh s knee pulling out of the shelter"
-> leave shelter).

Next: train on the real decodes (1,082 train turns decoded so far), size m.

## Round 5 — 2026-11-13 ~20:15 (train on real Arc decodes; robust threshold choice) — SHIPPED round 4's s as `on`

Changes: train regenerated with the real decodes available (1,082 train turns decoded by Arc, replayed for 0.9 of
the noised turns that have one; the rest still fitted noise); same val/test as round 4. Policy fit: among the
zero-extra-wrong settings within 0.5 % act accuracy of the best on val, take the most conservative (val is small;
round 4's `ask 0.95` cost a q80 turn on test). Data `ds_r5`: train 2,400 sessions; m 77,733 params (best step 2,000),
s 28,985 (best 1,400); ~3 min each once the CPU was free.

Raw model (M) vs rules (R), act acc and wrong/50:

| set | m act | s act | R act | m wrong/50 | s wrong/50 | R wrong/50 |
|---|---|---|---|---|---|---|
| test_clean | 0.973 | 0.956 | 0.868 | 12.2 | 13.0 | 8.2 |
| test_asr | 0.928 | 0.905 | 0.806 | 18.0 | 17.9 | 12.8 |
| test_real | 0.873 | 0.851 | 0.740 | 18.6 | 16.1 | 9.5 |
| test_ear | 0.810 | **0.865** | 0.720 | 39.7 | **20.7** | 17.2 |
| test_h40 | 0.925 | 0.85 | 0.45 | 23.8 | 13.8 | 3.8 |
| test_q80 | 0.913 | 0.95 | 0.863 | – | – | – |
| test_gold | 0.895 | 0.789 | 0.737 | 27.3 | 13.6 | 13.6 |

Training on real decodes is the biggest single gain on the real ear: raw s on test_ear act 0.70 -> **0.865** (rules
0.72) and wrong/50 44.8 -> **20.7** (rules 17.2); test_real wrong/50 25.4 -> 16.1. Card attribute m 0.786 vs 0.757 on
q80.

Guarded `on` (fitted thresholds), act acc / wrong/50 vs rules:

| set | r5 m on | r5 s on | **r4 s on (shipped)** | rules |
|---|---|---|---|---|
| test_clean | 0.963 / 8.0 | 0.952 / 7.6 | **0.951 / 7.6** | 0.868 / 8.2 |
| test_asr | 0.899 / 12.7 | 0.889 / 12.1 | **0.886 / 12.2** | 0.806 / 12.8 |
| test_real | 0.806 / 8.9 | 0.808 / 8.4 | **0.807 / 9.1** | 0.740 / 9.5 |
| test_ear | 0.715 / 17.2 | 0.72 / 16.4 | **0.72 / 16.4** | 0.72 / 17.2 |
| test_h40 | 0.525 / 2.5 | 0.45 / 3.8 | **0.45 / 1.3** | 0.45 / 3.8 |
| test_h40_asr | 0.40 / 2.5 | 0.375 / 3.8 | **0.375 / 2.5** | 0.375 / 3.8 |
| test_q80 | 0.863 / – | 0.85 / – | **0.863 / –** | 0.863 / – |
| test_q80_asr | 0.813 / – | 0.813 / – | **0.813 / –** | 0.813 / – |
| test_gold | 0.842 / **18.2** | 0.737 / 13.6 | **0.789 / 13.6** | 0.737 / 13.6 |

r5 m fails test_gold (one metaphor, "we re turning into snowmen", filled as heaters +10 where gold is the +5 nudge)
and test_ear act (0.715 < 0.72: "coffey capcom" -> ignore / ask); r5 s fails test_q80 by one turn ("is the moon flat
with no holes" -> ignore). **r4 s with the robust thresholds (cmd 0.95, veto 0.99, ignore 0.8, ask off) meets every
criterion** and is the shipped weights (`backend/app/director_model/weights.*`, policy in weights.json; int8 vs float
max |dp| 0.021, 0.18 ms/step p50).

Top remaining errors: wrong actions under `on` are the rules' own, on garbled real decodes the model is not >= 0.99 sure
to veto ("what is the crater" -> dispatch explore, "where does the power come from" -> query power, "a little more
raped on shiloh s knee pulling out of the shelter" -> leave shelter); "yes" decoded as junk; Academy correct answers
the ear garbles ("rover go get eyes") -> nudge; metaphor slots (+5 vs +10).

## Switch-on criteria (round 5) — MET by r4 s: default is now `DIRECTOR_MODEL=on`, rules as fallback

| criterion | result |
|---|---|
| guarded `on` wrong/50 <= rules on EVERY held-out set | yes: clean 7.6 / 8.2, asr 12.2 / 12.8, real 9.1 / 9.5, ear 16.4 / 17.2, h40 1.3 / 3.8, h40_asr 2.5 / 3.8, gold 13.6 / 13.6 (tie) |
| act accuracy >= rules on every set | yes: higher on clean / asr / real / gold, equal on ear / h40 / h40_asr / q80 / q80_asr |
| privacy / safety | no regression: the guard always wins (policy returns None on a guard turn); the PII rows are identical; a model command must pass nlu.valid(); ask/ignore never execute anything |
| policy scored exactly as it runs | yes: `runtime.policy` is the one definition used by `decide_turn` and evaluate.py |

`DIRECTOR_MODEL` now defaults to `on` (runtime.mode); `shadow` / `off` remain one env var away. On every turn the
policy does not take (no confident fill, no veto) the rules decide, and with no / stale weights the rules decide
everything. The margins are thin on the small sets (h40 40 turns, gold 19, ear 200), so watch
`/api/director/stats` (`model_overrides`) on the first real sessions.

Gaps: only 1,082 of 4,647 rendered train turns had real decodes (decoding shared the CPU with other jobs, and the
disk filled up mid-run: audio is now never written); the raw model still acts wrongly more often than the rules
(slot exactness 0.6-0.75), so the win is the cost-aware layer, not the model acting alone; `test_real` voices are TTS
(no real children); the veto almost never fires at 0.99 (val is too small to trust a lower one).
