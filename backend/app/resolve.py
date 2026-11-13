"""One kid turn -> what the app should do. The first, rule-based version of the Director (docs/REVAMP.md §3.5).

Inputs: the kid's text and Arc Tagger's read-out of it. Output: an action for the frontend.
  guard  - private details: don't look anything up, say a gentle line
  fly    - turn the globe to a place and say its fact
  play   - fly, then play the crew moment about that place
  view   - turn to a side of the Moon (near / far) with a line
  say    - just say something (LLM fallback or "I don't know")
"""
from __future__ import annotations

import re

from . import llm
from .gazetteer import Gazetteer, norm
from .moments import MomentIndex

CORRECTION = re.compile(r"\b(no wait|wait no|no no|i mean|sorry|actually|not that)\b")
WANTS_CREW = re.compile(r"\b(astronauts?|crew|hear|listen|what did|they say|say about|recording|play)\b")
NAME_GIVEN = re.compile(r"\b(my name is|my name s|i m called|call me)\b")

FAR = "This is the far side. It always faces away from Earth, so nobody saw it until spacecraft flew around. Artemis II astronauts saw it with their own eyes."
NEAR = "This is the near side, the face we always see from Earth. The dark patches are old lava seas."
EARTHRISE = "When Orion went behind the Moon, Earth came up over the edge. Listen to how the crew reacted!"
UNKNOWN = "I don't know that one yet. Try: “show me the giant bullseye” or “where did Apollo 11 land?”"
GUARD = "Let's keep names and addresses private! Ask me about a place on the Moon instead."


def _after_correction(text: str) -> tuple[str, bool]:
    q = norm(text)
    parts = CORRECTION.split(q)
    if len(parts) > 1:
        tail = parts[-1].strip()
        if len(tail.split()) >= 1:
            return tail, True
    return q, False


async def resolve(text: str, read: dict, gaz: Gazetteer, index: MomentIndex) -> dict:
    q = norm(text)
    base = {"text": text, "readout": read}

    # 1. Privacy first: never send a child's address, phone or name anywhere.
    if read.get("hard_pii") or ("private_name" in read.get("pii", []) and NAME_GIVEN.search(q)):
        return {**base, "action": "guard", "say": GUARD, "source": "arc"}

    target, corrected = _after_correction(text)
    wants_crew = bool(WANTS_CREW.search(q))

    # 2. Whole-Moon requests and Earthrise.
    if re.search(r"earth ?rise|see (the )?earth|earth from", target):
        clip = next((c for c in index.clips if c["id"] == "earthrise"), None)
        return {**base, "action": "play" if clip else "say", "say": EARTHRISE, "view": {"lat": 5, "lon": -100},
                "clip": {"id": "earthrise", "t": 0} if clip else None, "source": "rules"}

    # 3. A place: alias in the (corrected) words, else a tagger mention linked by fuzzy match.
    place, how = gaz.match_text(target), "alias"
    if place is None:
        for m in read.get("mentions", []):
            if norm(m) in target:
                hit = gaz.link(m)
                if hit:
                    place, how = hit[0], "arc+link"
                    break
    if place is None and corrected:
        place, how = gaz.match_text(q), "alias"

    if place is None:
        if re.search(r"\b(far|back|dark|other) side\b", target):
            return {**base, "action": "view", "view": {"lat": 0, "lon": 180}, "say": FAR, "source": "rules"}
        if re.search(r"\b(near side|side we see|front)\b", target):
            return {**base, "action": "view", "view": {"lat": 0, "lon": 0}, "say": NEAR, "source": "rules"}

    if place is not None:
        moment = index.best_for(place.id)
        play = wants_crew and moment is not None
        return {**base, "action": "play" if play else "fly", "place": place.id, "corrected": corrected,
                "lead": "Here's what the crew said." if play else "", "clip": moment if play else None,
                "crew_available": moment is not None, "source": how}

    # 4. Nothing matched: ask the LLM to pick a place, if configured.
    ans = await llm.place_question(text, gaz) if llm.available() else None
    if ans and ans["place"]:
        return {**base, "action": "fly", "place": ans["place"], "lead": ans["say"],
                "crew_available": index.best_for(ans["place"]) is not None, "source": "llm"}
    if ans and ans["say"]:
        return {**base, "action": "say", "say": ans["say"], "source": "llm"}
    return {**base, "action": "say", "say": UNKNOWN, "source": "none"}
