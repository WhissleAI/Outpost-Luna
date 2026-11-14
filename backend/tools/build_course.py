"""Write backend/data/academy/course.json (Flight School v3, docs/LEARNING_DESIGN.md §5).

The course is authored here as Python so the structure stays readable; the JSON is what the app loads and what
content.check() and tests/test_copy.py validate. Copy budgets: docs/COPY.md §3. Run: uv run python tools/build_course.py
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "academy" / "course.json"
C = "learning/concepts.json"


def src(title, url):
    return {"title": title, "url": url}


S_CONCEPT = {k: v["source"] for k, v in json.loads((OUT.parents[1] / C).read_text())["concepts"].items()}
IAU_SHACK = src("IAU Gazetteer of Planetary Nomenclature: Shackleton", "https://planetarynames.wr.usgs.gov/Feature/5450")
HORIZONS = src("JPL Horizons API", "https://ssd-api.jpl.nasa.gov/doc/horizons.html")
SEP_MAY24 = src("DONKI 2024-05-09T14:25:00-SEP-001 (NASA CCMC)", "https://ccmc.gsfc.nasa.gov/DONKI/view/SEP/30610/-1")
ZHANG = src("Zhang et al. 2020, First measurements of the radiation dose on the lunar surface, Science Advances 6:eaaz1334",
            "https://pmc.ncbi.nlm.nih.gov/articles/PMC7518862/")


def fact(text, frm, source, **kw):
    return {"text": text, "from": frm if isinstance(frm, list) else [frm], "source": source, **kw}


def opt(id_, label, *say, **kw):
    return {"id": id_, "label": label, "say": list(say), **kw}


def step(prompt, accept, success, fail, hint, **kw):
    return {"prompt": prompt, **({k: v for k, v in kw.items() if k in ("capcom", "alert")}), "accept": accept,
            **{k: v for k, v in kw.items() if k not in ("capcom", "alert")},
            "hint": hint, "success": success, "fail": fail}


def clip(clip_id, t0, t1, who, when="before"):
    return {"clip_id": clip_id, "t0": t0, "t1": t1, "who": who, "when": when}


LESSONS = [
    # ---------------------------------------------------------------- 1. the Moon: both sides, Earth in the sky
    {"id": "moon", "title": "Know your Moon", "minutes": 4, "place": "tranquillitatis",
     "badge": {"id": "scout", "name": "Moon Scout", "glyph": "S"},
     "globe": {"lat": 0, "lon": 0, "dist": 3.6},
     "clip": clip("hansen", 0.0, 24.89, "Jeremy Hansen"),
     "brief": "The Moon always shows Earth the same face. Let's explore both sides.",
     "facts": [
         fact("Artemis II flew its crew around the Moon in April 2026. NASA plans the first south-pole landing for "
              "Artemis IV, targeted for 2028.", C, S_CONCEPT["artemis_timeline"]),
         fact("NASA's 2024 list of 9 possible landing regions near the south pole includes Malapert Massif and "
              "de Gerlache Rim 2.", "mission/sites.json", src("NASA Provides Update on Artemis III Moon Landing Regions (Oct 2024)",
              "https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/")),
         fact("The Moon spins once for each trip around Earth, so the same side always faces us.", C,
              S_CONCEPT["tidal_locking"]),
         fact("Shackleton is a crater about 21 km wide and about 4 km deep. The south pole is on its edge.",
              "facts.json", IAU_SHACK),
         fact("Craters that never see the Sun are some of the coldest places measured, near -235 C.", C,
              S_CONCEPT["psr_cold"]),
     ],
     "steps": [
         step("Find where Apollo 11 landed.",
              {"type": "intent", "place": "tranquillitatis"},
              "Copy. The Sea of Tranquility, July 1969.", "Not quite. Try the near side.",
              "Look for a dark patch, right of center.",
              globe={"do": "side", "side": "near"}),
         step("Standing there, could you see Earth in the sky?",
              {"type": "earth_view", "place": "tranquillitatis"},
              "Yes. Earth hangs in the same spot there.", "Not quite. Which side faces Earth?",
              "This is the near side. It faces Earth.",
              globe={"do": "earth", "place": "tranquillitatis"}),
         step("Do people on Earth ever see the Moon's far side?",
              {"type": "predict", "answer": "never",
               "options": [opt("never", "Never", "never", "no"),
                           opt("full", "Only at full Moon", "full moon", "full"),
                           opt("month", "Once a month", "once a month", "month")]},
              "Right. The Moon turns once per trip around Earth.", "Pick one, then we check.",
              "Guess first. Then we'll see.",
              reveal="Never. The Moon turns once per trip around Earth."),
         step("Turn the Moon to show the far side.",
              {"type": "globe_side", "want": "far"},
              "Roger. The far side gets sunlight too.", "Not yet. Keep turning.",
              "Say far side, or tap Far.",
              clip=clip("orientale-basin-ejecta-extent", 1.12, 22.42, "an Artemis II astronaut", "after")),
         step("Now find the south pole, inside the gold ring.",
              {"type": "intent", "place": "shackleton"},
              "Roger. Shackleton crater. Our outpost goes here.", "Not quite. Look at the bottom.",
              "Say south pole, or tap the ring.",
              globe={"do": "pole", "pole": "south"}),
     ]},
    # ---------------------------------------------------------------- 2. Apollo to Artemis (near-side history)
    {"id": "history", "title": "Lessons from Apollo", "minutes": 5, "place": "surveyor3",
     "badge": {"id": "history", "name": "Historian", "glyph": "H"},
     "globe": {"place": "surveyor3", "dist": 2.3},
     "clip": clip("lovell", 4.64, 26.04, "Jim Lovell"),
     "library": {"place": "surveyor3", "label": "Open Surveyor 3"},
     "brief": "Every mission teaches the next. Follow the crews from Apollo to Artemis.",
     "facts": [
         fact("Surveyor 3 sent 6,326 pictures. In 1969 Apollo 12 astronauts walked over and took about 10 kg of parts "
              "home, including its TV camera.", "artifacts.json",
              src("NSSDCA Master Catalog: Surveyor 3", "https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id=1967-035A")),
         fact("John Young and Charlie Duke drove the Apollo 16 rover 26.7 km across the Moon's highlands.",
              "artifacts.json", src("NSSDCA: Apollo Lunar Roving Vehicle", "https://nssdc.gsfc.nasa.gov/planetary/lunar/apollo_lrv.html")),
         fact("Artemis II passed Apollo 13's record of 248,655 miles from Earth on April 6, 2026.", C,
              S_CONCEPT["apollo13_record"]),
         fact("The Artemis II crew proposed the names Integrity and Carroll for two craters. They are not approved yet.",
              C, S_CONCEPT["integrity_name"]),
     ],
     "steps": [
         step("Apollo 11 landed on a mare. What does mare mean?",
              {"type": "vocab_match", "term": "mare", "distractors": ["crater", "highlands"]},
              "Yes. A mare is a plain of old lava.", "Not quite. Look at the dark patch.",
              "The dark patches you can see from Earth.",
              globe={"do": "fly", "place": "tranquillitatis"}),
         step("What did the Apollo 12 crew take home from Surveyor 3?",
              {"type": "choice", "answer": "camera",
               "options": [opt("camera", "Its TV camera", "camera", "tv"), opt("rover", "A rover", "rover"),
                           opt("ice", "A block of ice", "ice")]},
              "Correct. Scientists studied what the Moon did to it.", "Not that one. It took pictures.",
              "Surveyor 3 took 6,326 pictures. With what?",
              globe={"do": "fly", "place": "surveyor3"}),
         step("Apollo 13 went farther from Earth than anyone. Did Artemis II beat it?",
              {"type": "predict", "answer": "yes",
               "options": [opt("yes", "Yes, it went farther", "yes", "farther", "beat"),
                           opt("no", "No, Apollo 13 still holds it", "no", "still", "holds")]},
              "Yes. Artemis II passed it on April 6, 2026.", "Pick one, then we listen.",
              "Guess first. Then hear Houston.",
              reveal="Artemis II passed it on April 6, 2026.",
              clip=clip("apollo13-record", 0.48, 24.98, "Houston", "after")),
         step("The crew named a crater. Trace it: Orientale, then up to Ohm.",
              {"type": "route", "stops": ["orientale", "ohm"], "radius_deg": 10},
              "Roger. Halfway between is their crater, Integrity.", "Not that one. Start at Orientale.",
              "Orientale is the big bullseye. Ohm is north.",
              globe={"do": "side", "side": "far", "lon": -100},
              clip=clip("naming", 40.54, 54.85, "the Artemis II crew", "after")),
         step("Listen to Charlie Duke. Who landed on the Moon with him?",
              {"type": "choice", "answer": "young",
               "options": [opt("young", "John Young", "john", "young"),
                           opt("armstrong", "Neil Armstrong", "neil", "armstrong"),
                           opt("lovell", "Jim Lovell", "jim", "lovell")]},
              "Correct. John Young. They drove 26.7 km.", "Listen again for the name.",
              "He names his partner right away.",
              clip=clip("duke", 5.6, 21.32, "Charlie Duke"),
              globe={"do": "fly", "place": "apollo16_lrv"}),
     ]},
    # ---------------------------------------------------------------- 3. the radio: Earth in the sky
    {"id": "comms", "title": "Talk on the radio", "minutes": 4,
     "place": {"name": "Malapert Massif", "lat": -85.98, "lon": -1.67},
     "badge": {"id": "radio", "name": "Radio Ready", "glyph": "R"},
     "clip": clip("loud-and-clear", 0.4, 21.33, "Artemis II crew and Houston"),
     "brief": "Radio is noisy, so crews keep it short. Copy means I heard you.",
     "facts": [
         fact("Artemis II and Houston really say it: \"Houston, we have you loud and clear.\" ... \"Houston copies "
              "all.\"", "index/clips.json",
              src("NASA Artemis II audio: Houston, We Have You Loud and Clear",
                  "https://www.nasa.gov/wp-content/uploads/2026/01/artemis-ii-houston-we-have-you-loud-and-clear-1.mp3")),
         fact("The Moon is about 384,400 km away, so a radio call takes about 1.3 seconds each way.", C,
              S_CONCEPT["light_time"]),
         fact("In our model of April 2026, Earth was up 93% of the time at Malapert and 45% at Shackleton Rim.",
              "mission/sites.json", HORIZONS),
     ],
     "steps": [
         step("What does \"copy\" mean on the radio?",
              {"type": "choice", "answer": "heard",
               "options": [opt("heard", "I heard you", "heard", "hear", "understood"),
                           opt("write", "Write it down", "write"), opt("again", "Say it again", "again", "repeat")]},
              "Roger. Copy means I heard you.", "Not quite.", "It's about hearing."),
         step("CAPCOM: \"Commander, set the heaters to 40 percent.\" Read it back.",
              {"type": "keywords", "all": [["heater", "heaters"], ["40", "forty"]]},
              "Good readback. Heaters to 40.", "Say again? Repeat the order.", "Repeat what, and how much.",
              capcom="Commander, set the heaters to 40 percent."),
         step("How long does your voice take to reach Earth?",
              {"type": "predict", "answer": "second",
               "options": [opt("second", "About a second", "second", "one second"),
                           opt("minute", "About a minute", "minute"), opt("hour", "About an hour", "hour")]},
              "Right. About 1.3 seconds, at light speed.", "Pick one, then we check.", "Guess first.",
              reveal="About 1.3 seconds. Radio moves at light speed.",
              globe={"do": "earth", "place": "malapert_massif"}),
         step("Which outpost can talk to Earth more often?",
              {"type": "compare", "answer": "malapert_massif", "metric": "earth_days",
               "options": [opt("malapert_massif", "Malapert Massif", "malapert", "mountain"),
                           opt("shackleton_rim", "Shackleton Rim", "shackleton", "rim")]},
              "Malapert. Earth was up 9 of 10 days.", "Not that one. Which faces Earth?",
              "Malapert sits on the side facing Earth.",
              globe={"do": "pair", "places": ["malapert_massif", "shackleton_rim"]}),
         step("Static! You missed the last order. What do you say?",
              {"type": "keywords", "any": [["say again", "repeat", "again", "one more time"]]},
              "Copy. Say again asks for a repeat.", "Ask CAPCOM to repeat it.", "Two words. The second one is again."),
     ]},
    # ---------------------------------------------------------------- 4. sunlight at the pole
    {"id": "power", "title": "Power from the Sun", "minutes": 4, "place": "shackleton",
     "badge": {"id": "sun", "name": "Sun Tracker", "glyph": "P"},
     "globe": {"lat": 0, "lon": 0, "dist": 3.4},
     "clip": clip("features-along-terminator", 47.33, 54.5, "Victor Glover"),
     "brief": "Solar panels need sunlight. At the south pole, the Sun skims the horizon.",
     "facts": [
         fact("Day and night sweep around the Moon once every 29.5 Earth days.", C, S_CONCEPT["lunar_day"]),
         fact("At the pole the Sun never climbs more than about 1.5 degrees above a flat horizon.", C,
              S_CONCEPT["pole_sun"]),
         fact("Averaged over a year, Shackleton's rim gets sunlight about 86% of the time and Malapert about 73%.",
              C, S_CONCEPT["sun_year"]),
         fact("In our model of April 2026, Malapert was in sunlight 35% of the time.", "mission/sites.json", HORIZONS),
         fact("Its longest dark spell in that window lasted 157 hours, more than 6 days.",
              "mission/ephemeris_malapert_massif.json", HORIZONS,
              calc={"kind": "longest_dark_h", "site": "malapert_massif"}),
     ],
     "steps": [
         step("Tap the line where day meets night.",
              {"type": "terminator", "sun_lon": 90, "tol_deg": 12},
              "That's the terminator. It sweeps around monthly.", "Not quite. Find the shadow's edge.",
              "Where the bright part turns dark.",
              globe={"do": "sun", "sun_lon": 90}),
         step("At the south pole, how high does the Sun climb?",
              {"type": "predict", "answer": "low",
               "options": [opt("high", "High overhead", "high", "overhead"),
                           opt("low", "Just above the horizon", "just above", "horizon", "low"),
                           opt("never", "It never rises", "never")]},
              "Right. It skims the horizon all day.", "Pick one, then we check.", "Guess first.",
              reveal="It skims the horizon, never more than about 1.5 degrees up.",
              globe={"do": "pole", "pole": "south"}),
         step("Which site stays sunny for our 10-day mission?",
              {"type": "compare", "answer": "shackleton_rim", "metric": "sun_days",
               "options": [opt("shackleton_rim", "Shackleton Rim", "shackleton", "rim"),
                           opt("malapert_massif", "Malapert Massif", "malapert", "mountain")]},
              "Shackleton Rim. Sun all 10 days in our model.", "Not that one. Check the sun days.",
              "Malapert goes dark early in our mission.",
              globe={"do": "pair", "places": ["shackleton_rim", "malapert_massif"]}),
         step("Night is coming at Malapert. Move power to the heaters so the pipes don't freeze.",
              {"type": "command", "expect": {"type": "allocate", "to": "heaters", "more": True}},
              "Copy. That dark spell lasted 157 hours.", "Negative. The heaters need more power.",
              "Ask for more power to the heaters.",
              globe={"do": "fly", "place": "malapert_massif"}),
     ]},
    # ---------------------------------------------------------------- 5. radiation and storms
    {"id": "radiation", "title": "Radiation and storms", "minutes": 4,
     "place": {"name": "de Gerlache Rim", "lat": -88.71, "lon": -68.7},
     "badge": {"id": "storm", "name": "Storm Watcher", "glyph": "W"},
     "clip": clip("observing-pulsating-streamers-suns", 0.0, 22.6, "an Artemis II astronaut"),
     "brief": "The Sun sometimes throws out fast particles. On the Moon, nothing stops them.",
     "facts": [
         fact("China's Chang'e 4 lander measured 1369 microsieverts a day on the Moon, about 2.6 times the cosmic-ray "
              "dose inside the ISS (523).", "mission/radiation.json", ZHANG),
         fact("In May 2024 a real solar particle storm hit space near Earth and the Moon. Earth also got huge auroras.",
              "mission/donki_events.json", SEP_MAY24),
         fact("After a big flare, particles can arrive in tens of minutes to a few hours.", C, S_CONCEPT["sep_timing"]),
         fact("On Orion, a sensor gives up to 1 hour of warning. The crew hides behind packed bags for up to 24 hours.",
              C, S_CONCEPT["orion_shelter"]),
         fact("Game doses are doubled so storms matter in 10 days. The powered shields are pretend tech.", C,
              S_CONCEPT["game_rules"]),
     ],
     "steps": [
         step("Earth has a magnetic shield and thick air. Does the Moon?",
              {"type": "predict", "answer": "no",
               "options": [opt("yes", "Yes, the Moon does too", "yes", "does"),
                           opt("no", "No, the Moon has neither", "no", "neither", "doesn't")]},
              "Right. Fast particles reach the Moon's ground.", "Pick one, then we check.", "Guess first.",
              reveal="No. Fast particles reach the Moon's ground."),
         step("Houston: particles likely within an hour. When do you shelter?",
              {"type": "choice", "answer": "now",
               "options": [opt("now", "Right now", "now", "right away"), opt("hit", "When it hits", "hits", "when"),
                           opt("never", "Never", "never")]},
              "Right. Get ready before the storm hits.", "Not quite. Particles move fast.",
              "An hour is not long. Act early."),
         step("Alert! A solar particle storm, like the real one in May 2024. Your order?",
              {"type": "command", "expect": {"type": "shelter", "on": True}},
              "Copy. Crew in the shelter. Dose rate way down.", "Say again? Radiation is climbing.",
              "Get the whole crew under cover.", alert=True),
         step("What is an mSv?",
              {"type": "choice", "answer": "dose",
               "options": [opt("dose", "A radiation dose", "dose", "radiation"),
                           opt("rocket", "A kind of rocket", "rocket"), opt("soil", "Moon soil", "soil", "dirt")]},
              "Correct. One mSv is about 10 chest x-rays.", "Not quite. It measures something.",
              "It measures how much radiation you got."),
     ]},
    # ---------------------------------------------------------------- 6. water and ice
    {"id": "life", "title": "Air, water and ice", "minutes": 4, "place": "lcross_centaur_impact",
     "badge": {"id": "ice", "name": "Ice Hunter", "glyph": "I"},
     "globe": {"place": "lcross_centaur_impact", "dist": 2.4},
     "clip": clip("impact-flashes-observing-moons", 0.56, 22.16, "Christina Koch"),
     "brief": "Water is heavy to launch. Ice on the Moon could become water and air.",
     "facts": [
         fact("In 2009 NASA crashed a Centaur rocket stage, about 2,300 kg, into Cabeus crater near the south pole.", C,
              S_CONCEPT["lcross"]),
         fact("The plume held about 155 kg of water, about 5.6% of the soil by mass.", C, S_CONCEPT["lcross"]),
         fact("Shackleton Rim is about 10 km from the middle of Shackleton crater; Malapert is about 130 km away.", C,
              S_CONCEPT["ice_distance"]),
     ],
     "steps": [
         step("Why would NASA crash a rocket into a dark crater?",
              {"type": "predict", "answer": "dig",
               "options": [opt("dig", "To dig up what's buried", "dig", "buried", "ice", "water"),
                           opt("test", "To test a new rocket", "test"),
                           opt("pad", "To make a landing pad", "pad", "landing")]},
              "Right. LCROSS found water in the dust.", "Pick one, then we check.", "Guess first.",
              reveal="To dig up buried stuff. LCROSS found about 155 kg of water."),
         step("Find where the LCROSS rocket hit, near the south pole.",
              {"type": "tap", "place": "lcross_centaur_impact", "also": ["lcross_impact"], "radius_deg": 8},
              "Roger. Cabeus crater, 2009.", "Not there. Look lower.", "Look just above the pole for the marker.",
              globe={"do": "pole", "pole": "south"}),
         step("Which outpost is closer to Shackleton's ice?",
              {"type": "compare", "answer": "shackleton_rim", "metric": "ice_km",
               "options": [opt("shackleton_rim", "Shackleton Rim", "shackleton", "rim"),
                           opt("malapert_massif", "Malapert Massif", "malapert", "mountain")]},
              "The rim, about 10 km. Malapert, about 130.", "Not that one. Look at the map.",
              "The rim sits right on the crater.",
              globe={"do": "pair", "places": ["shackleton_rim", "malapert_massif"]}),
         step("Life support is getting low. Send the rover for ice!",
              {"type": "command", "expect": {"type": "dispatch", "task": "collect_ice"}},
              "Copy. Rover rolling out for ice.", "Negative. The rover needs to fetch ice.",
              "The rover can dig up ice."),
         step("Fill the blank: \"Ice hides in the Moon's dusty soil, the ____.\"",
              {"type": "vocab_fill", "term": "regolith", "sentence": "Ice hides in the Moon's dusty soil, the ____.",
               "distractors": ["albedo", "ejecta"]},
              "Right. Regolith, the Moon's dusty soil.", "Which word means Moon soil?", "It starts with r."),
     ]},
    # ---------------------------------------------------------------- 7. check ride
    {"id": "checkride", "title": "Check ride", "minutes": 5,
     "place": {"name": "Shackleton Rim", "lat": -89.68, "lon": -166.0},
     "badge": {"id": "commander", "name": "Mission Commander", "glyph": "C"},
     "ride": {"site": "shackleton_rim", "seed": 2026, "storm_event": "2024-05-09T14:25:00-SEP-001",
              "start_h": 138, "storm_start_h": 6, "mission_h": 48, "max_missed": 0},
     "brief": "Your check ride: two days at Shackleton Rim. A real particle storm is coming.",
     "facts": [
         fact("The storm in this ride is based on the real solar particle storm of 2024-05-09. Earth also got huge "
              "auroras.", "mission/donki_events.json", SEP_MAY24),
         fact("The ride starts when Earth is above Shackleton Rim's horizon in our April 2026 model, so the radio "
              "works.", "mission/sites.json", HORIZONS),
     ],
     "steps": [
         step("Earth is up over the rim. Can you call Houston now?",
              {"type": "predict", "answer": "yes",
               "options": [opt("yes", "Yes, Earth is up", "yes", "can"),
                           opt("no", "No, never from here", "no", "never")]},
              "Right. Earth is up, so the radio works.", "Pick one, then we check.", "Guess first.",
              reveal="Yes. Earth is up, so the radio works."),
         step("Ask Houston about space weather.",
              {"type": "command", "expect": {"type": "call_houston"}},
              "Copy. Houston sees an active region. Stay sharp.", "Negative. Call Houston.",
              "Say: Houston, any space weather?", advance=1),
         step("Solar particle storm! Based on the real May 2024 storm. Your order?",
              {"type": "command", "expect": {"type": "shelter", "on": True}},
              "Copy. Crew in the shelter.", "Say again? Radiation is climbing.",
              "Get the whole crew under cover.", alert=True, advance="storm"),
         step("The storm has passed. Bring the crew out of the shelter.",
              {"type": "command", "expect": {"type": "shelter", "on": False}},
              "Copy. Crew is out. Back to work.", "Negative. Bring the crew out.",
              "The crew can leave the shelter now."),
         step("Life support is dropping. Send the rover for ice before day 2 ends.",
              {"type": "command", "expect": {"type": "dispatch", "task": "collect_ice"}},
              "Copy. Rover rolling out for ice.", "Negative. The rover needs to fetch ice.",
              "The rover can dig up ice.", advance="end"),
     ]},
]


def build() -> dict:
    return {"_note": "Flight School v3 (docs/LEARNING_DESIGN.md §5): 6 lessons and a check ride, in map order (each "
                     "lesson's `place` is its Moon-map pin). Authored in tools/build_course.py. Every fact cites a "
                     "{title,url} and names the repo data file(s) it comes from (`from`, relative to backend/data); "
                     "tests check every number in a fact appears in those files (or is recomputed, for `calc`). "
                     "Steps accept voice or taps; app/academy/grade.py lists the accept types.",
            "title": "Junior Astronaut Academy", "pass_badge": "commander", "retired_badges": ["words"],
            "lessons": LESSONS}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({len(LESSONS)} lessons, {sum(len(l['steps']) for l in LESSONS)} steps)")
