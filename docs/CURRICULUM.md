# Class lessons: teacher-written lessons and how they load

A teacher (or a parent) can write lessons for their class in **Settings → For grown-ups → Class lessons**. A Class
lesson plays exactly like a NASA lesson: the same lesson card, CAPCOM's voice, hints after two misses, voice / typed /
tap answers, and a patch at the end. It sits in Flight School as its own row and pins, next to NASA's lessons. It never
replaces them: NASA lessons, their order, the "Lesson n of 6" count and the check ride are untouched, and a Class
lesson's facts show as **Class facts**, each with the teacher's own source link, never as "NASA facts".

Code: `backend/app/academy/classpacks.py` (schema, checks, compile, loader, store), `backend/app/academy/class_routes.py`
(API), `backend/app/academy/content.py` (`course()` = NASA + Class), `frontend/src/class_editor.js` (+ `.css`, the
editor), `frontend/src/academy/class_patch.js` (the letter patch), `frontend/src/academy/pins.js` `classTrackHtml` (the
map row), `frontend/src/explorer.js` `isClass`. Tests: `backend/tests/test_classpacks.py`,
`frontend/tests/class_editor.test.js`, `frontend/tests/e2e/class_lessons_e2e.py`. Sample pack:
`docs/class_packs/sample_room12.json`.

## 1. The pack file (format v1)

All of one class's lessons travel as **one JSON file**, a *pack*. The editor writes it; Export saves it; Import reads it
on another computer.

```json
{
  "format": "outpost-luna-class-pack",
  "version": 1,
  "id": "room-12",
  "title": "Room 12 Moon unit",
  "lessons": [
    {
      "id": "craters",
      "title": "Craters up close",
      "brief": "Big craters tell the Moon's story. Let's visit two of them.",
      "place": "copernicus",
      "patch": {"name": "Crater Spotter", "glyph": "C"},
      "facts": [
        {"text": "Copernicus is a crater about 96 km wide.",
         "source": {"title": "IAU Gazetteer of Planetary Nomenclature: Copernicus",
                    "url": "https://planetarynames.wr.usgs.gov/Feature/1296"}}
      ],
      "steps": [
        {"kind": "predict", "prompt": "What made most of the round craters on the Moon?",
         "options": ["Space rocks hitting", "Old volcanoes"], "answer": 0,
         "reveal": "Space rocks. Each hit blasted out a round crater."},
        {"kind": "place", "prompt": "Find Copernicus, a big sharp crater on the near side.", "place": "copernicus"},
        {"kind": "choice", "prompt": "Which crater has the south pole on its edge?",
         "options": ["Shackleton", "Copernicus", "Tycho"], "answer": 0, "hint": "It's the one at the very bottom."},
        {"kind": "say", "prompt": "What do we call rock thrown out when a crater forms?", "words": ["ejecta"]}
      ]
    }
  ]
}
```

| Field | Rule (docs/COPY.md §3 budgets) |
|---|---|
| `format`, `version` | exactly `"outpost-luna-class-pack"`, `1` |
| `id` | 1–24 characters, `a-z 0-9 -`, lower case. The file name on disk. A second pack with the same id replaces it. |
| `title` | the pack's name (your class), 6 words / 32 characters at most. Shown on the map row and in Progress. |
| `lessons` | 1–20 lessons, in the order the map row and the editor show them |
| `lessons[].id` | as `id`, unique in the pack. The course id is `c-<pack id>-<lesson id>`; so is the patch id. |
| `title` | 6 words, 24 characters. Unique: no NASA title and no other pack's title (voice opens lessons by title). |
| `brief` | 20 words, 1–2 sentences. Spoken at the start, shown under Brief. |
| `place` | a place id from `GET /api/class/places` (named Moon features and the mission sites; hardware is left out). The lesson's pin. |
| `patch.name` | 1–2 words, 20 characters. `patch.glyph` (optional): one letter or digit drawn on the patch (default: the name's first letter). |
| `facts[]` | up to 5, each 30 words at most, **each with `source: {title, url}`**, the url starting `https://`. |
| `steps[]` | 1–8 (5 or fewer is advised: a warning, not an error) |
| `steps[].kind` | `say` (say a word; voice or typed), `place` (find a place on the Moon), `choice` (multiple choice), `predict` (guess, then the answer is revealed) |
| `steps[].prompt` | 20 words, 90 characters. No quote marks (quoted words are read as an order to repeat back). |
| `say.words` | 1–12 accepted words or short phrases (1–3 words each); any one of them passes |
| `place.place` | a place id, as `place` |
| `choice/predict.options` | 2–4 answers, 6 words each. **No two answers share a key word** (spoken answers match by their words). `answer`: the index of the right one. |
| `predict.reveal` | 20 words: the answer, said after the guess |
| `success`, `fail`, `hint` (optional) | 8 / 6 / 10 words. Defaults: "Roger. That's it.", "Not quite.", and a hint per kind ("Look for the glow." for a place). |

No emoji anywhere. Two steps of the same kind in a row is a warning. Unknown fields are kept in the file and ignored.

## 2. How a pack is compiled

`classpacks.compile_pack` turns each lesson into an ordinary course lesson (the shape `content.py` reads from
`course.json`) with `track: "class"`, `pack: {id, title}`, `badge: {id, name, glyph}`:

| kind | course step |
|---|---|
| `say` | `accept: {type: "keywords", all: [words]}` (any one word) |
| `place` | `accept: {type: "intent", place}`: tap it, or say its name; the target glows from the start, like NASA find steps |
| `choice` | `accept: {type: "choice", answer, options: [{id: a..d, label, say: the label's key words}]}` |
| `predict` | the same options as `predict`, plus `reveal` |

So grading (`/api/academy/attempt`), the hint ladder, the hands-free router ("lesson craters up close", answers by
voice) and the session's lesson table all treat them like NASA lessons. Client-side, `explorer.js isClass` makes a
Class lesson always open and a *bonus* lesson (`isBonus`): it never blocks the check ride and is never in "Lesson n of
6" or in the NASA patch total (`patchTotal`).

## 3. Where packs are stored, and how they load

- **Location:** `CLASS_DIR` if set, else `<per-user data folder>/class/<pack id>.json`: the same folder rule as the
  mission auto-save (`mission/registry.py save_dir`): the desktop app's `cache_dir` (the per-user app data folder, never
  inside the read-only app bundle), else `backend/data/class/` in a dev checkout (gitignored). Nothing is uploaded.
- **Saving:** `PUT /api/class/packs/{id}` validates, then writes atomically (temp file + rename). A pack that fails the
  checks is never written; the editor gets `422 {errors, warnings}` with a path per error (`lessons[0].steps[1].prompt`)
  and marks that field.
- **Loading:** on first use and after every change, `classpacks.packs()` reads every `*.json` in the folder, in file
  name order. Each file is checked like a save. A file that is not JSON, is over 256 KB, fails a check, reuses another
  pack's id or a lesson title another pack has, is **skipped** with one plain line (`problems()`, shown at the top of
  the Class lessons part: "room-12.json: skipped. lessons[0].place: Pick the lesson's place on the Moon from the
  list."). The loader catches everything: a broken pack never stops the app or the NASA course.
- **Joining the course:** `content.course()` = the NASA lessons, then the Class lessons, pack by pack. `content.check()`
  skips `track: "class"` (those are checked by `classpacks.validate`), and the copy tests read course.json. After a save, import, delete or preview, `content.reload()` drops every
  cached lesson list (the course, the voice titles in `hotlist`, the session's lesson table), and the page fires
  `outpost:class-changed`; Flight School fetches the course again and repaints the map.
- **Writes** need the app's own page: same origin and `X-Outpost-Class: 1` (like Reset), so another web page can't
  add lessons. Reads (`GET /api/class/packs`, `/places`) are open like the course.
- **Reset:** "Start over" keeps Class lessons (they are a grown-up's work, not progress); "Reset everything" removes
  the folder. Patches earned in Class lessons are ordinary entries in the cadet's progress (`atm-academy` badges).

API: `GET /api/class/packs`, `GET|PUT|DELETE /api/class/packs/{id}`, `POST /api/class/validate`,
`POST|DELETE /api/class/preview`, `GET /api/class/places`.

## 4. How Class lessons appear

- **Flight School map:** each pack is a row under the NASA track ("Class lessons · Room 12 Moon unit · 1 of 3 done",
  with its next lesson's patch). Pressing it selects that lesson; its pin on the Moon and the usual map card come up
  (eyebrow "Class lesson · Room 12 Moon unit"), and Start opens it. Class pins sit on the Moon at their places but are
  not joined into the NASA route line.
- **The lesson:** the same card and voice. The eyebrow says "Class lesson · <pack>", the facts disclosure says "Class
  facts", each with its source link.
- **The patch:** the round mission-patch shape with the lesson's letter, in a colour per pack (`class_patch.js`, the
  patch palette). It shows on the patch screen, the map's earned strip, the Mission cockpit's patch card ("Class
  lesson") and in Progress (grouped by pack, never in NASA's counts).

## 5. The editor (Settings → For grown-ups → Class lessons)

Behind the grown-ups hold, in the Settings sheet's own look and controls.

- **List:** every pack and its lessons: Edit, Move up / Move down (saved at once), New lesson, Export (one `.json`
  file), Remove pack (asks once more), Import a pack… (a file picker; a bad file says why and changes nothing). What the
  loader skipped is listed at the top.
- **Lesson:** pack name, title, its pin (a list of real places), brief, patch name and letter, facts with source and
  link, then the steps. Each step: its kind (Say it / Find a place / Multiple choice / Predict), the question, what
  counts (answer words, the place, 2–4 answers with the right one marked, the reveal), and "What CAPCOM says" (right /
  not right / hint, with the defaults shown). Steps move up and down and can be removed. Every text field shows its
  budget live ("12 / 20 words"), red when over.
- **Check** runs the server's rules and marks each field; **Preview** plays the lesson in Flight School as the cadet
  sees it (eyebrow "Preview", nothing saved, no patch: the preview is in memory only and hidden from the map);
  **Save** stores it and it's on the map at once.
- **Reach:** every control is a button, a choice or a field in the sheet: Tab and arrows, a controller (buttons and
  choices; typing needs a keyboard, as anywhere in the app), and voice ("press Save", "press Preview").

## 6. Not done

- No images or crew clips in Class lessons (NASA lessons keep those); no `tap`/route/globe steps beyond "find a place".
- Export in the desktop app uses the browser's download (Electron's save dialog); there is no shell-side save dialog
  like diagnostics has.
- Packs are per computer, not per cadet: every cadet on the computer sees the class's lessons.
