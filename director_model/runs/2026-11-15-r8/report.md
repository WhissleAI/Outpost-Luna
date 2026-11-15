# Director loop round 8 (2026-11-15): m and xl, each gated against the shipped r4 s weights; every class set gates

## Candidate m

# Director loop m

Data `director_model/data/ds_r8`; candidate `director_model/runs/2026-11-15-r8/m/cand`; shipped = `backend/app/director_model/weights.*` before this run.

**Gate: FAIL — the shipped weights stay**

Reasons:
- test_real: wrong actions 69 > rules 67
- test_real: act acc 0.588 < rules 0.5891
- test_ear: wrong actions 22 > rules 20
- cls_roomtalk: class regresses: act acc 0.8553 < shipped 0.8742
- cls_prep_roomtalk: class regresses: act acc 0.925 < shipped 0.9375

Fitted policy: `{"cmd": 0.9, "veto": 0.98, "ignore": 0.9, "ask": 0.7, "answer_ignore": 0.7, "nav": null}`

| set | turns | act acc rules / shipped on / **new on** | wrong actions rules / shipped / **new** | wrong/50 rules / shipped / **new** | raw new model act | gate |
|---|---|---|---|---|---|---|
| test_clean | 2001 | 0.787 / 0.792 / **0.788** | 132 / 132 / **121** | 9.9 / 9.9 / **9.1** | 0.944 | ok |
| test_asr | 1998 | 0.703 / 0.709 / **0.706** | 164 / 162 / **153** | 13.6 / 13.5 / **12.7** | 0.883 | ok |
| test_real | 920 | 0.589 / 0.590 / **0.588** | 67 / 67 / **69** | 14.4 / 14.4 / **14.8** | 0.812 | FAIL |
| test_ear | 200 | 0.720 / 0.720 / **0.720** | 20 / 19 / **22** | 17.2 / 16.4 / **19.0** | 0.820 | FAIL |
| test_h40 | 40 | 0.450 / 0.450 / **0.575** | 3 / 1 / **3** | 3.8 / 1.2 / **3.8** | 0.825 | ok |
| test_h40_asr | 40 | 0.400 / 0.400 / **0.475** | 4 / 3 / **4** | 5.0 / 3.8 / **5.0** | 0.750 | ok |
| test_q80 | 80 | 0.850 / 0.850 / **0.850** | 1 / 1 / **1** | – / – / **–** | 0.938 | ok |
| test_q80_asr | 80 | 0.812 / 0.812 / **0.812** | 0 / 0 / **0** | – / – / **–** | 0.925 | ok |
| test_gold | 19 | 0.789 / 0.789 / **0.789** | 3 / 3 / **3** | 13.6 / 13.6 / **13.6** | 0.895 | ok |
| cls_chatter | 160 | 0.912 / 0.912 / **0.919** | 2 / 2 / **2** | – / – / **–** | 0.838 | ok |
| cls_echo | 160 | 0.844 / 0.856 / **0.900** | 10 / 10 / **7** | – / – / **–** | 0.963 | ok |
| cls_offer | 160 | 0.700 / 0.700 / **0.700** | 3 / 3 / **3** | – / – / **–** | 0.812 | ok |
| cls_panel | 160 | 0.775 / 0.775 / **0.775** | 12 / 12 / **12** | 8.4 / 8.4 / **8.4** | 0.725 | ok |
| cls_help | 160 | 0.681 / 0.681 / **0.681** | 0 / 0 / **0** | – / – / **–** | 0.700 | ok |
| cls_mode | 159 | 0.805 / 0.805 / **0.805** | 1 / 1 / **1** | – / – / **–** | 0.761 | ok |
| cls_globe | 160 | 0.738 / 0.738 / **0.738** | 4 / 4 / **4** | – / – / **–** | 0.887 | ok |
| cls_mishear | 160 | 0.719 / 0.700 / **0.719** | 18 / 18 / **18** | 18.4 / 18.4 / **18.4** | 0.731 | ok |
| cls_roomtalk | 159 | 0.843 / 0.874 / **0.855** | 3 / 3 / **3** | – / – / **–** | 0.811 | FAIL |
| cls_video_ctrl | 160 | 0.419 / 0.419 / **0.419** | 17 / 17 / **17** | – / – / **–** | 0.456 | ok |
| cls_video_echo | 140 | 1.000 / 1.000 / **1.000** | 0 / 0 / **0** | – / – / **–** | 1.000 | ok |
| cls_prep | 160 | 0.569 / 0.569 / **0.569** | 0 / 0 / **0** | – / – / **–** | 0.225 | ok |
| cls_prep_roomtalk | 160 | 0.925 / 0.938 / **0.925** | 0 / 0 / **0** | – / – / **–** | 0.806 | FAIL |
| cls_voice_echo_os | 160 | 0.812 / 0.819 / **0.900** | 4 / 4 / **2** | – / – / **–** | 0.887 | ok |
| cls_gesture_cooccur | 160 | 0.812 / 0.812 / **0.812** | 0 / 0 / **0** | – / – / **–** | 0.881 | ok |
| cls_lesson_new | 160 | 0.725 / 0.725 / **0.725** | 2 / 2 / **2** | – / – / **–** | 0.894 | ok |
| cls_offers_new | 160 | 0.562 / 0.562 / **0.562** | 18 / 18 / **0** | – / – / **–** | 0.637 | ok |
| cls_coverage | 3009 | 0.840 / 0.840 / **0.845** | 49 / 49 / **47** | 98.0 / 98.0 / **94.0** | 0.643 | ok |

Chatter graded as a lesson answer (rules / shipped / new): test_clean (1, 1, 1), test_asr (1, 1, 1), test_real (1, 1, 1), cls_chatter (12, 12, 11), cls_roomtalk (4, 4, 4), cls_coverage (5, 5, 0)


## Candidate xl

# Director loop xl

Data `director_model/data/ds_r8`; candidate `director_model/runs/2026-11-15-r8/xl/cand`; shipped = `backend/app/director_model/weights.*` before this run.

**Gate: FAIL — the shipped weights stay**

Reasons:
- test_real: act acc 0.5859 < rules 0.5891
- test_ear: act acc 0.715 < rules 0.72
- cls_mishear: act acc 0.6875 < rules 0.7188
- cls_mishear: class regresses: act acc 0.6875 < shipped 0.7
- cls_roomtalk: class regresses: act acc 0.8428 < shipped 0.8742
- cls_prep_roomtalk: class regresses: act acc 0.925 < shipped 0.9375
- cls_lesson_new: act acc 0.7125 < rules 0.725
- cls_lesson_new: class regresses: act acc 0.7125 < shipped 0.725

Fitted policy: `{"cmd": 0.995, "veto": 0.9, "ignore": 0.95, "ask": 0.7, "answer_ignore": 0.7, "nav": null}`

| set | turns | act acc rules / shipped on / **new on** | wrong actions rules / shipped / **new** | wrong/50 rules / shipped / **new** | raw new model act | gate |
|---|---|---|---|---|---|---|
| test_clean | 2001 | 0.787 / 0.792 / **0.789** | 132 / 132 / **129** | 9.9 / 9.9 / **9.7** | 0.956 | ok |
| test_asr | 1998 | 0.703 / 0.709 / **0.712** | 164 / 162 / **156** | 13.6 / 13.5 / **13.0** | 0.901 | ok |
| test_real | 920 | 0.589 / 0.590 / **0.586** | 67 / 67 / **64** | 14.4 / 14.4 / **13.7** | 0.800 | FAIL |
| test_ear | 200 | 0.720 / 0.720 / **0.715** | 20 / 19 / **13** | 17.2 / 16.4 / **11.2** | 0.800 | FAIL |
| test_h40 | 40 | 0.450 / 0.450 / **0.575** | 3 / 1 / **3** | 3.8 / 1.2 / **3.8** | 0.900 | ok |
| test_h40_asr | 40 | 0.400 / 0.400 / **0.450** | 4 / 3 / **3** | 5.0 / 3.8 / **3.8** | 0.800 | ok |
| test_q80 | 80 | 0.850 / 0.850 / **0.850** | 1 / 1 / **1** | – / – / **–** | 0.863 | ok |
| test_q80_asr | 80 | 0.812 / 0.812 / **0.812** | 0 / 0 / **0** | – / – / **–** | 0.863 | ok |
| test_gold | 19 | 0.789 / 0.789 / **0.789** | 3 / 3 / **3** | 13.6 / 13.6 / **13.6** | 0.895 | ok |
| cls_chatter | 160 | 0.912 / 0.912 / **0.925** | 2 / 2 / **2** | – / – / **–** | 0.750 | ok |
| cls_echo | 160 | 0.844 / 0.856 / **0.931** | 10 / 10 / **2** | – / – / **–** | 0.963 | ok |
| cls_offer | 160 | 0.700 / 0.700 / **0.700** | 3 / 3 / **3** | – / – / **–** | 0.562 | ok |
| cls_panel | 160 | 0.775 / 0.775 / **0.781** | 12 / 12 / **11** | 8.4 / 8.4 / **7.8** | 0.713 | ok |
| cls_help | 160 | 0.681 / 0.681 / **0.681** | 0 / 0 / **0** | – / – / **–** | 0.669 | ok |
| cls_mode | 159 | 0.805 / 0.805 / **0.805** | 1 / 1 / **1** | – / – / **–** | 0.623 | ok |
| cls_globe | 160 | 0.738 / 0.738 / **0.738** | 4 / 4 / **4** | – / – / **–** | 0.863 | ok |
| cls_mishear | 160 | 0.719 / 0.700 / **0.688** | 18 / 18 / **18** | 18.4 / 18.4 / **18.4** | 0.644 | FAIL |
| cls_roomtalk | 159 | 0.843 / 0.874 / **0.843** | 3 / 3 / **3** | – / – / **–** | 0.786 | FAIL |
| cls_video_ctrl | 160 | 0.419 / 0.419 / **0.419** | 17 / 17 / **17** | – / – / **–** | 0.600 | ok |
| cls_video_echo | 140 | 1.000 / 1.000 / **1.000** | 0 / 0 / **0** | – / – / **–** | 1.000 | ok |
| cls_prep | 160 | 0.569 / 0.569 / **0.569** | 0 / 0 / **0** | – / – / **–** | 0.250 | ok |
| cls_prep_roomtalk | 160 | 0.925 / 0.938 / **0.925** | 0 / 0 / **0** | – / – / **–** | 0.775 | FAIL |
| cls_voice_echo_os | 160 | 0.812 / 0.819 / **0.950** | 4 / 4 / **2** | – / – / **–** | 0.919 | ok |
| cls_gesture_cooccur | 160 | 0.812 / 0.812 / **0.812** | 0 / 0 / **0** | – / – / **–** | 0.925 | ok |
| cls_lesson_new | 160 | 0.725 / 0.725 / **0.713** | 2 / 2 / **2** | – / – / **–** | 0.900 | FAIL |
| cls_offers_new | 160 | 0.562 / 0.562 / **0.562** | 18 / 18 / **0** | – / – / **–** | 0.794 | ok |
| cls_coverage | 3009 | 0.840 / 0.840 / **0.844** | 49 / 49 / **46** | 98.0 / 98.0 / **92.0** | 0.627 | ok |

Chatter graded as a lesson answer (rules / shipped / new): test_clean (1, 1, 1), test_asr (1, 1, 1), test_real (1, 1, 1), cls_chatter (12, 12, 10), cls_roomtalk (4, 4, 2), cls_coverage (5, 5, 0)

