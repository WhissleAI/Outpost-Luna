"""Knowledge cards: what the app may say, built at startup from the sourced data files. No new facts live here.

A card: {id, kind, title, aliases, attributes:{...}, answers:{attribute: [2-3 kid-phrased lines]}, sources:[{title,url}],
         questions:{attribute: [canonical question phrasings]}, place: <gazetteer id or None>}

Answer lines are templates filled only from card fields (sizes, dates, names, fact sentences come from the JSON), so every
line is true by construction. The question phrasings are what the embedder matches a kid's words against; they carry
no facts. Kinds: place (features), artifact (hardware), term (glossary), concept (mission ideas), site (outpost sites),
lesson (Academy facts), misconception.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from ..gazetteer import Gazetteer, Place, norm

IAU = {"title": "IAU Gazetteer of Planetary Nomenclature", "url": "https://planetarynames.wr.usgs.gov/"}
STYLE = {"size": "explain", "where": "explain", "what": "explain", "about": "story", "story": "story", "who": "story",
         "when": "story", "why": "explain", "science": "explain", "misconception": "explain"}

# Canonical question phrasings per attribute ({t} = the card title). Shapes of questions, not facts.
Q_PLACE = {
    "size": ["how big is {t}", "how wide is {t}", "what size is {t}", "how large is {t}", "how deep is {t}"],
    "where": ["where is {t}", "where can I find {t}", "which side of the moon is {t} on"],
    "when": ["how old is {t}", "when did people land at {t}", "what year was {t} found"],
    "who": ["who is {t} named after", "who went to {t}", "who named {t}"],
    "why": ["why is {t} special", "why does {t} look like that", "why is {t} bright"],
    "what": ["what is {t}", "what kind of place is {t}", "what is {t} made of"],
    "about": ["tell me about {t}", "what is cool about {t}", "fun fact about {t}"],
}
Q_ARTIFACT = {
    "story": ["tell me the story of {t}", "tell me about {t}", "what happened to {t}"],
    "what": ["what did {t} do", "what was {t} for", "what is {t}"],
    "science": ["what science did {t} do", "what did {t} discover", "what experiments did {t} have"],
    "who": ["who left {t}", "who flew {t}", "who was on {t}"],
    "when": ["when did {t} land", "what year did {t} land on the moon", "how long ago did {t} land"],
    "where": ["where is {t} now", "is {t} still on the moon", "where did {t} land"],
}
Q_TERM = {"what": ["what does {t} mean", "what is {t}", "what is a {t}", "explain {t}"]}
Q_SITE = {
    "what": ["tell me about {t}", "what is {t} like", "should we build the base at {t}"],
    "sun": ["how much sunlight does {t} get", "is {t} sunny", "does {t} get sun"],
    "earth": ["can we see earth from {t}", "can we talk to earth from {t}", "how often is earth up at {t}"],
    "ice": ["is there ice at {t}", "how far is the ice from {t}", "can we get water at {t}"],
}
ATTR_LABEL = {"size": "how big {t} is", "where": "where {t} is", "when": "when {t} happened", "who": "who {t} is about",
              "why": "why {t} is special", "what": "what {t} is", "about": "a fact about {t}", "story": "the story of {t}",
              "science": "the science of {t}", "sun": "sunlight at {t}", "earth": "seeing Earth from {t}",
              "ice": "ice at {t}", "misconception": "{t}"}
Q_FOR_LABEL = {"size": "How big is {t}?", "where": "Where is {t}?", "when": "When did {t} happen?",
               "who": "Who is {t} about?", "why": "Why is {t} special?", "what": "What is {t}?",
               "about": "Tell me about {t}", "story": "Tell me the story of {t}", "science": "What science did {t} do?",
               "sun": "How much sunlight does {t} get?", "earth": "Can we see Earth from {t}?",
               "ice": "Is there ice at {t}?", "misconception": "{t}"}

# Mission concepts: (id, title, aliases, questions, [(data path, ...)] resolved by _concept_lines).
CONCEPTS = [
    ("power", "solar power", ["solar power", "solar panels", "power", "sunlight", "electricity", "battery", "night"],
     ["how do we get power on the moon", "why do we need sunlight", "what happens to power at night",
      "what is the battery for", "why do the solar panels matter", "where do we get electricity"]),
    ("life_support", "life support", ["life support", "oxygen", "air", "breathe", "water"],
     ["what is life support", "how do astronauts breathe on the moon", "where does the air come from",
      "how do we get water on the moon", "what makes oxygen"]),
    ("dose", "radiation dose", ["radiation", "dose", "msv", "millisievert", "sievert"],
     ["what is radiation", "what is an msv", "how much radiation is on the moon", "is radiation dangerous",
      "what is the radiation limit for astronauts"]),
    ("storm", "solar storms", ["solar storm", "storm", "solar flare", "flare", "space weather"],
     ["what is a solar storm", "why are solar storms dangerous", "what do we do in a solar storm",
      "how do we stay safe from a storm", "what is a solar flare"]),
    ("shelter", "the storm shelter", ["shelter", "storm shelter", "bunker"],
     ["why do we go to the shelter", "what is the shelter made of", "how does the shelter protect us",
      "why does moon dirt stop radiation"]),
    ("comm_window", "comm windows", ["comm window", "radio", "talk to earth", "houston", "comms"],
     ["what is a comm window", "why can t we talk to earth", "why does the radio stop working",
      "why is there a delay talking to houston", "when can we call houston"]),
    ("ice", "ice at the south pole", ["ice", "frozen water", "permanently shadowed"],
     ["is there ice on the moon", "where is the ice", "why is there ice at the south pole",
      "how do we find water on the moon"]),
]

# Kid claims the data contradicts. Answers are built from glossary/facts lines (see _misconceptions).
MISCONCEPTIONS = [
    ("cheese", "Is the Moon made of cheese?", ["cheese", "cheddar"],
     ["is the moon made of cheese", "the moon is made out of cheese", "is the moon cheddar",
      "can you eat the moon", "is the moon made of swiss cheese"]),
    ("dark_side", "Is the far side always dark?", ["dark side"],
     ["the dark side of the moon never gets sunlight", "is the dark side always dark",
      "is it always night on the dark side", "does the far side ever get sun"]),
    ("no_craters", "Does the Moon have craters?", ["no craters"],
     ["the moon has no craters", "is the moon smooth", "does the moon have holes",
      "the moon is flat and smooth", "are there craters on the moon"]),
]

SENT = re.compile(r"(?<=[.!?])\s+")
YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b|\byears? (ago|old)\b|\b(million|billion) years\b|\bfirst seen\b")
SIZE = re.compile(r"\b(\d[\d,.]*)\s*(km|kilomet\w*|meters?)\b.*\b(wide|across|deep|tall|long)\b|\b(wide|across|deep)\b")
WHO = re.compile(r"\b(named after|named|astronauts?|crew|landed here|lived from)\b")
WHY = re.compile(r"\b(because|so it|so its|made by|formed|shaped like|which never|young)\b")
WHERE = re.compile(r"\b(side|edge|pole|north|south|east|west|sits|lies|near|between|halfway)\b")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT.split(text or "") if s.strip()]


def _uniq(xs: list[str], n: int = 3) -> list[str]:
    out = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out[:n]


def short_names(crew: list[str]) -> str:
    short = [re.sub(r"\s+(jr|sr)\.?$", "", re.sub(r'"[^"]*"\s*|\b[A-Z]\.\s*', "", c).strip(), flags=re.I) for c in crew]
    nick = [re.search(r'"([^"]+)"', c) for c in crew]
    short = [f"{m.group(1)} {s.split()[-1]}" if m else s for m, s in zip(nick, short)]
    short = [re.sub(r"^Charles ", "Charlie ", s) for s in short]
    return short[0] if len(short) == 1 else ", ".join(short[:-1]) + " and " + short[-1]


def _when(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _where_words(p: Place, side: str) -> str:
    if p.lat <= -80:
        return "at the Moon's south pole"
    if p.lat >= 80:
        return "at the Moon's north pole"
    s = {"near": "on the near side, the side we always see from Earth", "far": "on the far side, the side that never faces Earth",
         "limb": "near the Moon's edge, as we see it from Earth"}.get(side, f"on the {side} side")
    ns = "north" if p.lat > 20 else "south" if p.lat < -20 else ""
    return f"{s}{', in the ' + ns if ns else ''}"


def _card(cid, kind, title, aliases, attributes, answers, sources, questions, place=None) -> dict:
    answers = {k: v for k, v in answers.items() if v}
    return {"id": cid, "kind": kind, "title": title, "aliases": sorted({a for a in aliases if a}), "attributes": attributes,
            "answers": answers, "sources": sources, "place": place,
            "questions": {k: [q.format(t=title) for q in qs] for k, qs in questions.items() if k in answers}}


def place_card(p: Place, f: dict) -> dict:
    facts = [x["text"] for x in f.get("facts", [])] or _sentences(p.fact)
    side, typ = f.get("side", ""), f.get("type", "place")
    est = bool(f.get("estimated") or p.estimated)
    size = None if est or not f.get("diameter_km") else round(float(f["diameter_km"]))
    where = _where_words(p, side)
    attrs = {"type": typ, "side": side, "size_km": size, "where": where, "lat": p.lat, "lon": p.lon, "estimated": est}
    t = p.name
    pick = lambda pat: [x for x in facts if pat.search(x)]  # noqa: E731
    size_lines = [x for x in facts if size is not None and (f"{size:,}" in x or f"{size}" in x or " deep" in x)]
    if size is not None:
        size_lines = _uniq(size_lines + [f"{t} is about {size:,} km across.", f"From one side to the other, {t} is about {size:,} km wide."])
    elif est:
        size_lines = [f"Nobody has measured {t} yet. The Artemis II crew named it, so its size is only an estimate."]
    else:
        size_lines = []
    answers = {
        "size": size_lines,
        "where": _uniq(pick(WHERE) + [f"{t} is {where}.", f"You can find {t} {where}."]),
        "when": _uniq(pick(YEAR)),
        "who": _uniq(pick(WHO)),
        "why": _uniq(pick(WHY)),
        "what": _uniq([f"{t} is a {typ} {where}."] + facts[:1]) if typ != "pole" else facts[:1],
        "about": _uniq(facts),
    }
    src = [{"title": s, "url": ""} for s in _uniq([x.get("source", "") for x in f.get("facts", [])], 5)] or [IAU]
    return _card(f"place:{p.id}", "place", t, [p.name, p.id, *p.aliases], attrs, answers, src, Q_PLACE, place=p.id)


def artifact_card(p: Place) -> dict:
    t = p.name.split(" (")[0]
    who = (f"{short_names(p.crew)} {'drove' if p.type == 'rover' else 'landed' if p.type == 'lander' else 'left'} it, on {p.mission}."
           if p.crew else f"No one. {t} was a robot, sent by {p.agency}.")
    attrs = {"mission": p.mission, "agency": p.agency, "landed": p.landed, "crew": p.crew, "status": p.status, "type": p.type}
    answers = {
        "story": _uniq([p.story, " ".join(_sentences(p.story)[:2])]),
        "what": _uniq(_sentences(p.what_it_did)[:2]),
        "science": _uniq(_sentences(p.science)[:2]),
        "who": [who],
        "when": _uniq([f"{t} reached the Moon on {_when(p.landed)}, on {p.mission}.",
                       f"It got there on {_when(p.landed)}. That was {p.mission}."]) if p.landed else [],
        "where": _uniq([f"{p.status}." if p.status and not p.status.endswith(".") else p.status]),
    }
    return _card(f"artifact:{p.id}", "artifact", t, [t, p.name, p.id, *p.aliases], attrs, answers, p.sources, Q_ARTIFACT,
                 place=p.id)


def term_cards(glossary_path: Path) -> list[dict]:
    if not glossary_path.exists():
        return []
    out = []
    for term, v in json.loads(glossary_path.read_text())["terms"].items():
        ex = v["explain"]
        answers = {"what": _uniq([f"{term.capitalize()}: {ex}", f"{term.capitalize()} means {ex[:1].lower() + ex[1:]}"])}
        out.append(_card(f"term:{norm(term).replace(' ', '_')}", "term", term, [term, *v.get("forms", [])],
                         {"explain": ex}, answers, [{"title": "glossary.json (Moon Guide glossary)", "url": ""}], Q_TERM))
    return out


def _define(term_line: str) -> str:
    """capcom.TERMS phrasing ("a comm window, when Earth is up") -> a sentence ("A comm window is when Earth is up.")."""
    head, _, rest = term_line.partition(", ")
    if not rest or " is " in head:
        out = term_line
    elif rest.startswith("which "):
        out = f"{head} {rest[6:]}"
    else:
        out = f"{head} is {rest}"
    return out[0].upper() + out[1:] + "."


def _concept_lines(cid: str, sites: dict, rad: dict, terms: dict) -> tuple[list[str], list[dict]]:
    """Lines for a mission concept, each quoting a data field. -> (lines, sources)."""
    by = {s["id"]: s for s in sites.get("sites", [])}
    rim, floor, mal = by.get("shackleton_rim", {}), by.get("shackleton_floor", {}), by.get("malapert_massif", {})
    tline = lambda k: _define(terms[k]) if k in terms else ""  # noqa: E731
    if cid == "power":
        return ([tline("battery"), f"{rim.get('name')} gets sunlight about {rim.get('sunlight_pct')}% of the time, so solar panels work there most days.",
                 f"{floor.get('name')} gets sunlight {floor.get('sunlight_pct')}% of the time. Great for ice, terrible for solar power."],
                sites.get("sources", [])[:3])
    if cid == "life_support":
        return [tline("life support"), "Ice can become water and oxygen, so the rover digs for it."], sites.get("sources", [])[:1]
    if cid == "dose":
        b, lim = rad.get("baseline", {}), rad.get("limits", {})
        return ([tline("msv"), lim.get("what", ""),
                 f"On the Moon's surface, a lander measured about {b.get('dose_equivalent_usv_per_day')} microsieverts a day."],
                [x for x in (b.get("source"), lim.get("source")) if x])
    if cid == "storm":
        return [tline("solar storm"), _sentences(rad.get("shielding", {}).get("what", ""))[0]], rad.get("shielding", {}).get("sources", [])
    if cid == "shelter":
        sh = _sentences(rad.get("shielding", {}).get("what", ""))
        return sh[:2], rad.get("shielding", {}).get("sources", [])
    if cid == "comm_window":
        return ([tline("comm window"), f"At {mal.get('name')}, Earth is above the horizon about {mal.get('earth_visible_pct')}% of the time, the best spot for talking to Houston.",
                 f"A radio call to Houston and back takes about {_round_trip_s():g} seconds, so answers come with a little wait."],
                sites.get("sources", [])[:2])
    if cid == "ice":
        return _sentences(floor.get("notes", ""))[:2], floor.get("sources", [])[:2] or sites.get("sources", [])[:1]
    return [], []


def _round_trip_s() -> float:
    from ..mission.capcom import MOON_ROUND_TRIP_MS
    return MOON_ROUND_TRIP_MS / 1000


def site_cards(sites: dict) -> list[dict]:
    out = []
    for s in sites.get("sites", []):
        t = s["name"]
        answers = {"what": [" ".join(_sentences(s.get("notes", ""))[:2])],
                   "sun": [f"{t} gets sunlight about {s['sunlight_pct']}% of the time."] if "sunlight_pct" in s else [],
                   "earth": [f"From {t}, Earth is above the horizon about {s['earth_visible_pct']}% of the time."] if "earth_visible_pct" in s else [],
                   "ice": ([f"Yes! {t} has ice right there."] if s.get("ice") else
                           [f"No ice right at {t}. The rover needs about {s['rover_to_ice_h']} hours to reach ice."] if s.get("rover_to_ice_h") else [])}
        out.append(_card(f"site:{s['id']}", "site", t, [t, s["id"].replace("_", " ")], {k: v for k, v in s.items() if k != "sources"},
                         answers, s.get("sources", []), Q_SITE))
    return out


def lesson_cards(course: dict) -> list[dict]:
    out = []
    for les in course.get("lessons", []):
        facts = les.get("facts", [])
        if not facts:
            continue
        lines = [f["text"] for f in facts]
        qs = {"about": [f"tell me about {les['title']}", f"what do I learn in {les['title']}"],
              "what": [f["text"] for f in facts]}  # the facts themselves are the best "doc" side for paraphrases
        out.append({"id": f"lesson:{les['id']}", "kind": "lesson", "title": les["title"], "aliases": [], "place": None,
                    "attributes": {"lesson": les["id"]}, "answers": {"about": lines[:3], "what": lines},
                    "sources": [f["source"] for f in facts if f.get("source")], "questions": qs})
    return out


def misconception_cards(glossary: dict, facts: dict) -> list[dict]:
    def g(k: str) -> str:
        ex = glossary.get(k, {}).get("explain", "")
        return ex[:1].lower() + ex[1:]
    tycho = (facts.get("tycho") or {}).get("facts", [{}])[0].get("text", "")
    lines = {
        "cheese": [f"Not cheese! The ground is regolith. Regolith means {g('regolith')}",
                   f"Nope, no cheese. The Moon is covered in regolith: {g('regolith')}"],
        "dark_side": [f"The far side gets sunlight too! Far side means {g('far side')}",
                      f"It isn't always dark there. The far side is just {g('far side')}"],
        "no_craters": [f"The Moon is covered in craters! A crater is {g('crater')} {tycho}".strip(),
                       f"Lots of craters! {tycho}".strip()],
    }
    out = []
    for cid, title, aliases, qs in MISCONCEPTIONS:
        out.append({"id": f"misconception:{cid}", "kind": "misconception", "title": title, "aliases": aliases, "place": None,
                    "attributes": {}, "answers": {"misconception": [x for x in lines[cid] if x]},
                    "sources": [{"title": "glossary.json + facts.json", "url": ""}], "questions": {"misconception": qs}})
    return out


def build(gaz: Gazetteer, facts: dict, data_dir: Path) -> list[dict]:
    cards = []
    for p in gaz.places.values():
        cards.append(artifact_card(p) if p.kind == "artifact" else place_card(p, facts.get(p.id) or {}))
    gl_path = data_dir / "glossary.json"
    cards += term_cards(gl_path)
    glossary = json.loads(gl_path.read_text())["terms"] if gl_path.exists() else {}
    sites = _load(data_dir / "mission/sites.json")
    rad = _load(data_dir / "mission/radiation.json")
    from ..mission.capcom import TERMS
    for cid, title, aliases, qs in CONCEPTS:
        lines, srcs = _concept_lines(cid, sites, rad, TERMS)
        lines = [x for x in lines if x]
        if lines:
            cards.append({"id": f"concept:{cid}", "kind": "concept", "title": title, "aliases": aliases, "place": None,
                          "attributes": {}, "answers": {"what": _uniq(lines)}, "sources": srcs, "questions": {"what": qs}})
    cards += site_cards(sites)
    cards += lesson_cards(_load(data_dir / "academy/course.json"))
    cards += misconception_cards(glossary, facts)
    return cards


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}
