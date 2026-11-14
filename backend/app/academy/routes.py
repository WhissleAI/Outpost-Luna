"""Academy API: GET /api/academy/course, POST /api/academy/attempt, POST /api/academy/ride.

Progress lives on the device (localStorage, no names). Each attempt also returns `decisions` in the session-contract
shape (docs/SESSION_CONTRACT.md: `lesson` + `say`), so a session Director can relay them unchanged.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import steering
from . import content, ride as rides
from .grade import grade, similar

router = APIRouter()
from .vocab import router as _vocab_router  # noqa: E402  (GET /api/glossary: Space words, docs/VOCABULARY.md)
router.include_router(_vocab_router)
HINT_AFTER = 2   # misses before the hint


class AttemptInput(BaseModel):
    text: str | None = Field(None, max_length=300)
    tap: str | dict | None = None
    choice: str | None = Field(None, max_length=60)


class AttemptReq(BaseModel):
    lesson_id: str
    step: int = Field(..., ge=0)
    input: AttemptInput
    misses: int = Field(0, ge=0, le=50)   # misses so far on this step (client-side progress)
    ride_id: str | None = None


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
    ok, extra = grade(st, req.input.model_dump(exclude_none=True))
    if not ok and req.input.text:  # keyword rules first; a paraphrase of the expected line also passes
        ok = await similar(st, req.input.text)
    last = req.step == len(steps) - 1
    if st["accept"]["type"].startswith("vocab_"):     # Space words: slower, enunciated, the word itself stressed
        return _vocab_out(les, req, st, ok, last, extra)
    if ok:
        return _out(les["id"], req.step, "passed", st["success"], next_step=None if last else req.step + 1,
                    badge=les["badge"] if last else None, **extra)
    if req.misses + 1 >= HINT_AFTER:
        return _out(les["id"], req.step, "hint", st["fail"] + " Hint: " + st["hint"], hint=st["hint"])
    return _out(les["id"], req.step, "retry", st["fail"])


def _ride_attempt(les: dict, req: AttemptReq) -> dict:
    r = rides.get(req.ride_id)
    if r is None:
        raise HTTPException(404, "no such check ride; POST /api/academy/ride first")
    if r["done"] or req.step != r["step"]:
        raise HTTPException(409, f"the ride is on step {r['step']}")
    steps, m = les["steps"], r["m"]
    st = steps[r["step"]]
    ok, extra = grade(st, req.input.model_dump(exclude_none=True), loads=m.loads)
    sim_say = ""
    if ok:
        res = m.apply(extra["command"])["result"] if extra.get("command") else {"say": ""}
        if res.get("needs_confirm"):
            res = m.apply({"type": "confirm"})["result"]
        sim_say = res.get("say", "")
        r["missed"].append(False)
    else:
        r["misses"] += 1
        if r["misses"] < rides.MISS_LIMIT:
            status = "hint" if r["misses"] >= HINT_AFTER else "retry"
            say = st["fail"] + (" Hint: " + st["hint"] if status == "hint" else "")
            return _out(les["id"], r["step"], status, say, hint=st["hint"] if status == "hint" else None,
                        state=rides.hud(r))
        r["missed"].append(True)   # the world doesn't wait: the ride moves on without that order
    evs = rides.advance(r, st.get("advance"))
    r["step"] += 1
    r["misses"] = 0
    events = [{"kind": e["kind"], "text": e["text"], "source": e.get("source")} for e in evs]
    said = (st["success"] if ok else "Time's up on that one. " + st["hint"])
    if r["step"] < len(steps) and not m.over:
        return _out(les["id"], r["step"] - 1, "passed" if ok else "missed", said, next_step=r["step"],
                    state=rides.hud(r), events=events, sim_say=sim_say or None)
    # the ride is over: grade it
    rides.advance(r, "end")
    r["done"] = True
    missed = sum(r["missed"])
    score = len(r["missed"]) - missed
    passed = missed <= les["ride"]["max_missed"] and not m.over
    res = m.state()["resources"]
    summary = (f"Check ride complete. Power {res['power_pct']:.0f}%, life support {res['life_support_pct']:.0f}%, "
               f"dose {res['dose_msv']:.1f} of {res['dose_limit_msv']:.0f} mSv. {score} of {len(steps)} orders right. "
               "On Mars, Houston would answer 6–44 minutes later.")
    if passed:
        return _out(les["id"], len(steps) - 1, "done", said + " " + summary + " You are qualified, Commander!",
                    badge=les["badge"], unlocks="mission", passed=True, score=score, state=rides.hud(r), events=events)
    return _out(les["id"], len(steps) - 1, "done", said + " " + summary + " Not qualified yet. Try the ride again!",
                passed=False, score=score, state=rides.hud(r), events=events)


def _vocab_out(les: dict, req: AttemptReq, st: dict, ok: bool, last: bool, extra: dict) -> dict:
    """A vocab step's reply: the same shape, steered with the `vocab` situation and per-word emphasis (§4b)."""
    from .vocab import term
    t = term(st["accept"]["term"]) or {}
    if ok:
        out = _out(les["id"], req.step, "passed", st["success"], next_step=None if last else req.step + 1,
                   badge=les["badge"] if last else None, term=t or None, **{k: v for k, v in extra.items() if k != "term"})
    elif req.misses + 1 >= HINT_AFTER:
        out = _out(les["id"], req.step, "hint", st["fail"] + " Hint: " + st["hint"], hint=st["hint"])
    else:
        out = _out(les["id"], req.step, "retry", st["fail"])
    if not out.get("badge"):                          # a badge line keeps its proud style
        sit = "passed" if out["status"] == "passed" else "vocab"
        for d in out["decisions"]:
            if d["t"] == "say":
                d["style"] = steering.style_for("capcom", d["text"], situation=sit, vocab=[t.get("term", "")])
    return out
