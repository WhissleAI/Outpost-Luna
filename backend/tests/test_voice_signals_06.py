"""0.6 "full sensory blend", part 1: radio readback (mission/readback.py), hesitation-aware hints (hesitation.py) and
talking over CAPCOM. docs/GAMEPLAY.md §14, docs/LEARNING_DESIGN.md §13."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import director, hesitation, models_client, session as sessions
from app.academy import content
from app.config import settings
from app.gazetteer import Gazetteer
from app.main import app
from app.mission import capcom, gameplay as G, readback as R, registry, sim
from app.moments import MomentIndex

SITE, SEED = "shackleton_rim", 37     # the first job is "Set your power": order step "Shields up to 30"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def run(c):
    return asyncio.run(c)


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()


def mk(world, level):
    clock = Clock()
    m = registry.create(SITE, SEED, level=level)
    s = sessions.Session(f"rb-{level}", world[0], world[1], clock=clock, registry=registry)
    run(s.handle({"t": "hello", "mode": "mission", "mission_id": m.id, "role": None, "prefs": {"level": level}}))
    s.clock_obj, s.m = clock, m
    return s


def says(s):
    return [d["text"] for d in s.outbox if d["t"] == "say"]


def typed(s, text):
    s.outbox.clear()
    run(s.handle({"t": "typed", "text": text}))
    return says(s)


def heard(s, text, ear=None, at=None):
    """A turn through the ear relay: start, final words (with the ear's read-outs), end."""
    if at is not None:
        s.clock_obj.t = at
    s.outbox.clear()
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    run(s.handle({"t": "words", "text": text, "final": True, **(ear or {})}))
    s.clock_obj.t += 1.0
    run(s.handle({"t": "turn", "state": "end", "text": text}))
    return says(s)


# ------------------------------------------------------------------------------------------------ grading
def test_readback_keys_come_from_the_sims_readback():
    assert R.keys(G.ALLOC("shields", 40)) == [("shields", {"shield", "shields"}), ("40", {"40"})]
    assert R.phrase(G.ALLOC("life_support", 45)) == "life support 45"
    assert R.phrase(G.HOME) == "rover home"
    assert R.phrase({"type": "shelter", "on": False}) == "crew out"
    assert R.phrase({"type": "call_houston", "text": "x"}) == "Houston"


@pytest.mark.parametrize("text,good", [
    ("Copy, shields to forty", True),
    ("copy shields 40", True),
    ("roger, shield forty percent", True),
    ("Wilco. Shields at 40.", True),
    ("shields to forty", False),            # no radio call: an order, not a readback
    ("copy, shields to thirty", False),     # the wrong number
    ("copy shields", False),
    ("copy", False),
])
def test_readback_grade_numbers_either_way(text, good):
    assert R.grade(text, G.ALLOC("shields", 40))["good"] is good


def test_readback_grade_aliases_and_bare_acks():
    assert R.grade("Roger, air system to forty-five", G.ALLOC("life_support", 45))["good"]
    assert R.grade("copy, rover heading home", G.HOME)["good"]
    assert R.grade("copy, radio to ten", G.ALLOC("comms", 10))["good"]
    for t in ("copy", "copy that", "roger that", "copy, over", "Roger roger"):
        assert R.grade(t, G.HOME)["bare"], t
    assert not R.grade("copy rover", G.HOME)["bare"]


def test_readback_lines_praise_on_cadet_nudge_only_on_commander():
    good, part = R.grade("copy shields forty", G.ALLOC("shields", 40)), R.grade("copy", G.ALLOC("shields", 40))
    assert R.line("cadet", good, None) == R.line("commander", good, None) == "Good readback."
    assert R.line("cadet", part, G.ALLOC("shields", 40), "Shields to 40") is None
    assert R.line("commander", part, G.ALLOC("shields", 40), "Shields to 40") == "Read back: Shields to 40."
    assert R.line("commander", part, G.ALLOC("shields", 40)) == "Read back: shields 40."
    assert R.line("commander", R.grade("shields to forty", G.ALLOC("shields", 40)), G.ALLOC("shields", 40)) is None
    for ln in ("Good readback.", "Read back: Shields to 40."):     # docs/COPY.md: short, no "wrong"
        assert len(ln.split()) <= 20 and "wrong" not in ln.lower()


def test_open_order_is_the_ready_order_step_only():
    st = {"task": {"id": "t-1", "step": {"id": "power", "kind": "order", "ready": True, "label": "Shields up to 30",
                                         "cmd": G.ALLOC("shields", 30)}}}
    assert R.open_order(st) == {"key": "t-1:power", "cmd": G.ALLOC("shields", 30), "label": "Shields up to 30"}
    assert R.open_order({"task": {"id": "t", "step": {**st["task"]["step"], "ready": False}}}) is None
    assert R.open_order({"task": {"id": "t", "step": {"id": "steer", "kind": "choice", "ready": True}}}) is None
    assert R.open_order({**st, "over": True}) is None and R.open_order(None) is None


# ------------------------------------------------------------------------------------------------ the session
def test_cadet_good_readback_runs_the_cards_order_and_is_praised_once(world):
    s = mk(world, "cadet")
    step = s._state()["task"]["step"]
    assert step["kind"] == "order" and step["cmd"] == G.ALLOC("shields", 30)
    out = typed(s, "Copy, shields thirty")
    # the card's order ran ("Shields up to 30"), not the words' delta parse (+30)
    assert s.m.loads["shields"] == 30
    assert out[-1] == "Good readback." and out[0].startswith("Copy.")
    say_ids = [d for d in s.outbox if d["t"] == "say"]
    assert say_ids[-1]["after"] == say_ids[0]["id"]          # after CAPCOM's own line, its own say (20-word budget)


def test_cadet_hears_nothing_for_a_partial_readback(world):
    s = mk(world, "cadet")
    loads = dict(s.m.loads)
    assert typed(s, "copy") == [] and typed(s, "copy shields") == []
    assert s.m.loads == loads                                # never a new order, never a cost


def test_commander_partial_readback_gets_one_short_nudge_per_step(world):
    s = mk(world, "commander")
    loads = dict(s.m.loads)
    assert typed(s, "copy") == ["Read back: Shields up to 30."]
    assert typed(s, "roger that") == []                      # once per step
    assert s.m.loads == loads
    out = typed(s, "copy, shields to thirty")
    assert out[-1] == "Good readback." and s.m.loads["shields"] == 30


def test_a_radio_turn_with_another_order_runs_as_that_order(world):
    s = mk(world, "commander")
    out = typed(s, "copy, send the rover for ice")
    assert s.m.rover["busy"] and not any("readback" in x.lower() or x.startswith("Read back") for x in out)


def test_plain_order_is_not_graded(world):
    s = mk(world, "commander")
    out = typed(s, "shields to 30")
    assert s.m.loads["shields"] == 30 and "Good readback." not in out and not any(x.startswith("Read back") for x in out)


def test_a_yes_no_waiting_keeps_roger_as_yes(world):
    s = mk(world, "commander")
    typed(s, "all power to science")
    assert s._state()["pending"]
    typed(s, "roger")
    assert s.m.loads["science"] == 100 and not s._state()["pending"]


def test_a_readback_cut_in_two_by_the_ears_end_silence_is_graded_joined(world):
    s = mk(world, "commander")
    heard(s, "copy shields", ear={"eot": 0.1}, at=2000.0)        # low end-of-turn p: the kid wasn't done
    s.clock_obj.t += 0.4                                          # the next turn starts within CUT_GAP_S
    out = heard(s, "to thirty please", ear={"eot": 0.9})
    assert s.m.loads["shields"] == 30 and "Good readback." in out


def test_talking_over_capcom_never_adds_a_line(world):
    for level in ("cadet", "commander"):
        s = mk(world, level)
        s.belief["floor"] = "guide"
        s.outbox.clear()
        run(s.handle({"t": "ui", "event": "barge_in"}))
        assert says(s) == [] and s.belief["floor"] == "kid"


def test_readbacks_add_no_reward():
    """The sim never hears about a readback: the same order typed plainly or read back leaves the same mission."""
    a, b = sim.new_mission("rb-a", SITE, SEED), sim.new_mission("rb-b", SITE, SEED)
    sim.apply_command(a, G.ALLOC("shields", 30))
    sim.apply_command(b, G.ALLOC("shields", 30))
    assert sim.score(a) == sim.score(b) and a.science == b.science
    assert not hasattr(sim, "readback_bonus")


# ------------------------------------------------------------------------------------------------ hesitation
@pytest.mark.parametrize("ear,text,want", [
    ({"disfl": [{"i": 0, "w": "um", "kind": "filler"}, {"i": 2, "w": "uh", "kind": "filler"}]}, "um tycho uh crater", True),
    ({"disfl": [{"i": 0, "w": "um", "kind": "filler"}]}, "um tycho", True),
    ({"disfl": [{"i": 0, "w": "um", "kind": "filler"}]}, "um I think it is the big crater on the left", False),
    ({"disfl": [{"i": 1, "w": "th", "kind": "fragment"}, {"i": 3, "w": "the", "kind": "repeat"}]}, "it th is the the sea", True),
    ({}, "uh hmm tycho", True),                       # an ear without disfl: the fillers in the text
    ({"max_pause_s": 2.6}, "tycho crater", True),
    ({"max_pause_s": 0.7}, "tycho crater", False),    # the shipped ear's end silence caps pauses near here
    ({"uconf": 0.3}, "tycho", True),
    ({"uconf": 0.8}, "tycho", False),
    (None, "the sea of tranquility", False),
])
def test_hesitant(ear, text, want):
    assert hesitation.hesitant(ear, text) is want


def test_heard_carries_hes_on_a_lesson_step_only_and_nothing_is_kept(world):
    s = sessions.Session("hes-1", world[0], world[1], clock=Clock(), registry=registry)
    run(s.handle({"t": "hello", "mode": "academy"}))
    run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "lesson_id": "moon", "step": 0, "step_type": "intent"}))
    ear = {"disfl": [{"i": 0, "w": "um", "kind": "filler"}]}
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    run(s.handle({"t": "words", "text": "um tycho", "final": True, **ear}))
    run(s.handle({"t": "turn", "state": "end", "text": "um tycho"}))
    h = [d for d in s.outbox if d["t"] == "heard"]
    assert h and h[-1].get("hes") is True
    # in-session only: no score, nothing in the routes / history / turn log records
    assert not any("hes" in r for r in s.routes) and not any("hes" in r for r in s.history)
    # typed turns never carry it (no ear), and a calm turn doesn't either
    s.outbox.clear()
    run(s.handle({"t": "typed", "text": "um tycho"}))
    assert not any(d.get("hes") for d in s.outbox if d["t"] == "heard")


def test_heard_has_no_hes_on_the_library(world):
    s = sessions.Session("hes-2", world[0], world[1], clock=Clock(), registry=registry)
    run(s.handle({"t": "hello", "mode": "cadet"}))
    run(s.handle({"t": "ui", "event": "screen", "screen": "library"}))
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    run(s.handle({"t": "words", "text": "um uh tycho", "final": True}))
    run(s.handle({"t": "turn", "state": "end", "text": "um uh tycho"}))
    assert not any(d.get("hes") for d in s.outbox if d["t"] == "heard")


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_hesitant_miss_climbs_one_rung_sooner(client):
    A = lambda inp, misses=0, **kw: client.post("/api/academy/attempt", json={  # noqa: E731
        "lesson_id": "moon", "step": 0, "input": inp, "misses": misses, **kw}).json()
    calm, hes = A({"text": "tycho"}), A({"text": "tycho"}, hes=True)
    assert calm["status"] == hes["status"] == "hint"
    assert calm["rung"] == 1 and hes["rung"] == 2 and hes["label"] == ["tranquillitatis"]
    # never the answer sooner: the reveal still waits for real misses (and ~20 s)
    assert A({"text": "tycho"}, 1, hes=True)["status"] == "hint"
    assert "unsure" not in hes["say"].lower() and "hesitat" not in hes["say"].lower()


def test_hesitant_readback_lesson_step_shows_the_words_at_once(client):
    les = content.lesson("comms")
    assert les["steps"][1]["accept"]["type"] == "keywords"
    r = client.post("/api/academy/attempt", json={"lesson_id": "comms", "step": 1, "input": {"text": "um heaters"},
                                                  "misses": 0, "hes": True}).json()
    assert r["status"] == "hint" and r["rung"] == 2 and "40" in r["phrase"]
