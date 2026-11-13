"""Mission command understanding: kid phrasings -> Commands (docs/MISSION_CONTRACT.md). Rules only (no LLM in tests)."""
import asyncio

import pytest

from app.mission import nlu


def A(to, kind, value, src=None):
    return {"type": "allocate", "to": to, "amount": {"kind": kind, "value": value}, "from": src}


def D(task, target=None):
    return {"type": "dispatch", "vehicle": "rover", "task": task, "target": target}


Q = lambda what: {"type": "query", "what": what}  # noqa: E731
CLARIFY = "CLARIFY"

TABLE = [
    # allocate + synonyms
    ("move power to the shields", [A("shields", "delta", 10)]),
    ("more power to the radiation shield", [A("shields", "delta", 10)]),
    ("give the protection more power", [A("shields", "delta", 10)]),
    ("put 20 percent into life support", [A("life_support", "delta", 20)]),
    ("more energy for the air please", [A("life_support", "delta", 10)]),
    ("move 15% to oxygen", [A("life_support", "delta", 15)]),
    ("a little more for the plants", [A("greenhouse", "little", 5)]),
    ("a bit less power for the greenhouse", [A("greenhouse", "little", -5)]),
    ("more power to the buggy", [A("rover", "delta", 10)]),
    ("less power for the radio", [A("comms", "delta", -10)]),
    ("give half to life support", [A("life_support", "half", 50)]),
    ("all of it to the air", [A("life_support", "all", 100)]),
    ("give everything to the shields", [A("shields", "all", 100)]),
    ("turn off the science lab", [A("science", "none", 0)]),
    ("no power for the experiments", [A("science", "none", 0)]),
    ("set the shields to 30 percent", [A("shields", "percent", 30)]),
    ("twenty five percent to the greenhouse", [A("greenhouse", "delta", 25)]),
    ("take 10 percent from science and give it to the shields", [A("shields", "delta", 10, "science")]),
    ("move ten percent from the lab to the heaters", [A("heaters", "delta", 10, "science")]),
    ("turn the heaters up", [A("heaters", "delta", 10)]),
    # dispatch
    ("send the rover for ice", [D("collect_ice")]),
    ("send the buggy to get water", [D("collect_ice")]),
    ("go fix the solar panels with the rover", [D("repair_array")]),
    ("bring the rover back", [D("return")]),
    ("send the buggy to shackleton crater", [D("explore", "shackleton_crater")]),
    ("drive the rover around and explore", [D("explore")]),
    # shelter
    ("everyone into the shelter", [{"type": "shelter", "on": True}]),
    ("hide in the shelter now", [{"type": "shelter", "on": True}]),
    ("everybody come out of the shelter", [{"type": "shelter", "on": False}]),
    # queries
    ("how much oxygen do we have", [Q("oxygen")]),
    ("how much radiation did we get", [Q("dose")]),
    ("how much power is left", [Q("power")]),
    ("is there a solar storm", [Q("storm")]),
    ("what's the status", [Q("all")]),
    ("when can we talk to earth", [Q("comms")]),
    # Houston
    ("Houston, how much oxygen do we have?", [{"type": "call_houston", "text": "how much oxygen do we have"}]),
    ("call mission control", [{"type": "call_houston", "text": ""}]),
    # time
    ("end shift", [{"type": "end_shift"}]),
    ("next", [{"type": "end_shift"}]),
    # confirm / cancel
    ("yes", [{"type": "confirm"}]),
    ("do it", [{"type": "confirm"}]),
    ("confirm", [{"type": "confirm"}]),
    ("yeah go ahead", [{"type": "confirm"}]),
    ("no", [{"type": "cancel"}]),
    ("never mind", [{"type": "cancel"}]),
    ("cancel that", [{"type": "cancel"}]),
    # compound
    ("move 20% to shields and send the rover for ice", [A("shields", "delta", 20), D("collect_ice")]),
    ("power to shields and heaters", [A("shields", "delta", 10), A("heaters", "delta", 10)]),
    ("turn off the science lab then everyone into the shelter", [A("science", "none", 0),
                                                                  {"type": "shelter", "on": True}]),
    # negation -> no command, a question
    ("don't turn off the heaters", CLARIFY),
    ("do not send the rover", CLARIFY),
    # conditionals -> a standing order
    ("if a storm comes go to the shelter", [{"type": "rule", "when": "storm", "then": {"type": "shelter", "on": True}}]),
    ("when it gets dark turn the heaters up", [{"type": "rule", "when": "dark", "then": A("heaters", "delta", 10)}]),
    ("if the power gets low, turn off the science lab", [{"type": "rule", "when": "low_power",
                                                          "then": A("science", "none", 0)}]),
    # held-out misses, fixed after measuring
    ("switch the radio off", [A("comms", "none", 0)]),
    ("rover come home", [D("return")]),
    ("give the greenhouse thirty and take it from science", [A("greenhouse", "delta", 30, "science")]),
    ("ok that sounds good", [{"type": "confirm"}]),
    ("nah forget about it", [{"type": "cancel"}]),
    ("how long till we can call home", [Q("comms")]),
    ("we're freezing in here", [A("heaters", "delta", 10)]),
    # vague -> ask
    ("more power", CLARIFY),
]


def run_table():
    ok = []
    for text, want in TABLE:
        got = nlu.parse(text)
        got_cmds = [c for c in map(nlu.valid, got["commands"]) if c]
        if want == CLARIFY:
            ok.append(not got_cmds and bool(got["needs_clarify"]))
        else:
            ok.append(got_cmds == want)
    return ok


@pytest.mark.parametrize("text,want", TABLE, ids=[t for t, _ in TABLE])
def test_nlu_table(text, want):
    got = nlu.parse(text)
    cmds = [c for c in map(nlu.valid, got["commands"]) if c]
    if want == CLARIFY:
        assert not cmds and got["needs_clarify"], got
    else:
        assert cmds == want, got


def test_table_size_and_accuracy():
    ok = run_table()
    assert len(ok) >= 40
    assert sum(ok) / len(ok) >= 0.95


def test_validator_drops_bad_commands():
    assert nlu.valid({"type": "allocate", "to": "lasers", "amount": {"kind": "delta", "value": 5}}) is None
    assert nlu.valid({"type": "allocate", "to": "shields", "amount": {"kind": "lots", "value": 5}}) is None
    assert nlu.valid({"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 300}}) is None
    assert nlu.valid({"type": "dispatch", "vehicle": "rover", "task": "dance"}) is None
    assert nlu.valid({"type": "launch_nukes"}) is None
    assert nlu.valid({"type": "query", "what": "oxygen"}) == {"type": "query", "what": "oxygen"}
    assert nlu.valid({"type": "allocate", "to": "shields", "amount": {"kind": "delta", "value": 5}}) == \
        A("shields", "delta", 5)


def test_llm_fallback_validated(monkeypatch):
    async def fake_llm(text, state=None):
        raw = [{"type": "allocate", "to": "greenhouse", "amount": {"kind": "delta", "value": 10}, "from": None},
               {"type": "fly_to_mars"}]
        return [v for v in map(nlu.valid, raw) if v]
    monkeypatch.setattr(nlu, "llm_parse", fake_llm)
    out = asyncio.run(nlu.understand("the veggies are hungry for electrons"))
    assert out["source"] == "llm" and out["commands"] == [A("greenhouse", "delta", 10)]


def test_arc_numbers_fill_in_amount():
    out = nlu.parse("move the shields up by some", read={"numbers": ["twenty percent"]})
    assert out["commands"] == [A("shields", "delta", 20)]
