"""Round 6 (docs/DIRECTOR_LOOP.md): appended hands-free features, the lesson-chatter answer policy, the turn-log import
and the loop's gate. No torch, no model server."""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from app.director_model import features as FX, runtime as RT

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "director_model"))
import import_logs as IL  # noqa: E402
import loop as LOOP  # noqa: E402


def test_features_are_only_appended():
    assert FX.FEATS[FX.F_R5 - 1] == "lesson_pass" and FX.F > FX.F_R5
    assert FX.ACTS[:10] == ["wait", "answer", "command", "confirm_yes", "confirm_no", "ask_clarify", "guard", "alert",
                            "nudge", "ignore"] and FX.ACTS[10] == "navigate"


def test_weights_load_and_read_their_prefix():
    m = RT.Model()
    assert FX.F_R5 <= m.F <= FX.F
    x = np.zeros(FX.F, np.float32)
    toks, wtok, wfeat = np.zeros(FX.K, np.int64), np.zeros(FX.W, np.int64), np.zeros((FX.W, FX.WF), np.float32)
    o1, _ = m.step(None, x, toks, wtok, wfeat)
    x[FX.F_R5:] = 1.0                      # the appended block cannot move a model trained before it
    o2, _ = m.step(None, x, toks, wtok, wfeat)
    if m.F == FX.F_R5:
        assert np.allclose(o1["act"], o2["act"])


def _out(act, p):
    o = {"act": np.full(len(FX.ACTS), (1 - p) / (len(FX.ACTS) - 1))}
    o["act"][FX.ACTS.index(act)] = p
    return o


def test_answer_policy_is_off_unless_fitted():
    assert RT.answer_policy(_out("ignore", 0.999), RT.DEFAULT_POLICY) is False
    thr = {**RT.DEFAULT_POLICY, "answer_ignore": 0.9}
    assert RT.answer_policy(_out("ignore", 0.95), thr) is True
    assert RT.answer_policy(_out("ignore", 0.85), thr) is False
    assert RT.answer_policy(_out("answer", 0.99), thr) is False      # it may only silence, never answer


def test_handsfree_features_read_the_frame_and_the_router():
    rec = {"kind": "turn_end", "now": 10.0, "text": "next", "mission": False, "kid_open": False,
           "pending_confirm": False, "referent": False, "last_place": False, "frame": {"screen": "lesson_done", "step_type": None,
           "offer": "next_lesson", "options": []}, "route": {"outcome": "navigate", "reason": "intent"},
           "on_air": False, "speaking": True, "line_gap": 0.2, "recent": ["Ready for the next lesson?"]}
    x = FX.step_feats(rec, None)
    v = {k: x[FX.FEATS.index(k)] for k in ("scr_lesson_done", "offer_on", "rt_navigate", "nav_any", "nav_offer",
                                           "speaking", "echo_recent")}
    assert v == {"scr_lesson_done": 1, "offer_on": 1, "rt_navigate": 1, "nav_any": 1, "nav_offer": 1, "speaking": 1,
                 "echo_recent": 1}
    old = {k: v for k, v in rec.items() if k not in ("frame", "route", "on_air", "speaking", "line_gap", "recent")}
    assert not FX.step_feats(old, None)[FX.F_R5:].any()          # a pre-round-6 record: the block stays zero


# ---- import ------------------------------------------------------------------------------------------------------
def T(i, text, outcome, final, **k):
    return {"k": "turn", "v": 1, "s": "ab", "id": f"ab-{i}", "t": i, "text": text, "nw": len(text.split()),
            "src": "listen", "arc": {"dd": k.pop("dd", 0.9)}, "frame": {"screen": k.pop("screen", "lesson"),
            "step_type": "choice", "offer": None, "options": []}, "router": {"outcome": outcome},
            "director": {"final": final}, **k}


def S(ref, sig, by=None):
    return {"k": "signal", "s": "ab", "ref": ref, "sig": sig, "by": by}


def test_import_weak_labels(tmp_path):
    log = tmp_path / "turns.jsonl"
    rows = [T(0, "what is a crater", "ignore", "ignore", dd=0.3, screen="map"),
            T(1, "what is a crater", "question", "answer", screen="map"), S("ab-0", "repeat", "ab-1"),
            T(2, "oh it s", "answer", "answer"), S("ab-2", "hint"),
            T(3, "turn off life support", "order", "command", screen="cabin", director={"final": "command"}),
            S("ab-3", "confirm_cancel"),
            T(4, "next", "navigate", "navigate", screen="lesson_done"),
            T(5, "<private>", "order", "command", guard=True)]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n{torn")
    out, rev = tmp_path / "real_turns.json", tmp_path / "review"
    res = IL.run(IL.files_of([str(tmp_path)]), out, rev, quiet=True)
    items = {x["id"]: x for x in json.loads(out.read_text())["items"]}
    assert items["ab-0"]["gold"]["act"] == "answer"           # ignored, then repeated and answered: the ignore was wrong
    assert items["ab-2"]["gold"]["act"] == "ignore"           # chatter graded as an answer
    assert items["ab-4"]["gold"]["act"] == "navigate"
    assert "ab-5" not in items and res["skipped_private"] == 1
    review = [json.loads(x) for x in (rev / "review.jsonl").read_text().splitlines()]
    assert [r["id"] for r in review] == ["ab-3"]              # a cancelled confirm: a person decides
    (rev / "reviewed.jsonl").write_text(json.dumps({**review[0], "fix": "ask_clarify"}) + "\n")
    IL.run(IL.files_of([str(log)]), out, rev, quiet=True)
    items = {x["id"]: x for x in json.loads(out.read_text())["items"]}
    assert items["ab-3"]["gold"]["act"] == "ask_clarify" and items["ab-3"]["conf"] == 1.0


# ---- gate --------------------------------------------------------------------------------------------------------
def ev(on_act, on_wrong, rules_act=0.8, rules_wrong=3, guard="1/1", sets=("test_clean", "cls_chatter")):
    def blk(a, w, g):
        return {"turns": 100, "act_acc": a, "wrong_actions": w, "wrong_per_50": w * 1.0, "guard": g}
    return {"sets": {s: {"on": blk(on_act, on_wrong, guard), "rules": blk(rules_act, rules_wrong, "1/1"),
                         "model": blk(on_act, on_wrong, guard)} for s in sets}}


@pytest.mark.parametrize("cand,ship,ok", [
    (ev(0.9, 2), ev(0.85, 2), True),
    (ev(0.9, 4), ev(0.85, 2), False),                 # more wrong actions than the rules
    (ev(0.79, 2), ev(0.85, 2), False),                # act accuracy below the rules
    (ev(0.84, 2), ev(0.85, 2), False),                # a class set regresses vs the shipped weights
    (ev(0.9, 2, guard="0/1"), ev(0.85, 2), False),    # the privacy guard row changed
])
def test_gate(cand, ship, ok):
    assert LOOP.check(cand, ship)[0] is ok
