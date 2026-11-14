"""The ear's context lists, per screen and per step (round 7, docs/LOCAL_EAR.md "Contextual biasing").

We know the vocabulary of every place in the app, so the Arc ear gets RICH lists (Arc handles long lists: the bias
prefix tree has no token budget), weighted by context:

  step    the strongest boost: what the open step / offer / screen action expects right now (the step's options and
          their say words, keywords, places, the side or day-night words, the base parts of a command step, the space
          word; the offer's takers; the cabin's orders and panels; the site names on the picker; the call signs)
  screen  a lighter boost: the screen-wide vocabulary (the whole gazetteer and the hardware on the Moon / library
          screens, the lesson's own vocabulary, the glossary, the crew, the mission orders, the sites, the nav / help
          phrases)

The vocabulary is DATA built from the app's own JSON (places.json, artifacts.json, glossary.json, academy/course.json,
mission/sites.json, the call-sign presets, the router's nav / offer / help phrases), versioned by a hash of those
files (`vocab()["v"]`), so the lists follow the course as it changes. The session builds the lists from its screen
frame (session.hot_words), /ws/listen sends them to the ear ({"t":"context","hot":{"v","step","screen"}}), and the
Director sees which list a turn's words matched and how strongly (hot_match; features hot_*).
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
MAX_STEP = 48
SCHEMA = 4                   # bump when the way the lists are built changes (it is part of the version)
MAX_SCREEN = 260
MAX_NAMES = 320               # the Moon screens and the picker: every place, crew member and piece of hardware

OFFER_WORDS = {"next_lesson": ["next", "yes", "next lesson"], "next_step": ["next", "yes", "next one"],
               "mission": ["take command", "yes", "go to mission"], "take_command": ["take command", "yes"],
               "fly_again": ["fly again", "yes", "another site"], "tour": ["next", "skip tour"]}
PANELS = ["power panel", "comm panel", "comms panel", "habitat panel", "rover panel", "radiation panel",
          "back to my seat", "close the panel"]
# The cabin's strong tier holds the NOUNS of the orders (what is misheard); the generic order words ("turn", "more",
# "percent") stay on the screen tier, so the decoder is never pushed to start a turn with "Turn" or end it with them.
ORDERS = ["shields", "radiation shields", "heaters", "life support", "oxygen", "greenhouse", "science", "rover", "comms",
          "radio", "ice", "water", "shelter", "end shift", "Houston", "solar panels", "repair the array", "explore"]
ORDER_WORDS = ["come back", "percent", "more power", "less power", "status report", "a little more", "turn off",
               "turn on"]
NAV = ["next", "start", "go back", "go to the map", "patch map", "go to mission", "take command", "library", "academy",
       "flight school", "debrief", "fly again", "another site", "zoom out", "show me the rover", "settings",
       "say that again", "slower", "faster", "skip tour", "show me around"]
HELP = ["help", "what do I do", "what can I say", "where am I", "I'm stuck", "give me a hint", "voice bar",
        "move the voice bar", "reset the voice bar"]
CALLSIGNS = ["Comet", "Nova", "Rocket", "Orbit", "Moon Moth", "Crater Cat", "Star Hopper", "Sky Otter", "Pulsar",
             "Moonbeam", "Rover Fox", "Stardust"]           # session.CALLSIGNS (frontend story.js)
CREW_NOW = ["Reid Wiseman", "Victor Glover", "Christina Koch", "Jeremy Hansen", "CAPCOM", "Houston"]
SOURCES = ["places.json", "artifacts.json", "glossary.json", "academy/course.json", "mission/sites.json"]
MOON_SCREENS = ("library", "map", "patch", "lesson_done")


def _clean(w) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*\(.*?\)", "", str(w or ""))).strip()


def _person(n: str) -> list[str]:
    """'Edwin E. "Buzz" Aldrin Jr.' -> ['Buzz Aldrin', 'Edwin Aldrin', 'Aldrin']."""
    nick = re.findall(r'"([^"]+)"', n)
    ws = [w for w in re.sub(r'"[^"]+"', " ", n).replace(",", " ").split()
          if not re.fullmatch(r"[A-Z]\.|Jr\.?|Sr\.?|II|III", w)]
    if not ws:
        return []
    last = ws[-1]
    out = [f"{nick[0]} {last}"] if nick else []
    return out + [f"{ws[0]} {last}" if len(ws) > 1 else last, last]


def _dedupe(xs, cap: int) -> list[str]:
    seen, out = set(), []
    for w in xs:
        w = _clean(w)
        k = w.lower()
        if w and len(k) >= 2 and k not in seen:
            seen.add(k)
            out.append(w)
    return out[:cap]


VOCAB_FILE = DATA / "ear_vocab.json"    # the versioned lists (bundled with backend/data in the Mac + Windows apps)


def source_hash() -> str:
    h = hashlib.sha1()
    for f in SOURCES:
        p = DATA / f
        h.update(p.read_bytes() if p.exists() else b"")
    h.update(json.dumps([SCHEMA, ORDERS, ORDER_WORDS, PANELS, NAV, HELP, CALLSIGNS, CREW_NOW]).encode())   # + the lists kept here
    return h.hexdigest()[:12]


@lru_cache(maxsize=1)
def vocab() -> dict:
    """Every vocabulary list. The committed data file (data/ear_vocab.json, `python -m app.hotlist build`) when its
    version matches the sources' hash; otherwise rebuilt from the JSON (the lists always follow the course)."""
    v = source_hash()
    try:
        d = json.loads(VOCAB_FILE.read_text())
        if d.get("v") == v:
            return d
    except Exception:  # noqa: BLE001
        pass
    return build_vocab()


def build_vocab() -> dict:
    """The lists from places.json, artifacts.json, glossary.json, academy/course.json and mission/sites.json."""
    h = source_hash()
    raw_places = json.loads((DATA / "places.json").read_text())
    feats = raw_places if isinstance(raw_places, list) else raw_places.get("places") or raw_places.get("features") or []
    from .keyterms import PROPER_ALIASES, TITLE_NAMES, ARC_PLACES
    places = list(ARC_PLACES)
    for p in feats:
        if isinstance(p, dict) and p.get("name"):
            places.append(p["name"])
            places += [a.title() for a in p.get("aliases") or [] if a in PROPER_ALIASES]
    places += TITLE_NAMES
    arts = json.loads((DATA / "artifacts.json").read_text()) if (DATA / "artifacts.json").exists() else []
    hardware, crew = [], list(CREW_NOW)
    for a in arts:
        hardware += [a.get("name"), a.get("mission")] + [x for x in a.get("aliases") or [] if x and x[:1].isupper()]
        for c in a.get("crew") or []:
            crew += _person(c)
    from .keyterms import ARC_HARDWARE, HARDWARE, JARGON
    hardware = ARC_HARDWARE + HARDWARE + hardware
    gl = json.loads((DATA / "glossary.json").read_text()).get("terms") or {}
    glossary = list(gl) + JARGON
    sites = []
    try:
        from .mission import sim
        sites = [s["name"] for s in sim.sites()]
    except Exception:  # noqa: BLE001
        pass
    lessons, course_words = {}, []
    try:
        from .academy import content
        from .academy.grade import step_vocab
        for L in content.course()["lessons"]:
            ws = [L["title"]]
            for st in L["steps"]:
                ws += _bias_words(step_vocab(st, aliases=False))
            lessons[L["id"]] = _dedupe(ws, 120)
            course_words += ws
    except Exception:  # noqa: BLE001
        pass
    return {"v": h, "places": _dedupe(places, 200), "hardware": _dedupe(hardware, 160),
            "crew": _dedupe(crew, 80), "glossary": _dedupe(glossary, 80), "sites": _dedupe(sites, 20),
            "lessons": lessons, "course": _dedupe(course_words, 300), "orders": ORDERS, "panels": PANELS,
            "nav": NAV, "help": HELP, "callsigns": CALLSIGNS,
            "lesson_titles": [L for L in lessons]}


def hot_lists(frame: dict | None, step: dict | None = None) -> dict:
    """{"v", "step": [...], "screen": [...]} for this screen frame (and its open course step)."""
    V = vocab()
    fr = frame or {}
    screen = fr.get("screen") or "map"
    st: list[str] = []
    names: list[str] = []
    wide: list[str] = []
    if fr.get("offer"):
        st += OFFER_WORDS.get(fr["offer"], ["next", "yes"])
    if screen in ("lesson", "ride"):
        from .academy.grade import step_vocab
        st += _bias_words(step_vocab(step, list(fr.get("step_options") or []), aliases=False))
        wide += V["lessons"].get(fr.get("lesson_id") or "", []) + V["places"] + V["glossary"] + V["crew"] + \
            V["hardware"][:40]
    elif screen == "cabin":
        st += V["orders"] + V["panels"] + V["sites"]
        wide += ORDER_WORDS + V["places"] + V["crew"] + V["hardware"][:60] + V["glossary"]
    elif screen == "brief":
        st += V["sites"] + ["take command", "start the mission"]
        names += V["places"] + V["crew"]
        wide += V["orders"]
    elif screen == "callsign":
        st += V["callsigns"] + ["call me", "surprise me", "you pick"]
        wide += V["crew"]
    elif screen == "debrief":
        st += ["fly again", "another site"] + V["sites"]
        wide += V["orders"] + V["places"]
    else:          # the Moon screens: map, patch, lesson_done, library -> the whole gazetteer and the hardware
        # Names ARE what these screens are about: places, crew and hardware get their own strong tier here (round-7
        # ear eval: name recall 0.47 -> 0.60 with the strong weights vs 0.49 with the light screen ones)
        st += (["next", "start"] if screen != "library" else []) + \
            [t for t in (_lesson_titles() if screen != "library" else [])]
        names += V["places"] + V["crew"] + V["hardware"]
        wide += V["glossary"] + V["course"][:80]
    wide += V["nav"] + V["help"]
    st = _dedupe(st, MAX_STEP)
    sk = {w.lower() for w in st}
    names = [w for w in _dedupe(names, MAX_NAMES) if w.lower() not in sk]
    nk = sk | {w.lower() for w in names}
    return {"v": V["v"], "step": st, "names": names,
            "screen": [w for w in _dedupe(wide, MAX_SCREEN) if w.lower() not in nk]}


def _bias_words(ws: list[str]) -> list[str]:
    """What the decoder may be pushed toward: never function words or fillers ("yeah", "not", "sure"); the offer's
    own "yes" / "next" come from OFFER_WORDS, not from here. (The grader's sound-alike repair keeps them all.)"""
    from .soundalike import STOP, norm
    return [w for w in ws if norm(w) and not all(x in STOP for x in norm(w).split())]


@lru_cache(maxsize=1)
def _lesson_titles() -> tuple:
    try:
        from .academy import content
        return tuple(L["title"] for L in content.course()["lessons"])
    except Exception:  # noqa: BLE001
        return ()


def hot_match(text: str, lists: dict | None) -> dict:
    """Which list the heard words match and how strongly (the Director's hot_* features).
    -> {"step": exact hits, "screen": exact hits, "step_sa": best sound-alike score vs the step list (0..1),
        "screen_sa": the same vs the screen list}. Exact = a whole phrase on word boundaries."""
    from . import soundalike as SA
    out = {"step": 0, "screen": 0, "step_sa": 0.0, "screen_sa": 0.0}
    lists = {**lists, "screen": (lists.get("names") or []) + (lists.get("screen") or [])} if lists else lists
    if not lists or not (text or "").strip():
        return out
    t = " " + SA.norm(text) + " "
    for tier in ("step", "screen"):
        ph = [SA.norm(w) for w in lists.get(tier) or []]
        out[tier] = sum(1 for p in ph if p and f" {p} " in t)
        b = SA.best_span(text, [p for p in ph if p][:120], 0.6)
        out[tier + "_sa"] = round(b[2], 3) if b else 0.0
    return out


if __name__ == "__main__":      # python -m app.hotlist build  (from backend/): regenerate data/ear_vocab.json
    import sys
    if sys.argv[1:] == ["build"]:
        d = build_vocab()
        VOCAB_FILE.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
        print(f"{VOCAB_FILE}: v {d['v']}, " + ", ".join(f"{k} {len(x)}" for k, x in d.items() if isinstance(x, (list, dict))))
