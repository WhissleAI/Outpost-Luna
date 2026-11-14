"""Model vs rules on the held-out sets (gen_sessions.py): act accuracy, command exact match, wrong actions per 50
commands, card+attribute accuracy, end-of-turn latency / premature answers, barge precision/recall, clean vs ASR,
per-category breakdown.

  python3 evaluate.py --data data/ds_r1 --run runs/r1_m [--out runs/r1_m/eval.json]

Definitions
  act acc          turn ends with a gold act: argmax act == gold (rules: the act the rule Director took on the heard
                   words; Academy: the grader on the heard words).
  cmd exact        gold act command with a gold Command: decoded Command == gold (type + slots; features.same_command)
                   AND the act is command.
  wrong / 50 cmd   executed side effects the kid did not intend (act command/confirm with a different act or Command
                   in gold), per 50 gold command turns.
  h40              brain's 40 held-out commands: correct = type (+ to + sign of the amount / task) as `expect`.
  attr / card+attr turns with a gold attribute; the entity is the linker's (rules) for both, so card+attr differs
                   only by the attribute.
  eot              per spoken turn: the first step with p(when) >= thr (thr from val: premature <= 5%); premature =
                   fired on words that are not the final words; gain = turn end - fire time (s). Rules answer at the
                   turn end (gain 0, premature 0).
  barge            steps where guide/crew audio was playing and the kid spoke: p(barge) >= .5 vs gold; rules = the
                   Session's own barge-in at that step.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import train as TR  # noqa: E402
from train import FX  # noqa: E402

SETS = ["test_clean", "test_asr", "test_ear", "test_h40", "test_h40_asr", "test_q80", "test_q80_asr", "test_gold"]
EXEC = ("command", "confirm_yes", "confirm_no")


def load_meta(p: Path) -> list[list[dict]]:
    by = defaultdict(list)
    for line in open(p):
        m = json.loads(line)
        by[m["sess"]].append(m)
    return [by[i] for i in sorted(by)]


def h40_ok(c: dict | None, expect: dict) -> bool:
    if not c or c.get("type") != expect.get("type"):
        return False
    body = c
    for k in ("to", "task", "what", "on"):
        if k in expect and body.get(k) != expect[k]:
            return False
    if "sign" in expect and c.get("type") == "allocate":
        v = (c.get("amount") or {}).get("value") or 0
        k = (c.get("amount") or {}).get("kind")
        s = 1 if (k in ("all",) or (k in ("delta", "little") and v > 0) or k == "percent" and v >= 50 or k == "half") else -1
        if k == "none":
            s = -1
        if s != expect["sign"]:
            return False
    return True


def tune_when(model, data_dir: Path, target=0.05) -> float:
    ss = TR.load_split(data_dir / "val.npz")
    pr = TR.predict(model, ss)
    best = 0.99
    for thr in np.arange(0.5, 0.99, 0.02):
        pre, n = 0, 0
        for s, p in zip(ss, pr):
            y = s["y_when"]
            m = y >= 0
            fired = (p["when"] >= thr) & m
            n += int(m.sum() and (y[m] == 1).any())
            pre += int(((fired) & (y == 0)).any())
        if n and pre / n <= target:
            best = float(thr)
            break
    return best


def evaluate_set(model, data_dir: Path, name: str, thr_when: float) -> dict | None:
    if not (data_dir / f"{name}.npz").exists():
        return None
    ss = TR.load_split(data_dir / f"{name}.npz")
    metas = load_meta(data_dir / f"{name}.meta.jsonl")
    pr = TR.predict(model, ss)
    R = {"model": Counter(), "rules": Counter()}
    cats = defaultdict(lambda: Counter())
    errs = Counter()
    examples = defaultdict(list)
    eot = {"turns": 0, "fired": 0, "premature": 0, "gain": []}
    barge = {"model": Counter(), "rules": Counter()}
    shadow = Counter()
    for s, p, ms in zip(ss, pr, metas):
        T = len(s["feats"])
        assert len(ms) == T, (name, len(ms), T)
        # end of turn: per tid, steps in order
        by_tid = defaultdict(list)
        for t, m in enumerate(ms):
            if m.get("tid") is not None and s["y_when"][t] >= 0:
                by_tid[m["tid"]].append(t)
        for tid, idx in by_tid.items():
            ends = [t for t in idx if ms[t].get("end")]
            if not ends or ms[ends[0]]["kind"] == "typed":
                continue
            eot["turns"] += 1
            fire = next((t for t in idx if p["when"][t] >= thr_when), None)
            if fire is not None:
                eot["fired"] += 1
                if s["y_when"][fire] == 0:
                    eot["premature"] += 1
                else:
                    eot["gain"].append(max(0.0, (ms[ends[0]]["now"] - ms[fire]["now"])))
        for t, m in enumerate(ms):
            yb = s["y_barge"][t]
            if yb >= 0:
                pm = int(p["barge"][t] >= 0.5)
                pr_ = int(bool(m.get("rules_barge")))
                for who, v in (("model", pm), ("rules", pr_)):
                    barge[who]["tp" if v and yb else "fp" if v else "fn" if yb else "tn"] += 1
            ma = FX.ACTS[int(np.argmax(p["act"][t]))]
            if m["rules_act"] != "wait" or ma != "wait":
                shadow["n"] += 1
                shadow["agree"] += int(ma == m["rules_act"])
            if not m.get("end") or m.get("gold_act") is None:
                continue
            g, ra = m["gold_act"], m["rules_act"]
            words = FX.words_of(m["heard"])
            o = {k: p[k][t] for k in p}
            mc = FX.decode_command(o, words) if ma == "command" else None
            rc = m.get("rules_cmd") if ra == "command" else None
            gc = m.get("gold_cmd")
            cat = m.get("cat") or "?"
            for who, a, c in (("model", ma, mc), ("rules", ra, rc)):
                Rw = R[who]
                Rw["turns"] += 1
                Rw["act_ok"] += int(a == g)
                cats[(cat, who)]["n"] += 1
                cats[(cat, who)]["ok"] += int(a == g)
                if g == "command" and gc:
                    Rw["cmds"] += 1
                    Rw["cmd_exact"] += int(a == "command" and FX.same_command(c, gc))
                if a in EXEC and not (a == g and (a != "command" or (gc and FX.same_command(c, gc)))):
                    Rw["wrong_actions"] += 1
                if m.get("expect"):
                    Rw["h40_n"] += 1
                    Rw["h40_ok"] += int(a == "command" and h40_ok(c, m["expect"]))
                    Rw["h40_wrong"] += int(a == "command" and not h40_ok(c, m["expect"]))
                    Rw["h40_none"] += int(a != "command")
                ga = m.get("gold_attr")
                if ga or m.get("ok"):
                    if who == "model":
                        pa = FX.ATTRS[int(np.argmax(p["card_attr"][t][1:])) + 1]
                    else:
                        pa = m.get("rules_attr")
                    card = m.get("rules_card") or (f"place:{m['rules_place']}" if m.get("rules_place") else None)
                    if ga:
                        Rw["attr_n"] += 1
                        Rw["attr_ok"] += int(pa == ga)
                    if m.get("ok"):
                        Rw["ca_n"] += 1
                        if m["ok"] == ["unknown"]:
                            Rw["ca_ok"] += int(a == "answer" and not card)
                        else:
                            Rw["ca_ok"] += int(f"{card}|{pa}" in m["ok"])
                if who == "model" and a != g:
                    errs[(cat, g, a)] += 1
                    if len(examples[(cat, g, a)]) < 3:
                        examples[(cat, g, a)].append(m["heard"])
    out = {"set": name, "sessions": len(ss), "steps": int(sum(len(s["feats"]) for s in ss))}
    for who in ("model", "rules"):
        Rw = R[who]
        n = Rw["turns"] or 1
        out[who] = {
            "turns": Rw["turns"], "act_acc": round(Rw["act_ok"] / n, 4),
            "cmd_exact": round(Rw["cmd_exact"] / Rw["cmds"], 4) if Rw["cmds"] else None, "cmds": Rw["cmds"],
            "wrong_per_50": round(50 * Rw["wrong_actions"] / Rw["cmds"], 2) if Rw["cmds"] else None,
            "wrong_actions": Rw["wrong_actions"],
            "attr_acc": round(Rw["attr_ok"] / Rw["attr_n"], 4) if Rw["attr_n"] else None,
            "card_attr_acc": round(Rw["ca_ok"] / Rw["ca_n"], 4) if Rw["ca_n"] else None,
            "h40": f"{Rw['h40_ok']}/{Rw['h40_n']} ok, {Rw['h40_wrong']} wrong, {Rw['h40_none']} none" if Rw["h40_n"] else None,
        }
        b = barge[who]
        out[who]["barge_p"] = round(b["tp"] / (b["tp"] + b["fp"]), 3) if b["tp"] + b["fp"] else None
        out[who]["barge_r"] = round(b["tp"] / (b["tp"] + b["fn"]), 3) if b["tp"] + b["fn"] else None
    out["eot"] = {"turns": eot["turns"], "fire_rate": round(eot["fired"] / max(1, eot["turns"]), 3),
                  "premature": round(eot["premature"] / max(1, eot["turns"]), 3),
                  "gain_ms_p50": round(1000 * float(np.median(eot["gain"])), 0) if eot["gain"] else None}
    out["shadow_agreement"] = round(shadow["agree"] / shadow["n"], 4) if shadow["n"] else None
    out["by_cat"] = {c: {who: f"{cats[(c, who)]['ok']}/{cats[(c, who)]['n']}" for who in ("model", "rules")}
                     for c in sorted({c for c, _ in cats})}
    out["top_errors"] = [{"cat": k[0], "gold": k[1], "model": k[2], "n": v, "ex": examples[k]}
                         for k, v in errs.most_common(12)]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    cfg = json.load(open(f"{a.run}/train.json"))
    model = TR.make(cfg["F"], cfg["size_name"])
    model.load_state_dict(torch.load(f"{a.run}/model.pt", map_location="cpu"))
    model.eval()
    d = Path(a.data)
    thr = tune_when(model, d)
    res = {"run": a.run, "params": cfg["params"], "size": cfg["size_name"], "thr_when": thr, "sets": {}}
    for name in SETS:
        r = evaluate_set(model, d, name, thr)
        if r:
            res["sets"][name] = r
    out = Path(a.out or f"{a.run}/eval.json")
    out.write_text(json.dumps(res, indent=1))
    print(f"| set | turns | act acc M / R | cmd exact M / R | wrong/50 M / R | attr M / R | card+attr M / R | "
          f"eot premature, gain p50 | barge P/R M ; R | shadow agree |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name, r in res["sets"].items():
        M, Rr = r["model"], r["rules"]

        def f(k):
            return f"{M[k]} / {Rr[k]}"
        print(f"| {name} | {M['turns']} | {f('act_acc')} | {f('cmd_exact')} | {f('wrong_per_50')} | {f('attr_acc')} | "
              f"{f('card_attr_acc')} | {r['eot']['premature']}, {r['eot']['gain_ms_p50']} ms | "
              f"{M['barge_p']}/{M['barge_r']} ; {Rr['barge_p']}/{Rr['barge_r']} | {r['shadow_agreement']} |")
    for name in ("test_h40", "test_h40_asr"):
        if name in res["sets"]:
            print(name, "model:", res["sets"][name]["model"]["h40"], "| rules:", res["sets"][name]["rules"]["h40"])
    for name in ("test_asr", "test_ear", "test_q80"):
        if name in res["sets"]:
            print(f"top errors {name}:", json.dumps(res["sets"][name]["top_errors"][:8]))


if __name__ == "__main__":
    main()
