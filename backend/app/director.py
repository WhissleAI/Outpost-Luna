"""The Director (docs/REVAMP.md §3.5): one kid turn -> one action, as rules over Arc Tagger's read-out.

Actions returned: guard | fly | play | say | ask | view. WAIT / NUDGE / PAUSE_EXPLAIN are client behaviours driven by
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
    who = "The crew" if who.lower() in ("crew", "unknown") else who.split()[0]
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
    if read.get("hard_pii") or ("private_name" in read.get("pii", []) and NAME_GIVEN.search(q)) or NAME_GIVEN.search(q):
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

    # 5. Link a place: alias in the (corrected) words, else an Arc mention by fuzzy match (with an ask band).
    place, how, cands = _link(target, read, gaz)
    if place is None and corrected and not cands:
        place, how, cands = _link(q, read, gaz)
    if place is None and cands:
        names = [f"{p.name}" for p, _ in cands]
        question = f"Did you mean {names[0]}?" if len(names) == 1 else f"Did you mean {', '.join(names[:-1])} or {names[-1]}?"
        return {**out, "action": "ask", "say": question, "ask": {"question": question, "options": [p.id for p, _ in cands]},
                "place": cands[0][0].id, "view": _view(cands[0][0]), "source": "arc+link"}
    if place is None and ctx.get("last_place") in gaz.places and (MORE.search(target) or wants_crew):
        place, how = gaz.places[ctx["last_place"]], "context"

    if place is None:
        if re.search(r"\b(far|back|dark|other) side\b", target):
            return {**out, "action": "view", "view": {"lat": 0, "lon": 180}, "say": _short(FAR) if short else FAR}
        if re.search(r"\b(near side|side we see|front)\b", target):
            return {**out, "action": "view", "view": {"lat": 0, "lon": 0}, "say": _short(NEAR) if short else NEAR}

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
