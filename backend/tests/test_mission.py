"""Mission Trainer: sim determinism, costs, win/lose paths, and every API endpoint."""
import copy

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.mission import registry, sim

SITE = "connecting_ridge"


def run(m, policy=None):
    while not m.over:
        if policy:
            policy(m)
        sim.advance(m, 1)
    return m


def snapshot(m):
    return (m.t_h, round(m.power, 6), round(m.life, 6), round(m.dose, 6), round(m.science, 6), m.outcome)


def test_data_files_present_and_sourced():
    assert len(sim.sites()) >= 4
    for s in sim.sites():
        assert s["sources"] and all(src["url"].startswith("https://") for src in s["sources"])
        e = sim.ephemeris(s["id"])
        assert len(e["sun_elev_deg"]) == len(e["earth_elev_deg"]) == 241
    cat = sim.storms_catalog()
    assert 8 <= len(cat["events"]) <= 15
    for ev in cat["events"]:
        assert ev["severity"] in (1, 2, 3) and ev["dose_multiplier"] > 1 and ev["link"].startswith("https://")


@pytest.mark.parametrize("seed", [0, 7, 1234])
def test_deterministic_per_seed(seed):
    a = run(sim.new_mission("a", SITE, seed))
    b = run(sim.new_mission("b", SITE, seed))
    assert snapshot(a) == snapshot(b)
    assert [(s.start_h, s.event["id"]) for s in a.storms] == [(s.start_h, s.event["id"]) for s in b.storms]
    assert [e["text"] for e in a.events] == [e["text"] for e in b.events]


def test_different_seeds_differ():
    plans = {tuple((s.start_h, s.event["id"]) for s in sim.new_mission("x", SITE, k).storms) for k in range(10)}
    assert len(plans) > 1


def _future(m, shifts=8):
    f = copy.deepcopy(m)
    sim.advance(f, shifts)
    return {"power": f.power, "life": f.life, "dose": f.dose, "science": f.science}


ACTION_COMMANDS = [
    {"type": "allocate", "to": "shields", "amount": {"kind": "delta", "value": 20}},
    {"type": "allocate", "to": "science", "amount": {"kind": "percent", "value": 40}},
    {"type": "allocate", "to": "greenhouse", "amount": {"kind": "little", "value": 5}},
    {"type": "allocate", "to": "life_support", "amount": {"kind": "half"}},
    {"type": "dispatch", "vehicle": "rover", "task": "collect_ice", "target": None},
    {"type": "dispatch", "vehicle": "rover", "task": "explore", "target": None},
    {"type": "dispatch", "vehicle": "rover", "task": "repair_array", "target": None},
    {"type": "shelter", "on": True},
    {"type": "call_houston", "text": "How is space weather?"},
]


@pytest.mark.parametrize("cmd", ACTION_COMMANDS, ids=lambda c: c["type"] + ":" + str(c.get("to") or c.get("task") or ""))
def test_every_command_costs_something(cmd):
    """No free choices: every action changes at least two resources' futures (power, life, dose, science)."""
    # A site whose Earth rises before an idle crew runs out of power: on the real LOLA skyline the ridge sees Earth only
    # from hour 208 (docs/SITE_NAVIGATOR.md), de Gerlache from hour 138.
    base = sim.new_mission("c", "de_gerlache_rim", 3)
    # Move to a time when Earth is up so call_houston is possible.
    while not sim.env_at(base, base.t_h)["earth_visible"] and not base.over:
        sim.advance(base, 1)
    assert not base.over
    ref = _future(base)
    m = copy.deepcopy(base)
    res = sim.apply_command(m, cmd)
    if res.get("needs_confirm"):
        res = sim.apply_command(m, {"type": "confirm"})
    assert res["ok"], res
    fut = _future(m)
    changed = [k for k in ref if abs(ref[k] - fut[k]) > 1e-6]
    assert len(changed) >= 2, (cmd, changed, ref, fut)


def test_allocation_amounts_keep_total_100():
    m = sim.new_mission("a", SITE, 1)
    for amt in ({"kind": "percent", "value": 35}, {"kind": "delta", "value": -10}, {"kind": "little", "value": -5},
                {"kind": "half"}, {"kind": "none"}):
        r = sim.apply_command(m, {"type": "allocate", "to": "science", "amount": amt})
        if r.get("needs_confirm"):
            sim.apply_command(m, {"type": "confirm"})
        assert sum(m.loads.values()) == 100 and all(v >= 0 for v in m.loads.values())
    before = dict(m.loads)
    sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "delta", "value": 10}, "from": "comms"})
    assert m.loads["shields"] - before["shields"] == before["comms"] - m.loads["comms"]


def test_destructive_needs_confirm_and_cancel():
    m = sim.new_mission("a", SITE, 1)
    loads = dict(m.loads)
    r = sim.apply_command(m, {"type": "allocate", "to": "science", "amount": {"kind": "all"}})
    assert r["needs_confirm"] and r["readback"]
    assert m.loads == loads
    sim.apply_command(m, {"type": "cancel"})
    assert m.loads == loads and m.pending is None
    r = sim.apply_command(m, {"type": "allocate", "to": "heaters", "amount": {"kind": "none"}})
    assert r["needs_confirm"]
    sim.apply_command(m, {"type": "confirm"})
    assert m.loads["heaters"] == 0


def test_lose_path_life_support():
    m = sim.new_mission("l", SITE, 2)
    sim.apply_command(m, {"type": "allocate", "to": "science", "amount": {"kind": "all"}})
    sim.apply_command(m, {"type": "confirm"})
    run(m)
    assert m.outcome == "life_support_out"
    d = sim.debrief(m)
    assert d["outcome"] == "life_support_out" and d["why"] and d["grade"] in "ABCDF"


def test_lose_path_dose_when_storm_and_no_shields():
    lost = []
    for seed in range(20):
        m = sim.new_mission("d", "de_gerlache_rim", seed)
        sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "none"}})
        run(m)
        lost.append(m.outcome)
    assert "dose_limit" in lost


def careful(m):
    """Shelter for storms; night mode (not the shelter) for the dark, with the spare power on the recycler."""
    env = sim.env_at(m, m.t_h)
    storm_soon = any(st.start_h - 6 <= m.t_h < st.start_h + st.dur_h for st in m.storms if st.event.get("sep"))
    if storm_soon and not m.shelter and not m.rover["busy"]:
        sim.apply_command(m, {"type": "shelter", "on": True})
    elif not storm_soon and m.shelter:
        sim.apply_command(m, {"type": "shelter", "on": False})
    # a cabled site (the floor) has nights too: its rim arrays go dark on the real LOLA skyline (env "lit")
    dark = not env["lit"] if sim.site(m.site_id).get("power_from") else env["sun_frac"] < 0.5
    if dark != m.power_save:
        sim.apply_command(m, {"type": "power_save", "on": dark})
        if dark:
            sim.apply_command(m, {"type": "allocate", "to": "life_support", "amount": {"kind": "percent", "value": 45}})
    if not m.shelter and not m.rover["busy"] and not storm_soon:
        if m.array_eff < 1:
            sim.apply_command(m, {"type": "dispatch", "vehicle": "rover", "task": "repair_array"})
        elif m.life < 60:
            sim.apply_command(m, {"type": "dispatch", "vehicle": "rover", "task": "collect_ice"})


@pytest.mark.parametrize("site", [s["id"] for s in sim.sites()])
def test_win_path_every_site(site):
    m = run(sim.new_mission("w", site, 5), careful)
    assert m.outcome == "survived", (site, m.lose_reason, m.power, m.life, m.dose)
    d = sim.debrief(m)
    assert d["outcome"] == "survived" and d["score"] > 0
    assert len(d["timeline"]) == 40 and {"t_h", "power", "life_support", "dose_msv", "events"} <= d["timeline"][0].keys()
    assert d["lessons"] and all(l["source"]["url"].startswith("https://") for l in d["lessons"])
    assert any("real" in l["text"].lower() or "On 20" in l["text"] for l in d["lessons"])
    assert len(d["data_used"]) >= 5


def test_houston_blocked_when_earth_down():
    m = sim.new_mission("h", "shackleton_rim", 1)  # Earth is below the horizon early in the April 2026 window
    assert not sim.env_at(m, 0)["earth_visible"]
    r = sim.apply_command(m, {"type": "call_houston", "text": "hi"})
    assert not r["ok"] and "Houston can't hear us" in r["say"]


def test_telemetry_interpolates():
    m = sim.new_mission("t", SITE, 1)
    f0, f3 = sim.telemetry(m, 0), sim.telemetry(m, 3.5)
    assert f0["mission_time_h"] == 0 and f3["mission_time_h"] == 3.5
    assert f3["t"] == "telemetry" and f3["comm"] in ("open", "closed")
    assert m.t_h == 0  # the preview never mutates the mission


def test_registry_shape_for_director():
    m = registry.create(SITE, 9)
    out = registry.apply(m.id, {"type": "query", "what": "power"})
    assert set(out) == {"state", "result"} and {"ok", "needs_confirm", "say", "readback", "events"} <= out["result"].keys()
    assert registry.get(m.id).state()["id"] == m.id
    assert m.apply({"type": "rule", "text": "always keep shields on"})["result"]["ok"]


# ------------------------------------------------------------------ API

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_api_endpoints(client):
    sites = client.get("/api/mission/sites").json()["sites"]
    assert {"id", "name", "lat", "lon", "sunlight_pct", "ice", "earth_visible_pct", "notes", "sources"} <= sites[0].keys()
    assert client.post("/api/mission/start", json={"site": "nope"}).status_code == 404
    st = client.post("/api/mission/start", json={"site": SITE, "seed": 4}).json()
    mid = st["id"]
    assert st["resources"]["dose_limit_msv"] == 50 and sum(st["loads"].values()) == 100
    assert {"sun_elev_deg", "earth_elev_deg", "storm", "comm_delay_s", "next_comm_window_h"} <= st["env"].keys()
    assert client.get(f"/api/mission/{mid}").json()["id"] == mid
    assert client.get("/api/mission/m-nope").status_code == 404
    r = client.post(f"/api/mission/{mid}/command",
                    json={"command": {"type": "allocate", "to": "shields", "amount": {"kind": "delta", "value": 10}}}).json()
    assert r["result"]["ok"] and r["state"]["loads"]["shields"] == 30
    r = client.post(f"/api/mission/{mid}/command", json={"command": {"type": "end_shift"}}).json()
    assert r["state"]["mission_time_h"] == 6
    r = client.post(f"/api/mission/{mid}/advance", json={"shifts": 3}).json()
    assert r["state"]["mission_time_h"] == 24 and isinstance(r["events"], list) and r["say"]
    d = client.get(f"/api/mission/{mid}/debrief").json()
    assert {"score", "grade", "timeline", "lessons", "data_used", "outcome", "why"} <= d.keys()
    with client.websocket_connect(f"/ws/mission/{mid}") as ws:
        f = ws.receive_json()
        assert f["t"] == "telemetry" and {"power", "life_support", "dose_msv", "sun_elev_deg", "earth_elev_deg", "comm",
                                          "loads", "alerts"} <= f.keys()


def test_storm_state_fields(client):
    for seed in range(10):
        m = registry.create(SITE, seed)
        st = m.storms[0]
        sim.advance(m, (st.start_h + 1 + 5) // 6)
        if sim.env_at(m, m.t_h)["storm"]:
            s = client.get(f"/api/mission/{m.id}").json()["env"]["storm"]
            assert s["active"] and s["url"].startswith("https://") and len(s["real_date"]) == 10
            assert {"name", "source", "severity"} <= s.keys()
            return
    pytest.fail("no storm active in 10 seeds")
