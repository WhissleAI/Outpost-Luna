"""The Director (docs/REVAMP.md §3.5): one kid turn -> one action, as rules over Arc Tagger's read-out.

Actions returned: guard | fly | play | say | ask | view | tour (a list of artifacts: "show me the rovers"). WAIT / NUDGE / PAUSE_EXPLAIN are client behaviours driven by
the fields here (`readout.complete`, `moment.jargon`). What to say comes from knowledge cards (app/knowledge, templates
filled from the sourced data); what the kid means comes from rules + Arc Tagger, and the tiny local embedder when those
don't settle it. No cloud LLM (docs/LOCAL_BRAIN.md). Every place line still goes through the claim check (claims.py).
Response shape: docs/CONTRACT.md. Mission mode (`context.mission` set): the mission layer answers first, see
_mission_turn and docs/MISSION_CONTRACT.md.
"""
from __future__ import annotations

import inspect
import re

from . import claims, knowledge, steering
from .knowledge.answer import detect_attr, did_you_mean
from .mission import capcom, nlu
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
     "These rovers are still parked on the Moon. Tap one to hear its story."),
    (re.compile(r"\b(landers|landing sites|lunar modules|where (did|have) (people|astronauts|we) landed?)\b"), {"lander"},
     "Every spacecraft that landed here and stayed. Tap one to hear its story."),
    (re.compile(r"\b(crash(es| sites)|impacts?( sites)?|crashed)\b"), {"impact"},
     "Crash sites. Many spacecraft hit the Moon on purpose, for science."),
    (re.compile(r"\b(instruments|experiments|science stations|mirrors|reflectors)\b"), {"instrument"},
     "Science tools left on the Moon. One mirror still bounces lasers back to Earth."),
    (re.compile(r"\b(hardware|junk|trash|left (behind )?on the moon|left behind|left there|left on it|stuff (on|left)|"
                r"things (on|left)|abandoned|ghost|what s on the moon|spacecraft on the moon|machines)\b"), None,
     "Landers, rovers, science tools and crash sites. Tap one to hear its story."),
]
WHO = re.compile(r"\b(who (left|drove|put|flew|landed|built|sent|parked|rode|brought|made|used|set)|who was (in|on|driving)|"
                 r"whose|who did)\b")
HEAR_VOICE = re.compile(r"\b(hear|listen|voice|message|play)\b")
SOUNDS = [  # mission sounds from the NASA Artemis Audio Library (set "voices")
    (re.compile(r"\b(go no go|countdown|count down|poll)\b"), "go-no-go", "Mission control asks every team: go or no-go?"),
    (re.compile(r"\b(launch|liftoff|lift off|blast ?off|take ?off|rocket start)\b"), "liftoff",
     "Artemis II lifting off. Listen!"),
    (re.compile(r"\bfull send\b"), "full-send", "Before launch, the crew said who they flew for. Listen."),
    (re.compile(r"\b(translunar|tli|go for the moon|head(ed|ing)? to the moon)\b"), "tli",
     "Houston gives the go for the Moon. Listen!"),
    (re.compile(r"\b(good burn|engine burn|burn)\b"), "good-burn", "Here's the engine burn. Listen!"),
    (re.compile(r"\b(distance record|farthest|furthest|apollo 13 record|broke the record|record)\b"), "apollo13-record",
     "Artemis II flew farther from Earth than Apollo 13. Listen!"),
    (re.compile(r"\b(splash ?down|splash|landed in the (ocean|sea|water)|coming home|came home)\b"), "splashdown",
     "Orion splashing down in the ocean. Listen!"),
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
        return f"No one. {p.name} was a robot, sent by {p.agency}."
    verb = "drove" if p.type == "rover" else "landed" if p.type == "lander" else "left"
    return f"{_names(p.crew)} {verb} it, on {p.mission}."


def _sound_moment(clip_id: str, q: str, index: MomentIndex) -> dict | None:
    ms = [m for m in index.moments if m["clip_id"] == clip_id and m["kid_safe"]]
    if not ms:
        return None
    key = {"liftoff": "lift", "splashdown": "splashdown", "apollo13-record": "record", "go-no-go": "go"}.get(clip_id)
    hit = [m for m in ms if key and key in m["text"].lower()]
    return hit[0] if hit else index.best_in_clip(clip_id)


async def _artifact(p: Place, text: str, q: str, base: dict, gaz: Gazetteer, index: MomentIndex, short: bool,
                    sess: str = "") -> dict:
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
    # "When did Eagle land?", "where is it now?", "what science did it do?" -> that attribute's card line.
    attr = detect_attr(q)
    if attr in ("when", "where", "science", "what"):
        ans = knowledge.get(gaz, index.facts).for_card(f"artifact:{p.id}", text, sess)
        if ans and ans["attr"] == attr:
            cl = await claims.verify_draft(ans["say"], [p.id], gaz, index.facts)
            say = " ".join(c["text"] for c in cl if c["status"] == "verified")
            if not say:  # template lines are data fields verbatim: say it, sourced to the card
                say, cl = ans["say"], cl + [{"text": ans["say"], "status": "verified", "source": "artifacts.json (card)"}]
            return {**base, "action": "fly", "say": say, "claims": cl, "moment": public(voice), "style_hint": ans["style_hint"],
                    "source": base["source"] + f"+card:{attr}"}
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

FAR = "The far side. It always faces away from Earth."
NEAR = "The near side, the face we always see. The dark patches are old lava."
EARTHRISE = "Behind the Moon, the crew watched Earth rise. Listen!"
SAY_AGAIN = "Say again? I missed that."
# Spoken: the short line only. The examples are shown on the card (TRY), never spoken: a spoken example command
# ("show me the giant bullseye") heard back through the speakers by the open mic would be answered as a new turn.
UNKNOWN = "I don't know that one yet."
TRY = "Try: “show me the giant bullseye” or “where did Apollo 11 land?”"
GUARD = "Let's keep names and addresses private. Ask me about the Moon."
MISSION = "Want a mission? Find the giant bullseye on the far side."
NO_MOMENT = "The crew didn't talk about this place. Here it is."

# Kid claims that contradict the fact sheet -> gentle correction (pre-verified text) + an optional related place.
MISCONCEPTIONS = [
    (re.compile(r"\b(made (of|out of) cheese|is cheese|cheese moon)\b"),
     "Not cheese. The Moon is rock and dust. But the crew saw one spot look yellow.",
     "aristarchus"),
    (re.compile(r"\b(no craters|doesn t have (any )?craters|has no craters|not have craters|smooth)\b"),
     "The Moon is covered in craters, made by space rocks. Here's a giant one.", "orientale"),
    (re.compile(r"\b(makes (its|it s) own light|moon glows by itself|own light|moon is a star)\b"),
     "The Moon makes no light of its own. It shines with bounced sunlight.", None),
    (re.compile(r"\b(dark side (never|doesn t|does not) (get|see|have) (any )?(sun|light)|always dark on the (dark|far) side)\b"),
     "The far side gets sunlight too. We just never see it from Earth.", "hertzsprung"),
    (re.compile(r"\b(moon is bigger than (the )?earth|moon is (a )?planet)\b"),
     "The Moon is smaller than Earth. It circles us.", None),
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


# The ear's link decision (Arc Transcriber Space names[i].p, docs/SPEECH_SIGNALS_AUDIT.md section 3): on the round-11
# Mac-voice decodes a link with p >= LINK_ACT_P named the place the kid said 88 % of the time, one below it 47 %. A link
# under it is not acted on: the place is offered back ("Did you mean Tycho?"), unless what the ear heard (its spoken
# words, not the list spelling it wrote over them) names a place by itself.
LINK_ACT_P = 0.99
# "Almost linked": no link and no alias, but a span of the heard words sounds like a place name (soundalike.similar):
# offered back as a question, never acted on. Calibrated on the same decodes (section 3).
NEAR_SCORE = 0.8


def _near_vocab(gaz: Gazetteer) -> list[str]:
    v = getattr(gaz, "_near_vocab", None)
    if v is None:
        from .entities import registry
        v = []
        for e in registry().entities:
            if e.ear and place_of(e.id, gaz) is not None:
                v += [f for f in e.forms() if len(f) >= 5]
        v += [p.name for p in gaz.places.values()]
        gaz._near_vocab = v
    return v


def place_of(eid: str | None, gaz: Gazetteer) -> Place | None:
    """The gazetteer place an entity id stands for: the registry's `ref` (places.json / artifacts.json ids are the
    gazetteer's), else the entity's canonical name in the gazetteer."""
    from .entities import registry
    e = registry().get(eid)
    if e is None:
        return None
    r = e.ref or {}
    if r.get("source") in ("places.json", "artifacts.json") and r.get("id") in gaz.places:
        return gaz.places[r["id"]]
    if e.type in ("place", "hardware"):
        return gaz.match_text(e.name)
    return None


def ear_place(entity: str | None, gaz: Gazetteer) -> Place | None:
    """A linked name (the list's spelling) -> its place, by id through the registry; the text match as a fallback for
    names the registry does not know (a client's own context names)."""
    from .entities import registry
    e = registry().resolve(entity or "", prefer=("place", "hardware", "site"))
    if e is not None:
        return place_of(e.id, gaz)
    return gaz.match_text(entity or "") if entity else None


def near_name(heard: str, gaz: Gazetteer, min_score: float = NEAR_SCORE) -> tuple[Place, float] | None:
    """The place a span of the heard words sounds like ("the jelly" ~ "de Gerlache"), or None."""
    from . import soundalike
    if not heard or not heard.strip():
        return None
    b = soundalike.best_span(heard, _near_vocab(gaz), min_score)
    if b is None:
        return None
    p = gaz.match_text(b[1])
    return (p, b[2]) if p is not None else None


def _link(target: str, read: dict, gaz: Gazetteer) -> tuple[Place | None, str, list[tuple[Place, float]]]:
    """-> (place, how, ask_candidates). ask_candidates is set when the link is in the ask band ("ask": "did you mean
    A or B?") or needs a yes ("confirm": a low-p link, "near": a sound-alike; one candidate, "did you mean A?").

    The ear's names come first (read["ear_names"], Arc Transcriber Space linking what was said to the screen's names
    list): `linked` with p >= LINK_ACT_P -> that entry's place; `linked` below it -> what the ear HEARD (read["ear_spoken"],
    before the list spelling replaced it) is matched instead, else the entry is offered back (confirm); `abstain`
    (unsure, or only generic words) -> the gazetteer's candidates for what was heard, asked as "did you mean ...?" when
    two are close; `not_in_list` -> what was heard is searched in the whole gazetteer, like an Arc Tagger mention.
    Last, a span of the heard words that SOUNDS like a place (near_name) is offered back ("near"), never acted on."""
    ear = [n for n in read.get("ear_names") or [] if isinstance(n, dict)]
    spoken = read.get("ear_spoken")
    low: list[tuple[Place, float]] = []
    for n in ear:
        if n.get("state") == "linked" and n.get("entity"):
            p = ear_place(n["entity"], gaz)     # by id (registry), not by re-matching the text
            if not p:
                continue
            lp = n.get("p")
            if lp is None or lp >= LINK_ACT_P:
                return p, "ear_link", []
            low.append((p, 100.0 * float(lp)))
    if low:
        # the heard words name ANOTHER place by themselves: that one. The same place (the linker is unsure of exactly
        # these words, "Fly Tycho pelicus" for "fly to Copernicus") or none: offered back.
        p = gaz.match_text(spoken) if spoken else None
        if p and all(p.id != c[0].id for c in low):
            return p, "alias", []
        return None, "confirm", low[:1]
    p = gaz.match_text(target)
    if p:
        return p, "alias", []
    for n in ear:
        h = norm(n.get("heard") or "")
        if n.get("state") == "abstain" and h:
            cands = [c for c in gaz.candidates(h) if c[1] >= ASK_LO]
            if len(cands) >= 2:
                return None, "ask", cands[:2]
            if cands and cands[0][1] >= ACCEPT:
                return cands[0][0], "ear_heard", []
    mentions = [norm(n["heard"]) for n in ear if n.get("state") == "not_in_list" and norm(n.get("heard") or "")]
    mentions += [m for m in read.get("mentions", []) if norm(m) and norm(m) in target]
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
    if "ear_names" in read:     # a heard turn (the ear ran): a known mishearing ("the jelly"), then a sound-alike
        from .entities import registry
        mh = registry().mishear_of(spoken or target)
        mp = place_of(mh[0].id, gaz) if mh else None
        if mp is not None:
            return None, "near", [(mp, 100.0)]
        nm = near_name(spoken or target, gaz)
        if nm is not None:
            return None, "near", [(nm[0], 100.0 * nm[1])]
    return None, "", []


async def direct(text: str, read: dict, gaz: Gazetteer, index: MomentIndex, context: dict | None = None) -> dict:
    """One kid turn -> the old single-action response (docs/CONTRACT.md), plus `decisions:[…]` (docs/SESSION_CONTRACT.md
    §2): the same answer as typed, ordered decisions. The session Director (session.py) adds proactive ones around them."""
    out = await _direct(text, read, gaz, index, context)
    ctx = dict(context or {})
    p = gaz.places.get(out.get("place")) if out.get("place") else None
    if p is not None:
        ctx["place_name"] = p.name
    out["decisions"] = decisions_for(out, text, ctx)
    out.pop("style_hint", None)            # carried on the say decision (the voice-steering policy reads it), not the contract
    out.pop("hint", None)                  # on the card decision only (the client shows TRY when source is "none")
    brain = out.pop("brain", None)
    if brain and out.get("readout") is not None:
        out["readout"] = {**out["readout"], "brain": brain}
    return out


async def _direct(text: str, read: dict, gaz: Gazetteer, index: MomentIndex, context: dict | None = None) -> dict:
    ctx = context or {}
    sess = str(ctx.get("session") or "")
    q = norm(text)
    emotion = (ctx.get("emotion") or "").lower()
    short = emotion in ("confused", "frustrated")
    out = {"action": "say", "say": "", "place": None, "view": None, "moment": None, "ask": None, "claims": [],
           "readout": read, "source": "rules", "corrected": False}

    # 1. Privacy first: never send a child's address, phone or name anywhere (no LLM call).
    if _hard_pii(read, gaz) or NAME_GIVEN.search(q):
        return {**out, "action": "guard", "say": GUARD, "source": "arc" if read.get("available") else "rules"}

    # 1b. Mission mode: commands, status, Houston. Non-mission questions fall through to the Moon explorer below.
    if ctx.get("mission"):
        m = await _mission_turn(text, read, ctx, out, index)
        if m is not None:
            return m

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
        question = did_you_mean(names)
        return {**out, "action": "ask", "say": question, "ask": {"question": question, "options": [p.id for p, _ in cands], "labels": names},
                "place": cands[0][0].id, "view": _view(cands[0][0]),
                "source": {"confirm": "ear_confirm", "near": "ear_near"}.get(how, "arc+link")}
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
                               gaz, index, short, sess)

    if place is not None:
        moment = index.best_moment(place.id)
        base = {**out, "place": place.id, "view": _view(place), "source": how}
        if wants_crew:  # crew request -> play the best moment, one bridge line
            if moment:
                return {**base, "action": "play", "say": _bridge(moment), "moment": public(moment)}
            say, cl, src = await claims.guide_line([place.id], text, gaz, index.facts, short=True, session=sess)
            return {**base, "action": "fly", "say": f"{NO_MOMENT} {say}".strip(), "claims": cl,
                    "source": f"{how}+{src}"}
        say, cl, src = await claims.guide_line([place.id], text, gaz, index.facts, short=short, session=sess)
        return {**base, "action": "fly", "say": say, "claims": cl, "moment": public(moment),
                "source": f"{how}+{src}"}

    # 6. Bored and nothing to act on: offer a mission.
    if emotion == "bored":
        return {**out, "action": "say", "say": MISSION, "source": "emotion"}

    # 7. Nothing matched: the local brain. Card alias + attribute rules, else the embedder's nearest card+attribute
    #    (accept -> answer, ask band -> "Did you mean A or B?", below -> an honest "I don't know that one yet").
    return await _brain_turn(text, out, gaz, index, sess, short)


async def _brain_turn(text: str, out: dict, gaz: Gazetteer, index: MomentIndex, sess: str, short: bool) -> dict:
    brain = knowledge.get(gaz, index.facts)
    ans = await brain.answer(text, session=sess)
    base = {**out, "style_hint": ans["style_hint"], "brain": {k: ans[k] for k in ("card", "attr", "score", "status")}}
    if ans["status"] in ("ask", "unknown") and ans["options"]:
        sends = [o["send"] for o in ans["options"]]
        return {**base, "action": "ask", "say": ans["say"], "ask": {"question": ans["say"], "options": sends, "labels": sends},
                "source": ans["source"]}
    if ans["status"] != "answer":
        return {**base, "action": "say", "say": UNKNOWN, "hint": TRY, "source": "none"}
    say = _short(ans["say"]) if short else ans["say"]
    card = brain.cards[ans["card"]]
    p = gaz.places.get(ans["place"] or "")
    if p:
        cl = await claims.verify_draft(say, [p.id], gaz, index.facts)
        ok = " ".join(c["text"] for c in cl if c["status"] == "verified")
        if not ok:
            ok, cl = say, cl + [{"text": say, "status": "verified", "source": f"{card['kind']} card (data fields)"}]
        return {**base, "action": "fly", "place": p.id, "view": _view(p), "say": ok, "claims": cl,
                "moment": public(index.best_moment(p.id)), "source": f"{ans['source']}+claimcheck"}
    src = (card["sources"][0].get("title") if card["sources"] else "") or f"{card['kind']} card"
    return {**base, "action": "say", "say": say, "claims": [{"text": say, "status": "verified", "source": src}],
            "source": ans["source"]}


# ---- mission mode (docs/MISSION_CONTRACT.md "/api/ask in mission mode") -----------------------------------------------
# The sim lives in app/mission/registry.py (another work stream). It is called through this thin adapter only:
# registry.get(mid) -> a mission (State dict, or an object with .state()/.to_dict()) and mission.apply(cmd)
# (or registry.apply(mid, cmd)) -> {"state": State, "result": {ok, needs_confirm?, say, readback, events}}.
NOT_STARTED = "No mission yet. Pick a landing site first."
CHATTER_DD = 0.5          # Arc device_directed under this, and no command: the kid is talking to the team, not to us
RULES: dict[str, list[dict]] = {}       # mid -> standing orders [{"rule": Command, "armed": bool}]
PENDING: dict[str, dict] = {}           # mid -> {"commands": [...], "role": needed role} waiting for another officer


def _sim():
    try:
        from .mission import registry  # type: ignore[attr-defined]
    except ImportError:
        return None
    return registry


async def _maybe(v):
    return await v if inspect.isawaitable(v) else v


def _as_state(m) -> dict | None:
    if m is None or isinstance(m, dict):
        return m
    for a in ("state", "to_dict", "public", "model_dump"):
        f = getattr(m, a, None)
        if isinstance(f, dict):
            return f
        if callable(f):
            try:
                r = f()
            except TypeError:
                continue
            if isinstance(r, dict):
                return r
    return None


async def _sim_state(reg, mid: str | None) -> dict | None:
    if reg is None or not mid:
        return None
    try:
        return _as_state(await _maybe(reg.get(mid)))
    except Exception:  # noqa: BLE001 (unknown mission id, sim error)
        return None


async def _sim_apply(reg, mid: str, cmd: dict) -> tuple[dict | None, dict]:
    m = await _maybe(reg.get(mid))
    if m is not None and callable(getattr(m, "apply", None)):
        r = await _maybe(m.apply(cmd))
    else:
        r = await _maybe(reg.apply(mid, cmd))
    if isinstance(r, dict) and "result" in r:
        return _as_state(r.get("state")) or await _sim_state(reg, mid), r["result"] or {}
    return await _sim_state(reg, mid), (r if isinstance(r, dict) else {"ok": bool(r)})


TRIGGER_ON = {
    "storm": lambda s: bool(((s.get("env") or {}).get("storm") or {}).get("active")),
    "low_power": lambda s: ((s.get("resources") or {}).get("power_pct") or 100) < 25,
    "low_oxygen": lambda s: ((s.get("resources") or {}).get("life_support_pct") or 100) < 30,
    "dark": lambda s: (s.get("env") or {}).get("in_sun") is False,
    "comm_closed": lambda s: (s.get("env") or {}).get("earth_visible") is False,
    "dose_high": lambda s: ((s.get("resources") or {}).get("dose_msv") or 0) >=
                           0.8 * ((s.get("resources") or {}).get("dose_limit_msv") or 1e9),
}


def due_rules(mid: str, state: dict | None) -> list[dict]:
    """Standing orders whose trigger just became true (each fires once per time its trigger turns on)."""
    if not state:
        return []
    fire = []
    for r in RULES.get(mid, []):
        on = TRIGGER_ON.get(r["rule"]["when"], lambda s: False)(state)
        if on and r["armed"]:
            fire.append(r["rule"]["then"])
        r["armed"] = not on
    return fire


def _tone(say: str, emotion: str) -> str:
    if emotion in ("confused", "frustrated"):
        return capcom.short(say)
    if emotion == "excited":
        return capcom.excited(say)
    return say


def linked_entity(read: dict, types: tuple[str, ...]):
    """The registry entity the ear linked on this turn with p >= LINK_ACT_P, of one of these types (or None)."""
    from .entities import registry
    for n in read.get("ear_names") or []:
        if isinstance(n, dict) and n.get("state") == "linked" and n.get("entity") and \
                (n.get("p") is None or n["p"] >= LINK_ACT_P):
            e = registry().resolve(n["entity"], prefer=types)
            if e is not None and e.type in types:
                return e
    return None


async def _mission_turn(text: str, read: dict, ctx: dict, out: dict, index: MomentIndex) -> dict | None:
    """Mission layer first. None = not a mission turn (the Moon explorer answers)."""
    mctx = ctx.get("mission") or {}
    mid, role = mctx.get("id"), mctx.get("role")
    emotion = (ctx.get("emotion") or "").lower()
    reg = _sim()
    state = await _sim_state(reg, mid)
    base = {**out, "source": "mission", "mission": mid}

    if DEFINE.search(norm(text)) and not ctx.get("commands"):
        g = capcom.glossary_line(text, None)   # mission words; Moon words fall through to the app glossary
        if g:
            return {**base, "action": "say", "say": _tone(g, emotion), "source": "mission+glossary"}

    if ctx.get("commands"):   # the learned Director (DIRECTOR_MODEL=on) read the command; it passed nlu.valid()
        nl = {"commands": [c for c in map(nlu.valid, ctx["commands"]) if c], "confidence": 0.8, "needs_clarify": None,
              "source": "model"}
    else:
        nl = await nlu.understand(text, read, state)
    cmds, dd = nl["commands"], ctx.get("device_directed")
    site = linked_entity(read, ("site",))
    for c in cmds:     # the rover's target: the site the ear linked (by id), not the raw words after "to"
        if c.get("type") == "dispatch" and site is not None and c.get("task") in ("explore", "collect_ice"):
            c["target"], c["target_id"] = site.name, site.id
    if not cmds and not nl["needs_clarify"]:
        if dd is not None and float(dd) < CHATTER_DD:
            return {**base, "action": "none", "say": "", "source": "mission+chatter"}
        return None
    base["source"] = f"mission+{nl['source']}"
    base["nlu"] = {"commands": cmds, "confidence": nl["confidence"]}
    if nl["needs_clarify"]:
        q = nl["needs_clarify"]
        return {**base, "action": "ask", "say": _tone(q, emotion), "ask": {"question": q, "options": []}}

    lines: list[str] = []
    # Standing orders whose moment has come go first.
    if reg is not None and mid:
        for then in due_rules(mid, state):
            state, res = await _sim_apply(reg, mid, then)
            lines.append("Standing order! " + (capcom.readback(then, state, mid)))

    resp: dict = {}
    for cmd in cmds:
        ty = cmd["type"]
        if ty == "query":
            lines.append(capcom.status(cmd["what"], state, mid))
            resp = resp or {"action": "status", "state": state}
            continue
        if ty == "call_houston":
            say, delay = capcom.houston(cmd.get("text") or "", state, mid)
            lines.append(say)
            resp = {"action": "houston", "delay_ms": delay, "command": cmd, "state": state}
            continue
        if ty == "rule":
            RULES.setdefault(mid or "-", []).append({"rule": cmd, "armed": True})
            lines.append(capcom.readback(cmd, state, mid))
            resp = resp or {"action": "command", "command": cmd, "needs_confirm": False, "state": state}
            continue
        if ty == "confirm" and mid in PENDING:
            p = PENDING[mid]
            if role and p["role"] and role != p["role"]:
                lines.append(f"We need the {capcom.ROLE_NAME.get(p['role'], p['role'])} to agree.")
                resp = resp or {"action": "command", "command": cmd, "needs_confirm": True, "state": state}
                continue
            PENDING.pop(mid)
            for c in p["commands"]:
                state, res = await _sim_apply(reg, mid, c) if reg else (state, {})
                lines.append(capcom.readback(c, state, mid))
            resp = resp or {"action": "command", "command": p["commands"][0], "needs_confirm": False, "state": state}
            continue
        if ty == "cancel" and mid in PENDING:
            PENDING.pop(mid)
            lines.append(capcom.readback(cmd))
            resp = resp or {"action": "command", "command": cmd, "needs_confirm": False, "state": state}
            continue
        gate = capcom.role_check(cmd, role)
        if gate:
            PENDING[mid] = {"commands": [cmd], "role": capcom.ROLE_OF.get(ty)}
            lines.append(gate)
            resp = resp or {"action": "command", "command": cmd, "needs_confirm": True, "state": state,
                            "needs_role": capcom.ROLE_OF.get(ty)}
            continue
        if reg is None or state is None:
            return {**base, "action": "say", "say": NOT_STARTED, "command": cmd}
        state, res = await _sim_apply(reg, mid, cmd)
        rb = capcom.readback(cmd, state, mid)
        if res.get("needs_confirm"):
            lines.append(rb if "?" in rb else f"{rb} Are you sure?")
        else:
            lines.append(rb)
            same = ty == "allocate" and (cmd.get("amount") or {}).get("kind") == "percent"   # already in the readback
            if res.get("say") and res["say"] != rb and not same:
                # The sim's own line adds the result ("Shields now gets 40%"); drop its "Copy." so CAPCOM says it once.
                extra = re.sub(r"^\s*copy[,.!]?\s*", "", res["say"], flags=re.I)
                # [playtest 27] the sim's line often opens with the readback's own words ("Crew in the shelter.
                # Crew in the shelter. Much less radiation"): say them once
                body = capcom._strip_copy(rb).strip()
                if body and extra.lower().startswith(body.lower()):
                    extra = extra[len(body):].strip()
                if extra:
                    lines.append(extra)
        resp = resp or {"action": "command", "command": cmd, "needs_confirm": bool(res.get("needs_confirm")),
                        "state": state, "events": res.get("events") or []}
        if res.get("needs_confirm"):
            resp["needs_confirm"] = True
    if resp.get("action") in ("command", "houston") and len(cmds) > 1:
        resp["commands"] = cmds
    if resp.get("action") in ("status", "command") and state is not None:
        resp["state"] = state  # the LAST state: with several commands in one turn, the client must see all of them
    # one "Copy." per turn, however many commands
    lines = [x if i == 0 else re.sub(r"^(Copy, commander\.|Copy\.)\s+", "", x) for i, x in enumerate(y for y in lines if y)]
    say = _tone(" ".join(lines), emotion)
    if resp.get("action") == "command":
        # UI contract: a command response always carries `state` = the server already handled it (applied through the
        # sim, stored as a standing order, or held for confirmation). The client never POSTs it again. needs_confirm
        # -> nothing applied yet; the client shows Yes/No and sends "yes"/"no" as the next /api/ask.
        resp["applied"] = not resp.get("needs_confirm") and resp["command"]["type"] not in ("rule", "cancel")
        resp["readback"] = say
    return {**base, **resp, "say": say}


# ---- decisions (docs/SESSION_CONTRACT.md §2) --------------------------------------------------------------------------
# Priorities (§3 rule 6): 0 safety/privacy guard, 1 kid barge-in, 2 critical alert, 3 answer to the kid,
# 4 lesson/mission narration, 5 nudges.
P_GUARD, P_BARGE, P_CRITICAL, P_ANSWER, P_NARRATION, P_NUDGE = 0, 1, 2, 3, 4, 5
_seq = [0]


def new_id(prefix: str = "d") -> str:
    _seq[0] += 1
    return f"{prefix}-{_seq[0]}"


def decision(t: str, priority: int = P_ANSWER, after: str | None = None, situation: str | None = None,
             emotion: str | None = None, places: list[str] | None = None, **payload) -> dict:
    """One typed decision. Every `say` carries `style` (backend/app/steering.py): from the situation, the kid's affect
    and the persona voice, unless the caller passes one."""
    if t == "say" and "style" not in payload:
        payload["style"] = steering.style_for(payload.get("voice") or "guide", payload.get("text") or "",
                                              situation=situation, emotion=emotion, places=places)
    d = {"t": t, "id": new_id(), "priority": priority, **{k: v for k, v in payload.items() if v is not None}}
    if after:
        d["after"] = after
    return d


YES = {"t": "typed", "text": "yes"}
STYLE_HINT = {"ask": "question", "houston": "alert", "fly": "story", "play": "story", "tour": "story", "guard": "alert",
              "command": "explain", "status": "explain"}  # default `style_hint` per action (cards set their own)
NO = {"t": "typed", "text": "no"}


# The local brain's template hints -> a voice-steering situation when the rules name none.
_HINT_SITUATION = {"explain": "explain", "story": "story", "question": None, "alert": "storm_warning"}


def decisions_for(r: dict, asked: str = "", ctx: dict | None = None) -> list[dict]:
    """The single-action response -> ordered typed decisions. Visual decisions first (they apply at once), then speech;
    anything that must wait for the line (crew audio, Yes/No) carries `after` = the say's id."""
    a, say = r.get("action"), (r.get("say") or "").strip()
    ctx = ctx or {}
    mission = r.get("source", "").startswith("mission") or a in ("command", "status", "houston")
    voice = "houston" if a == "houston" else "capcom" if mission else "guide"
    steer = {"situation": steering.situation_for(r) or _HINT_SITUATION.get(r.get("style_hint")), "emotion": ctx.get("emotion"),
             "places": [ctx["place_name"]] if ctx.get("place_name") else None}
    title = "CAPCOM" if mission else "Guide"
    out: list[dict] = []
    if a == "none":
        return out
    if a == "guard":
        out.append(decision("card", P_GUARD, title="Let's keep that private", body=say, asked=asked or None))
        out.append(decision("say", P_GUARD, text=say, voice="guide", situation="guard"))
        return out
    if r.get("state") is not None and a in ("command", "status", "houston"):
        out.append(decision("hud", P_ANSWER, state=r["state"]))
    if a in ("fly", "play", "view") and (r.get("place") or r.get("view")):
        out.append(decision("fly", P_ANSWER, place=r.get("place"), view=r.get("view")))
    if a == "tour" and r.get("places"):
        out.append(decision("highlight", P_ANSWER, ids=r["places"]))
    actions = []
    if a == "ask" and r.get("ask"):
        actions = [{"label": o, "send": {"t": "typed", "text": o}} for o in (r["ask"].get("labels") or r["ask"].get("options") or [])]
    body = f"{say} {r['hint']}".strip() if r.get("hint") else say   # examples are shown, never spoken
    card = decision("card", P_ANSWER, title=title, body=body, asked=asked or None, chips=[], actions=actions,
                    place=r.get("place"), claims=r.get("claims") or None, readout=r.get("readout"),
                    source=r.get("source"), action=a)
    out.append(card)
    if say:
        s = decision("say", P_ANSWER, text=say, voice=voice, delay_ms=r.get("delay_ms") if a == "houston" else None,
                     style_hint=r.get("style_hint") or STYLE_HINT.get(a, "explain"), **steer)
        out.append(s)
    else:
        s = None
    if a == "play" and r.get("moment"):
        m = r["moment"]
        out.append(decision("play", P_ANSWER, after=s["id"] if s else None, moment=m, clip_id=m.get("clip_id") or m.get("clip"),
                            t0=m.get("t0"), t1=m.get("t1"), explain=m.get("jargon") or []))
    if r.get("needs_confirm") and a == "command":
        out.append(decision("ask_confirm", P_ANSWER, after=s["id"] if s else None, text=say or "Are you sure?", yes=YES, no=NO))
    return out
