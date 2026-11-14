# NASA and NASA-derived dataset inventory for Arc Transcriber / Arc Tagger (space adaptation)

Verified 2026-11-13 by opening each URL (curl/WebFetch) unless marked **UNVERIFIED**. "PD" = US-government work, generally not under US copyright. NASA's rule, quoted from https://www.nasa.gov/nasa-brand-center/images-and-media/: media "generally are not subject to copyright in the United States… NASA should be acknowledged as the source," with no implied endorsement, and third-party items are marked.

Tag key: **SPK** speaker/diarization · **ROLE** role (CAPCOM, FLIGHT, EECOM, PAO, crew) · **INT** intent · **ENT** entities · **EVT** events · **EMO** emotion/sentiment · **ASR** words.

## Summary table

| Dataset | Contents | Size/hours | Labels included | Licence | Download | Teaches which tags |
|---|---|---|---|---|---|---|
| Fearless Steps FS-1..FS-4 challenge corpora (UTD-CRSS), Apollo 11 (+A13, A8) | Multichannel MOCR loops (FD, MOCR, GNC, NTWK, EECOM), 0–20 dB SNR | 100 h challenge set (~36 h speech); FS-3 adds 5 h unseen-channel + 5 h Apollo-13; FS-4 adds 10 h Apollo-8 | SAD, diarization, speaker ID, ASR transcripts; FS-3 adds conversational analysis (extractive summarisation, hotspot); FS-4 adds speaker verification and topic detection. Sentiment exists in papers (109 h A11 + 10 h A13 + 6 h A8), not in challenge releases | "NASA Media Usage Guidelines" (FS-2 page); cleared by NASA Export Control | **Request access**: registration forms are closed; email FearlessSteps@utdallas.edu. S3 bucket `exploreapollo-audiodata` is not listable | SPK, ROLE (channel = role), ASR, topic→INT, EVT (mission phase), EMO (paper data only) |
| Fearless Steps 19k-hour Apollo-11 MOCR audio = NASA uploads on Internet Archive (`A11_T###_HR#_CH##`) | Raw 30-track MOCR tapes, one item per tape×channel, ~8.3 h WAV each (+FLAC/MP3/OGG) | 1,428 A11 items, 6.5 TB (~11.9k h); 484 A13 items | None (raw). Filename encodes tape, head, channel, wall-clock span | PD (NASA JSC upload, collection `nasaaudiocollection`; no licenseurl set) | `ia download <id>` or `https://archive.org/download/<id>/<id-without-.wav>.flac`; list: `https://archive.org/advancedsearch.php?q=identifier:A11_T*&fl[]=identifier&rows=2000&output=json` | ASR pretraining (self-supervised), SPK, ROLE via channel→console map, noisy-channel robustness |
| Internet Archive `apolloaudiocollection` (JSC Houston Audio Control Room) | Air-to-ground, PAO, onboard, MOCR reels per mission: Apollo 1, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17 | 19 items; e.g. Apollo13Audio 851 GB, Apollo17 328 GB, Apollo11Audio 284 GB | None (reel numbers only) | Public Domain Mark 1.0 | `ia download Apollo17 --glob='*.mp3'`; `https://archive.org/metadata/Apollo13Audio` gives the file list | ASR, SPK, ROLE, EVT (after alignment to the journals) |
| Apollo in Real Time (apolloinrealtime.org, Ben Feist), A11/A13/A17 | Mission audio synced to GET; utterance CSVs | A11: 11,000 h MOCR audio, 240 h space-to-ground, 15k utterances (CSV 14,895 lines) | GET timestamp, speaker callsign, text, commentary, milestones | Repo `bfeist/apolloinrealtime.org` has **no licence file** (UNVERIFIED terms; source audio is PD) | `curl -L https://raw.githubusercontent.com/bfeist/apolloinrealtime.org/main/mission-data/11/MISSION_DATA/A11_merged_utterances.csv` (format `GET|type|speaker|text`) | **Best alignment source**: ASR, SPK, ROLE, EVT, ENT |
| Apollo Flight Journal + Apollo Lunar Surface Journal (apollojournals.org) | Corrected air-to-ground and onboard transcripts with commentary, photos, audio clips | All crewed Apollo flights; ALSJ covers surface EVAs | GET per utterance, speaker, CSS class (`cc`=CAPCOM, `onboard`, `pao`, `comment`) | NASA-hosted volunteer work; **UNVERIFIED** terms (no licence statement found) | HTML scrape: `https://www.apollojournals.org/afj/ap11fj/02earth-orbit-tli.html`, `.../alsj/a11/a11.landing.html`; utterance anchors `<a name="HHHMMSS">` | ASR text, SPK, ROLE, ENT, EVT, plus INT/ENT for Arc Tagger text training |
| NASA Artemis Audio Library (nasa.gov/artemisaudio) | Artemis II flyby observations, crew reactions, launch, splashdown; some Artemis I | 113 clips (13 short + 46 extended flyby + 54 other), MP3 + some WAV (96 kHz/24-bit) | Title and description only | "No additional permission is required"; NASA media guidelines | `https://www.nasa.gov/wp-content/uploads/YYYY/MM/<file>`; scrape the page, then `grep -oE 'https://www.nasa.gov/wp-content/uploads/[^"]+\.(mp3|wav)'` | ASR on modern Orion comms, EMO (awe/joy: "OMG stop it"), ENT (craters: Orientale, Ohm, Vavilov) |
| NASA Image & Video Library API, media_type=audio | 79 "Houston We Have a Podcast" episodes, KSC launch multitrack feeds (Artemis II, Crew-10..13, IM-2, Roman), MCC-H→ISS safe-haven calls | **136 audio items in total** (2025–26); 0 items from 1960–75 | `description` holds the **full podcast transcript** (median 37.7k chars), plus keywords, center, date | NASA media guidelines (PD) | `GET https://images-api.nasa.gov/search?media_type=audio&q=…&page_size=100`, then `GET /asset/{nasa_id}` → `~orig.mp3`, `~128k.mp3`, `metadata.json` | ASR (with transcript, no timestamps), SPK (host/guest), ENT, ROLE (launch commentator vs. countdown net) |
| JSC Oral History Project | Interview transcripts with flight controllers, astronauts, engineers | ~755 PDF transcript links on the index page | Speaker turns (interviewer/subject), dates, positions | NASA (PD); disclaimer on views | PDFs: `https://www.nasa.gov/wp-content/uploads/YYYY/MM/<name>-M-D-YY.pdf` from https://www.nasa.gov/history/history-publications-and-resources/oral-histories/johnson-space-center/ | Arc Tagger text (ENT, ROLE vocabulary, INT); **no audio found** |
| JPL Horizons Artemis II (−1024), Artemis I (−1023) | Ephemeris plus a "MAJOR EVENTS" list with MET and UTC (TLI 5 m 55 s, OTC-3, closest approach 8,282 km, entry, splashdown) | Text | Event times | JPL/NASA (PD) | `curl "https://ssd.jpl.nasa.gov/api/horizons.api?format=text&COMMAND='-1024'&OBJ_DATA=YES&MAKE_EPHEM=NO"` | EVT (align to Artemis audio) |
| Artemis II OEM ephemeris (AROW page) | CCSDS OEM state vectors, 10 inner zips (02–10 Apr 2026) | 1.5 MB zip | Time-tagged position | NASA | `https://www.nasa.gov/wp-content/uploads/2026/03/all-artemis-ii-oem-files.zip` | EVT (phase), app content |
| DONKI space weather (api.nasa.gov) | CME, GST, IPS, SEP, MPC, RBE, HSS, WSA-Enlil, notifications | JSON events | Event type, time, instruments, links | NASA (PD) | `https://api.nasa.gov/DONKI/CME?startDate=…&endDate=…&api_key=KEY` (**FLR returned 404 today**; DEMO_KEY rate-limits quickly) | Synthetic EVT ("solar flare alert") |
| Lunar hardware coordinates (LROC 2016 + NSSDCA + NASA 2012 catalogue) | Lat/lon/elevation of Apollo LMs, LRVs 15/16/17, Surveyors 1/3/5/6/7, Rangers, S-IVBs, GRAIL-A/B, LADEE | 3 PDFs/pages | Coordinates ±0.3–19 m | NASA/ASU (LROC credit) | See notes | ENT gazetteer for app and tagger |
| CGI Moon Kit (SVS 4720) | LROC colour (2k–16k sRGB TIFF), LOLA displacement (4/16/64 ppd) | multi-GB TIFFs | n/a | NASA SVS (credit) | `https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/lroc_color_16bit_srgb_8k.tif`, `.../ldem_16.tif` | App visuals |
| LOLA global DEM 118 m (USGS) | GeoTIFF DEM | single large TIFF | n/a | PD | `https://planetarymaps.usgs.gov/mosaic/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif` (redirects to S3) | App terrain |
| ARISS school contacts | Upcoming-contact pages list the **students' question lists as text**; livestream links (YouTube/Vimeo, school-owned) | Ongoing; several per month | Questions (text), school, astronaut, callsign, UTC | ARISS page text; recordings are third-party/school-owned (**not PD**, ask) | Scrape https://www.ariss.org/upcoming-educational-contacts.html; archive at `/news-archive.html`; YouTube `@ARISSlive` | INT/ENT for kid queries (text), ROLE (student vs astronaut); audio is rights-restricted |
| Perseverance SuperCam microphone (PDS) | Raw, calibrated and derived audio from the Mars mic (laser zaps, wind, Ingenuity) | PDS bundle, updated 2026-08 | PDS4 labels, sol, target | PD (PDS) | `wget -r -np https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/` | EVT (non-speech sound events), noise augmentation |

## Per-dataset notes (URLs opened)

### 1. Fearless Steps (UTD-CRSS)
- Opened: https://fearless-steps.github.io/ChallengePhase2/ , /ChallengePhase2/Data.html , /ChallengePhase3/ , /ChallengePhase3/Data.html , /ChallengePhase4/ , /Fearless-Steps-Workshop . The root https://fearless-steps.github.io/ and /ChallengePhase1/ return **404**.
- Challenge corpus: Apollo-11 mission stages 1, 5 and 6. Lift Off 25 h, Lunar Landing 50 h, Lunar Walking 25 h = 100 h, with ~36 h of speech. It uses 5 of 29 channels: FD, MOCR, GNC, NTWK, EECOM. SNR is 0–20 dB.
- FS-2 tracks: SAD; diarization with system SAD (SD_track1) and with reference SAD (SD_track2); SID; ASR with system and with reference SAD. The split is 80 h train/dev + 20 h blind eval.
- FS-3 adds 5 h of unseen-channel eval and 5 h of Apollo-13 blind eval, plus conversational analysis tasks (extractive summarisation, hotspot detection). It was hosted on NIST OpenSAT (https://sat.nist.gov/fsc3); the registration form is now closed.
- FS-4 adds 10 h of manually transcribed Apollo-8 data, speaker verification, and topic detection (tracks 6a/6b).
- Licence text (FS-2 page): "The Entire Fearless Steps Corpus consisting of over 19,000 hours of audio from the Apollo-11 Mission is publicly available under the 'NASA Media Usage Guidelines'… contact us at FearlessSteps@utdallas.edu." Data was approved for public release by NASA Export Control.
- **No LDC catalogue entry found** (UNVERIFIED either way). NSF papers mention LDC collaboration on transcribing A11/A13.
- Sentiment and topic annotations (109 h A11, 10 h A13, 6 h A8) come from NSF PAR paper abstracts (https://par.nsf.gov/biblio/10542792), seen as search snippets only. They are **UNVERIFIED** as a downloadable release.
- Labels such as ASR transcripts and speaker IDs were not inspected (access is gated). Action: email FearlessSteps@utdallas.edu for the FS-2/3/4 packages with labels.
- The "30-track MOCR" source tapes are the Internet Archive `A11_T*` items (below), uploaded by john.l.stoll@nasa.gov.

### 2. Apollo audio on the Internet Archive
- Opened: `https://archive.org/metadata/A11_T648_HR1U_CH30_11-17-56_19-17-58_-_2015-10-01_Recording.wav`. It has 37 files: WAV 30,089 s (~8.4 h) at 2.65 GB, plus FLAC, MP3, OGG and a spectrogram PNG. Collection `nasaaudiocollection` (5,680 items).
- Filename pattern: `A11_T<tape>_HR<1|2><U|L>_CH<1-30>_<start>_<end>-<digitisation date>Recording.wav`. The channel number maps to a MOCR console loop; the mapping is in the FS papers and Apollo in Real Time's channel list (FLIGHT, CAPCOM, EECOM, GNC, FIDO, RETRO, GUIDO, SURGEON, INCO, NETWORK, …).
- Collection `apolloaudiocollection` (PD Mark 1.0), "Digitized, cataloged and archived by the Houston Audio Control Room": Apollo1 3 GB, Apollo7 1 GB, Apollo8 315 GB, Apollo9 94 GB, Apollo10 381 GB, Apollo11Audio 284 GB, Apollo12Audio 146 GB, Apollo13Audio 851 GB (1,080 files, e.g. `405-AAA_TRACK-1` 6.6 h), Apollo14 289 GB, Apollo15 239 GB, Apollo16 310 GB, Apollo17 328 GB (66 MP3 reels `765-AAA…`), and NasaAudioHighlightReels 125 GB.
- Apollo 13/17 air-to-ground loops sit inside these per-mission items, but individual reels are not labelled as A/G vs. MOCR in metadata; **UNVERIFIED** which reels are air-to-ground. Use the Apollo in Real Time channel mapping.
- Commands: `pip install internetarchive; ia download Apollo17 --glob="*.mp3"`, or `curl -L https://archive.org/download/Apollo17/765-AAA.mp3`.

### 3. Apollo Flight Journal / Apollo Lunar Surface Journal
- history.nasa.gov/afj and hq.nasa.gov/alsj now redirect to https://www.nasa.gov/history/alsj-and-afj/ , which links to https://apollojournals.org/ (opened).
- AFJ format, from https://www.apollojournals.org/afj/ap11fj/02earth-orbit-tli.html:
  `<div class="cc"><a name="0001818"></a><b>000:18:18 McCandless:</b> Apollo 11, this is Houston…</div>`
  - On that page the class counts are `onboard` 304, `cc` 25, `pao` 12, `comment` 39.
  - The chapter index is at `/afj/ap11fj/index.html` (01launch.html … 17day5-undock-doi.html).
- ALSJ format, from https://www.apollojournals.org/alsj/a11/a11.landing.html: `<b><a name="1021541">102:15:41</a></b> Collins: …`, with `<source src="a11a1021133-3114.mp3">` audio clips whose start GET appears in the caption. These clips include FD-loop and NC-loop excerpts.
- Scrape method: a BeautifulSoup pass over each chapter page; regex `^(\d{3}:\d{2}:\d{2}) ([^:]+): (.*)`; the class gives the role or channel.
- Licence: no explicit statement found (**UNVERIFIED**). Transcripts are NASA-derived; the commentary is volunteer-authored. Credit them and ask before redistributing the commentary.

### 3b. Apollo in Real Time (strongly recommended)
- Opened: https://apolloinrealtime.org/11/ . It lists "11,000 hours of Mission Control audio, 240 hours of space-to-ground audio, All onboard recorder audio, 15,000 searchable utterances", with 50+ MOCR channels by name.
- A13 and A17 sites exist (/13/, /17/).
- Data is on GitHub at https://github.com/bfeist/apolloinrealtime.org (pushed 2026-10-27; **no licence**):
  - `mission-data/{11,13,17}/MISSION_DATA/*_utterances.csv` (pipe-delimited `GET|type|speaker|text`), `*_commentary.csv`, and `SOURCE-MANIFEST.tsv`.
  - This gives GET-aligned, speaker-labelled transcripts to pair with the MOCR channel audio, and lets you derive EVT tags from milestones.

### 4. NASA Artemis Audio Library
- Opened https://www.nasa.gov/artemisaudio/ . There are 113 unique `.mp3`/`.wav` links. Flyby clips are under `/wp-content/uploads/2026/10/`, e.g. `art002a000015-omg-stop-it.mp3` and `art002a000019-reid-geologist.mp3`.
- **Correction:** `https://www.nasa.gov/wp-content/uploads/2026/01/3-hour-lunar-surface-observation.wav` is a **26-second** clip (96 kHz, 24-bit stereo PCM, 15 MB; ffprobe). Its title is "Artemis II Preparations: Planned Lunar Observations". It is not 3 hours of audio.
- Terms: "No additional permission is required to use these sounds", under NASA media guidelines.

### 5. NASA Image & Video Library API
- Opened: `https://images-api.nasa.gov/search?media_type=audio` → `total_hits: 136`.
  - Breakdown: 79 HWHAP episodes; the rest are KSC launch-coverage feeds (e.g. `KSC-20260401-AU-LMM01-0001-Artemis_II_Live_Launch_Coverage_Tech_Feed_OE1_212_Mix`, pad mics, ambisonic) and JSC ISS calls (`06-05-26_MCC-H-calls-ISS-to-safe-haven`, `10-01_DG1 conversation_Zero_G_indicator`).
  - `year_start=1960&year_end=1975` returns **0** audio items. The historic Apollo audio is not in this API.
- Fields: `center, date_created, description, description_508, keywords, media_type, nasa_id, title`, and sometimes `album, location`.
- Asset manifest: `GET https://images-api.nasa.gov/asset/<nasa_id>` → `~orig.mp3`, `~128k.mp3`, `~128k.m4a`, `~64k.m4a`, `metadata.json`.
- HWHAP `description` contains the full verbatim transcript, which gives 79 long-form audio+transcript pairs (no timestamps; force-align them). The RSS feed is https://www.nasa.gov/feeds/podcasts/houston-we-have-a-podcast .

### 6. JSC Oral History Project
- Opened: https://www.nasa.gov/history/history-publications-and-resources/oral-histories/johnson-space-center/ . It has ~755 PDF transcript links on that page, e.g. `https://www.nasa.gov/wp-content/uploads/2025/07/jwa-1-18-00.pdf` (John Aaron, EECOM).
- The page says transcripts "are created from audio-recorded oral history interviews". **No audio links were found** (0 mp3/wav), so audio is UNVERIFIED/unavailable.
- Use: text only, for Arc Tagger domain vocabulary (console names, procedures).

### 7. Telemetry / event timelines
- **Horizons −1024 = Artemis II (VERIFIED)** and −1023 = Artemis I. Opened via the API.
  - The −1024 header has MET+UTC events: launch Apr 1 2026 22:35:12 UTC; TLI start 1/01:14 (Apr 2 23:49 UTC); OTC-3 4/04:28:05; lunar SOI entry; closest approach 8,282 km at 5/00:26 (Apr 6 23:01); max Earth distance 413,146 km; entry interface 9/01:18; splashdown 9/01:32 (Apr 11 00:07 UTC). Crew: Wiseman, Glover, Koch, Hansen; capsule "Integrity".
  - The `horizons_lookup.api` endpoint returned 404.
- AROW page: https://www.nasa.gov/missions/artemis/artemis-2/track-nasas-artemis-ii-mission-in-real-time/ (nasa.gov/trackartemis 404s). Its ephemeris zip, `all-artemis-ii-oem-files.zip`, contains 10 OEM zips, 1.5 MB.
- Apollo GET timelines: (a) AFJ/ALSJ GET anchors; (b) Apollo in Real Time utterances and milestones; (c) "Apollo by the Numbers" SP-4029, https://history.nasa.gov/SP-4029/Apollo_00a_Cover.htm → redirects to `https://www.nasa.gov/wp-content/uploads/2023/04/sp-4029.pdf` (36 MB; contents not parsed, but its mission event tables in GET are well known; **UNVERIFIED** table format).
- DONKI: `api.nasa.gov/DONKI/{CME,GST,IPS,SEP,MPC,RBE,HSS,WSAEnlilSimulations}` return 200; **FLR returns 404** (`/DONKI-API/get/FLR/`) as of today. `notifications` hit the DEMO_KEY rate limit (get a free key). `kauai.ccmc.gsfc.nasa.gov/DONKI/WS/get/*` timed out. Value for us is limited to synthetic "space weather" EVT and intent prompts.

### 8. Hardware on the Moon (coordinates)
- **LROC 2016 robotic table**, https://www.lroc.asu.edu/data/support/downloads/2016_LROC_Coordinates_of_Robotic_Spacecraft.pdf (opened, 28 Jul 2016). Values are ME frame, east longitude, ±m:
  - Surveyors: Surveyor 1 −2.4745/316.6602; S3 −3.0162/336.5820; S5 1.4551/23.1943; S6 0.4742/358.5725; S7 −40.9812/348.4873.
  - Rangers: Ranger 6–9.
  - Apollo S-IVB impact sites: A13–A17.
  - Impactors: GRAIL-A 75.6088/333.4060; GRAIL-B 75.6508/333.1659; LADEE 11.8494/266.7506.
  - It also covers Luna, Lunokhod and Chang'e 3/Yutu.
- **LROC 2016 human features**, https://www.lroc.asu.edu/data/support/downloads/2016_LROC_Coordinates_of_Human_Features.pdf (opened):
  - Apollo LMs: A11 0.67416/23.47314; A12 −3.0128/336.5781; A14 −3.64589/342.52806; A15 26.13239/3.63330; A16 −8.9734/15.5011; A17 20.1911/30.7723.
  - LRVs: A15 26.13174/3.63803; A16 −8.9729/15.5037; A17 20.1896/30.7769.
  - It also has ALSEPs and LRRRs.
- **NSSDCA Apollo site coordinates**, https://nssdc.gsfc.nasa.gov/planetary/lunar/lunar_sites.html (opened): LM, ALSEP and LRRR, DE421 ME frame, from Wagner et al. 2017 (Icarus 283). They agree with LROC.
- **NSSDCA Surveyor page**, https://nssdc.gsfc.nasa.gov/planetary/lunar/surveyor.html (opened): landing lat/lon/time. Surveyor 4 lost 2.5 min before touchdown in Sinus Medii (no coordinates).
- **Lunar Prospector**: NSSDCA spacecraft 1998-001A, "approximately 87.7 S, 42.0 E" (opened).
- **NASA History "Catalogue of Manmade Material on the Moon"** (2012), https://history.nasa.gov/FINAL%20Catalogue%20of%20Manmade%20Material%20on%20the%20Moon.pdf (opened, 1,018 lines of text):
  - It gives the item-level inventory per Apollo site (flag, plaques, PLSS, bags, etc.) and is ideal for kid-app "what's there" content.
  - Coordinates: LCROSS shepherding −84.72/−49.62 and Centaur −84.9/−35.5. Lunar Prospector and Surveyor 4 are listed as UNKNOWN.
  - It contains a typo, Ranger 9 "112.828 N", which should be −12.828. It predates GRAIL and LADEE.
- NSSDCA Master Catalog pages work: `https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id=<COSPAR>`, e.g. 1969-059C = Apollo 11 LM.
- LROC featured sites: https://www.lroc.asu.edu/featured_sites (200, opened, not parsed in detail). Spatiotemporal shapefiles exist, e.g. `https://data.lroc.im-ldi.com/lroc/view_rdr/SHAPEFILE_APOLLO_11` (search result only, **UNVERIFIED**).

### 9. Imagery and terrain
- **CGI Moon Kit**, https://svs.gsfc.nasa.gov/4720 (opened; Ernie Wright, 2019):
  - Colour maps: `lroc_color_2k.jpg`, `lroc_color_16bit_srgb_{4k,8k,16k}.tif`, and polar variants.
  - Displacement maps `ldem_{4,16,64}.tif` (float km relative to 1737.4 km), with `_uint` variants (16-bit half-metres relative to 1,727,400 m).
  - Base path: `https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/`.
- **LOLA DEM 118 m**: `planetarymaps.usgs.gov/mosaic/Lunar_LRO_LOLA_Global_LDEM_118m_Mar2014.tif` → 302 to `asc-pds-services.s3.us-west-2.amazonaws.com` (200). The PDS GDR directory is at https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/cylindrical/ (200).
- **LROC WMS**: `https://wms.lroc.asu.edu/lroc` redirects to `data.lroc.im-ldi.com`, which serves an HTML "LROC WMS Image Map" browse page, not raw GetCapabilities XML. **UNVERIFIED** as a machine WMS endpoint.
- QuickMap: https://quickmap.lroc.asu.edu/ (200; JS app, no documented bulk API verified).

### 10. Other
- **ARISS**: https://www.ariss.org/upcoming-educational-contacts.html (opened). Each contact lists the school, astronaut, callsign, UTC time, livestream link, and "As time allows, students will ask these questions: 1. … 2. …".
  - This is the **only real corpus of kids' questions to astronauts**, as text. Questions are multilingual (e.g. French for École Secondaire du Sommet).
  - Audio is livestreamed on school YouTube/Vimeo or ARISS YouTube `@ARISSlive` (200). It is third-party content: not PD, needs permission.
  - The old ISS Fan Club archive (oldsite.issfanclub.eu, 2007–2017) has listener recordings of the 145.800 MHz downlink (search results only, **UNVERIFIED**; rights unclear).
- **HWHAP podcast**: transcripts are in the Images API (above), and the RSS feed is linked from https://www.nasa.gov/podcasts/houston-we-have-a-podcast/ .
- **Mars sounds**: https://science.nasa.gov/mission/mars-2020-perseverance/sounds-of-mars/ (opened). Perseverance carries two mics, SuperCam (mast) and EDL.
  - PDS bundle https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/ (opened) has `data_raw_audio/`, `data_calibrated_audio/` and `data_derived_audio/`, last updated 2026-08-10.
- ISS live audio: not verified as a downloadable dataset (**UNVERIFIED**). The JSC safe-haven MCC-H↔ISS clips in the Images API are the only verified ISS A/G audio found.

## Gaps (what does not exist and must be synthesised)
1. **Kids' speech about the Moon or space**: no public child-speech audio corpus. ARISS gives the questions as text only; the audio is third-party, far-field and adult-moderated. Synthesise with child TTS voices plus a text bank from ARISS questions; consider a consented in-house collection.
2. **Artemis-era mission-control audio with labels**: Artemis audio is 113 curated clips plus launch feeds. There are no multichannel MOCR loops and no diarization or role labels. Role/console tags for modern ops must be transferred from Apollo (Fearless Steps channels) or synthesised.
3. **Emotion labels on space speech**: only FS sentiment (paper-level, gated). No public emotion-labelled astronaut audio; label in-house or use weak labels (e.g. Artemis "reaction" clip titles).
4. **Intent labels**: no dataset tags operational intents (GO/NO-GO poll, readback, request, status report). Derive them from AFJ/AiRT text with rules or an LLM, then hand-check.
5. **Time-aligned event tags**: Horizons and AiRT give event times, but nothing pre-aligns them to audio frames. Build them by joining GET/UTC timelines to the IA reels (each reel's filename has wall-clock start/end).
6. **Offline Orion/ISS cabin acoustics**: there are no public cabin noise impulse responses or noise beds. Approximate them with launch-feed and onboard-recorder audio (DSE onboard in AFJ/AiRT), then augment.
7. **Word-level alignments**: none of the sources have word timestamps. FS ASR labels are segment-level (UNVERIFIED), and AiRT/AFJ are utterance-level GET at 1 s resolution. Force-align.

## Outpost Luna cabin window: bundled terrain and Earth (app visuals, offline)

The mission cabin's SITE, ROVER and EARTH window views (`frontend/src/mission/terrain.js`) draw real lunar terrain around each south-pole site. Everything ships inside the app (`frontend/public/terrain/` → `dist/terrain/`); nothing is fetched at runtime, so the desktop installer works with no network. ORBIT keeps the globe's LROC colour map (`/media/img/moon4k.jpg`, CGI Moon Kit row above).

Rebuild (build time only, needs network once): `uv run --no-project --with numpy==2.1.3 --with pillow==11.0.0 python frontend/tools/build_terrain.py [site_id …]`. The script range-requests only the rows each tile needs, keeps them in memory, and writes nothing else to disk.

| Asset | Source (opened 2026-11-13) | Product | Tile written | Size |
|---|---|---|---|---|
| `terrain/<site>/context.png` | https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/IMG/LDEM_75S_120M.IMG (+ `.LBL`) | LRO LOLA gridded DEM, south polar stereographic, 120 m/px, 75°S–90°S (PDS LRO-L-LOLA-4-GDR-V1.0) | 512² at 240 m/px (2×2 mean), 123 km across, centred on the site | ~355 kB each |
| `terrain/<site>/site.png` | https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/IMG/LDEM_80S_40M.IMG | same, 40 m/px, 80°S–90°S | 512² at 40 m/px, 20.5 km across | ~240 kB each |
| `terrain/<site>/rover.png` | https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/IMG/LDEM_85S_10M.IMG | same, 10 m/px, 85°S–90°S | 512² at 10 m/px, 5.1 km across | ~145 kB each |
| `terrain/earth.jpg` | https://svs.gsfc.nasa.gov/vis/a000000/a002900/a002915/bluemarble-2048.png | NASA SVS 2915, Blue Marble (NASA Goddard / Visible Earth) | 1024×512 JPEG | 76 kB |
| `terrain/<site>/meta.json`, `terrain/index.json` | written by the script | tile centre (polar-stereographic metres), m/px, DN offset, site height | | <1 kB |

Sites: shackleton_rim, shackleton_floor, connecting_ridge, de_gerlache_rim, malapert_massif (lat/lon from `backend/data/mission/sites.json`). **Total added: 3.7 MB** (15 tiles + Earth + metadata), plus ~110 kB of bundled cabin fonts (Barlow Condensed 600/700, Share Tech Mono; SIL OFL via @fontsource) and ~75 kB minified / 18 kB gzipped of `postprocessing` (pmndrs, zlib).

Format: each PNG is lossless 8-bit RGB with the LOLA height packed as `DN − dn_min = R·256 + G` (DN = 16-bit LSB integer, height = DN × 0.5 m above the 1,737.4 km sphere). Browsers would quantise a 16-bit PNG to 8 bits through `<canvas>`, so the packing keeps the full 0.5 m precision. Projection (PDS label): x = 2R·tan(45° + lat/2)·sin(lon), y = 2R·tan(45° + lat/2)·cos(lon); sample = SAMPLE_PROJECTION_OFFSET + x/scale, line = LINE_PROJECTION_OFFSET − y/scale (0-based). The client applies the Moon's curvature (−d²/2R) and feathers each finer tile into its parent so the nested meshes meet.

How the window uses the sim's numbers: Sun and Earth elevations are the sim's (JPL Horizons, `backend/data/mission/ephemeris_*.json`), so the window matches the SUN EL / EARTH EL readouts. Horizons gives elevation only; azimuths follow the globe's convention (Earth toward longitude 0; the Sun 140° from it, turning once per 708.7 h lunar day). Real terrain may hide a body the sim calls "up" (the sim models terrain as one effective horizon angle). When the Sun is below the horizon the window says LOW-LIGHT CAMERA and raises a fill light so the ground stays readable.

Credit line shown on the window: "Terrain: NASA LRO LOLA elevation · Earth: NASA Blue Marble · Uses NASA open data; not endorsed by NASA." App-wide credit: "Inspired by NASA's Artemis program. Uses NASA open data; not endorsed by NASA." Licence: NASA/PDS data is a US-government work, generally not under US copyright; acknowledge NASA (LRO LOLA team, NASA GSFC/MIT; NASA Goddard Blue Marble). No NASA endorsement is implied.

Not used, and why: PGDA's high-resolution south-pole site DEMs (5 m/px GeoTIFFs, https://pgda.gsfc.nasa.gov/) are hundreds of MB per region and not range-readable as raw rows; the PDS polar LDEMs give the same LOLA heights at 10–120 m/px with one Range request per tile. Possible later: an LROC NAC frame of each site, an Artemis II Earth image for the EARTH view (credited "NASA, Artemis II").
