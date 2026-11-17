"""Round 11: the class gate of a candidate against the rules AND against the shipped weights, turn by turn.

  python3 gate_vs.py --data data/ds_r11 --base backend/app/director_model --cand runs/<r11>/xl/cand [--cand-weights DIR]
                     [--policy JSON] [--out gate_vs.json]

For each set x class (evaluate.CLASSES), with the candidate enabled in that ONE class (guarded) and the base as it ships
(its own policy and classes):
  vs rules  act ok (cand, rules), wrong (cand, rules), extra wrong over the rules       (evaluate.class_gate)
  vs base   act ok (cand, base),  extra wrong over the base (cand wrong where the base is not)
A class ships only if, on every set: 0 extra wrong vs the rules and vs the base, act ok >= rules and >= base; and its
total act ok gain over the base is > 0 (or, for a class the base already ships, >= 0 with the base's gain kept).
Then the whole candidate config (the passing classes together) vs the base config, per set.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as E  # noqa: E402
import train as TR  # noqa: E402
from app.director_model import runtime as RT  # noqa: E402


def load(run: str | None, weights: str | None):
    if weights:
        m = E.NumpyModel(Path(weights))
        return m, {**RT.DEFAULT_POLICY, **(m.meta.get("policy") or {})}
    cfg = json.load(open(f"{run}/train.json"))
    model = TR.make(cfg["F"], cfg["size_name"])
    model.load_state_dict(torch.load(f"{run}/model.pt", map_location="cpu"))
    model.eval()
    return model, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--base", required=True, help="the shipped weights dir")
    ap.add_argument("--cand", default="", help="a torch run (policy fit on val)")
    ap.add_argument("--cand-weights", default="", help="exported weights (their own policy)")
    ap.add_argument("--policy", default="", help="JSON merged over the candidate's policy")
    ap.add_argument("--classes", default="", help="the candidate config's classes (comma); default: those that pass")
    ap.add_argument("--out", default="")
    ap.add_argument("--memo", default="", help="a dir to memoise per-set model outputs in")
    ap.add_argument("--base-tag", default="", help="memo key of the base (e.g. r10)")
    ap.add_argument("--cand-tag", default="", help="memo key of the candidate")
    a = ap.parse_args()
    d = Path(a.data)
    base, bpol = load(None, a.base)
    cand, cpol = load(a.cand or None, a.cand_weights or None)
    if cpol is None:
        cpol = E.fit_policy(cand, d)
    if a.policy:
        cpol = {**cpol, **json.loads(a.policy)}
    cpol = {k: v for k, v in cpol.items() if k != "classes"}
    print("base policy:", json.dumps(bpol))
    print("cand policy:", json.dumps(cpol), flush=True)
    sets = [n for n in E.SETS + E.CLASS_SETS if (d / f"{n}.npz").exists()]
    rows = {}
    import pickle

    def rows_of(model, tag, n):
        """turn_rows, memoised on disk (--memo DIR, tag = the model's identity): the numpy base is slow to step."""
        f = Path(a.memo) / f"{tag}__{n}.pkl" if a.memo and tag else None
        if f and f.exists():
            return pickle.loads(f.read_bytes())
        r = E.turn_rows(model, d, n)
        if f:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(pickle.dumps(r))
        return r
    btag = a.base_tag or ""
    ctag = a.cand_tag or ""
    for n in sets:
        rb = rows_of(base, btag, n)
        rc = rows_of(cand, ctag, n)
        assert len(rb) == len(rc)
        rows[n] = [(m, ob, oc) for (m, ob), (_, oc) in zip(rb, rc)]
        print("rows", n, len(rows[n]), flush=True)

    def cell(n, c, classes):
        t = {**cpol, "classes": classes}
        # the base restricted to the same class (its policy, its classes ∩ this one): a class's own contribution;
        # the whole base config when comparing configs (c None)
        bp = bpol if c is None else {**bpol, "classes": [k for k in (bpol.get("classes") or []) if k == c]}
        x = dict(n=0, rules_ok=0, base_ok=0, cand_ok=0, rules_wrong=0, base_wrong=0, cand_wrong=0, extra_rules=0,
                 extra_base=0, ex=[])
        for m, ob, oc in rows[n]:
            if c is not None and c in RT.SITUATIONS and (m.get("situ") or "quiet") != c:
                continue
            ra, rcm = E.rules_out(m)
            ba, bcm = E.guarded_outcome(m, ob, bp)
            ca, ccm = E.guarded_outcome(m, oc, t)
            x["n"] += 1
            x["rules_ok"] += E.act_ok(m, ra, rcm)
            x["base_ok"] += E.act_ok(m, ba, bcm)
            x["cand_ok"] += E.act_ok(m, ca, ccm)
            rw, bw, cw = E.is_wrong(m, ra, rcm), E.is_wrong(m, ba, bcm), E.is_wrong(m, ca, ccm)
            x["rules_wrong"] += rw
            x["base_wrong"] += bw
            x["cand_wrong"] += cw
            x["extra_rules"] += cw and not rw
            x["extra_base"] += cw and not bw
            if cw and not (rw and bw) and len(x["ex"]) < 4:
                x["ex"].append(f"{m['heard']} -> {ca} (gold {m['gold_act']})")
        return x

    res = {"base_policy": bpol, "cand_policy": cpol, "classes": {}, "config": {}}
    print("\n| class | turns | act ok rules / r10 / cand | wrong rules / r10 / cand | extra vs rules / vs r10 | "
          "sets worse | ships |")
    print("|---|---|---|---|---|---|---|")
    passing = []
    for c in E.CLASSES:
        cells = {n: cell(n, c, [c]) for n in sets}
        tot = {k: sum(v[k] for v in cells.values()) for k in ("n", "rules_ok", "base_ok", "cand_ok", "rules_wrong",
                                                                "base_wrong", "cand_wrong", "extra_rules",
                                                                "extra_base")}
        worse = [n for n, v in cells.items() if v["extra_rules"] or v["extra_base"] or v["cand_ok"] < v["rules_ok"]
                 or v["cand_ok"] < v["base_ok"]]
        ok = not worse and tot["cand_ok"] > tot["rules_ok"] and (
            tot["cand_ok"] > tot["base_ok"] or (c in (bpol.get("classes") or []) and tot["cand_ok"] >= tot["base_ok"]))
        if ok:
            passing.append(c)
        res["classes"][c] = {"total": tot, "worse_sets": worse, "pass": ok, "sets": cells}
        ws = ", ".join(f"{n} ({cells[n]['cand_ok'] - max(cells[n]['rules_ok'], cells[n]['base_ok']):+d}, "
                       f"+{max(cells[n]['extra_rules'], cells[n]['extra_base'])} wrong)" for n in worse) or "-"
        print(f"| {c} | {tot['n']} | {tot['rules_ok']} / {tot['base_ok']} / {tot['cand_ok']} | "
              f"{tot['rules_wrong']} / {tot['base_wrong']} / {tot['cand_wrong']} | {tot['extra_rules']} / "
              f"{tot['extra_base']} | {ws} | {'yes' if ok else 'no'} |", flush=True)
    classes = [x for x in a.classes.split(",") if x] if a.classes else passing
    res["config_classes"] = classes
    print(f"\ncandidate config classes {classes} vs the base ({bpol.get('classes')}), every set:")
    print("| set | turns | act ok rules / r10 / cand | wrong rules / r10 / cand | extra vs r10 |")
    print("|---|---|---|---|---|")
    T = {}
    for n in sets:
        v = cell(n, None, classes)
        res["config"][n] = v
        for k in ("n", "rules_ok", "base_ok", "cand_ok", "rules_wrong", "base_wrong", "cand_wrong", "extra_base"):
            T[k] = T.get(k, 0) + v[k]
        print(f"| {n} | {v['n']} | {v['rules_ok']} / {v['base_ok']} / {v['cand_ok']} | {v['rules_wrong']} / "
              f"{v['base_wrong']} / {v['cand_wrong']} | {v['extra_base']} |")
    print(f"| **all** | {T['n']} | {T['rules_ok']} / {T['base_ok']} / {T['cand_ok']} | {T['rules_wrong']} / "
          f"{T['base_wrong']} / {T['cand_wrong']} | {T['extra_base']} |")
    res["config_total"] = T
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
