"""Director in mission mode with a fake sim (the real one is app/mission/registry.py, built separately)."""
import asyncio
import copy

import pytest

from app import director
from app.gazetteer import Gazetteer
from app.config import settings
from app.mission import capcom
from app.moments import MomentIndex

STATE = {"id": "m-1", "day": 3, "shift": 2, "mission_time_h": 66, "over": False, "outcome": None,
         "resources": {"power_pct": 72, "life_support_pct": 81, "dose_msv": 14.2, "dose_limit_msv": 50,
                       "dose_rate_msv_h": 0.06},
         "loads": {"shields": 20, "life_support": 30, "greenhouse": 15, "science": 15, "rover": 10, "comms": 5,
                   "heaters": 5},
         "env": {"sun_elev_deg": 1.8, "in_sun": True, "earth_elev_deg": 2.0, "earth_visible": True,
                 "next_comm_window_h": 0, "comm_delay_s": 2.6, "storm": {"active": False}},
         "rover": {"busy": False, "task": None, "eta_h": 0}, "shelter": False, "alerts": [], "log": [], "score": 0}


class FakeMission:
    def __init__(self):
        self.s = copy.deepcopy(STATE)
        self.applied = []

    def state(self):
        return self.s

    def apply(self, cmd):
        self.applied.append(cmd)
        risky = cmd["type"] == "allocate" and cmd["amount"]["kind"] in ("all", "none") and cmd["to"] in (
            "heaters", "life_support", "shields")
        if cmd["type"] == "shelter":
            self.s["shelter"] = cmd["on"]
        return {"state": self.s, "result": {"ok": True, "needs_confirm": risky, "say": "", "readback": None,
                                            "events": []}}


class FakeRegistry:
    def __init__(self):
        self.m = FakeMission()

    def get(self, mid):
        return self.m if mid == "m-1" else None


@pytest.fixture
def sim(monkeypatch):
    reg = FakeRegistry()
    monkeypatch.setattr(director, "_sim", lambda: reg)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()
    return reg


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


def ask(world, text, **ctx):
    gaz, index = world
    ctx.setdefault("mission", {"id": "m-1", "role": None})
    return asyncio.run(director.direct(text, {"available": False}, gaz, index, ctx))


def test_command_readback_and_tradeoff(sim, world):
    r = ask(world, "move 20% to the shields")
    assert r["action"] == "command" and r["command"]["to"] == "shields"
    assert r["say"].startswith("Copy, commander. Moving 20 percent of power to the radiation shields.")
    assert "leaves less for the life support" in r["say"]
    assert sim.m.applied == [r["command"]]


def test_compound_applies_both(sim, world):
    r = ask(world, "move 20% to shields and send the rover for ice")
    assert [c["type"] for c in sim.m.applied] == ["allocate", "dispatch"]
    assert len(r["commands"]) == 2 and "rover" in r["say"] and r["say"].count("Copy, commander.") == 1


def test_status_answer_explains_units_once(sim, world):
    r = ask(world, "how much radiation did we get?")
    assert r["action"] == "status" and "14.2 mSv" in r["say"] and "a unit for radiation dose" in r["say"] and r["state"]
    r2 = ask(world, "how much radiation did we get?")
    assert "a unit for radiation dose" not in r2["say"] and "14.2 mSv" in r2["say"]


def test_houston_delay(sim, world):
    r = ask(world, "Houston, how much oxygen do we have?")
    assert r["action"] == "houston" and r["delay_ms"] == 2600 == capcom.MOON_ROUND_TRIP_MS
    assert r["say"].startswith("Houston here.") and "81 percent" in r["say"]


def test_houston_out_of_contact(sim, world):
    sim.m.s["env"]["earth_visible"] = False
    r = ask(world, "call Houston")
    assert r["action"] == "houston" and r["delay_ms"] == 0 and "can't reach Houston" in r["say"]


def test_needs_confirm_then_yes(sim, world):
    r = ask(world, "turn off the heaters")
    assert r["action"] == "command" and r["needs_confirm"] is True and "Are you sure" in r["say"]
    r2 = ask(world, "yes")
    assert sim.m.applied[-1] == {"type": "confirm"} and r2["action"] == "command"


def test_role_gating(sim, world):
    r = ask(world, "move 20% to the shields", mission={"id": "m-1", "role": "comms"})
    assert r["say"] == "That's the power officer's job. Power officer, do you agree?"
    assert r["needs_confirm"] is True and r["needs_role"] == "power" and sim.m.applied == []
    r2 = ask(world, "yes", mission={"id": "m-1", "role": "life"})
    assert "power officer" in r2["say"] and sim.m.applied == []
    r3 = ask(world, "yes", mission={"id": "m-1", "role": "power"})
    assert sim.m.applied and sim.m.applied[0]["to"] == "shields" and r3["say"].startswith("Copy")


def test_own_role_allowed(sim, world):
    r = ask(world, "move 20% to the shields", mission={"id": "m-1", "role": "power"})
    assert r["action"] == "command" and sim.m.applied


def test_negation_asks(sim, world):
    r = ask(world, "don't turn off the heaters")
    assert r["action"] == "ask" and "heaters" in r["say"] and sim.m.applied == []


def test_standing_order_fires_on_storm(sim, world):
    r = ask(world, "if a storm comes go to the shelter")
    assert r["action"] == "command" and r["command"]["type"] == "rule" and "Standing order set" in r["say"]
    assert sim.m.applied == []
    sim.m.s["env"]["storm"] = {"active": True, "name": "Real solar storm, May 2024"}
    r2 = ask(world, "how much power do we have")
    assert sim.m.applied == [{"type": "shelter", "on": True}] and r2["say"].startswith("Standing order!")
    ask(world, "how much power do we have")
    assert len(sim.m.applied) == 1   # fires once per storm


def test_emotion_shapes_line(sim, world):
    calm = ask(world, "move 20% to the shields", emotion="confused")
    assert calm["say"] == "Copy. Moving 20 percent of power to the radiation shields."
    hype = ask(world, "everyone into the shelter", emotion="excited")
    assert hype["say"].endswith("!")


def test_chatter_ignored(sim, world):
    r = ask(world, "I like pizza", device_directed=0.1)
    assert r["action"] == "none" and r["say"] == "" and sim.m.applied == []


def test_non_mission_question_falls_through(sim, world):
    r = ask(world, "show me the giant bullseye", device_directed=0.9)
    assert r["action"] == "fly" and r["place"] == "orientale"


def test_privacy_guard_still_first(sim, world):
    r = ask(world, "my name is Sam, send the rover for ice")
    assert r["action"] == "guard" and sim.m.applied == []


def test_no_sim_says_not_started(monkeypatch, world):
    monkeypatch.setattr(director, "_sim", lambda: None)
    r = ask(world, "send the rover for ice")
    assert r["action"] == "say" and "hasn't started" in r["say"]
    r = ask(world, "how much oxygen do we have")
    assert r["action"] == "status" and "hasn't started" in r["say"]


def test_api_ask_passes_mission_context(sim):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/ask", json={"text": "Houston, are we okay?",
                                     "context": {"mission": {"id": "m-1", "role": "comms"}}}).json()
    assert r["action"] == "houston" and r["delay_ms"] == 2600


def test_ui_contract_command_always_has_state(sim, world):
    """UI: `state` present = handled server-side (never POST again); needs_confirm = nothing applied yet."""
    r = ask(world, "move 20% to the shields")
    assert r["state"] and r["applied"] is True and r["readback"] == r["say"] and r["needs_confirm"] is False
    r = ask(world, "turn off the heaters")
    assert r["state"] and r["needs_confirm"] is True and r["applied"] is False
    r = ask(world, "no")
    assert r["action"] == "command" and r["state"] and sim.m.applied[-1] == {"type": "cancel"}
    r = ask(world, "move 20% to the shields", mission={"id": "m-1", "role": "comms"})
    assert r["state"] and r["needs_confirm"] is True and r["applied"] is False
