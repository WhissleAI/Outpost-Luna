"""The Director (docs/REVAMP.md §3.5): one kid turn -> one action, as rules over Arc Tagger's read-out.

Actions returned: guard | fly | play | say | ask | view | tour (a list of artifacts: "show me the rovers"). WAIT / NUDGE / PAUSE_EXPLAIN are client behaviours driven by
the fields here (`readout.complete`, `moment.jargon`). Every spoken line goes through the claim check (claims.py).
Response shape: docs/CONTRACT.md.
"""
from __future__ import annotations

import re

from . import claims, llm
from .gazetteer import Gazetteer, Place, norm
from .moments import MomentIndex, public

CORRECTION = re.compile(r"\b(no wait|wait no|no no|i mean|sorry|actually|not that)\b")
WANTS_CREW = re.compile(r"\b(astronauts?|crew|hear|listen|what did|they say|say about|recording|play|christina|"
                        r"victor|reid|jeremy)\b")
NAME_GIVEN = re.compile(r"\b(my name is|my name s|i m called|call me)\b")
MORE = re.compile(r"\b(there|that one|it|this one|more|again|that place|that crater)\b")
DEFINE = re.compile(r"\b(what does|what s|what is|whats|what are|mean|means|meaning)\b")

# ---- hardware left on the Moon (artifacts.json) ----------------------------------------------------------------------
TOURS = [  # (pattern, artifact types or None = all, say)
    (re.compile(r"\b(ghost )?(rovers?|moon buggies|moon buggy|buggies|lrvs?)\b"), {"rover"},
     "Here are the rovers still parked on the Moon. Tap one to hear its story!"),
    (re.compile(r"\b(landers|landing sites|lunar modules|where (did|have) (people|astronauts|we) landed?)\b"), {"lander"},
     "Here is every spacecraft that landed on the Moon and stayed there. Tap one to hear its story!"),
    (re.compile(r"\b(crash(es| sites)|impacts?( sites)?|crashed)\b"), {"impact"},
     "These are the places where spacecraft crashed into the Moon, many of them on purpose, for science!"),
    (re.compile(r"\b(instruments|experiments|science stations|mirrors|reflectors)\b"), {"instrument"},
     "These science tools were left on the Moon. One mirror still bounces lasers back to Earth!"),
    (re.compile(r"\b(hardware|junk|trash|left (behind )?on the moon|left behind|left there|left on it|stuff (on|left)|"
                r"things (on|left)|abandoned|ghost|what s on the moon|spacecraft on the moon|machines)\b"), None,
     "People have left lots of hardware on the Moon: landers, rovers, science tools and crash sites. Tap one to hear its story!"),
]
WHO = re.compile(r"\b(who (left|drove|put|flew|landed|built|sent|parked|rode|brought|made|used|set)|who was (in|on|driving)|"
                 r"whose|who did)\b")
HEAR_VOICE = re.compile(r"\b(hear|listen|voice|message|play)\b")
SOUNDS = [  # mission sounds from the NASA Artemis Audio Library (set "voices")
    (re.compile(r"\b(go no go|countdown|count down|poll)\b"), "go-no-go", "Mission control asks every team: go or no-go?"),
    (re.compile(r"\b(launch|liftoff|lift off|blast ?off|take ?off|rocket start)\b"), "liftoff",
     "Here's the moment Artemis II lifted off. Listen!"),
    (re.compile(r"\bfull send\b"), "full-send", "Right before launch, the crew said who they were flying for. Listen!"),
    (re.compile(r"\b(translunar|tli|go for the moon|head(ed|ing)? to the moon)\b"), "tli",
     "This is when Houston said go to fly to the Moon. Listen!"),
    (re.compile(r"\b(good burn|engine burn|burn)\b"), "good-burn", "Here's the engine burn. Listen!"),
    (re.compile(r"\b(distance record|farthest|furthest|apollo 13 record|broke the record|record)\b"), "apollo13-record",
     "Artemis II flew farther from Earth than Apollo 13! Listen!"),
    (re.compile(r"\b(splash ?down|splash|landed in the (ocean|sea|water)|coming home|came home)\b"), "splashdown",
     "Here's Orion splashing down in the ocean. Listen!"),
    (re.compile(r"\b(loud and clear|houston we have you)\b"), "loud-and-clear", "Houston hears the crew again. Listen!"),
    (re.compile(r"\b(charlie duke)\b"), "duke", "Here's Apollo 16 astronaut Charlie Duke. Listen!"),
    (re.compile(r"\b(jim lovell|lovell)\b"), "lovell", "Here's Apollo astronaut Jim Lovell. Listen!"),
]
SOUND_ASK = re.compile(r"\b(sound|sounded|hear|listen|play|audio|recording)\b")


def _tour(q: str, gaz: Gazetteer) -> tuple[list[str], str] | None:
    for pat, types, say in TOURS:
        if pat.search(q):
            ps = sorted((p for p in gaz.artifacts if types is None or p.type in types), key=lambda p: p.landed)
            if ps:
                return [p.id for p in ps], say
    return None


def _names(crew: list[str]) -> str:
    short = [re.sub(r'\s+(jr|sr)\.?$', "", re.sub(r'"[^"]*"\s*|\b[A-Z]\.\s*', "", c).strip(), flags=re.I) for c in crew]
    nick = [re.search(r'"([^"]+)"', c) for c in crew]
    short = [f"{m.group(1)} {s.split()[-1]}" if m else s for m, s in zip(nick, short)]
    short = [re.sub(r"^Charles ", "Charlie ", s) for s in short]
    return short[0] if len(short) == 1 else ", ".join(short[:-1]) + " and " + short[-1]


def _voice(p: Place, index: MomentIndex) -> dict | None:
    for v in p.voices:
        m = index.span(v["clip_id"], float(v["t0"]), float(v["t1"]), f"{v['clip_id']}-voice-{p.id}", v.get("who", ""), [p.id])
        if m:
            return m
    return None


def _who_line(p: Place) -> str:
    if not p.crew:
        return f"No one! {p.name} was a robot spacecraft, sent by {p.agency}. No people rode on it."
    verb = "drove" if p.type == "rover" else "landed" if p.type == "lander" else "left"
    return f"{_names(p.crew)} {verb} it, on {p.mission}."


def _sound_moment(clip_id: str, q: str, index: MomentIndex) -> dict | None:
    ms = [m for m in index.moments if m["clip_id"] == clip_id and m["kid_safe"]]
    if not ms:
        return None
    key = {"liftoff": "lift", "splashdown": "splashdown", "apollo13-record": "record", "go-no-go": "go"}.get(clip_id)
    hit = [m for m in ms if key and key in m["text"].lower()]
    return hit[0] if hit else index.best_in_clip(clip_id)


async def _artifact(p: Place, text: str, q: str, base: dict, gaz: Gazetteer, index: MomentIndex, short: bool) -> dict:
    """An artifact was named (or tapped, or is the last place and the kid asks who left it)."""
    voice = _voice(p, index)
    if WHO.search(q) or (HEAR_VOICE.search(q) and voice):
        if voice:
            who = voice["speaker"] or "an astronaut"
            line = f"{_who_line(p)} Listen to {who}!" if p.crew else f"Listen to {who}!"
            return {**base, "action": "play", "say": line, "moment": public(voice), "source": base["source"] + "+voice"}
        line = _who_line(p)
        return {**base, "action": "say" if not p.crew else "fly", "say": line,
                "claims": [{"text": line, "status": "verified", "source": "artifacts.json (crew)"}],
                "source": base["source"] + "+crew"}
    # The first-person story, claim-checked sentence by sentence; the story verbatim if nothing survives.
    story = claims.SENT.split(p.story)[0] if short else p.story
    cl = await claims.verify_draft(story, [p.id], gaz, index.facts)
    say = " ".join(c["text"] for c in cl if c["status"] == "verified")
    if not say:
        say, cl = story, cl + [{"text": story, "status": "verified", "source": claims.PREVERIFIED}]
    return {**base, "action": "fly", "say": say, "claims": cl, "moment": public(voice),
            "source": base["source"] + "+story+claimcheck"}


def _benign_pii(text: str, gaz: Gazetteer) -> bool:
    """Arc tags Moon words as PII ("Moon" -> street_address in "Apollo 16 Moon buggy"). A span that names a place or
    artifact, or is made only of gazetteer / hardware words (no digits), is not a child's private detail."""
    t = norm(text)
    if not t:
        return True
    if gaz.match_text(t):
        return True
    return not re.search(r"\d|@", text) and all(w in gaz.vocab for w in t.split())


def _hard_pii(read: dict, gaz: Gazetteer) -> bool:
    spans = read.get("pii_spans")
    if spans is None:  # older read-outs: trust the type list
        return bool(read.get("hard_pii"))
    from .readout import HARD_PII
    return any(s["type"] in HARD_PII and not _benign_pii(s["text"], gaz) for s in spans)


ACCEPT, ASK_LO, ASK_MARGIN = 89.0, 82.0, 5.0

FAR = "This is the far side. It always faces away from Earth, so nobody saw it until spacecraft flew around."
NEAR = "This is the near side, the face we always see from Earth. The dark patches are old lava seas."
EARTHRISE = "When Orion went behind the Moon, Earth came up over the edge. Listen to how the crew reacted!"
UNKNOWN = "I don't know that one yet. Try: “show me the giant bullseye” or “where did Apollo 11 land?”"
GUARD = "Let's keep names and addresses private! Ask me about a place on the Moon instead."
MISSION = "Want a mission? Find the giant bullseye on the far side, then ask what the crew said about it!"
NO_MOMENT = "The crew didn't talk about that place in our recordings, but here it is!"

# Kid claims that contradict the fact sheet -> gentle correction (pre-verified text) + an optional related place.
MISCONCEPTIONS = [
    (re.compile(r"\b(made (of|out of) cheese|is cheese|cheese moon)\b"),
     "Not cheese! The Moon is made of rock and dust. But the crew did say one place looked yellow, like a snowy mountain.",
     "aristarchus"),
    (re.compile(r"\b(no craters|doesn t have (any )?craters|has no craters|not have craters|smooth)\b"),
     "The Moon is covered in craters! Space rocks made them. Here's a giant one, like a bullseye.", "orientale"),
    (re.compile(r"\b(makes (its|it s) own light|moon glows by itself|own light|moon is a star)\b"),
     "The Moon doesn't make its own light. It shines because sunlight bounces off it.", None),
    (re.compile(r"\b(dark side (never|doesn t|does not) (get|see|have) (any )?(sun|light)|always dark on the (dark|far) side)\b"),
     "The far side gets sunlight too! We just never see it from Earth, because it always faces away.", "hertzsprung"),
    (re.compile(r"\b(moon is bigger than (the )?earth|moon is (a )?planet)\b"),
     "The Moon is smaller than Earth. It's Earth's partner that goes around us.", None),
]


def _after_correction(text: str) -> tuple[str, bool]:
    q = norm(text)
    parts = CORRECTION.split(q)
    if len(parts) > 1 and parts[-1].strip():
        return parts[-1].strip(), True
    return q, False


def _view(p: Place | None) -> dict | None:
    return {"lat": p.lat, "lon": p.lon} if p else None


def _short(text: str, n: int = 14) -> str:
    first = re.split(r"(?<=[.!?])\s+", text.strip())[0]
    w = first.split()
    return first if len(w) <= n else " ".join(w[:n]).rstrip(",;") + "."


def _bridge(m: dict) -> str:
    who = m.get("speaker") or "crew"
    # Deepgram diarization gives numbers (0, 1, ...), not names: only use a real name.
    who = str(who)
    who = who.split()[0] if re.match(r"^[A-Za-z][A-Za-z.'-]+", who) and who.lower() not in ("crew", "unknown") else "The crew"
    return f"{who} saw this from Orion. Listen!"


def _link(target: str, read: dict, gaz: Gazetteer) -> tuple[Place | None, str, list[tuple[Place, float]]]:
    """-> (place, how, ask_candidates). ask_candidates is set when the fuzzy link is in the ask band."""
    p = gaz.match_text(target)
    if p:
        return p, "alias", []
    mentions = [m for m in read.get("mentions", []) if norm(m) and norm(m) in target]
    if not read.get("available"):  # no Arc: fuzzy the longer words of the text itself
        mentions += [w for w in target.split() if len(w) >= 5]
    for m in mentions:
        cands = gaz.candidates(m)
        if not cands or cands[0][1] < ASK_LO:
            continue
        top, s = cands[0]
        close = [c for c in cands[1:] if s - c[1] <= ASK_MARGIN]
        if s >= ACCEPT and not close:
            return top, "arc+link" if read.get("available") else "fuzzy", []
        return None, "ask", [cands[0], *close]
    return None, "", []


async def direct(text: str, read: dict, gaz: Gazetteer, index: MomentIndex, context: dict | None = None) -> dict:
    ctx = context or {}
    q = norm(text)
    emotion = (ctx.get("emotion") or "").lower()
    short = emotion in ("confused", "frustrated")
    out = {"action": "say", "say": "", "place": None, "view": None, "moment": None, "ask": None, "claims": [],
           "readout": read, "source": "rules", "corrected": False}

    # 1. Privacy first: never send a child's address, phone or name anywhere (no LLM call).
    if _hard_pii(read, gaz) or NAME_GIVEN.search(q):
        return {**out, "action": "guard", "say": GUARD, "source": "arc" if read.get("available") else "rules"}

    target, corrected = _after_correction(text)
    out["corrected"] = corrected
    wants_crew = bool(WANTS_CREW.search(q))

    # 2. Misconceptions: gentle correction + a related moment as evidence.
    for pat, fix, pid in MISCONCEPTIONS:
        if pat.search(q):
            p = gaz.places.get(pid) if pid else None
            m = index.best_moment(pid) if pid else None
            return {**out, "action": "say", "say": _short(fix) if short else fix, "place": p.id if p else None,
                    "view": _view(p), "moment": public(m), "source": "misconception",
                    "claims": [{"text": fix, "status": "verified", "source": "fact sheet (misconception)"}]}

    # 3. "What does albedo mean?" -> glossary (useful while a crew moment plays).
    if DEFINE.search(q):
        for form, (term, explain) in index.glossary.items():
            if re.search(rf"\b{re.escape(form)}\b", q):
                return {**out, "action": "say", "say": f"{term.capitalize()}: {explain}", "source": "glossary",
                        "claims": [{"text": explain, "status": "verified", "source": "glossary"}]}

    # 4. Earthrise.
    if re.search(r"earth ?rise|see (the )?earth|earth from", target):
        m = index.best_in_clip("earthrise")
        return {**out, "action": "play" if m else "say", "say": EARTHRISE, "view": {"lat": 5, "lon": -100},
                "moment": public(m)}

    # 4b. Mission sounds ("play the launch", "what did liftoff sound like") -> the Artemis voices clip.
    for pat, clip_id, line in SOUNDS:
        if pat.search(target) and (SOUND_ASK.search(q) or clip_id in ("duke", "lovell")):
            m = _sound_moment(clip_id, target, index)
            if m:
                return {**out, "action": "play", "say": line, "moment": public(m), "source": "sounds"}

    # 4c. Hardware tours ("show me the rovers", "what's left on the Moon"), unless one artifact is named.
    named = gaz.match_text(target)
    if not (named and named.kind == "artifact"):
        tour = _tour(target, gaz)
        if tour and WHO.search(q):  # "who drove the rovers?" -> every crew, from the data
            crews = [f"{_names(p.crew)} on {p.mission}" for p in map(gaz.places.get, tour[0]) if p.crew]
            if crews:
                say = "These astronauts did: " + "; ".join(crews) + "."
                tour = (tour[0], say)
        if tour:
            return {**out, "action": "tour", "places": tour[0], "say": tour[1], "source": "tour"}

    # 5. Link a place: alias in the (corrected) words, else an Arc mention by fuzzy match (with an ask band).
    place, how, cands = _link(target, read, gaz)
    if place is None and corrected and not cands:
        place, how, cands = _link(q, read, gaz)
    if place is None and cands:
        names = [f"{p.name}" for p, _ in cands]
        question = f"Did you mean {names[0]}?" if len(names) == 1 else f"Did you mean {', '.join(names[:-1])} or {names[-1]}?"
        return {**out, "action": "ask", "say": question, "ask": {"question": question, "options": [p.id for p, _ in cands]},
                "place": cands[0][0].id, "view": _view(cands[0][0]), "source": "arc+link"}
    last = gaz.places.get(ctx.get("last_place") or "")
    if place is None and last and (MORE.search(target) or wants_crew or (last.kind == "artifact" and WHO.search(q))):
        place, how = last, "context"

    if place is None:
        if re.search(r"\b(far|back|dark|other) side\b", target):
            return {**out, "action": "view", "view": {"lat": 0, "lon": 180}, "say": _short(FAR) if short else FAR}
        if re.search(r"\b(near side|side we see|front)\b", target):
            return {**out, "action": "view", "view": {"lat": 0, "lon": 0}, "say": _short(NEAR) if short else NEAR}

    if place is not None and place.kind == "artifact":
        return await _artifact(place, text, q, {**out, "place": place.id, "view": _view(place), "source": how},
                               gaz, index, short)

    if place is not None:
        moment = index.best_moment(place.id)
        base = {**out, "place": place.id, "view": _view(place), "source": how}
        if wants_crew:  # crew request -> play the best moment, one bridge line
            if moment:
                return {**base, "action": "play", "say": _bridge(moment), "moment": public(moment)}
            say, cl, src = await claims.guide_line([place.id], text, gaz, index.facts, short=True)
            return {**base, "action": "fly", "say": f"{NO_MOMENT} {say}".strip(), "claims": cl,
                    "source": f"{how}+{src}"}
        say, cl, src = await claims.guide_line([place.id], text, gaz, index.facts, short=short)
        return {**base, "action": "fly", "say": say, "claims": cl, "moment": public(moment),
                "source": f"{how}+{src}"}

    # 6. Bored and nothing to act on: offer a mission.
    if emotion == "bored":
        return {**out, "action": "say", "say": MISSION, "source": "emotion"}

    # 7. Nothing matched: ask the LLM to pick a place, then claim-check whatever it says.
    ans = await llm.place_question(text, gaz) if llm.available() else None
    if ans and ans["place"]:
        p = gaz.places[ans["place"]]
        say, cl, src = await claims.guide_line([p.id], text, gaz, index.facts, short=short)
        return {**out, "action": "fly", "place": p.id, "view": _view(p), "say": say, "claims": cl,
                "moment": public(index.best_moment(p.id)), "source": f"llm+{src}"}
    if ans and ans["say"]:
        cl = await claims.verify_draft(ans["say"], [], gaz, index.facts)
        say = " ".join(c["text"] for c in cl if c["status"] == "verified")
        if say:
            return {**out, "action": "say", "say": _short(say) if short else say, "claims": cl, "source": "llm"}
    return {**out, "action": "say", "say": UNKNOWN, "source": "none"}
