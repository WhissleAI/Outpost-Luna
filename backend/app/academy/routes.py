"""Academy API: GET /api/academy/course, POST /api/academy/attempt, POST /api/academy/ride.

Progress lives on the device (localStorage, no names). Each attempt also returns `decisions` in the session-contract
shape (docs/SESSION_CONTRACT.md: `lesson` + `say`), so a session Director can relay them unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Literal

from pydantic import BaseModel, Field

from .. import safety as safety_, steering
from . import arch_steps, content, guide, ride as rides
from .grade import FIELD_TYPES, REVEAL_AFTER, grade, plausible, references, reveal_due, similar, text_only
from . import feedback as fb, speech
from .speech import SPEECH_TYPES

router = APIRouter()
from .vocab import router as _vocab_router  # noqa: E402  (GET /api/glossary: Space words, docs/VOCABULARY.md)
router.include_router(_vocab_router)
HINT_AFTER = 1   # misses before the hint (the hint ladder: app/academy/guide.py)
SHOW_AFTER = REVEAL_AFTER   # real misses (and >= 20 s open: grade.reveal_due) before CAPCOM shows the answer (§5)
SHOWN = "Here it is. "
GUESS_RIGHT = "You guessed it! "     # a video step's guess chip, checked after the video (or Skip)
GUESS_OTHER = "Good guess. Here's the answer. "
# The check-ride result card shows this one line (not spoken). Moon: ~2.6 s round trip; Mars: 6 to 44 minutes.
MARS_FACT = "On Mars, Houston would answer 6 to 44 minutes later."


class AttemptInput(BaseModel):
    text: str | None = Field(None, max_length=300)
    tap: str | dict | None = None
    choice: str | None = Field(None, max_length=60)
    view: dict | None = None                       # globe_side: the camera's centre {lat, lon}
    taps: list[str | dict] | None = Field(None, max_length=12)   # route: the stops tapped so far, in order
    video: dict | None = None                      # video step: {watched, seconds, skipped?, offline?} (docs/MEDIA.md)
    got: list[str] | None = Field(None, max_length=12)   # Field School steps: the reply's `got`, sent back (grade.py)
    plan: list[str] | None = Field(None, max_length=12)   # vocab step: the client's spaced-repetition order of item ids
    long_text: str | None = Field(None, max_length=2400)  # summary step: the whole spoken / typed summary
    rich: bool = False   # summary step: the grown-up setting asked for the local rewrite (feedback.py; off by default)


class AttemptReq(BaseModel):
    lesson_id: str
    step: int = Field(..., ge=0)
    input: AttemptInput
    misses: int = Field(0, ge=0, le=50)   # misses so far on this step (client-side progress)
    ride_id: str | None = None
    step_s: float | None = Field(None, ge=0)   # seconds the step has been open (client): no reveal in the first 20 s
    level: Literal["cadet", "commander"] = "cadet"   # Settings (docs/VOICES.md): for the learning design; no effect yet
    rung: int = Field(0, ge=0, le=3)   # the hint rung the card already shows (a find step opens at 1; help climbs)
    # [0.6] the answer came with hesitation (the session's heard.hes; the client sends it once per step): a miss climbs
    # one rung further. Never stored, never a score, never said; the reveal still waits for real misses (reveal_due).
    hes: bool = False


class HintReq(BaseModel):
    lesson_id: str
    step: int = Field(..., ge=0)
    rung: int = Field(1, ge=1, le=3)   # the rung to show: help climbs one at a time (highlight, label, show)
    got: list[str] | None = Field(None, max_length=12)   # route: the stops already tapped right
    plan: list[str] | None = Field(None, max_length=12)  # vocab step: the client's spaced-repetition order


def _decisions(lesson_id: str, step: int, status: str, say: str, score: int | None = None, badge: bool = False,
               emotion: str | None = None) -> list[dict]:
    d = [{"t": "lesson", "id": f"ac-{lesson_id}-{step}-{status}", "priority": 4, "lesson_id": lesson_id, "step": step,
          "status": status}]
    if score is not None:
        d[0]["score"] = score
    if say:
        d.append({"t": "say", "id": f"ac-{lesson_id}-{step}-say", "priority": 4, "text": say, "voice": "capcom",
                  "after": d[0]["id"],
                  "style": steering.style_for("capcom", say, situation=steering.lesson_situation(status, badge),
                                              emotion=emotion)})
    return d


def _out(lesson_id: str, step: int, status: str, say: str, **extra) -> dict:
    return {"status": status, "say": say, **{k: v for k, v in extra.items() if v is not None},
            "decisions": _decisions(lesson_id, step, status, say, extra.get("score"), badge=bool(extra.get("badge")),
                                    emotion=extra.get("emotion"))}


@router.get("/api/academy/course")
def academy_course():
    return content.public()


@router.post("/api/academy/ride")
def academy_ride():
    les = next(l for l in content.course()["lessons"] if l.get("ride"))
    r = rides.start(les["ride"])
    return {"ride_id": r["m"].id, "lesson_id": les["id"], "state": rides.hud(r), "say": les["steps"][0]["prompt"]}


@router.post("/api/academy/hint")
def academy_hint(req: HintReq):
    """The kid asked for help ("help", "I don't know", "where is it?"): the next rung of the hint ladder, with no miss
    counted and nothing graded (guide.help_rung). The check ride has no ladder: its hint, as written."""
    les = content.lesson(req.lesson_id)
    if not les:
        raise HTTPException(404, "no such lesson")
    if req.step >= len(les["steps"]):
        raise HTTPException(422, "no such step")
    st = les["steps"][req.step]
    if st["accept"]["type"] in SPEECH_TYPES:
        out = speech_help(st, req.rung, req.got, req.plan)
        return {"status": "help", **out, "decisions": _decisions(les["id"], req.step, "help", out["say"])}
    if les.get("ride"):
        exp = (st["accept"] or {}).get("expect")
        say = guide._end(st["hint"]) + (f" Tap {guide.order_label(exp)}." if exp else "")
        return {"status": "help", "rung": 1, "say": say, "hint": st["hint"],
                "decisions": _decisions(les["id"], req.step, "help", say)}
    out = guide.help_rung(st, req.rung, req.got)
    return {"status": "help", **out, "decisions": _decisions(les["id"], req.step, "help", out["say"])}


@router.post("/api/academy/attempt")
async def academy_attempt(req: AttemptReq):
    les = content.lesson(req.lesson_id)
    if not les:
        raise HTTPException(404, "no such lesson")
    steps = les["steps"]
    if req.step >= len(steps):
        raise HTTPException(422, "no such step")
    if les.get("ride"):
        return _ride_attempt(les, req)
    st = steps[req.step]
    if (req.input.text and safety_.has_profanity(req.input.text)) or \
            (req.input.long_text and safety_.has_profanity(req.input.long_text)):
        return _ignored(les["id"], req.step)          # [P0] a rude turn is never graded (safety.py)
    if st["accept"]["type"] in SPEECH_TYPES:          # read / vocab / summary (docs/SPEECH_LEARNING.md)
        return await _speech_attempt(les, req, st)
    ok, extra = grade(st, req.input.model_dump(exclude_none=True))
    if not ok and req.input.text:  # keyword rules first; a paraphrase of the expected line also passes
        ok = await similar(st, req.input.text)
    if not ok and text_only(req.input.model_dump(exclude_none=True)) and not plausible(st, req.input.text):
        return _ignored(les["id"], req.step)          # room talk / filler: not a try, no miss, nothing said
    if not ok and st["accept"]["type"] == "video":
        return _ignored(les["id"], req.step)          # a video step is never missed: only watch / skip move it on
    if st["accept"]["type"] in FIELD_TYPES:
        return _field_reply(les, req, st, ok, extra)
    if not ok and st["accept"]["type"] == "decide":
        return _ignored(les["id"], req.step)          # an ethics call: only a choice moves it on (never a miss)
    if not ok and st["accept"]["type"] == "predict":
        return _ignored(les["id"], req.step)          # [0.3.12] a guess step: only a guess moves it on; other words never
        #                                               count as a miss, so they never reveal the answer before a guess
    last = req.step == len(steps) - 1
    shown = not ok and reveal_due(req.misses + 1, req.step_s)
    if st["accept"]["type"].startswith("vocab_"):     # Space words: slower, enunciated, the word itself stressed
        return _vocab_out(les, req, st, ok, last, extra, shown)
    if ok or shown:
        say = st["success"]
        if st["accept"]["type"] == "predict" and not extra.get("correct"):
            say = st["reveal"]                          # a guess is never wrong: "your guess" vs "the data"
        if st["accept"]["type"] == "decide" and ok:     # every call gets its own reply, then the law card (on screen)
            say = next((o["reply"] for o in st["accept"]["options"] if o["id"] == extra.get("choice")), say)
        if st["accept"]["type"] == "video" and extra.get("guess"):   # the guess, acknowledged, then the answer
            say = (GUESS_RIGHT if extra.get("correct") else GUESS_OTHER) + say
        if shown:
            say = SHOWN + say
        return _out(les["id"], req.step, "passed", say, next_step=None if last else req.step + 1,
                    badge=les["badge"] if last else None, shown=True if shown else None,
                    shown_answer=_answer_of(st) if shown else None, **extra)
    if st["accept"]["type"] == "route" and _route_progress(req.input.model_dump(exclude_none=True), extra):
        nxt = extra["next"]   # every stop so far was right: not a miss, just the next stop
        return _out(les["id"], req.step, "progress", f"Yes, {guide.short(extra['got'][-1])}. Now {guide.short(nxt)}.",
                    got=extra["got"], next=nxt)
    return _miss(les, req, st, extra)


def _field_reply(les: dict, req: AttemptReq, st: dict, ok: bool, extra: dict) -> dict:
    """Field School steps (grade.FIELD_TYPES) build up over turns, like the route: a turn that adds something is
    `progress` (never a miss) and carries `got` for the client to send back. A turn that adds nothing is a miss on the
    hint ladder; after 3 misses (and 20 s) CAPCOM shows it: the whole description or order, or, in a rounds step, just
    this round's answer, and the next round goes on (no dead ends, and every round is still asked)."""
    from .grade import describe_label
    kind, acc, lid = st["accept"]["type"], st["accept"], les["id"]
    inp = req.input.model_dump(exclude_none=True)
    last = req.step == len(les["steps"]) - 1
    prior = inp.get("got") or []
    got = extra.get("got") or []

    def passed(say: str, shown: bool = False) -> dict:
        return _out(lid, req.step, "passed", (SHOWN if shown else "") + say, next_step=None if last else req.step + 1,
                    badge=les["badge"] if last else None, shown=True if shown else None,
                    shown_answer=_answer_of(st) if shown else None, **extra)
    if ok:
        say = st["success"]
        if kind == "describe":   # praise what they got, then the payoff line
            say = f"You noted {describe_label(got)}. " + say
        return passed(say)
    grew = len(got) > len([g for g in prior if g in got])
    if kind == "describe" and extra.get("new"):
        return _out(lid, req.step, "progress", f"Good: {describe_label(extra['new'])}. Now, {guide.describe_ask(extra['missing'])}",
                    **extra)
    if kind == "sequence" and grew and extra.get("next"):
        new = [i["label"] for i in acc["items"] if i["id"] in got[len(prior):]]
        return _out(lid, req.step, "progress", f"Yes: {', '.join(new)}. What comes next?", **extra)
    if kind == "layers" and grew and extra.get("next"):
        new = [i["label"] for i in arch_steps._seq_items(acc) if i["id"] in got[len(prior):]]
        return _out(lid, req.step, "progress", f"Yes: {', '.join(new)}. What came next?", **extra)
    if kind == "layers" and extra.get("trap") == "pit":   # the intrusive pit, named too early: why, never "wrong"
        if reveal_due(req.misses + 1, req.step_s):
            return passed(st["success"], shown=True)
        return _miss(les, req, st, extra)
    if kind == "hillshade" and extra.get("new") and extra.get("next"):
        name = next(t["label"] for t in acc["targets"] if t["id"] == extra["new"][-1])
        left = min(int(acc.get("need") or len(acc["targets"])), len(acc["targets"])) - len(got)
        return _out(lid, req.step, "progress", f"Yes: {name}. {left} more to find.", **extra)
    if kind == "hillshade" and extra.get("again"):        # a found one tapped again: not a miss
        return _ignored(lid, req.step, got=got)
    if kind == "rounds" and grew and extra.get("next"):
        rd = next(r for r in acc["rounds"] if r["id"] == got[-1])
        nx = next(r for r in acc["rounds"] if r["id"] == extra["next"])
        return _out(lid, req.step, "progress", f"{rd.get('yes') or 'Yes.'} {nx['prompt']}", **extra)
    if reveal_due(req.misses + 1, req.step_s):          # CAPCOM shows it
        if kind == "rounds":
            rs = acc["rounds"]
            cur = rs[len(got)]
            label = guide.option_label(acc, cur["answer"]).split(":")[0]   # "Basalt: dark lava rock" -> "Basalt"
            got2 = got + [cur["id"]]
            if len(got2) == len(rs):
                return passed(f"Here it is: {label}. " + st["success"])
            nx = rs[len(got2)]
            return _out(lid, req.step, "progress", f"Here it is: {label}. {nx['prompt']}", got=got2, next=nx["id"],
                        shown=True, shown_answer={"choice": cur["answer"]})
        if kind == "describe":
            return passed(st["example"], shown=True)
        return passed(st["success"], shown=True)
    return _miss(les, req, st, extra)


def _route_progress(inp: dict, extra: dict) -> bool:
    got = extra.get("got") or []
    return bool(got) and len(got) >= len(inp.get("taps") or []) and extra.get("next") is not None


def _miss(les: dict, req: AttemptReq, st: dict, extra: dict) -> dict:
    """A real miss: the next rung of the hint ladder (app/academy/guide.py), which always says what to do next."""
    g = guide.ladder(st, req.misses + (1 if req.hes else 0), req.input.model_dump(exclude_none=True), extra,
                     seen=req.rung)
    if st["accept"]["type"] in ("route", *FIELD_TYPES):
        g["got"] = extra.get("got") or []   # the stops still right (the client keeps those taps)
        if st["accept"]["type"] in FIELD_TYPES and extra.get("next"):
            g["next"] = extra["next"]
    g.setdefault("mixup", mixup_of(extra))
    return _out(les["id"], req.step, "hint", g.pop("say"), **g)


MIXUPS = ("pit", "soundalike", "order", "sequence", "pick")


def mixup_of(extra: dict | None) -> str | None:
    """[brain] A miss's misconception kind, an enum (never the kid's words): the intrusive pit named too early, a wrong
    order, a step out of sequence, a tempting wrong option. The client counts it per lesson step (brain_store.js
    traps) for the grown-ups' "Common mix-ups". None when the grader said nothing about why."""
    e = extra or {}
    if e.get("trap") == "pit":
        return "pit"
    if e.get("trap"):
        return "soundalike"
    if e.get("heard_order"):
        return "order"
    if e.get("wrong"):
        return "sequence"
    if e.get("choice"):
        return "pick"
    return None


def _ignored(lesson_id: str, step: int, **extra) -> dict:
    """Not a try (grade.plausible): no miss, no line, the step stays open. The client counts nothing."""
    return {"status": "ignored", "say": "", "lesson_id": lesson_id, "step": step, "decisions": [],
            **{k: v for k, v in extra.items() if v is not None}}


def _ride_attempt(les: dict, req: AttemptReq) -> dict:
    r = rides.get(req.ride_id)
    if r is None:
        raise HTTPException(404, "no such check ride; POST /api/academy/ride first")
    if r["done"] or req.step != r["step"]:
        raise HTTPException(409, f"the ride is on step {r['step']}")
    steps, m = les["steps"], r["m"]
    st = steps[r["step"]]
    inp = req.input.model_dump(exclude_none=True)
    if req.input.text and safety_.has_profanity(req.input.text):
        return _ignored(les["id"], r["step"], state=rides.hud(r))   # [P0] a rude turn is never graded
    ok, extra = grade(st, inp, loads=m.loads)
    if not ok and (st["accept"] or {}).get("type") == "predict":
        return _ignored(les["id"], r["step"], state=rides.hud(r))   # [0.3.12] a guess step waits for a guess
    if not ok and text_only(inp) and not plausible(st, req.input.text):
        return _ignored(les["id"], r["step"], state=rides.hud(r))   # not a try: the miss counter doesn't move
    if not ok and (st["accept"] or {}).get("type") == "sequence":
        # [0.4.1] a readback / confirm builds up over turns: words that add to it are progress, never a miss
        prior, got = inp.get("got") or [], extra.get("got") or []
        if len(got) > len([g for g in prior if g in got]) and extra.get("next"):
            items = st["accept"]["items"]
            said = ", ".join(i["label"] for i in items if i["id"] in got)
            nxt = next(i["label"] for i in items if i["id"] == extra["next"])
            return _out(les["id"], r["step"], "progress", f"Copy: {said}. Then: {nxt}.", got=got, next=extra["next"],
                        state=rides.hud(r))
    sim_say, said_override = "", None
    if ok:
        res = m.apply(extra["command"])["result"] if extra.get("command") else {"say": ""}
        if res.get("needs_confirm"):
            res = m.apply({"type": "confirm"})["result"]
        sim_say = _new_news(st["success"], res.get("say", ""))
        if (extra.get("command") or {}).get("type") == "call_houston" and res.get("ok") and res.get("say"):
            # [0.3.12] a radio call answers with Houston's own reply (light time included), not CAPCOM's success line
            # and then Houston's: one reply, 20 words or fewer (it was two, about 33 words)
            said_override, sim_say = res["say"], ""
        else:
            said_override = None
        r["missed"].append(False)
    else:
        r["misses"] += 1
        if r["misses"] < rides.MISS_LIMIT:
            status = "hint" if r["misses"] >= HINT_AFTER else "retry"
            # a wrong order teaches why (step.wrong: "Shields help a little. The shelter is safer."), then what to do
            lead = (st.get("wrong") or {}).get(extra.get("heard_order") or "", st["fail"])
            say = lead + (" " + guide._end(st["hint"]) if status == "hint" else "")
            return _out(les["id"], r["step"], status, say, hint=st["hint"] if status == "hint" else None,
                        state=rides.hud(r), cue=(st["accept"] or {}).get("expect") if r["misses"] >= 2 else None,
                        mixup=mixup_of(extra))
        r["missed"].append(True)   # the world doesn't wait: the ride moves on without that order
    evs = rides.advance(r, st.get("advance"))
    r["step"] += 1
    r["misses"] = 0
    events = [{"kind": e["kind"], "text": e["text"], "source": e.get("source")} for e in evs]
    said = (said_override or st["success"]) if ok else "Time's up. " + st["hint"]
    if r["step"] < len(steps) and not m.over:
        return _out(les["id"], r["step"] - 1, "passed" if ok else "missed", said, next_step=r["step"],
                    state=rides.hud(r), events=events, sim_say=sim_say or None)
    # the ride is over: grade it
    rides.advance(r, "end")
    r["done"] = True
    missed = sum(r["missed"])
    score = len(r["missed"]) - missed
    passed = missed <= les["ride"]["max_missed"] and not m.over
    # Spoken: the score only. The HUD in `state` shows power, life support and dose; `fact` is on screen, never spoken.
    summary = f"Check ride done. {score} of {len(steps)} steps right."
    if passed:
        return _out(les["id"], len(steps) - 1, "done", said + " " + summary + " You're qualified, Commander.",
                    badge=les["badge"], unlocks="mission", passed=True, score=score, state=rides.hud(r), events=events,
                    fact=MARS_FACT)
    return _out(les["id"], len(steps) - 1, "done", said + " " + summary + " Not qualified yet. Fly it again.",
                passed=False, score=score, state=rides.hud(r), events=events, fact=MARS_FACT)


def _new_news(said: str, sim_say: str) -> str:
    """The sim's own reply minus what the step's success line already said ("Copy. Crew in the shelter." then "Crew in
    the shelter. Much less radiation…" said it twice): only its sentences that are new."""
    import re
    key = lambda t: re.sub(r"[^a-z0-9 ]", "", t.lower()).strip()  # noqa: E731
    have = {key(x) for x in re.split(r"(?<=[.!?])\s+", said or "") if x.strip()}
    keep = [x for x in re.split(r"(?<=[.!?])\s+", sim_say or "") if x.strip() and key(x) not in have]
    return " ".join(keep)


def _answer_of(st: dict) -> dict:
    """What the client highlights when CAPCOM shows the answer: an option id, a place, or the route."""
    a = st["accept"]
    if a["type"] in ("choice", "predict", "compare"):
        return {"choice": a["answer"]}
    if a["type"] in ("tap", "intent"):
        return {"place": a["place"]}
    if a["type"] == "route":
        return {"stops": a["stops"]}
    if a["type"] == "globe_side":
        return {"side": a["want"]}
    if a["type"] == "earth_view":
        from .grade import earth_answer
        return {"choice": earth_answer(a["place"])}
    if a["type"] == "terminator":
        return {"sun_lon": a["sun_lon"]}
    if a["type"] == "keywords":
        return {"say": (references(st) or [""])[0]}
    if a["type"] == "describe":
        return {"say": st.get("example", "")}
    if a["type"] == "sequence":
        return {"order": [i["id"] for i in a["items"]], "say": ", ".join(i["label"] for i in a["items"])}
    if a["type"] == "rounds":
        return {"choice": a["rounds"][-1]["answer"]}
    if a["type"] in arch_steps.ARCH_TYPES:
        return arch_steps.answer_of(st)
    return {}


def _vocab_out(les: dict, req: AttemptReq, st: dict, ok: bool, last: bool, extra: dict, shown: bool = False) -> dict:
    """A vocab step's reply: the same shape, steered with the `vocab` situation and per-word emphasis (§4b)."""
    from .vocab import term
    t = term(st["accept"]["term"]) or {}
    if ok or shown:
        out = _out(les["id"], req.step, "passed", (SHOWN if shown else "") + st["success"],
                   next_step=None if last else req.step + 1, shown=True if shown else None,
                   badge=les["badge"] if last else None, term=t or None, **{k: v for k, v in extra.items() if k != "term"})
    else:
        out = _miss(les, req, st, extra)
    if not out.get("badge"):                          # a badge line keeps its proud style
        sit = "passed" if out["status"] == "passed" else "vocab"
        for d in out["decisions"]:
            if d["t"] == "say":
                d["style"] = steering.style_for("capcom", d["text"], situation=sit, vocab=[t.get("term", "")])
    return out


# ---- speech learning steps: read, vocab, summary (app/academy/speech.py, docs/SPEECH_LEARNING.md) -------------------
SUMMARY_SIM = 0.62   # cosine (all-MiniLM-L6-v2) between a summary span and a key point's phrasing (docs §3.2)
NEXT_ITEM = "Next word."


def _item_cue(it: dict) -> str:
    """What CAPCOM says to open a vocab item (the card shows the same)."""
    if it.get("kind", "word") == "word":
        return f"Which word means: {speech.define_of(it).rstrip('.')}?"
    return f"Use {it['term']} in a sentence."


def _next_prompt(acc: dict, nid: str | None, plan: list | None = None) -> str:
    if not nid:
        return ""
    if acc["type"] == "read":
        return next(q["prompt"] for q in acc["questions"] if q["id"] == nid)
    it = speech.item_by_id(acc, nid)
    return f"{NEXT_ITEM} {_item_cue(it)}" if it else ""


def speech_help(st: dict, rung: int, got: list | None = None, plan: list | None = None) -> dict:
    """The help ladder for the question / item / summary the kid is on (no miss counted)."""
    acc = st["accept"]
    rung = max(1, min(3, int(rung or 1)))
    out: dict = {"rung": rung, "hint": st.get("hint", "")}
    if acc["type"] == "summary":
        miss = [p for p in acc["points"] if p["id"] not in (got or [])]
        p = miss[min(rung - 1, len(miss) - 1)] if miss else None
        out["say"] = p["ask"] if p else guide._end(st.get("hint", ""))
        if rung == 3:
            out["phrase"] = acc.get("example", "")
            out["say"] = "Here's one way to start. Say it your way."
        return out
    cur = speech.current(acc, got, plan)
    if not cur:
        out["say"] = guide._end(st.get("hint", ""))
        return out
    hint = guide._end(cur.get("hint") or st.get("hint", ""))
    out["say"] = hint
    if rung >= 2:
        opts = speech.step_options(acc, got)
        sa = speech.answer_of(acc, got, plan)
        wrong = next((i for i, _ in opts if i != sa.get("choice")), None) if opts else None
        if wrong:
            out["eliminate"] = wrong
            out["say"] = hint + " I crossed one out."
        if "sentence" in sa:
            out["sentence_near"] = sa["sentence"]
            out["say"] = hint + " Look at the glowing part."
    if rung == 3:
        sa = speech.answer_of(acc, got, plan)
        out["answer"] = sa.get("choice")
        if "sentence" in sa:
            out["sentence"] = sa["sentence"]
        out["say"] = f"Here's the answer: {speech.label_of_answer(acc, cur)}."
    return out


async def summary_hits(acc: dict, text: str) -> tuple[list[str], list[str]]:
    """(points the embedder hears, Arc Tagger's mentions). Both fail open to [] (model server off)."""
    from .. import models_client
    from ..readout import summarize
    emb: list[str] = []
    spans = speech.clauses(text)
    phr = [(p["id"], ph) for p in acc["points"] for ph in [p["label"], *p.get("say", [])]]
    if spans and phr:
        v = await models_client.embed([*spans, *(x for _, x in phr)], "query")
        if v and len(v) == len(spans) + len(phr):
            sv, pv = v[:len(spans)], v[len(spans):]
            for (pid, _), vec in zip(phr, pv):
                if pid not in emb and max(sum(a * b for a, b in zip(s, vec)) for s in sv) >= SUMMARY_SIM:
                    emb.append(pid)
    mentions: list[str] = []
    try:
        mentions = summarize(await models_client.tag(text, safety_.TAG_DOMAIN)).get("mentions") or []
    except Exception:   # noqa: BLE001
        mentions = []
    return emb, mentions


async def _speech_attempt(les: dict, req: AttemptReq, st: dict) -> dict:
    acc, lid = st["accept"], les["id"]
    kind = acc["type"]
    inp = req.input.model_dump(exclude_none=True)
    text = (inp.get("long_text") or inp.get("text") or "") if kind == "summary" else (inp.get("text") or "")
    last = req.step == len(les["steps"]) - 1
    has_tap = inp.get("choice") is not None
    if text and not has_tap and not speech.plausible(acc, text):
        return _ignored(lid, req.step)                # room talk / filler: not a try
    if not text and not has_tap:
        return _ignored(lid, req.step)
    if kind == "summary":
        emb, men = await summary_hits(acc, text)
        ok, extra = speech.grade_summary(acc, inp, text, emb, men)
    else:
        ok, extra = grade(st, inp)
    prior = inp.get("got") or []
    got = extra.get("got") or []

    def passed(say: str, shown: bool = False, **more) -> dict:
        return _out(lid, req.step, "passed", (SHOWN if shown else "") + say, next_step=None if last else req.step + 1,
                    badge=les["badge"] if last else None, shown=True if shown else None,
                    shown_answer=speech.answer_of(acc, prior, inp.get("plan")) if shown else None, **{**extra, **more})

    if kind == "summary":
        if ok:
            f = await fb.summary_feedback(acc, got, extra["missing"], text, lesson_id=lid, rich=bool(inp.get("rich")))
            return passed(f["say"], feedback=f["lines"], engine=f["engine"])
        if extra.get("new"):
            return _out(lid, req.step, "progress", fb.progress_line(acc, extra["new"], extra["missing"]), **extra)
        if reveal_due(req.misses + 1, req.step_s):    # never "wrong": a model summary, and the lesson goes on
            return passed(acc.get("example", ""), shown=True, feedback=[acc.get("example", "")], engine="template")
        h = speech_help(st, 2 if req.misses >= 1 else 1, got)
        return _out(lid, req.step, "hint", h["say"], rung=h["rung"], **extra)
    cur = speech.current(acc, prior, inp.get("plan"))
    grew = len(got) > len(speech._valid_prefix(prior, got))
    if ok:
        yes = (cur or {}).get("yes") or ""
        return passed(" ".join(x for x in (yes, st["success"]) if x))
    if grew:
        yes = (cur or {}).get("yes") or "Yes."
        return _out(lid, req.step, "progress", f"{yes} {_next_prompt(acc, extra.get('next'), extra.get('plan'))}".strip(),
                    **extra)
    if extra.get("trap"):                             # a sound-alike: what it means, then try again (not a miss)
        it = speech.item_by_id(acc, extra.get("item") or "") or {}
        note = next((t["note"] for t in it.get("traps", []) if t["word"].lower() == extra["trap"].lower()), "")
        return _out(lid, req.step, "hint", f"Close! {note} Try again.".replace("  ", " "), rung=1, mixup="soundalike",
                    **extra)
    if cur and reveal_due(req.misses + 1, req.step_s):   # show this one, then the next goes on (no dead ends)
        label = speech.label_of_answer(acc, cur)
        sa = speech.answer_of(acc, prior, inp.get("plan"))
        ids = extra.get("plan") or [q["id"] for q in acc.get("questions", [])]
        got2 = speech._valid_prefix(prior, ids) + [cur["id"]]
        if len(got2) >= len(ids):
            return passed(f"Here it is: {label}. " + st["success"], **{"got": got2})
        nid = ids[len(got2)]
        return _out(lid, req.step, "progress", f"Here it is: {label}. {_next_prompt(acc, nid)}", got=got2, next=nid,
                    shown=True, shown_answer=sa, **({"plan": extra["plan"]} if extra.get("plan") else {}))
    h = speech_help(st, 2 if req.misses >= 1 else 1, prior, inp.get("plan"))
    lead = "" if h["rung"] >= 2 else (st.get("fail", "") + " ")
    return _out(lid, req.step, "hint", (lead + h["say"]).strip(), **{k: v for k, v in h.items() if k != "say"},
                **{k: v for k, v in extra.items() if k not in h})


class FluencyReq(BaseModel):
    lesson_id: str
    step: int = Field(..., ge=0)
    text: str = Field(..., max_length=6000)       # what the ear heard while the cadet read aloud (never stored)
    seconds: float | None = Field(None, ge=0, le=1800)   # speaking time (the ear's speech_s, else the clock)


FLUENCY = {
    "read": lambda c, of: f"You read {c} of {of} words.",
    "pace": lambda w: f"That's about {w} words a minute.",
    "skipped": lambda ws: f"Words to try again: {', '.join(ws)}.",
    "repeats": "Going back to reread is a good habit.",
    "none": "I didn't catch the reading. Try again, a bit louder.",
}


@router.post("/api/academy/fluency")
def academy_fluency(req: FluencyReq):
    """Read it yourself aloud (a read step): counts only. Words read correctly, words a minute, words to try again,
    rereads. Never a label or a level; the words heard are not kept or returned."""
    les = content.lesson(req.lesson_id)
    if not les or req.step >= len(les["steps"]):
        raise HTTPException(404, "no such step")
    acc = les["steps"][req.step]["accept"]
    passage = (acc.get("passage") or (acc.get("source") or {}).get("passage") or {}).get("text")
    if not passage:
        raise HTTPException(422, "this step has no passage")
    clean = " ".join(w for w in req.text.split() if not safety_.is_profane(w))
    f = speech.fluency(passage, clean, req.seconds)
    if not f["correct"]:
        return {**f, "lines": [FLUENCY["none"]], "say": FLUENCY["none"]}
    lines = [FLUENCY["read"](f["correct"], f["of"])]
    if f["wcpm"]:
        lines.append(FLUENCY["pace"](f["wcpm"]))
    if f["skipped"]:
        lines.append(FLUENCY["skipped"](f["skipped"][:3]))
    if f["repeats"]:
        lines.append(FLUENCY["repeats"])
    return {**f, "lines": lines, "say": " ".join(lines[:3])}
