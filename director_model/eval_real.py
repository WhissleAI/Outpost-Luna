"""The class gate on REAL turns: the shipped routed Director config vs the rules, on an imported turn log or playtest.

    make director-eval-real LOG=path/to/turnlog-or-playtest.zip [EVAL_OUT=runs/real/eval_real.json]
    python3 director_model/eval_real.py --log <folder | .jsonl | .zip> [--min-conf 0.6] [--out file.json]

No model is re-run: a turn log v2 line (backend/app/turnlog.py, 0.4.3) carries what the app decided live, per path:
the rules' act (`director.rules`; estimated from the parse and flagged `rules_est` when the model overrode and the
rules never ran), the final act the shipped config took (`director.final`), the situation class the runtime put the
turn in (`seen.cls`: hot / short / echo / video / quiet) and which weight file each path consulted (`director.picked`).
Gold is import_logs.weak_label (the outcome signals) at >= --min-conf, or a reviewed label (data/review/reviewed.jsonl).

Per class (the situation classes, plus `nav`: the turns where a model could navigate in place of the router, and
`answer`: the router's lesson answers a model could silence), and `all`: turns, act ok and wrong actions for the rules
and for the shipped config, and the extra wrong actions (the shipped config wrong where the rules were not).
Wrong action = an executed command / confirm / cancel the gold does not have, or a navigation the gold is not.
v1 lines (before 0.4.3) have no class: they count under `unknown` (and `all`).

The table says which weights and mode decided the turns, and warns when that differs from the weights in
backend/app/director_model now (the turns then measure the config that was live, not this checkout's).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import import_logs as IL  # noqa: E402

EXEC = ("command", "confirm_yes", "confirm_no")
CLASSES = ("hot", "short", "echo", "video", "quiet", "unknown", "nav", "answer")
WEIGHTS = HERE.parent / "backend" / "app" / "director_model"


def shipped_config(d: Path = WEIGHTS) -> dict:
    """The weights in this checkout: {"weights": "<data>/<size>", "classes": [...], "routes": {class: file}}."""
    try:
        m = json.loads((d / "weights.json").read_text())
    except (OSError, ValueError):
        return {}
    pol = m.get("policy") or {}
    return {"weights": f"{m.get('data') or '?'}/{m.get('size_name') or '?'}", "classes": pol.get("classes") or [],
            "routes": pol.get("routes") or {}}


def wrong(act: str | None, gold: str, nav: str | None = None, gold_nav: str | None = None) -> bool:
    """A wrong action. A navigation is wrong when the gold is not a navigation, or (a labeller named which one,
    label_ui) when it went somewhere else."""
    if act == "navigate":
        return gold != "navigate" or bool(gold_nav and nav and nav != gold_nav)
    return act in EXEC and act != gold


def ok(act: str | None, gold: str, nav: str | None = None, gold_nav: str | None = None) -> bool:
    return act == gold and not (act == "navigate" and gold_nav and nav and nav != gold_nav)


def nav_of(t: dict) -> str | None:
    """Which navigation the app ran for a turn: the reply's nav decision (adult collection), else the router's
    intent (or the model's, `navigate:<intent>`)."""
    rep = (t.get("reply") or {}).get("nav") if isinstance(t.get("reply"), dict) else None
    if isinstance(rep, dict) and rep.get("intent"):
        return rep["intent"]
    rt = t.get("router") or {}
    m = rt.get("model")
    if isinstance(m, str) and m.startswith("navigate:"):
        return m.split(":", 1)[1]
    return rt.get("intent") if rt.get("outcome") == "navigate" else None


def rows_of(files: list, min_conf: float = 0.6, reviewed: dict | None = None) -> list[dict]:
    """Per decided, non-private turn with a gold act: {id, cls, classes, gold, conf, rules, final, est, mode, weights}."""
    turns, sigs = IL.read(files)
    by_id = {t["id"]: t for t in turns}
    for t in turns:
        t["_sigs"] = sigs.get(t["id"], [])
    full = IL.load_reviewed_full() if reviewed is None else {k: {"fix": v} for k, v in reviewed.items()}
    reviewed = {k: r["fix"] for k, r in full.items()}
    out = []
    for t in turns:
        if t.get("guard") or not t.get("text") or "<" in (t.get("text") or ""):
            continue
        d = t.get("director") or {}
        final = IL.final_act(t)
        if final is None:
            continue
        gold_nav = None
        if t["id"] in reviewed:
            if reviewed[t["id"]] == "skip":
                continue
            gold, conf = reviewed[t["id"]], 1.0
            gold_nav = full[t["id"]].get("nav") if gold == "navigate" else None
        else:
            gold, conf, _ = IL.weak_label(t, t["_sigs"], by_id)
            if gold is None or conf < min_conf:
                continue
        rules = d.get("rules") or final
        rules = IL.ACT_OF_FINAL.get(rules, rules)
        cls = (t.get("seen") or {}).get("cls") or "unknown"
        route = (t.get("router") or {}).get("outcome")
        classes = [cls, "all"]
        if route != "navigate":
            classes.append("nav")
        if route == "answer":
            classes.append("answer")
        out.append({"id": t["id"], "cls": cls, "classes": classes, "gold": gold, "conf": conf, "rules": rules,
                    "final": final, "est": bool(d.get("rules_est")), "mode": d.get("mode"), "weights": d.get("weights"),
                    "text": t["text"], "nav": nav_of(t) if final == "navigate" else None, "gold_nav": gold_nav,
                    "rules_nav": (t.get("router") or {}).get("intent") if rules == "navigate" else None})
    return out


def gate(rows: list[dict]) -> dict:
    res: dict = defaultdict(lambda: {"n": 0, "rules_ok": 0, "ship_ok": 0, "rules_wrong": 0, "ship_wrong": 0,
                                     "extra": 0, "est": 0, "ex": []})
    for r in rows:
        gn = r.get("gold_nav")
        rw, sw = wrong(r["rules"], r["gold"], r.get("rules_nav"), gn), wrong(r["final"], r["gold"], r.get("nav"), gn)
        for c in r["classes"]:
            x = res[c]
            x["n"] += 1
            x["rules_ok"] += ok(r["rules"], r["gold"], r.get("rules_nav"), gn)
            x["ship_ok"] += ok(r["final"], r["gold"], r.get("nav"), gn)
            x["rules_wrong"] += rw
            x["ship_wrong"] += sw
            x["est"] += r["est"]
            if sw and not rw:
                x["extra"] += 1
                if len(x["ex"]) < 3:
                    x["ex"].append(f"{r['text'][:50]} -> {r['final']} (gold {r['gold']})")
    for x in res.values():
        x["pass"] = x["extra"] == 0 and x["ship_ok"] >= x["rules_ok"]
    return dict(res)


def table(res: dict, rows: list[dict], cfg: dict) -> str:
    live = Counter((r["mode"] or "?", r["weights"] or "?") for r in rows)
    lines = [f"Real turns: {len(rows)} with a gold act. Decided live by: "
             + ", ".join(f"{w} ({m}) x{n}" for (m, w), n in live.most_common()) + "."]
    if cfg:
        lines.append(f"Shipped in this checkout: {cfg['weights']}, acts in {cfg['classes'] or 'no class'}, routes "
                     f"{cfg['routes'] or 'none'}.")
        if any(w not in ("?", cfg["weights"]) for (_, w) in live):
            lines.append("WARNING: some turns were decided by other weights than this checkout ships.")
    lines += ["", "| class | turns | rules ok (wrong) | shipped ok (wrong) | extra wrong | ok |",
              "|---|---|---|---|---|---|"]
    for c in (*CLASSES, "all"):
        x = res.get(c)
        if not x or not x["n"]:
            continue
        est = f" ({x['est']} est.)" if x["est"] else ""
        lines.append(f"| {c} | {x['n']} | {x['rules_ok']} ({x['rules_wrong']}){est} | {x['ship_ok']} ({x['ship_wrong']}) | "
                     f"{x['extra']} | {'yes' if x['pass'] else 'NO'} |")
    ex = [f"- {c}: {e}" for c in (*CLASSES, "all") if c in res for e in res[c]["ex"]]
    if ex:
        lines += ["", "Extra wrong actions (shipped wrong where the rules were right):", *ex]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", action="append", required=True)
    ap.add_argument("--min-conf", type=float, default=IL.REVIEW_MIN)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    fs = IL.files_of(a.log)
    if not fs:
        raise SystemExit(f"no turn logs in {a.log}")
    rows = rows_of(fs, a.min_conf)
    res = gate(rows)
    cfg = shipped_config()
    print(table(res, rows, cfg))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps({"config": cfg, "turns": len(rows), "classes": res}, indent=1))
    return res


if __name__ == "__main__":
    main()
