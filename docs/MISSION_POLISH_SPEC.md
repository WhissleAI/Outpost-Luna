# Mission polish spec: simpler, console-style

Status: proposal for the owner (phase 1, no code changed). Base: `origin/main` b8c17d9 (0.3.1 + #39 flow pause/resume).
Evidence: headless silent playthroughs at 1440×900 and 1600×1000 (light), `frontend/tools/play_mission.py` novice runs,
the slide screenshot run, `docs/GAMEPLAY.md`, `docs/PLAYTEST.md`, `docs/UX_ROUNDS.md`, keys_e2e on main.

## The goal in one line

One clear objective, one primary button (A / Enter / "yes" / thumbs up), everything else one press away and readable
from the sofa.

## Top 10 problems, by impact

1. **The site picker can't be driven by keyboard or controller.** keys_e2e on main stops at "picker: Up reaches the site
   rows" (since #33). The first Mission screen is a dead end without a mouse. P0.
2. **Too many controls at once in the cabin.** First cabin screen: about 45 interactive targets (top nav 3 + 4 icons;
   deck: Play, 1×, 2×, 4×, Skip ahead, Log; views: Orbit, Site, Rover, Earth, Center view; Now card; six consoles with
   Heaters, Science, Shelter, Shields −/+, five (i), Ice, Explore, Home, End shift early, Master alarm, eight caution
   lights, Call Houston; voice bar). Console games show 1–3 actionable prompts. (shot: 04-mission-cabin)
3. **Several voices give instructions at the same moment.** Now card, CAPCOM caption, alert banner, glowing console and
   spoken line can each name a different action. At the storm warning the Now card says "Shelter opens when the rover
   crew is home" while the banner's button says "Set shields to 40", and the clock is held on a decision whose button is
   in the banner, not the Now card. Our automated novice could not find what to press (held:decision, 3 minutes).
4. **The clock is a separate job.** After an order, the player must also find Play in the deck ("Power set. Now press
   Play to start the clock"; the card has no button). Time has five controls (Play/Pause, 1×, 2×, 4×, Skip ahead). The
   pre-#39 novice spent 156 of 331 moments toggling 1×/2× at "All steady. Time warp?". #39 lit only 4×, but the model
   is still "operate a clock" rather than "play".
5. **Text too small to read at TV distance.** Console labels and caution lights are 7–10 px after the 3D projection
   (SHIFT lights "SOLAR STORM", "LOW AIR", "ROVER OUT"; Rover "Parked"; Comm "No signal"; Radiation "Dose / Rate").
   Unreadable at 3 m and on a 1280×720 laptop.
6. **Long road before the fun.** Mission tab → first-mission video offer (yes/no) → site picker (5 presets, 9 numbers per
   site) → Take command → a 12-step cabin tour → "Set your power" → find Play. At least 4 decisions and ~16 presses before
   the outpost does anything.
7. **The picker is a data sheet.** Great for Engineer, heavy as the first screen: presets, weights, a 9-row table per
   site with ranges and source links. A first mission needs "Recommended site → Start", with "Choose a different site"
   behind one press. (shot: 03-mission-site-picker)
8. **A 48-minute mission with no chapters.** HOUR_MS is 12 s, so 10 days = 240 h = 48 min at 1× (12 min at 4×). No
   checkpoint, no "shift complete" beat; the pause menu (#39) has Resume, but no Restart shift / Quit to hub.
9. **Weak feedback.** Success is a CAPCOM text line; gauges change by a few pixels; a storm is a banner. No "objective
   complete" pulse, no shift stars, no takeover for the one moment that matters (shelter the crew).
10. **Rough edges a judge will see.** Why card source line shows an internal path ("Outpost Luna game scale
    (docs/PHYSICS.md)"); Settings › Voice help lines overlap (`.set-help` negative margin, stacked twice); Commander
    first entry timed out waiting for the cabin in the pre-#39 novice run (re-check); the debrief is long text before
    the grade.

## The redesign, screen by screen

Glyphs: Ⓐ = Enter / A / "yes" / thumbs up. Ⓑ = Esc / B / "back" / open hand. Ⓧ = secondary. Ⓨ = info ("why").
LB/RB = previous/next panel. Start = pause menu.

1. **Mission hub** (replaces the first picker screen). One big card: "Mission 1 · Shackleton Rim · 10 days", the
   NASA-recommended site. Ⓐ Start. Ⓧ Choose site (opens the navigator). Ⓨ What's this mission? Video offer becomes a
   small "Watch the 1-min briefing" chip, never a blocking yes/no.
2. **Briefing** (one screen, 3 cards, ≤ 12 words each): Goal "Keep the crew safe for 10 days." · Danger "Solar storms
   and long nights." · Bonus "Bring back ice and science." Ⓐ Take command.
3. **Cabin, teach by doing** (replaces the 12-step tour). First shift shows one prompt at a time, in place:
   "Ⓐ Raise shields to 30" → "Ⓐ Send the rover for ice" → "Hold RT to speed up time". Each lights its one control.
4. **Cabin HUD** (every shift after): see layout below. The objective chip says the ONE next thing; the action bar
   holds the ONE primary action with its glyph. Time runs by itself after an order; hold RT/Space-Shift or say "faster"
   to fast-forward; the clock pauses itself for a decision. 1×/2×/4× and Skip ahead move into the pause menu.
5. **Systems drawer** (LB/RB or "show power"): the six consoles become five big panels, one at a time, labels ≥ 20 px:
   Power, Life support, Radiation, Rover, Radio. Cadet sees Power, Radiation, Rover only; Commander all five; Engineer
   adds numbers and equations. Ⓨ on any gauge opens its Why card.
6. **Event takeover** (storms, low power, rover stuck): the window dims, one card slides up: "Solar storm in 6 h.
   Shelter the crew?" Ⓐ Shelter · Ⓑ Wait. A ring shows game hours left. The decision is the only button on screen.
7. **Shift complete** (end of each of 5 chapters, ~2 days each): stars for Safe · Powered · Science, one line from
   CAPCOM, Ⓐ Next shift. This is the checkpoint: the pause menu offers Restart shift.
8. **Pause menu** (Start / Esc / "pause"): Resume · Restart shift · Time speed · Settings · Quit to hub.
9. **Debrief**: grade + 3 stars first, then 3 highlights (one with its real NASA source), then Ⓐ Next mission ·
   Ⓧ Fly again · Ⓨ The numbers (physics lines from #32).

## HUD layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ ◉ Day 3 · Shift 2          [ Next: Send the rover for ice ]   ☰ Start │  objective chip, 1 line
│                                                                        │
│                        (Moon window, full width)                      │
│                                                                        │
│  ( ⚡ 85 )  ( 💨 80 )  ( ☢ 0.4 )                  LB  Systems  RB      │  3 big rings, ≥ 24 px labels
│ ┌──────────────────────────────────────────────────────────────────┐  │
│ │  Ⓐ  Send the rover for ice            Ⓧ Ask CAPCOM   ⏩ Hold RT  │  │  action bar: one primary
│ └──────────────────────────────────────────────────────────────────┘  │
│  CAPCOM: Rover's ready. Ice is 3 km out.                    🎙 Mic on │  one caption line
└──────────────────────────────────────────────────────────────────────┘
```

Rules: one primary action; one caption line (CAPCOM and the objective never repeat each other); any text ≥ 18 px at
1280×720; the 3D consoles stay as the drawer's art, not as the always-on interface.

## Implementation plan (5 waves, each one PR)

**Wave 1 · Unblock and focus (P0).** Fix keyboard/controller navigation in the site picker (keys_e2e green). One
"primary action" contract: the Now card always carries the decision the clock waits for (banner buttons mirror it, never
replace it). Glyph prompts (Ⓐ/Enter/"yes") on the primary button. Dedupe CAPCOM vs objective text. Fix the Why source
path and the `.set-help` overlap. Risk low. Tests: keys_e2e, flows_e2e, gestures_e2e, answers_e2e, mission_ui overlap,
novice play_mission (target: 0 "confusing", automated player never stuck on a held decision).

**Wave 2 · Time that plays itself.** Auto-run the clock after an order; hold-to-fast-forward (RT / Shift / "faster");
auto-pause on decisions; move 1×/2×/4×/Skip into the pause menu; 5 shift chapters with "Shift complete" and Restart
shift. Sim untouched (strategy/balance tests must stay identical). Risk medium (clock + keys). Tests: clock unit tests,
strategy_sim, play_mission timing (first meaningful action < 20 s after Take command).

**Wave 3 · HUD and Systems drawer.** Objective chip, 3 gauge rings, action bar; consoles behind LB/RB drawer with
level-based disclosure (Cadet 3, Commander 5, Engineer all + numbers); minimum text sizes. Risk medium-high (largest UI
change; Mac and Windows parity on GPU/low graphics). Tests: mission_ui overlaps at 5 sizes incl. 1024×640, a11y, font
floor check (no text < 18 px in the HUD), Windows win_bundle_check + cross-build smoke.

**Wave 4 · Hub, briefing, teach-by-doing.** Mission hub with recommended site (navigator one press away), 3-card
briefing, video offer as a chip, first shift's in-place prompts replace the 12-step tour (tour stays in Help).
Risk low-medium. Tests: picker e2e + navigator checks, flows_e2e, novice playthrough presses-before-first-action ≤ 4.

**Wave 5 · Feedback and debrief.** Event takeover cards, objective-complete pulses (motion, colour; respects reduced
motion), shift stars, debrief stars-first with Next mission. Risk low. Tests: debrief/physics tests, story tests,
screenshot review.

All waves: silent testing, no kid/age wording in public copy, Mac + Windows parity, and the strategy/balance and
Director coverage tests green.

## Decisions for the owner

1. Mission length: keep 10 days at today's pace (48 min at 1×) with 5 chapter checkpoints, or shorten the default (for
   example 12 h → 6 s per game hour, about 24 min)?
2. Cadet default: hide the Systems drawer's advanced panels (Life support, Radio) until Commander?
3. Replace the visible 1×/2×/4×/Skip ahead with auto-time + hold-to-fast-forward (speeds stay in the pause menu)?
4. First mission: start at the recommended site and keep the navigator one press away (yes/no)?
5. Keep the 12-step cabin tour only in Help once teach-by-doing ships?

## Progress

- PR 1 (#69): the Commander stall, no repeated chores, varied jobs with a why.
- PR 2 (#97): autosave and resume, Restart shift, 5 chapters with stars, the pause menu, hold to fast-forward.
- PR 3: one instruction at a time. The Now card carries every decision (the storm, CAPCOM's yes / no, the Director's
  offers); the alert strip has no buttons; decisions dim the cabin around the card with a time-left ring; no repeated
  lines on screen. Details: docs/GAMEPLAY.md §10.
- PR 4: the Mission hub (one mission, Start; the navigator one press away), the 3-card briefing, teach by doing in
  place of the 12-step tour (which stays in Help), the debrief with stars first and Next mission / Fly again always on
  screen, one wording for the storm's orders ("Shields to 40"), the Orbit ↔ seat key trap, and story moments clear
  of the window's markers. Details: docs/GAMEPLAY.md §11.
