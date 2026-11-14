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


def test_embed_fallback_fills_slots_and_validates(monkeypatch):
    """Rules miss -> nearest bank example gives the shape; the load comes from the kid's words; valid() runs."""
    from app import models_client
    import numpy as np
    bank = [{"text": "the plants look sad and droopy", "command": A("greenhouse", "little", 5)},
            {"text": "go to the shelter", "command": {"type": "shelter", "on": True}}]
    monkeypatch.setitem(nlu._BANK, "examples", bank)
    monkeypatch.setitem(nlu._BANK, "vecs", np.eye(2, dtype=np.float32))

    async def fake_embed(texts, kind="query", timeout=None):
        return [[0.9, 0.1]]
    monkeypatch.setattr(models_client, "embed", fake_embed)
    out = asyncio.run(nlu.understand("the veggies are hungry for electrons"))
    assert out["source"] == "embed" and out["commands"] == [A("greenhouse", "little", 5)]
    # far from every example -> nothing (a wrong command is worse than asking again)

    async def far(texts, kind="query", timeout=None):
        return [[0.5, 0.5]]
    monkeypatch.setattr(models_client, "embed", far)
    assert asyncio.run(nlu.understand("the veggies are hungry for electrons"))["source"] == "none"


def test_embed_fallback_never_borrows_a_positive_for_a_negation(monkeypatch):
    from app import models_client
    import numpy as np
    monkeypatch.setitem(nlu._BANK, "examples", [{"text": "go to the shelter", "command": {"type": "shelter", "on": True}}])
    monkeypatch.setitem(nlu._BANK, "vecs", np.eye(1, dtype=np.float32))

    async def near(texts, kind="query", timeout=None):
        return [[1.0]]
    monkeypatch.setattr(models_client, "embed", near)
    cmds, score, _ = asyncio.run(nlu.bank_parse("we should never ever hide in that bunker thing"))
    assert cmds == [] and score > 0.9


def test_command_bank_is_valid():
    ex = nlu._bank()
    assert 300 <= len(ex) <= 600 and all(nlu.valid(e["command"]) for e in ex)


def test_arc_numbers_fill_in_amount():
    out = nlu.parse("move the shields up by some", read={"numbers": ["twenty percent"]})
    assert out["commands"] == [A("shields", "delta", 20)]


def test_set_to_is_absolute_share():
    from app.mission.nlu import parse
    for t in ["shields to 40", "make the shields 40", "set shields to 40", "heaters at 30 percent"]:
        c = parse(t)["commands"][0]
        assert c["amount"] == {"kind": "percent", "value": int(t.split()[-1]) if t.split()[-1].isdigit() else 30}, t
    c = parse("move 20% to shields")["commands"][0]
    assert c["amount"]["kind"] == "delta" and c["amount"]["value"] == 20


# ONE slot convention (nlu.py docstring): a little = +-5, more/less = +-10, "to N" = set N, "N more" = +N.
CONVENTION = [
    ("a little more power to the shields", A("shields", "little", 5)),
    ("a bit less for the heaters", A("heaters", "little", -5)),
    ("more power to the shields", A("shields", "delta", 10)),
    ("turn down the heaters", A("heaters", "delta", -10)),
    ("dial back the comms", A("comms", "delta", -10)),
    ("lower the shields to 20 percent", A("shields", "percent", 20)),
    ("turn the heaters up to 60", A("heaters", "percent", 60)),
    ("set the greenhouse to 35 percent", A("greenhouse", "percent", 35)),
    ("give the shields 15 more percent", A("shields", "delta", 15)),
    ("add 20 to the heaters", A("heaters", "delta", 20)),
]


@pytest.mark.parametrize("text,cmd", CONVENTION)
def test_slot_convention_rules(text, cmd):
    assert nlu.parse(text)["commands"] == [cmd]


def test_slot_convention_bank_and_fill():
    """The command bank and the embed fill agree with the rules: plain more/less examples are +-10, never `little`
    unless the words say a little / a bit; an implied need (no more/less word) is a +5 nudge."""
    import json
    from pathlib import Path
    bank = json.loads((Path(__file__).resolve().parents[1] / "data/mission/command_bank.json").read_text())["examples"]
    for e in bank:
        c = e["command"]
        c = c.get("then") if c.get("type") == "rule" else c
        if (c or {}).get("type") != "allocate" or c["amount"]["kind"] != "little":
            continue
        t = nlu._words_to_digits(nlu.norm(e["text"]))
        assert nlu.LITTLE.search(t) or not (nlu.MORE.search(t) or nlu.LESS.search(t)), e["text"]
    ex = {"text": "x", "command": A("greenhouse", "little", 5)}
    assert nlu.fill_slots(ex, "the plants need more power")["amount"] == {"kind": "delta", "value": 10}
    assert nlu.fill_slots(ex, "a little more for the plants")["amount"] == {"kind": "little", "value": 5}
    assert nlu.fill_slots(ex, "the plants look sad")["amount"] == {"kind": "little", "value": 5}
