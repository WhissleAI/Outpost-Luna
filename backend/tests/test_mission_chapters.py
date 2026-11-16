"""[polish 2] Chapters with stars, Restart shift and the chapter auto-save (docs/MISSION_POLISH_SPEC.md)."""
import json

import pytest

from app.mission import gameplay, registry, sim


def _play(mid, n=200, live=False):
    """A card-following player through the registry (the routes' path), with some live-clock slices."""
    for i in range(n):
        m = registry.get(mid)
        if m.over:
            return
        t = gameplay.view(m)["task"]
        st = t and t["step"]
        if st and st["ready"] and st["kind"] != "wait":
            cmd = {"type": "task", "task": t["id"], "step": st["id"]}
            if st["kind"] == "choice":
                cmd["choice"] = st["options"][0]["id"]
            r = registry.apply(mid, cmd)
            if r["result"].get("needs_confirm"):
                registry.apply(mid, {"type": "confirm"})
        elif live and i % 3 == 0:
            registry.step(mid, 2.75)
        else:
            registry.skip(mid)


@pytest.fixture(autouse=True)
def _saves(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSION_SAVE_DIR", str(tmp_path))
    yield tmp_path


def _same(a, b):
    sa, sb = sim.to_state(a), sim.to_state(b)
    for k in ("id",):
        sa.pop(k, None), sb.pop(k, None)
    return json.dumps(sa, sort_keys=True, default=str) == json.dumps(sb, sort_keys=True, default=str)


@pytest.mark.parametrize("level", ["cadet", "commander"])
def test_five_chapters_with_stars_and_a_line(level):
    m = registry.create("shackleton_rim", 3, level=level)
    _play(m.id, 400)
    m = registry.get(m.id)
    ch = m.gp["chapters"]
    assert m.over and len(ch) == 5 and ch[-1]["last"]
    for k, c in enumerate(ch):
        assert c["n"] == k + 1 and c["of"] == 5 and set(c["stars"]) == {"safe", "powered", "science"}
        assert c["count"] == sum(c["stars"].values()) and len(c["capcom"].split()) <= 12
    assert any(e["kind"] == "chapter" for e in m.events)


def test_a_chapter_end_stops_a_skip(monkeypatch):
    m = registry.create("connecting_ridge", 1, level="cadet")
    seen = []
    real = sim.skip_to_event

    def spy(mm, *a, **k):
        evs = real(mm, *a, **k)
        ch = [e for e in evs if e["kind"] == "chapter"]
        if ch:
            seen.append(ch[0])
            assert evs[-1]["kind"] == "chapter" or evs[-1]["kind"] in sim.SKIP_STOPS
        return evs
    monkeypatch.setattr(sim, "skip_to_event", spy)
    for _ in range(80):
        if seen or registry.get(m.id).over:
            break
        _play(m.id, 1)
    assert seen and seen[0]["chapter"]["t_h"] == gameplay.CHAPTER_H


@pytest.mark.parametrize("site,seed,level", [("shackleton_rim", 0, "cadet"), ("malapert_massif", 1, "commander"),
                                             ("de_gerlache_rim", 2, "engineer")])
def test_replaying_the_journal_rebuilds_the_same_mission(site, seed, level):
    m = registry.create(site, seed, level=level)
    _play(m.id, 120, live=True)
    m = registry.get(m.id)
    n = registry._rebuild(m, len(m.journal))
    assert _same(m, n)


def test_restart_shift_goes_back_to_the_shift_start():
    m = registry.create("shackleton_rim", 0, level="cadet")
    _play(m.id, 25, live=True)
    m = registry.get(m.id)
    idx = m.t_h // sim.SHIFT_H
    t0 = m.t_h
    r = registry.restart_shift(m.id)
    n = registry.get(m.id)
    assert n is not m and n.t_h // sim.SHIFT_H == idx and n.t_h <= t0
    assert r["state"]["mission_time_h"] == n.t_h and "shift" in r["say"]
    registry.step(m.id, 1.0)   # it plays on from there


def test_the_game_saves_each_chapter_and_continues(_saves):
    assert registry.saved() is None
    m = registry.create("connecting_ridge", 4, level="commander")
    for _ in range(200):
        if registry.get(m.id).gp.get("chapters"):
            break
        _play(m.id, 1)
    s = registry.saved()
    assert s and s["chapter"] == 1 and s["site"] == "connecting_ridge"
    body = json.loads((_saves / "mission.json").read_text())
    r = registry.resume()
    assert r and r.id != m.id and r.t_h == body["t_h"] and len(r.gp["chapters"]) == 1
    _play(r.id, 400)
    assert registry.get(r.id).over and registry.saved() is None   # a finished mission isn't offered again


# ---- autosave + resume (a real-user ask: "does the 10-day mission save if they close the app halfway?") ----------
def test_every_meaningful_change_is_saved_and_a_hard_quit_resumes_there(_saves):
    m = registry.create("shackleton_rim", 7, level="cadet")
    _play(m.id, 30, live=True)
    m = registry.get(m.id)
    s = registry.saved()
    assert s and s["day"] == m.t_h // 24 + 1 and s["site_name"]
    body = json.loads((_saves / "mission.json").read_text())
    assert body["t_h"] == m.t_h, "the save is current, not just the last chapter"
    # a hard quit: the process dies; nothing in memory survives, only the file
    registry.MISSIONS.clear()
    r = registry.resume()
    assert r is not None and r.t_h == m.t_h
    a, b = sim.to_state(m), sim.to_state(r)
    for k in ("resources", "loads", "rover", "shelter", "objectives", "task", "progress", "chapter"):
        assert json.dumps(a.get(k), sort_keys=True, default=str) == json.dumps(b.get(k), sort_keys=True, default=str), k
    assert r.gp["count"] == m.gp["count"] and r.warned == m.warned and r.storms == m.storms


def test_a_clock_slice_inside_an_hour_does_not_rewrite_the_save(_saves):
    m = registry.create("shackleton_rim", 1, level="cadet")
    registry.step(m.id, 0.2)
    p = _saves / "mission.json"
    t0 = p.stat().st_mtime_ns
    registry.step(m.id, 0.2)
    assert p.stat().st_mtime_ns == t0
    registry.step(m.id, 1.0)   # a whole hour passed: saved
    assert json.loads(p.read_text())["t_h"] == registry.get(m.id).t_h


def test_a_practice_run_never_overwrites_the_saved_mission(_saves):
    m = registry.create("connecting_ridge", 2, level="cadet")
    registry.skip(m.id)
    before = (_saves / "mission.json").read_text()
    p = registry.create("shackleton_rim", 3, level="cadet", save=False)
    registry.skip(p.id); registry.apply(p.id, {"type": "end_shift"})
    assert (_saves / "mission.json").read_text() == before


@pytest.mark.parametrize("junk", ["", "{not json", "[]", json.dumps({"v": 0, "site": "shackleton_rim"}),
                                  json.dumps({"v": 1, "site": "nowhere", "seed": 1, "t_h": 5, "chapter": 0, "journal": []}),
                                  json.dumps({"v": 1, "site": "shackleton_rim", "seed": 1, "t_h": 99, "chapter": 2,
                                              "journal": [["cmd", {"type": "no_such"}], ["bogus"]]})])
def test_a_corrupt_or_old_save_falls_back_to_a_new_mission(_saves, junk):
    (_saves / "mission.json").write_text(junk)
    s = registry.saved()
    r = registry.resume()
    assert r is None, "never resumes a broken save"
    if s is not None:   # it looked fine on the outside but didn't replay: set aside, not offered again
        assert registry.saved() is None and (_saves / "mission.bad.json").exists()
    m = registry.create("shackleton_rim", 0, level="cadet")   # a new mission still starts and saves
    registry.skip(m.id)
    assert registry.saved()["site"] == "shackleton_rim"


def test_the_routes_offer_resume_and_new(_saves):
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    assert c.get("/api/mission/saved").json() == {"saved": None}
    assert c.post("/api/mission/resume").status_code == 404
    st = c.post("/api/mission/start", json={"site": "shackleton_rim", "seed": 5, "level": "cadet"}).json()
    c.post(f"/api/mission/{st['id']}/skip")
    sv = c.get("/api/mission/saved").json()["saved"]
    assert sv["site"] == "shackleton_rim" and sv["day"] >= 1
    r = c.post("/api/mission/resume").json()
    assert r["mission_time_h"] == registry.get(st["id"]).t_h and r["id"] != st["id"]
    rs = c.post(f"/api/mission/{r['id']}/restart_shift").json()
    assert rs["state"]["id"] == r["id"]
    pr = c.post("/api/mission/start", json={"site": "connecting_ridge", "seed": 1, "level": "cadet", "practice": True}).json()
    c.post(f"/api/mission/{pr['id']}/skip")
    assert c.get("/api/mission/saved").json()["saved"]["site"] == "shackleton_rim"
