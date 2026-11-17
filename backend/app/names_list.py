"""The ear's NAMES LIST per screen, for Arc Transcriber Space (model_server/app/arc_ear.py; docs/LOCAL_EAR.md).

The model takes a list of entries {"name", "kind", "aliases"} and uses it three ways: it biases the transcript toward
them, puts the first ~10-15 in its decoder prompt, and LINKS what was said to an entry (names[i].entity = our `name`,
state linked / abstain / not_in_list). Its guide's rules, applied here:
  - `kind` always set: lunar_feature, site, celestial, spacecraft, mission, crew, organization, ...
  - short and current: <= MAX (40), MOST RELEVANT FIRST (what is on screen or in the open step);
  - aliases for anything not said as written: Roman numerals ("Artemis II" -> "Artemis 2", "Artemis two"), Latin and
    English names ("Sea of Tranquility" + "Mare Tranquillitatis"), letters said one by one ("LCROSS" -> "L cross",
    "S-IVB" -> "S 4 B"), acronyms said as words ("ALSEP" -> "al sep"), ASCII spellings;
  - no entries made only of generic words ("Sea", "Crater", "North").
The catalogue is DATA from places.json, artifacts.json, mission/sites.json and the crew lists; the screen picks from it.
`session.ear_names()` builds the list for the kid's screen, and /ws/listen sends it ({"t":"context","names":[...]})
whenever it changes. Routing then uses names[i].entity (session.py -> director._link), never the raw words.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
MAX = 40           # the cap for a focused screen (cabin, lesson, video ...): the model card's "<= 30-50"
MAX_MOON = 80      # the Moon screens (map, library, patch, lesson_done): every place AND every piece of hardware.
# Signals audit (docs/SPEECH_SIGNALS_AUDIT.md): at 40 the library list held 3 of the 36 hardware entries, so 57 % of the
# names kids say on the library screen (595 of 1051 mentions in the round-11 texts) could never be linked. The
# re-decode with an 80-entry list is in the audit (linking, wrong links, spurious links, decode time).
MAX_EAR = MAX_MOON  # what /ws/listen and the model server accept (the longest list a screen sends)

# Latin <-> English and other spoken forms of the gazetteer's places (by places.json id).
PLACE_ALIASES = {
    "tranquillitatis": ["Mare Tranquillitatis", "Tranquility Base", "Sea of Tranquillity"],
    "aristarchus": ["Aristarchus", "Aristarchus crater"],
    "orientale": ["Mare Orientale", "Orientale", "Orientale basin"],
    "hertzsprung": ["Hertzsprung basin", "Hertzsprung crater"],
    "imbrium": ["Mare Imbrium", "Imbrium"],
    "crisium": ["Mare Crisium", "Crisium"],
    "shackleton": ["Shackleton crater"],
    "tsiolkovskiy": ["Tsiolkovsky", "Tsiolkovsky crater"],
    "spa": ["South Pole Aitken", "Aitken basin", "South Pole Aitken basin"],
    "byrgius_a": ["Byrgius Alpha"],
    "humorum": ["Sea of Moisture", "Humorum"],
    "reiner": ["Reiner Gamma swirl"],
    "copernicus": ["Copernicus crater"],
    "tycho": ["Tycho crater"],
    # spoken / singular forms the ear produced for these names in the round-11 decodes ("sea of rain" x5, "c of crisi")
    # and the place names kids use without the qualifier
}
SPOKEN_FORMS = {"imbrium": ["Sea of Rain"], "crisium": ["Sea of Crisis"], "byrgius_a": ["Byrgius"],
                "ohm": ["Ohm crater"], "pythagoras": ["Pythagoras crater"],
                "malapert_massif": ["Malapert", "Malapert Mountain"], "de_gerlache_rim": ["de Gerlache", "de Gerlache rim"],
                "shackleton_rim": ["Shackleton rim"], "shackleton_floor": ["Shackleton floor"]}
# aliases that name a CLASS of thing, not one entry (three lunar modules had "descent stage"): never a link target
GENERIC_ALIASES = {"descent stage", "lander", "rover", "impact site", "spacecraft"}
CREW_NOW = [("Reid Wiseman", ["Reid", "Commander Wiseman"]), ("Victor Glover", ["Victor", "Glover"]),
            ("Christina Koch", ["Christina", "Koch"]), ("Jeremy Hansen", ["Jeremy", "Hansen"])]
ORGS = [("Houston", "organization", ["Mission Control"]), ("CAPCOM", "crew", ["cap com", "capsule communicator"]),
        ("NASA", "organization", ["N A S A"])]
MISSIONS = [("Artemis II", ["Artemis 2", "Artemis two"]), ("Artemis III", ["Artemis 3", "Artemis three"]),
            ("Artemis I", ["Artemis 1", "Artemis one"])]
SPACECRAFT = [("Orion", ["Orion capsule", "Orion spacecraft"]), ("SLS", ["S L S", "Space Launch System"]),
              ("Lunar Module", ["L M", "lunar lander"]), ("Lunar Roving Vehicle", ["moon buggy", "L R V"]),
              ("Integrity spacecraft", ["the Integrity capsule"])]
# letters / acronyms / non-ASCII as spoken
SPOKEN = [(re.compile(r"\bS-IVB\b"), ["S 4 B", "S four B"]), (re.compile(r"\bLCROSS\b"), ["L cross"]),
          (re.compile(r"\bALSEP\b"), ["al sep"]), (re.compile(r"\bLADEE\b"), ["laddie"]),
          (re.compile(r"\bGRAIL\b"), ["grail"]), (re.compile(r"Chang'e"), ["Chang e", "Changee"])]
ROMAN = {"I": "1", "II": "2", "III": "3", "IV": "4"}
WORDS = {"1": "one", "2": "two", "3": "three", "4": "four"}
GENERIC = set("sea crater basin mare north south pole valley mountain plateau rim floor ridge base the of".split())


def _clean(n: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\s*\(.*?\)", "", n or "")).strip()


def _paren(n: str) -> list[str]:
    """'Yutu (Jade Rabbit) rover' -> ['Jade Rabbit']."""
    return [x.strip() for x in re.findall(r"\(([^)]+)\)", n or "") if x.strip()]


def _roman(n: str) -> list[str]:
    m = re.search(r"\b(I{1,3}|IV)\s*$", n)
    if not m or n.strip() in ROMAN:
        return []
    d = ROMAN[m.group(1)]
    base = n[: m.start()].strip()
    return [f"{base} {d}", f"{base} {WORDS[d]}"]


def _person(n: str) -> tuple[str, list[str]] | None:
    """'Edwin E. "Buzz" Aldrin Jr.' -> ('Buzz Aldrin', ['Edwin Aldrin', 'Aldrin'])."""
    nick = re.findall(r'"([^"]+)"', n)
    ws = [w for w in re.sub(r'"[^"]+"', " ", n).replace(",", " ").split()
          if not re.fullmatch(r"[A-Z]\.|Jr\.?|Sr\.?|II|III", w)]
    if not ws:
        return None
    last = ws[-1]
    full = f"{ws[0]} {last}" if len(ws) > 1 else last
    if nick:
        return f"{nick[0]} {last}", [full, last]
    return full, [last]


def _entry(name: str, kind: str, aliases=(), id: str | None = None) -> dict:
    name = _clean(name)
    al = []
    for a in [*aliases, *_roman(name)]:
        a = _clean(a)
        if a and a.lower() != name.lower() and a.lower() not in {x.lower() for x in al}:
            al.append(a)
    spoken = []
    for x in sorted([name, *al], key=len):          # the shortest forms first: the cap keeps what kids say
        for rx, forms in SPOKEN:
            if rx.search(x):
                spoken += [rx.sub(f, x) for f in forms]
    al = [a for a in spoken + al if a.lower() != name.lower()]
    al = [a for i, a in enumerate(al) if a.lower() not in {b.lower() for b in al[:i]}]
    if not name.isascii():
        al.append(name.encode("ascii", "ignore").decode())
    e = {"name": name, "kind": kind}
    if al:
        e["aliases"] = al[:8]
    if id:
        e["id"] = id
    return e


def generic(name: str) -> bool:
    return all(w in GENERIC for w in re.findall(r"[a-z]+", name.lower()))


@lru_cache(maxsize=1)
def catalogue() -> dict[str, list[dict]]:
    """Every name the app knows, by group: places, sites, crew, missions, spacecraft, hardware."""
    places = []
    raw = json.loads((DATA / "places.json").read_text(encoding="utf-8"))
    for p in raw.get("places") or []:
        nm = _clean(p["name"])
        if generic(nm) and p["id"] != "north_pole":
            continue
        places.append(_entry(nm, "lunar_feature", PLACE_ALIASES.get(p["id"], []) + SPOKEN_FORMS.get(p["id"], [])
                             + [x for x in _paren(p["name"]) if x.lower() != "south pole"], id=p["id"]))
        if p["id"] == "shackleton":
            # "south pole" is only an alias of Shackleton, and the ear's linker doesn't link aliases: without an entry
            # of its own, "show me the south pole" linked "Pole" -> "North Pole" (16/16 test clips) and flew north.
            # With this entry it links "South Pole" (p 1.0); the director resolves it to Shackleton (gazetteer alias).
            places.append(_entry("South Pole", "lunar_feature", ["lunar south pole"], id="south_pole"))
    sites = []
    try:
        for s in json.loads((DATA / "mission/sites.json").read_text(encoding="utf-8")).get("sites") or []:
            nm = s["name"]
            sites.append(_entry(nm, "site", SPOKEN_FORMS.get(s.get("id"), []), id=s.get("id")))
    except OSError:
        pass
    sites += [_entry("Cabeus", "lunar_feature", ["Cabeus crater"], id="cabeus"),
              _entry("Malapert", "lunar_feature", ["Malapert Mountain"], id="malapert"),
              _entry("de Gerlache", "lunar_feature", ["de Gerlache crater"], id="de_gerlache")]
    crew = [_entry(n, "crew", al) for n, al in CREW_NOW] + [_entry(n, k, al) for n, k, al in ORGS]
    hardware, missions, old_crew = [], [_entry(n, "mission", al) for n, al in MISSIONS], []
    seen_m = set()
    arts = json.loads((DATA / "artifacts.json").read_text(encoding="utf-8")) if (DATA / "artifacts.json").exists() else []
    for a in arts:
        kind = "site" if a.get("kind") in ("impact", "memorial") else "spacecraft"
        al = [x for x in a.get("aliases") or [] if x and x[:1].isupper() and len(x) >= 3] + _paren(a["name"])
        short = re.sub(r"\s+(\(.*?\)|descent stage|rocket stage impact site|impact site)$", "", _clean(a["name"])).strip()
        if short != _clean(a["name"]):
            al.insert(0, short)
        hardware.append(_entry(a["name"], kind, al, id=a.get("id")))
        m = a.get("mission")
        if m and m not in seen_m:
            seen_m.add(m)
            missions.append(_entry(m, "mission"))
        for c in a.get("crew") or []:
            pr = _person(c)
            if pr:
                old_crew.append(_entry(pr[0], "crew", pr[1]))
    return {"places": places, "sites": sites, "crew": crew, "missions": missions,
            "spacecraft": [_entry(n, "spacecraft", al) for n, al in SPACECRAFT], "hardware": hardware,
            "old_crew": old_crew}


# The cabin's sites carry the short names ("de Gerlache", "Malapert"): the lunar-feature entries of the same names stay
# off the cabin list, so "explore de Gerlache" links the SITE (round 11: cabin had 11 % links to the wrong entity).
SITE_TWINS = {"de_gerlache", "malapert"}


def _find(name: str) -> dict | None:
    k = _clean(name).lower()
    for grp in catalogue().values():
        for e in grp:
            if e["name"].lower() == k or k in (a.lower() for a in e.get("aliases") or []):
                return e
    return None


def _take(out: list[dict], xs, cap: int = MAX) -> None:
    have = {e["name"].lower() for e in out}
    for e in xs:
        if e and e["name"].lower() not in have and len(out) < cap:
            have.add(e["name"].lower())
            out.append(e)


def recent_names(lines) -> list[dict]:
    """Catalogue entries named in these lines (what we just said / showed): the kid's next turn often names them
    ("...the crater Tsiolkovskiy." -> "how far is Tsiolkovskiy?"), so they go first: into the decoder's kb prompt
    (the first ~10-15 entries) as well as the biasing and linking lists."""
    text = " " + " ".join(_toks(x) for x in lines or [] if x) + " "
    if not text.strip():
        return []
    out = []
    for grp in ("places", "sites", "hardware", "crew", "missions", "spacecraft", "old_crew"):
        for e in catalogue()[grp]:
            for f in [e["name"], *(e.get("aliases") or [])]:
                t = _toks(f)
                if t and not generic(f) and f" {t} " in text:
                    out.append(e)
                    break
    return out


def _toks(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def dedupe_aliases(out: list[dict]) -> list[dict]:
    """An alias is a link target, so it must name ONE entry: aliases equal to another entry's name, shared by two
    entries, or generic (GENERIC_ALIASES) are dropped (round 11: "Shackleton" was an alias of both Shackleton sites AND
    the name of the crater; "descent stage" of three lunar modules)."""
    names = {e["name"].lower() for e in out}
    seen: dict[str, int] = {}
    for e in out:
        for a in {a.lower() for a in e.get("aliases") or []}:
            seen[a] = seen.get(a, 0) + 1
    res = []
    for e in out:
        al = [a for a in e.get("aliases") or [] if a.lower() not in names and seen.get(a.lower(), 0) == 1
              and a.lower() not in GENERIC_ALIASES]
        e = {k: v for k, v in e.items() if k != "aliases"}
        if al:
            e["aliases"] = al
        res.append(e)
    return res


def screen_names(frame: dict | None, step: dict | None = None, last_place: str | None = None,
                 recent: list[str] | None = None) -> list[dict]:
    """The names list for this screen frame, most relevant first ({"name","kind","aliases"?}): <= MAX entries on a
    focused screen, <= MAX_MOON on the Moon screens. Order = weight: the ear puts the first ~10-15 in its decoder prompt.
      1. what is on screen right now: the open step's options, then what we just said / showed (`recent` lines),
         then the place the kid is looking at;
      2. what the screen is about (per screen, below)."""
    C = catalogue()
    fr = frame or {}
    screen = fr.get("screen") or "map"
    moon = screen not in ("cabin", "brief", "debrief", "video", "lesson", "ride", "callsign", "prep")
    cap = MAX_MOON if moon else MAX
    out: list[dict] = []
    cabin = screen in ("cabin", "brief", "debrief")
    if screen in ("lesson", "ride"):
        from .academy.grade import step_vocab
        for w in step_vocab(step, list(fr.get("step_options") or []), aliases=False):
            e = _find(w)
            if e:
                _take(out, [e], cap)
            elif re.search(r"[A-Z]", w) and len(w) >= 3 and not generic(w) and len(w.split()) <= 4:
                _take(out, [_entry(w, "place")], cap)      # an option that is a proper name we don't catalogue
    rec = [e for e in recent_names(recent) if not (cabin and e.get("id") in SITE_TWINS)]
    _take(out, rec[:8], cap)
    if last_place:
        _take(out, [e for e in C["places"] + C["hardware"] if e.get("id") == last_place], cap)
    if cabin:
        # NOT the rover / moon buggy: a control is not a name. The ear writes a linked span in the list's spelling, so
        # "send the rover" became "send Lunar Roving Vehicle" and the cabin's WER rose 36 -> 46 % in the re-decode
        # (docs/SPEECH_SIGNALS_AUDIT.md; the Arc ask: bias-only entries that are never linked or rewritten).
        _take(out, [e for e in C["sites"] if e.get("id") not in SITE_TWINS] + C["crew"] + C["missions"][:3]
              + C["spacecraft"][:3] + C["places"], cap)
    elif screen == "video":
        _take(out, C["crew"] + C["missions"][:3] + C["places"], cap)
    elif screen in ("lesson", "ride"):
        _take(out, C["places"] + C["crew"][:4] + C["missions"][:2], cap)
    elif screen == "callsign":
        _take(out, C["crew"], cap)
    elif screen == "prep":
        _take(out, C["crew"][:4] + C["missions"][:2], cap)
    elif screen == "library":   # the hardware library: what is left on the Moon first, then the places
        _take(out, C["hardware"] + C["places"] + C["crew"][:6] + C["missions"][:2] + C["spacecraft"][:2]
              + C["sites"] + C["old_crew"], cap)
    else:   # map, patch, lesson_done: the gazetteer, the hardware on it, the Artemis II crew and craft, the sites
        _take(out, C["places"] + C["hardware"] + C["crew"][:6] + C["missions"][:2] + C["spacecraft"][:2]
              + C["sites"] + C["old_crew"], cap)
    return dedupe_aliases([{k: v for k, v in e.items() if k != "id"} for e in out[:cap]])


def catalogue_names() -> list[dict]:
    """Everything (for offline tools: the ear eval's decoys)."""
    out: list[dict] = []
    for grp in catalogue().values():
        _take(out, grp, cap=10_000)
    return [{k: v for k, v in e.items() if k != "id"} for e in out]
