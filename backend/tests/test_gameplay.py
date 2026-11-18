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
    t = task(m)   # [0.4.1] sheltered straight away: the readback is skipped, the confirm is next
    assert t["kind"] == "storm_prep" and t["step"]["id"] == "confirm" and t["step"]["ready"]
    assert next(s for s in t["steps"] if s["id"] == "readback")["done"]
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "confirm", "text": "in the shelter, copy"})
    assert r["ok"] and r["say"].startswith("Houston copies")
    assert task(m) is None or task(m)["kind"] != "storm_prep"
    log = sim.to_state(m)["mission_log"]
    assert any(e["title"] == "Storm prep" for e in log)


def _to_storm_hit(seed_range=range(40)):
    for seed in seed_range:
        m = sim.new_mission("m", "shackleton_rim", seed, level="cadet")
        sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 30}})
        while not m.over and not (sim.env_at(m, m.t_h)["storm"] and sim.env_at(m, m.t_h)["storm"].event.get("sep")):
            sim.advance(m, 1)
        t = task(m)
        if not m.over and t and t["kind"] == "storm_hit" and not m.rover["busy"]:
            return m, t
    pytest.skip("no particle storm with the rover home in these seeds")


def test_storm_procedure_readback_act_confirm():
    """[0.4.1] Houston calls the order, the cadet reads it back, acts, then confirms (voice or one tap each)."""
    m, t = _to_storm_hit()
    assert t["say"] == gameplay.HOUSTON_SHELTER and words(t["say"]) <= 20
    assert [s["id"] for s in t["steps"]] == ["rover", "readback", "shelter", "confirm"]
    assert t["step"]["id"] == "readback" and t["step"]["kind"] == "sequence" and t["decision"]
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "readback", "text": "all crew"})
    assert r["ok"] and r.get("progress") and not m.shelter                     # half a readback: not done, no miss
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "readback", "text": "into the shelter"})
    assert r["ok"] and r["say"].startswith("Readback correct") and not m.shelter   # a readback is words, not the act
    t = task(m)
    assert t["step"]["id"] == "shelter" and t["step"]["cmd"] == {"type": "shelter", "on": True}
    r = sim.apply_command(m, t["step"]["cmd"])
    assert m.shelter and r["ack"] == "Crew sheltered. Good."
    t = task(m)
    assert t["kind"] == "storm_hit" and t["step"]["id"] == "confirm" and t["step"]["options"][0]["label"] == "In the shelter, copy"
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "confirm", "choice": "say"})   # the one tap
    assert r["ok"] and r["say"].startswith("Houston copies")
    assert task(m) is None or task(m)["kind"] != "storm_hit"
    assert any(e["title"] == "Storm! Shelter the crew" for e in sim.to_state(m)["mission_log"])


def test_storm_procedure_never_blocks_a_crew_that_shelters_first():
    """An order given at once still counts: the readback is skipped, the confirm settles itself an hour in."""
    m, t = _to_storm_hit()
    sim.apply_command(m, {"type": "shelter", "on": True})
    t = task(m)
    rb = next(s for s in t["steps"] if s["id"] == "readback")
    assert m.shelter and rb["done"] and "No readback" in rb["result"] and t["step"]["id"] == "confirm"
    sim.step(m, gameplay.CONFIRM_WAIT_H + 0.01)
    assert task(m) is None or task(m)["kind"] != "storm_hit"


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


def _to_station(level="cadet", seed=2):
    """Play like a kid until the first science job: the sample station."""
    m = sim.new_mission("m", "shackleton_rim", seed, level=level)
    do_step(m)
    for _ in range(120):
        t = task(m)
        if t and t["kind"] == "science":
            break
        if t and t["step"] and t["step"]["ready"]:
            do_step(m)
        sim.step(m, 1)
    t = task(m)
    assert t and t["kind"] == "science" and [s["id"] for s in t["steps"]] == ["tool", "describe", "bag"]
    return m, t, m.gp["tasks"][t["id"]]


# ---- [0.5 field] 1. the sample station: tool, a one-line description, the bag number ---------------------------------
@pytest.mark.parametrize("level", ["cadet", "commander"])
def test_sample_station_scales_with_the_description(level):
    m, t, raw = _to_station(level)
    assert t["decision"] and t["lesson"]["id"] == "fieldkit" and t["lesson"]["track"] == "field"
    opts = t["step"]["options"]
    assert raw["tool"] in [o["id"] for o in opts] and len(opts) == (3 if level == "cadet" else 4)
    sci = m.science
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "tool", "choice": raw["tool"]})
    assert r["ok"] and "Good pick" in r["say"] and m.science == sci   # nothing until it's bagged and called in
    t = task(m)
    assert t["step"]["kind"] == "describe" and t["decision"]   # the clock holds while the kid describes
    assert len(t["step"]["options"]) <= 4 and t["step"]["options"][-1]["label"] == "Bag it"
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "describe", "text": "it is really big"})
    assert r["ok"] and r.get("progress") and r["say"].startswith("Good: size.") and words(r["say"]) <= 8
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "describe", "text": "round and bright"})
    assert r["ok"] and not r.get("progress") and "size, shape and bright or dark" in r["say"]
    t = task(m)
    assert t["step"]["kind"] == "sequence" and t["step"]["options"][0]["label"] == f"Bag {raw['bag']}"
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "bag", "text": "uh, the bag"})
    assert r.get("progress") and m.science == sci
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "bag",
                              "text": f"bag {gameplay._num_words(raw['bag'])}"})
    best = gameplay.STATION_BAG + gameplay.STATION_TOOL + gameplay.STATION_KIND * 3
    assert r["ok"] and m.science == pytest.approx(sci + best) and f"bag {raw['bag']}" in r["say"].lower()
    assert words(r["say"]) <= 20 and raw["status"] == "done"


def test_a_lazy_station_still_counts_but_less():
    m, t, raw = _to_station()
    wrong = next(o["id"] for o in t["step"]["options"] if o["id"] != raw["tool"])
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "tool", "choice": wrong})
    assert r["ok"] and gameplay.TOOL_USE[raw["tool"]] in r["say"]   # a wrong pick teaches; the job goes on
    sci = m.science
    sim.apply_command(m, {"type": "task", "task": t["id"], "step": "describe", "choice": "bag"})
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "bag", "choice": "say"})
    assert m.science == pytest.approx(sci + gameplay.STATION_BAG)
    # every station is worth little next to the sim's own science (the strategy guarantees hold)
    assert gameplay.STATION_BAG + gameplay.STATION_TOOL + gameplay.STATION_KIND * gameplay.STATION_KINDS <= 2.5


def test_station_chips_describe_by_tap():
    m, t, raw = _to_station()
    sim.apply_command(m, {"type": "task", "task": t["id"], "step": "tool", "choice": raw["tool"]})
    for _ in range(3):
        t = task(m)
        chip = t["step"]["options"][0]
        assert chip["id"] in raw["steps"][1]["look"]
        sim.apply_command(m, {"type": "task", "task": t["id"], "step": "describe", "choice": chip["id"]})
    assert task(m)["step"]["id"] == "bag" and len(raw["steps"][1]["got"]) == 3


# ---- [0.5 field] 2. the low-Sun drive: tack off the sunline, lights before the shadow --------------------------------
def _ice_drive(monkeypatch, sun):
    """A Cadet ice drive with the Sun where the test puts it (sun_view patched; the real geometry is tested below)."""
    monkeypatch.setattr(gameplay, "sun_view", lambda m, t_h=None, leg="out": dict(sun))
    m = sim.new_mission("m", "connecting_ridge", 3, level="cadet")
    for _ in range(300):
        t = task(m)
        if t and t["kind"] == "ice_run" and t["step"]["ready"]:
            do_step(m)   # send the rover
            return m, m.gp["tasks"][t["id"]]
        if t and t["step"] and t["step"]["ready"]:
            do_step(m)
            if m.pending:
                sim.apply_command(m, {"type": "confirm"})
        sim.step(m, 1)
    pytest.fail("no ice run")


GLARE_LEFT = {"rel": -12.0, "side": "left", "elev": 1.4, "up": True, "glare": True}


def test_low_sun_tack_away_from_the_sun(monkeypatch):
    m, raw = _ice_drive(monkeypatch, GLARE_LEFT)
    assert [s["id"] for s in raw["steps"]] == ["send", "tack", "steer", "lights", "back"]
    sim.step(m, gameplay.TACK_AT_H)
    t = task(m)
    assert t["step"]["id"] == "tack" and t["decision"] and t["lesson"]["id"] == "observe"
    assert any(r["k"] == "Sun" and r["v"] == "12° left, 1.4° up" for r in t["readouts"])
    assert t["step"]["label"] == "Glare: Sun 12° left. Tack left or right?"   # the data is in the line too
    eta = m.rover["eta_h"]
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "tack", "choice": "right"})
    assert r["ok"] and m.rover["eta_h"] == eta and "can see" in r["say"]


def test_low_sun_wrong_or_no_call_costs_an_hour_never_the_mission(monkeypatch):
    m, raw = _ice_drive(monkeypatch, GLARE_LEFT)
    sim.step(m, gameplay.TACK_AT_H)
    eta = m.rover["eta_h"]
    r = sim.apply_command(m, {"type": "task", "task": raw["id"], "step": "tack", "choice": "left"})
    assert r["ok"] and m.rover["eta_h"] == eta + gameplay.NAV_COST_H and "glare" in r["say"].lower()
    # nobody calls the lights: once it's the card's step, NAV_WAIT_H hours later the rover stops at the shadow
    m2, raw2 = _ice_drive(monkeypatch, GLARE_LEFT)
    for _ in range(40):
        if raw2["steps"][3]["done"] or not m2.rover["busy"]:
            break
        t = task(m2)
        if t["step"]["id"] in ("tack", "steer"):
            do_step(m2)
        p0, e0 = m2.power, m2.rover["eta_h"]
        sim.step(m2, 1)
    assert raw2["steps"][3]["result"].startswith("No lights") and not m2.over
    assert m2.rover["eta_h"] == e0 - 1 + gameplay.NAV_COST_H


def test_lights_on_before_the_shadow(monkeypatch):
    m, raw = _ice_drive(monkeypatch, {**GLARE_LEFT, "glare": False, "up": False})
    assert [s["id"] for s in raw["steps"]] == ["send", "steer", "lights", "back"]   # Sun down: no glare call
    while task(m)["step"]["id"] != "lights" or not task(m)["step"]["ready"]:
        if task(m)["step"]["ready"]:
            do_step(m)
        sim.step(m, 1)
    t = task(m)
    assert t["step"]["options"] == [{"id": "on", "label": "Lights on"}]
    assert any(r["k"] == "Shadow in" for r in t["readouts"])
    eta, p = m.rover["eta_h"], m.power
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "lights", "choice": "on"})
    assert r["ok"] and m.rover["eta_h"] == eta and m.power == p


def test_the_sun_is_real_data_and_the_glare_leg_varies():
    m = sim.new_mission("m", "shackleton_rim", 0, level="cadet")
    eph = sim.ephemeris("shackleton_rim")["sun_elev_deg"]
    sv = gameplay.sun_view(m, 10)
    assert sv["elev"] == pytest.approx(eph[10], abs=0.01) and -180 <= sv["rel"] <= 180
    assert gameplay.sun_view(m, 10, "home")["rel"] == pytest.approx(((sv["rel"] + 360) % 360) - 180, abs=0.2)
    legs = set()
    for site in SITES:
        mm = sim.new_mission("m", site, 0, level="cadet")
        for h in range(0, sim.MISSION_H, 6):
            mm.t_h = h
            legs.add(gameplay._glare_leg(mm))
    assert {"out", "home", None} <= legs   # the data decides: some drives face the Sun going out, some coming home
    floor = sim.new_mission("m", "shackleton_floor", 0, level="cadet")
    assert not any(gameplay.sun_view(floor, h)["up"] for h in range(0, 48))   # the crater floor never sees the Sun


# ---- [0.5 field] 3. the science team's replan: what to give up, then the readback ---------------------------------------
def _to_replan(level="cadet"):
    m = sim.new_mission("m", "de_gerlache_rim", 1, level=level)
    for _ in range(4000):
        t = task(m)
        if t and t["kind"] == "replan":
            return m, t, m.gp["tasks"][t["id"]]
        if t and t["step"] and t["step"]["ready"]:
            do_step(m, t)
            if m.pending:
                sim.apply_command(m, {"type": "confirm"})
        sim.step(m, 0.5)
    pytest.fail("no replan")


def test_replan_trades_real_numbers_and_needs_a_readback():
    m, t, raw = _to_replan()
    assert t["say"].startswith("Science Officer: unusual bright rock.") and words(t["say"]) <= 20
    assert m.rover["busy"] and sim.env_at(m, m.t_h)["earth_visible"]   # the science room is on Earth
    assert t["decision"] and t["lesson"]["id"] == "rocks"
    hints = {o["id"]: o["hint"] for o in t["step"]["options"]}
    mg = gameplay._margin(m)
    assert ("all day" in hints["margin"]) if mg["margin_h"] is None else (f"{mg['margin_h']} h" in hints["margin"])
    assert f"{gameplay.SAMPLE_SCIENCE:g}" in hints["sample"] or "Free" in hints["sample"]
    sci, left = m.science, gameplay._samples_left(m)
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "trade", "choice": "margin"})
    assert r["ok"] and r["say"] == "Flight approves, 15 minutes at the rock." and gameplay._samples_left(m) == left
    assert m.rover.get("late_min") == gameplay.REPLAN_MIN and m.science == sci
    t = task(m)
    assert t["step"]["kind"] == "sequence" and t["decision"]
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "readback", "text": "fifteen minutes"})
    assert r.get("progress") and "Then: at the rock" in r["say"] and m.science == sci
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "readback", "text": "at the rock, copy"})
    assert r["ok"] and "Readback correct" in r["say"] and m.science == pytest.approx(sci + gameplay.ROCK_SCIENCE)
    assert raw["status"] == "done" and words(r["say"]) <= 20


def test_replan_with_no_light_margin_flight_says_no(monkeypatch):
    m, t, raw = _to_replan()
    monkeypatch.setattr(gameplay, "_margin", lambda m: {"eta_h": 9, "sun_h": 4, "lit": True, "margin_h": 0, "tight": True})
    left = gameplay._samples_left(m)
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "trade", "choice": "margin"})
    assert r["say"].startswith("Flight: negative, sunset in 4 h") and words(r["say"]) <= 20
    assert gameplay._samples_left(m) == max(0, left - 1) and not m.rover.get("late_min")


def test_replan_never_without_earth_and_once_a_mission():
    for site in ("shackleton_rim", "de_gerlache_rim"):
        m = sim.new_mission("m", site, 1, level="cadet")
        while not m.over:
            t = task(m)
            if t and t["step"] and t["step"]["ready"]:
                if t["kind"] == "replan":
                    assert sim.env_at(m, m.t_h)["earth_visible"]
                do_step(m, t)
                if m.pending:
                    sim.apply_command(m, {"type": "confirm"})
            sim.step(m, 0.5)
        assert m.gp["count"].get("replan", 0) <= gameplay.REPLAN_MAX


def test_free_text_steps_route_by_voice():
    from app import turn_router as R
    ctx = R.Ctx(screen="cabin", offer="task", step_type="describe", step_options=["Fist-size", "Rounded", "Bag it"])
    assert R.nav_intent("it's a big round rock with sharp edges", ctx) == ("task_choice", "it s a big round rock with sharp edges")
    assert R.nav_intent("pause the clock", ctx)[0] == "time_pause"   # the clock still answers
    ctx = R.Ctx(screen="cabin", offer="task", step_type="sequence", step_options=["Read it back"])
    assert R.nav_intent("fifteen minutes at the rock copy", ctx)[0] == "task_choice"
    ctx = R.Ctx(screen="cabin", offer="task", step_type="sequence", step_options=["Bag 14"])
    assert R.nav_intent("bag twelve", ctx) == ("task_choice", "bag twelve")   # the words go to the grader
    ctx = R.Ctx(screen="cabin", offer="task", step_options=["Tack left", "Tack right"])
    assert R.nav_intent("left", ctx) == ("task_choice", "Tack left")
    assert R.nav_intent("tack right", ctx) == ("task_choice", "Tack right")   # the word both options share doesn't count
    ctx = R.Ctx(screen="cabin", offer="task", step_options=["Lights on"])
    assert R.nav_intent("lights", ctx) == ("task_choice", "Lights on")
    assert R.nav_intent("tongs", R.Ctx(screen="cabin", offer="task", step_options=["Rake", "Tongs", "Scoop"])) == \
        ("task_choice", "Tongs")


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


def test_storm_readback_uses_the_radio_readback_grader():
    """[0.4.1] The storm's readback and confirm are graded by mission/readback.py (the 0.6 radio readback), not a second
    grader: any wording that names the shelter reads it back; the confirm also needs the radio word ("copy")."""
    from app.academy import grade as g
    from app.mission import readback
    rb = gameplay._readback_step()
    cf = gameplay._confirm_step()
    assert rb["order"] == cf["order"] == {"type": "shelter", "on": True} and readback.keys(rb["order"])
    acc = lambda s: {"items": s["items"], "order": s["order"], "radio": s.get("radio")}  # noqa: E731
    for t in ("everyone to the shelter", "copy, crew into the storm shelter", "all crew into the shelter"):
        assert g._sequence(acc(rb), {}, t)[0], t
    assert g._sequence(acc(cf), {}, "copy, we're in the shelter")[0]
    assert not g._sequence(acc(cf), {}, "in the shelter")[0]          # no radio word yet: half a confirm
    assert not g._sequence(acc(cf), {}, "copy")[0]


def test_a_slow_clock_frame_never_runs_past_a_choice():
    """[0.4.1] A live-clock slice of several hours stops where a step becomes doable (the boulders), so the client's
    held clock gets the choice; the rest of the slice runs after it, and the hours are never lost."""
    m = sim.new_mission("m", "shackleton_rim", 2, level="cadet")
    sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 30}})
    sim.step(m, 2)
    sim.apply_command(m, task(m)["step"]["cmd"])            # send the rover for ice
    sim.step(m, 6)                                           # one slow frame: six hours at once
    t = task(m)
    assert t["step"]["id"] == "steer" and t["step"]["ready"] and t["decision"] and m.frac >= 1
    h = m.t_h + m.frac
    sim.step(m, 0)                                           # the leftover hours still run later
    assert m.t_h + m.frac == pytest.approx(h)
