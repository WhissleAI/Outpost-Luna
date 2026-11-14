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
