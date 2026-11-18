"""Round 13: the class gate of a round-13 candidate against what ships (round 12's routed config), turn by turn.

  python3 gate_r13.py --data data/ds_r13 --ship backend/app/director_model --cand <r13 run> [--cand-weights DIR]
                      [--policy JSON] [--memo DIR] [--out gate_r13.json]

Configs (each exactly as runtime.Shadow + session.py decide it, through evaluate.guarded_outcome / runtime.pick):
  rules   DIRECTOR_MODEL=shadow (the one-env rollback): the rules decide everywhere
  ship    what ships today (round 12): weights.json (r12 xl) decides in quiet, weights_r10 in hot + echo, the rules
          elsewhere (short, video, nav, answer)
  r13     ship, with ONE class handed to the round-13 candidate (val-fitted policy)
  routed  ship, with every class the candidate passes on its own handed to it
A candidate class passes only if, on EVERY set: 0 extra wrong actions vs the rules and vs ship, act ok >= both (the
class's own turns; for nav / answer, which touch every turn: >= ship, and no more extra wrong vs the rules than ship);
and its total act ok gain over ship is > 0. The routed config must then beat ship on every set: act ok >=, 0 extra
wrong vs ship and vs the rules, and > 0 in total. Each model reads its own feature prefix (r10 242, r12 261, r13 275)
with its own `trained_zero` slots at 0 (the numpy runtime does that; the torch candidate was trained with them at 0).
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as E  # noqa: E402
from gate_r12 import Torch, fit  # noqa: E402
from app.director_model import runtime as RT  # noqa: E402

FILES = {"r12": "weights", "r10": "weights_r10", "r13": "weights_r13"}   # the names the runtime routes by


class NumpyNamed:
    """A shipped weight file by name (weights / weights_r10), stepped by the numpy runtime."""

    def __init__(self, d: str, name: str):
        self.nm = E.NumpyModel.__new__(E.NumpyModel)
        self.nm.m = RT.Model(Path(d), name)
        self.nm.meta = self.nm.m.meta
        self.meta = self.nm.meta

    def rows(self, d: Path, name: str):
        return E.turn_rows(self.nm, d, name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--ship", required=True, help="the shipped weights dir (weights.* = r12, weights_r10.*)")
    ap.add_argument("--cand", default="", help="the round-13 torch run (policy fit on val)")
    ap.add_argument("--cand-weights", default="", help="the round-13 exported weights dir (file weights.*, own policy)")
    ap.add_argument("--policy", default="", help="JSON merged over the candidate's fitted policy")
    ap.add_argument("--route", default="", help="force the routed config's candidate classes (comma)")
    ap.add_argument("--memo", default="")
    ap.add_argument("--tag", default="r13", help="memo key of the candidate")
    ap.add_argument("--sets", default="", help="only these sets (comma)")
    ap.add_argument("--report", default="", help="report-only sets (comma; the stress sets): never gate")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    d = Path(a.data)
    extra = json.loads(a.policy) if a.policy else {}
    models = {"r12": NumpyNamed(a.ship, "weights"), "r10": NumpyNamed(a.ship, "weights_r10")}
    p12 = {**RT.DEFAULT_POLICY, **(models["r12"].meta.get("policy") or {})}
    p10 = {**RT.DEFAULT_POLICY, **(models["r10"].meta.get("policy") or {})}
    pols = {"r12": {k: v for k, v in p12.items() if k not in ("classes", "routes")},
            "r10": {k: v for k, v in p10.items() if k not in ("classes", "routes")}}
    # what ships: class -> the model that decides it (the rules decide every class not listed)
    SHIP = {c: "r12" for c in p12.get("classes") or []}
    SHIP.update({c: {v: k for k, v in FILES.items()}[f] for c, f in (p12.get("routes") or {}).items()})
    if a.cand_weights:
        models["r13"] = NumpyNamed(a.cand_weights, "weights")
        p13 = {**RT.DEFAULT_POLICY, **(models["r13"].meta.get("policy") or {})}
        pols["r13"] = {k: v for k, v in p13.items() if k not in ("classes", "routes")}
    else:
        models["r13"] = Torch(a.cand)
        pols["r13"] = {**{x: v for x, v in fit(models["r13"], d).items() if x != "fit"}, **extra}
    print(f"ship: {json.dumps(SHIP)}")
    for k, v in pols.items():
        print(f"policy {k}: {json.dumps(v)}", flush=True)
    sets = [n for n in E.SETS + E.CLASS_SETS if (d / f"{n}.npz").exists()]
    if a.sets:
        sets = [n for n in sets if n in a.sets.split(",")]
    tags = {"r12": "r12ship", "r10": "r10", "r13": a.tag}

    def rows_of(k, n):
        f = Path(a.memo) / f"{tags[k]}__{n}.pkl" if a.memo else None
        if f and f.exists():
            return pickle.loads(f.read_bytes())
        r = models[k].rows(d, n)
        if f:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(pickle.dumps(r))
        return r

    report = [n for n in a.report.split(",") if n and (d / f"{n}.npz").exists()]
    rows = {}
    for n in sets + report:
        rs = {k: rows_of(k, n) for k in models}
        L = {len(v) for v in rs.values()}
        assert len(L) == 1, (n, L)
        rows[n] = [(rs["r12"][i][0], {k: rs[k][i][1] for k in rs}) for i in range(L.pop())]
        print("rows", n, len(rows[n]), flush=True)

    def outcome(m, os_, owners: dict | None):
        """owners: {class: model key} (None: the rules everywhere). As the runtime runs it: a primary file (r12, the
        shipped weights.json) with `classes` = its own, `routes` = the others' files, each with its own policy."""
        if owners is None:
            return E.rules_out(m)
        thr = {**pols["r12"], "classes": [c for c, k in owners.items() if k == "r12"],
               "routes": {c: FILES[k] for c, k in owners.items() if k != "r12"}}
        o = {**os_["r12"], "_routed": {FILES[k]: os_[k] for k in ("r10", "r13")}}
        return E.guarded_outcome(m, o, thr, {FILES[k]: pols[k] for k in ("r10", "r13")})

    def cell(n, c, owners):
        x = dict(n=0, ok=0, wrong=0, extra_rules=0, extra_ship=0, ex=[])
        for m, os_ in rows[n]:
            if c is not None and c in RT.SITUATIONS and (m.get("situ") or "quiet") != c:
                continue
            ra, rc = E.rules_out(m)
            sa, sc = outcome(m, os_, SHIP)
            a_, c_ = outcome(m, os_, owners)
            x["n"] += 1
            x["ok"] += E.act_ok(m, a_, c_)
            w = E.is_wrong(m, a_, c_)
            x["wrong"] += w
            x["extra_rules"] += w and not E.is_wrong(m, ra, rc)
            x["extra_ship"] += w and not E.is_wrong(m, sa, sc)
            if (w and not E.is_wrong(m, sa, sc)) or (E.act_ok(m, sa, sc) and not E.act_ok(m, a_, c_)):
                if len(x["ex"]) < 6:
                    x["ex"].append(f"[{m.get('situ')}|{m.get('route')}] {m['heard']} -> {a_} (gold {m['gold_act']}, "
                                   f"ship {sa})")
        return x

    res = {"policies": pols, "ship": SHIP, "classes": {}, "routed": {}}
    print("\n| class | turns | act ok rules / ship / r13 | wrong rules / ship / r13 | sets worse | r13 passes |")
    print("|---|---|---|---|---|---|")
    passing = []
    for c in E.CLASSES:
        per = {}
        for n in sets:
            per[n] = {"rules": cell(n, c, None), "ship": cell(n, c, SHIP), "r13": cell(n, c, {**SHIP, c: "r13"})}
        tot = {k: {f: sum(per[n][k][f] for n in sets) for f in ("n", "ok", "wrong", "extra_rules", "extra_ship")}
               for k in per[sets[0]]}
        if c in RT.SITUATIONS:
            worse = [n for n in sets if per[n]["r13"]["extra_rules"] or per[n]["r13"]["extra_ship"]
                     or per[n]["r13"]["ok"] < per[n]["rules"]["ok"] or per[n]["r13"]["ok"] < per[n]["ship"]["ok"]]
        else:
            worse = [n for n in sets if per[n]["r13"]["extra_ship"] or per[n]["r13"]["ok"] < per[n]["ship"]["ok"]
                     or per[n]["r13"]["extra_rules"] > per[n]["ship"]["extra_rules"]]
        ok = not worse and tot["r13"]["ok"] > tot["ship"]["ok"]
        if ok:
            passing.append(c)
        res["classes"][c] = {"total": tot, "worse": worse, "pass": ok, "sets": per}
        ws = ", ".join(f"{n} ({per[n]['r13']['ok'] - max(per[n]['rules']['ok'], per[n]['ship']['ok']):+d} ok, "
                       f"+{max(per[n]['r13']['extra_rules'], per[n]['r13']['extra_ship'])} wrong)" for n in worse) or "none"
        print(f"| {c} | {tot['rules']['n']} | {tot['rules']['ok']} / {tot['ship']['ok']} / {tot['r13']['ok']} | "
              f"{tot['rules']['wrong']} / {tot['ship']['wrong']} / {tot['r13']['wrong']} | {ws} | "
              f"{'yes' if ok else 'no'} |", flush=True)
    route = [x for x in a.route.split(",") if x] if a.route else passing
    owners = {**SHIP, **{c: "r13" for c in route}}
    res["route_classes"], res["owners"] = route, owners
    print(f"\nrouted: {json.dumps(owners)}; vs ship:")
    print("| set | turns | act ok rules / ship / routed | wrong rules / ship / routed | extra wrong vs ship / vs rules |")
    print("|---|---|---|---|---|")
    T: dict = {}
    bad = []
    for n in sets:
        v, b, r = cell(n, None, owners), cell(n, None, SHIP), cell(n, None, None)
        res["routed"][n] = {"routed": v, "ship": b, "rules": r}
        for k, x in (("n", v["n"]), ("rules_ok", r["ok"]), ("ship_ok", b["ok"]), ("ok", v["ok"]),
                     ("rules_wrong", r["wrong"]), ("ship_wrong", b["wrong"]), ("wrong", v["wrong"]),
                     ("extra_ship", v["extra_ship"]), ("extra_rules", v["extra_rules"])):
            T[k] = T.get(k, 0) + x
        if v["ok"] < b["ok"] or v["extra_ship"] or v["extra_rules"] > b["extra_rules"]:
            bad.append(n)
        print(f"| {n} | {v['n']} | {r['ok']} / {b['ok']} / {v['ok']} | {r['wrong']} / {b['wrong']} / {v['wrong']} | "
              f"{v['extra_ship']} / {v['extra_rules']} |")
    print(f"| **all** | {T['n']} | {T['rules_ok']} / {T['ship_ok']} / {T['ok']} | {T['rules_wrong']} / "
          f"{T['ship_wrong']} / {T['wrong']} | {T['extra_ship']} / {T['extra_rules']} |")
    ships = bool(route) and not bad and T["ok"] > T["ship_ok"]
    res["routed_total"], res["routed_worse_sets"], res["routed_ships"] = T, bad, ships
    print(f"\nrouted config ships: {ships} (sets worse than ship: {bad or 'none'})")
    if report:
        print("\nreport only (never gated): act ok / wrong")
        print("| set | turns | rules | ship | routed |")
        print("|---|---|---|---|---|")
        res["report"] = {}
        for n in report:
            r, b, v = cell(n, None, None), cell(n, None, SHIP), cell(n, None, owners)
            res["report"][n] = {"rules": r, "ship": b, "routed": v}
            print(f"| {n} | {r['n']} | {r['ok']} / {r['wrong']} | {b['ok']} / {b['wrong']} | {v['ok']} / {v['wrong']} |")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
