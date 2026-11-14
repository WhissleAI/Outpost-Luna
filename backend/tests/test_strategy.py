"""Game balance: no fixed rule wins the mission; reading the data does (docs/LEARNING_DESIGN.md §6.4).

Plays tools/strategy_sim.py's policies through the real sim. The policies see only what a kid sees. Every guarantee is
checked under each clock: the old turn-based shifts, the live mission clock (act at any hour) and "skip to next event"
(docs/GAMEPLAY.md)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import strategy_sim as ss  # noqa: E402

SEEDS = 4


@pytest.fixture(scope="module", params=[(lv, c) for c in ss.CLOCKS for lv in ("commander", "cadet")],
                ids=lambda p: f"{p[0]}-{p[1]}")
def summary(request):
    level, clock = request.param
    return level, ss.summarize(ss.run(SEEDS, level, clock))


def test_reading_the_data_survives_every_site(summary):
    level, s = summary
    for site, v in s["planner"]["by_site"].items():
        assert v["survived"] >= 0.9, (level, site, v)


def test_no_fixed_rule_dominates(summary):
    level, s = summary
    best_fixed = max(s[p]["score_mean"] for p in ss.FIXED)
    assert s["planner"]["score_mean"] >= best_fixed + 150, (level, s["planner"]["score_mean"], best_fixed)
    for p in ss.FIXED:
        # No fixed rule averages a B (560), and few runs reach A. A gamble (rover spam) may sometimes pay off with a
        # B: that is risk vs reward, not a dominant strategy. Cadet: surviving is a B by design, so only A counts.
        assert s[p]["score_mean"] < 560, (level, p, s[p]["score_mean"])
        assert s[p]["grades"]["A"] <= 0.2 * sum(s[p]["grades"].values()), (level, p, s[p]["grades"])


def test_hiding_is_safe_but_not_a_mission(summary):
    level, s = summary
    assert s["always_shelter"]["goals_met"] <= 0.05, s["always_shelter"]


def test_spamming_end_shift_loses_on_commander(summary):
    level, s = summary
    if level == "commander":
        assert s["idle"]["survived"] < 0.5, s["idle"]


def test_degenerate_rules_fail_for_different_reasons(summary):
    level, s = summary
    reasons = set()
    for p in ss.FIXED:
        reasons |= set(s[p]["fails"])
        if s[p]["goals_met"] < 0.5:
            reasons.add("goals")
    assert len(reasons) >= 3, reasons   # each debrief teaches something different


def test_live_clock_is_the_same_game_as_shifts():
    """Stepping a shift in small real-time frames is bit-identical to ending it: the clock never changes the physics."""
    from app.mission import sim
    a, b = sim.new_mission("a", "malapert_massif", 3, level="commander"), sim.new_mission("b", "malapert_massif", 3,
                                                                                         level="commander")
    while not a.over:
        sim.advance(a, 1)
        for _ in range(24):
            sim.step(b, 0.25)
        assert (a.t_h, round(a.power, 6), round(a.life, 6), round(a.dose, 6)) == \
            (b.t_h, round(b.power, 6), round(b.life, 6), round(b.dose, 6))
    assert a.outcome == b.outcome and sim.score(a) == sim.score(b)


def test_policies_never_read_the_hidden_schedule():
    src = Path(ss.__file__).read_text()
    assert ".storms" not in src and "start_h" not in src
