"""The first-time-player playtest's Mission science findings (docs/playtest/NOVICE_PLAYTEST_2026-11-16.md, finding 4).

At Shackleton Rim, the "best first pick", Earth is below the outpost's horizon until Day 6 (JPL Horizons + the LOLA
skyline: real data, unchanged). The Science star used to count only science SENT home, so chapters 1 and 2 could not
earn it, and a card-following first mission gathered ~80 of the 120 science goal. Now: store and forward (science
gathered with no Earth window counts, and waits on board), science drives after the ice, and lines that agree.
"""
import pytest

from app.mission import gameplay, registry, sim


@pytest.fixture(autouse=True)
def _saves(tmp_path, monkeypatch):
    monkeypatch.setenv("MISSION_SAVE_DIR", str(tmp_path))


def _follow(mid, n=500):
    """A first-time player: press whatever the Now card offers (the first option of a choice), else let time run."""
    for i in range(n):
        m = registry.get(mid)
        if m.over:
            return registry.get(mid)
        t = gameplay.view(m)["task"]
        st = t and t["step"]
        if st and st["ready"] and st["kind"] != "wait":
            cmd = {"type": "task", "task": t["id"], "step": st["id"]}
            if st["kind"] in ("choice", "describe", "sequence"):   # [0.5 field] the card's first button
                cmd["choice"] = st["options"][0]["id"]
            r = registry.apply(mid, cmd)
            if r["result"].get("needs_confirm"):
                registry.apply(mid, {"type": "confirm"})
        elif i % 3 == 0:
            registry.step(mid, 2.75)
        else:
            registry.skip(mid)
    return registry.get(mid)


def test_earth_is_really_down_at_shackleton_rim_until_day_6():
    earth = sim.sky_table("shackleton_rim")[1]
    first = next(h for h, up in enumerate(earth) if up)
    assert 120 <= first < 144, first          # Day 6 (the data, not a game choice)
    assert gameplay.earth_hours(sim.new_mission("x", "shackleton_rim", 0), 0) == 0
    assert gameplay.earth_hours(sim.new_mission("x", "shackleton_rim", 0), 1) == 0


@pytest.mark.parametrize("level", ["cadet", "commander"])
@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_a_first_mission_at_shackleton_can_earn_every_star(level, seed):
    m = _follow(registry.create("shackleton_rim", seed, level=level).id)
    ch = m.gp["chapters"]
    assert m.over and m.outcome == "survived"
    # chapter 1 has no Earth window: its Science star counts science gathered (store and forward), and a kid who does
    # the jobs earns it
    assert ch[0]["science"]["mode"] == "stored" and ch[0]["stars"]["science"], ch[0]
    # chapters with a window count science sent home, as before
    assert any(c["science"]["mode"] == "sent" and c["stars"]["science"] for c in ch[2:])
    # the mission's goals are reachable on a first mission: the science drives after the ice
    assert sim.objectives(m)["science"]["met"] and sim.objectives(m)["ice"]["met"], sim.objectives(m)
    assert m.gp["count"].get("explore", 0) >= 1


def test_the_chapter_line_never_asks_for_a_downlink_with_earth_down():
    m = registry.create("shackleton_rim", 0, level="cadet")
    registry.apply(m.id, {"type": "power_save", "on": True})   # the lab sleeps: no science in chapter 1
    for _ in range(60):
        if registry.get(m.id).gp.get("chapters"):
            break
        registry.skip(m.id)
    c = registry.get(m.id).gp["chapters"][0]
    assert not c["stars"]["science"] and c["science"]["mode"] == "stored"
    assert "Earth is up" not in c["capcom"] or c["stars"]["science"], c["capcom"]


def test_the_counter_shows_science_on_board_and_samples_say_where_it_waits():
    m = sim.new_mission("m", "shackleton_rim", 2, level="cadet")
    m.science = 14.0
    p = gameplay.view(m)["progress"]
    assert p["science_sent"] == 0 and p["science_stored"] == 14.0 and p["earth_up"] is False and p["earth_in_h"] > 100
    sp = gameplay._science(m)
    assert sp.get("sub") == "sample"   # [0.5 field] the first science job is the sample station
    gameplay._start(m, "science", lambda m: sp, [])
    t = gameplay._active(m)[-1]
    sim.apply_command(m, {"type": "task", "task": t["id"], "step": "tool", "choice": t["tool"]})
    sim.apply_command(m, {"type": "task", "task": t["id"], "step": "describe", "choice": "bag"})
    r = sim.apply_command(m, {"type": "task", "task": t["id"], "step": "bag", "choice": "say"})
    assert r["ok"] and "saved for Earthrise" in r["say"], r["say"]


def test_the_debrief_names_the_missed_goal_and_agrees_with_itself():
    m = sim.new_mission("m", "shackleton_rim", 0, level="cadet")
    m.t_h, m.outcome, m.over, m.ice_runs, m.science_sent, m.science = sim.MISSION_H, "survived", True, 1, 58.0, 61.0
    d = sim.debrief(m)
    assert d["why"] == "The crew was safe all 10 days. Science home: 58 of 120."
    assert "shelter" not in d["try"].lower() and "science" in d["try"].lower()


def test_a_skip_never_says_quiet_day_under_a_warning_or_a_storm():
    m = sim.new_mission("m", "shackleton_rim", 0, level="cadet")
    for _ in range(200):
        if m.over:
            break
        r = sim.apply_command(m, {"type": "skip"})
        if sim._warning(m) is not None or sim.env_at(m, m.t_h)["storm"]:
            assert "quiet day" not in r["say"].lower(), r["say"]
