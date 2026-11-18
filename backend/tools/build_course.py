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


def video(media, say, reveal, guess=None):
    """A NASA video step (docs/MEDIA.md: {type: video, media, say, reveal}; media from backend/data/video/catalog.json):
    CAPCOM asks for a guess (`say`), the kid watches (or skips, or is offline), then CAPCOM says the one-line
    `reveal`. It never blocks. Written out in the shape content.video_step() gives it, so tools that read course.json
    directly see a whole step. `guess` = (options, answer): the guess chips a "Guess, then watch" step shows; the
    reply checks the kid's guess against `answer` after the video, or after Skip (novice playtest 2026-11-16 #7)."""
    g = {"guess": {"options": guess[0], "answer": guess[1]}} if guess else {}
    return {"type": "video", "media": media, "say": say, "reveal": reveal, **g, "prompt": say,
            "accept": {"type": "video", "media": media, **g}, "hint": VIDEO_HINT, "success": reveal, "fail": VIDEO_HINT}


def prep(id_, title, steps, source, grown_up=False):
    """Mission prep: an optional hands-on job before the lesson, adapted from a NASA activity (credited here, in data,
    never on screen). 3 spoken steps or fewer; the last ends "Tell me when it's ready." (never the trigger word: the
    open mic would hear "done" back). The kid answers Done by voice, a thumbs-up or the button."""
    return {"id": id_, "title": title, "steps": steps, "grown_up": grown_up, "source": source}


# A real order, the wrong one: say why it isn't the one, then what to do (guide.ladder; never "Say again?", which the
# radio lesson teaches as "I didn't hear you"). Keys: guide.order_key. Novice playtest 2026-11-16 #10.
WRONG_STORM = {"shields": "Shields help a little. The shelter is safer.",
               "heaters": "Heaters fight cold, not radiation.",
               "rover_ice": "Ice can wait. Keep the crew safe.",
               "houston": "Houston agrees: get under cover.",
               "shelter_out": "Not yet. The storm is coming."}
WRONG_COLD = {"shields": "Shields block radiation, not cold.",
              "shelter_in": "The shelter is for storms.",
              "rover_ice": "The rover can wait.",
              "houston": "Houston can't warm the pipes."}
WRONG_ICE = {"shields": "Shields won't bring water.",
             "heaters": "Heaters won't bring water.",
             "shelter_in": "No storm now.",
             "houston": "Houston agrees: get ice."}


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
              globe={"do": "side", "side": "near"}),
         step("Standing there, could you see Earth in the sky?",
              {"type": "earth_view", "place": "tranquillitatis"},
              "Yes. Earth hangs in the same spot there.", "Not quite.",
              "This side of the Moon always faces Earth.",
              show=["tranquillitatis"], globe={"do": "earth", "place": "tranquillitatis"}),
         video("far_side_view", "We never see the far side from Earth. Does it ever get sunlight? Guess, then watch.",
               "Yes. Far side, not dark side.",
               guess=([opt("yes", "Yes, sometimes", "yes", "sometimes"), opt("no", "No, never", "no", "never")], "yes")),
         step("Turn the Moon to show the far side.",
              {"type": "globe_side", "want": "far"},
              "Roger. That's the far side.", "Not yet. Keep turning.",
              "Tap Far, or drag the Moon around.",
              clip=clip("orientale-basin-ejecta-extent", 1.12, 13.3, "an Artemis II astronaut", "after")),
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
              # the camera faces the terminator (sun_lon - 90), so the edge runs down the middle of the disc: a half
              # Moon, never a full one with the edge on the rim (novice playtest 2026-11-16 #2)
              globe={"do": "sun", "sun_lon": 45, "view_lon": -45}),
         step("Artemis two flew behind the Moon. What did the Moon block for the crew?",
              {"type": "predict", "answer": "sun",
               "options": [opt("sun", "The Sun", "sun"), opt("earth", "Earth", "earth"),
                           opt("stars", "The stars", "stars")]},
              "Right. The Moon hid the Sun.", "Pick one, then we listen.",
              "Guess first. Then hear the crew.",
              reveal="The Sun. The Moon hid it: a solar eclipse.",
              clip=clip("observing-pulsating-streamers-suns", 40.0, 53.2, "an Artemis II astronaut", "after")),
         video("lunar_eclipse", "In a lunar eclipse, what covers the Moon? Guess, then watch.",
               "Earth's shadow. Phases happen without it.",
               guess=([opt("shadow", "Earth's shadow", "shadow", "earth"), opt("cloud", "A big cloud", "cloud"),
                       opt("sun", "The Sun", "sun")], "shadow")),
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
               "Sharp, like tiny glass. It clings to everything.",
               guess=([opt("soft", "Soft like flour", "soft", "flour"), opt("sharp", "Sharp", "sharp")], "sharp")),
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
              "Good readback. Heaters to 40.", "Close. Repeat the whole order.", "Say what to set, and how much.",
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
         step("Pretend you're at Malapert. Night is coming. Move power to the heaters!",
              {"type": "command", "expect": {"type": "allocate", "to": "heaters", "more": True}},
              f"Copy. That dark spell lasted {DARK_H} hours.", "Not that order.",
              "The heaters need more power. Tap Heaters up.",
              wrong=WRONG_COLD,
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
               "Yes: space weather, fast particles from the Sun.",
               guess=([opt("yes", "Yes", "yes"), opt("no", "No", "no")], "yes")),
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
              "Copy. Crew in the shelter. Dose rate way down.", "Radiation is climbing.",
              "Get the crew under cover. Tap Into the shelter.", alert=True, wrong=WRONG_STORM),
         step("Doctors count radiation in mSv. So what is an mSv?",
              {"type": "choice", "answer": "dose",
               "options": [opt("dose", "A radiation dose", "dose", "radiation"),
                           opt("rocket", "A kind of rocket", "rocket"), opt("soil", "Moon soil", "soil", "dirt")]},
              "Correct. One mSv is about 10 chest x-rays.", "Not quite.",
              "It measures how much radiation you got."),
     ]},
    # ---------------------------------------------------------------- 6. water and ice
    {"id": "life", "title": "Air, water and ice", "minutes": 4,
     "place": {"name": "Cabeus crater", "lat": -84.68, "lon": -48.73},   # the word the lesson uses, not the hardware's
     "badge": {"id": "ice", "name": "Ice Hunter", "glyph": "I"},
     "globe": {"lat": -80, "lon": -48.73, "dist": 2.6},
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
               "Among the coldest spots measured. Ice hides there.",
               guess=([opt("freezer", "Cold like a freezer", "freezer"),
                       opt("coldest", "Colder than anywhere on Earth", "colder", "coldest", "anywhere")], "coldest")),
         step("Why would NASA crash a rocket into a dark crater?",
              {"type": "predict", "answer": "dig",
               "options": [opt("dig", "To dig up what's buried", "dig", "buried", "ice", "water"),
                           opt("test", "To test a new rocket", "test"),
                           opt("pad", "To make a landing pad", "pad", "landing")]},
              "Right. Water hid in regolith, the Moon's dust.", "Pick one, then we check.", "Guess first.",
              reveal="To dig up buried stuff. LCROSS found about 155 kg of water."),
         step("The LCROSS rocket hit Cabeus crater, near the south pole. Find Cabeus crater.",
              {"type": "tap", "place": "lcross_centaur_impact", "also": ["lcross_impact", "cabeus"], "radius_deg": 8,
               "label": "Cabeus crater"},
              "Roger. Cabeus crater, 2009.", "Not there.", "It's close to the south pole, in the middle.",
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
              "Copy. Rover rolling out for ice.", "Not that order.",
              "The rover can dig up ice. Tap Rover: get ice.", wrong=WRONG_ICE),
     ],
     # at the patch: an optional "Ice home" video on the patch screen (never a step; the patch is already earned)
     "patch_video": {"media": "water_extraction", "line": "How could crews get water out of icy dirt?"}},
    # ---------------------------------------------------------------- 7. check ride
    {"id": "checkride", "title": "Check ride", "minutes": 5,
     "place": {"name": "Shackleton Rim", "lat": -89.68, "lon": -166.0},
     "badge": {"id": "commander", "name": "Mission Commander", "glyph": "C"},
     "ride": {"site": "shackleton_rim", "seed": 2026, "storm_event": "2024-05-09T14:25:00-SEP-001",
              "start_h": 168, "storm_start_h": 6, "mission_h": 48, "max_missed": 0},
     "brief": "Your check ride: two days at Shackleton Rim. A real particle storm is coming.",
     "facts": [
         fact("The storm in this ride is based on the real solar particle storm of 2024-05-09. Earth also got huge "
              "auroras.", "mission/donki_events.json", SEP_MAY24),
         fact("The ride starts when Earth is above Shackleton Rim's horizon in our April 2026 model, so the radio "
              "works.", "mission/sites.json", HORIZONS),
     ],
     "steps": [
         step("Look: Earth is up over the rim. Can you call Houston now?",
              {"type": "predict", "answer": "yes",
               "options": [opt("yes", "Yes, Earth is up", "yes", "can"),
                           opt("no", "No, never from here", "no", "never")]},
              "Right. Earth is up, so the radio works.", "Pick one, then we check.", "The radio needs Earth in the sky.",
              reveal="Yes. Earth is up, so the radio works.", do="Tap an answer, or say it"),
         step("Ask Houston about space weather.",
              {"type": "command", "expect": {"type": "call_houston"}},
              "Copy. Houston sees an active region. Stay sharp.", "Negative. Call Houston.",
              "Say: Houston, any space weather?", advance=1),
         # [0.4.1] the storm procedure, as flight controllers run it: Houston calls the order, the cadet reads it
         # back, acts on the console (a wrong order still counts as wrong), then confirms
         step("Storm alert! Houston: all crew into the shelter. Read it back.",
              {"type": "sequence", "readback": True, "order": {"type": "shelter", "on": True},
               "items": [opt("crew", "All crew", "all crew", "crew", "everyone", "everybody", "all of us"),
                         opt("shelter", "into the shelter", "shelter", "inside", "under cover")]},
              "Readback correct. Now get them in.", "Read Houston's order back.",
              "Say it back: all crew into the shelter.", alert=True, do="Say it back, or tap the words"),
         step("Get the crew into the shelter.",
              {"type": "command", "expect": {"type": "shelter", "on": True}},
              "Copy. Crew in the shelter.", "Radiation is climbing.",
              "Get the whole crew under cover.", wrong={**WRONG_STORM, "shelter_out": "Wrong way. The storm is here."}),
         step("Tell Houston the crew is inside.",
              {"type": "sequence", "readback": True, "order": {"type": "shelter", "on": True}, "radio": True,
               "items": [opt("in", "In the shelter", "in the shelter", "inside", "sheltered"),
                         opt("copy", "copy", "copy", "copied", "roger")]},
              "Houston copies. Ride it out in there.", "Tell Houston: in the shelter, copy.",
              "Say: in the shelter, copy.", advance="storm", do="Say it, or tap the words"),
         step("The storm has passed. Bring the crew out of the shelter.",
              {"type": "command", "expect": {"type": "shelter", "on": False}},
              "Copy. Crew is out. Back to work.", "Negative. Bring the crew out.",
              "The crew can leave the shelter now."),
         step("Life support is dropping. Send the rover for ice.",
              {"type": "command", "expect": {"type": "dispatch", "task": "collect_ice"}},
              "Copy. Rover rolling out for ice.", "Negative. The rover needs to fetch ice.",
              "The rover can dig up ice.", advance="end"),
     ]},
]

# ---------------------------------------------------------------------------------------------------- Field School
# A second track that opens after the check ride (docs/LEARNING_DESIGN.md §12): observe and describe like the Artemis II
# crew, read craters and lava, name real Apollo rocks, and pick the right sampling tool. Sources: concepts.json
# crew_describe, impact_craters, maria_lava, apollo_samples, sampling_tools, sampling_routine, geology_training.
TOOLS = [opt("rake", "Rake", "rake"), opt("tongs", "Tongs", "tongs", "tong", "grabber", "claw"),
         opt("hammer", "Hammer", "hammer"), opt("scoop", "Scoop", "scoop", "spoon", "shovel"),
         opt("tube", "Drive tube", "drive tube", "tube", "core")]
ROCKS = [opt("basalt", "Basalt: dark lava rock", "basalt", "lava rock"),
         opt("anorthosite", "Anorthosite: light crystals", "anorthosite", "crystals"),
         opt("breccia", "Breccia: bits glued together", "breccia", "glued", "bits")]


def rnd(id_, prompt, answer, hint, yes, **kw):
    return {"id": id_, "prompt": prompt, "answer": answer, "hint": hint, "yes": yes, **kw}


FIELD = [
    # ---------------------------------------------------------------- F1. observe and describe (MS-ESS1-3)
    {"id": "observe", "title": "Eyes of a geologist", "minutes": 4, "place": "copernicus",
     "badge": {"id": "observer", "name": "Moon Observer", "glyph": "O"},
     "globe": {"lat": 5, "lon": -15, "dist": 3.4},
     "ngss": ["MS-ESS1-3"],
     "clip": clip("ohm-crater-ray-systems", 0.88, 22.41, "an Artemis II astronaut"),
     "brief": "The Artemis II crew described the Moon out loud. Let's learn to see like they did.",
     "facts": [
         fact("The Artemis II crew gave spoken and written descriptions of the Moon, guided by a Cue Card.", C,
              S_CONCEPT["crew_describe"]),
         fact("Before the flight, the crew trained on 15 key lunar features, the Lunar Fifteen.", C,
              S_CONCEPT["crew_describe"]),
         fact("NASA's Lunar Log Card asks what features, shapes, colors and shadows you see.", C,
              S_CONCEPT["crew_describe"]),
     ],
     "steps": [
         step("From orbit, can astronauts see colors on the gray Moon?",
              {"type": "predict", "answer": "yes",
               "options": [opt("yes", "Yes, some colors", "yes", "colors", "some"),
                           opt("no", "No, only gray", "no", "only gray", "just gray")]},
              "Right. The crew saw browns and even green.", "Pick one, then we listen.",
              "Guess first. Then hear the crew.",
              reveal="Yes. The crew saw brown, tan, and even green.",
              clip=clip("texture-albedo-across-mare", 35.3, 45.7, "an Artemis II astronaut", "after")),
         step("Fly to Copernicus, a big, sharp crater near the middle.",
              {"type": "intent", "place": "copernicus"},
              "Roger. Copernicus. Now look closely.", "Not there.",
              "Look left of the middle, above the equator.",
              globe={"do": "side", "side": "near"}),
         step("Geologists note size, shape, brightness, texture and shadows. Which is a shape word?",
              {"type": "choice", "answer": "round",
               "options": [opt("round", "Round", "round"), opt("bright", "Bright", "bright"),
                           opt("bumpy", "Bumpy", "bumpy")]},
              "Correct. Round is a shape.", "Not that one.",
              "Bright is light. Bumpy is texture.",
              globe={"do": "fly", "place": "copernicus"}),
         {**step("Now describe Copernicus like the crew. Size, shape, bright or dark, texture, shadows?",
                 {"type": "describe", "need": 3},
                 "That's a real geologist's report.", "Tell me more.",
                 "Is it big or small? Bright or dark?",
                 do="Say what you see, or tap the words",
                 globe={"do": "fly", "place": "copernicus"},
                 clip=clip("using-geology-terms-describe", 47.3, 56.7, "the Artemis II crew", "after")),
          "example": "It's big and round, with bright walls, a bumpy floor and long shadows."},
         step("The crew called one spot \"high albedo\". What does albedo mean?",
              {"type": "vocab_match", "term": "albedo", "distractors": ["crater", "regolith"]},
              "Yes. Albedo is how bright a surface is.", "Not quite.",
              "Think bright or dark."),
     ]},
    # ---------------------------------------------------------------- F2. impacts, lava, superposition (HS-ESS1-6)
    {"id": "craters", "title": "Craters and lava", "minutes": 5, "place": "tycho",
     "badge": {"id": "lava", "name": "Lava Tracker", "glyph": "L"},
     "globe": {"lat": -20, "lon": -12, "dist": 3.4},
     "ngss": ["MS-ESS1-3", "HS-ESS1-6"],
     "clip": clip("crew-choice-irregular-crater", 69.0, 92.9, "an Artemis II astronaut"),
     "brief": "One astronaut said a crater looked like a volcano. Let's find out what really made it.",
     "facts": [
         fact("Impact craters are left when an asteroid, meteoroid or comet hits the Moon.", C,
              S_CONCEPT["impact_craters"]),
         fact("The spray of broken rock is ejecta. Plumes of ejecta settle back as bright rays.", C,
              S_CONCEPT["impact_craters"]),
         fact("Tycho is about 85 km wide and 110 million years old: young, for the Moon.", C,
              S_CONCEPT["impact_craters"]),
         fact("The dark maria are cooled lava that flooded giant impact basins, between 4.2 and 1.2 billion years "
              "ago.", C, S_CONCEPT["maria_lava"]),
     ],
     "steps": [
         step("What made the Moon's round craters?",
              {"type": "predict", "answer": "impact",
               "options": [opt("impact", "Space rocks hitting it", "space rocks", "rocks", "hitting", "asteroids",
                               "meteors", "impact"),
                           opt("volcano", "Volcanoes erupting", "volcano", "volcanoes", "erupting"),
                           opt("quake", "Moonquakes", "moonquake", "moonquakes", "quake")]},
              "Right. Each crater is an old impact.", "Pick one, then we check.", "Guess first.",
              reveal="Space rocks. A crater is an impact, not a volcano."),
         step("Find Tycho. Look for bright rays, like a splash.",
              {"type": "intent", "place": "tycho"},
              "Roger. Tycho's rays are splashed rock: ejecta.", "Not there.",
              "It's low on the Moon, with bright streaks.",
              globe={"do": "side", "side": "near"}),
         step("The dark maria are named seas. What are they really?",
              {"type": "choice", "answer": "lava",
               "options": [opt("lava", "Old cooled lava", "lava", "cooled"), opt("water", "Dried-up water", "water", "dried"),
                           opt("shadow", "Deep shadows", "shadow", "shadows")]},
              "Correct. Cooled lava, never water.", "Not that one.",
              "They were hot and runny once.",
              show=["imbrium"], globe={"do": "fly", "place": "imbrium"}),
         step("Lava flooded the giant Imbrium basin. Which came first?",
              {"type": "predict", "answer": "basin",
               "options": [opt("basin", "The basin", "basin", "hole", "crater"),
                           opt("lava", "The lava", "lava")]},
              "Right. The basin first, then the lava.", "Pick one, then we check.", "Guess first.",
              reveal="The basin. Lava can only fill a hole that's there.",
              globe={"do": "fly", "place": "imbrium"},
              clip=clip("orientale-basin-ejecta-extent", 32.2, 42.3, "an Artemis II astronaut", "after")),
         step("Tycho's rays lie on top of older ground. Is Tycho young or old?",
              {"type": "choice", "answer": "young",
               "options": [opt("young", "Young, for the Moon", "young", "new", "newer"),
                           opt("old", "Old as the Moon", "old", "older")]},
              "Correct. About 110 million years: young!", "Not that one.",
              "What's on top came later.",
              globe={"do": "fly", "place": "tycho"}),
     ]},
    # ---------------------------------------------------------------- F3. Apollo rocks tell time (HS-ESS1-6)
    {"id": "rocks", "title": "Moon rocks tell time", "minutes": 5, "place": "apollo16_lm_orion",
     "badge": {"id": "rockhound", "name": "Rock Hound", "glyph": "B"},
     "globe": {"place": "apollo16_lm_orion", "dist": 2.6},
     "ngss": ["HS-ESS1-6"],
     "clip": clip("whole-moon-imaging-orientale", 211.3, 222.4, "an Artemis II astronaut"),
     "brief": "Apollo crews brought rocks home. Each one tells part of the Moon's story.",
     "facts": [
         fact("The bright highlands are older crust. The dark maria came later, as lava.", C, S_CONCEPT["maria_lava"]),
         fact("Sample 60025, an anorthosite, is about 4.4 billion years old: a piece of the Moon's first crust.", C,
              S_CONCEPT["apollo_samples"]),
         fact("Sample 15016, a basalt, is 3.4 billion years old. About half of it is holes left by gas bubbles.", C,
              S_CONCEPT["apollo_samples"]),
         fact("Sample 79115 is a breccia: soil and rock bits glued together by impacts. Apollo 17 broke it off a "
              "boulder.", C, S_CONCEPT["apollo_samples"]),
     ],
     "steps": [
         step("Bright highlands or dark maria: which is older?",
              {"type": "predict", "answer": "highlands",
               "options": [opt("highlands", "The bright highlands", "highlands", "bright"),
                           opt("maria", "The dark maria", "maria", "mare", "dark")]},
              "Right. The highlands are older crust.", "Pick one, then we check.", "Guess first.",
              reveal="The highlands. Bright doesn't always mean young."),
         step("Real Apollo rocks! Name each kind.",
              {"type": "rounds", "options": ROCKS,
               "rounds": [rnd("r15016", "Rock 1: dark, full of little holes. Which kind?", "basalt",
                              "The holes were gas bubbles in lava.", "Yes, basalt. Lava with gas bubbles.",
                              rock="15016", clue="Sample 15016, Apollo 15: dark, with holes"),
                          rnd("r60025", "Rock 2: pale, made of light crystals. Which kind?", "anorthosite",
                              "Light crystals floated up long ago.", "Yes, anorthosite. The Moon's first crust.",
                              rock="60025", clue="Sample 60025, Apollo 16: pale crystals"),
                          rnd("r79115", "Rock 3: broken bits stuck together. Which kind?", "breccia",
                              "Impacts glued the bits together.", "Yes, breccia.",
                              rock="79115", clue="Sample 79115, Apollo 17: bits glued together")]},
              "Roger. Three real Moon rocks named.", "Look again.",
              "Read the clue under the rock.",
              do="Turn the rock, then tap its kind"),
         step("Light anorthosite crystals floated up long ago. What did they make?",
              {"type": "choice", "answer": "highlands",
               "options": [opt("highlands", "The bright highlands", "highlands", "bright"),
                           opt("maria", "The dark maria", "maria", "mare", "dark"),
                           opt("rays", "Tycho's rays", "rays", "tycho")]},
              "Correct. The Moon's first crust.", "Not that one.",
              "Light rock makes bright ground."),
         step("Basalt 15016 is 3.4 billion years old. Is anorthosite 60025 older or younger?",
              {"type": "predict", "answer": "older",
               "options": [opt("older", "Older", "older", "old"), opt("younger", "Younger", "younger", "young")]},
              "Right. About 4.4 billion years old.", "Pick one, then we check.", "Guess first.",
              reveal="Older: about 4.4 billion years. The highlands came first."),
         step("Apollo 16 found rock 60025 in the bright highlands. Find Apollo 16.",
              {"type": "tap", "place": "apollo16_lm_orion", "radius_deg": 8, "label": "Apollo 16"},
              "Roger. Apollo 16, in the highlands.", "Not there.",
              "It's just right of the middle.",
              globe={"do": "side", "side": "near"}),
     ]},
    # ---------------------------------------------------------------- F4. the field kit and the station routine
    {"id": "fieldkit", "title": "Field kit", "minutes": 4, "place": "shackleton_rim",
     "badge": {"id": "fieldkit", "name": "Field Ready", "glyph": "F"},
     "ngss": ["MS-ESS1-3", "3-5-ETS1-1"],
     "photo": {"id": "geology_iceland_2026", "alt": "Astronaut Zena Cardman trains with NASA geologists in Iceland's Moon-like lava fields.",
               "credit": "NASA/James Blair", "source": S_CONCEPT["geology_training"]},
     "brief": "Astronauts practice field geology on Earth. Let's pack your kit for the south pole.",
     "facts": [
         fact("In July 2026 astronaut Zena Cardman trained with NASA geologists in Iceland's Moon-like lava fields.",
              C, S_CONCEPT["geology_training"]),
         fact("NASA's first Artemis geology tools include a hammer, a rake, a scoop, tongs, a drive tube and sample "
              "bags.", C, S_CONCEPT["sampling_tools"]),
         fact("On Apollo, tongs picked up small rocks and the rake gathered many small rocks at once.", C,
              S_CONCEPT["sampling_tools"]),
         fact("Apollo crews bagged each sample, took pictures after, and told Houston which numbered bag it was in.",
              C, S_CONCEPT["sampling_routine"]),
     ],
     "steps": [
         step("Moon geologists carry a rake. What is it for?",
              {"type": "predict", "answer": "pebbles",
               "options": [opt("pebbles", "Gathering lots of small rocks", "small rocks", "pebbles", "gathering"),
                           opt("smooth", "Smoothing out footprints", "smoothing", "footprints"),
                           opt("dig", "Digging a deep hole", "digging", "deep hole")]},
              "Right. It gathers many small rocks.", "Pick one, then we check.", "Guess first.",
              reveal="It gathers lots of small rocks at once."),
         step("Pick the right tool for each job.",
              {"type": "rounds", "options": TOOLS,
               "rounds": [rnd("pebbles", "Lots of loose pebbles. Which tool?", "rake",
                              "It gathers many small rocks at once.", "Yes, the rake."),
                          rnd("rock", "One rock the size of your fist. Which tool?", "tongs",
                              "It grabs one rock, like a claw.", "Yes, tongs."),
                          rnd("chip", "A chip off a big boulder. Which tool?", "hammer",
                              "You need to knock a piece off.", "Yes, the hammer."),
                          rnd("soil", "Fine soil and dust. Which tool?", "scoop",
                              "Dig it up, like a big spoon.", "Yes, the scoop."),
                          rnd("layers", "The soil's layers, top to bottom. Which tool?", "tube",
                              "A tube pushed down keeps the layers.", "Yes, the drive tube.")]},
              "Roger. Your field kit is packed.", "Try another tool.",
              "Think about what each tool does.",
              do="Say a tool, or tap it"),
         step("Why does each sample get its own numbered bag?",
              {"type": "choice", "answer": "where",
               "options": [opt("where", "To know where it came from", "where", "came from", "know"),
                           opt("warm", "To keep it warm", "warm"), opt("light", "To make it lighter", "lighter")]},
              "Correct. Houston logs every bag.", "Not that one.",
              "Scientists need to know the spot."),
         step("CAPCOM: \"Photo, describe, sample, bag, call it in.\" Read back the station order.",
              {"type": "sequence",
               "items": [opt("photo", "Photo", "photo", "picture", "camera"),
                         opt("describe", "Describe", "describe", "description"),
                         opt("sample", "Sample", "sample", "grab", "collect"),
                         opt("bag", "Bag", "bag"),
                         opt("report", "Call it in", "call it in", "call", "report", "houston", "radio")]},
              "Good readback. That's a geology station.", "Not that order.",
              "Start with the camera. End with the radio.",
              do="Say them in order, or tap them"),
     ]},
]
LESSONS += FIELD


# Map / course order (coordinator, 2026-11-14): the basics first, then the outpost systems, then Apollo, then the ride.
# Owner decision (via the coordinator, 2026-11-14): 6 core lessons before the check ride; "Moon gravity and dust" and
# "Lessons from Apollo" are explorer lessons, unlocked after missions (gravity after the 1st, Apollo after the 2nd).
# The check ride stays the last stop; explorer lessons sit before it in the data but never block it.
# Field School (owner brief 2026-11-17) sits after the explorer lessons, before the ride in the data, like them: the
# check ride stays the last stop on the map, and Field School opens once it is flown (unlock_after: "checkride").
ORDER = ["moon", "phases", "power", "comms", "radiation", "life", "gravity", "history",
         "observe", "craters", "rocks", "fieldkit", "checkride"]
FIELD_IDS = [l["id"] for l in FIELD]   # Field School: a second track after the check ride (unlock_after: "checkride")
EXPLORER = {"gravity": 1, "history": 0}     # lesson id -> missions to fly before it unlocks
# Novice playtest 2026-11-16 #22: "Lessons from Apollo" (the trace step) waited for a second mission, out of reach in a
# new kid's first hour. It opens after the check ride instead (`unlock_after: "checkride"`).
UNLOCK_AFTER = {"history": "checkride"}


def build() -> dict:
    return {"_note": "Flight School v4 (docs/LEARNING_DESIGN.md §11): 6 core lessons, the check ride, and 2 explorer "
                     "lessons unlocked after missions (`track`, `unlock_after_missions`), then Field School (track `field`: 4 "
                     "geology lessons that open after the check ride, docs/LEARNING_DESIGN.md §12), in map order (each "
                     "lesson's `place` is its Moon-map pin). Authored in tools/build_course.py. Every fact cites a "
                     "{title,url} and names the repo data file(s) it comes from (`from`, relative to backend/data); "
                     "tests check every number in a fact appears in those files (or is recomputed, for `calc`). "
                     "Steps accept voice or taps; app/academy/grade.py lists the accept types. A `video` step "
                     "(app/academy/content.py VIDEO_MEDIA) is predict -> watch -> reveal and never blocks; a lesson's "
                     "optional `prep` is a hands-on Mission prep task with its NASA activity source.",
            "title": "Junior Astronaut Academy", "pass_badge": "commander", "retired_badges": ["words"],
            "lessons": [{**l, "track": "field" if l["id"] in FIELD_IDS else "explorer" if l["id"] in EXPLORER else "core",
                         **({"unlock_after": "checkride"} if l["id"] in FIELD_IDS else {}),
                         **({"unlock_after_missions": EXPLORER[l["id"]]} if EXPLORER.get(l["id"]) else {}),
                         **({"unlock_after": UNLOCK_AFTER[l["id"]]} if l["id"] in UNLOCK_AFTER else {})}
                        for l in sorted(LESSONS, key=lambda l: ORDER.index(l["id"]))]}


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {OUT} ({len(LESSONS)} lessons, {sum(len(l['steps']) for l in LESSONS)} steps)")
