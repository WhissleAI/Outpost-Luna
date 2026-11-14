"""Play fixed strategies through the real mission sim (app/mission/sim.py) and report outcomes.

Purpose: game-balance evidence for docs/LEARNING_DESIGN.md §6. A healthy design has no dominant strategy: the
"reads the data" strategies should beat every degenerate one (idle, always-shelter, max shields, spam science,
spam rover) on score, and the degenerate ones should each fail somewhere for a reason the debrief can teach.

Policies only see what a kid sees: the State (resources, env, alerts, rover, storm when active) and the events and
Houston replies the sim emits. None of them read the hidden storm schedule.

    uv run python tools/strategy_sim.py                 # all sites x seeds 0..29
    uv run python tools/strategy_sim.py --seeds 60 --json out.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.mission import sim  # noqa: E402


def cmd(m, c: dict) -> dict:
    r = sim.apply_command(m, c)
    if r.get("needs_confirm"):
        r = sim.apply_command(m, {"type": "confirm"})
    return r


def alloc(m, to: str, pct: int):
    if m.loads.get(to) != pct:
        cmd(m, {"type": "allocate", "to": to, "amount": {"kind": "percent", "value": pct}})


class Policy:
    """Base: do nothing, end every shift (the "spam end shift" player)."""
    name = "idle"
    blurb = "never gives an order; says end shift 40 times"

    def __init__(self):
        self.warned_at: int | None = None   # mission hour of the last storm warning heard (event or Houston)
        self.heard_eta: int | None = None

    def observe(self, m, events: list[dict], replies: list[str]):
        for e in events:
            if e["kind"] == "solar_storm" and "may reach you" in e["text"]:
                self.warned_at = m.t_h
            if e["kind"] == "storm_warning":   # tuned sim: explicit warning event with a lead time
                self.warned_at = m.t_h
        for say in replies:
            if "Expect a storm in about" in say:
                try:
                    self.heard_eta = m.t_h + int(say.split("Expect a storm in about")[1].split()[0])
                except ValueError:
                    pass

    def act(self, m, st: dict):
        return []


class ShieldsMax(Policy):
    name = "shields_max"
    blurb = "all power to the radiation shields, forever"

    def act(self, m, st):
        alloc(m, "shields", 100)
        return []


class AlwaysShelter(Policy):
    name = "always_shelter"
    blurb = "crew lives in the storm shelter for 10 days"

    def act(self, m, st):
        if not m.shelter:
            cmd(m, {"type": "shelter", "on": True})
        return []


class ScienceMax(Policy):
    name = "science_max"
    blurb = "all power to science, ignores everything"

    def act(self, m, st):
        alloc(m, "science", 100)
        return []


class CommsMax(Policy):
    name = "comms_max"
    blurb = "all power to the radio: the cheapest load, so the battery never drains (a split-sums-to-100 loophole)"

    def act(self, m, st):
        alloc(m, "comms", 100)
        return []


class RoverSpam(Policy):
    name = "rover_spam"
    blurb = "rover out for ice or samples every time it is free"

    def act(self, m, st):
        if not m.rover["busy"] and not m.shelter:
            task = "collect_ice" if m.life < 90 else "explore"
            cmd(m, {"type": "dispatch", "vehicle": "rover", "task": task})
        return []


class Reactive(Policy):
    name = "reactive"
    blurb = "shelters only once a storm is already hitting; fixes things when alarms sound"

    def act(self, m, st):
        storm = st["env"]["storm"]["active"]
        if storm and not m.shelter:
            if m.rover["busy"]:
                cmd(m, {"type": "dispatch", "vehicle": "rover", "task": "return"})
            cmd(m, {"type": "shelter", "on": True})
        elif not storm and m.shelter:
            cmd(m, {"type": "shelter", "on": False})
        _housekeeping(m, st)
        return []


def _housekeeping(m, st, ice_at: float = 45, science_bias: bool = False):
    """Rover for ice/repairs when free and safe; heaters on in the dark; trim loads when the battery is low."""
    env = st["env"]
    if not m.shelter and not m.rover["busy"] and not env["storm"]["active"]:
        if "array_damaged" in st["alerts"] and m.power > 15:
            cmd(m, {"type": "dispatch", "vehicle": "rover", "task": "repair_array"})
        elif m.life < ice_at and m.power > 15:
            cmd(m, {"type": "dispatch", "vehicle": "rover", "task": "collect_ice"})
    if not env["in_sun"] and m.loads["heaters"] < 10:
        alloc(m, "heaters", 10)
    if m.power < 25 and m.loads["science"] > 5:
        alloc(m, "science", 5)
    elif science_bias and m.power > 60 and m.loads["science"] < 30:
        alloc(m, "science", 30)


class Planner(Policy):
    """Reads the data: calls Houston when Earth is up, shelters on a warning (before the hit), keeps shields
    moderate, sends science home in comm windows, runs ice when it's safe."""
    name = "planner"
    blurb = "listens for warnings, calls Houston in comm windows, shelters early, banks science home"

    def act(self, m, st):
        env = st["env"]
        if env["earth_visible"] and m.power > 30 and (self.heard_eta is None or self.heard_eta < m.t_h) \
                and m.t_h % 24 == 0:
            r = cmd(m, {"type": "call_houston", "text": "space weather?"})
            self.observe(m, [], [r.get("say", "")])
        storm = env["storm"]["active"]
        soon = (self.warned_at is not None and m.t_h - self.warned_at <= 12) or \
               (self.heard_eta is not None and 0 <= self.heard_eta - m.t_h <= 6)
        if (storm or soon) and not m.shelter:
            if m.rover["busy"]:
                cmd(m, {"type": "dispatch", "vehicle": "rover", "task": "return"})
            cmd(m, {"type": "shelter", "on": True})
        elif not storm and not soon and m.shelter:
            cmd(m, {"type": "shelter", "on": False})
        alloc(m, "comms", 10 if env["earth_visible"] else 2)
        _housekeeping(m, st, ice_at=50, science_bias=True)
        return []


POLICIES = [Policy, ShieldsMax, AlwaysShelter, ScienceMax, CommsMax, RoverSpam, Reactive, Planner]


def play(policy_cls, site: str, seed: int) -> dict:
    m = sim.new_mission(f"s-{policy_cls.name}", site, seed)
    p = policy_cls()
    while not m.over:
        st = sim.to_state(m)
        p.act(m, st)
        evs = sim.advance(m, 1)
        p.observe(m, evs, [])
    return {"policy": p.name, "site": site, "seed": seed, "outcome": m.outcome, "score": sim.score(m),
            "dose": round(m.dose, 1), "science_sent": round(m.science_sent, 1), "hours": m.t_h,
            "grade": sim.debrief(m)["grade"]}


def summarize(rows: list[dict]) -> dict:
    out = {}
    for name in dict.fromkeys(r["policy"] for r in rows):
        rs = [r for r in rows if r["policy"] == name]
        by_site = {}
        for s in dict.fromkeys(r["site"] for r in rs):
            ss = [r for r in rs if r["site"] == s]
            by_site[s] = {"survived": round(sum(r["outcome"] == "survived" for r in ss) / len(ss), 2),
                          "score": round(statistics.mean(r["score"] for r in ss))}
        fails = {}
        for r in rs:
            if r["outcome"] != "survived":
                fails[r["outcome"]] = fails.get(r["outcome"], 0) + 1
        out[name] = {"survived": round(sum(r["outcome"] == "survived" for r in rs) / len(rs), 2),
                     "score_mean": round(statistics.mean(r["score"] for r in rs)),
                     "score_min": min(r["score"] for r in rs),
                     "dose_mean": round(statistics.mean(r["dose"] for r in rs), 1),
                     "science_sent_mean": round(statistics.mean(r["science_sent"] for r in rs), 1),
                     "fails": fails, "by_site": by_site}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    rows = [play(P, s["id"], k) for P in POLICIES for s in sim.sites() for k in range(a.seeds)]
    summ = summarize(rows)
    sites = [s["id"] for s in sim.sites()]
    print(f"{'policy':16} {'surv':>5} {'score':>6} {'min':>5} {'dose':>6} {'sci':>6}  " +
          " ".join(f"{s[:10]:>10}" for s in sites) + "  fails")
    for name, v in sorted(summ.items(), key=lambda kv: -kv[1]["score_mean"]):
        print(f"{name:16} {v['survived']:5.2f} {v['score_mean']:6d} {v['score_min']:5d} {v['dose_mean']:6.1f} "
              f"{v['science_sent_mean']:6.1f}  " +
              " ".join(f"{v['by_site'][s]['survived']:4.2f}/{v['by_site'][s]['score']:<5d}" for s in sites) +
              f"  {v['fails']}")
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summ, "rows": rows}, indent=1))
    return summ


if __name__ == "__main__":
    main()
