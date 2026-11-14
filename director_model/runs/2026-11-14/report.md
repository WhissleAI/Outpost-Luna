# Director loop 2026-11-14

Data `director_model/data/ds_r6`; candidate `director_model/runs/2026-11-14/cand`; shipped = `backend/app/director_model/weights.*` before this run.

**Gate: FAIL — the shipped weights stay**

Reasons:
- test_clean: wrong actions 89 > rules 87
- test_real: wrong actions 47 > rules 46
- cls_panel: wrong actions 11 > rules 7
- cls_panel: class regresses: wrong 11 > shipped 7
- cls_mishear: act acc 0.6937 < rules 0.7375
- not better than the shipped weights overall: wrong 321 vs 313, right acts 4903 vs 4874

Fitted policy: `{"cmd": 0.9, "veto": 0.95, "ignore": 0.7, "ask": 1.01, "answer_ignore": null}`

| set | turns | act acc rules / shipped on / **new on** | wrong actions rules / shipped / **new** | wrong/50 rules / shipped / **new** | raw new model act | gate |
|---|---|---|---|---|---|---|
| test_clean | 1979 | 0.803 / 0.807 / **0.805** | 87 / 87 / **89** | 6.5 / 6.5 / **6.7** | 0.933 | FAIL |
| test_asr | 1977 | 0.714 / 0.719 / **0.719** | 134 / 133 / **133** | 11.2 / 11.1 / **11.1** | 0.877 | ok |
| test_real | 1081 | 0.618 / 0.618 / **0.619** | 46 / 46 / **47** | 7.7 / 7.7 / **7.9** | 0.840 | FAIL |
| test_ear | 200 | 0.715 / 0.715 / **0.720** | 20 / 19 / **19** | 17.2 / 16.4 / **16.4** | 0.740 | ok |
| test_h40 | 40 | 0.450 / 0.450 / **0.525** | 3 / 1 / **3** | 3.8 / 1.2 / **3.8** | 0.925 | ok |
| test_h40_asr | 40 | 0.400 / 0.400 / **0.450** | 4 / 3 / **3** | 5.0 / 3.8 / **3.8** | 0.800 | ok |
| test_q80 | 80 | 0.850 / 0.850 / **0.850** | 0 / 0 / **0** | – / – / **–** | 0.950 | ok |
| test_q80_asr | 80 | 0.825 / 0.825 / **0.825** | 0 / 0 / **0** | – / – / **–** | 0.975 | ok |
| test_gold | 19 | 0.789 / 0.789 / **0.789** | 3 / 3 / **3** | 13.6 / 13.6 / **13.6** | 0.842 | ok |
| cls_chatter | 160 | 0.969 / 0.969 / **0.969** | 0 / 0 / **0** | – / – / **–** | 0.819 | ok |
| cls_echo | 160 | 0.844 / 0.863 / **0.975** | 5 / 4 / **3** | – / – / **–** | 0.994 | ok |
| cls_offer | 160 | 0.600 / 0.600 / **0.600** | 9 / 9 / **9** | – / – / **–** | 1.000 | ok |
| cls_panel | 160 | 0.731 / 0.731 / **0.731** | 7 / 7 / **11** | 9.5 / 9.5 / **14.9** | 0.731 | FAIL |
| cls_help | 160 | 0.487 / 0.487 / **0.487** | 0 / 0 / **0** | – / – / **–** | 0.794 | ok |
| cls_mode | 160 | 0.463 / 0.463 / **0.463** | 0 / 0 / **0** | – / – / **–** | 0.963 | ok |
| cls_globe | 160 | 0.631 / 0.631 / **0.631** | 0 / 0 / **0** | – / – / **–** | 0.775 | ok |
| cls_mishear | 160 | 0.738 / 0.637 / **0.694** | 1 / 1 / **1** | 1.2 / 1.2 / **1.2** | 0.581 | FAIL |

Chatter graded as a lesson answer (rules / shipped / new): test_real (1, 1, 1), cls_chatter (5, 5, 5)

Also gated this round (same data):

- **s** (28,985 params): FAIL. cls_echo is one turn below the shipped weights (0.856 vs 0.863), and overall it has
  315 vs 313 wrong.
- **The shipped weights with a policy refit on this val**: FAIL on test_clean, test_real, cls_echo, cls_panel and
  cls_mishear.

The before / after table and findings are in `director_model/RESULTS.md`, round 6.

The shipped weights are below the rules on cls_mishear (0.637 vs 0.738): their ignore fill silences misheard real
answers. This needs a decision: keep `on`, or run `DIRECTOR_MODEL=shadow` until the next round.
