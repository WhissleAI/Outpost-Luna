# Outpost Luna: advisor discussion brief

2026-11-13 · For the advisor conversation. One page per topic: what we have, what we're building, open questions.
Outpost Luna (formerly Ask the Moon / Moonbase Cadet) is our NASA Space Apps 2026 entry for **"Build a Junior Astronaut
Mission Trainer"** (kids 7–12). It's inspired by NASA's Artemis program and uses NASA open data. It is not endorsed by
NASA.

## 1. The story, through the Artemis lens

Artemis II flew its crew around the Moon in April 2026; we use their real recorded audio. **Artemis III, the first
landing near the south pole, hasn't happened yet.** That gap is the story. The kid isn't watching history; they're
training for what comes next.

| Beat | What the kid does | Real NASA material behind it |
| --- | --- | --- |
| **Flight School** (Academy) | Short voice lessons with CAPCOM as a mentor, earning a patch per lesson | Artemis II crew audio, the hardware left on the Moon (NSSDCA, LROC), IAU lunar names |
| **Space words** | Vocabulary drills: match, say, fill the blank, listen & pick | The glossary (albedo, ejecta, regolith, terminator…) with sources |
| **Check ride** | First solo shift in a simplified cockpit, with a real solar storm | The real May 2024 G5 storm (DONKI), Chang'e 4 radiation measurement |
| **Outpost Luna** (Mission) | Command a south-pole outpost for 10 days by voice from a cockpit | JPL Horizons Sun/Earth positions at real Artemis III candidate regions; DONKI storms |
| **Debrief** | What happened, the real data behind each event, try another strategy | Every event links to its source |
| **Next crew** | Replay or pick another site | A different real-event seed each run |

**Questions for the advisor:**
- Should the story have named characters (CAPCOM, a flight director) or stay neutral?
- How strongly should we tie it to Artemis III, given the landing date isn't fixed?
- Should a Mars "next frontier" teaser stay as one line in the debrief, or become a short epilogue?

## 2. How NASA might see the project and its use

What we know for certain: Space Apps judges on **Impact, Creativity, Validity, Relevance and Presentation**
([2025 submission guide](https://www.spaceappschallenge.org/resources/project-submission-guide/),
[Judging & Awards Guide](https://www.spaceappschallenge.org/resources/judging-awards-guide)).
What the challenge asks for:
- real engineering trade-offs, where no choice is free;
- real NASA open data, with sources shown in the app;
- ages 7–12;
- replayability;
- a short explanation of the data used.

| Criterion | Our case |
| --- | --- |
| **Impact** | A voice-first trainer works for kids who can't yet read well, kids with visual impairments, and classrooms. It runs fully on a laptop, offline, with no accounts and no stored audio |
| **Creativity** | You talk to Mission Control, and real Artemis II crew voices are part of the lessons. The cockpit reacts to your orders; storms arrive from real dates |
| **Validity** | Every fact the app says comes from a sourced card, and every number is traceable to NASA data (DONKI, Horizons, NSSDCA, LROC, IAU). There's no generative model in the loop, so it can't make facts up |
| **Relevance** | Built directly on the challenge's named data (DONKI, Artemis data) and on the Artemis III south-pole regions |
| **Presentation** | A 2-minute arc: Flight School → check ride with a real storm → cockpit mission → debrief with sources |

**How it could be used beyond the hackathon:**
- classroom units on the Moon, light and radiation;
- museum or planetarium kiosks (offline);
- accessible STEM for kids with visual or hearing impairments;
- a reusable voice-trainer pattern for other NASA datasets.

**Questions for the advisor:**
- Which of these uses should the pitch lead with?
- Do we know anyone at NASA STEM Engagement or a museum to show it to?
- Is "inspired by Artemis" the right line on endorsement?

## 3. Accessibility

We are building it into the app now. The full spec will be in `docs/ACCESSIBILITY.md`.

| For | What we're adding |
| --- | --- |
| **Visual impairments** | Everything works by voice. "Where am I?" / "What can I do?" describes the screen. An audio-description mode speaks every globe move, highlight and gauge change. Full keyboard control, screen-reader labels on every cockpit control, high contrast, 100–150% text, reduced motion |
| **Hearing impairments** | Captions always on (guide, CAPCOM, hardware stories and crew audio), with the word being spoken highlighted. Visual alerts (flashing border plus icon) instead of only a chime, and vibration where supported. Transcripts of crew clips. Typing works everywhere |
| **Reading support** | A dyslexia-friendly font option, short caption lines, adjustable speech speed |

**Questions for the advisor:**
- Should we test with a teacher of visually impaired students?
- Is sign language (an avatar or video) worth scoping, or is that out of reach?
- Which accessibility standard should we cite: WCAG 2.2 AA?

## 4. Vocabulary: teaching space words

- A new **"Space words"** lesson plus vocab steps inside other lessons, all from our sourced glossary:
  - **match:** word to meaning;
  - **say it:** the app hears you, using the local Arc ear;
  - **fill the blank;**
  - **listen & pick.**
  
  These earn a "Word Explorer" patch.
- Words reappear in context: CAPCOM uses them in the Mission, the cockpit labels them, and tapping any highlighted word opens its card and plays it aloud.

**Questions for the advisor:**
- Which words matter most at ages 7–9 vs. 10–12?
- Should we align with NGSS (Next Generation Science Standards) terms so teachers can map lessons to standards?

## 5. Highlighting and enrichment

What changes:
- **Captions with word highlighting,** synced to the speech. Today speech has no visual track.
- **Key information marked in captions, cards and the radio log:** places and hardware (tap to fly there), numbers with units, vocabulary words (tap for the definition), and mission resources. Marks use underline and shape, never colour alone.
- **Speech speed:** 0.75× to 1.5×, applied through Steer's rate control so it stays natural, not chipmunk audio.
- **More steering:** slower and clearer for vocabulary and younger kids, emphasis on the word being taught, calm during alarms, excited for patches.

**Questions for the advisor:**
- How much enrichment is too much on screen for a 7-year-old?
- Should key-word highlighting be on by default or opt-in?

## 6. Models (everything local except NASA data)

Every model below runs locally:

| Job | Model | Size |
| --- | --- | --- |
| Hearing | Arc v1.1 Mini (Whissle) | ~1 GB RAM with metadata |
| Understanding | Arc Tagger v0.3 (Whissle), plus a tiny embedder (MiniLM, int8) | 26 MB + 53 MB |
| Deciding | A learned Director, a tiny Mamba-3 (Whissle Director family), next to the rules; it acts only where it proved it adds no wrong action (guarded) | 743K params, 0.9 MB |
| Speaking | Steer TTS Edge (Whissle), with styles chosen per line | ~12 MB |
| Knowledge | 106 sourced knowledge cards; no cloud LLM | — |

Current gaps:
- The learned Director acts only in two situations: when a command names an on-screen control, and when our own voice or a clip is heard back. In those two it was never worse than the rules on any test set, but the gain is small: +41 right calls over ~6,200 turns. Everywhere else the rules decide.
- The ear has only been tested on synthetic kid voices.

**Ask for the advisor:** can we get 10 minutes of real kids using it before the final pitch?

## Sources

- [Space Apps 2025 project submission guide](https://www.spaceappschallenge.org/resources/project-submission-guide/)
- [Space Apps Judging & Awards Guide](https://www.spaceappschallenge.org/resources/judging-awards-guide)
- Data sources and their URLs: [NASA_DATASETS.md](NASA_DATASETS.md); the mission data in `backend/data/mission/` (each file lists its sources).
