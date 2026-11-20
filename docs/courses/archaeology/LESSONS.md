# Archaeology v1: lesson drafts

Draft content for course #2 (`docs/COURSES.md` §3). Steps use the course.json step types
(`backend/app/academy/content.py` `ACCEPT_TYPES`). Four new types are marked **NEW** and specified in `COURSES.md` §3.2.

**Status: built (P3, `feat/archaeology-content`).** The playable lessons are `backend/data/courses/archaeology/course.json`
(the course pack's folder: `places.json`, `entities.json`, `ear_vocab.json`, `sources.json`, `rings/`, `media/`). The
tables below were the drafts; where the built lesson differs, the JSON wins (and the differences are listed in
"What changed from the drafts" at the end).
- Every fact cites `sources.json` by `source_id`: 40 sources, each opened and checked on 2026-11-19, quote verbatim.
- Play it: it is the course pack `course_archaeology` (docs/COURSES.md §4.9): Settings → For grown-ups → Course storage
  → Get, then the course chip. From source (authors): backend `OUTPOST_DEV_COURSE=archaeology`.
- Reading level: grades 9-12 (owner decision 2). Prompts ≤ 20 words; spoken replies ≤ 20; hints ≤ 14.

> **Teacher note (review before a pilot).** This course is a draft for teacher review. Before a classroom pilot,
> review it, especially *Who decides?*, *Many voices* and *Mesa Verde, around 1280*, with Crow Canyon's education team
> or a tribal cultural office. No tribe has endorsed it. (Also in `course.json` `teacher_note`, which the teacher
> pack shows; owner decision 3 is still open.)

Rules for every lesson (`COURSES.md` §1.5):
- Park-level locations only.
- No human remains on screen.
- Leave artifacts in place.
- Say "Ancestral Puebloans", never "Anasazi".
- Say "moved", never "vanished".
- Tribal views come from tribal or NPS / Crow Canyon sources that tribes helped write. CAPCOM never speaks for a tribe.

Voice roles (owner decision 1): keep **CAPCOM** and **Houston**, presented through the analogy. The **Field Director**
is "your CAPCOM on the dig" and **the Lab** is "your Houston: results come back after a delay" (a radiocarbon lab can
take days or weeks: Beta Analytic "3-14 business days", NOSAMS weeks). Lesson 1's brief says it out loud; `course.json`
`roles` holds the lines for the platform.

---

## L1 `what_is` · Clues, not treasure · patch Field Scout · ~4 min · pin Mesa Verde NP

Hook: the globe flies from the whole Earth to the Four Corners. "Archaeologists read the past from what people left."

| # | Type | Prompt (≤20 words) | Accepts / answer | Reply |
|---|---|---|---|---|
| 1 | predict | What is an archaeologist mostly looking for? | Treasure / **Clues about daily life** | "Clues. A broken pot can say more than gold." |
| 2 | intent | Find Mesa Verde National Park, in the south-west corner of Colorado. | place `mesa_verde` | "That's it. Ancestral Puebloans lived here for centuries." |
| 3 | choice | Which is evidence, not a guess? | **A dated roof beam** / A legend online / A movie scene | "A dated beam can be checked. That's evidence." |
| 4 | keywords | What do we call the study of the past through what people left? | `archaeology` | |
| 5 | **decide** NEW | You find a pottery piece on a trail. What do you do? | Photo it and leave it ✓ / Take it home / Hide it | Every option gets a reason. ✓: "Right. Where it lies is part of the clue." |

Facts:
- Mesa Verde protects nearly 5,000 known archaeological sites, including about 600 cliff dwellings [check:
  nps.gov/meve/learn/historyculture/cliff_dwellings_home.htm].
- Taking artifacts from federal land is against the law (ARPA, 1979) [check: nps.gov/subjects/archeology/laws-regulations-guidelines.htm].

## L2 `survey` · Read the land from above · patch Sky Surveyor · ~5 min · pin Four Corners → Mesa Verde hillshade

Hook: NASA and the Park Service used aircraft scanners to find ancient Chaco roads that photos missed (NASA *Spinoff*
1978, ntrs.nasa.gov/citations/20070018879).

| # | Type | Prompt | Accepts | Reply |
|---|---|---|---|---|
| 1 | predict | Before digging, what should come first? | **Look from above and walk the land** / Dig test holes everywhere | "Look first. It costs nothing and harms nothing." |
| 2 | choice | Lidar maps the ground by timing what? | **Laser pulses** / Sound waves / Radio from space | |
| 3 | **hillshade** NEW | Low sun on the mesa top. Tap the three room blocks the park describes. | 3 tap targets (NPS-interpreted features only) | "Low light makes small bumps throw shadows." |
| 4 | keywords | What is walking the land in lines, looking down, called? | `survey`, `pedestrian survey`, `transect` | |
| 5 | describe | Describe the mesa from above: size, shape, edges. | descriptor kinds | |

## L3 `layers` · Layers tell time · patch Layer Reader · ~5 min · schematic trench (no real site)

Hook: "Dirt piles up like pages in a book. The bottom page was written first."

| # | Type | Prompt | Accepts | Reply |
|---|---|---|---|---|
| 1 | predict | In undisturbed ground, which layer is oldest? | **The bottom** / The top / The thickest | "The bottom. That's the law of superposition." |
| 2 | **layers** NEW | Order this trench's layers, oldest to youngest. | 5 layers: bedrock, floor, ash, collapse, topsoil | "Floor, then ash, then the roof fell in." |
| 3 | choice | A pit cuts down through three layers. It is… | **younger than all three** / older than all three | "Whatever cuts a layer came after it." |
| 4 | keywords | What's the word for studying layers? | `stratigraphy` | |
| 5 | sequence | Put the dig steps in order. | photo · measure · dig one layer · bag and label · record | |

## L4 `dating` · Dating the past · patch Ring Counter · ~5 min · pin Mesa Verde (Long House)

Hook: NPS ranger-style line: "A beam can tell you the year its tree was cut."

| # | Type | Prompt | Accepts | Reply |
|---|---|---|---|---|
| 1 | predict | Can a roof beam give the exact year a room was built? | **Yes, from its tree rings** / No, only a guess | |
| 2 | **rings** NEW | Slide the beam's rings until they match the master pattern. Say the outer year. | offset ±1 → **1275** | "1275. That matches the Long House beam the park dated." |
| 3 | choice | Wide rings usually mean a year that was… | **wet** / dry / cold | |
| 4 | predict | Radiocarbon dating gives… | **a range of years** / one exact year | "A range, like 1250 to 1290. Tree rings can give the year." |
| 5 | keywords | Tree-ring dating has a long name. Say it. | `dendrochronology`, `tree ring dating` | |

Facts:
- Mesa Verde has worked with the University of Arizona's tree-ring lab since 1923.
- A Long House beam was cut in 1275.
- "The last tree-ring date in the region is 1281." [read: nps.gov/meve/learn/education/tree-rings.htm]
- The master series is the Mesa Verde Douglas-fir chronology, ITRDB CO652 [check: Stahle et al. 2015].

## L5 `stuff` · Things people left · patch Object Reader · ~4 min · pin mesa-top pithouse (NPS-interpreted)

| # | Type | Prompt | Accepts |
|---|---|---|---|
| 1 | predict | A grinding stone and a hand stone. What were they for? | **Grinding corn** / Weapons |
| 2 | rounds | Name each object: mano, metate, potsherd, yucca sandal (photos: NPS, or Smithsonian CC0 after a licence check) | per round |
| 3 | describe | Describe the potsherd: colour, pattern, thickness. | descriptor kinds |
| 4 | choice | A trash heap is called a… | **midden** / kiva / mesa |
| 5 | **decide** NEW | Rain washed a sherd down the slope. Can we say where it was used? | Not exactly; it moved ✓ / Yes, right here |

Teaches site formation: things move after people leave (water, animals, collapse).

## L6 `law` · Who decides? · patch Steward · ~5 min · pin Mesa Verde

| # | Type | Prompt | Accepts |
|---|---|---|---|
| 1 | predict | Can anyone dig on public land if they're careful? | **No, it needs a permit** / Yes |
| 2 | rounds | Match the law: Antiquities Act 1906 · ARPA 1979 · NHPA Section 106 · NAGPRA 1990 → what each protects | per round |
| 3 | **decide** NEW | A road is planned over a known site. What happens first? | **A review with tribes and the State** ✓ / Build, then look |
| 4 | choice | NAGPRA returns ancestors and sacred items to… | **tribes and descendants** / museums / collectors |
| 5 | keywords | Taking care of sites for the future is called… | `stewardship` |

Before it ships, check the NAGPRA 2024 wording against eCFR 43 CFR Part 10. No images of remains or sacred items.

## L7 `voices` · Many voices · patch Listener · ~5 min · pin Mesa Verde

Hook: a quote from NPS or Crow Canyon material written with tribal partners. Name the 26 associated tribes (NPS list).

| # | Type | Prompt | Accepts |
|---|---|---|---|
| 1 | predict | Did the people of Mesa Verde vanish? | **No, they moved south; their descendants live today** / Yes |
| 2 | choice | Today's Pueblo peoples include… | **Hopi and Zuni** / Maya / Inca |
| 3 | video / watch | NPS or Crow Canyon clip, if licence allows; else a photo and a line | — |
| 4 | **decide** NEW | A tribe asks you not to dig one area. You… | **Change the plan** ✓ / Dig anyway, carefully |
| 5 | keywords | Asking descendant communities before research is called… | `consultation` |

## L8 `mesa_verde` · Mesa Verde, around 1280 · patch Case Builder · ~6 min · pin Mesa Verde

The case study joins L3, L4 and L7: tree rings show drought years in the late 1200s; the last tree-ring date is 1281;
by about 1300 people had moved south.
- Present the reasons as several causes historians and descendants discuss: drought, conflict, social and religious
  change.
- Give no single answer.

| # | Type | Prompt | Accepts |
|---|---|---|---|
| 1 | predict | Narrow rings in the late 1200s suggest… | **drought** / floods |
| 2 | sequence | Order: first pithouses · mesa-top pueblos · cliff dwellings · move south | — |
| 3 | choice | The last tree-ring date in the region is… | **1281** / 1066 / 1492 |
| 4 | describe | Give two kinds of evidence for your claim. | evidence kinds: rings, layers, objects, oral history |
| 5 | keywords | Say one reason people may have moved. | `drought`, `conflict`, `farming`, `water`, … |

## L9 `capstone` · Survey season · patch Season Lead

This is the mission (`COURSES.md` §3.3). The lesson node opens Survey season.

## Explorer: `chimney_rock` · Moonrise at Chimney Rock · patch Moon Watcher (the Moon ↔ Earth bridge)

Globe: start on the **Moon**, then switch body to **Earth** and fly to Chimney Rock National Monument.

| # | Type | Prompt | Accepts |
|---|---|---|---|
| 1 | predict | How often does the Moon rise between the two rock spires? | **About every 18.6 years** / Every month |
| 2 | intent | Find Chimney Rock National Monument in south-west Colorado. | place `chimney_rock` |
| 3 | choice | The next major lunar standstill is in… | **2044** / 2030 |

Fact: USFS, "Northern Major Lunar Standstill" (fs.usda.gov/r02/sanjuan/…) [read]. Frame the alignment as a scholarly
interpretation.

---

## Survey season (mission) data sketch (`seasons.json`)

```json
{"id": "mesa_tract_a", "title": "Mesa tract survey", "fictional": true,
 "days": 14, "resources": {"trust": 60, "integrity": 100, "knowledge": 0},
 "chapters": [
  {"id": "permits", "now": "File the permit and write to the tribes' cultural offices.",
   "choices": [{"id": "consult_first", "trust": 20, "days": -3},
               {"id": "start_now", "trust": -30, "flag": "rushed"}]},
  {"id": "remote", "now": "Pick what to look at before anyone digs.",
   "choices": [{"id": "lidar_low_sun", "knowledge": 25, "days": -1},
               {"id": "test_pits", "integrity": -20, "knowledge": 10, "days": -2}]},
  {"id": "walk", "now": "Walk the transects. Record what you see."},
  {"id": "dig", "now": "Choose one small test unit, where your question is."},
  {"id": "date", "now": "Send samples to the Lab.", "lab_delay_days": 2},
  {"id": "report", "now": "Share the report. Keep the location private."}
 ],
 "stars": {"integrity": 90, "trust": 80, "question_answered": true}}
```

## Patches

Field Scout · Sky Surveyor · Layer Reader · Ring Counter · Object Reader · Steward · Listener · Case Builder · Season
Lead · (explorer) Moon Watcher.
- Ids: `archaeology:<id>`.
- Shape: the round mission-patch, with an earth-tone ring.

## What changed from the drafts (P3)

- **27, not 26.** Mesa Verde's pages now say "27 Pueblos and Tribes"; the 2018 PDF lists 26. The lessons say 27.
- **Far View Reservoir** (the drafts' "Mummy Lake"): NPS calls it "Far View Reservoir (currently dry)" and does not
  say what it held; its purpose is debated. The hillshade step names it that way.
- **Cliff dwellings:** "late 1190s to late 1270s" (NPS article); other NPS pages say 1180-1280 or 1180-1300.
- **ARPA** covers "public lands or Indian lands", not "federal land". **NHPA §304** says agencies "shall withhold".
- **Chimney Rock:** 25 affiliated tribes; USFS says the ancestral people "would have seen" the moonrises. The lesson
  frames it as an interpretation in a `decide` step.
- **Tree rings:** NCEI publishes only raw measurements for CO652, so `rings/itrdb_co652.json` is a standard chronology
  built from the 197 series (negative-exponential detrending, biweight mean; method in its `derivation`). No licence
  is stated on the record; it asks for the citation, which the step and the fact carry.
- **L5 describe** uses the existing descriptor kinds (tone, texture, size); **L8** replaces the "evidence kinds"
  describe with a `decide` step (several causes), so the Moon's describe kinds are untouched.
- **L7** shows a descendant's words on screen (NPS ranger TJ Atsye, Laguna Pueblo, NPS audio tour); the app's voice
  never reads them.
- **L9 capstone** is a 5-step preview of Survey season (consult, look, record, order, keep locations private) until
  the P4 mission replaces it.
- **Not found with a clean licence:** an NPS mano/metate photo, a tree-ring photo, a Chimney Rock photo (USFS pages
  credit named photographers). The lessons use text there.
