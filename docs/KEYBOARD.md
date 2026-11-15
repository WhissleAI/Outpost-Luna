# Keyboard and controller

Outpost Luna can be driven from the keyboard the way a TV app is driven by a remote: the arrows move a big, bright
focus ring from control to control, <kbd>Enter</kbd> selects, <kbd>Esc</kbd> goes back. Voice, camera gestures, taps
and a game controller do the same things, through the same intents. Every flow in docs/FLOWS.md can be finished with
the keyboard alone (tested end to end, §Testing).

Code:
- `frontend/src/input/spatial.js`: the spatial (D-pad) focus engine. It holds the pure geometry, scopes and memory, plus the DOM engine: the Moon reticle and the cabin seat.
- `input/keys.js`: the remote keys as intents. It also owns the Space tap / hold split, the help sheet, the key-hint chip, the focus sound and **Settings → Keyboard & controller**.
- `input/gamepad.js`: game controllers. It maps the standard layout to the same intents.
- `input/keys.css`: the TV focus ring, the reticle, the chips and the help sheet.
- `desktop/main/keys.js`: the app menu, plus the keys the Electron shell keeps from the page.
- Small hooks marked `[keys]`:
  - `globe.js`: pins carry their lat / lon; `distance`, `tap()` and `tapArtifact()`.
  - `academy/ui.js`: `#aPanel[data-step]`.
  - `mission/ui.js`: the picker's arrows; the `pending` and `highlighted` getters.
  - `mission/cabin.js`: the knob takes Left / Right.
  - `main.js`: the wiring.
  - `desktop/main/main.js`.

## The keys

| Key | Intent on the bus | What it does |
|---|---|---|
| <kbd>←</kbd> <kbd>↑</kbd> <kbd>→</kbd> <kbd>↓</kbd> | `move {dir}` | Moves focus to the nearest control that way. Tab and Shift+Tab still work as always. |
| <kbd>Enter</kbd>, or a tap of <kbd>Space</kbd> | `select` | Presses the focused control. On the Moon, it picks the place under the ring. At the cabin seat, it opens the lit panel. |
| <kbd>Space</kbd> held (≥ 0.26 s) | voice.js push-to-talk | Hold to talk, unchanged. With nothing selectable focused, Space is talk at once, as before. |
| <kbd>Esc</kbd>, <kbd>Backspace</kbd> (when not typing) | `back` | In order: close the help sheet, Settings, About, the calibration, a glossary card, the lesson brief, the answer card (in the cabin, only when focus is on it) or Find it. Then close an open cabin panel (`panel_back`). Then the screen's own back: lesson → map, patch → map, Library → where you were, debrief → cabin or picker. **Never quits.** |
| <kbd>M</kbd> | `mic` | Turns the mic on or off. |
| <kbd>Shift</kbd>+<kbd>M</kbd> | `mute` | The top bar's **Mute** (next to Settings): every sound off or back on. Captions and text stay. Output only; the mic is unchanged. Voice: "mute" / "unmute". |
| <kbd>H</kbd> or <kbd>?</kbd> | `help` | Opens the help sheet with every key for **this** screen, plus the controller's buttons when one is connected. |
| <kbd>1</kbd>–<kbd>4</kbd> (up to <kbd>9</kbd>), and <kbd>A</kbd>–<kbd>D</kbd> | `pick {n}` | Picks an answer. Works on lesson answers, vocab options, order buttons, call-sign chips, site rows, the cabin's offer buttons and the card's buttons. A–D work only while lettered answers are on screen. |
| <kbd>N</kbd> / <kbd>P</kbd> | `next` / `prev` | Next / previous: next step or lesson, the next site, the window view, the panel, the tour stop. |
| <kbd>Y</kbd> / <kbd>N</kbd> | `yes` / `no` | Yes / no to a confirm. **N is "no" only while a yes / no waits**, and "next" otherwise. Y also takes the screen's offer, like saying "yes". |
| <kbd>S</kbd> | `settings` | Opens Settings. |
| <kbd>C</kbd> | `captions` | Turns captions on or off, with a toast. While lettered answers are up, C is answer C. |
| <kbd>R</kbd> | `recenter` | Cabin: **Center view**. The camera goes back to the seat pose (any panel closes, any look offset goes, the window shows the site). Voice: "center", "look forward", "reset view". |
| <kbd>V</kbd> | `view_next` | Cycles the cabin window view: Orbit → Site → Rover → Earth. |
| <kbd>O</kbd> | `panel_open` | Opens the lit cabin panel. |
| <kbd>T</kbd> | `task_step` | Cabin: does the Now panel's step (its button wears a **T**). <kbd>Y</kbd> does too when no yes/no waits. |
| <kbd>1</kbd>–<kbd>4</kbd> | `pick {n}` | Cabin: picks a choice on the Now panel (each option wears its number; the panel also says the word to say, e.g. "Say “left” or “right”"). |
| <kbd>K</kbd> | `time_toggle` | Cabin: pauses or runs the mission clock (docs/GAMEPLAY.md). |
| <kbd>W</kbd> | `time_warp` | Cabin: time warp 1x → 2x → 4x. |
| <kbd>E</kbd> | `skip_event` | Cabin: skip to the next event. |
| <kbd>/</kbd> | `focus_input` | Focuses the text box: the call-sign field on Home, the voice bar's field everywhere else. |
| <kbd>Shift</kbd>+arrows, <kbd>+</kbd> <kbd>−</kbd> | rotate / zoom | On the Moon: turn it, and zoom. |
| <kbd>Alt</kbd>+<kbd>→</kbd>/<kbd>←</kbd>, <kbd>Alt</kbd>+<kbd>Y</kbd>/<kbd>N</kbd>, <kbd>Alt</kbd>+<kbd>.</kbd>, <kbd>Alt</kbd>+<kbd>A</kbd>/<kbd>W</kbd>/<kbd>P</kbd> | (unchanged) | The existing shortcuts: next / prev, yes / no, stop, settings, "where am I", pick a place. The new keys never use a modifier, so the two sets can't collide. |

**Typing.** In a text field, letters, digits, the arrows, <kbd>Backspace</kbd> and <kbd>Enter</kbd> behave as in any
field. **Only <kbd>Esc</kbd> leaves.** It returns focus to where it was before <kbd>/</kbd>, or to the screen's
primary action. <kbd>Tab</kbd> also leaves. The arrows never land on a text field: that would trap them. To type, use
<kbd>/</kbd>, Tab or a click.

**Sliders, knobs and choices.** The rule is the same everywhere. A 1-D control is **directly adjustable**:
<kbd>←</kbd> <kbd>→</kbd> change its value, and <kbd>↑</kbd> <kbd>↓</kbd> leave it. This covers range sliders
(Settings), the shield knob (`role=slider`, also <kbd>PgUp</kbd> / <kbd>PgDn</kbd>), radio rows (Settings) and
`<select>`. There is no "adjust mode" to enter. The Moon is the one 2-D surface: its arrows hop between places, and
past the last place in a direction the arrow leaves the Moon like any other control (§The Moon).

**Exceptions that own their arrows.** These keep their documented behaviour:
- The voice-bar grip moves the bar (docs/ACCESSIBILITY.md).
- The camera self-view grip moves the self-view.
- The site rows: <kbd>↑</kbd> <kbd>↓</kbd> pick the next row. Past the first or last row, or with <kbd>←</kbd> <kbd>→</kbd>, the arrow leaves the list.

The arrows never land on the two grips: Tab reaches them.

## How focus moves (`spatial.js`)

- **Geometry.** The engine works like a TV focus engine:
  - Only controls whose centre lies that way count.
  - It uses the Android TV beam rule. A control straight ahead (overlapping the current one on the other axis) wins when its near edge is closer than the far edge of the nearest off-axis control.
  - Otherwise the score decides: the main-axis gap + 2 × the off-axis gap + a small pull to the centre line.

  The tests cover a 3×3 grid, gaps, rows and the edges.
- **Scopes.** A layer that is open traps the arrows. From the top:
  1. the help sheet;
  2. Settings;
  3. a `<dialog>` (About);
  4. an `aria-modal` dialog (calibration);
  5. a glossary card that has focus;
  6. an **open cabin panel** (the panel plus the Seat button);
  7. the **cabin seat**: the panels, the window views, the alert strip, the comm row and the top bar;
  8. a **lesson card**: the card, the Moon reticle on a Moon step, the site pins of a compare step, and the answer card.

  The **cabin tour** card (first mission, `mission/tour.js`) is a scope too. Next is its primary; Enter or N advances it; ← / → step it (flows.js); the first Esc pauses it (Resume focused, Enter resumes), a second Esc skips it.

  Otherwise the whole screen is one scope, and focus moves **inside the current region first** before it jumps to the nearest control in any region. A control in another region still wins when it is under half the distance. Sheets have regions too: the Settings section list, then the section body. **The top bar is the edge**: it is reached only when nothing on the stage (or in the cabin) lies that way. The regions are the top bar, the Flight School panel, the map pins, the mission panel, the debrief, the answer card, the Library toolbar, the now-playing chip and the voice bar.
- **Memory and restore.** The last focused control is remembered per screen: mode + Academy view + mission screen + cabin panel + scope. It is restored when the kid comes back. When a re-render drops the focused control, focus goes to its twin, found by its id or an identifying data attribute (`data-l`, `data-c`, `data-site`, `data-sec`…). This happens when a pin is picked, after a wrong answer, or when Settings re-renders. On a new screen with nothing remembered, focus goes to the primary action: Next, the first answer, Start, Take command, Fly again, and so on. Restore runs only while the kid uses keys or a controller; a pointer never has its focus moved.
- **Long sheets.** When nothing lies that way inside a scrolling sheet (About, Settings, the debrief), <kbd>↑</kbd> <kbd>↓</kbd> scroll it instead, so what was below comes into reach.
- **Key repeat.** A held arrow moves at most once per 260 / 150 / 80 ms (Slow / Normal / Fast). A fresh press always moves.

### The Moon

The globe has one focusable **reticle** (`#moonFocus`), a ring with a crosshair at the centre of the view. It is
active in the Library and on every lesson step whose answer is a tap on the Moon: `tap`, `intent`, `terminator`,
`route`, `compare` and `globe_side`. It is the primary control on those steps.

| On the reticle | Does |
|---|---|
| <kbd>←</kbd> <kbd>↑</kbd> <kbd>→</kbd> <kbd>↓</kbd> | Hops to the nearest named place that way on screen, within about 50° of the arrow (else about 75°), and within the neighbourhood (30 % of the stage's short side). The globe flies there, keeping its zoom; the place is ringed and named under the reticle, and is announced. Hardware markers count in the Library when the Hardware layer is on. With no place near that way, the arrow **leaves the Moon** to the nearest control (the Library toolbar, the lesson card). Shift+arrows bring far places near. |
| <kbd>Shift</kbd>+arrows / right stick | Turns the Moon freely (about 7° a press), for the terminator, or to find the far side. |
| <kbd>+</kbd> <kbd>−</kbd> | Zoom, on any screen showing the Moon: held, at the camera pinch's rate; a quick tap is one eased step (docs/GESTURES.md §Zoom). |
| <kbd>Enter</kbd> / Space tap / A | Picks what is under the ring: the hopped place (`globe.tap`, or `tapArtifact` for hardware), else the point at the centre of the view. It is graded exactly like a tap. After three misses CAPCOM shows the answer, so a Moon step is never a dead end. |

The **map pins** of the course map are real buttons. The arrows move between them by their screen position (that is,
geographically), and the globe flies to the focused pin (`data-lat` / `data-lon`). The first <kbd>Enter</kbd> picks a
pin, so the card shows that lesson, and the second <kbd>Enter</kbd> starts it.

### The 3D cabin

- **Entering the cabin.** The seat takes focus: the panel the **Now** objective points at (cabin.js `point()`, `.is-point`), else the lit panel, else Displays. Inside a panel opened to answer the objective, its glowing control is focused first.
- **Seat view.** Focus sits on a proxy (`#seatFocus`) that stands over the lit panel and draws its ring. The arrows move across the six console faces (Habitat, Rover, Displays and power, Radiation, Comm, and the pedestal with Caution and warning and End shift). The focused face is lit (`missionUI.intent("highlight_panel")`, the head-look highlight), and the chip says "Enter · open". The arrows also reach the window views, the alert strip's Shelter and Shields buttons, the comm row and the top bar. **Enter** or **O** opens the lit panel.
- **Inside a panel.** The arrows move between the panel's controls. The shield knob turns with <kbd>←</kbd> <kbd>→</kbd>. **N / P** go to the next / previous panel. **Esc** or **Backspace** goes back to the seat, and focus returns to the panel just left. A panel opened by voice, a gesture or a click also pulls focus inside it while keys are in use.

## Gamepad (`gamepad.js`)

The gamepad layer is off until a controller connects. Chromium reports a controller after its first button press.
When one connects, a toast says "Controller connected". Then a rAF poll maps the standard layout (Xbox, PlayStation,
most generic pads) to the same intents. The focus ring and chips switch to `data-input="pad"`, so the chip says "A"
instead of "Enter".

| Control | Intent |
|---|---|
| D-pad, left stick (dead zone 0.5) | `move` (repeats after 380 ms, then at the key-repeat speed) |
| A / Cross | `select` |
| B / Circle | `back` |
| X / Square | `mic` |
| Y / Triangle | `help` |
| LB / RB (L1 / R1) | `prev` / `next` |
| Right stick | Outside the cabin: `spin` (spins the Moon at a rate, with easing and a little momentum: the same rate control as the camera fist, docs/GESTURES.md §Fist spin). In the cabin: `look`, which looks around and lights the aimed panel, the same as the head gesture. |
| Start / Options | `settings` |

**Left-handed controller** (Settings) swaps the sticks.

## Focus you can see from the sofa

While keys or a pad are in use (`html[data-input=keys|pad]`; the first trusted pointer move or click switches back; camera gestures set `gesture` and wear the same ring):
- **The ring.** The focused control grows to 1.04× and wears a two-tone ring, the theme's background then `--color-focus` at `--focus-width`, plus a soft glow and a slow brightness pulse. The two tones mean one always contrasts, on the Moon, on light glass or on the cabin's dark panels. Dark surfaces (the route pins, the cabin, the reticle) use a fixed light-blue variant. The ring uses the `scale` property, so it composes with the pins' own `transform`.
- **Less motion** (Settings, or the OS setting): no grow, no pulse, no transition.
- **High contrast**: a 4 px yellow ring between black rings.
- **Key hints.** A chip next to the focused control names its key: "Enter", "← → adjust", "Esc · leave", "Enter · pick" on the Moon, "Enter · open" on a panel. A corner legend says "Esc Back · / Type · H Help". Pointer use hides all of them.
- **Focus sound** (Settings, off by default): a 30 ms, 880 Hz tick at low volume on each move.

## Settings → Keyboard & controller

The section is registered through `window.__outpost.settingsSections` and listed after Display. It has:
- **Show all keys**, which opens the help sheet;
- **Focus sound**;
- **Key repeat** (Slow / Normal / Fast);
- **Left-handed controller**;
- whether a controller is connected.

The settings are stored on this device in `outpost-keys`.

## Desktop (Electron, `desktop/main/keys.js`)

| | macOS | Windows |
|---|---|---|
| Menu | App (About, Hide, **Quit ⌘Q**), Edit (undo / redo / cut / copy / paste / select all, so the text box keeps them), View (zoom, full screen), Window (Minimize, Zoom). **No Reload, no Dev Tools, no Close (⌘W)**: closing the only window quits the app. | **No menu bar** in a packaged build, so <kbd>Alt</kbd> never opens a menu and Alt+letter mnemonics can't take the page's Alt shortcuts. Quit is the close box or Alt+F4. |
| Blocked in packaged builds (`before-input-event`) | ⌘R, ⇧⌘R, ⌥⌘I / ⌥⌘J, F5, F12, browser back / forward keys | Ctrl+R, Ctrl+Shift+R, Ctrl+Shift+I / J / C, F5, F12, browser back / forward keys |
| Zoom, full screen | View menu: ⌘= / ⌘- / ⌘0, full screen | No menu, so the shell handles them itself (`shellAction`): Ctrl+= / Ctrl+- / Ctrl+0, F11 |
| Dev builds (`npm start`) | Reload and Dev Tools stay in View | A View menu with Reload and Dev Tools |

The page's own keys always pass: the arrows, Enter, Esc, Backspace, Space, letters, `/`, `?`, the Alt shortcuts, and
Cmd / Ctrl + C / V (tested in `desktop/main/keys.test.js`). Chromium no longer goes back on Backspace, so Backspace is
free to be "back" in the app.

## Parity: voice ↔ gesture ↔ key ↔ click

Each row is one action, and every column reaches the same intent or handler. "—" means that device has no sensible
way to do it (a gesture can't spell a call sign). The key column is the new, keyboard-only path; the Alt shortcuts
still work.

| Screen | Action | Voice (say or type) | Gesture (camera on) | Key | Click / tap |
|---|---|---|---|---|---|
| **Everywhere** | Move between controls | — | point (cursor) | arrows, Tab | — |
| | Select | "press *Next*" | point + dwell | Enter, Space tap | click |
| | Back | "go back", "back to my seat" | — (sit back in the cabin) | Esc, Backspace | the Back / × / Map / Seat buttons |
| | Stop speech | (talk over it) | open palm | Space (hold), Alt+. | — |
| | Talk | (hands-free) or hold the mic | — | Space (hold) | hold the mic |
| | Mic on / off | — | — | M | the mic button |
| | Help | "what can I do?" (spoken list) | — | H, ? (sheet) | Settings → Keyboard & controller → Show all keys |
| | Settings | "open settings" | — | S, Alt+A | the gear |
| | Captions | (Settings) | — | C | Settings → Reading & captions |
| | Type | — | — | / | click the field |
| | Where am I | "where am I?" | — | Alt+W | — |
| **Home** | Pick a call sign | "call me Nova", "surprise me" | point at a chip | 1–3, or arrows + Enter | a chip |
| | Type one | — | — | / then type | the field |
| | Start | (saying a name starts) | point at Start | Enter on Start (the primary) | Start |
| **Moon map** | Start the next lesson | "next", "start", "yes" | swipe left, thumbs up | N, Y, Enter on Start | Start |
| | Look at another lesson | "lesson 3", "space words" | point at a pin | arrows over the pins (the globe follows), Enter | a pin |
| | Replay a lesson | "lesson 1" | point at a pin, then Replay | arrows to the pin, Enter, Enter | pin, Replay |
| | Change call sign | — | point at the chip | arrows to the chip, Enter | the chip |
| **Lesson: choice / predict / earth view** | Answer | the answer, "option 2" | point at an answer | 1–4, A–D, arrows + Enter | an answer |
| **Lesson: turn the Moon** | Answer | "show me the far side" | fist and lean (spin), then point at Check | 1 / 2 (near / far), or Shift+arrows on the Moon then Check this view | Near / Far, drag + Check |
| **Lesson: tap / find / terminator / route** | Tap the Moon | name the place | point + dwell on the Moon | Moon reticle: arrows hop, Shift+arrows turn, Enter taps | tap the Moon |
| **Lesson: compare** | Pick a site | name it, "option 1" | point at a card or pin | 1 / 2, arrows to a card or pin | a card or pin |
| **Lesson: keywords / command / vocab say / fill** | Answer | say it | — | / then type, Enter; orders: 1–5 | the order buttons |
| **Lesson: vocab listen / match** | Hear / pick | "option 2" | point | arrows + Enter, digits | the buttons |
| **Lesson** | Brief, Hear it again, Hear the crew | "say that again" | point | arrows + Enter (Esc closes the brief) | the buttons |
| | Next (after a right answer) | "next" | swipe left | Enter (focus is on Next), N | Next |
| | Back to the map | "go back", "map" | — | Esc | Map |
| **Patch earned** | Next lesson / Take command | "next", "yes" | thumbs up, swipe | N, Y, Enter | Next |
| | Map | "map" | — | Esc, or arrows to Map | Map |
| **Check ride** | An order | say it | point at a control | 1–5 (order buttons), / then type | the orders, the cabin controls |
| | Fly it again | "start" | point | Enter on Fly it again | Fly it again |
| **Site picker** | Next / previous site | "pick Malapert" | swipe | N / P, ↑ ↓ on the rows, 1–5 | a row or a pin |
| | Take command | "take command", "yes" | thumbs up | Y, Enter on Take command | Take command |
| **Cabin, seat** | Light a panel | — | turn your head | arrows | hover |
| | Open it | "open the comm panel" | lean in | Enter, O | click the panel |
| | Window view | "show me the rover", "zoom out" | swipe | V, N / P | Orbit / Site / Rover / Earth |
| | Look around | — | head, fist and lean | right stick (pad) | move the mouse |
| **Cabin, panel** | Use a control | the order ("shields to 40") | point + dwell | arrows + Enter; knob ← → | click |
| | Next / previous panel | "open the rover panel" | swipe | N / P | — |
| | Back to the seat | "back to my seat" | sit back | Esc, Backspace | Seat |
| **Storm / alert strip** | Shelter, Shields 40 | "everyone to the shelter", "shields to 40" | point | arrows to the strip, Enter | the buttons |
| **Confirm (risky order)** | Yes / No | "yes" / "no" | thumbs up / down | Y / N (N means no while it waits) | Yes / No |
| **Houston** | Call Houston | "call Houston" | — (raise hand removed: an open hand is always stop) | Comm panel → Call Houston, Enter | Call Houston |
| **End shift** | End shift | "end shift" | — | pedestal → End shift, Enter | End shift |
| | Finish mission | "debrief" | — | pedestal → Finish mission, Enter | Finish mission |
| **Debrief** | Fly again | "fly again", "yes" | thumbs up | Y, Enter on Fly again | Fly again |
| | Another site | "new site" | — | arrows to Another site, Enter | Another site |
| | Close | "go back" | — | Esc, Backspace | × |
| **Library** | Pick a place | "where did Apollo 11 land?" | point at the Moon | Moon reticle: arrows hop, Enter | tap the Moon or a marker |
| | Turn the Moon | "show me the far side" | fist and lean (spin) | Shift+arrows, right stick | drag, Near / Far side |
| | Zoom the Moon | "zoom in", "closer", "zoom out", "farther" | pinch and slide up / down | + / −, RT / LT | scroll / pinch |
| | Tour, next / previous stop | "next" | swipe | Enter on Tour, N / P | Tour, Next |
| | Close the card | — | — | Esc | × |
| | Hear the crew | "play it" | point | arrows to Hear the crew, Enter | Hear the crew |
| **Settings** | Sections, switches, sliders | "bigger text", "high contrast", "slower" | point + dwell | ↑ ↓ move, Enter / Space toggles, ← → change, Esc closes | click |
| **About** | Open / close | — | point | arrows to ⓘ, Enter; Esc | ⓘ, × |
| **Answer card** | Its buttons, Previous | "press Hear the crew" | point | arrows + Enter, 1–n | click |

## Testing

- **Unit** (`npm test`; `tests/spatial.test.js`, 30 tests): the geometry (grid, beam, gaps, edges, Moon cone), scopes, memory and restore (re-render twins, bounded), key repeat, value controls and text fields, the whole key map (modifiers, typing, A–D vs C, Y / N, held keys), the help sheet's rows per screen, screen names, the settings defaults, and the gamepad mapping (D-pad, sticks, lefty, edges, repeat, look and recentre).
- **Desktop** (`cd desktop && npm test`; `main/keys.test.js`): reloads and dev tools are blocked in packaged builds on macOS and Windows; the page's keys always pass; the menus.
- **Keyboard only, end to end** (`tests/e2e/keys_e2e.py`): the full journey of docs/FLOWS.md using only `page.keyboard`. It fails on any trusted pointer event.
- **Controller, end to end** (`tests/e2e/gamepad_e2e.py`): a synthetic `navigator.getGamepads` stub plus a `gamepadconnected` event drive the map, a lesson, the picker and the cabin.

Running the stack:
```
# backend :8397 against the model server :8200, media linked in
ln -s <main checkout>/backend/data/media backend/data/media
cd backend && UV_PROJECT_ENVIRONMENT=<main checkout>/backend/.venv uv run --frozen uvicorn app.main:app --port 8397
cd frontend && npm ci && node tools/fetch_vision.mjs && BACKEND_URL=http://127.0.0.1:8397 npx vite --port 5297 --strictPort
uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/keys_e2e.py --base http://127.0.0.1:5297 --shots docs/img/keys
uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/gamepad_e2e.py --base http://127.0.0.1:5297
```

Results on `rc/2` with the story merge (2026-11-14):
- keys_e2e: 178/178 checks, 0 console errors (full journey, keyboard only, no pointer events);
- gamepad_e2e: 31/31;
- gestures_e2e: 21/21;
- ux_flow: 22/22;
- unit: 117/117;
- desktop: 11/11;
- backend pytest: 746 passed.

Screenshots of the focus states are in `docs/img/keys/`.

## The cabin's deck and Now panel (fix/mission-ui-polish)

- **The deck** is one bar across the top of the cabin. It holds the clock, the clock state (Running 2× / Paused /
  On hold: your choice), Pause/Play, the speed (1× 2× 4×), Skip ahead, the window views and the goals. Each control is
  shown once.
- **Keys.** <kbd>K</kbd> pause/run, <kbd>W</kbd> speed, <kbd>E</kbd> skip. The arrows reach every deck control
  (spatial focus). Space is not the pause key: a tap of Space is *select* and holding it is push-to-talk, so it stays
  free for talking.
- **The Now panel** is docked on the left wall. One focus ring sits on one button at a time: the old glow drew one ring
  round both choices, which looked like a single control. The arrows move between the options. <kbd>Enter</kbd> or a
  tap of <kbd>Space</kbd> presses the focused one. <kbd>1</kbd>–<kbd>4</kbd> pick, and <kbd>T</kbd> does a plain step.
  The fold button (⌃) shrinks the panel to its one line.
- **Controller** (unchanged): View/Share pause/run, RT/R2 skip, LT/L2 speed. The D-pad and A work the Now panel's
  buttons like any other control.
