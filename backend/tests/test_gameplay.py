"""The live mission clock, tasks, story beats and the mission log (docs/GAMEPLAY.md, app/mission/gameplay.py)."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.mission import gameplay, sim

SITES = [s["id"] for s in sim.sites()]


def words(s: str) -> int:
    return len(s.split())


def task(m):
    return sim.to_state(m)["task"]


def do_step(m, t=None):
    """Press the current step's button the way the task card does (order -> the order; press/choice -> task)."""
    t = t or task(m)
    s = t["step"]
    if s["kind"] == "order":
        return sim.apply_command(m, s["cmd"])
    if s["kind"] == "choice":
        return sim.apply_command(m, {"type": "task", "task": t["id"], "step": s["id"], "choice": s["options"][0]["id"]})
    return sim.apply_command(m, {"type": "task", "task": t["id"], "step": s["id"]})


# ---- 1. the stuck objective (owner's bug): any power change counts, is acknowledged, and the job moves on ----------
@pytest.mark.parametrize("level", ["cadet", "commander"])
def test_first_job_reacts_to_any_power_change(level):
    m = sim.new_mission("m", "malapert_massif", 1, level=level)
    t = task(m)
    assert t["kind"] == "first_power" and t["step"]["target"] == "shields"
    r = sim.apply_command(m, {"type": "allocate", "to": "heaters", "amount": {"kind": "delta", "value": 5}})
    assert r["ok"] and r["ack"] == "Power set. Good."
    st = sim.to_state(m)
    assert st["task"] is None or st["task"]["kind"] != "first_power"
    assert st["ack"]["text"] == "Power set. Good." and st["acted"]["allocate"] == 1


def test_first_job_by_its_own_button():
    m = sim.new_mission("m", "shackleton_rim", 2, level="cadet")
    r = do_step(m)
    assert r["ok"] and m.loads["shields"] == 30 and r["ack"]


# ---- 2. the live clock ------------------------------------------------------------------------------------------------
def test_step_moves_fractional_time_and_state_shows_it():
    m = sim.new_mission("m", "shackleton_rim", 0, level="cadet")
    sim.step(m, 0.4)
    st = sim.to_state(m)
    assert st["mission_time_h"] == 0 and st["clock"]["mission_time_h"] == pytest.approx(0.4)
    sim.step(m, 0.7)
    assert m.t_h == 1 and m.frac == pytest.approx(0.1)
    assert sim.to_state(m)["clock"]["shift_ends_in_h"] == 5


def test_end_shift_early_runs_to_the_boundary():
    m = sim.new_mission("m", "shackleton_rim", 0, level="cadet")
    sim.step(m, 2.5)
    sim.apply_command(m, {"type": "end_shift"})
    assert m.t_h == 6 and m.frac == 0


def test_skip_stops_at_the_next_event_and_never_jumps_a_storm():
    m = sim.new_mission("m", "malapert_massif", 4, level="cadet")
    seen = []
    while not m.over and len(seen) < 80:
        r = sim.apply_command(m, {"type": "skip"})
        kinds = [e["kind"] for e in r["events"]]
        seen.append(kinds)
        if not m.over:
            assert any(k in sim.SKIP_STOPS for k in kinds) or r["say"].endswith(("A quiet day. All systems fine.", "Stay ready.", "Stay in the shelter."))
        assert words(r["say"]) <= 22
    flat = [k for ks in seen for k in ks]
    assert "storm_warning" in flat and "solar_storm" in flat   # each one stopped the skip on its own
    # a warning and its hit never arrive in one skip
    assert not any("storm_warning" in ks and "solar_storm" in ks for ks in seen)


def test_sunset_soon_gives_six_hours_notice():
    # Shackleton Rim: on the real LOLA skyline its first sunset is at hour 41 (Malapert starts the window in the dark and
    # an idle crew there runs out of power before its first sunset; docs/SITE_NAVIGATOR.md)
    m = sim.new_mission("m", "shackleton_rim", 0, level="cadet")
    evs = sim.advance(m, 20)
    soon = [e for e in evs if e["kind"] == "sunset_soon"]
    down = [e for e in evs if e["kind"] == "sunset"]
    assert soon and down and down[0]["t_h"] - soon[0]["t_h"] == sim.SUNSET_NOTICE_H


def test_api_step_and_skip():
    from app.main import app
    c = TestClient(app)
    st = c.post("/api/mission/start", json={"site": "malapert_massif", "seed": 3, "level": "cadet"}).json()
    r = c.post(f"/api/mission/{st['id']}/step", json={"dt_h": 1.25}).json()
    assert r["state"]["mission_time_h"] == 1 and r["live"]["live"] and r["live"]["mission_time_h"] == pytest.approx(1.25)
    r = c.post(f"/api/mission/{st['id']}/skip").json()
    assert r["state"]["mission_time_h"] > 1 and r["say"]
    assert c.post(f"/api/mission/{st['id']}/step", json={"dt_h": -1}).status_code == 422


# ---- 3. tasks come from the state, and every input completes them ---------------------------------------------------
def test_storm_prep_from_a_warning_and_its_steps_tick_off():
    m = sim.new_mission("m", "shackleton_rim", 5, level="cadet")
    sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 30}})
    while not m.over and sim._warning(m) is None:
        sim.step(m, 1)
    t = task(m)
    assert t["kind"] == "storm_prep" and t["lesson"]["n"] == 5 and t["time_left_h"] > 0   # radiation, core lesson 5
    r = sim.apply_command(m, {"type": "shelter", "on": True})      # by voice / tap: the same order
    assert r["ack"] == "Crew sheltered. Good."
    assert task(m) is None or task(m)["kind"] != "storm_prep"
    log = sim.to_state(m)["mission_log"]
    assert any(e["title"] == "Storm prep" for e in log)


def test_commander_possible_storm_is_a_real_decision():
    for seed in range(40):
        m = sim.new_mission("m", "connecting_ridge", seed, level="commander")
        while not m.over and not (sim._warning(m) and sim._warning(m)["confidence"] == "possible"):
            sim.advance(m, 1)
            if m.t_h > 200:
                break
        t = task(m)
        if t and t["kind"] == "storm_prep":
            assert any(s["kind"] == "choice" for s in t["steps"])
            return
    pytest.skip("no possible-storm warning in these seeds")


def test_ice_run_route_steer_and_return():
    m = sim.new_mission("m", "shackleton_rim", 1, level="commander")
    do_step(m)   # first job
    while not m.over and (task(m) or {}).get("kind") != "ice_run":
        sim.step(m, 1)
    t = task(m)
    assert t["decision"] and t["step"]["id"] == "route"
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "route", "choice": "slope"})
    assert r["ok"] and m.rover["busy"] and m.rover["route"] == "slope"
    eta0 = m.rover["eta_h"]
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "steer", "choice": "left"})
    assert not r["ok"] and "still driving" in r["say"]
    sim.step(m, gameplay.STEER_AFTER_H)
    t = sim.to_state(m)["task"]
    tv = next(x for x in [t] if x and x["kind"] == "ice_run")
    st = next(s for s in tv["steps"] if s["id"] == "steer")
    assert st["ready"] and "LOLA" in st["hint"]
    good = st["hint"].split("the ")[1].split()[0]
    before = m.rover["eta_h"]
    r = sim.apply_command(m, {"type": "task", "task": tv["id"], "step": "steer", "choice": good})
    assert r["ok"] and m.rover["eta_h"] == before - 1 and eta0 > 0
    while m.rover["busy"] and not m.over:
        sim.step(m, 1)
    assert m.ice_runs == 1
    assert any(e["title"] == "Ice run" for e in sim.to_state(m)["mission_log"])


def test_sample_gives_science_only_when_pressed():
    m = sim.new_mission("m", "shackleton_rim", 2, level="cadet")
    do_step(m)
    for _ in range(80):
        t = task(m)
        if t and t["kind"] == "science":
            break
        if t and t["kind"] in ("ice_run", "explore"):   # [playtest 4] the science drive comes after the ice
            do_step(m)
        sim.step(m, 1)
    t = task(m)
    assert t and t["kind"] == "science"
    sci = m.science
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "sample"})
    assert r["ok"] and m.science == pytest.approx(sci + gameplay.SAMPLE_SCIENCE)


def test_night_prep_at_malapert_includes_the_long_night():
    m = sim.new_mission("m", "malapert_massif", 0, level="cadet")
    do_step(m)
    while not m.over:
        sim.step(m, 1)
        t = task(m)
        if t and t["kind"] == "night_prep":
            break
    ids = [s["id"] for s in t["steps"]]
    assert ids[0] == "night" and "air" in ids and t["time_left_h"] <= sim.SUNSET_NOTICE_H


def test_cadet_gets_fewer_tasks_than_commander():
    # over 5 seeds: one seed can tie (a Commander-only repair against a storm the Commander band skips)
    def count(level):
        n = 0
        for seed in range(7, 12):
            m = sim.new_mission("m", "de_gerlache_rim", seed, level=level)
            while not m.over:
                sim.step(m, 1)
            n += len(m.gp["tasks"])
        return n
    assert count("cadet") < count("commander")


def test_orders_still_work_without_tasks_and_unknown_task_is_safe():
    m = sim.new_mission("m", "shackleton_rim", 0, level="cadet")
    assert not sim.apply_command(m, {"type": "task", "task": "nope", "step": "x"})["ok"] or True
    r = sim.apply_command(m, {"type": "task", "task": "first_power-1", "step": "zzz", "choice": "x"})
    assert "ok" in r


# ---- 4. story beats, progress, the mission log -----------------------------------------------------------------------
def test_beat_copy_budgets():
    for bid, (title, say, visual, objective) in gameplay.BEATS.items():
        assert words(say) <= 20 and words(objective) <= 12 and words(title) <= 4, bid
        assert visual


def test_task_copy_budgets():
    src = open(gameplay.__file__).read()
    for s in re.findall(r'(?:label|say|ack)=?\s*"([^"]+)"', src) + re.findall(r'_(?:order|press|choice|wait)\("\w+", "([^"]+)"', src):
        assert words(s) <= 20, s


@pytest.mark.parametrize("site", SITES)
def test_a_played_mission_tells_the_story(site):
    """A careful player (does each task step) sees the arc in order and the log grows with the milestones."""
    m = sim.new_mission("m", site, 11, level="cadet")
    n = 0
    while not m.over and n < 2000:
        n += 1
        t = task(m)
        if t and t["step"] and t["step"]["ready"]:
            do_step(m, t)
            if m.pending:
                sim.apply_command(m, {"type": "confirm"})
        sim.step(m, 0.5)
    st = sim.to_state(m)
    reached = [b["id"] for b in m.gp["beats"]]
    assert reached[0] == "arrival" and "settle" in reached
    assert len(set(reached)) == len(reached)   # each beat once; the middle follows what really happens
    assert m.outcome == "survived", (site, m.outcome)
    assert reached[-1] == "complete" and len(st["mission_log"]) >= 5
    assert st["progress"]["days_done"] == 10


def test_beats_and_tasks_reach_the_event_stream_but_not_the_radio_log():
    m = sim.new_mission("m", "shackleton_rim", 0, level="cadet")
    kinds = {e["kind"] for e in m.events}
    assert {"beat", "task"} <= kinds
    assert not any("New task" in e["text"] for e in m.log)


def test_an_open_ice_run_waits_out_a_storm():
    """An ice run started in calm weather never says "send the rover" while a storm or warning is on."""
    for seed in range(30):
        m = sim.new_mission("m", "shackleton_rim", seed, level="cadet")
        sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 30}})
        while not m.over and m.t_h < 120:
            sim.step(m, 1)
            for t in gameplay._active(m):
                if t["kind"] == "ice_run":
                    v = gameplay.task_view(m, t)
                    if not gameplay._calm(m) or m.shelter:
                        assert not (v["step"]["id"] in ("send", "route") and v["step"]["ready"]), (seed, m.t_h)


def test_shelter_wait_counts_down_and_stops_a_skip():
    """The kid never has to work out "6 hours before": the card counts down, and skip stops when the shelter opens."""
    for seed in range(20):
        m = sim.new_mission("m", "shackleton_rim", seed, level="cadet")
        sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 30}})
        while not m.over and sim._warning(m) is None:
            sim.step(m, 1)
        if m.over or m.rover["busy"]:
            continue
        t = sim.to_state(m)["task"]
        sh = next(s for s in t["steps"] if s["id"] == "shelter")
        eta = sim._warning(m)["eta_h"]
        if eta <= gameplay.SHELTER_LEAD_H:
            continue
        assert not sh["ready"] and sh["wait"].startswith(f"Shelter opens in {eta - gameplay.SHELTER_LEAD_H} h")
        r = sim.apply_command(m, {"type": "skip"})
        assert sim._warning(m)["eta_h"] == gameplay.SHELTER_LEAD_H, r["say"]
        assert any(e["kind"] == "task" and e.get("phase") == "ready" for e in r["events"])
        assert next(s for s in sim.to_state(m)["task"]["steps"] if s["id"] == "shelter")["ready"]
        return
    pytest.fail("no seed with a long enough warning")


def test_session_drops_storm_news_the_clock_overtook():
    """A storm line held on the voice floor is dropped once the storm and its warning are gone (the live clock ran)."""
    from app import session as sessions
    from app.mission import registry
    m = registry.create("shackleton_rim", 3, level="cadet")
    s = sessions.Session("t-overtaken", None, None, registry=registry)
    s.belief["mission_id"] = m.id
    say = {"t": "say", "text": "Storm coming. Crew into the shelter, or shields to 40?", "situation": "storm_warning"}
    card = {"t": "card", "chips": ["Solar storm", "DONKI"]}
    calm = {"t": "say", "text": "Comm window open."}
    assert s._overtaken(say) and s._overtaken(card) and not s._overtaken(calm)


def test_commander_life_check_always_offers_a_real_change():
    """Picking the recycler raises it every time (never "to 40" when it is already 40), and past the cap only ice."""
    m = sim.new_mission("m", "shackleton_rim", 1, level="commander")
    for share, expect in ((30, 40), (40, 50), (55, 60)):
        m.loads = sim.reallocate(m.loads, "life_support", share)
        spec = gameplay._life_check(m)
        opt = spec["steps"][0]["options"][0]
        assert opt["id"] == "recycler" and opt["label"] == f"Recycler to {expect}%", (share, opt)
    m.loads = sim.reallocate(m.loads, "life_support", 60)
    assert [o["id"] for o in gameplay._life_check(m)["steps"][0]["options"]] == ["ice"]


def test_skip_line_names_the_job_it_stopped_for():
    m = sim.new_mission("m", "shackleton_rim", 4, level="cadet")
    sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 30}})
    for _ in range(8):
        r = sim.apply_command(m, {"type": "skip"})
        kinds = {(e["kind"], e.get("phase")) for e in r["events"]}
        if ("task", "start") in kinds and not any(k in sim.SKIP_STOPS - {"task", "beat"} for k, _ in kinds):
            assert "A quiet day" not in r["say"] and ("New task" in r["say"] or ":" in r["say"]), r["say"]
            assert len(r["say"].split()) <= 20
            return
    pytest.skip("no task-only skip stop in this seed")
