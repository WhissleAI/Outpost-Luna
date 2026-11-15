"""The landing-site navigator (docs/SITE_NAVIGATOR.md): the NASA data loader, the scoring, the router's intents and the
mission integration (a picked site's real numbers reach the sim through its existing site parameters)."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import turn_router as R
from app.config import settings
from app.main import app
from app.mission import navigator as nav
from app.mission import sim

client = TestClient(app)
FIELDS = ("sunlight_pct", "longest_dark_h", "earth_pct", "slope_deg", "psr_km", "ice_km", "temp_c")


# ---------------------------------------------------------------- the data loader
def test_every_place_has_every_number_with_a_source():
    d = nav.load()
    assert len([p for p in d["places"] if p["kind"] == "site"]) == len(sim.sites()) == 5
    assert len([p for p in d["places"] if p["kind"] == "region"]) == 9      # NASA's Oct 2024 list
    for p in d["places"]:
        for f in FIELDS:
            assert f in p, (p["id"], f)
            assert p[f]["source"] in d["sources"], (p["id"], f, p[f]["source"])
            assert p[f].get("basis") and p[f].get("unit"), (p["id"], f)
        assert p["status"] in ("nasa_2024", "dropped_2022", "studied"), p["id"]
    for k, s in d["sources"].items():
        assert s["url"].startswith("https://") and s["title"] and s["label"], k


def test_numbers_are_physical_and_ranges_hold_the_value():
    for p in nav.places():
        assert 0 <= p["sunlight_pct"]["value"] <= 100 and 0 <= p["earth_pct"]["value"] <= 100, p["id"]
        assert 0 <= p["slope_deg"]["value"] < 45, p["id"]
        lo, hi = p["sunlight_pct"]["range"]
        assert lo <= p["sunlight_pct"]["value"] <= hi, p["id"]
        t = p["temp_c"]["range"]
        assert -273 < t[0] <= t[1] < 130, p["id"]                           # yearly average to yearly maximum
        assert p["longest_dark_h"]["value"] >= 0


def test_the_crater_floor_is_the_cold_dark_ice_site():
    floor, rim = nav.place("shackleton_floor"), nav.place("shackleton_rim")
    assert floor["sunlight_pct"]["value"] == 0 and floor["longest_dark_h"]["value"] >= 8760   # never lit in 2026
    assert floor["ice_km"]["value"] < 0.5 and floor["temp_c"]["range"][1] < -150             # Diviner: always < -150 C
    assert rim["sunlight_pct"]["value"] > 80                                                   # LOLA agrees with Bussey 2010
    assert nav.place("malapert_massif")["earth_pct"]["range"][1] >= 95   # the Earth-facing mountain


def test_nasa_tags_match_the_2024_list():
    tags = {p["id"]: p["status"] for p in nav.places()}
    assert tags["malapert_massif"] == tags["de_gerlache_rim"] == "nasa_2024"
    assert tags["shackleton_rim"] == tags["connecting_ridge"] == "dropped_2022"
    assert tags["shackleton_floor"] == "studied"
    names = {p["name"] for p in nav.places() if p["kind"] == "region"}
    assert names == {"Peak near Cabeus B", "Haworth", "Malapert Massif", "Mons Mouton Plateau", "Mons Mouton",
                     "Nobile Rim 1", "Nobile Rim 2", "de Gerlache Rim 2", "Slater Plain"}


# ---------------------------------------------------------------- scoring (frontend/src/mission/navigator_score.js mirrors it)
CASES = json.loads((settings.data_dir.parent.parent / "frontend/tests/fixtures/navigator_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"{c['place']}-{c['preset']}")
def test_score_matches_the_shared_cases(case):
    assert nav.score(nav.place(case["place"]), nav.PRESETS[case["preset"]]) == case["score"]


def test_weights_move_the_ranking():
    sites = [p for p in nav.places() if p["kind"] == "site"]
    top = lambda w: max(sites, key=lambda p: nav.score(p, w))["id"]
    assert top(nav.PRESETS["ice_first"]) != top(nav.PRESETS["power_first"]) or \
        nav.score(nav.place("shackleton_floor"), nav.PRESETS["ice_first"]) > nav.score(nav.place("shackleton_floor"), nav.PRESETS["power_first"])
    assert nav.score(nav.place("shackleton_floor"), {"power": 0, "comms": 0, "ice": 0, "safety": 0}) == \
        nav.score(nav.place("shackleton_floor"), nav.PRESETS["balanced"])          # all zero counts as balanced
    assert nav.best("ice_km")["id"] == "shackleton_floor"


def test_api_navigator_and_layers():
    r = client.get("/api/sites/navigator").json()
    assert len(r["places"]) == 14 and {c["id"] for c in r["criteria"]} == {"power", "comms", "ice", "safety"}
    assert sum(p["playable"] for p in r["places"]) == 5
    assert r["layers"]["state"] in ("ready", "missing", "downloading")
    assert client.get("/api/sites/layers/evil.png").status_code == 404
    assert client.get("/api/sites/layers/..%2Fsites_physics.json").status_code == 404


def test_layers_state_without_the_asset(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_LAYERS_DIR", str(tmp_path / "none"))
    monkeypatch.delenv("ASSETS_DIR", raising=False)
    assert nav.layers_state() == {"state": "missing", "managed": False}
    monkeypatch.setenv("ASSETS_DIR", str(tmp_path))
    assert client.post("/api/sites/layers/want").json() == {"ok": True, "managed": True}
    assert (tmp_path / ".want" / "site_layers").exists()
    assert nav.layers_state() == {"state": "missing", "managed": True}     # asked for, not yet moving
    (tmp_path / ".active").mkdir()
    (tmp_path / ".active" / "site_layers").write_text("")
    assert nav.layers_state()["state"] == "downloading"


# ---------------------------------------------------------------- the router
@pytest.mark.parametrize("q,want", [
    ("show sunlight", ("site_layer", "sunlight")), ("show me the ice", ("site_layer", "ice")),
    ("earth view", ("site_layer", "earth")), ("the slope map", ("site_layer", "slope")),
    ("hide the layers", ("site_layer", "off")),
    ("which site has the most ice", ("site_query", "ice")), ("which one is the sunniest", ("site_query", "sunlight")),
    ("where can we talk to earth the most", ("site_query", "earth")), ("which site is best", ("site_query", "best")),
    ("ice first", ("site_preset", "ice_first")), ("power first", ("site_preset", "power_first")),
    ("make it balanced", ("site_preset", "balanced")),
    ("pick malapert", ("pick_site", "malapert_massif")), ("pick haworth", ("pick_site", "a3_haworth")),
])
def test_router_navigator_intents_on_the_picker(q, want):
    from app import session as S
    assert R.nav_intent(q, R.Ctx(screen="brief", sites=S._sites())) == want


@pytest.mark.parametrize("screen", ["cabin", "lesson", "map", "library", "debrief"])
def test_router_navigator_intents_stay_on_the_picker(screen):
    for q in ("show sunlight", "which site has the most ice", "ice first"):
        nv = R.nav_intent(q, R.Ctx(screen=screen))
        assert not nv or not nv[0].startswith("site_"), (screen, q, nv)
    assert R.nav_intent("what is ice", R.Ctx(screen="brief")) is None    # a question, not a ranking


# ---------------------------------------------------------------- the mission engine
def test_engine_fields_come_from_the_physics():
    for s in sim.sites():
        p = nav.place(s["physics_id"])
        assert s["sunlight_pct"] == p["sunlight_pct"]["value"]
        assert s["rover_to_ice_h"] == (0 if s["ice"] else p["rover_to_ice_h"])
        e = sim.ephemeris(s["id"])
        assert len(e["sun_terrain_deg"]) == len(e["sun_elev_deg"]) == len(e["earth_terrain_deg"])
        lit = [a > b for a, b in zip(e["sun_elev_deg"], e["sun_terrain_deg"])]
        assert s["window_sunlit_pct"] == round(100 * sum(lit) / len(lit))


def test_picking_a_site_flies_its_real_numbers():
    """The sim's Sun, Earth and ice run follow the picked site's LOLA skyline and Diviner/LOLA ice drive."""
    for sid in ("shackleton_rim", "malapert_massif", "connecting_ridge"):
        st = client.post("/api/mission/start", json={"site": sid, "seed": 3}).json()
        s, e = sim.site(sid), sim.ephemeris(sid)
        assert st["site"]["id"] == sid and st["site"]["rover_to_ice_h"] == s["rover_to_ice_h"]
        m = sim.new_mission("t", sid, 3)
        for t in (0, 30, 77, 150, 239):
            env = sim.env_at(m, t)
            assert env["in_sun"] == (e["sun_elev_deg"][t] > e["sun_terrain_deg"][t]), (sid, t)
            assert env["earth_visible"] == (e["earth_elev_deg"][t] > e["earth_terrain_deg"][t]), (sid, t)
        win = client.get(f"/api/mission/{st['id']}/windows").json()
        sun_h = sum(b - a for a, b in win["sun"])
        assert abs(sun_h - s["window_sunlit_pct"] * 2.4) <= 3, (sid, sun_h)


def test_the_ice_run_costs_its_distance_and_slope():
    s = sim.site("malapert_massif")
    m = sim.new_mission("ice", "malapert_massif", 1)
    m.power = 90.0
    out = m.apply({"type": "dispatch", "vehicle": "rover", "task": "collect_ice"})
    assert out["result"]["ok"]
    assert m.rover["eta_h"] == max(4, 2 * s["rover_to_ice_h"] + 2)
    assert m.power == pytest.approx(90.0 - sim.ROVER_POWER - s["rover_slope_power"])
    near = sim.site("shackleton_rim")
    assert near["rover_to_ice_h"] < s["rover_to_ice_h"]              # 2.9 km vs 12.1 km to surface-stable ice
