"""Write backend/data/academy/course.json (Flight School v3, docs/LEARNING_DESIGN.md §5).

The course is authored here as Python so the structure stays readable; the JSON is what the app loads and what
content.check() and tests/test_copy.py validate. Copy budgets: docs/COPY.md §3. Run: uv run python tools/build_course.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.academy.grade import compare_data  # noqa: E402  (QA-28: compare lines quote the numbers the cards show)
from app.academy.content import VIDEO_HINT  # noqa: E402  (a video step's hint line, docs/MEDIA.md)
from app.academy.content import longest_dark_h  # noqa: E402

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


# One source of truth for the compare steps' numbers: the sim's window days and distances, exactly as the result
# cards show them after the answer (grade.compare_data).
SITES_JSON = {s["id"]: s for s in json.loads((Path(__file__).resolve().parents[1] / "data" / "mission" / "sites.json").read_text())["sites"]}
DARK_H = longest_dark_h("malapert_massif")   # the sim's own rule (real LOLA skyline), app/academy/content.py
SITE = compare_data({"options": [{"id": "malapert_massif"}, {"id": "shackleton_rim"}]})


def num(v) -> str:
    """9.5 -> "9.5", 10.0 -> "10"."""
    return f"{v:g}"


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


def video(media, say, reveal):
    """A NASA video step (docs/MEDIA.md: {type: video, media, say, reveal}; media from backend/data/video/catalog.json):
    CAPCOM asks for a guess (`say`), the kid watches (or skips, or is offline), then CAPCOM says the one-line
    `reveal`. It never blocks. Written out in the shape content.video_step() gives it, so tools that read course.json
    directly see a whole step."""
    return {"type": "video", "media": media, "say": say, "reveal": reveal, "prompt": say,
            "accept": {"type": "video", "media": media}, "hint": VIDEO_HINT, "success": reveal, "fail": VIDEO_HINT}


def prep(id_, title, steps, source, grown_up=False):
    """Mission prep: an optional hands-on job before the lesson, adapted from a NASA activity (credited here, in data,
    never on screen). 3 spoken steps or fewer; the last ends "Tell me when it's ready." (never the trigger word: the
    open mic would hear "done" back). The kid answers Done by voice, a thumbs-up or the button."""
    return {"id": id_, "title": title, "steps": steps, "grown_up": grown_up, "source": source}


LESSONS = [
    # ---------------------------------------------------------------- 1. the Moon: both sides, Earth in the sky
    {"id": "moon", "title": "Know your Moon", "minutes": 4, "place": "tranquillitatis",
     "badge": {"id": "scout", "name": "Moon Scout", "glyph": "S"},
     "globe": {"lat": 0, "lon": 0, "dist": 3.6},
     "clip": clip("hansen", 0.0, 24.89, "Jeremy Hansen"),
     "brief": "Let's explore the Moon, from its big dark plains to the south pole.",
     "facts": [
         fact("Artemis II flew its crew around the Moon in April 2026. NASA plans the first south-pole landing for "
              "Artemis IV, in early 2028.", C, S_CONCEPT["artemis_timeline"]),
         fact("NASA's 2024 list of 9 possible landing regions near the south pole includes Malapert Massif and "
              "de Gerlache Rim 2.", "mission/sites.json", src("NASA Provides Update on Artemis III Moon Landing Regions (Oct 2024)",
              "https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/")),
         fact("The Moon spins once for each trip around Earth, so the same side always faces us.", C,
              S_CONCEPT["tidal_locking"]),
         fact("Shackleton is a crater about 21 km wide and about 4 km deep. The south pole is on its edge.",
              "facts.json", IAU_SHACK),
         fact("Craters that never see the Sun are some of the coldest spots measured: below -246 C.", C,
              S_CONCEPT["psr_cold"]),
         fact("NASA's Moon Base page gives about -203 C inside shadowed craters.", C,
              src("NASA: About the Moon Base", "https://www.nasa.gov/reference/moonbase-about/")),
     ],
     "prep": prep("crater_drop", "Crater drop",
                  ["Pour flour in a pan. Sprinkle cocoa powder on top.",
                   "Drop a marble from up high. See the splash? That's ejecta.",
                   "Look at your crater and its rays. Tell me when it's ready."],
                  src("NASA JPL Education: Make a Moon Crater",
                      "https://www.jpl.nasa.gov/edu/resources/project/make-a-moon-crater/"), grown_up=True),
     "steps": [
         step("Apollo 11 landed on a dark plain of old lava, called a mare. Find the Sea of Tranquility.",
              {"type": "intent", "place": "tranquillitatis"},
              "Copy. The Sea of Tranquility, July 1969.", "Not there.",
              "It's the dark plain right of the middle.",
              do="Tap it on the Moon, or say its name",
              globe={"do": "side", "side": "near"}),
         step("Standing there, could you see Earth in the sky?",
              {"type": "earth_view", "place": "tranquillitatis"},
              "Yes. Earth hangs in the same spot there.", "Not quite.",
              "This side of the Moon always faces Earth.",
              show=["tranquillitatis"], globe={"do": "earth", "place": "tranquillitatis"}),
         video("far_side_view", "We never see the far side from Earth. Does it ever get sunlight? Guess, then watch.",
               "Yes. Far side, not dark side."),
         step("Turn the Moon to show the far side.",
              {"type": "globe_side", "want": "far"},
              "Roger. That's the far side.", "Not yet. Keep turning.",
              "Tap Far, or drag the Moon around.",
              clip=clip("orientale-basin-ejecta-extent", 1.12, 22.42, "an Artemis II astronaut", "after")),
         step("Now find the south pole. It's inside the gold ring.",
              {"type": "intent", "place": "shackleton"},
              "Roger. Shackleton crater. Our outpost goes here.", "Not quite.",
              "Tap inside the gold ring.",
              ring=["shackleton"], globe={"do": "pole", "pole": "south"}),
     ]},
    # ---------------------------------------------------------------- 2. phases and eclipses (NGSS 1-ESS1-1, MS-ESS1-1)
    {"id": "phases", "title": "Phases and eclipses", "minutes": 5, "place": "imbrium",
     "badge": {"id": "watcher", "name": "Moon Watcher", "glyph": "M"},
     "globe": {"lat": 0, "lon": 0, "dist": 3.6},
     "ngss": ["1-ESS1-1", "MS-ESS1-1"],
     "clip": clip("moon-during-eclipse-rare", 65.84, 83.33, "the Artemis II crew"),
     "brief": "The Moon seems to change shape. Let's find out why, then catch an eclipse.",
     "facts": [
         fact("The Sun always lights half of the Moon. As it goes around Earth, we see more or less of that half.",
              C, S_CONCEPT["moon_phases"]),
         fact("Sunrise to sunrise on the Moon takes about 29.5 Earth days, so the phases repeat about every month.", C,
              S_CONCEPT["lunar_day"]),
         fact("In a lunar eclipse, Earth's shadow covers the Moon. It can look reddish.", C,
              S_CONCEPT["lunar_eclipse"]),
         fact("Behind the Moon, the Artemis II crew watched the Moon cover the Sun, with the Sun's glowing corona "
              "around it.", "index/clips.json",
              src("NASA Artemis II audio: Moon During Eclipse",
                  "https://www.nasa.gov/wp-content/uploads/2026/10/art002a000053-part-1-clipped.mp3")),
     ],
     "prep": prep("oreo_phases", "Oreo phases",
                  ["Grab some sandwich cookies. Twist each one open.",
                   "Scrape off filling to make a half Moon.",
                   "Now make a thin crescent and a full Moon. Tell me when it's ready."],
                  src("NASA Space Place: Make Oreo Moon Phases", "https://spaceplace.nasa.gov/oreo-moon/en/")),
     "steps": [
         step("Why does the Moon seem to change shape each month?",
              {"type": "predict", "answer": "sunny",
               "options": [opt("shadow", "Earth's shadow covers it", "shadow", "earth's shadow"),
                           opt("sunny", "We see more or less of its sunny side", "sunny", "sunny side", "more or less"),
                           opt("shrink", "It really shrinks", "shrinks", "shrink", "smaller")]},
              "Right. Half the Moon is always sunny.", "Pick one, then we check.",
              "Guess first. Then we'll watch.",
              reveal="We see more or less of its sunny half. It's not Earth's shadow."),
         video("phases_loop", "Here's a whole month in 15 seconds. Watch the bright part grow, then shrink.",
               "Half is always lit. We see a slice."),
         step("The bright part's edge moves every night. Tap where day meets night.",
              {"type": "terminator", "sun_lon": 45, "tol_deg": 12},
              "That's the terminator. It shapes the phase.", "Not quite. Find the shadow's edge.",
              "Where the bright part turns dark.",
              globe={"do": "sun", "sun_lon": 45}),
         step("Artemis two flew behind the Moon. What did the Moon block for the crew?",
              {"type": "predict", "answer": "sun",
               "options": [opt("sun", "The Sun", "sun"), opt("earth", "Earth", "earth"),
                           opt("stars", "The stars", "stars")]},
              "Right. The Moon hid the Sun.", "Pick one, then we listen.",
              "Guess first. Then hear the crew.",
              reveal="The Sun. The Moon hid it: a solar eclipse.",
              clip=clip("observing-pulsating-streamers-suns", 27.49, 50.78, "an Artemis II astronaut", "after")),
         video("lunar_eclipse", "In a lunar eclipse, what covers the Moon? Guess, then watch.",
               "Yes, Earth's shadow. Phases happen without it."),
     ]},
    # ---------------------------------------------------------------- 3. gravity and dust (NGSS 5-PS2-1)
    {"id": "gravity", "title": "Moon gravity and dust", "minutes": 5, "place": "apollo15_lm_falcon",
     "badge": {"id": "moonwalker", "name": "Moonwalker", "glyph": "G"},
     "globe": {"place": "apollo15_lm_falcon", "dist": 2.3},
     "ngss": ["5-PS2-1"],
     "clip": clip("ohm-crater-ray-systems", 290.0, 306.5, "an Artemis II astronaut"),
     "brief": "Moon gravity and Moon dust both surprise people. Let's test them.",
     "facts": [
         fact("At the end of the last Apollo 15 moonwalk in 1971, Commander David Scott dropped a hammer and a "
              "feather. They hit the ground together.", C, S_CONCEPT["feather_drop"]),
         fact("Gravity on the Moon's surface is 0.165 of Earth's, about one sixth. So 30 kg feels like about 5 kg.",
              C, S_CONCEPT["moon_gravity"]),
         fact("Regolith is the Moon's dusty soil. Its tiny, sharp bits cling to everything.", C,
              S_CONCEPT["regolith"]),
     ],
     "prep": prep("feather_coin", "Feather and coin",
                  ["Crumple one paper into a ball. Keep one paper flat.",
                   "Drop both from the same height. Which lands first?",
                   "Air slows the flat one. The Moon has no air. Tell me when it's ready."],
                  src("NSSDCA: The Apollo 15 Hammer-Feather Drop",
                      "https://nssdc.gsfc.nasa.gov/planetary/lunar/apollo_15_feather_drop.html")),
     "steps": [
         step("On the Moon, drop a hammer and a feather together. Which lands first?",
              {"type": "predict", "answer": "same",
               "options": [opt("feather", "The feather", "feather"), opt("hammer", "The hammer", "hammer"),
                           opt("same", "Both at once", "both", "same time", "together", "at once")]},
              "Good guess. Let's see what Apollo 15 found.", "Pick one, then we watch.",
              "Guess first. Then we'll watch.",
              reveal="Good guess. Let's see what Apollo 15 found."),
         video("hammer_feather", "Commander David Scott tried it on the Moon. Watch closely.",
               "Together. No air slows the feather."),
         step("Your backpack feels like 30 kilos here. How heavy on the Moon?",
              {"type": "choice", "answer": "five",
               "options": [opt("five", "Like 5 kilos", "five", "5"), opt("thirty", "Like 30 kilos", "thirty", "30"),
                           opt("sixty", "Like 60 kilos", "sixty", "60")]},
              "Right. About 5 kilos. One sixth.", "Not that one.",
              "The Moon pulls about one sixth as hard.",
              do="Tap an answer, or say it"),
         video("lunar_dust", "Is Moon dust soft like flour, or sharp? Guess, then watch.",
               "Sharp, like tiny glass. It clings to everything."),
         step("Moon dust has a science name: regolith. Say it out loud: regolith!",
              {"type": "vocab_say", "term": "regolith"},
              "Yes! Regolith, the Moon's dusty soil.", "Say it again.",
              "Say it slowly: reg, oh, lith.",
              do="Say the word out loud"),
     ]},
    # ---------------------------------------------------------------- 4. Apollo to Artemis (near-side history)
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
         fact("On April 6, 2026, Artemis II reached 252,756 miles from Earth, a new record for human spaceflight. It "
              "passed Apollo 13's record of 248,655 miles.", C, S_CONCEPT["artemis2_record"]),
         fact("Artemis III is a 2027 test flight in Earth orbit. Artemis IV, planned for early 2028, is to land two "
              "astronauts near the south pole.", C, S_CONCEPT["artemis_timeline"]),
         fact("NASA plans its Moon Base, humanity's first lunar outpost, near the lunar South Pole. Outpost Luna is a "
              "pretend base.", C, S_CONCEPT["moon_base"]),
         fact("The Artemis II crew proposed the names Integrity and Carroll for two craters. As of November 2026 the IAU "
              "has not approved them.", C, S_CONCEPT["integrity_name"]),
     ],
     "steps": [
         step("Apollo 11 landed on a mare. What does mare mean?",
              {"type": "vocab_match", "term": "mare", "distractors": ["crater", "highlands"]},
              "Yes. A mare is a plain of old lava.", "Not quite.",
              "Look at the dark patch on the Moon.",
              show=["tranquillitatis"], globe={"do": "fly", "place": "tranquillitatis"}),
         step("Robot Surveyor 3 took photos here. Apollo 12 took one part home. Which?",
              {"type": "choice", "answer": "camera",
               "options": [opt("camera", "Its TV camera", "camera", "tv"), opt("rover", "A rover", "rover"),
                           opt("ice", "A block of ice", "ice")]},
              "Correct. Scientists studied what the Moon did to it.", "Not that one.",
              "It took photos. What takes photos?",
              show=["surveyor3"], globe={"do": "fly", "place": "surveyor3"}),
         step("Apollo 13 went farther from Earth than anyone. Did Artemis two beat it?",
              {"type": "predict", "answer": "yes",
               "options": [opt("yes", "Yes, it went farther", "yes", "farther", "beat"),
                           opt("no", "No, Apollo 13 still holds it", "no", "still", "holds")]},
              "Yes. Artemis two went over 250 thousand miles.", "Pick one, then we listen.",
              "Guess first. Then hear Houston.",
              reveal="It did: over 250 thousand miles, in April 2026.",
              clip=clip("apollo13-record", 0.48, 24.98, "Houston", "after")),
         step("Artemis two's crew picked a crater name: Integrity. Tap Orientale Basin, then Ohm.",
              {"type": "route", "stops": ["orientale", "ohm"], "radius_deg": 10},
              "Roger. Integrity sits halfway. Not official yet.", "Not that one.",
              "Orientale Basin is the big bullseye. Ohm is above it.",
              do="Tap the glowing places in order: 1, then 2",
              show=["orientale", "ohm"], after_place="integrity",
              globe={"do": "side", "side": "far", "lon": -100},
              clip=clip("naming", 40.54, 54.85, "the Artemis II crew", "after")),
         step("Listen to Charlie Duke. Who landed on the Moon with him?",
              {"type": "choice", "answer": "young",
               "options": [opt("young", "John Young", "john", "young"),
                           opt("armstrong", "Neil Armstrong", "neil", "armstrong"),
                           opt("lovell", "Jim Lovell", "jim", "lovell")]},
              "Correct. John Young. They drove 26.7 km.", "Not that one.",
              "Tap Hear Charlie Duke. He says the name first.",
              do="Tap Hear Charlie Duke, then pick a name",
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
         fact(f"In our model of April 2026, Earth was up {SITES_JSON['malapert_massif']['earth_visible_pct']}% of the "
              f"time at Malapert and {SITES_JSON['shackleton_rim']['earth_visible_pct']}% at Shackleton Rim.",
              "mission/sites.json", HORIZONS),
     ],
     "steps": [
         step("What does \"copy\" mean on the radio?",
              {"type": "choice", "answer": "heard",
               "options": [opt("heard", "I heard you", "heard", "hear", "understood"),
                           opt("write", "Write it down", "write"), opt("again", "Say it again", "again", "repeat")]},
              "Roger. Copy means I heard you.", "Not that one.", "Copy is about hearing.",
              do="Tap an answer, or say it"),
         step("CAPCOM: \"Commander, set the heaters to 40 percent.\" Say it back.",
              {"type": "keywords", "all": [["heater", "heaters"], ["40", "forty"]]},
              "Good readback. Heaters to 40.", "Say again? Repeat the order.", "Say what to set, and how much.",
              do="Repeat the order out loud, or type it",
              capcom="Commander, set the heaters to 40 percent."),
         step("How long does your voice take to reach Earth?",
              {"type": "predict", "answer": "second",
               "options": [opt("second", "About a second", "second", "one second"),
                           opt("minute", "About a minute", "minute"), opt("hour", "About an hour", "hour")]},
              "Right. About 1.3 seconds, at light speed.", "Pick one, then we check.", "Guess first.",
              reveal="About 1.3 seconds. Radio moves at light speed.",
              globe={"do": "earth", "place": "malapert_massif"}),
         step("Earth hangs over the Moon's near side. Which outpost sees Earth more?",
              {"type": "compare", "answer": "malapert_massif", "metric": "earth_days",
               "options": [opt("malapert_massif", "Malapert Massif", "malapert", "mountain"),
                           opt("shackleton_rim", "Shackleton Rim", "shackleton", "rim")]},
              f"Malapert. Earth was up {num(SITE['malapert_massif']['earth_days'])} of 10 days.", "Not that one.",
              "Malapert sits on the side facing Earth.",
              globe={"do": "pair", "places": ["malapert_massif", "shackleton_rim"]}),
         step("Static! You missed the last order. Ask CAPCOM to repeat it, radio style.",
              {"type": "keywords", "any": [["say again", "repeat", "again", "one more time"]]},
              "Copy. Say again asks for a repeat.", "Not quite.", "Radio talk for repeat: two words, ending in again.",
              do="Say it out loud, or type it"),
     ]},
    # ---------------------------------------------------------------- 4. sunlight at the pole
    {"id": "power", "title": "Power from the Sun", "minutes": 4, "place": "shackleton",
     "badge": {"id": "sun", "name": "Sun Tracker", "glyph": "P"},
     "globe": {"lat": 0, "lon": 0, "dist": 3.4},
     "clip": clip("features-along-terminator", 47.33, 54.5, "Victor Glover"),
     "brief": "Solar panels need sunlight. Let's see how the Sun moves at the pole.",
     "facts": [
         fact("Day and night sweep around the Moon once every 29.5 Earth days.", C, S_CONCEPT["lunar_day"]),
         fact("At the pole the Sun never climbs more than about 1.5 degrees above a flat horizon.", C,
              S_CONCEPT["pole_sun"]),
         fact("Averaged over a year, Shackleton's rim gets sunlight about 86% of the time and Malapert about 73%.",
              C, S_CONCEPT["sun_year"]),
         fact(f"In our model of April 2026, Malapert was in sunlight {SITES_JSON['malapert_massif']['window_sunlit_pct']}% "
              "of the time.", "mission/sites.json", HORIZONS),
         fact(f"Its longest dark spell in that window lasted {DARK_H} hours, more than {DARK_H // 24} days.",
              "mission/ephemeris_malapert_massif.json", HORIZONS,
              calc={"kind": "longest_dark_h", "site": "malapert_massif"}),
     ],
     "prep": prep("low_sun", "Low Sun at the pole",
                  ["Put a ball on a chair. Put a lamp on the floor.",
                   "Shine the lamp low across the ball. See the long shadows?",
                   "That's sunlight at the south pole. Tell me when it's ready."],
                  src("NASA SVS: Moon Essentials: Seasons", "https://svs.gsfc.nasa.gov/5229/"), grown_up=True),
     "steps": [
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
              "Shackleton Rim. Sun " + ("all 10 days" if SITE["shackleton_rim"]["sun_days"] >= 10
                                          else f"{num(SITE['shackleton_rim']['sun_days'])} of 10 days") + " in our model.", "Not that one.",
              "Malapert goes dark early in our mission.",
              globe={"do": "pair", "places": ["shackleton_rim", "malapert_massif"]}),
         step("Night is coming at Malapert. Move power to the heaters so the pipes don't freeze.",
              {"type": "command", "expect": {"type": "allocate", "to": "heaters", "more": True}},
              f"Copy. That dark spell lasted {DARK_H} hours.", "Negative.",
              "The heaters need more power. Tap Heaters up.",
              globe={"do": "fly", "place": "malapert_massif"}),
     ]},
    # ---------------------------------------------------------------- 5. radiation and storms
    {"id": "radiation", "title": "Radiation and storms", "minutes": 4,
     "place": {"name": "de Gerlache Rim", "lat": -88.71, "lon": -68.7},
     "badge": {"id": "storm", "name": "Storm Watcher", "glyph": "W"},
     "brief": "The Sun sometimes throws out storms. Let's learn to keep a crew safe.",
     "facts": [
         fact("China's Chang'e 4 lander measured 1369 microsieverts a day on the Moon, about 2.6 times the cosmic-ray "
              "dose inside the ISS, 523 microsieverts a day.", "mission/radiation.json", ZHANG),
         fact("In May 2024 a real solar particle storm hit space near Earth and the Moon. Earth also got huge auroras.",
              "mission/donki_events.json", SEP_MAY24),
         fact("After a big flare, particles can arrive in tens of minutes to a few hours.", C, S_CONCEPT["sep_timing"]),
         fact("On Orion, a sensor gives up to 1 hour of warning. The crew hides behind packed bags for up to 24 hours.",
              C, S_CONCEPT["orion_shelter"]),
         fact("Game doses are doubled so storms matter in 10 days. The powered shields are pretend tech.", C,
              S_CONCEPT["game_rules"]),
         fact("LRO has measured cosmic rays since 2009, with its CRaTER instrument.", C, S_CONCEPT["lro_crater"]),
     ],
     "prep": prep("ray_shield", "Ray shield",
                  ["Shine a flashlight through a book. Then through foil.",
                   "Which blocks more light? Thick, heavy stuff shields best.",
                   "Shields for radiation work a bit like that. Tell me when it's ready."],
                  src("NASA STEM: Ray Shielding Activity", "https://www.nasa.gov/stem-content/ray-shielding-activity/")),
     "steps": [
         video("moon_weather", "No wind, no rain. Is there weather on the Moon? Guess, then watch.",
               "Yes: space weather, fast particles from the Sun."),
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
              "Right. Get ready before the storm hits.", "Not quite.",
              "Particles move fast. An hour is short. Act early."),
         step("Alert! A solar particle storm, like the real one in May 2024. Your order?",
              {"type": "command", "expect": {"type": "shelter", "on": True}},
              "Copy. Crew in the shelter. Dose rate way down.", "Say again? Radiation is climbing.",
              "Get the crew under cover. Tap Into the shelter.", alert=True),
         step("Doctors count radiation in mSv. So what is an mSv?",
              {"type": "choice", "answer": "dose",
               "options": [opt("dose", "A radiation dose", "dose", "radiation"),
                           opt("rocket", "A kind of rocket", "rocket"), opt("soil", "Moon soil", "soil", "dirt")]},
              "Correct. One mSv is about 10 chest x-rays.", "Not quite.",
              "It measures how much radiation you got."),
     ]},
    # ---------------------------------------------------------------- 6. water and ice
    {"id": "life", "title": "Air, water and ice", "minutes": 4, "place": "lcross_centaur_impact",
     "badge": {"id": "ice", "name": "Ice Hunter", "glyph": "I"},
     "globe": {"place": "lcross_centaur_impact", "dist": 2.4},
     "clip": {**clip("impact-flashes-observing-moons", 0.56, 22.16, "Christina Koch"),
              "note": "She says dark side. She means the night side."},
     "brief": "Water is heavy to launch. Let's look for some on the Moon.",
     "facts": [
         fact("In 2009 NASA crashed a Centaur rocket stage, about 2,300 kg, into Cabeus crater near the south pole.", C,
              S_CONCEPT["lcross"]),
         fact("The plume held about 155 kg of water, about 5.6% of the soil by mass.", C, S_CONCEPT["lcross"]),
         fact("Shackleton Rim is about 10 km from the middle of Shackleton crater; Malapert is about 130 km away.", C,
              S_CONCEPT["ice_distance"]),
     ],
     "prep": prep("make_regolith", "Make regolith",
                  ["Put a cracker in a bag. Crush it into crumbs.",
                   "Touch the crumbs. Tiny bits stick to your fingers.",
                   "Regolith, the Moon's dusty soil, clings like that. Tell me when it's ready."],
                  src("NASA: Making Regolith (educator activity)",
                      "https://www.nasa.gov/wp-content/uploads/2012/02/146860main_making_regolith_educator.pdf")),
     "steps": [
         video("psr", "Some craters at the pole never see sunlight. How cold? Guess, then watch.",
               "Among the coldest spots measured. Ice hides there."),
         step("Why would NASA crash a rocket into a dark crater?",
              {"type": "predict", "answer": "dig",
               "options": [opt("dig", "To dig up what's buried", "dig", "buried", "ice", "water"),
                           opt("test", "To test a new rocket", "test"),
                           opt("pad", "To make a landing pad", "pad", "landing")]},
              "Right. Water hid in regolith, the Moon's dust.", "Pick one, then we check.", "Guess first.",
              reveal="To dig up buried stuff. LCROSS found about 155 kg of water."),
         step("The LCROSS rocket hit Cabeus crater, near the south pole. Find it.",
              {"type": "tap", "place": "lcross_centaur_impact", "also": ["lcross_impact"], "radius_deg": 8},
              "Roger. Cabeus crater, 2009.", "Not there.", "It's close to the south pole, in the middle.",
              do="Tap it on the Moon, or say its name",
              globe={"do": "pole", "pole": "south"}),
         step("Ice hides in Shackleton crater. Which outpost is closer to it?",
              {"type": "compare", "answer": "shackleton_rim", "metric": "ice_km",
               "options": [opt("shackleton_rim", "Shackleton Rim", "shackleton", "rim"),
                           opt("malapert_massif", "Malapert Massif", "malapert", "mountain")]},
              f"The rim, about {SITE['shackleton_rim']['ice_km']} km. Malapert, about {SITE['malapert_massif']['ice_km']}.", "Not that one.",
              "Look at the Moon. The rim sits right on the crater.",
              show=["shackleton"], globe={"do": "pair", "places": ["shackleton_rim", "malapert_massif"]}),
         step("Life support is getting low. Send the rover for ice!",
              {"type": "command", "expect": {"type": "dispatch", "task": "collect_ice"}},
              "Copy. Rover rolling out for ice.", "Negative.",
              "The rover can dig up ice. Tap Rover: get ice."),
     ],
     # at the patch: an optional "Ice home" video on the patch screen (never a step; the patch is already earned)
     "patch_video": {"media": "water_extraction", "line": "How could crews get water out of icy dirt?"}},
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


# Map / course order (coordinator, 2026-11-14): the basics first, then the outpost systems, then Apollo, then the ride.
# Owner decision (via the coordinator, 2026-11-14): 6 core lessons before the check ride; "Moon gravity and dust" and
# "Lessons from Apollo" are explorer lessons, unlocked after missions (gravity after the 1st, Apollo after the 2nd).
# The check ride stays the last stop; explorer lessons sit before it in the data but never block it.
ORDER = ["moon", "phases", "power", "comms", "radiation", "life", "gravity", "history", "checkride"]
EXPLORER = {"gravity": 1, "history": 2}     # lesson id -> missions to fly before it unlocks


def build() -> dict:
    return {"_note": "Flight School v4 (docs/LEARNING_DESIGN.md §11): 6 core lessons, the check ride, and 2 explorer "
                     "lessons unlocked after missions (`track`, `unlock_after_missions`), in map order (each "
                     "lesson's `place` is its Moon-map pin). Authored in tools/build_course.py. Every fact cites a "
                     "{title,url} and names the repo data file(s) it comes from (`from`, relative to backend/data); "
                     "tests check every number in a fact appears in those files (or is recomputed, for `calc`). "
                     "Steps accept voice or taps; app/academy/grade.py lists the accept types. A `video` step "
                     "(app/academy/content.py VIDEO_MEDIA) is predict -> watch -> reveal and never blocks; a lesson's "
                     "optional `prep` is a hands-on Mission prep task with its NASA activity source.",
            "title": "Junior Astronaut Academy", "pass_badge": "commander", "retired_badges": ["words"],
            "lessons": [{**l, "track": "explorer" if l["id"] in EXPLORER else "core",
                         **({"unlock_after_missions": EXPLORER[l["id"]]} if l["id"] in EXPLORER else {})}
                        for l in sorted(LESSONS, key=lambda l: ORDER.index(l["id"]))]}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({len(LESSONS)} lessons, {sum(len(l['steps']) for l in LESSONS)} steps)")
