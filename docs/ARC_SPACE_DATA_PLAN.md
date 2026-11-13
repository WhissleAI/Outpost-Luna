# Arc for Space: data, vocabulary and tag plan for Arc Transcriber + Arc Tagger

2026-11-13 · Whissle · For the Arc modelling team (Arc Transcriber, Arc Tagger). Share as-is; every number in here was
measured on our data or read from the source linked next to it.

> **v3: Mission Trainer + multi-stream → see [`ARC_MULTISTREAM_PLAN.md`](ARC_MULTISTREAM_PLAN.md).** Ask the Moon is
> now also a NASA Space Apps 2026 *Junior Astronaut Mission Trainer* (kids 7–12 command a lunar outpost by voice while
> real telemetry flows; contract in [`MISSION_CONTRACT.md`](MISSION_CONTRACT.md)). That plan makes Arc read telemetry,
> events, game state, context lists and dialogue state next to 1..N audio streams, with masks for missing streams. It
> builds on this doc. Changes here: mission command intents in §6, telemetry datasets in §3.3.

**In one paragraph.** We want Arc Transcriber and Arc Tagger to run fully on-device and be great at space speech. That
means hearing every named place on the Moon, every piece of hardware and every crew member, and marking the meaning as
it streams: where, who, what happened, what they want, how it feels, when to answer. This doc covers:
- the data to download, with exact commands;
- the vocabulary to make the ASR hear (all 9,087 IAU lunar names, in tiers);
- the tags and intents the product needs, and their targets;
- what's broken today and how to fix it;
- the synthetic data to generate;
- how to fine-tune with name lists as context, so any list works at runtime.

The product using it is **Moonbase Cadet** (formerly Ask the Moon) (this repo), a voice-first 3D Moon for kids built for NASA Space Apps 2026 on
the challenge *Abandoned but not Forgotten: Storytelling about NASA's Discarded Equipment on the Moon and Mars*.

Contents:
1. Why: smart transcription, on-device
2. Baseline: measured today
3. What to download (with commands)
4. Lunar vocabulary for the ASR (custom vocabulary)
5. Tag taxonomy + tag capability targets
6. App intents and slots (what the app must understand)
7. What to fix: known issues with evidence
8. Building the real-audio dataset
9. Synthetic data
10. Fine-tuning with list context
11. Training order and evaluation
12. Running it locally
13. Asks and open questions
14. Appendix: file formats and scripts

---

## 1. Why: smart transcription, fully on-device

A plain transcript is words. A smart one is words plus the meaning we mark on them, word by word, while the person is
still talking:

| Question | What the model marks | Example |
| --- | --- | --- |
| *Where* | Lunar features, landing sites, hardware, linked to a point on the Moon even when misspoken | "Oriental" → Mare Orientale (19.9°S 94.7°W) |
| *Who* | Speaker, role (crew, CAPCOM, Flight), name when known | "Christina saw this", not "Astronaut 2" |
| *What happened* | Mission events in speech; audio events | "go for TLI", liftoff, loss of signal, quindar tone, laughter |
| *What they mean* | Description vs request vs question; colors, geology words, directions, spatial relations | "northwest of Glushko, same latitude as Ohm" |
| *How it feels* | Awe, excitement, tension, a kid's confusion | Earthrise: "Oh my gosh! It's amazing!" |
| *When to act* | Request complete, turn yielded, interruption, addressed to the app or not | Answer 200 ms after the kid stops, not 700 |

**Why local.**
- **Comms:** deep-space links run with seconds to minutes of delay and blackouts; Artemis II lost signal behind the Moon.
- **Privacy:** kids' audio must not leave the device.
- **One host, many apps:** a single local model host already serves Ask the Moon and Head Start, which only works if
  the models are small.
- **Today's sizes:** Arc Tagger 26 MB at ~0.1 ms per word; Arc v1.1 Mini ~1 GB RAM.

---

## 2. Baseline: what Arc does on Artemis II audio today

Measured 2026-11-13 on all 60 Artemis II lunar-flyby recordings: 60,583 words, Deepgram nova-3 transcripts, Arc Tagger
v0.3 native int8, domain `news`. Reproduce with `backend/pipeline/probe_tagger.py` and `make index`.

| What we measured | Result | What it means |
| --- | --- | --- |
| Lunar-name mentions found as entity spans and linked to a gazetteer place | 820 | Mention detection is good and survives ASR misspellings ("babilov", "Oriental") |
| Entity type on those lunar names | person 616 (75%) · place 116 · organization 88 | No lunar type; needs `entity.mention.lunar_feature` |
| Lunar names missed (caught by our gazetteer fallback) | 97 (~10%): Aristarchus 23, Orientale 19, Reiner Gamma 18, Integrity 15 | Recall gap on multi-word names and names that are also common words |
| Unlinked entity spans | 1,081; top: Earth 96, Jeremy 65, albedo 64, Grimaldi 39, Kepler 21, Byrgius A ~31 | Gazetteer gaps + jargon and directions typed as names |
| Direction words typed as entities | ~100 (northwest 25, south 24, north 12, …) | Need `geo.direction` and relation spans |
| Crew first names | typed person, correctly | Useful for speaker naming |
| Number spans | 645 | Type `measure` vs `count` is mixed ("20 kilometers" → count) |
| Speed | 0.08–0.11 ms/word batch; a 344 s clip in ~120 ms | Fine for on-device |
| Arc v1.1 Mini via our host | RTF 0.03–0.06 on files; ~1 streamed live under load; metadata 1.2–4 s behind the words | Too slow and late for live endpointing |
| Arc v1.1 Mini emotion | `affect.emotion.*` never emitted, any domain | Emotion is off in the app |
| Deepgram diarization | 1–2 speakers found on clips with 3–4 crew | Speakers undercounted |

---

## 3. What to download

All NASA media: free to use, no implied NASA endorsement
([NASA media guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/)).

### 3.1 Already verified and in use

| Dataset | What it gives | Size | Download |
| --- | --- | --- | --- |
| [IAU Gazetteer of Planetary Nomenclature, Moon](https://planetarynames.wr.usgs.gov/GIS_Downloads) (USGS) | 9,087 named lunar features: name, type, diameter, center lat/lon, extent, origin of the name and its language/ethnicity, approval date, link | 24 MB zip (shapefile; `.dbf` holds the attributes) | `curl -LO https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/MOON_nomenclature_center_pts.zip && unzip MOON_nomenclature_center_pts.zip` |
| [NASA Artemis Audio Library](https://www.nasa.gov/artemisaudio/) | ~113 clips (MP3 + WAV): 59 Artemis II lunar-flyby crew observations (13 shorter + 46 extended), launch/in-flight/splashdown loops, Apollo astronaut messages to the crew (Charlie Duke, Jim Lovell), crew interviews, 24 briefing/podcast WAVs (96 kHz/24-bit; note `3-hour-lunar-surface-observation.wav` is a 26 s clip, not 3 hours) | 60 flyby MP3s ≈ 250 MB; WAVs 0.3–110 MB each | `cd backend && uv run python -m pipeline.scrape_manifest && bash pipeline/fetch_media.sh` (manifest-driven; send a browser User-Agent) |
| Shared Drive folder "original" (collaborator) | 50 files, all also on the NASA page above (the non-flyby half) | ~700 MB | Fetch from NASA directly |
| [NASA SVS CGI Moon Kit](https://svs.gsfc.nasa.gov/4720/) | LRO LROC color maps (1k–27k), LOLA elevation | 2–100s of MB | `curl -LO https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_poles_4k.tif` |

### 3.2 Training sources (verified 2026-11-13)

Full inventory, with per-dataset notes, the URLs opened and the gaps: [`NASA_DATASETS.md`](NASA_DATASETS.md). Each source
was checked by opening its page. "PD" means a US-government work.

| Source | What it gives | Size | Labels | Licence | How to get it | Use it for |
| --- | --- | --- | --- | --- | --- | --- |
| **Apollo in Real Time** (A11/A13/A17) | Mission audio synced to GET + utterance CSVs | A11: 11,000 h MOCR + 240 h space-to-ground; 14,895 utterances | GET, speaker callsign, text, milestones | Source audio PD; repo has **no licence file** (ask) | `curl -L https://raw.githubusercontent.com/bfeist/apolloinrealtime.org/main/mission-data/11/MISSION_DATA/A11_merged_utterances.csv` (`GET\|type\|speaker\|text`) | **Best alignment source**: words, speakers, roles, events |
| **Apollo audio, Internet Archive** | Raw 30-track Apollo 11 mission control (1,428 items, 6.5 TB, ~11.9k h); 484 Apollo 13 items; `apolloaudiocollection` reels for Apollo 1–17 | ~12k h + per-mission TBs | None (raw); channel number = console loop | PD | `pip install internetarchive; ia download Apollo17 --glob="*.mp3"` | Self-supervised pretraining, radio robustness, speaker/role via channel |
| **Fearless Steps** (UT Dallas, FS-1..FS-4) | Apollo 11 (+A13, A8) mission control, 0–20 dB SNR | 100 h challenge set (~36 h speech) + 10 h A8 + 5 h A13 | Speech activity, diarization, speaker ID, ASR; FS-3 summaries/hotspots; FS-4 speaker verification, topics | NASA media guidelines | **Request access**: email FearlessSteps@utdallas.edu (registration closed) | Gold speakers + words on noisy radio |
| **Apollo Flight Journal + Lunar Surface Journal** (apollojournals.org) | Corrected transcripts with commentary and audio clips, all crewed Apollo flights + EVAs | All missions | GET per utterance, speaker, role class (`cc`=CAPCOM, `onboard`, `pao`) | No licence statement found (credit; ask before redistributing commentary) | HTML scrape; anchors `<a name="HHHMMSS">` | Text for the tagger; alignment; roles |
| **NASA Artemis Audio Library** | 113 clips (13 + 46 flyby + 54 other) | ~1 GB | Title/description only | "No additional permission is required" | Scrape page → `wp-content/uploads/...mp3/wav` (in this repo) | Modern Orion comms, awe, lunar names |
| **NASA Images API, `media_type=audio`** | 79 "Houston We Have a Podcast" episodes + KSC launch multitrack feeds (incl. Artemis II) + ISS calls | 136 items (2025–26 only; nothing from 1960–75) | Podcast `description` = **full transcript** (median ~38k chars) | PD | `GET https://images-api.nasa.gov/search?media_type=audio&page_size=100` → `/asset/{nasa_id}` | Audio + transcript pairs (no timestamps): long-form ASR, host/guest speakers |
| **JPL Horizons** Artemis II (−1024), Artemis I (−1023) | Ephemeris + major events with MET/UTC (TLI, OTC, 8,282 km flyby, splashdown) | Text | Event times | PD | `curl "https://ssd.jpl.nasa.gov/api/horizons.api?format=text&COMMAND='-1024'&OBJ_DATA=YES&MAKE_EPHEM=NO"` | `event.space.*` aligned to Artemis audio |
| **Artemis II ephemeris (AROW)** | CCSDS OEM state vectors, 2–10 Apr 2026 | 1.5 MB | Time-tagged position | NASA | `https://www.nasa.gov/wp-content/uploads/2026/03/all-artemis-ii-oem-files.zip` | Mission phase per moment |
| **DONKI** space weather | CME, storms, SEP events | JSON | Event type/time | PD | `https://api.nasa.gov/DONKI/CME?startDate=…&endDate=…&api_key=KEY` (FLR endpoint 404 today) | Synthetic event call-outs |
| **Lunar hardware coordinates** | LROC 2016 tables (Apollo LMs, LRVs, Surveyors, Rangers, S-IVBs, GRAIL, LADEE) + NSSDCA + NASA 2012 catalogue | 3 PDFs/pages | Coordinates (±0.3–19 m) | NASA/ASU | See `NASA_DATASETS.md` | Hardware gazetteer (Tier A names) |
| **ARISS school contacts** | Students' question lists (text, several languages) for each ISS contact | Ongoing | Questions, school, astronaut | Text public; **recordings are school-owned, not PD** | Scrape `ariss.org/upcoming-educational-contacts.html` | **Real kid question wording** for the synthetic templates |
| **JSC Oral History Project** | ~755 PDF interview transcripts (flight controllers, astronauts) | Text only, no audio | Speaker turns | PD | PDFs from the JSC oral-history index | Vocabulary and roles for the tagger |
| **Perseverance SuperCam mic** (PDS) | Mars microphone audio (wind, laser zaps, Ingenuity) | PDS bundle | PDS4 labels | PD | `wget -r -np https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/` | Non-speech sound events, noise augmentation |
| **LOLA DEM 118 m** (USGS) | Global elevation GeoTIFF | Large | — | PD | `https://planetarymaps.usgs.gov/mosaic/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif` | App terrain, horizon |

### 3.3 Telemetry, event and timeline sources (v3, verified 2026-11-13)

For the multi-stream work. Full table, pairing and licences: [`ARC_MULTISTREAM_PLAN.md`](ARC_MULTISTREAM_PLAN.md) §5.

| Source | What it gives | How to get it | Use it for |
| --- | --- | --- | --- |
| **Apollo in Real Time milestones + A13 Flight Director loop** | `A11_TOC.csv` 274 / `A13_TOC.csv` 380 milestones (`GET\|level\|title`); `flight-director-loop.txt` 4,267 FD-loop turns, GET 55:46–62:06 (the Apollo 13 accident) | `curl -LO https://raw.githubusercontent.com/bfeist/apolloinrealtime.org/main/mission-data/13/MISSION_DATA/flight-director-loop.txt` (repo has no licence file) | Event stream for Apollo replays; urgency vs alarm on real speech |
| **ISS live telemetry** (Lightstreamer, adapter `ISSLIVE`) | Live public ISS channels (`TimeStamp`, `Value`); ISS Mimic subscribes to 337 ids, meanings in `Telemetry/ISS_Public_Telemetry.xlsx` | `LightstreamerClient("https://push.lightstreamer.com","ISSLIVE")` as in `github.com/ISS-Mimic/Mimic` `Pi/iss_telemetry.py` (MIT). No archive found: record it | Real channel rates, gaps, staleness for the telemetry encoder |
| **OSDR Environmental Data App** | ISS cabin temperature, CO2, RH, radiation dose (GCR/SAA) per mission | `https://visualization.osdr.nasa.gov/eda/` (UI; bulk endpoint UNVERIFIED) | Realistic life-support and dose curves for the sim |
| **LRO CRaTER dose rates** | Daily lunar-orbit dose rates (L30, shadow-corrected) | `https://crater-products.sr.unh.edu/` → Dose/Dose Rates | Real lunar dose levels and storm spikes |
| **NOAA SWPC GOES proton flux** | 5-min ≥1/≥10/≥100 MeV flux, last 7 days | `curl https://services.swpc.noaa.gov/json/goes/primary/integral-protons-7-day.json` | Shape of storm onset in the dose-rate channel |
| **JPL Horizons from a lunar site** | Sun/Earth azimuth/elevation at the outpost (sunset/sunrise, comm windows) | `horizons.api` with `CENTER='coord@301'`, `SITE_COORD='0,-89.5,0'`, `QUANTITIES='4'` | `sun_elev_deg`, `earth_elev_deg` in the sim |
| **Mars 2020 MEDA / MOXIE, MSL REMS** (PDS) | Mars environment telemetry; MOXIE oxygen production | `https://atmos.nmsu.edu/PDS/data/PDS4/Mars2020/` (`meda_derived.tar.gz`, `moxie_bundle.tar.gz`); `.../mslrem_1001/` | Unseen telemetry channels to test channel generalisation |
| DONKI (already above) | GST/CME/SEP for storm events | real `api.nasa.gov` key needed (DEMO_KEY 429 today) | Storm events in the sim |

**What still has to be synthetic** (no real source exists):
- kids' speech about the Moon;
- labeled Artemis-era mission-control audio (multichannel, roles, diarization);
- emotion labels and app intents;
- event tags aligned to audio frames;
- Orion/ISS cabin acoustics;
- word-level timestamps for any of these sources (they come from forced alignment).

**Do first:**
- Email Fearless Steps for the labeled packages.
- Ask Ben Feist about licence terms for the Apollo in Real Time CSVs.
- Scrape ARISS question lists into the kid templates.

---

## 4. Lunar vocabulary for the ASR

Every named place on the Moon must be in the engine's vocabulary, along with every piece of hardware and every crew
name, with the ways people actually say them. The IAU list has 9,087 names. No runtime keyterm list holds that
(Deepgram's limit is 100 terms), so we use **tiers**. The model learns the whole vocabulary in training, and at runtime
gets a small, current list.

### 4.1 Tiers (counts from the IAU file above)

| Tier | What's in it | Count | Where it's used |
| --- | --- | --- | --- |
| **A: always on** | The 59 maria, oceanus, lacus, sinus and palus names; the 364 primary craters ≥ 100 km; the 6 landing-site *Statio* names; the 81 astronaut-named features (e.g. "North Ray", "Taurus Littrow Valley", "Shorty"); all Apollo / Luna / Chang'e / Surveyor landing sites; Artemis III candidate regions near the south pole; our ~35 hardware items + their nicknames ("Eagle", "Challenger", "LRV 2") | ~550 | Trained in with heavy weight; always in the decoder's prior; synthetic audio ×20 per name |
| **B: all primary names** | All 2,023 non-satellite IAU names (1,615 craters + rimae, montes, dorsa, valles, …); 494 of them are multi-word | 2,023 | Trained in; runtime list when the app is near them; synthetic audio ×5 per name |
| **C: satellite features** | The 7,064 lettered craters ("Copernicus A", "Byrgius A") | 7,064 | Text-level only (tagger, linker); spoken form = base name + letter; synthetic audio ×1 |
| **People and missions** | Artemis II crew (Reid Wiseman, Victor Glover, Christina Koch, Jeremy Hansen), Apollo crews, mission names (Apollo 11–17, Artemis I–III, Surveyor 1–7, Ranger, Luna, LCROSS, GRAIL, LADEE, Chang'e), vehicles (Orion, *Integrity*, SLS, LM, LRV) | ~250 | Tier A weight |
| **Kid descriptors** | "the giant bullseye" → Orientale, "the yellow part" → Aristarchus, "where Neil landed" → Statio Tranquillitatis | ~150, growing from logs | Linker aliases + synthetic kid queries (not ASR vocabulary) |
| **Glossary** | albedo, ejecta, regolith, terminator, limb, mare/maria, rille, rays, highlands, Earthshine, Earthset, … | ~60 | Tier A weight; explained by the app |

### 4.2 Pronunciations

The names come from **71 origin languages** (top: American 308, German 277, French 199, British 194, Italian 114, Greek
110, Soviet 109, Latin 74). Kids and astronauts say them differently.

**Build a lexicon:** for each name, produce:
- the canonical pronunciation (G2P in the origin language, then anglicized);
- 2–4 common English variants ("Aris-TAR-kus" / "Aris-TAR-cus", "Her-zprung" / "Hertz-sprung", "Gloosh-ko");
- 1–2 kid mispronunciations, LLM-generated and then filtered by a human for the Tier A names.

Store as `vocab/lunar_lexicon.jsonl`: `{name, tier, iau_id, lat, lon, origin_lang, prons:[...], spellings_seen:[...]}`.

**Seed `spellings_seen` from real ASR errors we've already logged:**
- "Oriental", "Orin Ta" → Orientale
- "babilov", "Vavilof" → Vavilov
- "Burgius alpha" → Byrgius A
- "Hertzprung" → Hertzsprung
- "Carol" → Carroll (crew-proposed name)
- "Ohm's" → Ohm

### 4.3 How the vocabulary is used at each layer

1. **Training:** every Tier A/B name appears in synthetic audio (section 9), and list-context training (section 10)
   teaches the model to use whatever list it's handed.
2. **Runtime keyterms (cloud ear, until the on-device ear replaces it):** ≤ 100 terms per stream. The app picks them:
   names in view on the globe, the current clip's names, Tier A essentials.
3. **Runtime list for Arc:** 10–30 candidate names (`names` / `context`), refreshed as the kid talks.
4. **After ASR:** the linker maps every tagger mention to the gazetteer (rapidfuzz + phonetic). Between thresholds, Arc
   scores candidates against the audio, and the app asks "Did you mean …?".

**Gaps in the app's own list today** (found in the crew audio): Grimaldi, Kepler, Pythagoras, Byrgius A, Mare Humorum and
the north pole are being added now.

---

## 5. Tag taxonomy and tag capability targets

*New* = not in the r8 ontology. *Calibrate* = exists but misfires on space audio. *Keep* = works.

### 5.1 Arc Tagger (text: words, spans, utterances)

| Tag | Status | Definition | Example |
| --- | --- | --- | --- |
| `entity.mention.lunar_feature` | New | Named place on the Moon (crater, mare, basin, mons, rima, plateau, swirl, pole, statio) | "down on **Vavilov**" |
| `entity.mention.spacecraft` | New | Named vehicle or hardware (Orion, *Integrity*, Eagle, LRV, Surveyor 3, SLS, ALSEP) | "our great spacecraft **Integrity**" |
| `entity.mention.mission` | New | Mission names and numbers | "**Apollo 16**", "**Artemis II**" |
| `entity.mention.crew_member` | Calibrate (person → crew) | Astronaut or controller, linked to the roster | "**Jeremy**, look at this" |
| `entity.mention.celestial` | New | Earth, Sun, stars, planets as objects in view | "**Earth** set behind the limb" |
| `geo.term` | New | Geology/optics vocabulary | **albedo**, **ejecta**, **regolith** |
| `geo.color` | New | Surface color words | "distinctly **yellow**" |
| `geo.direction` | New | Compass/relative directions | **northwest**, "**far side**" |
| `geo.relation` (span) | New | Place located by reference to others, with operator: `midpoint`, `direction_of`, `same_latitude`, `near`, `inside`, `between` | "**halfway between Orientale and Ohm**" |
| `geo.texture` | New | Surface texture words (for "Talk like an astronaut") | **hummocky**, **pillowing**, **blanketing** |
| `event.space.*` | New | Mission events said in speech: `go_no_go`, `liftoff`, `tli`, `burn`, `los`, `aos`, `landing`, `splashdown`, `eva_start/end` | "**go for TLI**" |
| `entity.number.measure` | Calibrate | Sizes, distances, altitudes with units; feeds the claim check | "**930 km** wide" |
| `entity.date` / year | Keep | Mission years ("in **1972**") | |
| `discourse.claim` | New | A factual claim that can be checked (kid or guide) | "the moon is **made of cheese**" |
| App intents (section 6) | New / extend | Kid requests | "show me the rovers" |
| `safety.pii.*`, `safety.child.*`, `safety.jailbreak.*` | Keep, with a fix (section 7) | Kid's own name, address, phone; prompt injection | "I live at 42 Oak Street" |

### 5.2 Arc Transcriber (audio: frames, utterances)

| Tag | Status | Definition | Why the app needs it |
| --- | --- | --- | --- |
| `speaker.id` + `speaker.role.{crew,capcom,flight,pao,controller,kid,adult}` | Calibrate | Who speaks; name when enrolled | Name the astronaut; separate the kid from a teacher |
| `channel.{air_to_ground,loop,studio,phone,device_mic}` | New | Radio vs studio vs room | Space audio is band-limited radio |
| `audio_event.quindar_tone` | New | NASA intro/outro tones | Turn boundary on radio |
| `audio_event.{static,dropout,los}` | New | Noise, packet loss, loss of signal | Don't transcribe noise; mark blackouts |
| `audio_event.{laughter,gasp,cheer,applause}` | Calibrate | Today: laughter p > 0.9 on most crew radio frames | Awe moments |
| `audio_event.app_playback` | New | The app's own audio coming back into the mic | Stop the open mic answering the crew clip (seen in testing) |
| `affect.awe`, `affect.{excited,calm,tense,confused,bored}` | New / calibrate | Tone; awe for the crew, confused/bored for kids | Rank moments; adapt pacing |
| `discourse.assistant.command_complete`, `device_directed` | Keep | When to answer; is it for the app | Endpointing |
| `bio_event.{breath,cough}` | Keep | | Suit/helmet audio |

### 5.3 Capability targets per tag family

These are the targets each family must hit for the app to rely on it. *Tier* = when it must be readable: T0 = as the word
arrives, T1 = ≤ 3 words later, T2 = at utterance end.

| Family | Read-out | Tier | Used for | Precision target | Recall target |
| --- | --- | --- | --- | --- | --- |
| Lunar feature / spacecraft / mission mentions | span | T0–T1 | Fly the globe as words arrive | ≥ 0.95 | ≥ 0.97 |
| Link to the right gazetteer entry | span → id | T1 | Correct place | ≥ 0.95 | — |
| `geo.term` | span | T1 | Explain hard words mid-clip | ≥ 0.9 | ≥ 0.9 |
| `geo.direction`, `geo.relation` | span | T2 | Missions, "find it like an astronaut" | ≥ 0.85 | ≥ 0.8 |
| `event.space.*` | span / event | T1 | Mission story mode | ≥ 0.9 | ≥ 0.85 |
| App intents (section 6) | utterance | T2 (running guess at T0) | What to do | ≥ 0.92 top-1 | — |
| `command_complete` | event | T0 | Answer early | premature ≤ 10 / 100 turns | — |
| PII (address, phone, email, own name) | span | T0 | Never send or store | ≥ 0.9 | ≥ 0.98 |
| Speaker role / name | per speaker | T2 | "Christina saw this" | ≥ 0.9 | — |
| Audio events (quindar, static, LOS, laughter) | event | T1 | Segment, awe | ≥ 0.8 | ≥ 0.7 |
| `affect.awe`, kid affect | utterance | T2 | Moment ranking, pacing | ≥ 0.75 | — |

---

## 6. App intents and slots

These are the requests Ask the Moon must understand. Proposed as `intent.moon.*` in the `space` domain. Every one of them
gets synthetic training data (section 9) and a held-out spoken test set.

| Group | Intent | Slots | Examples |
| --- | --- | --- | --- |
| Navigate | `show_place` | place / artifact / descriptor | "show me Tycho", "where's the giant bullseye", "take me to the Apollo 11 lander" |
| | `show_side` | near / far | "show me the far side" |
| | `view_control` | zoom in/out, spin, reset | "zoom in", "spin it", "go back" |
| | `show_layer` | places / hardware / landing sites | "show me all the rovers", "hide the pins" |
| | `find_by_relation` | relation, anchors | "what's northwest of Glushko", "halfway between Orientale and Ohm" |
| Learn | `ask_fact` | entity, attribute (size, age, location, when, why, how) | "how big is Orientale", "when did Surveyor 3 land" |
| | `explain_term` | term | "what does albedo mean" |
| | `compare` | entity A, entity B | "which is bigger, Tycho or Copernicus" |
| | `who_left` / `who_drove` | artifact | "who left this here", "who drove the Apollo 16 rover" |
| | `what_did_it_do` | artifact | "what did Surveyor 3 find" |
| Listen | `play_crew` | place / topic / color | "what did the astronauts say about the yellow part" |
| | `play_voice` | person | "play Charlie Duke's message" |
| | `play_event` | event | "play the launch", "what did liftoff sound like" |
| | `playback_control` | stop, pause, resume, repeat, louder, quieter, skip | "stop", "say that again", "louder" |
| Tour | `start_tour` | kind (rovers, landers, Apollo sites) | "show me everything left on the Moon" |
| | `tour_control` | next, previous, stop | "next", "stop the tour" |
| Missions | `start_mission`, `hint`, `answer`, `skip_mission` | place / artifact | "give me a mission", "I need a hint", "it's this one" |
| Talk like an astronaut | `describe_place` | the kid's own description (tags: geo.*) | "it's bright and bumpy with rays" |
| Dialogue | `confirm_yes`, `confirm_no`, `choose_option` | option | "yes", "the first one", "Vavilov" |
| | `repair` | — | "what?", "I didn't hear", "say it again" |
| | `greeting`, `thanks`, `goodbye` | — | |
| | `misconception` | claim | "the moon is made of cheese right" |
| | `off_topic` | — | "what's for lunch" |
| App | `theme`, `open_about`, `help`, `mute` | light/dark | "make it dark", "what can you do" |
| Safety | `pii_disclosure`, `unkind`, `jailbreak` | — | handled by the guard; never answered with the content |
| **Mission (v3)** | `intent.mission.allocate` | `load` (shields, life_support, greenhouse, science, rover, comms, heaters), `amount` {kind: percent/delta/all/half/little/none, value}, `from` | "put 30 percent into shields", "more to heaters" |
| | `intent.mission.dispatch` | `vehicle`, `task` (collect_ice, repair_array, explore, return), `target` | "send the rover to get ice" |
| | `intent.mission.shelter` | `on` | "everyone into the shelter" |
| | `intent.mission.query` | `what` (power, oxygen, life_support, dose, storm, comms, all) | "how much power is left?" |
| | `intent.mission.call_houston` | `text` | "Houston, we have a problem" |
| | `intent.mission.confirm`, `intent.mission.cancel` | — (only while a confirm is pending) | "yes, do it", "no wait" |
| | `intent.mission.end_shift` | — | "end shift", "next" |
| | Modifiers: `cmd.boundary`, `cmd.negation`, `cmd.condition`, `cmd.correction`, `cmd.amount` | compound, negated, conditional ("if power drops below 20…"), self-corrected, numbers + units | "shields to 40 and bring the rover home", "don't touch life support" |
| | Radio: `discourse.radio.{copy,roger,say_again,go,no_go,readback,…}` | readback match vs the last CAPCOM line | "copy, shields forty" |

Mission intents map 1:1 onto `Command` in [`MISSION_CONTRACT.md`](MISSION_CONTRACT.md). Slots, targets, grounding on
telemetry ("it's dropping" → power), addressee (device / team / Houston) and tiers are in
[`ARC_MULTISTREAM_PLAN.md`](ARC_MULTISTREAM_PLAN.md) §4.

Context the app sends with each turn: `last_place`, `playing` (clip id + time), `tour` (stop i of n), `mission` (active
id), `emotion`. Follow-ups ("who drove *it*?", "what's *that* crater?") must resolve against them.

---

## 7. What to fix: known issues with evidence

Every item below was seen in this project. Fixing these is the first training goal.

| # | Problem | Evidence | Fix |
| --- | --- | --- | --- |
| 1 | Lunar names typed as people/orgs | 616 of 820 typed person (section 2) | New `lunar_feature` type + `space` domain adapter |
| 2 | ~10% of lunar names missed | 97 caught only by the gazetteer fallback | Tier A/B synthetic audio + list-context training |
| 3 | Jargon typed as names | "albedo" 64× as an entity | `geo.term` tag |
| 4 | Directions typed as names | ~100 direction words as entities | `geo.direction` + relation spans |
| 5 | Hardware/mission names trip the privacy guard | "Apollo 16 Moon buggy" → `guard` in the app | `spacecraft`/`mission` types; PII heads must not fire on known catalog entities |
| 6 | Number in an address typed as time | "42 Oak Street" → `time_of_day 42` | Calibrate number types inside address spans |
| 7 | `safety.pii.request` fires on ordinary questions | Head Start saw it on most questions; same here | Recalibrate or drop for the kid domain |
| 8 | Tag questions miss the question act | "the moon is made of cheese right" → no act | Train tag questions ("…, right?") + `discourse.claim` |
| 9 | `command_complete` missing on some questions | "why is the Moon gray" → no event | More kid question endings in training |
| 10 | Unpunctuated monologue = one 75 s utterance | Aristarchus clip came back as one utterance | Segment on pauses for radio monologue; train eou on silence |
| 11 | Laughter fires almost constantly on radio | p > 0.9 through most frames | Recalibrate on reviewed crew clips + radio channel tag |
| 12 | No emotion in output | `affect.emotion.*` never emitted | Emotion/awe head trained on reviewed clips + kid affect set |
| 13 | Live audio metadata too slow | RTF ~1, 1.2–4 s late through the host under load | Smaller chunks, quantized build, drop unused heads |
| 14 | Speakers undercounted, no names | 1–2 speakers on 3–4-crew clips | Speaker enrollment for the roster; radio-trained diarization |
| 15 | ASR hallucination loop | Whisper repeated "I have all the things" 14× on a clip with eating/silence | Repetition guard + silence/noise training for the on-device ear |
| 16 | Misspelled names from ASR | "Orin Ta", "babilov", "Burgius alpha", "Hertzprung", "Carol" | Lexicon variants (4.2) + list context |
| 17 | App audio heard as the kid | Open mic took crew playback as a turn | `audio_event.app_playback` + echo-reference input |
| 18 | `device_directed` has no margin | 0.82–0.92 on chatter vs 0.95–1.0 on questions (Head Start) | Classroom chatter negatives (section 9) |
| 19 | Number type mixed | "20 kilometers" → count, not measure | Unit-aware measure training |

---

## 8. Building the real-audio dataset

Label real NASA audio in three passes:
1. machine words;
2. machine tags linked to catalogs;
3. human review of a sample.

Split by recording, never by sentence. The pipeline already runs in this repo (`backend/pipeline/`).

1. **Words and timing.**
   - Deepgram nova-3 batch (`diarize`, `utterances`, `smart_format`, `keyterm` ≤ 100 from Tier A + the clip's title),
     with Whisper large-v3-turbo as a second opinion.
   - Where they disagree on a name, that word goes to review.
   - Per word: `t0, t1, word, speaker, confidence`. Script: `backend/pipeline/transcribe_deepgram.py`.
2. **Align existing human transcripts** (Apollo Flight/Surface Journals, Fearless Steps) to the audio with a CTC forced
   aligner. Treat them as gold for words and speakers.
3. **Silver tags.**
   - Arc Tagger spans, linked to the gazetteer + hardware catalog and retyped.
   - Rule lists for `geo.*`.
   - GET timeline alignment for `event.space.*`.
   - Arc v1.1 for audio events and speakers.
   - Every tag keeps its source (`arc`, `gazetteer`, `rules`, `timeline`, `human`).
4. **Human review.**
   - 10% of utterances, plus every name disagreement, every `geo.relation` candidate and every low-confidence link.
   - A form, no free text.
   - Relations are labeled by hand only.
5. **Splits.**
   - **train:** Apollo + Artemis interviews and loops;
   - **dev:** 10 Artemis II flyby clips;
   - **test:** 10 other flyby clips + the Apollo in Real Time held-out hours (below), never trained on.
   - The crew's two proposed craters (Integrity, Carroll) and their spoken directions stay in test as the relation
     probe.
6. **Kid safety.** Crew audio has occasional adult language. Mark it `kid_safe=false` for playback but keep it in
   training.

---

## 9. Synthetic data

No public dataset has children asking about the Moon, and no list of 9,087 names will be heard in real audio. Both are
synthetic. Labels come free from generation. Total plan: **~170,000 utterances, ~140 hours** (113,000 name-coverage + 54,500 kid-intent utterances at ~2.5 s, plus ~25 h of radio and call-outs).

### 9.1 Name coverage (for the ASR)

| Set | Recipe | Utterances |
| --- | --- | --- |
| Tier A names (~550) | 20 carrier phrases × 6 voices (3 kid, 3 adult), cycling through each name's pronunciation variants | ~66,000 |
| Tier B names (2,023) | 5 carrier phrases × 3 voices | ~30,000 |
| Tier C satellite features (7,064) | 1 phrase × 1 voice ("Copernicus A") | ~7,000 |
| Hardware, missions, crew (~250) | 10 phrases × 4 voices | ~10,000 |

**Carrier phrases** come in kid style ("show me ___", "where is ___", "what happened at ___"), crew style ("we're looking
right down on ___", "___ is just to the northwest") and CAPCOM style ("Orion, Houston, ___ in view").

### 9.2 Kid intents (for the tagger and the ear)

| Bucket | Example | Teaches | Utterances |
| --- | --- | --- | --- |
| Show / find | "show me the giant bullseye" | `show_place`, descriptors | 8,000 |
| Hardware questions | "who drove the Apollo 16 rover" | `who_left`, `spacecraft`, `mission` | 6,000 |
| Crew audio requests | "what did the astronauts say about the yellow part" | `play_crew`, `geo.color` | 4,000 |
| Mission sounds | "play the launch" | `play_event`, `event.space.*` | 1,500 |
| Explain a word | "what does albedo mean" | `explain_term`, `geo.term` | 3,000 |
| Spatial directions | "halfway between Orientale and Ohm" | `geo.relation` | 4,000 |
| Compare / facts | "which is bigger, Tycho or Copernicus" | `compare`, `ask_fact`, measures | 3,000 |
| Tours, missions, playback control, view control | "next", "stop", "zoom in", "give me a hint" | control intents | 5,000 |
| Self-corrections | "show me Tycho, no wait, Copernicus" | correction span | 3,000 |
| Mispronunciations | "Aris-tar-cus", "Oriental", "Vavilof" | linking under noise | 4,000 |
| Misconceptions | "the moon is made of cheese right" | `misconception`, `discourse.claim` | 2,000 |
| Follow-ups with context | "who drove it?" + `last_place` | context resolution | 3,000 |
| Private details (negatives) | "my name is Maya and I live at 42 Oak Street" | `safety.pii.*` | 2,000 |
| Hardware names that must NOT trip PII | "Apollo 16 Moon buggy", "Surveyor 3" | fix #5 | 2,000 |
| Off-topic, chatter, greetings | classroom talk | `device_directed=false`, `off_topic` | 4,000 |

### 9.3 Radio and acoustics

- **Radio conversion** of clean astronaut speech: band-limit to 300–3,000 Hz; add static, dropouts, quindar tones and
  1–2.5 s delays. ~20 h. Teaches `channel.*`, quindar, static, LOS.
- **Mission call-outs:** TTS reads real CAPCOM lines from GET timelines over loop background. ~5 h.
- **Classroom:** babble at 5–15 dB SNR, RT60 0.3–0.8 s, tablet mics. Plus the app's own playback leaked into the mic
  (fix #17).

### 9.4 Voices

- **Kid voices:** child-range TTS for ages 6–12, several accents, and 10% Spanish/Hindi-English code-switch.
- **Real kids:** ~20% of the kid set re-recorded by children with parental consent, at events.
- **Local generation:** use the Steer TTS family where it has child voices.

---

## 10. Fine-tuning with list context

Train both models to **use whatever list they're given**, so at runtime the app can pass any 10–100 names without
retraining.

**Recipe (applies to the Arc Transcriber decoder and to the Arc Tagger linker head):**

1. **Build a list for each training utterance.** Take its true names (from labels) and add distractors:
   - 50% random from the same tier;
   - 30% phonetically close (Double Metaphone / embedding neighbours: "Vavilov" ↔ "Pavlov", "Ohm" ↔ "Ohm A");
   - 20% from the same region of the Moon.
2. **List size:** sample from {0, 5, 10, 30, 100, 300}. Size 0 keeps the model working with no list.
3. **Positive dropout:** with probability 0.15, drop the true name from the list, so the model doesn't blindly copy from
   it and still hears names that aren't listed.
4. **Order and format:** shuffle the list. Pass it in the same field the runtime uses (`names` / `context` / `terms`),
   with each entry's type and id (`{"text":"Vavilov","type":"lunar_feature","id":"iau-<feature id>"}`).
5. **Output:** for each span, the linked list entry + a score, so the app can apply its accept / ask / reject thresholds.
6. **Curriculum:** start with lists that contain the answer; mix in dropout and large lists after the first epoch.
7. **Evaluate per list size:** name recall, false insertions of list names that weren't said, and latency.
   **Accept the change only if** recall with list size 0 does not drop, and false insertions stay under 1 per 100
   utterances at list size 100.

Steer's book-search results set the expectation: a whole-catalog bias barely helps, while short candidate lists checked
against the audio help a lot (80% → 84–88% right first). This recipe trains the model for that short-list setting.

---

## 11. Training order and evaluation

Cheapest change first. Each step is gated on the held-out Artemis II test clips, with no regression on the r8 gold sets.

1. **Lists only** (in progress for the demo): gazetteer expansion, spoken variants, keyterms.
2. **Arc Tagger `space` domain adapter + new heads** on silver + reviewed real text + synthetic kid text. Trunk frozen.
3. **Relation head + resolver** (relation parse → lat/lon ± radius).
4. **Arc Transcriber:**
   - list-context fine-tune on name-coverage audio (9.1) + radio + kid sets;
   - event heads (quindar, static/LOS, channel);
   - laughter recalibration;
   - awe and kid affect.
5. **Distill and quantize for the edge** (section 12).

| Metric | Baseline (2026-11-13) | Target v1 |
| --- | --- | --- |
| Lunar-name mention recall (Artemis test clips) | ~90% | ≥ 97% |
| Correct type on lunar names | 14% place (75% person) | ≥ 95% `lunar_feature` |
| Link accuracy | not yet measured on gold | ≥ 95% |
| Tier A name WER (synthetic kid voices) | not yet measured | ≤ 5% |
| Tier B name WER (synthetic) | not yet measured | ≤ 10% |
| Name recall on crew radio audio | not yet measured | ≥ 95% Tier A |
| `geo.relation` resolved within radius | 0 (no head) | 2/2 crew craters + ≥ 80% synthetic |
| Kid query → right action + place first (spoken, 60 queries × 4 voices) | not yet measured | ≥ 85%, ≤ 5% asks |
| App intent top-1 (held-out synthetic + real kid set) | — | ≥ 92% |
| Hardware names wrongly guarded as PII | "Apollo 16 Moon buggy" guarded | 0 on the hardware list |
| Laughter/awe precision on reviewed crew clips | fires on most frames | ≥ 0.8 |
| Speakers per clip exact | undercounts | ≥ 80% of clips |
| End of speech → answer, on device | ~1.2 s with Flux (Head Start) | ≤ 700 ms p50 |

---

## 12. Running it locally

One model host per device loads each model once and serves every app on it. The target is a laptop or tablet with no
network after setup, and < 1.5 GB RAM for the live path. The host is `model_server/` in this repo (FastAPI). Head Start
uses it in draft PR WhissleAI/headstart#1, at ~1 ms extra per tagger call.

| Model | Today (M3 Pro) | On-device target |
| --- | --- | --- |
| Arc Tagger v0.3 | 26 MB int8 native C; 0.1 ms/word batch, ~1–2 ms per streamed word | Same + `space` adapter (< 2 MB) |
| Arc v1.1 Mini | ~1 GB RSS with the tagger; RTF ~1 live under load | RTF ≤ 0.3 live; metadata ≤ 500 ms behind the words |
| Arc Transcriber (full, Parakeet 0.6B) | ~3.3 GB, batch only | Batch indexing on laptops only |
| Live ear | Deepgram Flux (cloud) in the demo | **Arc Transcriber Edge (4-bit), offline**, with the lunar vocabulary |
| Embeddings | EmbeddingGemma 2 (740M) in Head Start | Shared `/v1/embed` on the host |

**Host endpoints today:**
- `GET /health`
- `POST /v1/tag`
- `WS /v1/tag/stream`
- `POST /v1/meta`
- `WS /v1/stream`

**Host rules:**
- weights load once, per-session state;
- a session cap that fails open;
- no audio stored;
- private details redacted before anything leaves the device.

---

## 13. Asks for the Arc team and open questions

- [ ] Confirm tag names (section 5) and intents (section 6) for the ontology (r9?) before labeling starts.
- [ ] A `space` domain in both models.
- [ ] How far can a definition-keyed head take a new tag from its definition alone, before labels?
- [ ] A native list API (`names` / `terms` / `context`) with per-span link output, trained per section 10.
- [ ] An emotion/awe carrier on device: Arc v1.1 Mini emits none; STT-meta-1B has no local weights.
- [ ] Live speed of Arc v1.1 Mini (RTF ~1 through the host under load): a smaller-chunk or quantized build?
- [ ] Arc Transcriber Edge (4-bit): ETA, and lexicon/list support for the 9,087 lunar names.
- [ ] Speaker enrollment for a small roster (Artemis II + Apollo crews).
- [ ] An echo-reference input (the app's playback signal) to stop self-hearing (fix #17).
- [ ] Licensing for the Fearless Steps corpus; NASA media is free to use with no implied endorsement.
- [ ] A consent form and storage rules for real kid recordings (default: none stored).

---

## 14. Appendix: file formats and scripts

**Utterance row (real or synthetic), one JSONL line:**

```json
{"rec": "art002a000022", "set": "artemis2-flyby", "split": "dev", "src": "real", "t0": 31.2, "t1": 48.9,
 "words": [{"w": "yellow", "t0": 40.1, "t1": 40.4, "spk": "1", "conf": 0.98}],
 "spans": [{"start": 3, "end": 5, "tag": "entity.mention.lunar_feature", "link": "iau-<feature id>", "src": "arc+gazetteer"}],
 "utt": {"act": "statement", "intent": null, "awe": 0.82, "channel": "air_to_ground", "kid_safe": true},
 "context": {"names": [{"text": "Aristarchus", "type": "lunar_feature", "id": "iau-<feature id>"}], "last_place": null},
 "audio_events": [{"tag": "laughter", "t0": 45.0, "t1": 46.2, "src": "arc-v1.1"}]}
```

**Lexicon row** (`vocab/lunar_lexicon.jsonl`):

```json
{"name": "Aristarchus", "tier": "A", "iau_id": "<feature id from the IAU link field>", "lat": 23.7, "lon": -47.5, "type": "Crater",
 "origin_lang": "Greek", "prons": ["ar-ih-STAR-kus", "ar-iss-TAR-kus"], "spellings_seen": ["Aristarcus"]}
```

**Scripts in this repo:**
- Existing:
  - `backend/pipeline/scrape_manifest.py`: NASA Artemis audio manifest
  - `fetch_media.sh`: download
  - `transcribe_deepgram.py`: words with keyterms
  - `build_index.py`: Arc Tagger + gazetteer linking → index
  - `build_audio_meta.py`: Arc v1.1 audio metadata
  - `probe_tagger.py`: the baseline numbers
- Proposed:
  - `vocab/build_lexicon.py`: IAU file → tiers → lexicon
  - `synth/render_text.py`, `synth/speak.py`, `synth/degrade.py`: synthetic sets
  - `train/make_list_context.py`: section 10 lists
