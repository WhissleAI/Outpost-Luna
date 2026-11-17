"""Kid-turn safety (P0, docs/ARC_FEEDBACK.md).

Three layers decide what a heard turn may do:

1. Arc Tagger 0.5's safety tags in the ``kids`` domain (model_server/app/arctag.py asks for EMIT=...safety...): each
   utterance carries ``safety: [{tag, p, thr, on}]``. A tag counts only when ``on`` is true and ``p >= thr``. The kids
   domain is calibrated on short kid turns and adds a guard layer: profanity / insult / threat as utterance tags, PII
   only with evidence in the words, rule backstops for self-harm and grooming. On a cockpit / mission screen the turn is
   sent with ``command_context`` on, so "kill the heaters" is a command, never a threat or a jailbreak.
2. An offline word list (this file; frontend/src/profanity.js is the same list): the backstop when the tagger is slow,
   off or misses a word (it did on the owner's "shit shit oh" before 0.5).
3. Narrow phrase backstops for crisis and grooming (CRISIS, GROOMING). The Arc team asked us to keep them: the kids
   domain's precision on these tags is 1.00, but its recall on indirect phrasings is about 0.5.

What each finding means (``classify``):
  - profanity / toxicity / child.inappropriate -> ``mask``: the words are masked wherever they show, and the turn is
    never graded as an answer or routed as a question (the router ignores it, silently).
  - crisis.self_harm / child.grooming_cue      -> ``care``: CAPCOM says one gentle line (CARE_LINE) and the session
    raises a flag for the parent / teacher side (``Session.flags``).
  - pii.*                                      -> ``pii``: the text stays out of the turn log. It never hides normal text
    on screen and never blocks the turn (the tagger's PII tag is often wrong: 0.99 "pii.leak" on "shit shit oh").
"""
from __future__ import annotations

import re

EXACT = set((
    "ass asses asshole assholes arse arsehole bastard bastards bitch bitches bitchy bollocks boner bullshit cock cocks "
    "crap crappy cum cunt cunts damn damned damnit dammit dick dicks dickhead dildo douche douchebag fag fags faggot "
    "faggots goddamn goddamnit horseshit jackass jerkoff motherfucker motherfuckers motherfucking nigga niggas nigger "
    "niggers piss pissed pisses pissing porn prick pricks pussy pussies retard retarded scrotum shag slut sluts smartass "
    "tit tits titty twat twats wank wanker wankers whore whores wtf stfu").split())
STEMS = re.compile(r"(fuck|fuk|fck|shit|sh1t|wank|bitch|nigg)")
WORD = re.compile(r"[A-Za-z0-9'’]+")

CARE_LINE = "Let's take a break. Talk to a grown-up you trust."
TAG_DOMAIN = "kids"   # Arc Tagger 0.5's kids / game domain (the Director's read-out stays on "assistant")
# Screens whose turns are cockpit / mission commands ("kill the heaters", "fire the thrusters"): Arc's command_context.
COMMAND_SCREENS = frozenset({"cabin", "brief", "ride"})

MASK_TAGS = ("safety.profanity", "safety.toxicity", "safety.child.inappropriate")
CARE_TAGS = ("safety.crisis.self_harm", "safety.child.grooming_cue")
PII_TAGS = ("safety.pii",)


def is_profane(word: str) -> bool:
    w = re.sub(r"['’]", "", (word or "").lower())
    return bool(w) and (w in EXACT or bool(STEMS.search(w)))


def has_profanity(text: str) -> bool:
    return any(is_profane(w) for w in WORD.findall(text or ""))


def mask_profanity(text: str) -> str:
    return WORD.sub(lambda m: m.group(0)[0] + "***" if is_profane(m.group(0)) else m.group(0), text or "")


def tags_on(safety) -> list[str]:
    """The tags Arc Tagger is sure of: ``on`` and ``p >= thr`` (a missing thr means the tagger's own ``on`` decides)."""
    out = []
    for s in safety or []:
        if not isinstance(s, dict) or not s.get("tag") or not s.get("on"):
            continue
        p, thr = s.get("p"), s.get("thr")
        try:
            if p is not None and thr is not None and float(p) < float(thr):
                continue
        except (TypeError, ValueError):
            continue
        out.append(str(s["tag"]))
    return out


# The tagger missed every one of these in our probes (docs/ARC_FEEDBACK.md): a small, specific backstop for the
# gentle care line. Specific phrases only, so "the shields kill the radiation" never triggers it.
CRISIS = re.compile(r"\b(kill(ing)? my ?self|hurt(ing)? my ?self|want to die|wanna die|end my life|suicide|"
                    r"cut(ting)? my ?self)\b")
# Grooming cues a kid may repeat or type (someone asking for pictures of them, secrecy from parents, a meeting, moving
# to another app). Specific phrases only: "show me a picture of the Moon" or "keep the secret base" never trigger it.
GROOMING = re.compile(r"\b((send|show|give) me (a |some )?(pic|pics|picture|pictures|photo|photos|selfie|selfies) of "
                      r"(yourself|you|ur ?self)\b|send (me )?(a |some )?(selfie|selfies|nudes)\b"
                      r"|(don'?t|do not|never) tell (your|ur) (mom|mum|dad|parents?|teacher|family)"
                      r"|(our|a) little secret|keep (it|this|us) (a )?secret from"
                      r"|(meet|meeting) (me|up) (in person|alone|after school)"
                      r"|add me on (snap|snapchat|insta|instagram|discord|whatsapp|tiktok|kik))")


def from_tag(resp: dict | None) -> list[dict]:
    """The safety list from POST /v1/tag (all utterances); [] when the tagger is off."""
    out: list[dict] = []
    for u in (resp or {}).get("utterances") or []:
        out += [s for s in (u.get("safety") or []) if isinstance(s, dict)]
    return out


TAGGER_BUDGET_S = 0.3   # a busy model server never holds a turn up: past this, the word list decides alone


def command_context(screen: str | None) -> bool:
    """True on a screen whose turns are cockpit / mission commands (Arc Tagger's command_context)."""
    return (screen or "") in COMMAND_SCREENS


async def tagger_read(text: str, command_context: bool = False) -> list[dict]:
    """Arc Tagger's safety list for a turn's words (POST /v1/tag, kids domain, ~20 ms locally); [] when the model server
    is off or slower than TAGGER_BUDGET_S (every turn waits for this, so it is capped)."""
    import asyncio

    from . import models_client
    try:
        return from_tag(await asyncio.wait_for(models_client.tag(text, TAG_DOMAIN, command_context=command_context),
                                               TAGGER_BUDGET_S))
    except (asyncio.TimeoutError, Exception):
        return []


def classify(text: str, safety=None) -> dict:
    """-> {"mask": bool, "care": bool, "pii": bool, "tags": [...], "words": bool} for a kid's turn."""
    tags = tags_on(safety)
    hit = lambda pre: any(t == p or t.startswith(p + ".") for t in tags for p in pre)  # noqa: E731
    words = has_profanity(text)
    low = (text or "").lower().replace("’", "'")
    crisis, grooming = bool(CRISIS.search(low)), bool(GROOMING.search(low))
    for on, tag in ((crisis, "safety.crisis.self_harm"), (grooming, "safety.child.grooming_cue")):
        if on and tag not in tags:
            tags = tags + [tag]
    return {"mask": words or hit(MASK_TAGS), "care": crisis or grooming or hit(CARE_TAGS), "pii": hit(PII_TAGS),
            "tags": tags, "words": words}
