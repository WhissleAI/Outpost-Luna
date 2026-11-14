"""The Director's continuous-improvement loop (docs/DIRECTOR_LOOP.md): the steps `make director-loop` runs around the
existing pipeline (import -> generate -> train -> evaluate -> GATE -> export), plus the dated report.

  python3 director_model/loop.py preflight [--min-free-gb 3] [--max-cache-gb 1]
  python3 director_model/loop.py gate --run director_model/runs/<date> --data director_model/data/ds [--export]

gate reads <run>/eval_candidate.json (the new model, thresholds fit on val) and <run>/eval_shipped.json (the weights in
backend/app/director_model, stepped by the numpy runtime with their own policy: what the app runs today) and ships
the candidate only if, on EVERY held-out set:
  1. guarded `on` wrong actions <= the rules (RETRAIN.md switch-on criterion; wrong/50 on the command sets)
  2. guarded `on` act accuracy >= the rules
  3. the privacy guard: `on` takes every guard turn the rules take (guard rows unchanged)
  4. no class regresses: on the round-6 class sets (cls_*, test_log) `on` act accuracy >= the shipped weights' and
     wrong actions <= theirs
  5. worth shipping: summed over every set, no more wrong actions and no fewer right acts than the shipped weights
Otherwise the shipped weights stay. Either way <run>/report.md has the before / after table and the reasons.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
WEIGHTS = ROOT / "backend" / "app" / "director_model"
HELD_OUT = ["test_clean", "test_asr", "test_real", "test_ear", "test_h40", "test_h40_asr", "test_q80", "test_q80_asr",
            "test_gold"]
CLASS_SETS = ["cls_chatter", "cls_echo", "cls_offer", "cls_panel", "cls_help", "cls_mode", "cls_globe", "cls_mishear",
              "cls_roomtalk", "test_log"]
CACHE_DIRS = [HERE / "data", HERE / "cache", HERE / "runs"]


def du(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def free_bytes(p: Path = ROOT) -> int:
    return shutil.disk_usage(p).free


def preflight(min_free_gb: float, max_cache_gb: float) -> dict:
    free, cache = free_bytes(), sum(du(d) for d in CACHE_DIRS)
    r = {"free_gb": round(free / 1e9, 2), "cache_gb": round(cache / 1e9, 3), "min_free_gb": min_free_gb,
         "max_cache_gb": max_cache_gb}
    print(json.dumps(r))
    if free < min_free_gb * 1e9:
        raise SystemExit(f"STOP: {r['free_gb']} GB free < {min_free_gb} GB (shared disk)")
    if cache > max_cache_gb * 1e9:
        raise SystemExit(f"STOP: training cache {r['cache_gb']} GB > {max_cache_gb} GB (prune director_model/runs or "
                         f"data/ds_*)")
    return r


def _f(x, nd=3):
    return "–" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def check(cand: dict, ship: dict) -> tuple[bool, list[str], list[dict]]:
    ok, why, rows = True, [], []
    cs, ss = cand["sets"], ship["sets"]
    for name in HELD_OUT + CLASS_SETS:
        if name not in cs:
            continue
        C, R = cs[name]["on"], cs[name]["rules"]
        S = (ss.get(name) or {}).get("on")
        row = {"set": name, "turns": C["turns"], "rules_act": R["act_acc"], "ship_act": S and S["act_acc"],
               "cand_act": C["act_acc"], "rules_wrong": R["wrong_actions"], "ship_wrong": S and S["wrong_actions"],
               "cand_wrong": C["wrong_actions"], "rules_w50": R["wrong_per_50"], "ship_w50": S and S["wrong_per_50"],
               "cand_w50": C["wrong_per_50"], "model_act": cs[name]["model"]["act_acc"],
               "chatter_graded": (R.get("chatter_graded"), S and S.get("chatter_graded"), C.get("chatter_graded")),
               "fail": []}
        if C["wrong_actions"] > R["wrong_actions"]:
            row["fail"].append(f"wrong actions {C['wrong_actions']} > rules {R['wrong_actions']}")
        if C["act_acc"] + 1e-9 < R["act_acc"]:
            row["fail"].append(f"act acc {C['act_acc']} < rules {R['act_acc']}")
        if C.get("guard") != R.get("guard"):
            row["fail"].append(f"guard {C.get('guard')} != rules {R.get('guard')}")
        if name in CLASS_SETS and S is not None:
            if C["act_acc"] + 1e-9 < S["act_acc"]:
                row["fail"].append(f"class regresses: act acc {C['act_acc']} < shipped {S['act_acc']}")
            if C["wrong_actions"] > S["wrong_actions"]:
                row["fail"].append(f"class regresses: wrong {C['wrong_actions']} > shipped {S['wrong_actions']}")
        if row["fail"]:
            ok = False
            why += [f"{name}: {x}" for x in row["fail"]]
        rows.append(row)
    if not any(r["set"] in HELD_OUT for r in rows):
        ok = False
        why.append("no held-out set evaluated")
    # 5. worth shipping: over all sets together, no more wrong actions and no fewer right acts than the shipped weights
    both = [r for r in rows if r["ship_act"] is not None]
    if both:
        cw, sw = sum(r["cand_wrong"] for r in both), sum(r["ship_wrong"] for r in both)
        ca = sum(r["cand_act"] * r["turns"] for r in both)
        sa = sum(r["ship_act"] * r["turns"] for r in both)
        if cw > sw or ca + 1e-6 < sa:
            ok = False
            why.append(f"not better than the shipped weights overall: wrong {cw} vs {sw}, right acts {ca:.0f} vs {sa:.0f}")
    return ok, why, rows


def table(rows: list[dict]) -> str:
    out = ["| set | turns | act acc rules / shipped on / **new on** | wrong actions rules / shipped / **new** | "
           "wrong/50 rules / shipped / **new** | raw new model act | gate |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['set']} | {r['turns']} | {_f(r['rules_act'])} / {_f(r['ship_act'])} / **{_f(r['cand_act'])}** | "
                   f"{r['rules_wrong']} / {_f(r['ship_wrong'])} / **{r['cand_wrong']}** | {_f(r['rules_w50'], 1)} / "
                   f"{_f(r['ship_w50'], 1)} / **{_f(r['cand_w50'], 1)}** | {_f(r['model_act'])} | "
                   f"{'ok' if not r['fail'] else 'FAIL'} |")
    return "\n".join(out)


def gate(run: Path, data: Path, export: bool) -> dict:
    cand = json.loads((run / "eval_candidate.json").read_text())
    ship = json.loads((run / "eval_shipped.json").read_text())
    ok, why, rows = check(cand, ship)
    res = {"date": dt.datetime.now().isoformat(timespec="minutes"), "run": str(run), "data": str(data), "pass": ok,
           "reasons": why, "policy": cand.get("policy"), "shipped_policy": ship.get("policy"), "rows": rows}
    exported = False
    if ok and export:
        bk = run / "weights_before"
        bk.mkdir(exist_ok=True)
        for f in ("weights.npz", "weights.json"):
            shutil.copy2(WEIGHTS / f, bk / f)
        subprocess.run([sys.executable, str(HERE / "export.py"), "--run", str(run / "cand"), "--data", str(data),
                        "--eval", str(run / "eval_candidate.json")], check=True)
        exported = True
    res["exported"] = exported
    (run / "gate.json").write_text(json.dumps(res, indent=1))
    pol = cand.get("policy") or {}
    md = [f"# Director loop {run.name}", "",
          f"Data `{data}`; candidate `{run / 'cand'}`; shipped = `backend/app/director_model/weights.*` before this run.",
          "", "**Gate: " + ("PASS — new weights exported" if ok and exported else "PASS (not exported: --export off)"
                            if ok else "FAIL — the shipped weights stay") + "**", ""]
    if why:
        md += ["Reasons:", *[f"- {x}" for x in why], ""]
    md += [f"Fitted policy: `{json.dumps({k: v for k, v in pol.items() if k != 'fit'})}`", "", table(rows), "",
           "Chatter graded as a lesson answer (rules / shipped / new): " +
           ", ".join(f"{r['set']} {r['chatter_graded']}" for r in rows if any(r["chatter_graded"] or ())), ""]
    (run / "report.md").write_text("\n".join(md))
    print("\n".join(md))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["preflight", "gate", "today"])
    ap.add_argument("--run", default="")
    ap.add_argument("--data", default=str(HERE / "data" / "ds"))
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--min-free-gb", type=float, default=3.0)
    ap.add_argument("--max-cache-gb", type=float, default=1.0)
    a = ap.parse_args()
    if a.cmd == "preflight":
        preflight(a.min_free_gb, a.max_cache_gb)
    elif a.cmd == "today":
        print(dt.date.today().isoformat())
    else:
        r = gate(Path(a.run), Path(a.data), a.export)
        raise SystemExit(0 if r["pass"] else 3)


if __name__ == "__main__":
    main()
