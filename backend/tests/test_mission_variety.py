"""[polish 1] The mission never stalls a player who follows the Now card, never re-asks a satisfied step, and varies
its jobs day to day, each with a short why (docs/MISSION_POLISH_SPEC.md)."""
import collections

import pytest

from app.mission import gameplay, sim

SITES = ["shackleton_rim", "shackleton_floor", "malapert_massif", "connecting_ridge", "de_gerlache_rim"]


def _novice(m, cap=400):
    """Do whatever the Now card offers (the first option of a choice); when it offers nothing, skip ahead.
    Returns the step labels pressed, and fails if the same ready step is pressed 4 times with no progress."""
    pressed, last, same = [], None, 0
    for _ in range(cap):
        if m.over:
            break
        t = gameplay.view(m)["task"]
        st = t and t["step"]
        if st and st["ready"] and st["kind"] != "wait":
            cmd = {"type": "task", "task": t["id"], "step": st["id"]}
            if st["kind"] == "choice":
                cmd["choice"] = st["options"][0]["id"]
            r = sim.apply_command(m, cmd)
            if r.get("needs_confirm"):
                sim.apply_command(m, {"type": "confirm"})
            key = (t["id"], st["id"], m.t_h)
            same = same + 1 if key == last else 0
            last = key
            assert same < 3, f"stuck on a ready step the sim refuses: {t['title']}: {st['label']} -> {r.get('say')}"
            pressed.append(st["label"])
        else:
            sim.apply_command(m, {"type": "skip"})
    return pressed


@pytest.mark.parametrize("level", ["cadet", "commander", "engineer"])
@pytest.mark.parametrize("site", SITES)
def test_a_player_who_follows_the_card_always_finishes(site, level):
    for seed in (0, 1, 3):
        m = sim.new_mission("v", site, seed, level=level)
        _novice(m)
        assert m.over, f"{site} {level} seed {seed}: the mission never ended (t_h={m.t_h})"


def test_a_rover_step_waits_while_the_rover_is_out():
    m = sim.new_mission("v", "malapert_massif", 0, level="commander")
    m.rover.update(busy=True, task="collect_ice", eta_h=9)
    s = gameplay._order("send", "Send the rover to fix it", "task", gameplay.ROVER("repair_array"),
                        lambda m, t: False, None)
    gameplay._gate_rover(s)
    assert not s["ready_if"](m, {})
    assert "Back in about 9 h" in s["wait_text"](m, {})
    m.rover.update(busy=False, task=None, eta_h=0)
    m.shelter = True
    assert not s["ready_if"](m, {}) and "shelter" in s["wait_text"](m, {})


def test_a_satisfied_step_is_never_asked_again():
    m = sim.new_mission("v", "malapert_massif", 0, level="cadet")
    t = {"id": "x", "kind": "night_prep", "status": "active", "started_h": 0, "steps": [
        gameplay._order("heaters", "Heaters to 10", "load:heaters", gameplay.ALLOC("heaters", 10),
                        lambda m, t: m.loads["heaters"] >= 10, "ok"),
        gameplay._press("battery", "Check the battery", None)]}
    t["steps"][0].setdefault("latch", True)
    for s in t["steps"]:
        s.setdefault("done", False)
    m.loads = sim.reallocate(m.loads, "heaters", 10, None)
    gameplay._gp(m)["tasks"]["x"], gameplay._gp(m)["order"] = t, gameplay._gp(m)["order"] + ["x"]
    gameplay._check(m, [])
    assert t["steps"][0]["done"]
    m.loads = sim.reallocate(m.loads, "life_support", 40, None)   # trims the heaters to 9 or so
    assert m.loads["heaters"] < 10
    gameplay._check(m, [])
    assert t["steps"][0]["done"], "Heaters to 10 came back after another power move"


def test_heaters_are_only_asked_while_low():
    m = sim.new_mission("v", "malapert_massif", 0, level="cadet")
    assert any(s["id"] == "heaters" for s in gameplay._night_prep(m)["steps"])
    m.loads = sim.reallocate(m.loads, "heaters", 9, None)
    steps = gameplay._night_prep(m)["steps"]
    assert not any(s["id"] == "heaters" for s in steps)
    assert {s["id"] for s in steps} & {"battery", "sunset"}, "a different second job instead"


def test_jobs_vary_and_each_step_says_why():
    seen = collections.Counter()
    for site in SITES:
        m = sim.new_mission("v", site, 2, level="commander")
        _novice(m)
        g = gameplay._gp(m)
        subs = [g["tasks"][i].get("sub") for i in g["order"] if g["tasks"][i]["kind"] == "science"]
        assert all(a != b for a, b in zip(subs, subs[1:])), f"{site}: the same science job twice in a row: {subs}"
        heat = [i for i in g["order"] if any(s["id"] == "heaters" and s["done"] for s in g["tasks"][i]["steps"])]
        assert len(heat) <= 1 or m.loads["heaters"] < gameplay.HEATERS_SAFE
        for i in g["order"]:
            for s in g["tasks"][i]["steps"]:
                seen[bool(s.get("why") or s.get("hint"))] += 1
    assert seen[True] / sum(seen.values()) >= 0.8, seen


@pytest.mark.parametrize("level", ["cadet", "commander", "engineer"])
@pytest.mark.parametrize("site", SITES)
def test_every_mission_gets_a_sample_station(site, level):
    """[0.4.1] Every mission has at least one Field School task: the sample station shows up, even at Malapert where
    the lab never gets a quiet hour (the rover crew stops for it on a drive). Low-Sun calls stay on ice runs; one
    replan a mission at most."""
    for seed in (0, 1, 3, 7):
        m = sim.new_mission("v", site, seed, level=level)
        _novice(m)
        tasks = list(m.gp["tasks"].values())
        assert any(t["kind"] == "science" and t.get("sub") == "sample" for t in tasks), (site, level, seed)
        assert m.gp["count"].get("replan", 0) <= gameplay.REPLAN_MAX
        assert all(t["kind"] == "ice_run" for t in tasks if any(s["id"] == "tack" for s in t["steps"]))
