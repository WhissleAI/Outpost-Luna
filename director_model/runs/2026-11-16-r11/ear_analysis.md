# Round 11: the real ear on the Mac voice bank (ear analysis)

Ear: Arc Transcriber Space (nft2, the installed app's downloaded model) through libarc, the same `model_server/app/arc_ear.EarStream` path as `real_ear.py decode` (partials every 3 s), with each turn's screen names list (`names_list.screen_names`, what the app sends) as the ear's names list. **All audio is synthetic** (macOS `say` voices pitched / sped toward a child, a laptop-mic band, room reverb, one noise bed per turn); treat these as a stress test of the ear on TTS-like speech, not as kid data.

Clips: 5660 kid turns in Mac voices (train 4977, val 302, held-out voices 381), 318 echo-bank clips (our own lines / crew clips alone), 2446 round-9 Steer TTS kid turns (comparison).

WER: word edits / reference words after lower-casing, removing punctuation, number words -> digits and `%` -> percent on both sides (so ITN form differences do not count as errors here; they are measured separately below).

## 1. WER and empty decodes

### By voice group (Mac groups: natural = the system voices, eloquence = Eddy/Flo/Grandma/... UK+US, novelty = Albert/Bahh/Boing/..., sung = Bells/Cellos/Organ/Good News/Bad News)

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| eloquence | 3010 | 48.5 % | 18.3 % | 9.5 % |
| natural | 2650 | 30.3 % | 39.4 % | 8.4 % |
| steer (r9, test) | 1242 | 11.5 % | 71.5 % | 3.9 % |
| steer (r9, train) | 902 | 10.1 % | 71.3 % | 2.9 % |
| steer (r9, val) | 302 | 9.8 % | 71.9 % | 2.3 % |

### Mac-voice kid turns by noise bed

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| babble | 1096 | 40.2 % | 26.2 % | 9.9 % |
| os_echo | 913 | 40.3 % | 29.4 % | 10.8 % |
| none | 893 | 33.3 % | 31.8 % | 15.6 % |
| room | 776 | 31.9 % | 35.6 % | 1.8 % |
| tv | 705 | 49.3 % | 21.3 % | 8.5 % |
| crew_echo | 698 | 50.8 % | 23.1 % | 9.5 % |
| music | 579 | 37.1 % | 29.2 % | 4.1 % |

### By voice (>= 10 clips)

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| Karen | 368 | 29.9 % | 41.0 % | 5.7 % |
| Moira | 351 | 16.8 % | 52.4 % | 4.0 % |
| Reed (English (US)) | 346 | 37.5 % | 24.6 % | 6.9 % |
| Flo (English (UK)) | 343 | 52.1 % | 16.6 % | 6.4 % |
| Rishi | 342 | 24.1 % | 45.6 % | 4.4 % |
| Daniel | 336 | 26.2 % | 41.4 % | 10.4 % |
| Reed (English (UK)) | 335 | 52.0 % | 16.1 % | 9.3 % |
| Tessa | 334 | 20.6 % | 45.8 % | 6.6 % |
| Shelley (English (US)) | 333 | 48.6 % | 17.1 % | 11.4 % |
| Samantha | 325 | 22.0 % | 44.9 % | 6.8 % |
| Shelley (English (UK)) | 320 | 56.2 % | 15.6 % | 10.6 % |
| Flo (English (US)) | 318 | 42.5 % | 22.6 % | 6.3 % |
| Grandpa (English (UK)) | 313 | 51.3 % | 13.1 % | 11.8 % |
| Ralph | 308 | 59.7 % | 12.3 % | 19.8 % |
| Grandpa (English (US)) | 305 | 44.5 % | 20.7 % | 7.2 % |
| Fred | 88 | 58.7 % | 20.5 % | 17.0 % |
| Aman (English (India)) | 76 | 43.4 % | 42.1 % | 7.9 % |
| Grandma (English (US)) | 73 | 38.9 % | 23.3 % | 13.7 % |
| Grandma (English (UK)) | 65 | 59.0 % | 15.4 % | 9.2 % |
| Tara (English (India)) | 54 | 42.7 % | 29.6 % | 7.4 % |
| Rocko (English (UK)) | 47 | 47.0 % | 17.0 % | 6.4 % |
| Sandy (English (US)) | 47 | 69.1 % | 10.6 % | 21.3 % |
| Eddy (English (UK)) | 45 | 45.2 % | 22.2 % | 17.8 % |
| Rocko (English (US)) | 43 | 41.1 % | 30.2 % | 18.6 % |
| Sandy (English (UK)) | 40 | 70.4 % | 5.0 % | 25.0 % |
| Eddy (English (US)) | 37 | 40.3 % | 21.6 % | 10.8 % |
| Junior | 35 | 49.0 % | 17.1 % | 14.3 % |
| Kathy | 33 | 65.9 % | 12.1 % | 9.1 % |

### By pitch shift

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| resample x1.1 | 1182 | 40.3 % | 29.0 % | 7.6 % |
| no shift | 1145 | 38.6 % | 30.0 % | 10.2 % |
| sox pitch +400 c | 803 | 43.1 % | 25.7 % | 9.3 % |
| sox pitch +300 c | 800 | 40.3 % | 26.9 % | 10.6 % |
| sox pitch +200 c | 776 | 39.7 % | 28.4 % | 9.4 % |
| resample x1.2 | 476 | 40.6 % | 27.7 % | 7.8 % |
| sox pitch +100 c | 425 | 36.6 % | 29.2 % | 6.8 % |
| resample x1.0 | 53 | 45.9 % | 22.6 % | 7.5 % |

### By mic chain

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| laptop mic | 2408 | 37.0 % | 31.8 % | 7.8 % |
| full band | 1578 | 37.9 % | 31.4 % | 6.3 % |
| laptop mic + reverb | 992 | 46.3 % | 20.3 % | 12.7 % |
| full band + reverb | 682 | 46.9 % | 19.4 % | 14.1 % |

### By SNR (babble / TV / music)

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| babble SNR 8-14 dB | 448 | 40.5 % | 23.4 % | 9.8 % |
| babble SNR >= 14 dB | 425 | 32.4 % | 34.1 % | 4.7 % |
| tv SNR 8-14 dB | 374 | 52.6 % | 19.3 % | 8.3 % |
| music SNR >= 14 dB | 321 | 35.1 % | 29.6 % | 2.5 % |
| music SNR 8-14 dB | 258 | 39.5 % | 28.7 % | 6.2 % |
| tv SNR >= 14 dB | 230 | 40.4 % | 27.4 % | 8.3 % |
| babble SNR < 8 dB | 223 | 54.3 % | 16.6 % | 19.7 % |
| tv SNR < 8 dB | 101 | 55.7 % | 14.9 % | 9.9 % |

**The harsh chain (stress set, 653 clips, not trained on):** the first decodes of this round used a harder chain (rate up to 230 wpm, pitch up to +700 cents, reverb RT60 to 0.7 s with a weak direct path, SNR down to 3 dB). Same voices and texts; it is kept as a stress set:

### Harsh chain, by voice group

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| eloquence | 340 | 61.9 % | 15.9 % | 18.2 % |
| natural | 237 | 61.1 % | 18.6 % | 15.6 % |
| novelty | 76 | 88.9 % | 2.6 % | 67.1 % |

### Harsh chain, natural + eloquence voices, by reverb and speaking rate

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| no reverb, rate < 200 | 199 | 54.2 % | 17.6 % | 13.6 % |
| reverb, rate < 200 | 144 | 68.9 % | 16.0 % | 18.8 % |
| no reverb, rate >= 200 | 144 | 55.0 % | 23.6 % | 15.3 % |
| reverb, rate >= 200 | 90 | 79.4 % | 6.7 % | 25.6 % |

**Novelty and sung voices (stress set, 675 clips, removed from training and from test_voice_heldout):** not plausible kid speech; their decodes were re-rendered in the other voices of the same split and these are reported only:

### Novelty / sung voices (moderate chain), by group

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| novelty | 433 | 74.2 % | 8.5 % | 36.0 % |
| sung | 242 | 84.1 % | 3.3 % | 37.2 % |

### Novelty / sung voices, by voice (turns without an OS-voice echo bed: those renders recorded the echo's voice in place of the kid's)

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| Bahh | 55 | 90.5 % | 1.8 % | 41.8 % |
| Boing | 45 | 65.6 % | 15.6 % | 31.1 % |
| Cellos | 45 | 85.0 % | 6.7 % | 22.2 % |
| Bad News | 45 | 79.9 % | 2.2 % | 20.0 % |
| Good News | 44 | 77.2 % | 2.3 % | 27.3 % |
| Albert | 43 | 85.3 % | 2.3 % | 41.9 % |
| Zarvox | 43 | 51.1 % | 16.3 % | 4.7 % |
| Superstar | 42 | 44.7 % | 16.7 % | 9.5 % |
| Whisper | 41 | 72.0 % | 12.2 % | 22.0 % |
| Bells | 39 | 99.1 % | 0.0 % | 84.6 % |
| Wobble | 33 | 84.3 % | 0.0 % | 42.4 % |
| Organ | 30 | 83.0 % | 3.3 % | 33.3 % |
| Bubbles | 28 | 94.8 % | 0.0 % | 64.3 % |
| Jester | 23 | 100.9 % | 0.0 % | 87.0 % |
| Trinoids | 12 | 37.5 % | 25.0 % | 8.3 % |

## 2. Lunar names: words and the ear's linker (`names` on the final words)

Per screen (the screen's names list was the ear's list); a turn counts once per list name it says.

| screen | name mentions | words right | linked (right) | abstain | linked (WRONG entity) | not_in_list | no name returned |
|---|---|---|---|---|---|---|---|
| library | 521 | 61.4 % | 49.1 % | 6.5 % | 4.8 % | 7.9 % | 31.7 % |
| cabin | 255 | 63.9 % | 49.8 % | 2.0 % | 12.2 % | 3.9 % | 32.2 % |
| lesson | 162 | 58.6 % | 51.9 % | 0.6 % | 2.5 % | 5.6 % | 39.5 % |
| map | 59 | 54.2 % | 49.2 % | 3.4 % | 3.4 % | 6.8 % | 37.3 % |
| **all** | 997 | 61.2 % | 49.7 % | 4.2 % | 6.2 % | 6.4 % | 33.4 % |

Most misheard names (>= 4 mentions; words right, linked right; the top mishearings):

| name | mentions | words right | linked right | heard as (count) |
|---|---|---|---|---|
| Tsiolkovskiy | 27 | 0.0 % | 0.0 % | "siakowski" (2); "slskovsky" (2); "syalkovski" (2); "(nothing)" (2) |
| Byrgius A | 13 | 15.4 % | 15.4 % | "(nothing)" (1); "by gsr" (1); "the name act for flee" (1); "beauty s" (1) |
| Malapert Massif | 12 | 16.7 % | 16.7 % | "(nothing)" (4); "vavilov" (1); "is mare" (1); "magic" (1) |
| Sea of Rains | 20 | 20.0 % | 20.0 % | "sea of rain" (6); "(nothing)" (1); "c orion" (1); "i would see rings guy" (1) |
| Ohm | 33 | 24.2 % | 24.2 % | "(nothing)" (8); "the greenhouse" (1); "them" (1); "by zone" (1) |
| Like 5 kilos | 4 | 25.0 % | 25.0 % | "like size kilos" (1); "i have 5 kilos" (1); "like 5" (1) |
| Mare Humorum | 12 | 25.0 % | 25.0 % | "emma snare him" (1); "very innumerable" (1); "their ingram" (1); "flight air sea of rains" (1) |
| CAPCOM | 4 | 25.0 % | 25.0 % | "(nothing)" (1); "just after me" (1); "i was cabeus" (1) |
| de Gerlache Crater Rim | 16 | 31.2 % | 12.5 % | "the jelly" (3); "the dew artemis" (1); "olis jelly crisi" (1); "that extold the glover" (1) |
| Sea of Tranquility | 28 | 32.1 % | 32.1 % | "z of tranquility" (3); "c of tranquility" (2); "(nothing)" (2); "alta tranquility" (1) |
| Hertzsprung | 12 | 33.3 % | 25.0 % | "birth" (1); "above the lane touch green light" (1); "eagleski" (1); "our deepest earthspring" (1) |
| Sea of Crises | 25 | 40.0 % | 24.0 % | "c of crisi" (3); "sea" (1); "a crisium" (1); "the acroces" (1) |
| Aristarchus Plateau | 22 | 40.9 % | 40.9 % | "aristarchus crater oh name" (1); "olly not just not" (1); "sls plateau" (1); "on their starter school" (1) |
| Yes | 14 | 42.9 % | 35.7 % | "(nothing)" (5); "it's" (1); "it's not a" (1); "dear dolly" (1) |
| Pythagoras | 15 | 46.7 % | 33.3 % | "shame" (1); "5 apollo" (1); "descent stage" (1); "places tygos" (1) |
| Tycho | 26 | 50.0 % | 42.3 % | "name was a teacher" (1); "like ij" (1); "that's pitch" (1); "we're in title" (1) |
| Jim Lovell | 4 | 50.0 % | 25.0 % | "(nothing)" (1); "see 2" (1) |
| South Pole | 23 | 56.5 % | 47.8 % | "shackleton" (6); "(nothing)" (2); "south" (1); "so all" (1) |
| Glushko | 24 | 58.3 % | 41.7 % | "(nothing)" (2); "lunar" (2); "lacho" (1); "bloodstock" (1) |
| Houston | 13 | 61.5 % | 76.9 % | "houston" (2); "command" (1); "racing control" (1); "(nothing)" (1) |

Examples:

- Tsiolkovskiy: "where is tsiolkovskiy" -> "Where is siakowski"
- Tsiolkovskiy: "guide how far away is tsiolkovskiy" -> "guy how far away sir kochi"
- Byrgius A: "fly to byrgius a" -> ""
- Byrgius A: "show me byrgius a" -> "Show me by gsr"
- Malapert Massif: "um malapert massif" -> ""
- Malapert Massif: "i think malapert massif" -> "I think vavilov"
- Sea of Rains: "fly to sea of rains" -> "light a sea of rain"
- Sea of Rains: "uh what is sea of rains" -> ""
- Ohm: "what did the crew say about ohm" -> "What did the crew say about the greenhouse"
- Ohm: "orientale basin and then ohm" -> "Orientale Basin"
- Like 5 kilos: "i think like 5 kilos" -> "I think like size kilos"
- Like 5 kilos: "like 5 kilos i guess" -> "i have 5 kilos, I guess."
- Mare Humorum: "uh what is mare humorum" -> "emma snare him"
- Mare Humorum: "fun fact about mare humorum please" -> "fun fact very innumerable please"
- CAPCOM: "so what does capcom mean" -> ""
- CAPCOM: "okay but what does capcom mean" -> "Okay, but just after me"

## 3. Numbers and percents (ITN)

Turns with a number or percent in the reference: 1422. Numbers exactly right (as digits after normalising number words): 56.6 %; a reference number missing from the decode: 39.7 %.

Written form of percents (386 turns): N% 87.0 %, words 5.4 %, percent lost 7.5 %. Turns where a number stayed a word in the written form: 184.

Examples of number errors:

- "so what science did ranger 9 impact site do" -> "Then was science at tycho"
- "my phone number is 555 33" -> "My phone number is five hundred and fifty five thirty three"
- "my phone number is 555 179" -> "My phone number is five one hundred fifty five one hundred and seventy nine"
- "put 25 percent on rover" -> "clipped lountifi in percent time roll over"
- "hey what was surveyor 6 for" -> "Say apollo 11"
- "so when did apollo 15 lunar roving vehicle land" -> "So, when did Apollo 14 Lunar module Vehicle end"
- "veggies to 10" -> "veggies two ten"
- "my phone number is 555 65" -> "My phone number is five hundred fifty five sixty five"

## 4. One- and two-word turns

### By reference length

| group | clips | WER | exact | empty |
|---|---|---|---|---|
| 3+ words | 4853 | 38.5 % | 27.4 % | 5.4 % |
| 2 words | 538 | 68.9 % | 35.1 % | 21.2 % |
| 1 words | 269 | 103.7 % | 27.9 % | 49.1 % |

Most frequent short-turn errors: "hmm" -> "(empty)" (28); "help" -> "(empty)" (25); "this one" -> "(empty)" (19); "it's" -> "(empty)" (10); "alright alright" -> "(empty)" (9); "oh okay" -> "okay" (9); "yeah" -> "(empty)" (9); "yay" -> "(empty)" (7); "yeah okay" -> "okay" (7); "shh" -> "(empty)" (6); "oh cool" -> "oh" (6); "wait what" -> "(empty)" (6)

## 5. Echo leakage: our own voice and crew clips alone through speaker -> mic

All: 318 clips, words out on 52.2 %, 2.6 words per clip.

| voice | clips | produced words | words / clip |
|---|---|---|---|
| Reed (English (US)) | 6 | 100.0 % | 6.8 |
| Grandma (English (UK)) | 6 | 100.0 % | 5.0 |
| Aman (English (India)) | 6 | 100.0 % | 4.0 |
| Rishi (app OS voice) | 6 | 83.3 % | 7.3 |
| Fred | 6 | 83.3 % | 3.7 |
| Tara (English (India)) | 6 | 83.3 % | 3.5 |
| Tessa (app OS voice) | 6 | 83.3 % | 5.7 |
| Zarvox | 6 | 83.3 % | 4.3 |
| Grandma (English (US)) | 6 | 83.3 % | 5.2 |
| Rocko (English (US)) | 6 | 83.3 % | 2.0 |
| Moira (app OS voice) | 6 | 66.7 % | 3.0 |
| Eddy (English (UK)) | 6 | 66.7 % | 2.7 |
| Trinoids | 6 | 66.7 % | 1.8 |
| Shelley (English (UK)) | 6 | 66.7 % | 2.3 |
| Kathy | 6 | 66.7 % | 3.3 |
| Superstar | 6 | 66.7 % | 3.2 |
| Cellos | 6 | 66.7 % | 2.7 |
| Junior | 6 | 66.7 % | 4.0 |
| Shelley (English (US)) | 6 | 66.7 % | 4.2 |
| crew clip | 60 | 55.0 % | 3.7 |
| Eddy (English (US)) | 6 | 50.0 % | 4.0 |
| Reed (English (UK)) | 6 | 50.0 % | 2.3 |
| Flo (English (US)) | 6 | 50.0 % | 2.7 |
| Sandy (English (UK)) | 6 | 50.0 % | 1.2 |
| Karen (app OS voice) | 6 | 50.0 % | 1.8 |
| Rocko (English (UK)) | 6 | 50.0 % | 1.8 |
| Grandpa (English (US)) | 6 | 50.0 % | 1.7 |
| Flo (English (UK)) | 6 | 50.0 % | 2.3 |
| Sandy (English (US)) | 6 | 50.0 % | 1.8 |
| Daniel (app OS voice) | 6 | 50.0 % | 1.3 |
| Grandpa (English (UK)) | 6 | 33.3 % | 1.7 |
| Whisper | 6 | 33.3 % | 0.3 |
| Samantha (app OS voice) | 6 | 33.3 % | 1.3 |
| Wobble | 6 | 33.3 % | 1.3 |
| Good News | 6 | 33.3 % | 1.2 |
| Ralph | 6 | 16.7 % | 0.5 |
| Organ | 6 | 16.7 % | 0.2 |
| Bad News | 6 | 16.7 % | 0.5 |
| Albert | 6 | 16.7 % | 0.2 |
| Jester | 6 | 0.0 % | 0.0 |
| Boing | 6 | 0.0 % | 0.0 |
| Bells | 6 | 0.0 % | 0.0 |
| Bahh | 6 | 0.0 % | 0.0 |
| Bubbles | 6 | 0.0 % | 0.0 |

Kid turns with an echo under them: share with >= 2 inserted words (the echo leaking into the kid's turn):

- babble: 4.6 % of 1096
- crew_echo: 15.9 % of 698
- music: 2.8 % of 579
- none: 2.1 % of 893
- os_echo: 7.8 % of 913
- room: 3.6 % of 776
- tv: 8.7 % of 705

## 6. device_directed: room talk vs directed

Kid turns with a gold act: directed 1545, not directed (gold ignore: room talk, chatter, echo-like) 409 (of which room talk / chatter 407). `dd` = the app's remapped head (max over the clip's segments; a wordless segment has none).

| comparison | AUC | dd >= 0.5: directed / other |
|---|---|---|
| directed vs gold-ignore kid turns | 0.698 | 93.2 % / 78.5 % |
| directed vs room talk / chatter | 0.697 | 93.2 % / 78.6 % |
| directed vs echo-bank clips with words | 0.802 | 93.2 % / 66.7 % |

## 7. End of turn

5660 kid clips (speech end known from the render). Turn closes per clip: more than one (the turn was cut into pieces) on 2.6 %; the first close before the speech ended (a premature cut-off) on 0.2 %.
Close latency after the speech ends (audio time; the end-silence wait is in it): p50 0.49 s, p90 2.08 s. Final decode time per close: p50 480 ms, p90 929 ms (under the machine's load).

## 8. Compound commands and commands kept

Turns whose gold act is a command and whose reference parses (mission NLU): the decode parses to the same command types / loses a command.

| kind | turns | same commands | a command lost |
|---|---|---|---|
| single | 633 | 53.9 % | 45.3 % |
| compound | 280 | 47.5 % | 47.9 % |

## 9. Director features the ear leaves at 0

test_voice_heldout, 489 turn-end steps (every turn a real-ear decode): share of steps where the feature is non-zero.

| feature | non-zero |
|---|---|
| ear_avail | 95.3 % |
| ear_conf | 0.0 % |
| ear_alts | 0.0 % |
| ear_alt_hot | 0.0 % |
| ear_rescored | 0.0 % |
| ear_tier_step | 0.0 % |
| ear_tier_screen | 0.0 % |
| dd_avail | 85.1 % |
| dd | 84.7 % |
| cc_avail | 85.1 % |
| cc | 85.1 % |
| tag_avail | 52.1 % |
| hot_avail | 100.0 % |
| hot_step | 11.7 % |
| hot_screen | 32.3 % |
| hot_step_sa | 9.6 % |
| hot_screen_sa | 29.7 % |
| emo_neutral | 92.4 % |
| emo_happy | 1.0 % |
| emo_excited | 0.6 % |
| emo_frustrated | 5.5 % |
| emo_confused | 0.0 % |
| emo_scared | 0.4 % |
| emo_bored | 0.0 % |

**`cc` is a train / serve skew:** the ear sent `command_complete` on 0 of 6648 arc messages (it has no such head), so in the app `cc_avail` = `cc` = 0; but `gen_sessions.run` sends its own `command_complete` = U(0.5, 0.95) with every turn, real-ear turns included, so every train and test set has `cc` non-zero on ~85 % of turn ends. `ear_avail` is 1 in both (the final words carry an empty `alts` list), but every value behind it (conf, alts, rescored, tiers) is empty. `emo_*` comes from the generator's emotion items, not the ear (it sends none).

Not features at all (the ear sends them, the Director never reads them): `names` link state / link p / entity kind, `audio_events`, `spoken`, `tags`, `directed_head` (raw).
