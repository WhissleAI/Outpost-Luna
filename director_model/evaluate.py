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
  navigate (r7)    a navigate act is right only with the right intent (gold = the router on the CLEAN words in the
                   screen frame; taking the offer is one class); a navigation the kid did not mean is a wrong action
                   (counted in wrong_actions, like an executed command), for the rules and the model alike.
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
from app.director_model import runtime as RT  # noqa: E402
from app.mission import nlu  # noqa: E402

_PARSE: dict = {}


def rules_cmds(heard: str) -> list[dict]:
    """What runtime.decide_turn sees: the deterministic parse of the heard words (valid commands)."""
    if heard not in _PARSE:
        _PARSE[heard] = [c for c in map(nlu.valid, nlu.parse(heard).get("commands") or []) if c]
    return _PARSE[heard]


def guard_of(m: dict) -> bool:
    return m["rules_act"] == "guard"

SETS = ["test_clean", "test_asr", "test_real", "test_ear", "test_h40", "test_h40_asr", "test_q80", "test_q80_asr",
        "test_gold",
        # round 11: test_real's sessions in Mac voices never used in train / val (voice_bank.HELDOUT)
        "test_voice_heldout"]
# round 6: today's real failure classes (gen_sessions.py cls_set; pools.CLASSES) and the imported real turns
CLASS_SETS = ["cls_chatter", "cls_echo", "cls_offer", "cls_panel", "cls_help", "cls_mode", "cls_globe", "cls_mishear",
              "cls_roomtalk", "test_log",
              # round 8 (pools_r8.py): the capabilities added since round 7
              "cls_video_ctrl", "cls_video_echo", "cls_prep", "cls_prep_roomtalk", "cls_voice_echo_os",
              "cls_gesture_cooccur", "cls_lesson_new", "cls_offers_new", "cls_coverage", "cls_coverage_pending"]


class NumpyModel:
    """The SHIPPED weights (backend/app/director_model/weights.*) stepped by the numpy runtime, one event at a time:
    exactly what the app runs, so the before column of a round is the live Director, not a re-trained copy."""

    def __init__(self, d: Path):
        self.m = RT.Model(Path(d))
        self.meta = self.m.meta


def predict_any(model, ss):
    if not isinstance(model, NumpyModel):
        return TR.predict(model, ss)
    m = model.m
    res = []
    for s in ss:
        T = len(s["feats"])
        r: dict = {}
        st = None
        for t in range(T):
            o, st = m.step(st, s["feats"][t], s["toks"][t], s["wtok"][t], s["wfeat"][t])
            for k, v in o.items():
                v = np.asarray(v, np.float32)
                if k == "act" and v.shape[0] < len(FX.ACTS):      # an older model: no `navigate` act
                    v = np.concatenate([v, np.zeros(len(FX.ACTS) - v.shape[0], np.float32)])
                r.setdefault(k, np.zeros((T,) + v.shape, np.float32))[t] = v
        res.append(r)
    return res
EXEC = ("command", "confirm_yes", "confirm_no")
CONF = 0.7          # runtime.CONF


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
    pr = predict_any(model, ss)
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


def turn_rows(model, data_dir: Path, name: str):
    """Per turn end with a gold act: (meta, model outputs at that step)."""
    ss = TR.load_split(data_dir / f"{name}.npz")
    metas = load_meta(data_dir / f"{name}.meta.jsonl")
    pr = predict_any(model, ss)
    out = []
    for p, ms in zip(pr, metas):
        for t, m in enumerate(ms):
            if m.get("end") and m.get("gold_act") is not None:
                out.append((m, {k: p[k][t] for k in p}))
    return out


def rules_out(m: dict):
    ra = m["rules_act"]
    if ra == "navigate":
        return ra, {"nav": m.get("rules_nav")}
    return ra, (m.get("rules_cmd") if ra == "command" else None)


def on_outcome(m: dict, o: dict, thr: dict):
    """The shipped `on` policy at one turn, exactly as runtime.decide_turn / decide_nav + session run it -> (act, Command
    or {"nav": intent})."""
    ra, rc = rules_out(m)
    route = m.get("route")
    if route == "navigate":                  # the router navigated; the model is never asked (session._routed)
        return ra, rc
    nv = RT.nav_policy(o, thr, offer=bool(m.get("offer"))) if route is not None else None
    if nv:                                   # round 7: the model navigates where the router did not (fitted, guarded)
        return "navigate", {"nav": nv}
    if route == "ignore":
        return ra, rc
    if route == "answer":                    # a lesson step's answer: the model may only silence it
        return ("ignore", None) if RT.answer_policy(o, thr) else (ra, rc)
    words = FX.words_of(m["heard"])
    ov = RT.policy(o, words, rules_cmds(m["heard"]), guard_of(m), thr, mission=m["mode"] == "mission")
    if ov and ov["act"] == "command" and m["mode"] != "mission":
        ov = None
    if not ov:
        return ra, rc
    return ov["act"], ov.get("command")


def guarded_outcome(m: dict, o: dict, thr: dict):
    """Round 10, DIRECTOR_MODEL=guarded exactly as the runtime runs it: the model may act only where the turn's class
    is in thr["classes"] (runtime.situation for a policy turn; "nav" for the navigate fill, "answer" for the lesson
    silencing); the rules decide everywhere else."""
    ra, rc = rules_out(m)
    route = m.get("route")
    if route == "navigate":
        return ra, rc
    if RT.allowed(thr, "nav"):
        nv = RT.nav_policy(o, thr, offer=bool(m.get("offer"))) if route is not None else None
        if nv:
            return "navigate", {"nav": nv}
    if route == "ignore":
        return ra, rc
    if route == "answer":
        return ("ignore", None) if RT.allowed(thr, "answer") and RT.answer_policy(o, thr) else (ra, rc)
    if not RT.allowed(thr, m.get("situ") or "quiet"):
        return ra, rc
    t = {**thr, **(thr.get("guarded") or {})}
    ov = RT.policy(o, FX.words_of(m["heard"]), rules_cmds(m["heard"]), guard_of(m), t, mission=m["mode"] == "mission")
    if ov and ov["act"] == "command" and m["mode"] != "mission":
        ov = None
    if not ov:
        return ra, rc
    return ov["act"], ov.get("command")


CLASSES = RT.SITUATIONS + ("nav", "answer")


def class_gate(model, data_dir: Path, pol: dict) -> dict:
    """Round 10: per set x class, the model enabled in that ONE class (guarded) vs the rules: turns, act ok, wrong,
    extra wrong (the model wrong where the rules were not). A class may ship only with 0 extra wrong and act ok >=
    rules on every set."""
    res = {}
    for name in SETS + CLASS_SETS:
        if not (data_dir / f"{name}.npz").exists():
            continue
        rows = turn_rows(model, data_dir, name)
        for c in CLASSES:
            t = {**pol, "classes": [c]}
            n = rok = ook = rw = ow = extra = 0
            ex = []
            for m, o in rows:
                if c in RT.SITUATIONS and (m.get("situ") or "quiet") != c:
                    continue
                ra, rcm = rules_out(m)
                a, cm = guarded_outcome(m, o, t)
                n += 1
                rok += act_ok(m, ra, rcm)
                ook += act_ok(m, a, cm)
                r_w, o_w = is_wrong(m, ra, rcm), is_wrong(m, a, cm)
                rw += r_w
                ow += o_w
                if o_w and not r_w:
                    extra += 1
                    if len(ex) < 4:
                        ex.append(f"{m['heard']} -> {a} (gold {m['gold_act']})")
            res.setdefault(name, {})[c] = {"n": n, "rules_ok": rok, "on_ok": ook, "rules_wrong": rw, "on_wrong": ow,
                                           "extra": extra, "ex": ex}
    verdict = {}
    for c in CLASSES:
        cells = [r[c] for r in res.values()]
        ok = all(x["extra"] == 0 and x["on_ok"] >= x["rules_ok"] for x in cells)
        gain = sum(x["on_ok"] - x["rules_ok"] for x in cells)
        verdict[c] = {"pass": ok and gain > 0, "clean": ok, "gain": gain, "n": sum(x["n"] for x in cells),
                      "extra": sum(x["extra"] for x in cells),
                      "worse_sets": [k for k, r in res.items() if r[c]["extra"] or r[c]["on_ok"] < r[c]["rules_ok"]]}
    return {"sets": res, "verdict": verdict}


def nav_right(m, c) -> bool:
    gn = m.get("gold_nav")
    return gn in (None, "other", "none") or (c or {}).get("nav") == gn


def act_ok(m, a, c) -> bool:
    return a == m["gold_act"] and (a != "navigate" or nav_right(m, c))


def is_wrong(m, a, c) -> bool:
    g, gc = m["gold_act"], m.get("gold_cmd")
    if a == "navigate":                     # round 7: a navigation the kid did not mean moves the app: a wrong action
        return g != "navigate" or not nav_right(m, c)
    if m.get("expect"):
        return a in EXEC and not (a == "command" and h40_ok(c, m["expect"]))
    return a in EXEC and not (a == g and (a != "command" or (gc and FX.same_command(c, gc))))


def fit_policy(model, data_dir: Path, sets=("val",)) -> dict:
    """Per-act thresholds on val: no more wrong actions than the rules on val (the hard constraint), then the best
    act accuracy; ties -> the more conservative (higher) thresholds."""
    rows = [r for s_ in sets for r in turn_rows(model, data_dir, s_)]
    r_wrong = sum(is_wrong(m, *rules_out(m)) for m, _ in rows)
    for m, o in rows:          # memo for the grid: the decode and its confidence do not depend on the thresholds
        o["_conf"] = RT.cmd_conf(o)
        o["_cmd"] = FX.decode_command(o, FX.words_of(m["heard"]))
    rw = [is_wrong(m, *rules_out(m)) for m, _ in rows]
    grid = [0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 0.99, 0.995, 1.01]
    best = None
    cands = []
    for cmd in grid:
        for veto in [None, 0.9, 0.95, 0.98, 0.99, 0.995]:
            for ign in (0.7, 0.8, 0.9, 0.95, 1.01):
                for ask in (0.7, 0.8, 0.9, 0.95, 1.01):
                    thr = {"cmd": cmd, "veto": veto, "ignore": ign, "ask": ask}
                    w = ok = extra = 0
                    for (m, o), r_ in zip(rows, rw):
                        a, c = on_outcome(m, o, thr)
                        wr = is_wrong(m, a, c)
                        w += wr
                        extra += wr and not r_
                        ok += act_ok(m, a, c)
                    # zero EXTRA wrong actions vs the rules (turns where the rules were right and `on` acts wrongly),
                    # then the fewest wrong actions, then act accuracy, then the more conservative thresholds
                    key = (-extra, -w, ok, cmd, veto or 2, ign, ask)
                    cands.append((thr, w, ok, extra))
                    if best is None or key > best[0]:
                        best = (key, thr, w, ok, extra)
    _, thr, w, ok, extra = best
    thr_ans = fit_answer_ignore(rows)
    for c in cands:
        c[0]["answer_ignore"] = thr_ans
    # robustness (val is small): the most conservative thresholds within 0.5 % act accuracy of the best, with no more
    # wrong actions and still zero extra -> fewer turns ride on a single val example
    slack = 0.005 * len(rows)
    safe = [c for c in cands if c[3] == 0 and c[1] <= w and c[2] >= ok - slack]
    thr, w, ok, extra = max(safe, key=lambda c: (c[0]["cmd"] + (c[0]["veto"] or 1.01) + c[0]["ignore"] + c[0]["ask"],
                                                 c[2]))
    thr = {**thr, **fit_nav(rows, thr, rw)}
    w = sum(is_wrong(m, *on_outcome(m, o, thr)) for m, o in rows)
    ok = sum(act_ok(m, *on_outcome(m, o, thr)) for m, o in rows)
    print(f"policy fit on {sets}: {thr} -> wrong {w} (extra {extra}) vs rules {r_wrong}, act ok {ok}/{len(rows)}",
          flush=True)
    return {**thr, "fit": {"sets": list(sets), "wrong": w, "extra_wrong": extra, "rules_wrong": r_wrong, "act_ok": ok,
                           "turns": len(rows)}}


def fit_nav(rows, thr: dict, rw: list) -> dict:
    """Round 7: the navigate fill alone (nav = p(act navigate) and p(nav intent) floor), on top of the fitted policy:
    zero turns the rules got right that `on` gets wrong, zero extra wrong actions, then the most turns right; off
    (None) unless it gains."""
    def score(v):
        t = {**thr, "nav": v}
        ok = extra = 0
        for (m, o), r_ in zip(rows, rw):
            a, c = on_outcome(m, o, t)
            good = act_ok(m, a, c)
            ok += good
            ra, rc = rules_out(m)
            extra += (not good and act_ok(m, ra, rc)) or (is_wrong(m, a, c) and not r_)
        return ok, extra
    base, _ = score(None)
    best = (base, None)
    for v in (0.7, 0.8, 0.9, 0.95, 0.98, 0.99):
        ok, extra = score(v)
        if extra == 0 and ok > best[0]:
            best = (ok, v)
    print(f"nav fit: {best[1]} -> {best[0]}/{len(rows)} vs {base} without", flush=True)
    return {"nav": best[1]}


def fit_answer_ignore(rows) -> float | None:
    """The lesson-chatter threshold alone (only `answer`-routed turns depend on it): zero turns the rules got right
    that `on` gets wrong on val, then the most turns right; None (off) unless it gains."""
    ans = [(m, o) for m, o in rows if m.get("route") == "answer"]
    if not ans:
        return None
    base = sum(m["rules_act"] == m["gold_act"] for m, _ in ans)
    best = (base, None)
    for v in (0.7, 0.8, 0.9, 0.95, 0.98, 0.99):
        ok = extra = 0
        for m, o in ans:
            a, _ = on_outcome(m, o, {"answer_ignore": v, "nav": None})
            ok += a == m["gold_act"]
            extra += a != m["gold_act"] and m["rules_act"] == m["gold_act"]
        if extra == 0 and ok > best[0]:
            best = (ok, v)
    print(f"answer_ignore fit: {best[1]} -> {best[0]}/{len(ans)} vs rules {base}", flush=True)
    return best[1]


def evaluate_set(model, data_dir: Path, name: str, thr_when: float, pol: dict | None = None) -> dict | None:
    if not (data_dir / f"{name}.npz").exists():
        return None
    ss = TR.load_split(data_dir / f"{name}.npz")
    metas = load_meta(data_dir / f"{name}.meta.jsonl")
    pr = predict_any(model, ss)
    pol = pol or RT.DEFAULT_POLICY
    R = {"model": Counter(), "rules": Counter(), "on": Counter(), "on_fill": Counter()}
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
            if ma == "navigate" and "nav" in o:
                mc = {"nav": FX.NAV_INTENTS[int(np.argmax(o["nav"]))]}
            _, rc = rules_out(m)
            gc = m.get("gold_cmd")
            cat = m.get("cat") or "?"
            # `on` = the shipped policy (runtime.policy with the fitted thresholds, exactly as decide_turn runs it);
            # `on_fill` = round 3's shipped policy (CONF 0.7, fill only where the rules parse no command), for reference.
            oa, oc = on_outcome(m, o, pol)
            fa, fc = on_outcome(m, o, RT.DEFAULT_POLICY)
            for who, a, c in (("model", ma, mc), ("rules", ra, rc), ("on", oa, oc), ("on_fill", fa, fc)):
                Rw = R[who]
                Rw["turns"] += 1
                Rw["act_ok"] += int(act_ok(m, a, c))
                cats[(cat, who)]["n"] += 1
                cats[(cat, who)]["ok"] += int(act_ok(m, a, c))
                if g == "command" and gc:
                    Rw["cmds"] += 1
                    Rw["cmd_exact"] += int(a == "command" and FX.same_command(c, gc))
                wrong = is_wrong(m, a, c)
                Rw["wrong_actions"] += int(wrong)
                if g == "guard" or a == "guard":
                    Rw["guard_n"] += int(g == "guard")
                    Rw["guard_ok"] += int(a == g)
                if m.get("route") == "answer" and g != "ignore" and a == "ignore":
                    Rw["answers_dropped"] += 1         # a real lesson answer silenced
                if m.get("route") == "answer" and g == "ignore" and a in ("answer", "nudge"):
                    Rw["chatter_graded"] += 1          # room chatter graded as the step's answer (a miss)
                if who in ("on", "rules") and wrong and len(examples[("WRONG_" + who, g, a)]) < 6:
                    examples[("WRONG_" + who, g, a)].append(f"{m['heard']} -> {a} {json.dumps(c)}")
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
                if a == "navigate" and g == "navigate":
                    Rw["nav_n"] += 1
                    Rw["nav_intent_ok"] += int(nav_right(m, c))
                if who == "model" and a != g:
                    errs[(cat, g, a)] += 1
                    if len(examples[(cat, g, a)]) < 3:
                        examples[(cat, g, a)].append(m["heard"])
    out = {"set": name, "sessions": len(ss), "steps": int(sum(len(s["feats"]) for s in ss))}
    for who in ("model", "rules", "on", "on_fill"):
        Rw = R[who]
        n = Rw["turns"] or 1
        out[who] = {
            "turns": Rw["turns"], "act_acc": round(Rw["act_ok"] / n, 4),
            "cmd_exact": round(Rw["cmd_exact"] / Rw["cmds"], 4) if Rw["cmds"] else None, "cmds": Rw["cmds"],
            "wrong_per_50": round(50 * Rw["wrong_actions"] / max(Rw["cmds"], Rw["h40_n"]), 2)
            if (Rw["cmds"] or Rw["h40_n"]) else None,
            "wrong_actions": Rw["wrong_actions"], "guard": f"{Rw['guard_ok']}/{Rw['guard_n']}",
            "answers_dropped": Rw["answers_dropped"], "chatter_graded": Rw["chatter_graded"],
            "attr_acc": round(Rw["attr_ok"] / Rw["attr_n"], 4) if Rw["attr_n"] else None,
            "card_attr_acc": round(Rw["ca_ok"] / Rw["ca_n"], 4) if Rw["ca_n"] else None,
            "h40": f"{Rw['h40_ok']}/{Rw['h40_n']} ok, {Rw['h40_wrong']} wrong, {Rw['h40_none']} none" if Rw["h40_n"] else None,
            "nav_intent": f"{Rw['nav_intent_ok']}/{Rw['nav_n']}" if Rw["nav_n"] else None,
        }
        if who not in barge:
            continue
        b = barge[who]
        out[who]["barge_p"] = round(b["tp"] / (b["tp"] + b["fp"]), 3) if b["tp"] + b["fp"] else None
        out[who]["barge_r"] = round(b["tp"] / (b["tp"] + b["fn"]), 3) if b["tp"] + b["fn"] else None
    out["eot"] = {"turns": eot["turns"], "fire_rate": round(eot["fired"] / max(1, eot["turns"]), 3),
                  "premature": round(eot["premature"] / max(1, eot["turns"]), 3),
                  "gain_ms_p50": round(1000 * float(np.median(eot["gain"])), 0) if eot["gain"] else None,
                  "gain_ms_mean": round(1000 * float(np.mean(eot["gain"])), 0) if eot["gain"] else None}
    out["shadow_agreement"] = round(shadow["agree"] / shadow["n"], 4) if shadow["n"] else None
    out["by_cat"] = {c: {who: f"{cats[(c, who)]['ok']}/{cats[(c, who)]['n']}" for who in ("model", "rules", "on")}
                     for c in sorted({c for c, _ in cats})}
    out["top_errors"] = [{"cat": k[0], "gold": k[1], "model": k[2], "n": v, "ex": examples[k]}
                         for k, v in errs.most_common(12)]
    out["wrong_examples"] = {f"{k[0]}:{k[1]}->{k[2]}": v for k, v in examples.items() if k[0].startswith("WRONG_")}
    return out


def ignore_only(pol: dict) -> dict:
    """Round 9's restricted policy (runtime.IGNORE_ONLY): keep the fitted ignore thresholds, switch off command fill,
    ask, veto and navigation."""
    return {**pol, "cmd": 1.01, "ask": 1.01, "veto": None, "nav": None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", default="", help="a trained run (torch): thresholds are fit on val")
    ap.add_argument("--weights", default="", help="exported weights dir (numpy runtime, e.g. the shipped "
                    "backend/app/director_model): its own policy, as it runs in the app")
    ap.add_argument("--refit", action="store_true", help="with --weights: refit the policy thresholds on this val "
                    "(a policy-only update of the shipped weights)")
    ap.add_argument("--out", default="")
    ap.add_argument("--ignore-only", action="store_true", help="round 9: the restricted policy. The model may only "
                    "silence a turn (ignore / answer_ignore at the fitted thresholds); it never fills a command, asks, "
                    "vetoes a rules command or navigates. Everything else stays with the rules")
    ap.add_argument("--policy", default="", help='round 9: JSON merged over the policy, e.g. '
                    '\'{"veto": null, "ignore_min_words": 3}\'')
    ap.add_argument("--class-gate", action="store_true", help="round 10: also the per-situation-class gate "
                    "(the model enabled in one class at a time, guarded, vs the rules on every set)")
    a = ap.parse_args()
    d = Path(a.data)
    if a.weights:
        model = NumpyModel(Path(a.weights))
        meta = model.meta
        thr = float((meta.get("thr") or {}).get("when", 0.9))
        pol = fit_policy(model, d) if a.refit else {**RT.DEFAULT_POLICY, **(meta.get("policy") or {})}
        res = {"weights": a.weights, "params": meta.get("params"), "size": meta.get("size_name"), "F": meta.get("F"),
               "thr_when": thr, "policy": pol, "sets": {}}
    else:
        cfg = json.load(open(f"{a.run}/train.json"))
        model = TR.make(cfg["F"], cfg["size_name"])
        model.load_state_dict(torch.load(f"{a.run}/model.pt", map_location="cpu"))
        model.eval()
        thr = tune_when(model, d)
        pol = fit_policy(model, d)
        res = {"run": a.run, "params": cfg["params"], "size": cfg["size_name"], "thr_when": thr, "policy": pol, "sets": {}}
    if a.policy:
        pol = {**pol, **json.loads(a.policy)}
        res["policy"] = pol
    if a.ignore_only:
        pol = ignore_only(pol)
        res["policy"] = pol
        res["policy_kind"] = "ignore_only"
    if a.class_gate:
        g = class_gate(model, d, pol)
        res["class_gate"] = g
        print("| class | turns | gain (act ok vs rules) | extra wrong | sets worse | ships |")
        for c, v in g["verdict"].items():
            print(f"| {c} | {v['n']} | {v['gain']:+d} | {v['extra']} | {', '.join(v['worse_sets']) or '-'} | "
                  f"{'yes' if v['pass'] else 'no'} |")
    for name in SETS + CLASS_SETS:
        r = evaluate_set(model, d, name, thr, pol)
        if r:
            res["sets"][name] = r
    out = Path(a.out or f"{a.run or a.weights}/eval.json")
    out.write_text(json.dumps(res, indent=1))
    print(f"| set | turns | act acc M / R | cmd exact M / R | wrong/50 M / R | attr M / R | card+attr M / R | "
          f"eot premature, mean gain | barge P/R M ; R | shadow agree |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for name, r in res["sets"].items():
        M, Rr = r["model"], r["rules"]

        def f(k):
            return f"{M[k]} / {Rr[k]}"
        print(f"| {name} | {M['turns']} | {f('act_acc')} | {f('cmd_exact')} | {f('wrong_per_50')} | {f('attr_acc')} | "
              f"{f('card_attr_acc')} | {r['eot']['premature']}, {r['eot']['gain_ms_mean']} ms | "
              f"{M['barge_p']}/{M['barge_r']} ; {Rr['barge_p']}/{Rr['barge_r']} | {r['shadow_agreement']} |")
    print("\n`on` policy (guarded) vs rules: act acc, cmd exact, wrong/50 | on_fill")
    for name, r in res["sets"].items():
        O, F_, Rr = r["on"], r["on_fill"], r["rules"]
        print(f"| {name} | {O['act_acc']} / {Rr['act_acc']} | {O['cmd_exact']} / {Rr['cmd_exact']} | "
              f"{O['wrong_per_50']} / {Rr['wrong_per_50']} | fill: {F_['act_acc']}, {F_['cmd_exact']}, {F_['wrong_per_50']} |"
              + (f" h40 on {O['h40']} ; fill {F_['h40']}" if O.get('h40') else ""))
    for name in ("test_h40", "test_h40_asr"):
        if name in res["sets"]:
            print(name, "model:", res["sets"][name]["model"]["h40"], "| rules:", res["sets"][name]["rules"]["h40"])
    for name in ("test_asr", "test_ear", "test_q80"):
        if name in res["sets"]:
            print(f"top errors {name}:", json.dumps(res["sets"][name]["top_errors"][:8]))


if __name__ == "__main__":
    main()
