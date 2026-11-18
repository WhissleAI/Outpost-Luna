# Arc Transcriber Space v2: measured against what we ship (2026-11-17)

The Arc team's update ("Arc Transcriber v2 — Update for the Luna App Team", 17 Nov 2026) replaces the recogniser of
`WhissleAI/arc-transcriber-space` (revision `d35e3e7002ddd89325ecad626171dc08891656d9`), keeps the decoder (names,
punctuation) and adds `nft2/room.onnx`: per-utterance room read-outs (utterance type, end of turn, app playback, media,
and two BETA outputs, addressee and kids safety). This document records what we measured on our own sets, what this
PR integrates, and what it leaves off.

**Verdict:** the v2 recogniser is **not** pinned as the app's ear for 0.3.12. On our kid sets it hears more (WER, short turns,
names, numbers all better), but on the same sets the shipped Director makes **more wrong actions** with it (143 → 164 on
the held-out sets, section 4), its device-directed head shifts down, it transcribes the app's own voices far more often,
the golden WER goes from 1.6 % to 3.3 %, and its playback head does not separate our own voice from a kid on Karan's
real laptop recording. This PR integrates the room read-outs (libarc tap, ONNX Runtime, shadow on the final words) so
the flip is one constant when Arc's next release clears these gates; with the shipped v1 model they are inert.

Code: `model_server/app/arc_room.py` (room.onnx on ONNX Runtime), `model_server/app/arc_ear.py` (`EAR_ROOM`,
`room` on the final words), `model_server/app/nft2.py` (`transcribe(tap=True)`), `desktop/vendor/libarc`
(`arc_nft2_tap`, ARC_VERSION `1.3.0-outpost.2`, ABI unchanged), `backend/app/session.py` (`EAR_V2`: kept on the turn's
ear read, shadow). Tests: `model_server/tests/test_arc_room.py`, `backend/tests/test_arc_v2_room.py`,
`desktop/tests/fuzz/fuzz_libarc.c` (the tap).

## 1. What changed in the files

22 files in `nft2/SHA256SUMS`, all verified on a fresh download at the pinned revision. Against the shipped
`176d324`: 7 changed (`config.json`, `encoder_onnx/{encoder.onnx, encoder.weights, encoder_first.onnx, decoder.onnx,
joint_enc.onnx, joint_net.onnx}`), 1 new (`room.onnx`, 9.1 MB), the rest byte-identical (`decoder/`, adapters,
`model.q4.safetensors`, `tags.json`, frontend, tokenizer). So the "new recogniser" is the encoder + RNNT; the Arc
decoder and its heads read the new encoder's frames. The arc_transcriber C sources did not change between `0aa792f`
(our vendored ABI 2) and `f8bb78d` (1.3.0): our libarc loads v2 as is.

## 2. How the room read-outs run (libarc does not run room.onnx)

room.onnx reads the encoder's Arc tap (layer 9, 80 ms frames), the microphone audio and, optionally, the app's playback
reference. arc_audio 1.3.0 gets the tap from a second encoder pass in Python. We do not: libarc already computes the tap
for the clip decode and memoises it, so a small local addition, `arc_nft2_tap` (+ `arc_nft2_tap_free`), copies it out
right after `arc_nft2_transcribe`, under the same model lock: no second encoder pass, no second copy of the 282 MB
encoder weights. It is an addition only (no existing declaration changes), so the ABI stays 2 and the version is
`1.3.0-outpost.2`; bindings regenerated; `fuzz:libarc` now also calls it (the decode's memo, a fresh pass on a cut of the
clip, NULL pcm, odd lengths).

Parity with Arc's own path (arc_audio f8bb78d `OnnxEncoder` + `Room`, ONNX Runtime 1.20 in Python) on 12 golden clips:
tap correlation 0.9998-0.9999 (relative error 1.3-1.7 %, int8 kernels of two ORT versions); act label 12/12 equal,
end_of_turn within 0.02, playback share within one 80 ms frame, addressee 12/12 equal.

Cost: room.onnx on one intra-op thread, p50 6.3 ms / p90 11.9 ms per turn (#125's set, loaded machine). It runs
after the clip decode, before the final words go out; the turn's own audio, cut to its last 20 s.

`EAR_ROOM=shadow` (default): the final words carry `room` = `{act {label, p, probs}, end_of_turn, playback,
playback_max, media, live_speech, reference, addressee {..., beta: true}, safety {above_threshold, max_p, beta: true},
ms}`. `EAR_ROOM=off` skips it. With the v1 model (no room section) nothing changes. `EAR_ROOM_REF=0` runs it without the
playback reference (measurement only). `/health` reports `models.arc_room`.

## 3. A/B: the shipped ear (`176d324`) vs v2 (`d35e3e7`)

Same code (this branch: libarc `1.3.0-outpost.2`, the app's `EarStream`, live mode, names lists from `names_list`), only
the model folder differs; v1 with `EAR_ROOM=off`, v2 with `EAR_ROOM=shadow`. All speech is synthetic (Mac voices):
directional, not a child benchmark. The machine was shared with a video build (load 5-30); timing rows say how they
were run.

### Golden (`release_check.golden_run` on a source build, 40 clips, two rounds alternating v1 / v2)

| | v1 (shipped) | v2 |
|---|---|---|
| WER | **1.6 %** | 3.3 % (3 noisy clips gain words: "… Vehicle? copy captain", "… Koch do? 25", "and How far …") |
| names / linked / numbers | 23/23 · 23/23 · 11/12 | 23/23 · 23/23 · 11/12 |
| p50 (round 1 / 2) | 1055 / 1091 ms (load 15 / 12) | 931 / 884 ms (load 8 / 8) |
| p95 (round 1 / 2) | 1857 / 2062 ms | 1935 / 1952 ms |

Both within the 1519 ms budget. v2 is not slower; the p50 gap follows the machine load (the rounds alternated but the
video agent's load did not), so it is not a speed-up claim. The WER rule "no worse than main" fails.

### #125's set (758 kid turns + 258 echo-bank clips, re-rendered from seeds; `EarStream` in 80 ms frames)

| | v1 (shipped) | v2 |
|---|---|---|
| WER | 35.1 % | **34.2 %** |
| names in the list (380): linked right / wrong / none | 55.5 / 6.1 / 38.4 % | **60.5 / 5.8** / 33.7 % |
| explorer turns (491): act right / act wrong / act on a turn that names no place | 137 / 33 / 6 | **147 / 26** / 11 |
| "Did you mean" (shipped arc_first): right / wrong / spurious | 69 / 5 / 1 | 76 / 7 / 5 |
| name said, nothing done | 45 | **33** |
| numbers carried (215): words / + quantities | 60.5 / 68.4 % | **64.2 / 73.0 %** |
| empty decodes: 1-word / 2-word / all kid turns | 33.3 / 24.8 / 10.6 % | **17.9 / 4.8 / 3.7 %** |
| echo bank (our audio alone): clips with words / words per clip | **54.7 % / 2.62** | 72.9 % / 3.98 |
| kid turns over our OS voice / crew clip: ≥ 2 inserted words | **6.2 / 13.3 %** | 21.1 / 24.1 % |
| final decode p50 / p90 | 546 / 933 ms | 563 / 999 ms |
| close (last voice → final words, real-time queue) p50 / p90 | 1176 / 1779 ms | 1200 / 1868 ms |
| ear CPU s per audio s (all threads; v2 incl. room) | 0.628 | 0.667 |
| peak RSS of one decode process | ~1000 MB | ~1024 MB |
| room.onnx per turn p50 / p90 | | 6.3 / 11.9 ms |

### Round-11 ear set (the round-12 jobs re-decoded; `director_model/real_ear.py decode`)

| | held-out Mac voices (`voice_ho`, 381) v1 / v2 | Steer TTS `test` group (1,242) v1 / v2 |
|---|---|---|
| WER | 49.4 / **45.6 %** | 10.2 / **9.3 %** |
| empty decodes | 12.1 / **5.8 %** | 4.0 / **1.2 %** |
| 1-2 word turns empty | 17/50 / **5/50** | 44/345 / **14/345** |
| links / of them naming an entry the reference names | 30 / 23 → 39 / 28 | 190 / 158 → 196 / 164 |
| directed head, median / share under the 0.05 knee (= `device_directed` < DD_MIN) | 0.78 / 10.7 % → **0.53 / 18.4 %** | 0.79 / 18.3 % → **0.44 / 25.8 %** |

### What moves under the Director (#125's 758 kid turns)

| ear read-out | v1 p10 / median / p90 | v2 |
|---|---|---|
| `device_directed` (app scale) | 0.517 / 0.911 / 0.999 | **0.360 / 0.795** / 0.998 |
| `uconf` | 0.458 / 0.711 / 0.874 | 0.449 / 0.702 / 0.877 |
| `agree` (RNNT vs decoder) | 0.118 / 0.667 / 1.0 | 0.143 / 0.727 / 1.0 |
| `eot` on the final words | 0.004 / 0.042 / 0.349 | identical |
| `almost` p | 0.651 / 0.808 / 0.981 | 0.651 / 0.808 / 0.987 |

38 directed kid turns fall under DD_MIN with v2 (5 go the other way); 69 turns link a different set of names; 54 flip
between empty and non-empty. `conf` / `alts` stay null / [] and `trained_zero` keeps the round-7 slots at 0, so the
change reaches the shipped weights through the words, the links and `dd`, not through dead slots.

## 4. Director parity (shipped config: r12 xl quiet + r10 hot / echo, `gate_r12.py` on regenerated sets)

The round-12 `test_real` and `test_voice_heldout` sessions, regenerated from each decode cache (same scripts and seeds;
the other groups' decodes unchanged). Act ok (wrong):

| set | v1: rules / shipped | v2: rules / shipped | v2 + `dd` re-mapped to v1's quantiles (knee 0.01, strong 0.171) |
|---|---|---|---|
| test_real | 536 (92) / 536 (92), 887 turns | 525 (110) / 525 (110), 906 turns | 534 (114) / 535 (114) |
| test_voice_heldout | 244 (51) / 244 (51), 502 turns | 246 (54) / 246 (54), 534 turns | 258 (56) / 258 (56) |
| **all** | **780 (143)** | 771 (**164**) | 793 (**170**) |

By class (shipped config, turns / ok / wrong): quiet 497 / 208 / 83 → 520 / 197 / **101**; hot 592 / 433 / 55 → 626 / 443 /
58; echo 157 / 97 / 2 → 158 / 89 / 2. v2 hears more turns (fewer empty decodes) and more of them become wrong actions,
mostly in quiet room talk. Re-mapping the shifted directed head restores act ok (+12 over v1) but not the wrong count.
**Rule: never ship a change that moves the Director's wrong count up**, so v2 is not the ear. Round 13 (the re-decode
in `docs/ARC_ABI2.md` section 6) should train on v2 decodes if v2 is to ship: the Director learnt v1's `dd` and words.

## 5. Echo: the v2 playback head on Karan's real recording

`echo_set/mac_m3pro_builtin_2026-11-16` (25 min, 295 lines, MacBook Pro M3 Pro speakers → mic) through the app's own
ear with the reference fed as `echoref.js` does, plus 161 round-11 kid turns mixed in (106 over our playback), routed by
`turn_router` (the `docs/ARC_ABI2.md` section 8 method; the kid set is the 161 of its 220 seeds still in the job list).
The room network ran on every final with the reference and without it.

| | v1 (shipped) | v2 |
|---|---|---|
| our own lines that put words into the ear (finals) | **180** | 304 |
| ... that become turns, no echo rule | 15 | 16 |
| kid turns heard / reaching the app (no rule) | 110 / 45 | **148 / 74** |
| playback_leak AUC, own-line finals vs kid-over-playback finals | 0.70 | 0.74 |
| **shipped rule (leak ≥ 0.85): own-line turns / kid turns lost / kid turns reaching the app** | **10 / 4 / 44** | 11 / 3 / 72 |
| room playback share AUC, own vs kid over playback: with reference / without | | **0.45 / 0.49** |
| room playback share, median own / kid over playback | | 0.74 / 0.78 |
| room playback ≥ 0.5 / 0.7 / 0.9 (reference): own-line turns / kid turns lost | | 0 / 143 · 0 / 97 · 6 / 8 |
| without reference ≥ 0.9 | | 9 / 7 |
| room ≥ 0.9 OR leak ≥ 0.85 | | 5 / 12 |

On this laptop the playback head is no better than chance at telling our voice from a kid talking over it, with or
without the reference, and every threshold that removes own-line turns throws kid turns away (kid voices here are Mac
voices mixed digitally; Arc warns synthetic voices read as playback, so this test is biased against the head; but it
is the only real echo we have, and it decides). **Kept: the leak rule** (`session.PLAYBACK_THRESHOLD` 0.85). On
#125's synthetic set the head flags 55 % of our own audio alone and 51 % of kid turns with our audio under them, and 33 %
of kid turns with no playback at all.

## 6. End of turn

Our end of turn is the VAD's silence (0.5 s, learned up to 0.8 s per child). The v2 room `end_of_turn` at that close,
on 101 rendered kid turns of 4+ words: the whole turn vs the same turn cut at the quietest point of its middle (what a
mid-sentence pause does): AUC 0.855; at 0.5 it would hold 30 % of the cut turns and delay none of the complete ones (at
0.7: 33 % / 2 %). Promising, but it needs the v2 encoder (room.onnx reads its tap) and has not been seen on a child: it
stays a shadow read-out, `room.end_of_turn`, for round 13 and the learner. libarc's stream `eot` is unchanged.

## 7. What this PR integrates and what it leaves off

| | status | why |
|---|---|---|
| v2 recogniser as the app's ear (manifest pin `d35e3e7`, asset tar, per-file hashes incl. `room.onnx`) | **left off** | Director wrong actions up (section 4), golden WER up, our own voice transcribed far more (section 3). `scripts/asset_pack.py` knows v2's extra files (`EAR_EXTRA`): flipping is `EAR_REVISION` + `arcmeta.ARC_REVISION` + `make asset-pack`. The v2 per-file sha256 are in Arc's `nft2/SHA256SUMS`; 22/22 verified. |
| room read-outs (act, end_of_turn, playback, media; addressee + safety BETA) | **integrated, shadow** | `EAR_ROOM=shadow`: on the final words as `room`, kept on the backend's turn read (`EAR_V2`), never read by a rule, the router, the echo drop, the safety path or the Director features (tests). Inert with the shipped v1 model. |
| libarc `arc_nft2_tap` | **integrated** | the tap from the decode's memo: no second encoder pass. ABI 2 unchanged, `1.3.0-outpost.2`; fuzzed under ASan + UBSan. |
| playback head for echo | **not used** | AUC 0.45 / 0.49 on the real recording (section 5). |
| room end_of_turn for the close | **not used** | v2-only, synthetic; shadow (section 6). |
| kids safety, addressee | **shadow, BETA, never an action** | safety stays with Arc Tagger's kids domain and the phrase backstops. On #125's (benign) kid turns the safety read-out put a class above Arc's threshold on 17.8 % of turns (`pii.leak` 78, `profanity.strong` 25, `toxicity.hate_identity` 16 of 752); addressee said "device" on 65 % of kid turns that were all addressed to the device. Nothing in the app shows them. |
| utterance type | shadow | 58 % right on 209 labelled kid turns (command / confirmation from the gold act, question from the wording). |

## 8. Gates on this branch (v1 model, as it ships)

- backend 1,341 passed / 3 skipped; model_server 151 passed / 56 skipped (the skips are Arc Tagger / embedder files not
  in this checkout), plus the ear, ABI 2, bindings and room tests on the v2 folder: 58 passed; frontend 314 / 314;
  desktop 88 / 88.
- `fuzz:libarc` (ASan + UBSan debug build, the fuzzer now calling `arc_nft2_tap`): 13 cases / 235 API calls / 400 s on
  the shipped model and the same on v2: clean.
- `gen_bindings.py --check --lib desktop/build/libarc/libarc.dylib`: ABI 2 (matches arc.h).
- Golden on the shipped model: unchanged path (no room section, no tap call): p50 1055 / 1091 ms in two rounds under
  load 12-15, within the 1519 ms budget; WER 1.6 %, names 23/23, linked 23/23, numbers 11/12.
- On-device learning is untouched: its inputs (`playback_leak`, `eot`, `speech_s`, `max_pause_s`) are unchanged and
  `room` is not read.

