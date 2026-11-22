"""Round 15: the raw-feature candidate (perception + state only, with the reply / slot heads) against what ships
(round 12's routed config), turn by turn, plus the new heads' accuracy.

  python3 gate_r15.py --data data/ds_r15 --ship backend/app/director_model --cand <r15 run> [--cand-weights DIR]
                      [--policy JSON] [--memo DIR] [--out gate_r15.json] [--report stress_*]

Act configs (each exactly as runtime.Shadow + session.py decide it, through evaluate.guarded_outcome / runtime.pick):
  rules   DIRECTOR_MODEL=shadow: the rules decide everywhere
  ship    what ships (round 12): weights.json (r12 xl, the legacy "full" features) in quiet, weights_r10 in hot + echo
  r15     ship, with ONE class handed to the raw candidate (val-fitted policy; it reads features.raw_feats)
  routed  ship, with every class the candidate passes on its own handed to it
The pass rule is round 13's (gate_r13.py): on EVERY set 0 extra wrong vs the rules and vs ship, act ok >= both, and a
total gain over ship > 0. Round 15 ships NOTHING whatever this says: the raw model runs in shadow only.

New heads (the candidate only; teacher labels: the clean run's engine, r15_labels.py / gen_sessions.py):
  reply    top-1 / top-3 over the reply candidates on turn ends where the engine spoke a matched line; baseline: the
           candidate line nearest the kid's words (cosine of the embedder vectors the raw features carry)
  ent      the entity pointer on labeled turn ends (all; and only those naming a place); baseline: always "none"
  opt      the option pointer where the frame shows options (all; and only those naming one); baseline: always 0
  nav_arg  the navigation argument kind on gold navigate turns; baseline: the majority kind. Full slot: the kind
           right AND, for an option / a site, the pointer right too
  style    the style head vs the line steering chose (teacher), next to r12's own style head
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as E  # noqa: E402
import train as TR  # noqa: E402
from gate_r12 import fit  # noqa: E402
from gate_r13 import NumpyNamed  # noqa: E402
from app.director_model import features as FX, runtime as RT  # noqa: E402

FILES = {"r12": "weights", "r10": "weights_r10", "r15": "weights_r15"}   # the names the runtime routes by
LAB = ("reply", "ent", "opt", "nav_arg", "style")


def _rows(pr, metas, ss):
    out = []
    for p, ms, s in zip(pr, metas, ss):
        for t, m in enumerate(ms):
            if m.get("end") and m.get("gold_act") is not None:
                m = {**m, "_y": {k: int(s[f"y_{k}"][t]) for k in LAB if f"y_{k}" in s}}
                if "feats" in s and s["feats"].shape[1] == FX.F_RAW:
                    e = s["feats"][t, FX._EMB0:FX._EMB0 + FX.EMB_DIM]
                    m["_emb"] = e if float(s["feats"][t, FX._RIDX["emb_avail"]]) > 0 else None
                out.append((m, {k: p[k][t] for k in p}))
    return out


class TorchRaw:
    """A round-15 torch run (feat_set raw, the r15 heads), read on the set's raw features + side labels."""

    def __init__(self, run: str, data: Path):
        cfg = json.load(open(f"{run}/train.json"))
        self.fs = cfg.get("feat_set") or "full"
        self.m = TR.make_from_cfg(cfg, data)
        self.m.load_state_dict(torch.load(f"{run}/model.pt", map_location="cpu"))
        self.m.eval()

    def rows(self, d: Path, name: str):
        ss = TR.load_split(d / f"{name}.npz", self.fs)
        with torch.no_grad():
            pr = TR.predict(self.m, ss)
        return _rows(pr, E.load_meta(d / f"{name}.meta.jsonl"), ss)


class NumpyRaw:
    """The exported weights_r15 file stepped by the numpy runtime (what the app's shadow runs)."""

    def __init__(self, d: str, name: str = "weights_r15"):
        self.m = RT.Model(Path(d), name)
        self.meta = self.m.meta

    def rows(self, d: Path, name: str):
        ss = TR.load_split(d / f"{name}.npz", self.m.feat_set)
        res = []
        for s in ss:
            T = len(s["feats"])
            r: dict = {}
            st = None
            for t in range(T):
                o, st = self.m.step(st, s["feats"][t], s["toks"][t], s["wtok"][t], s["wfeat"][t])
                for k, v in o.items():
                    v = np.asarray(v, np.float32)
                    r.setdefault(k, np.zeros((T,) + v.shape, np.float32))[t] = v
            res.append(r)
        return _rows(res, E.load_meta(d / f"{name}.meta.jsonl"), ss)


def head_metrics(rows, reply_emb: np.ndarray | None) -> dict:
    """The new heads' accuracy on one set's turn ends (the candidate's outputs `o`, the labels in m["_y"])."""
    c = Counter()
    for m, o in rows:
        y = m.get("_y") or {}
        yr = y.get("reply", -1)
        if yr >= 0 and "reply" in o:
            top = np.argsort(-np.asarray(o["reply"]))[:3]
            c["reply_n"] += 1
            c["reply_top1"] += int(top[0] == yr)
            c["reply_top3"] += int(yr in top)
            if reply_emb is not None and m.get("_emb") is not None:
                c["reply_nn_top1"] += int(int(np.argmax(reply_emb @ m["_emb"])) == yr)
                c["reply_nn_top3"] += int(yr in np.argsort(-(reply_emb @ m["_emb"]))[:3])
        ye = y.get("ent", -1)
        if ye >= 0 and "ent" in o:
            pe = int(np.argmax(o["ent"]))
            c["ent_n"] += 1
            c["ent_ok"] += int(pe == ye)
            c["ent_none_base"] += int(ye == 0)
            if ye > 0:
                c["ent_named_n"] += 1
                c["ent_named_ok"] += int(pe == ye)
        yo = y.get("opt", -1)
        if yo >= 0 and "opt" in o:
            po = int(np.argmax(o["opt"]))
            c["opt_n"] += 1
            c["opt_ok"] += int(po == yo)
            c["opt_zero_base"] += int(yo == 0)
            if yo > 0:
                c["opt_named_n"] += 1
                c["opt_named_ok"] += int(po == yo)
        ya = y.get("nav_arg", -1)
        if ya >= 0 and "nav_arg" in o:
            pa = int(np.argmax(o["nav_arg"]))
            c["navarg_n"] += 1
            c["navarg_ok"] += int(pa == ya)
            c[f"navarg_kind_{FX.NAV_ARGS[ya]}"] += 1
            kind = FX.NAV_ARGS[ya]
            full = pa == ya
            if full and kind == "option":
                full = int(np.argmax(o["opt"])) == y.get("opt", -2)
            elif full and kind == "site":
                full = int(np.argmax(o["ent"])) == y.get("ent", -2)
            c["navarg_full_ok"] += int(full)
        ys = y.get("style", -1)
        if ys >= 0 and "style" in o:
            c["style_n"] += 1
            c["style_ok"] += int(int(np.argmax(o["style"])) == ys)
    return dict(c)


def summarize(c: dict) -> dict:
    f = lambda a, b: round(c.get(a, 0) / c[b], 4) if c.get(b) else None  # noqa: E731
    kinds = {k[len("navarg_kind_"):]: v for k, v in c.items() if k.startswith("navarg_kind_")}
    maj = max(kinds.values()) if kinds else 0
    return {"reply": {"n": c.get("reply_n", 0), "top1": f("reply_top1", "reply_n"), "top3": f("reply_top3", "reply_n"),
                      "nearest_line_top1": f("reply_nn_top1", "reply_n"), "nearest_line_top3": f("reply_nn_top3", "reply_n")},
            "ent": {"n": c.get("ent_n", 0), "acc": f("ent_ok", "ent_n"), "always_none": f("ent_none_base", "ent_n"),
                    "named_n": c.get("ent_named_n", 0), "named_acc": f("ent_named_ok", "ent_named_n")},
            "opt": {"n": c.get("opt_n", 0), "acc": f("opt_ok", "opt_n"), "always_none": f("opt_zero_base", "opt_n"),
                    "named_n": c.get("opt_named_n", 0), "named_acc": f("opt_named_ok", "opt_named_n")},
            "nav_arg": {"n": c.get("navarg_n", 0), "kind_acc": f("navarg_ok", "navarg_n"),
                        "majority": round(maj / c["navarg_n"], 4) if c.get("navarg_n") else None,
                        "full_slot_acc": f("navarg_full_ok", "navarg_n"), "kinds": kinds},
            "style": {"n": c.get("style_n", 0), "acc": f("style_ok", "style_n")}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--ship", required=True, help="the shipped weights dir (weights.* = r12, weights_r10.*)")
    ap.add_argument("--cand", default="", help="the round-15 torch run (raw features; policy fit on val)")
    ap.add_argument("--cand-weights", default="", help="the exported weights_r15 dir (numpy runtime, own policy)")
    ap.add_argument("--policy", default="", help="JSON merged over the candidate's fitted policy")
    ap.add_argument("--memo", default="")
    ap.add_argument("--tag", default="r15")
    ap.add_argument("--sets", default="")
    ap.add_argument("--report", default="", help="report-only sets (comma): never gate")
    ap.add_argument("--out", default="")
    ap.add_argument("--policy-out", default="", help="write the candidate's fitted policy here (export.py --policy-json)")
    a = ap.parse_args()
    d = Path(a.data)
    extra = json.loads(a.policy) if a.policy else {}
    models = {"r12": NumpyNamed(a.ship, "weights"), "r10": NumpyNamed(a.ship, "weights_r10")}
    p12 = {**RT.DEFAULT_POLICY, **(models["r12"].meta.get("policy") or {})}
    p10 = {**RT.DEFAULT_POLICY, **(models["r10"].meta.get("policy") or {})}
    pols = {"r12": {k: v for k, v in p12.items() if k not in ("classes", "routes")},
            "r10": {k: v for k, v in p10.items() if k not in ("classes", "routes")}}
    SHIP = {c: "r12" for c in p12.get("classes") or []}
    SHIP.update({c: {v: k for k, v in FILES.items()}[f] for c, f in (p12.get("routes") or {}).items()})
    if a.cand_weights:
        models["r15"] = NumpyRaw(a.cand_weights)
        p15 = {**RT.DEFAULT_POLICY, **(models["r15"].meta.get("policy") or {})}
        pols["r15"] = {k: v for k, v in p15.items() if k not in ("classes", "routes")}
    else:
        models["r15"] = TorchRaw(a.cand, d)
        pols["r15"] = {**{x: v for x, v in fit(models["r15"], d).items() if x != "fit"}, **extra}
    if a.policy_out:
        Path(a.policy_out).write_text(json.dumps(pols["r15"], indent=1))
    print(f"ship: {json.dumps(SHIP)}")
    for k, v in pols.items():
        print(f"policy {k}: {json.dumps(v)}", flush=True)
    sets = [n for n in E.SETS + E.CLASS_SETS if (d / f"{n}.npz").exists()]
    if a.sets:
        sets = [n for n in sets if n in a.sets.split(",")]
    tags = {"r12": "r12ship", "r10": "r10", "r15": a.tag}

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
    rows, cand_rows = {}, {}
    for n in sets + report:
        rs = {k: rows_of(k, n) for k in models}
        L = {len(v) for v in rs.values()}
        assert len(L) == 1, (n, L)
        cand_rows[n] = rs["r15"]
        rows[n] = [(rs["r12"][i][0], {k: rs[k][i][1] for k in rs}) for i in range(L.pop())]
        print("rows", n, len(rows[n]), flush=True)

    def outcome(m, os_, owners: dict | None):
        if owners is None:
            return E.rules_out(m)
        thr = {**pols["r12"], "classes": [c for c, k in owners.items() if k == "r12"],
               "routes": {c: FILES[k] for c, k in owners.items() if k != "r12"}}
        o = {**os_["r12"], "_routed": {FILES[k]: os_[k] for k in ("r10", "r15")}}
        return E.guarded_outcome(m, o, thr, {FILES[k]: pols[k] for k in ("r10", "r15")})

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

    res = {"policies": pols, "ship": SHIP, "classes": {}, "routed": {}, "shadow_only": True}
    print("\n| class | turns | act ok rules / ship / r15 | wrong rules / ship / r15 | sets worse | r15 passes |")
    print("|---|---|---|---|---|---|")
    passing = []
    for c in E.CLASSES:
        per = {n: {"rules": cell(n, c, None), "ship": cell(n, c, SHIP), "r15": cell(n, c, {**SHIP, c: "r15"})}
               for n in sets}
        tot = {k: {f: sum(per[n][k][f] for n in sets) for f in ("n", "ok", "wrong", "extra_rules", "extra_ship")}
               for k in per[sets[0]]}
        if c in RT.SITUATIONS:
            worse = [n for n in sets if per[n]["r15"]["extra_rules"] or per[n]["r15"]["extra_ship"]
                     or per[n]["r15"]["ok"] < per[n]["rules"]["ok"] or per[n]["r15"]["ok"] < per[n]["ship"]["ok"]]
        else:
            worse = [n for n in sets if per[n]["r15"]["extra_ship"] or per[n]["r15"]["ok"] < per[n]["ship"]["ok"]
                     or per[n]["r15"]["extra_rules"] > per[n]["ship"]["extra_rules"]]
        ok = not worse and tot["r15"]["ok"] > tot["ship"]["ok"]
        if ok:
            passing.append(c)
        res["classes"][c] = {"total": tot, "worse": worse, "pass": ok, "sets": per}
        ws = ", ".join(f"{n} ({per[n]['r15']['ok'] - max(per[n]['rules']['ok'], per[n]['ship']['ok']):+d} ok, "
                       f"+{max(per[n]['r15']['extra_rules'], per[n]['r15']['extra_ship'])} wrong)" for n in worse) or "none"
        print(f"| {c} | {tot['rules']['n']} | {tot['rules']['ok']} / {tot['ship']['ok']} / {tot['r15']['ok']} | "
              f"{tot['rules']['wrong']} / {tot['ship']['wrong']} / {tot['r15']['wrong']} | {ws} | "
              f"{'yes' if ok else 'no'} |", flush=True)
    owners = {**SHIP, **{c: "r15" for c in passing}}
    res["route_classes"], res["owners"] = passing, owners
    print(f"\nrouted (hypothetical: round 15 routes nothing): {json.dumps(owners)}; vs ship:")
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
    res["routed_total"], res["routed_worse_sets"] = T, bad
    # the candidate's act head alone (argmax, no policy, no guard): how far perception alone gets vs the rules / r12
    print("\nact head alone (argmax vs gold): rules / r12 xl / r15 raw")
    alone = {}
    for n in sets:
        k = Counter()
        for m, os_ in rows[n]:
            k["n"] += 1
            k["rules"] += m["rules_act"] == m["gold_act"]
            k["r12"] += FX.ACTS[int(np.argmax(os_["r12"]["act"]))] == m["gold_act"]
            k["r15"] += FX.ACTS[int(np.argmax(os_["r15"]["act"]))] == m["gold_act"]
        alone[n] = dict(k)
    tot = Counter()
    for v in alone.values():
        tot.update(v)
    alone["all"] = dict(tot)
    print(f"all {tot['n']}: rules {tot['rules']} / r12 {tot['r12']} / r15 {tot['r15']}")
    res["act_alone"] = alone
    # new heads
    cz = d / "r15_cands.npz"
    remb = np.load(cz)["reply_emb"] if cz.exists() else None
    heads, all_c = {}, Counter()
    for n in sets + report:
        c = head_metrics(cand_rows[n], remb)
        heads[n] = summarize(c)
        if n in sets:
            all_c.update(c)
    heads["all"] = summarize(dict(all_c))
    # r12's own style head next to the candidate's (the same turns, the same teacher label)
    sc = Counter()
    for n in sets:
        for (m, os_), (m2, _) in zip(rows[n], cand_rows[n]):
            ys = (m2.get("_y") or {}).get("style", -1)
            if ys >= 0:
                sc["n"] += 1
                sc["r12"] += int(np.argmax(os_["r12"]["style"])) == ys
    heads["all"]["style"]["r12_acc"] = round(sc["r12"] / sc["n"], 4) if sc["n"] else None
    res["heads"] = heads
    print("\nnew heads (all gated sets):", json.dumps(heads["all"], indent=1))
    if report:
        res["report"] = {n: {"rules": cell(n, None, None), "ship": cell(n, None, SHIP)} for n in report}
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()
