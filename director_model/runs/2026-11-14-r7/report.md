# Director loop round 7 (2026-11-14): two candidates, m and xl, each gated against the shipped r4 s weights

## Candidate m

# Director loop m

Data `director_model/data/ds_r7`; candidate `director_model/runs/2026-11-14-r7/m/cand`; shipped = `backend/app/director_model/weights.*` before this run.

**Gate: FAIL — the shipped weights stay**

Reasons:
- test_ear: wrong actions 22 > rules 20
- test_ear: act acc 0.705 < rules 0.715
- cls_panel: wrong actions 20 > rules 19
- cls_roomtalk: class regresses: act acc 0.8 < shipped 0.8125

Fitted policy: `{"cmd": 0.95, "veto": 0.9, "ignore": 0.8, "ask": 0.9, "answer_ignore": null, "nav": null}`

| set | turns | act acc rules / shipped on / **new on** | wrong actions rules / shipped / **new** | wrong/50 rules / shipped / **new** | raw new model act | gate |
|---|---|---|---|---|---|---|
| test_clean | 1979 | 0.802 / 0.806 / **0.804** | 126 / 126 / **120** | 9.5 / 9.5 / **9.0** | 0.935 | ok |
| test_asr | 1977 | 0.716 / 0.721 / **0.720** | 168 / 167 / **160** | 14.1 / 14.0 / **13.4** | 0.878 | ok |
| test_real | 878 | 0.597 / 0.601 / **0.598** | 70 / 69 / **68** | 15.1 / 14.9 / **14.7** | 0.799 | ok |
| test_ear | 200 | 0.715 / 0.715 / **0.705** | 20 / 19 / **22** | 17.2 / 16.4 / **19.0** | 0.715 | FAIL |
| test_h40 | 40 | 0.450 / 0.450 / **0.525** | 3 / 1 / **1** | 3.8 / 1.2 / **1.2** | 0.825 | ok |
| test_h40_asr | 40 | 0.400 / 0.400 / **0.450** | 4 / 3 / **3** | 5.0 / 3.8 / **3.8** | 0.825 | ok |
| test_q80 | 80 | 0.850 / 0.850 / **0.850** | 1 / 1 / **1** | – / – / **–** | 0.875 | ok |
| test_q80_asr | 80 | 0.812 / 0.812 / **0.812** | 0 / 0 / **0** | – / – / **–** | 0.912 | ok |
| test_gold | 19 | 0.789 / 0.789 / **0.789** | 3 / 3 / **2** | 13.6 / 13.6 / **9.1** | 0.895 | ok |
| cls_chatter | 160 | 0.912 / 0.912 / **0.912** | 0 / 0 / **0** | – / – / **–** | 0.812 | ok |
| cls_echo | 160 | 0.844 / 0.856 / **0.906** | 9 / 9 / **5** | – / – / **–** | 0.869 | ok |
| cls_offer | 160 | 0.719 / 0.719 / **0.719** | 0 / 0 / **0** | – / – / **–** | 0.900 | ok |
| cls_panel | 160 | 0.775 / 0.775 / **0.775** | 19 / 23 / **20** | 13.2 / 16.0 / **13.9** | 0.681 | FAIL |
| cls_help | 159 | 0.629 / 0.629 / **0.629** | 1 / 1 / **1** | – / – / **–** | 0.598 | ok |
| cls_mode | 158 | 0.886 / 0.886 / **0.886** | 0 / 0 / **0** | – / – / **–** | 0.430 | ok |
| cls_globe | 160 | 0.675 / 0.675 / **0.675** | 3 / 3 / **3** | – / – / **–** | 0.869 | ok |
| cls_mishear | 160 | 0.738 / 0.725 / **0.738** | 1 / 1 / **1** | 0.9 / 0.9 / **0.9** | 0.800 | ok |
| cls_roomtalk | 160 | 0.756 / 0.812 / **0.800** | 1 / 1 / **1** | – / – / **–** | 0.719 | FAIL |

Chatter graded as a lesson answer (rules / shipped / new): test_real (2, 2, 2), cls_chatter (13, 13, 13), cls_roomtalk (2, 2, 2)


## Candidate xl

# Director loop xl

Data `director_model/data/ds_r7`; candidate `director_model/runs/2026-11-14-r7/xl/cand`; shipped = `backend/app/director_model/weights.*` before this run.

**Gate: FAIL — the shipped weights stay**

Reasons:
- test_clean: wrong actions 129 > rules 126
- test_h40: wrong actions 4 > rules 3
- cls_panel: wrong actions 20 > rules 19
- cls_roomtalk: class regresses: act acc 0.7812 < shipped 0.8125

Fitted policy: `{"cmd": 0.98, "veto": 0.98, "ignore": 0.95, "ask": 1.01, "answer_ignore": 0.7, "nav": null}`

| set | turns | act acc rules / shipped on / **new on** | wrong actions rules / shipped / **new** | wrong/50 rules / shipped / **new** | raw new model act | gate |
|---|---|---|---|---|---|---|
| test_clean | 1979 | 0.802 / 0.806 / **0.808** | 126 / 126 / **129** | 9.5 / 9.5 / **9.7** | 0.945 | FAIL |
| test_asr | 1977 | 0.716 / 0.721 / **0.721** | 168 / 167 / **166** | 14.1 / 14.0 / **13.9** | 0.880 | ok |
| test_real | 878 | 0.597 / 0.601 / **0.598** | 70 / 69 / **67** | 15.1 / 14.9 / **14.4** | 0.802 | ok |
| test_ear | 200 | 0.715 / 0.715 / **0.715** | 20 / 19 / **19** | 17.2 / 16.4 / **16.4** | 0.790 | ok |
| test_h40 | 40 | 0.450 / 0.450 / **0.525** | 3 / 1 / **4** | 3.8 / 1.2 / **5.0** | 0.775 | FAIL |
| test_h40_asr | 40 | 0.400 / 0.400 / **0.475** | 4 / 3 / **4** | 5.0 / 3.8 / **5.0** | 0.750 | ok |
| test_q80 | 80 | 0.850 / 0.850 / **0.850** | 1 / 1 / **1** | – / – / **–** | 0.938 | ok |
| test_q80_asr | 80 | 0.812 / 0.812 / **0.812** | 0 / 0 / **0** | – / – / **–** | 0.938 | ok |
| test_gold | 19 | 0.789 / 0.789 / **0.789** | 3 / 3 / **3** | 13.6 / 13.6 / **13.6** | 0.789 | ok |
| cls_chatter | 160 | 0.912 / 0.912 / **0.975** | 0 / 0 / **0** | – / – / **–** | 0.950 | ok |
| cls_echo | 160 | 0.844 / 0.856 / **0.938** | 9 / 9 / **7** | – / – / **–** | 0.944 | ok |
| cls_offer | 160 | 0.719 / 0.719 / **0.719** | 0 / 0 / **0** | – / – / **–** | 0.794 | ok |
| cls_panel | 160 | 0.775 / 0.775 / **0.775** | 19 / 23 / **20** | 13.2 / 16.0 / **13.9** | 0.681 | FAIL |
| cls_help | 159 | 0.629 / 0.629 / **0.629** | 1 / 1 / **1** | – / – / **–** | 0.503 | ok |
| cls_mode | 158 | 0.886 / 0.886 / **0.886** | 0 / 0 / **0** | – / – / **–** | 0.392 | ok |
| cls_globe | 160 | 0.675 / 0.675 / **0.675** | 3 / 3 / **3** | – / – / **–** | 0.844 | ok |
| cls_mishear | 160 | 0.738 / 0.725 / **0.738** | 1 / 1 / **1** | 0.9 / 0.9 / **0.9** | 0.719 | ok |
| cls_roomtalk | 160 | 0.756 / 0.812 / **0.781** | 1 / 1 / **1** | – / – / **–** | 0.713 | FAIL |

Chatter graded as a lesson answer (rules / shipped / new): test_real (2, 2, 2), cls_chatter (13, 13, 3), cls_roomtalk (2, 2, 1)

