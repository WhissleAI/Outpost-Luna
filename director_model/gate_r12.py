"""Round 12: the class gate of every Director config the runtime can run, turn by turn, on the round-12 data.

  python3 gate_r12.py --data data/ds_r12 --r10 backend/app/director_model --r11 <r11 xl run> --cand <r12 run>
                      [--cand-weights DIR] [--memo DIR] [--out gate_r12.json]

Configs (each exactly as runtime.Shadow + session.py decide it, through evaluate.guarded_outcome / runtime.pick):
  rules   DIRECTOR_MODEL=shadow (the one-env rollback): the rules decide everywhere
  r10     what ships today: r10 xl guarded, its own policy, classes hot + echo
  r11     r11 xl (round 11's candidate, never shipped), val-fitted policy, in ONE class at a time
  r12     the round-12 candidate, val-fitted policy, in ONE class at a time
  routed  per-class routing (round 12): r10's file decides in r10's classes (hot, echo), the candidate in the classes
          it passes on its own; every other class: the rules
A candidate class passes only if, on EVERY set: 0 extra wrong actions vs the rules and vs r10, act ok >= both; and its
total act ok gain over r10 is > 0. The routed config must then beat what ships (r10 guarded) on every set: act ok >=,
0 extra wrong actions, and > 0 in total. Feature vectors: r10 / r11 read the 242-wide prefix (they were trained on it),
the candidate all 261.
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as E  # noqa: E402
import train as TR  # noqa: E402
from app.director_model import runtime as RT  # noqa: E402

R10 = "weights_r10"       # the routed file name (backend/app/director_model/weights_r10.{json,npz})


class Torch:
    """A torch run read at its own feature width (an r11 model reads the 242 prefix of the 261-wide sets)."""

    def __init__(self, run: str):
        cfg = json.load(open(f"{run}/train.json"))
        self.F = cfg["F"]
        self.m = TR.make(cfg["F"], cfg["size_name"])
        self.m.load_state_dict(torch.load(f"{run}/model.pt", map_location="cpu"))
        self.m.eval()

    def rows(self, d: Path, name: str):
        ss = TR.load_split(d / f"{name}.npz")
        for s in ss:
            s["feats"] = s["feats"][:, :self.F]
        F0 = TR.FX.F
        TR.FX.F = self.F          # train.batch sizes its feature array by FX.F
        try:
            with torch.no_grad():
                pr = TR.predict(self.m, ss)
        finally:
            TR.FX.F = F0
        return _rows(pr, E.load_meta(d / f"{name}.meta.jsonl"))


def _rows(pr, metas):
    out = []
    for p, ms in zip(pr, metas):
        for t, m in enumerate(ms):
            if m.get("end") and m.get("gold_act") is not None:
                out.append((m, {k: p[k][t] for k in p}))
    return out


class Numpy:
    def __init__(self, d: str):
        self.nm = E.NumpyModel(Path(d))
        self.meta = self.nm.meta

    def rows(self, d: Path, name: str):
        return E.turn_rows(self.nm, d, name)


def fit(model, d: Path) -> dict:
    """evaluate.fit_policy on val for a wrapped model (rows through the wrapper)."""
    orig = E.turn_rows
    E.turn_rows = lambda _m, dd, n: model.rows(dd, n)
    try:
        return E.fit_policy(model, d)
    finally:
        E.turn_rows = orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--r10", required=True, help="the shipped r10 weights dir")
    ap.add_argument("--r11", default="", help="round 11's xl torch run")
    ap.add_argument("--cand", default="", help="the round-12 torch run (policy fit on val)")
    ap.add_argument("--cand-weights", default="", help="the round-12 exported weights (their own policy)")
    ap.add_argument("--policy", default="", help="JSON merged over every fitted policy (e.g. r10's veto / min words)")
    ap.add_argument("--route", default="", help="force the routed config's candidate classes (comma)")
    ap.add_argument("--memo", default="")
    ap.add_argument("--tag", default="r12", help="memo key of the candidate")
    ap.add_argument("--sets", default="", help="only these sets (comma)")
    ap.add_argument("--report", default="", help="report-only sets (comma; e.g. the stress sets): never gate")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    d = Path(a.data)
    extra = json.loads(a.policy) if a.policy else {}
    r10 = Numpy(a.r10)
    p10 = {**RT.DEFAULT_POLICY, **(r10.meta.get("policy") or {})}
    models = {"r10": r10}
    pols = {"r10": p10}
    if a.r11:
        models["r11"] = Torch(a.r11)
    if a.cand_weights:
        models["r12"] = Numpy(a.cand_weights)
        pols["r12"] = {**RT.DEFAULT_POLICY, **(models["r12"].meta.get("policy") or {})}
        pols["r12"] = {k: v for k, v in pols["r12"].items() if k not in ("classes", "routes")}
    elif a.cand:
        models["r12"] = Torch(a.cand)
    for k in ("r11", "r12"):
        if k in models and k not in pols:
            pols[k] = {**{x: v for x, v in fit(models[k], d).items() if x != "fit"}, **extra}
    for k, v in pols.items():
        print(f"policy {k}: {json.dumps(v)}", flush=True)
    sets = [n for n in E.SETS + E.CLASS_SETS if (d / f"{n}.npz").exists()]
    if a.sets:
        sets = [n for n in sets if n in a.sets.split(",")]
    tags = {"r10": "r10", "r11": "r11", "r12": a.tag}

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
        rows[n] = [(rs["r10"][i][0], {k: rs[k][i][1] for k in rs}) for i in range(L.pop())]
        print("rows", n, len(rows[n]), flush=True)

    def outcome(m, os_, cfg):
        """cfg: ("rules",) | ("r10",) | ("routed", model, [classes]): r10's file in r10's classes not listed, `model`
        in the listed ones (one class at a time for the class gate; the passing set for the shipped config)."""
        if cfg[0] == "rules":
            return E.rules_out(m)
        if cfg[0] == "r10":
            return E.guarded_outcome(m, os_["r10"], p10)
        k, cls = cfg[1], list(cfg[2])
        thr = {**pols[k], "classes": cls, "routes": {c: R10 for c in (p10.get("classes") or []) if c not in cls}}
        o = {**os_[k], "_routed": {R10: os_["r10"]}}
        return E.guarded_outcome(m, o, thr, {R10: p10})

    def cell(n, c, cfg):
        x = dict(n=0, ok=0, wrong=0, extra_rules=0, extra_r10=0, ok_lt=0, ex=[])
        for m, os_ in rows[n]:
            if c is not None and c in RT.SITUATIONS and (m.get("situ") or "quiet") != c:
                continue
            ra, rc = E.rules_out(m)
            ba, bc = E.guarded_outcome(m, os_["r10"], p10)
            a_, c_ = outcome(m, os_, cfg)
            x["n"] += 1
            x["ok"] += E.act_ok(m, a_, c_)
            w = E.is_wrong(m, a_, c_)
            x["wrong"] += w
            x["extra_rules"] += w and not E.is_wrong(m, ra, rc)
            x["extra_r10"] += w and not E.is_wrong(m, ba, bc)
            if (w and not E.is_wrong(m, ba, bc)) or (E.act_ok(m, ba, bc) and not E.act_ok(m, a_, c_)):
                if len(x["ex"]) < 6:
                    x["ex"].append(f"[{m.get('situ')}] {m['heard']} -> {a_} (gold {m['gold_act']}, r10 {ba})")
        return x

    res = {"policies": pols, "classes": {}, "routed": {}}
    print("\n| class | turns | act ok rules / r10 / r11 / r12 | wrong rules / r10 / r11 / r12 | r12 sets worse | "
          "r12 passes |")
    print("|---|---|---|---|---|---|")
    passing = []
    for c in E.CLASSES:
        per = {}
        for n in sets:
            per[n] = {"rules": cell(n, c, ("rules",)), "r10": cell(n, c, ("r10",)),
                      **({"r11": cell(n, c, ("routed", "r11", [c]))} if "r11" in models else {}),
                      "r12": cell(n, c, ("routed", "r12", [c]))}
        tot = {k: {f: sum(per[n][k][f] for n in sets) for f in ("n", "ok", "wrong", "extra_rules", "extra_r10")}
               for k in per[sets[0]]}
        if c in RT.SITUATIONS:      # the class's own turns: vs the rules and vs r10, each on its own
            worse = [n for n in sets if per[n]["r12"]["extra_rules"] or per[n]["r12"]["extra_r10"]
                     or per[n]["r12"]["ok"] < per[n]["rules"]["ok"] or per[n]["r12"]["ok"] < per[n]["r10"]["ok"]]
        else:     # nav / answer touch every turn: the candidate config is r10 + the model in this class, so its delta
            # over r10 is the class's own contribution (r10's own gap to the rules, if any, is not this class's)
            worse = [n for n in sets if per[n]["r12"]["extra_r10"] or per[n]["r12"]["ok"] < per[n]["r10"]["ok"]
                     or per[n]["r12"]["extra_rules"] > per[n]["r10"]["extra_rules"]]
        ok = not worse and tot["r12"]["ok"] > tot["r10"]["ok"]
        if ok:
            passing.append(c)
        res["classes"][c] = {"total": tot, "worse": worse, "pass": ok,
                             "sets": per}
        g = lambda k, f: str(tot[k][f]) if k in tot else "-"  # noqa: E731
        ws = ", ".join(f"{n} ({per[n]['r12']['ok'] - max(per[n]['rules']['ok'], per[n]['r10']['ok']):+d} ok, "
                       f"+{max(per[n]['r12']['extra_rules'], per[n]['r12']['extra_r10'])} wrong)" for n in worse) or "none"
        print(f"| {c} | {tot['rules']['n']} | {g('rules','ok')} / {g('r10','ok')} / {g('r11','ok')} / {g('r12','ok')} | "
              f"{g('rules','wrong')} / {g('r10','wrong')} / {g('r11','wrong')} / {g('r12','wrong')} | {ws} | "
              f"{'yes' if ok else 'no'} |", flush=True)
    route = [x for x in a.route.split(",") if x] if a.route else passing
    res["route_classes"] = route
    print(f"\nrouted: r10 in {[c for c in p10.get('classes') or [] if c not in route]}, r12 in {route}; vs r10 guarded "
          "(what ships):")
    print("| set | turns | act ok rules / r10 / routed | wrong rules / r10 / routed | extra wrong vs r10 / vs rules |")
    print("|---|---|---|---|---|")
    T: dict = {}
    bad = []
    for n in sets:
        v = cell(n, None, ("routed", "r12", route))
        b = cell(n, None, ("r10",))
        r = cell(n, None, ("rules",))
        res["routed"][n] = {"routed": v, "r10": b, "rules": r}
        for k, x in (("n", v["n"]), ("rules_ok", r["ok"]), ("r10_ok", b["ok"]), ("ok", v["ok"]),
                     ("rules_wrong", r["wrong"]), ("r10_wrong", b["wrong"]), ("wrong", v["wrong"]),
                     ("extra_r10", v["extra_r10"]), ("extra_rules", v["extra_rules"])):
            T[k] = T.get(k, 0) + x
        if v["ok"] < b["ok"] or v["extra_r10"]:
            bad.append(n)
        print(f"| {n} | {v['n']} | {r['ok']} / {b['ok']} / {v['ok']} | {r['wrong']} / {b['wrong']} / {v['wrong']} | "
              f"{v['extra_r10']} / {v['extra_rules']} |")
    print(f"| **all** | {T['n']} | {T['rules_ok']} / {T['r10_ok']} / {T['ok']} | {T['rules_wrong']} / {T['r10_wrong']} / "
          f"{T['wrong']} | {T['extra_r10']} / {T['extra_rules']} |")
    ships = bool(route) and not bad and T["ok"] > T["r10_ok"]
    res["routed_total"], res["routed_worse_sets"], res["routed_ships"] = T, bad, ships
    print(f"\nrouted config ships: {ships} (sets worse than r10: {bad or 'none'})")
    if report:
        print("\nreport only (never gated): act ok / wrong")
        print("| set | turns | rules | r10 | r10 + r11 in quiet / nav / answer (round 11's passing classes) | routed |")
        print("|---|---|---|---|---|---|")
        res["report"] = {}
        for n in report:
            r, b, v = cell(n, None, ("rules",)), cell(n, None, ("r10",)), cell(n, None, ("routed", "r12", route))
            r11 = cell(n, None, ("routed", "r11", ["quiet", "nav", "answer"])) if "r11" in models else None
            res["report"][n] = {"rules": r, "r10": b, "routed": v, "r11": r11}
            f = lambda x: f"{x['ok']} / {x['wrong']}" if x else "-"  # noqa: E731
            print(f"| {n} | {r['n']} | {f(r)} | {f(b)} | {f(r11)} | {f(v)} |")
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
