"""The physics behind the gauges (docs/PHYSICS.md): the NASA tables, the "Why?" cards, Engineer mode, the debrief's
numbers, and the router's `why` intent. None of it may change the game."""
import json
import re
from pathlib import Path

import pytest

from app import turn_router as R
from app.mission import gameplay, physics, sim

DATA = Path(__file__).resolve().parents[1] / "data" / "physics"
SITES = [s["id"] for s in sim.sites()]


def _sources_used(node, out):
    if isinstance(node, dict):
        if "source" in node and isinstance(node["source"], str):
            out.add(node["source"])
        for v in node.values():
            _sources_used(v, out)
    elif isinstance(node, list):
        for v in node:
            _sources_used(v, out)
    return out


def test_every_number_cites_a_listed_source():
    t = physics.table()
    used = _sources_used({k: v for k, v in t.items() if k != "sources"}, set())
    assert used and used <= set(t["sources"]), used - set(t["sources"])
    md = (DATA / "SOURCES.md").read_text()
    for sid, s in t["sources"].items():
        assert s["url"].startswith("http") and s["use"], sid
        assert f"`{sid}`" in md, f"SOURCES.md does not list {sid}"
    code = (Path(physics.__file__)).read_text()
    for sid in set(re.findall(r'"([a-z0-9_]+)"', code)) & {"horizons", "sunfact", "vsat", "crater", "change4", "lcross"}:
        assert sid in t["sources"], sid


def test_site_tables_are_physical_and_shared_with_the_navigator():
    """One table per quantity: the navigator's sites_physics.json for sunlight, slopes and the Diviner yearly
    average / maximum; physics.json only adds the Diviner night minimum, sampled at the navigator's own spot."""
    t = physics.table()
    assert set(t["sites"]) == set(SITES)
    for sid in SITES:
        assert set(t["sites"][sid]) == {"diviner"} and set(t["sites"][sid]["diviner"]) == {"min_k"}, sid
        nav = physics.nav_place(sid)
        assert tuple(t["sampled"]["coords"][sid]) == (nav["spot"]["lat"], nav["spot"]["lon"]), sid
        d = physics.site_phys(sid)["diviner"]
        assert 20 < d["min_k"]["value"] < d["avg_k"]["value"] < d["max_k"]["value"] < 400, sid
        assert d["max_k"]["value"] == pytest.approx(nav["temp_c"]["range"][1] + 273.15)
        sl = physics.site_phys(sid)["slope"]
        assert (sl["median_deg"]["value"], sl["p90_deg"]["value"]) == (nav["drive_to_ice"]["mean_slope_deg"],
                                                                       nav["drive_to_ice"]["steep_slope_deg"])
    floor = physics.site_phys("shackleton_floor")["diviner"]
    assert floor.get("psr") and floor["avg_k"]["value"] < physics.val("ice.ice_cold_trap_k.value")
    # CRaTER, converted with Chang'e 4's quality factor, agrees with the baseline the sim uses
    base = sim.radiation()["baseline"]["dose_rate_msv_per_h"]
    assert abs(physics.val("radiation.crater_quiet_gcr.msv_per_h.value") - base) < 0.01


def test_heaters_card_and_navigator_quote_the_same_temperature():
    m = sim.new_mission("h", "shackleton_floor", 1, level="commander")
    t = physics.nav_place("shackleton_floor")["temp_c"]["value"]
    assert f"{t}" in sim.to_state(m)["why"]["heaters"]["text"].replace("−", "-")


def _missions():
    for sid in SITES:
        for level in ("cadet", "commander", "engineer"):
            m = sim.new_mission("t", sid, 3, level=level)
            for h in (0, 30, 70, 130, 200):
                while m.t_h < h and not m.over:
                    sim.step(m, 1)
                yield sid, level, m


def test_why_cards_follow_the_copy_rules():
    seen = set()
    for sid, level, m in _missions():
        w = sim.to_state(m)["why"]
        assert set(w) == set(physics.GAUGES)
        for g, c in w.items():
            seen.add((g, c["text"][:12]))
            assert physics.words(c["say"]) <= 20, (sid, g, c["say"])
            assert len(c["text"]) <= 110, (sid, g, c["text"])        # two lines on the card
            assert not re.search(r"[%°]|mSv/h|kWh|\bkW\b", c["say"]), (g, c["say"])   # spoken: units in words
            assert "(" not in c["say"]                               # sources stay on screen
            assert c["source"]["url"].startswith("http") and c["formula"] and c["eng"]
            assert len(re.findall(r"\d+(?:\.\d+)?", c["say"])) <= 2, c["say"]   # one number (a range or a pair at most)
    assert len(seen) > len(physics.GAUGES)                          # the cards follow the state, not one fixed line


def test_engineer_plays_commanders_game():
    """Same missions: with no orders, Engineer and Commander end bit-identical (only the view and the choices differ)."""
    for sid in SITES:
        a, b = sim.new_mission("a", sid, 5, level="commander"), sim.new_mission("b", sid, 5, level="engineer")
        assert [(s.start_h, s.event["id"]) for s in a.storms] == [(s.start_h, s.event["id"]) for s in b.storms]
        sim.advance(a, 40)
        sim.advance(b, 40)
        assert (a.power, a.life, a.dose, a.outcome) == (b.power, b.life, b.dose, b.outcome), sid
        assert sim.to_state(b)["engineer"] and not sim.to_state(a)["engineer"]


def test_units_are_real_and_consistent():
    m = sim.new_mission("u", "malapert_massif", 2, level="engineer")
    u = sim.to_state(m)["units"]
    B = physics.model()["battery_kwh"]["value"]
    assert u["battery_kwh"] == pytest.approx(m.power * B / 100, abs=0.1)
    assert u["net_kw"] == pytest.approx(u["solar_kw"] + u["backup_kw"] - u["load_kw"], abs=0.02)
    assert 0 < u["heater_kw"] <= u["heater_rated_kw"] and u["outside_k"] > 0
    # the array that makes the sim's full-Sun charge, at NASA's 30% cells and 1361 W/m²
    assert u["array_m2"] == round(physics.kw(sim.SOLAR_GEN) * 1000 / (1361 * 0.30))


def _night(level):
    m = sim.new_mission("n", "malapert_massif", 2, level=level)
    for _ in range(240):
        if m.gp and any(t["kind"] == "night_prep" and t["status"] == "active" for t in m.gp["tasks"].values()):
            return m
        sim.step(m, 1)
    raise AssertionError("no night checklist")


def test_engineer_night_is_a_budget_and_duty_cycle_choice():
    m = _night("engineer")
    t = next(t for t in m.gp["tasks"].values() if t["kind"] == "night_prep" and t["status"] == "active")
    ids = [s["id"] for s in t["steps"]]
    assert ids[:2] == ["budget", "duty"]
    assert all("kW" in o["hint"] for s in t["steps"][:2] for o in s["options"])
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "budget", "choice": "night"})
    assert r["ok"] and m.power_save
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "duty", "choice": "50"})
    assert r["ok"] and m.loads["heaters"] == 10 and physics.heater_duty(m) == 0.5
    # Commander keeps its two orders
    c = _night("commander")
    ct = next(t for t in c.gp["tasks"].values() if t["kind"] == "night_prep" and t["status"] == "active")
    assert [s["id"] for s in ct["steps"]][:2] == ["night", "heaters"]


def test_route_choice_names_the_lola_slopes():
    m = sim.new_mission("r", "shackleton_rim", 2, level="commander")
    t = gameplay._ice_run(m)
    hints = [o["hint"] for o in t["steps"][0]["options"]]
    sl = physics.site_phys("shackleton_rim")["slope"]
    assert f"{sl['median_deg']['value']:.0f}°" in hints[0] and f"{sl['p90_deg']['value']:.0f}°" in hints[1]


def test_debrief_numbers_are_cause_and_effect_with_sources():
    for sid in SITES:
        m = sim.new_mission("d", sid, 4, level="engineer")
        sim.advance(m, 40)
        d = sim.debrief(m)
        assert 3 <= len(d["numbers"]) <= 5, (sid, d["numbers"])
        for n in d["numbers"]:
            assert n["source"]["url"].startswith("http") and n["eq"] and re.search(r"\d", n["text"])
            assert physics.words(n["say"]) <= 20, n["say"]
    # a sheltered storm reports the dose it saved
    m = sim.new_mission("s", "shackleton_rim", 4, level="commander")
    st = next(s for s in m.storms if s.event.get("sep"))
    while m.t_h < st.start_h and not m.over:
        m.power, m.life = 100.0, 100.0     # keep the outpost alive to the storm: this test is about the storm ledger
        sim.step(m, 1)
    assert not m.over
    m.rover["busy"] = False
    sim.apply_command(m, {"type": "shelter", "on": True})
    sim.step(m, 6)
    line = next(n for n in physics.numbers(m) if n["id"] == "storm")
    b = m.phys["storms"][st.event["id"]]
    assert b["shelter_h"] >= 6 and b["dose"] < b["dose_open"] and "instead of" in line["text"]


@pytest.mark.parametrize("text,gauge", [("why is power low", "power"), ("why is the battery dropping", "battery"),
                                        ("how come the dose is rising", "dose"), ("explain the heaters", "heaters"),
                                        ("why is the air going down", "life_support"), ("why are the shields pretend", "shields"),
                                        ("why is the rover so slow", "rover"), ("why", None)])
def test_router_why_intent(text, gauge):
    assert R.nav_intent(text, R.Ctx(screen="cabin")) == ("why", gauge)
    assert R.nav_intent(text, R.Ctx(screen="library")) is None      # elsewhere it stays a question for the brain


def test_router_why_leaves_other_questions_alone():
    assert R.nav_intent("why is the sky black", R.Ctx(screen="cabin")) is None
    assert R.nav_intent("why", R.Ctx(screen="cabin", offer="tour")) is None
