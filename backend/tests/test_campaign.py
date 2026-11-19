"""[campaign] Missions 2+ (app/mission/campaign.py, docs/GAMEPLAY.md §16): each mission has its own site, goal and twist,
is winnable by a player who follows the Now card, and stays deterministic per (mission, site, seed, inputs)."""
import json

import pytest

from app.mission import campaign, gameplay, registry, sim

IDS = [m["id"] for m in campaign.MISSIONS]
LEVELS = ["cadet", "commander", "engineer"]


def follow_card(m, cap=500):
    """Do what the Now card offers; on a choice, the first option the card does not mark as risky (the long night's
    low heater duty says "pipes may freeze"); when it offers nothing, skip ahead. Fails on a ready step the sim refuses."""
    last, same = None, 0
    for _ in range(cap):
        if m.over:
            break
        t = gameplay.view(m)["task"]
        st = t and t["step"]
        if st and st["ready"] and st["kind"] != "wait":
            cmd = {"type": "task", "task": t["id"], "step": st["id"]}
            if st["kind"] == "choice":
                cmd["choice"] = next((o["id"] for o in st["options"] if not o.get("risky")), st["options"][0]["id"])
            r = sim.apply_command(m, cmd)
            if r.get("needs_confirm"):
                sim.apply_command(m, {"type": "confirm"})
            key = (t["id"], st["id"], m.t_h)
            same = same + 1 if key == last else 0
            last = key
            assert same < 3, f"stuck: {t['title']}: {st['label']} -> {r.get('say')}"
        else:
            sim.apply_command(m, {"type": "skip"})
    return m


def test_six_missions_in_order_each_with_its_own_site_goal_and_line():
    assert [m["n"] for m in campaign.MISSIONS] == list(range(1, len(campaign.MISSIONS) + 1))
    assert len(campaign.MISSIONS) >= 6
    later = campaign.MISSIONS[1:]
    assert len({m["site"] for m in later}) == len(later), "Missions 2+ each fly a different real site"
    assert all(m["site"] in {s["id"] for s in sim.sites()} for m in later)
    goals = [tuple(m["goals"]) for m in campaign.MISSIONS]
    assert len(set(goals)) == len(goals), "no two missions share their goals"
    firsts = [m["goals"][0] for m in later]
    assert len(set(firsts)) == len(firsts), "each mission's main goal is its own"
    for m in campaign.MISSIONS:
        assert all(g in campaign.GOALS for g in m["goals"])
        for k in ("title", "danger"):
            assert 1 <= len(m[k].split()) <= 8, m[k]
        if m["n"] > 1:
            assert len(m["line"].split()) <= 12, m["line"]   # docs/COPY.md: a supporting line
        assert len(m["say"].split()) <= 20, m["say"]         # spoken
        for g in m["goals"]:
            assert len(campaign.GOALS[g][0].split()) <= 8


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("mid", IDS[1:])
def test_each_mission_is_winnable_by_a_card_following_player(mid, level):
    both = 0
    seeds = (0, 1, 3, 7)
    for seed in seeds:
        m = follow_card(sim.new_mission("c", "shackleton_rim", seed, level=level, campaign=mid))
        assert m.outcome == "survived", f"{mid} {level} seed {seed}: {m.outcome} at {m.t_h} h"
        g = sim.objectives(m)["goals"]
        assert g[0]["met"], f"{mid} {level} seed {seed}: the mission's main goal missed: {g[0]}"
        both += all(x["met"] for x in g)
        assert len(m.gp["chapters"]) == len(gameplay.CHAPTERS), "every chapter card still comes"
    assert both * 2 >= len(seeds), f"{mid} {level}: both goals in only {both} of {len(seeds)} runs"


@pytest.mark.parametrize("mid", IDS[1:])
def test_a_player_who_ignores_the_twist_misses_the_goal(mid):
    """The goal is about the twist: skipping time and never doing the jobs misses it (or loses the crew)."""
    m = sim.new_mission("c", "shackleton_rim", 1, level="commander", campaign=mid)
    for _ in range(80):
        if m.over:
            break
        sim.apply_command(m, {"type": "skip"})
    g = sim.objectives(m)["goals"]
    assert not all(x["met"] for x in g), (mid, g, m.outcome)


def test_the_twists():
    # storm season: four real DONKI particle storms, two back-to-back pairs, the same at every level and seed
    a = sim.new_mission("c", "x", 3, level="cadet", campaign="storm_season")
    b = sim.new_mission("c", "x", 9, level="commander", campaign="storm_season")
    assert [s.event["id"] for s in a.storms] == [e for e, _ in campaign.STORM_SEASON] == [s.event["id"] for s in b.storms]
    assert all(s.event.get("sep") and s.event["date"].startswith("2024") for s in a.storms)
    assert a.site_id == "shackleton_floor"
    gaps = [b2.start_h - (b1.start_h + b1.dur_h) for b1, b2 in zip(a.storms, a.storms[1:])]
    assert gaps[0] >= sim.SHELTER_REST_H and gaps[2] >= sim.SHELTER_REST_H, "the crew gets its rest between the pair"
    # rover rescue: the rover starts stranded; the card's first job after power is the rescue; no ice run until then
    m = sim.new_mission("c", "x", 0, level="commander", campaign="rover_rescue")
    assert m.rover["task"] == "stranded" and not sim.crew_out(m)
    sim.apply_command(m, {"type": "allocate", "to": "shields", "amount": {"kind": "percent", "value": 30}, "from": None})
    assert gameplay.view(m)["task"]["title"] == "Rover rescue"
    r = sim.apply_command(m, {"type": "dispatch", "vehicle": "rover", "task": "collect_ice", "target": None})
    assert not r["ok"]
    if not sim.env_at(m, m.t_h)["lit"]:
        r = sim.apply_command(m, {"type": "dispatch", "vehicle": "rover", "task": "return", "target": None})
        assert not r["ok"] and "sunlight" in r["say"]
    # far-side relay: radio windows every 12 h even where Earth is below the ridge
    f = sim.new_mission("c", "x", 0, level="commander", campaign="far_relay")
    plain = sim.new_mission("c", "connecting_ridge", 0, level="commander")
    up = sum(sim.sky_table(sim.sky_key(f))[1]); base = sum(sim.sky_table(sim.sky_key(plain))[1])
    assert up > base + 40 and sim.sky_key(f) == "connecting_ridge|relay"
    # power budget: no backup generator; Mission 1 at the same site keeps it
    p = sim.new_mission("c", "x", 0, level="commander", campaign="power_budget")
    assert p.backup_gen == 0 and sim.new_mission("c", "shackleton_rim", 0).backup_gen == sim.BACKUP_GEN
    # the long night: Malapert starts dark, with the tanks full
    n = sim.new_mission("c", "x", 0, level="commander", campaign="long_night")
    assert n.site_id == "malapert_massif" and not sim.env_at(n, 0)["lit"] and n.life == 100


def test_mission_one_is_the_classic():
    a, b = sim.new_mission("c", "malapert_massif", 4), sim.new_mission("c", "malapert_massif", 4, campaign="first_light")
    assert a.campaign == b.campaign == "first_light" and a.site_id == "malapert_massif"
    assert [s.event["id"] for s in a.storms] == [s.event["id"] for s in b.storms]
    o = sim.objectives(a)
    assert [g["id"] for g in o["goals"]] == ["science", "ice"] and o["science"]["goal"] == sim.SCIENCE_GOAL


@pytest.mark.parametrize("mid", IDS)
def test_deterministic_per_mission_seed_and_inputs(mid):
    runs = []
    for _ in range(2):
        m = follow_card(sim.new_mission("c", "shackleton_rim", 5, level="commander", campaign=mid), cap=60)
        runs.append(json.dumps({k: v for k, v in sim.to_state(m).items() if k not in ("id",)}, sort_keys=True, default=str))
    assert runs[0] == runs[1]


def test_autosave_and_restart_shift_keep_the_campaign_mission(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSION_SAVE_DIR", str(tmp_path))
    m = registry.create("shackleton_rim", 2, level="commander", campaign="far_relay")
    for _ in range(6):
        registry.skip(m.id)
    saved = registry.saved()
    assert saved["campaign"] == "far_relay" and saved["mission_n"] == 5 and saved["site"] == "connecting_ridge"
    n = registry.resume()
    assert n.campaign == "far_relay" and n.comm == "relay" and n.t_h == m.t_h
    assert sim.to_state(n)["progress"]["goals"] == sim.to_state(m)["progress"]["goals"]
    out = registry.restart_shift(m.id)
    assert registry.get(m.id).campaign == "far_relay" and out["state"]["campaign"]["n"] == 5


def test_api_lists_the_campaign_and_starts_a_mission():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    ms = c.get("/api/mission/campaign").json()["missions"]
    assert [m["n"] for m in ms] == list(range(1, len(campaign.MISSIONS) + 1)) and ms[1]["goals"]
    st = c.post("/api/mission/start", json={"site": "shackleton_rim", "seed": 1, "level": "cadet",
                                            "campaign": "long_night"}).json()
    assert st["site"]["id"] == "malapert_massif" and st["campaign"]["title"] == "The long night"
    assert [g["id"] for g in st["progress"]["goals"]] == ["warm", "life"]
    assert c.post("/api/mission/start", json={"site": "shackleton_rim", "campaign": "nope"}).status_code == 404


def test_debrief_names_the_missed_goal():
    m = sim.new_mission("c", "x", 1, level="commander", campaign="rover_rescue")
    for _ in range(80):
        if m.over:
            break
        sim.apply_command(m, {"type": "skip"})
    d = sim.debrief(m)
    assert d["campaign"]["n"] == 4
    if m.outcome == "survived":
        assert "missed" in d["why"].lower() and d["try"] == campaign.TRY["rescue"]
