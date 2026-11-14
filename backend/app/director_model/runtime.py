"""The learned Director at runtime: a tiny streaming Mamba-3 (trained in director_model/, exported int8) stepped once per
session event, numpy only (no torch).

DIRECTOR_MODEL=off|shadow|on (env; default shadow):
  off     the model never runs.
  shadow  the model runs on every step and logs what it would do next to what the rules did; it never acts.
  on      the model decides at a kid's turn end, with the rules as guardrails: the privacy guard always wins; a model
          command must pass nlu.valid(); below CONF the rules decide; style tags outside the allowed set are never
          produced (the space only has allowed tags; steering re-checks FORBIDDEN anyway).
GET /api/director/stats: shadow agreement counts (main.py).

The forward pass mirrors director_model/train.py `Director` (verified by director_model/export.py and
backend/tests/test_director_model.py: numpy streaming == torch parallel).
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter, deque
from pathlib import Path

import numpy as np

from . import features as FX

MODEL_DIR = Path(__file__).resolve().parent
CONF = 0.7                     # `on`: the model's act must be at least this sure, else the rules decide


def mode() -> str:
    m = (os.environ.get("DIRECTOR_MODEL") or "shadow").strip().lower()
    return m if m in ("off", "shadow", "on") else "shadow"


# ---------------------------------------------------------------------------------------------- numpy forward
_ERF = np.vectorize(math.erf)


def _gelu(x):
    return 0.5 * x * (1.0 + _ERF(x / math.sqrt(2.0)))


def _silu(x):
    return x / (1.0 + np.exp(-x))


def _softplus(x):
    return np.where(x > 20, x, np.log1p(np.exp(np.minimum(x, 20))))


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60, 60)))


def _softmax(x):
    e = np.exp(x - x.max())
    return e / e.sum()


class Model:
    def __init__(self, path: Path = MODEL_DIR, name: str = "weights"):
        meta = json.loads((path / f"{name}.json").read_text())
        z = np.load(path / f"{name}.npz")
        p = {}
        for k in z.files:
            if k.endswith("::q"):
                base = k[:-3]
                p[base] = z[k].astype(np.float32) * z[base + "::s"][:, None]
            elif not k.endswith("::s"):
                p[k] = z[k].astype(np.float32)
        self.p, self.meta = p, meta
        c = meta["size"]
        self.d, self.L, self.N, self.P = c["d"], c["layers"], c["d_state"], c["head_dim"]
        self.H = self.d // self.P
        self.buckets = c["buckets"]
        self.emb_dim = c["emb"]
        self.heads = meta["heads"]
        self.thr = meta.get("thr", {})
        self.eps = float(np.finfo(np.float32).eps)
        assert meta["F"] == FX.F, f"feature width {meta['F']} != {FX.F}: retrain/export the model for this features.py"

    def lin(self, name, x):
        y = x @ self.p[name + ".weight"].T
        b = self.p.get(name + ".bias")
        return y + b if b is not None else y

    def rms(self, name, x):
        return x / np.sqrt(np.mean(x * x, -1, keepdims=True) + self.eps) * self.p[name + ".weight"]

    def ln(self, name, x, eps=1e-5):
        m = x.mean(-1, keepdims=True)
        v = ((x - m) ** 2).mean(-1, keepdims=True)
        return (x - m) / np.sqrt(v + eps) * self.p[name + ".weight"] + self.p[name + ".bias"]

    def emb(self, t):
        t = np.where(t > 0, np.remainder(t, self.buckets), 0)
        return self.p["emb.weight"][t]

    def block(self, i, u, h, bx):
        pre = f"blocks.{i}."
        H, N, P = self.H, self.N, self.P
        nu = self.rms(pre + "norm", u)
        dt = _softplus(self.lin(pre + "dt_proj", nu))
        A = -np.exp(self.p[pre + "A_log"])
        alpha = np.exp(dt * A)
        lam = _sigmoid(self.lin(pre + "lam_proj", nu))
        gamma, beta = lam * dt, (1 - lam) * dt * alpha
        Bm = self.rms(pre + "B_norm", self.lin(pre + "B_proj", nu).reshape(H, 1, N)).transpose(0, 2, 1) + self.p[pre + "B_bias"]
        Cm = self.rms(pre + "C_norm", self.lin(pre + "C_proj", nu).reshape(H, 1, N)).transpose(0, 2, 1) + self.p[pre + "C_bias"]
        x = self.lin(pre + "x_proj", nu).reshape(H, P, 1)
        theta = self.lin(pre + "theta_proj", nu).reshape(H, N // 2) * dt[:, None]
        h = np.zeros((H, N, P), np.float32) if h is None else h
        s = alpha[:, None, None] * h
        if bx is not None:
            s = s + beta[:, None, None] * bx
        c, sn = np.cos(theta)[:, :, None], np.sin(theta)[:, :, None]
        a_, b_ = s[:, 0::2, :], s[:, 1::2, :]
        r = np.empty_like(s)
        r[:, 0::2, :] = c * a_ - sn * b_
        r[:, 1::2, :] = sn * a_ + c * b_
        bxn = Bm @ x.transpose(0, 2, 1)
        h = r + gamma[:, None, None] * bxn
        y = (Cm.transpose(0, 2, 1) @ h).reshape(-1)
        out = self.lin(pre + "out_proj", y * _silu(self.lin(pre + "in_proj", nu)))
        return out, h, bxn

    def step(self, state, feats, toks, wtok, wfeat):
        """One event. Returns ({head: probs}, new state). Class heads -> softmax, binary -> sigmoid, word heads -> [W]."""
        p = self.p
        e = self.emb(toks)
        m = (toks > 0).astype(np.float32)[:, None]
        bag = (e * m).sum(0) / max(1.0, float(m.sum()))
        x = self.lin("inp", np.concatenate([(feats - p["mu"]) / p["sd"], bag]))
        state = state or [(None, None)] * self.L
        new = []
        for i in range(self.L):
            h, bx = state[i]
            y, h, bx = self.block(i, x, h, bx)
            x = x + y
            mm = f"mlps.{i}."
            x = x + self.lin(mm + "3", _gelu(self.lin(mm + "1", self.ln(mm + "0", x))))
            new.append((h, bx))
        hN = self.ln("norm", x)
        o = self.lin("head", hN)
        out, j = {}, 0
        for name, n in self.heads:
            z = o[j:j + n]
            out[name] = float(_sigmoid(z[0])) if n == 1 else _softmax(z)
            j += n
        we = self.emb(wtok)                                                  # W, E
        q = self.lin("wq", hN).reshape(len(FX.WORD_HEADS), self.emb_dim)     # 3, E
        wl = we @ q.T + self.lin("wf", wfeat) + self.lin("wb", hN)[None, :]  # W, 3
        for i, name in enumerate(FX.WORD_HEADS):
            out[name] = np.where(wtok > 0, _sigmoid(wl[:, i]), 0.0)
        return out, new


_model: Model | None = None
_failed: str | None = None


def model() -> Model | None:
    global _model, _failed
    if _model is None and _failed is None:
        try:
            _model = Model()
        except Exception as e:  # noqa: BLE001 (no weights shipped / stale features: shadow logs nothing, rules decide)
            _failed = f"{type(e).__name__}: {e}"
    return _model


# ---------------------------------------------------------------------------------------------- stats
STATS: dict = {"steps": 0, "decisions": 0, "act_agree": 0, "turns": 0, "turn_agree": 0, "commands": 0,
               "command_agree": 0, "model_overrides": 0, "pairs": Counter(), "recent": deque(maxlen=50)}


def stats() -> dict:
    s = {k: v for k, v in STATS.items() if k not in ("pairs", "recent")}
    s["mode"] = mode()
    s["model"] = None if model() is None else {k: _model.meta.get(k) for k in ("size_name", "params", "trained")}
    s["model_error"] = _failed
    s["act_agreement"] = round(s["act_agree"] / s["decisions"], 4) if s["decisions"] else None
    s["turn_agreement"] = round(s["turn_agree"] / s["turns"], 4) if s["turns"] else None
    s["command_agreement"] = round(s["command_agree"] / s["commands"], 4) if s["commands"] else None
    s["pairs"] = {f"{a}->{b}": n for (a, b), n in STATS["pairs"].most_common(40)}
    s["recent"] = list(STATS["recent"])
    return s


def reset_stats():
    for k in ("steps", "decisions", "act_agree", "turns", "turn_agree", "commands", "command_agree", "model_overrides"):
        STATS[k] = 0
    STATS["pairs"].clear()
    STATS["recent"].clear()


# ---------------------------------------------------------------------------------------------- the per-session hook
def emitted_act(cur: dict) -> str:
    """What the rules did at one step (from the direct() result at a turn, else from the decisions emitted)."""
    if cur.get("r") is not None:
        return FX.rules_act(cur["r"])
    ds = cur.get("decisions") or []
    if cur["rec"]["kind"] == "ui" and cur["rec"].get("ui") == "end_shift" and any(d["t"] == "hud" for d in ds):
        return "command"
    if any(d["t"] == "alert" for d in ds):
        return "alert"
    if any(d["t"] == "card" and d.get("nudge") for d in ds):
        return "nudge"
    return "wait"


class Shadow:
    """One per Session. `step(ev, read)` at every event (before the policy acts); `emitted(ds)` / `turn_result(r)`
    record what the rules did; the previous step is scored when the next one starts. `sink` (a list) receives every
    finished step (the training generator uses it: the same hook, the same features)."""

    def __init__(self, sess, sink: list | None = None, run_model: bool | None = None):
        self.sess = sess
        self.sink = sink
        self.run_model = (mode() != "off") if run_model is None else run_model
        self.state = None
        self.prev: dict | None = None
        self.cur: dict | None = None
        self.n = 0

    def step(self, ev: dict, read: dict | None = None) -> dict | None:
        self._close()
        rec = FX.record(self.sess, ev, read)
        out = None
        if self.run_model:
            m = model()
            if m is not None:
                x = FX.step_feats(rec, self.prev)
                toks, wtok, wfeat = FX.step_tokens(rec)
                out, self.state = m.step(self.state, x, toks, wtok, wfeat)
        self.cur = {"rec": rec, "out": out, "decisions": [], "r": None, "i": self.n}
        self.prev = rec
        self.n += 1
        STATS["steps"] += 1
        return out

    def emitted(self, ds: list[dict]):
        if self.cur is not None:
            self.cur["decisions"] += ds

    def turn_result(self, r: dict):
        if self.cur is not None:
            self.cur["r"] = {k: r.get(k) for k in ("action", "command", "nlu", "source", "needs_confirm", "place")}
            self.cur["r"]["brain"] = (r.get("readout") or {}).get("brain")

    def flush(self):
        self._close()

    def model_act(self, out: dict | None) -> tuple[str, float]:
        if not out:
            return "wait", 0.0
        i = int(np.argmax(out["act"]))
        return FX.ACTS[i], float(out["act"][i])

    def _close(self):
        cur, self.cur = self.cur, None
        if cur is None:
            return
        ra = emitted_act(cur)
        cur["rules_act"] = ra
        if cur["out"] is not None:
            ma, p = self.model_act(cur["out"])
            if ra != "wait" or ma != "wait":
                STATS["decisions"] += 1
                STATS["act_agree"] += int(ra == ma)
                STATS["pairs"][(ra, ma)] += 1
            if cur["rec"]["kind"] in ("turn_end", "typed"):
                STATS["turns"] += 1
                STATS["turn_agree"] += int(ra == ma)
                rc = FX.rules_command(cur["r"])
                if rc or ma == "command":
                    mc = FX.decode_command(cur["out"], FX.words_of(cur["rec"]["text"])) if ma == "command" else None
                    STATS["commands"] += 1
                    STATS["command_agree"] += int(bool(rc and mc and FX.same_command(rc, mc)) or (not rc and not mc))
                STATS["recent"].append({"text": cur["rec"]["text"][:80], "rules": ra, "model": ma, "p": round(p, 3)})
        if self.sink is not None:
            self.sink.append({"rec": cur["rec"], "r": cur["r"], "rules_act": ra,
                              "decisions": [_slim(d) for d in cur["decisions"]]})

    # ---- `on` mode -------------------------------------------------------------------------------------------------
    def decide_turn(self, out: dict | None, text: str, rules_guard: bool) -> dict | None:
        """At a turn end, `on` mode: the model's decision if it may override the rules, else None (rules decide).
        -> {"act": "ignore"|"ask_clarify"|"command", "command"?: Command}."""
        if mode() != "on" or not out or rules_guard:
            return None
        act, p = self.model_act(out)
        if p < CONF:
            return None
        if act == "ignore":
            return {"act": "ignore"}
        if act == "ask_clarify":
            return {"act": "ask_clarify"}
        if act == "command":
            c = FX.decode_command(out, FX.words_of(text))
            if c is not None:
                return {"act": "command", "command": c}
        return None


def _slim(d: dict) -> dict:
    keep = ("t", "priority", "style", "nudge", "hint", "action", "source", "level", "holder", "voice", "proactive")
    return {k: d[k] for k in keep if k in d}


def attach(sess, sink: list | None = None) -> Shadow | None:
    if sink is None and mode() == "off":
        return None
    return Shadow(sess, sink=sink, run_model=None if sink is None else False)
