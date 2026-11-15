# Space words: vocabulary in the Academy

Kids 7–12 meet words like *albedo*, *regolith* and *terminator* in the Artemis II crew audio. The Academy teaches them
with four short exercise types, a dedicated lesson (**Space words**, badge **Word Explorer**), and single vocab steps
sprinkled into three other lessons. Every term is one the crew really says, and its source is that recording.

## Terms and sources

The 36 terms come from `backend/data/glossary.json` (kid meaning, at most 20 words and spoken-ready, plus spellings to match).
`backend/app/academy/vocab.py` finds, for each term, the first NASA Artemis II crew clip in `data/index/clips.json`
where the crew says it, and records the clip title, its nasa.gov URL, the clip id and the second it is said. The
glossary card (tap a dotted-underlined word anywhere) offers **Hear it** (Steer TTS, `vocab` style: slow, the word
stressed) and **Hear the crew say it** (the clip from 2 s before to 4 s after). `GET /api/glossary` serves the list;
`GET /api/glossary/{term}` one term.

| Term | Kid meaning | Heard in (NASA Artemis II crew audio) |
| --- | --- | --- |
| albedo | How bright or dark a surface is in sunlight. | [Aristarchus Plateau: Color and Limb Relief Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005-ck-vg-relief-color-audio.mp3) at 36 s |
| ejecta | Rock and dust thrown out when something smashes into the Moon. | [Hertzsprung and Vavilov: Ejecta and Terrain Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000025-reid-tourist.mp3) at 37 s |
| regolith | The Moon's dusty, rocky soil. | [Ohm Crater: Ray Systems and Texture Analysis](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000009.mp3) at 301 s |
| limb | The edge of the Moon as we see it. | [Aristarchus Plateau: Color and Limb Relief Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005-ck-vg-relief-color-audio.mp3) at 2 s |
| terminator | The line between the Moon's day side and night side. | [Crew Reacts Joyfully to Earth Rise from Behind the Moon](https://www.nasa.gov/wp-content/uploads/2026/10/art002a00004915-clipped.mp3) at 32 s |
| mare | A dark, flat 'sea' of old cooled lava. | [Aristarchus Plateau: Color and Limb Relief Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005-ck-vg-relief-color-audio.mp3) at 61 s |
| rays | Bright streaks of splashed rock spreading out from a crater. | [Lunar Mosaic Imaging: Multi‑Feature Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005-ck-swampcolors.mp3) at 140 s |
| basin | A giant crater, hundreds of kilometers wide. | [Orientale Basin: Annular Rings and Mare Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000006.mp3) at 28 s |
| plateau | A big raised area of land with a flat top. | [Aristarchus Plateau: Color and Limb Relief Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005-ck-vg-relief-color-audio.mp3) at 20 s |
| relief | How bumpy the ground is: hills, holes and ridges. | [Aristarchus Plateau: Color and Limb Relief Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005-ck-vg-relief-color-audio.mp3) at 1 s |
| hummocky | Covered in lots of small, rounded bumps. | [Aristarchus Plateau: Color and Limb Relief Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005-ck-vg-relief-color-audio.mp3) at 40 s |
| swirl | A bright, curly pattern painted on the Moon's surface. | [Hertzsprung and Vavilov: Ejecta and Terrain Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000025-reid-tourist.mp3) at 18 s |
| impact flash | A tiny burst of light when a space rock hits. | [Impact Flashes: Observing Moon’s Dark Side](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000014.mp3) at 3 s |
| corona | The Sun's glowing outer air, seen when the Sun is hidden. | [Moon During Eclipse: Rare and Striking Visual Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000053-part-1-clipped.mp3) at 46 s |
| earthset | Earth sinking out of sight behind the Moon's edge. | [Earthset: Limb Observations and Moon’s Brightness](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000011.mp3) at 11 s |
| earthrise | Earth coming up over the Moon's edge. | [Crew Reacts Joyfully to Earth Rise from Behind the Moon](https://www.nasa.gov/wp-content/uploads/2026/10/art002a00004915-clipped.mp3) at 138 s |
| crater | A round hole made when a space rock crashed in. | [Aristarchus Plateau: Color and Limb Relief Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005-ck-vg-relief-color-audio.mp3) at 32 s |
| central peak | A mountain in a crater's middle that bounced up. | [Ohm Crater: Ray Systems and Texture Analysis](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000009.mp3) at 178 s |
| pyroclastic | Made by volcanoes spraying out tiny glass beads. | [Far side Albedo: Mare Color and Crater Patterns](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000008.mp3) at 732 s |
| lava | Melted rock that flowed out, then cooled hard. | [Byrgius Alpha and Mare Humorum: Regolith Color](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000017.mp3) at 470 s |
| highlands | The bright, old, bumpy parts of the Moon. | [Whole Moon Imaging and Orientale Feature Descriptions](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000005.mp3) at 266 s |
| pillowing | Soft, puffy-looking rounded shapes, like pillows. | [Hertzsprung and Vavilov: Ejecta and Terrain Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000025-reid-tourist.mp3) at 38 s |
| blanketing | A layer of thrown-out rock covering the ground. | [Orientale South Ejecta: Texture and Distribution Observations](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000024-clipped.mp3) at 3 s |
| orbit | Going around and around something in space. | [Byrgius Alpha and Aristarchus Plateau: Regolith Comparison](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000018.mp3) at 221 s |
| far side | The Moon's side that always faces away from Earth. | [Orientale Basin: Ejecta Extent and Age Assessment](https://www.nasa.gov/wp-content/uploads/2026/10/art002a000019-reid-geologist.mp3) at 8 s |

**Words our own lines use** (fix/flow-resume): everyday space words the guide, the course and the cabin say often. No
crew clip says most of them, so each names a NASA page (`source` in glossary.json); `crew_jargon: false` keeps them
from pausing crew audio to explain them (`moments.load_glossary`). `mare` also matches "dark plain(s)".

| Term | Kid meaning | Source |
| --- | --- | --- |
| near side | The Moon's side that always faces Earth: the face we see every night. | [NASA Science: Moon facts](https://science.nasa.gov/moon/facts/) |
| rille | A long, winding groove on the Moon, often cut by flowing lava. | [NASA Science: what the Moon is made of](https://science.nasa.gov/moon/composition/) |
| impact | A space rock smashing into the Moon. Every crater is an old impact. | [NASA Science: lunar craters](https://science.nasa.gov/moon/lunar-craters/) |
| phase | How much of the Moon's sunny side we can see from Earth. | [NASA Science: Moon phases](https://science.nasa.gov/moon/moon-phases/) |
| eclipse | When the Sun, Earth and Moon line up and one blocks the other's light. | [NASA Science: eclipses](https://science.nasa.gov/eclipses/) |
| solar storm | A burst of fast particles from the Sun. Astronauts take shelter until it passes. | [NASA: space weather](https://www.nasa.gov/space-weather/) |
| millisievert | A unit for how much space radiation your body gets. Smaller numbers are safer. | [NASA: space radiation](https://www.nasa.gov/humans-in-space/space-radiation/) |
| shelter | A safe room with thick walls that blocks space radiation during a solar storm. | [NASA: space radiation](https://www.nasa.gov/humans-in-space/space-radiation/) |
| rover | A car or a robot that drives across the Moon's surface. | [NASA Science: the VIPER rover](https://science.nasa.gov/mission/viper/) |
| permanently shadowed region | A deep crater floor the Sun never reaches. It is so cold that ice stays frozen. | [NASA Science: water and ice on the Moon](https://science.nasa.gov/moon/moon-water-and-ices/) |
| ice | Frozen water. Moon ice could give astronauts water, air and rocket fuel. | [NASA Science: water and ice on the Moon](https://science.nasa.gov/moon/moon-water-and-ices/) |

**Chips and marks** (`frontend/src/highlight.js`): a word is marked (dotted underline, role=button) and chipped under an
answer ("ⓘ lava") only when the glossary has it; a resource word that is also a space word (ice, rover, shelter) opens
its meaning. A chip or a mark opens the same small card (meaning, Hear it, source) on a click, Enter, controller A, a
point-and-hold, or by voice ("what is lava?", "what does that mean?": the latest word on screen). It is centred on
screen, scrolls inside if needed, and one Esc (or ✕) closes only it. Owner bug, 0.1.2: chips never opened anything:
their `data-kind` / `data-ref` were set on a line that sat inside a comment. `tests/glossary.test.js` scans the course,
places, facts, concepts and every fixed line for marked words and checks each has a definition;
`tests/e2e/flows_e2e.py` (glossary) clicks every chip and mark on a card.

## Exercise types

| Type | The kid… | By tap | By voice / typing | Graded (`vocab.grade`) |
| --- | --- | --- | --- | --- |
| `vocab_match` | sees the word, picks its meaning | tap a meaning | says the meaning in their own words ("albedo is how bright a surface is") | the option whose content words overlap the answer most (≥ 2 words or ≥ 50 %), uniquely; naming the word alone doesn't count |
| `vocab_say` | hears the word, says it back | — | the Arc ear's words (or typing) | fuzzy: exact (plural ok), else best `difflib` ratio ≥ 0.75 over 1–2-word windows with spaces removed ("regolis", "earth rise") |
| `vocab_fill` | fills the blank in a sentence | tap a word | says the word | the best-matching word option (≥ 0.8), at least 0.08 ahead of the next (so "earthrise" ≠ "earthset") |
| `vocab_listen` | hears a meaning, picks the word | tap a word | says the word | as `vocab_fill`; the meaning is also shown ("Show the words", open by default while captions are on) |

Authoring (`course.json`): `{"type": "vocab_match", "term": "albedo", "distractors": ["regolith", "terminator"]}`;
`vocab_fill` adds `"sentence"` with a `____` blank. The client gets options with opaque ids (`o1…`, a stable shuffle),
never the answer; `content.check()` rejects unknown terms, missing distractors and blanks.

Steering: every non-pass reply uses the `vocab` situation, and every reply stresses the step's word with
`<slow><emph>` markup (docs/VOICE_STEERING.md §4b).

## Where the steps are

Flight School v3 (docs/LEARNING_DESIGN.md §5) has no separate Space words lesson: each word is taught where it is used,
next to a place on the globe or a crew clip. The `words` patch is retired (`course.json` `retired_badges`). Words
without a step of their own (albedo, terminator, earthrise, far side…) are still tap-to-define in every caption.

| Lesson | Step | Type | Term | Context |
| --- | --- | --- | --- | --- |
| history | 1 | `vocab_match` | mare | the globe flies to Tranquility, where Apollo 11 landed |
| power | 1 | `terminator` (globe) | terminator | tap the real day/night line; the success line glosses the word |
| life | 5 | `vocab_fill` | regolith | "Ice hides in the Moon's dusty soil" |

The front end (`frontend/src/academy/vocab.js`) registers one renderer per type on
`window.__outpost.stepRenderers[type]`; the Academy UI dispatches to it (a marked block in `academy/ui.js`). Options are
numbered buttons, so "option 2" and "press crater" work by voice, and Tab/Enter by keyboard.

## Tests

`backend/tests/test_vocab.py`: every term sourced to a nasa.gov crew clip; the course validates; the public course hides
answers; each type graded by tap and by voice (including fuzzy ASR spellings and near-miss distractors); `/api/glossary`;
the attempt route's `vocab` steering. `frontend/tests/a11y.test.js`: syllable hints.
