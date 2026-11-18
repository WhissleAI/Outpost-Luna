"""Packaged-app RC bug: room chatter graded as wrong answers, and the 3-miss reveal in the first seconds of a step.

The kid said "start", lesson 2 ("Lessons from Apollo") opened on a vocab_match step ("Apollo 11 landed on a mare. What
does mare mean?"), and within ~4 s "Okay." / "Oh, it's." counted as misses and CAPCOM revealed the answer. Now only a
plausible answer is a try (grade.plausible, shared by the router and the grader), a queued multi-line CAPCOM sequence is
one on-air span (Spoken `more`), and the reveal needs 3 real misses AND ~20 s (grade.reveal_due)."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import director, models_client, session as sessions
from app.academy import content, grade
from app.config import settings
from app.gazetteer import Gazetteer
from app.main import app
from app.mission import capcom, registry
from app.moments import MomentIndex
from app import turn_router as R

LESSON = "history"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture(scope="module")
def api():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()


def run(c):
    return asyncio.run(c)


def frame(step=0):
    st = content.lesson(LESSON)["steps"][step]
    opts = [say[0] for _, say in grade.step_options(st["accept"])]
    return {"t": "ui", "event": "screen", "screen": "lesson", "step_type": st["accept"]["type"], "step_options": opts,
            "lesson_id": LESSON, "step": step}


def lesson_session(world, step=0):
    clock = Clock()
    s = sessions.Session("tries-1", world[0], world[1], clock=clock, registry=registry)
    run(s.handle({"t": "hello", "mode": "cadet"}))
    run(s.handle(frame(step)))
    s.clock_obj = clock
    return s


def hear(s, text, dd=None, advance=0.4):
    s.clock_obj.t += advance
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    if dd is not None:
        run(s.handle({"t": "arc", "device_directed": dd}))
    run(s.handle({"t": "turn", "state": "end", "text": text}))


def line(s, did, text, dur=1.8, more=False, gap=0.9):
    """One CAPCOM line as floor.js reports it; `more`: the next line of the same say is queued (TTS fetch gap)."""
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": did, "text": text}))
    s.clock_obj.t += dur
    run(s.handle({"t": "playback", "kind": "guide", "state": "end", "id": did, **({"more": True} if more else {})}))
    s.clock_obj.t += gap


def answers(s):
    return [d for d in s.outbox if d["t"] == "nav" and d.get("intent") == "answer"]


class Kid:
    """The client: every routed `answer` is graded by POST /api/academy/attempt; misses counted as academy/ui.js does."""

    def __init__(self, api, step=0):
        self.api, self.step, self.misses, self.passed, self.shown, self.seen = api, step, 0, False, False, 0

    def grade_new(self, s, step_s=4.0):
        for d in answers(s)[self.seen:]:
            self.seen += 1
            r = self.api.post("/api/academy/attempt", json={"lesson_id": LESSON, "step": self.step,
                                                             "input": {"text": d["text"]}, "misses": self.misses,
                                                             "step_s": step_s}).json()
            if r["status"] in ("passed",):
                self.passed, self.shown = True, bool(r.get("shown"))
            elif r["status"] in ("retry", "hint"):
                self.misses += 1


# ---- 1. the exact packaged-app transcript ---------------------------------------------------------------------------
def test_the_packaged_app_transcript_leaves_the_step_open_with_no_misses(world, api):
    """kid "Alright." · kid "start" · capcom "Every crew learns…" · kid "Okay." · capcom "Every mission teaches…" ·
    kid "Oh, it's." · capcom "Apollo 11 landed on a mare." · kid "Oh, it's." → no miss, no reveal."""
    s, kid = lesson_session(world), Kid(api)
    hear(s, "Alright.")
    hear(s, "start")
    line(s, "a1", "Every crew learns from the crews before.", more=True)
    hear(s, "Okay.", advance=0.2)                       # in the gap before the next queued line
    line(s, "a2", "Every mission teaches the next.", more=True)
    hear(s, "Oh, it's.", advance=0.2)
    line(s, "a3", "Apollo 11 landed on a mare. What does mare mean?", gap=1.0)
    hear(s, "Oh, it's.", advance=1.5)                   # well after the last line: the gate is the plausibility rule
    kid.grade_new(s)
    assert answers(s) == [] and kid.misses == 0 and not kid.passed and not kid.shown
    assert not any(d["t"] == "say" and d["text"].startswith("Here it is") for d in s.outbox)
    reasons = {r["text"]: r["reason"] for r in s.routes}
    assert reasons["Oh, it's."] == "not_an_answer" and reasons["Okay."] in ("not_an_answer", "speaking", "filler")


def test_the_same_transcript_with_no_hold_and_no_timing_still_counts_nothing(world, api):
    """Even with the lines' timing unknown (typed-in like the old client copy), the grader agrees: no miss."""
    s, kid = lesson_session(world), Kid(api)
    for t in ["Alright.", "Okay.", "Oh, it's.", "Oh, it's.", "um", "hmm", "what", "alright", "okay"]:
        hear(s, t, advance=3.0)
    kid.grade_new(s)
    assert kid.misses == 0 and not kid.passed
    st = content.lesson(LESSON)["steps"][0]
    for t in ["Alright.", "Okay.", "Oh, it's.", "um", "what", "hmm"]:
        r = api.post("/api/academy/attempt", json={"lesson_id": LESSON, "step": 0, "input": {"text": t},
                                                    "misses": 2, "step_s": 60}).json()
        assert r["status"] == "ignored" and r["decisions"] == [] and not r.get("shown"), t
        assert not grade.plausible(st, t), t


# ---- 2. a real wrong answer is still a miss -------------------------------------------------------------------------
def test_a_real_wrong_answer_still_counts_as_a_miss(world, api):
    s, kid = lesson_session(world), Kid(api)
    line(s, "a1", "Apollo 11 landed on a mare. What does mare mean?", gap=1.0)
    hear(s, "a round hole made by a rock", dd=0.8, advance=1.0)
    kid.grade_new(s)
    assert len(answers(s)) == 1 and kid.misses == 1 and not kid.passed


# ---- 3. the right answer by number, letter or meaning ---------------------------------------------------------------
@pytest.mark.parametrize("text", ["one", "the first one", "1", "A.", "a", "A dark flat sea of old lava",
                                  "mare means a sea of cooled lava"])
def test_the_right_answer_by_number_letter_or_meaning_passes(world, api, text):
    s, kid = lesson_session(world), Kid(api)
    line(s, "a1", "Apollo 11 landed on a mare. What does mare mean?", gap=1.0)
    hear(s, text, advance=1.0)
    kid.grade_new(s)
    assert kid.passed and kid.misses == 0 and not kid.shown, text


@pytest.mark.parametrize("text,ok", [("a", True), ("one", True), ("its tv camera", True), ("b", False),
                                     ("a rover", False)])
def test_a_choice_step_by_letter(api, text, ok):
    r = api.post("/api/academy/attempt", json={"lesson_id": LESSON, "step": 1, "input": {"text": text}}).json()
    assert (r["status"] == "passed") is ok and r["status"] != "ignored", (text, r["status"])


# ---- 4. the reveal needs 3 real misses AND ~20 s ----------------------------------------------------------------------
def test_reveal_needs_three_misses_and_twenty_seconds(api):
    assert not grade.reveal_due(2, 60) and not grade.reveal_due(3, 4) and grade.reveal_due(3, 20) and \
        grade.reveal_due(3, None)
    body = {"lesson_id": LESSON, "step": 0, "input": {"text": "a round hole made by a rock"}, "misses": 2}
    early = api.post("/api/academy/attempt", json={**body, "step_s": 4}).json()
    assert early["status"] == "hint" and not early.get("shown")
    late = api.post("/api/academy/attempt", json={**body, "step_s": 21}).json()
    assert late["status"] == "passed" and late["shown"] and late["say"].startswith("Here it is.")


# ---- 4b. a room "yes" / "no" never answers a yes-no step (guidance playtest) ------------------------------------------
PREDICT = 2      # Lessons from Apollo: "Apollo 13 went farther from Earth than anyone. Did Artemis II beat it?"


def _routed(s, text):
    return next(r for r in reversed(s.routes) if r["text"] == text)


def test_a_room_yes_no_on_a_predict_step_needs_dd_or_a_settled_question(world):
    assert content.lesson(LESSON)["steps"][PREDICT]["accept"]["type"] == "predict"
    # the step opens and its question starts playing; "yes" from the room 0.4 s in, mid-question: ignored
    s = lesson_session(world, PREDICT)
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": "q", "text": "Did Artemis II beat it?"}))
    hear(s, "yes", advance=0.4)
    assert _routed(s, "yes")["outcome"] == "ignore" and answers(s) == []
    # the question ends; a room "no" 0.3 s later (inside the hard-mute tail): ignored
    s.clock_obj.t += 0.4
    run(s.handle({"t": "playback", "kind": "guide", "state": "end", "id": "q"}))
    s.clock_obj.t += 0.3
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    run(s.handle({"t": "turn", "state": "end", "text": "no"}))
    assert _routed(s, "no")["outcome"] == "ignore" and answers(s) == []


def test_a_yes_no_counts_once_the_question_settled_or_when_clearly_directed(world):
    # clearly directed: counts at once, even early
    s = lesson_session(world, PREDICT)
    hear(s, "yes", dd=0.85, advance=0.3)
    assert _routed(s, "yes")["outcome"] == "answer" and len(answers(s)) == 1
    # [0.4.1] crew talk: on a predict step Arc unsure (< dd_strong) never answers, however settled the question
    s = lesson_session(world, PREDICT)
    line(s, "q", "Apollo 13 went farther from Earth than anyone. Did Artemis II beat it?", dur=1.2, gap=0.0)
    hear(s, "no", dd=0.55, advance=1.0)
    assert _routed(s, "no")["reason"] == "crew_talk" and answers(s) == []
    s = lesson_session(world, PREDICT)
    hear(s, "yes it went farther", dd=0.55, advance=0.5)
    assert _routed(s, "yes it went farther")["reason"] == "crew_talk" and answers(s) == []
    # earth_view keeps the settled-question rule
    ctx = R.Ctx(screen="lesson", step_type="earth_view", step_options=["Yes", "No", "Sometimes"], source="listen", dd=0.5, step_age=0.6)
    assert R.route("yes", ctx)["reason"] == "room_yes_no"
    assert R.route("yes", R.Ctx(screen="lesson", step_type="earth_view", step_options=["Yes", "No", "Sometimes"], source="listen", dd=0.5, step_age=3.0))[
        "outcome"] == "answer"
    assert R.route("yes", R.Ctx(screen="lesson", step_type="earth_view", step_options=["Yes", "No", "Sometimes"], source="typed"))["outcome"] == "answer"


# ---- 5. a queued multi-line say is one on-air span --------------------------------------------------------------------
def test_hard_mute_holds_across_a_queued_capcom_sequence():
    c = Clock()
    sp = R.Spoken(c)
    sp.start("a1", "Every crew learns from the crews before.")
    c.t += 2.0
    sp.end("a1", more=True)
    c.t += 1.2                                      # the next line's TTS is still being fetched
    assert sp.speaking() and sp.on_air() and sp.playing_at()
    sp.start("a2", "Every mission teaches the next.")
    c.t += 1.5
    sp.end("a2")                                    # the last line: no hold
    c.t += 1.0
    assert not sp.speaking() and not sp.on_air()
    # a hold never outlives HOLD_S (the sequence was cancelled before the next line started)
    sp.start("b1", "Brief.")
    sp.end("b1", more=True)
    c.t += R.Spoken.HOLD_S + 0.1
    assert not sp.speaking() and not sp.on_air()


def test_a_directed_turn_in_the_gap_between_queued_lines_is_muted(world):
    s = lesson_session(world)
    line(s, "a1", "Every crew learns from the crews before.", more=True, gap=0.0)
    hear(s, "every crew learns from crews", dd=0.6, advance=0.8)
    assert s.routes[-1]["outcome"] == "ignore" and answers(s) == []


def test_a_misheard_option_name_is_still_a_try():
    """The live run through the real Arc ear: "Malapert Massif" is heard "Malapart must be". Not plausible meant an
    endless silent ignore on the compare step; a near-miss of an option name is a try, and grades as that option."""
    from app.academy import content, grade
    st = content.lesson("comms")["steps"][3]
    assert st["accept"]["type"] == "compare"
    assert grade.plausible(st, "Malapart must be", 0.9)
    assert grade.grade(st, {"text": "Malapart must be"})[1].get("choice") == "malapert_massif"
    for chatter in ("oh it s", "okay", "alright so", "rocks"):
        assert not grade.plausible(st, chatter, 0.9)
