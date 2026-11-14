"""Game balance: no fixed rule wins the mission; reading the data does (docs/LEARNING_DESIGN.md §6.4).

Plays tools/strategy_sim.py's policies through the real sim. The policies see only what a kid sees."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import strategy_sim as ss  # noqa: E402

SEEDS = 4


@pytest.fixture(scope="module", params=["commander", "cadet"])
def summary(request):
    return request.param, ss.summarize(ss.run(SEEDS, request.param))


def test_reading_the_data_survives_every_site(summary):
    level, s = summary
    for site, v in s["planner"]["by_site"].items():
        assert v["survived"] >= 0.9, (level, site, v)


def test_no_fixed_rule_dominates(summary):
    level, s = summary
    best_fixed = max(s[p]["score_mean"] for p in ss.FIXED)
    assert s["planner"]["score_mean"] >= best_fixed + 150, (level, s["planner"]["score_mean"], best_fixed)
    for p in ss.FIXED:
        # Commander: a fixed rule almost never earns A or B. Cadet: surviving is a B by design, so only the goals' A
        # counts, and a gamble (rover spam) may sometimes pay: risk vs reward, not a dominant strategy.
        top = s[p]["grades"]["A"] + (s[p]["grades"]["B"] if level == "commander" else 0)
        assert top <= (0.1 if level == "commander" else 0.2) * sum(s[p]["grades"].values()), (level, p, s[p]["grades"])


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


def test_policies_never_read_the_hidden_schedule():
    src = Path(ss.__file__).read_text()
    assert ".storms" not in src and "start_h" not in src
