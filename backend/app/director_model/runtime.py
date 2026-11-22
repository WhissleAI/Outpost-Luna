"""The learned Director at runtime: a tiny streaming Mamba-3 (trained in director_model/, exported int8) stepped once per
session event, numpy only (no torch).

DIRECTOR_MODEL=off|shadow|guarded|on (env; see DEFAULT_MODE. shadow 2026-11-14 to round 10, owner decision after round 6; was on since round 4: the guarded policy met the switch-on criteria in
director_model/RESULTS.md; the rules remain the fallback on every turn the policy does not take, and whenever the
weights fail to load):
  off     the model never runs.
  shadow  the model runs on every step and logs what it would do next to what the rules did; it never acts.
  guarded (round 10) as `on`, but only in the situation classes (situation(): hot / short / echo / video / quiet, plus
          "nav" and "answer") that the weights' policy lists under "classes", each passed on the full gate with no
          extra wrong action over the rules. A policy without "classes" enables nothing: guarded == the rules.
  on      the model decides at a kid's turn end where the rules read no command, with the rules as guardrails: the
          privacy guard always wins; the model never overrides a rules command; a model
          command must pass nlu.valid(); below CONF the rules decide; style tags outside the allowed set are never
          produced (the space only has allowed tags; steering re-checks FORBIDDEN anyway).
GET /api/director/stats: shadow agreement counts (main.py), and `latency` (round 7): the loaded weights' numpy step time
(p50 / p95 ms, measured at load; the bigger xl size must stay under ~5 ms per step on CPU).
Round 7 also adds `nav_policy` (the `nav` head: the model may navigate a turn the router did not, fitted and guarded).

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


MODES = ("off", "shadow", "guarded", "on")


def mode() -> str:
    """off: no model. shadow: the model runs and is scored, the rules decide. guarded (round 10): the model may act
    only in the situation classes its weights' policy lists under "classes" (each proven on the full gate to add no
    wrong action over the rules), the rules decide everywhere else. on: the fitted policy everywhere."""
    m = (os.environ.get("DIRECTOR_MODEL") or DEFAULT_MODE).strip().lower()
    return m if m in MODES else "on"


DEFAULT_MODE = "guarded"  # round 12 (2026-11-17): r12 xl acts in quiet, r10 xl (weights_r10, routed) in hot + echo;
#   round 10 (2026-11-16): r10 xl acts only in the classes its policy lists (hot, echo: each
#   passed the full gate with 0 extra wrong actions); the rules decide everywhere else. Was "shadow" since 2026-11-14
#   (owner: shadow until a round passes the gate).

# Round 10: the situation a turn end is in, from session state the runtime has at that moment (features.record).
# Checked in this order; the first that holds names the class.
SITUATIONS = ("hot", "short", "echo", "video", "quiet")


def situation(rec: dict | None, text: str) -> str:
    """hot   : the words name an on-screen control or the step's options (hot-list exact hit) - a command said plainly;
       short : fewer than 3 words (usually a real answer or a control: "far side", "yes please");
       echo  : our own line is on the air / just spoken, or a guide or crew clip is playing (its audio leaks in);
       video : a video is playing;
       quiet : none of these (room talk, a plain turn)."""
    rec = rec or {}
    hot = rec.get("hot") or {}
    if (hot.get("step") or 0) > 0 or (hot.get("screen") or 0) > 0:
        return "hot"
    if len([w for w in FX.words_of(text) if w]) < 3:
        return "short"
    if rec.get("on_air") or rec.get("speaking") or rec.get("playing_kind") in ("guide", "crew"):
        return "echo"
    if rec.get("video_on") or rec.get("playing_kind") == "video":
        return "video"
    return "quiet"


def bare_turn(rec: dict | None, n_words: int) -> bool:
    """Round 14 (round 13 "Next"): a heard turn end with no ear read-out at all: no partial words since its start, no
    ear extras on the final words (no ABI 2 read-out: e13_avail 0, no names / decoder text). The backend tests' form
    ("a" with no arc read and no partials); no live ear sends it. The model never decides such a turn (it may not
    answer it, silence it or navigate it): the rules do. Typed turns are not heard turns and are unaffected.
    ONE definition: Shadow (runtime) and director_model/evaluate.py (`bare` in the dataset meta)."""
    return bool(rec) and rec.get("kind") == "turn_end" and not n_words and not rec.get("e13") and not rec.get("ear")


def turn_words_next(kind: str, n: int) -> int:
    """The partial / final word messages seen since the current heard turn started, after an event of `kind` (bare_turn
    reads it at the turn end). A turn start opens the count; a turn end or typed turn closes it (the next turn counts
    from 0 even when no turn start precedes it). ONE definition: Shadow and gen_sessions.label_session."""
    if kind == "turn_start":
        return 0
    if kind == "words":
        return n + 1
    return n


def allowed(thr: dict, cls: str) -> bool:
    """`guarded`: may a model act in this class? Only the classes the weights' policy lists (none = nowhere), either
    for the weights themselves (`classes`) or routed to another weight file (`routes`, round 12)."""
    return cls in (thr.get("classes") or ()) or cls in (thr.get("routes") or {})


def pick(thr: dict, cls: str, out: dict | None, pols: dict | None = None) -> tuple[dict, dict] | None:
    """Round 12, per-class model routing (`guarded`): which model decides in class `cls`, and with which policy.
    `thr` is the primary weights' policy: `classes` lists the classes the primary acts in itself; `routes`
    ({class: weight file name}) the classes another weight file acts in, with ITS OWN fitted policy (`pols[name]`) and
    its own output (`out["_routed"][name]`, stepped on the same events). A class in neither: None, the rules decide.
    A routed file that failed to load gives None too (the rules decide). ONE definition: the runtime below and
    director_model/evaluate.py (the gate evaluates exactly this)."""
    if not out:
        return None
    r = (thr.get("routes") or {}).get(cls)
    if r:
        o = (out.get("_routed") or {}).get(r)
        p = (pols or {}).get(r)
        return (o, p) if o is not None and p is not None else None
    return (out, thr) if cls in (thr.get("classes") or ()) else None


# ---------------------------------------------------------------------------------------------- numpy forward
def _ERF(x):
    """Vectorised erf (Abramowitz & Stegun 7.1.26, |error| < 1.5e-7): np.vectorize(math.erf) was a Python call per
    unit, the slowest part of a step once the model grew (round 7 xl)."""
    x = np.asarray(x, np.float64)
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * \
        np.exp(-a * a)
    return (s * y).astype(np.float32)


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
        # Features are only ever APPENDED (round 6 added the hands-free block after F_R5): older weights read the
        # prefix they were trained on. A model wider than features.py is stale code, not stale weights.
        self.F = int(meta["F"])
        # Round 15: which feature set the weights read. "full" (every file up to round 14): the legacy vector's
        # prefix. "raw": features.raw_feats (perception + state only), its own fixed width.
        self.feat_set = meta.get("feat_set") or "full"
        # Round 12: the slots these weights were trained with at 0 (the dead round-7 ear slots, `trained_zero` in
        # weights.json). An ear that fills them later (libarc ABI 2: per-word conf, n-best alts) must not move these
        # weights' inputs: they are forced back to 0 here, whatever features.py computes.
        self.zero = np.array([FX._IDX[k] for k in meta.get("trained_zero") or [] if FX._IDX.get(k, self.F) < self.F],
                             np.int64) if self.feat_set == "full" else np.zeros(0, np.int64)
        if self.feat_set == "raw":
            assert self.F == FX.F_RAW, f"raw feature width {meta['F']} vs {FX.F_RAW}: retrain/export for this features.py"
        else:
            assert self.F <= FX.F and self.F >= FX.F_R5, \
                f"feature width {meta['F']} vs {FX.F}: retrain/export the model for this features.py"
        # Round 15: pointer heads (shadow only): score each candidate (a reply line, an entity) by a dot product of the
        # model state's query with the candidate's precomputed key (the embedder's vector, projected; exported int8)
        self.ptr = [(n, int(k), int(r)) for n, k, r in meta.get("ptr_heads") or []]

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
        feats = feats[:self.F]
        if self.zero.size:
            feats = feats.copy()
            feats[self.zero] = 0.0
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
        for name, _, r in self.ptr:          # round 15: reply-line / entity pointers (dot product over candidates)
            q = self.lin(f"ptr_{name}_q", hN)
            out[name] = _softmax(self.p[f"ptr_{name}_K"] @ q / math.sqrt(r))
        return out, new

    def feats(self, rec: dict, prev: dict | None) -> np.ndarray:
        """This file's own input vector for a step (its feature set)."""
        return FX.feats_for(self.feat_set, rec, prev)


_model: Model | None = None
_failed: str | None = None
_routed: dict = {}           # round 12: {weight file name: Model} for the primary policy's `routes`
LATENCY: dict = {}            # step latency of the loaded weights (ms p50 / p95 over a short warm-up, CPU, numpy)


def measure_latency(m: "Model", n: int = 60) -> dict:
    """Step the model n times on zero features: the per-event cost the session pays (round 7 reports it for xl)."""
    import time
    st = None
    x = np.zeros(m.F, np.float32)
    toks, wtok, wf = np.zeros(FX.K, np.int64), np.zeros(FX.W, np.int64), np.zeros((FX.W, FX.WF), np.float32)
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        _, st = m.step(st, x, toks, wtok, wf)
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    return {"p50_ms": round(ts[len(ts) // 2], 3), "p95_ms": round(ts[int(len(ts) * 0.95) - 1], 3), "n": n}


def model() -> Model | None:
    global _model, _failed
    if _model is None and _failed is None:
        try:
            _model = Model(MODEL_DIR)
            for name in sorted(set(((_model.meta.get("policy") or {}).get("routes") or {}).values())):
                try:
                    _routed[name] = Model(MODEL_DIR, name)
                except Exception as e:  # noqa: BLE001 (a routed file that fails: its classes go back to the rules)
                    LATENCY["routed_error"] = f"{name}: {type(e).__name__}: {e}"
            LATENCY.update(measure_latency(_model))
            if _routed:
                LATENCY["routed"] = {n: measure_latency(m) for n, m in _routed.items()}
                LATENCY["turn_p50_ms"] = round(LATENCY["p50_ms"] + sum(v["p50_ms"] for v in LATENCY["routed"].values()), 3)
        except Exception as e:  # noqa: BLE001 (no weights shipped / stale features: shadow logs nothing, rules decide)
            _failed = f"{type(e).__name__}: {e}"
    return _model


_r15: dict = {}               # round 15: {"model": Model | None, "error": str | None} (weights_r15.*, SHADOW only)
R15_FILE = "weights_r15"
PERCEIVE_TIMEOUT_S = 0.5      # the pre-routing tagger + embedder read for the raw model (shadow): never blocks longer


def r15_model() -> Model | None:
    """Round 15: the raw-feature model with the reply / slot heads, loaded only to LOG what it would do (shadow). It is
    never consulted by any decide_* path: the shipped policy (weights.json + its routes) is unchanged. Off with
    DIRECTOR_R15=off, or when DIRECTOR_MODEL=off, or when the file is absent."""
    if mode() == "off" or (os.environ.get("DIRECTOR_R15") or "on").strip().lower() == "off":
        return None
    if "model" not in _r15:
        _r15["model"], _r15["error"] = None, None
        if (MODEL_DIR / f"{R15_FILE}.json").exists():
            try:
                m = Model(MODEL_DIR, R15_FILE)
                _r15["model"] = m
                LATENCY["r15"] = measure_latency(m, 30)
            except Exception as e:  # noqa: BLE001 (a stale / broken shadow file: nothing is logged, nothing changes)
                _r15["error"] = f"{type(e).__name__}: {e}"
    return _r15["model"]


def routed_models() -> dict:
    """{name: Model} of the routed weight files (loaded with the primary; empty without `routes`)."""
    model()
    return _routed


def policies() -> dict:
    """{name: policy} of the routed weight files (runtime.pick's `pols`)."""
    return {n: {**DEFAULT_POLICY, **(m.meta.get("policy") or {})} for n, m in routed_models().items()}


# ---------------------------------------------------------------------------------------------- stats
STATS: dict = {"steps": 0, "decisions": 0, "act_agree": 0, "turns": 0, "turn_agree": 0, "commands": 0,
               "command_agree": 0, "model_overrides": 0, "pairs": Counter(), "recent": deque(maxlen=50)}


def stats() -> dict:
    s = {k: v for k, v in STATS.items() if k not in ("pairs", "recent")}
    s["mode"] = mode()
    s["model"] = None if model() is None else {k: _model.meta.get(k) for k in ("size_name", "params", "trained")}
    s["routed"] = {n: {"classes": [c for c, f in ((_model.meta.get("policy") or {}).get("routes") or {}).items() if f == n],
                       **{k: m.meta.get(k) for k in ("size_name", "params", "trained")}}
                   for n, m in _routed.items()} if _model is not None else None
    s["latency"] = dict(LATENCY) or None
    s["model_error"] = _failed
    m15 = r15_model()
    s["r15"] = None if m15 is None and not _r15.get("error") else {
        "shadow_only": True, "error": _r15.get("error"),
        "model": None if m15 is None else {k: m15.meta.get(k) for k in ("size_name", "params", "trained", "feat_set")},
        **{k: v for k, v in R15_STATS.items() if k != "recent"}, "recent": list(R15_STATS["recent"]),
        "act_agreement": round(R15_STATS["act_agree"] / R15_STATS["turns"], 4) if R15_STATS["turns"] else None,
        "style_agreement": round(R15_STATS["style_agree"] / R15_STATS["style_n"], 4) if R15_STATS["style_n"] else None}
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
    for k in ("steps", "turns", "act_agree", "style_n", "style_agree", "perceived", "perceive_fail"):
        R15_STATS[k] = 0
    R15_STATS["recent"].clear()


# Round 15 (shadow only): what the raw model would have done at each turn end, next to what ran. Counts and our own
# candidate lines only (never the kid's words).
R15_STATS: dict = {"steps": 0, "turns": 0, "act_agree": 0, "style_n": 0, "style_agree": 0, "perceived": 0,
                   "perceive_fail": 0, "recent": deque(maxlen=30)}


def r15_view(m: Model, out: dict | None) -> dict | None:
    """The raw model's outputs at a step as the turn log / stats show them: act + p, the reply line it ranks first
    (candidate index, kind, p; top 3 indices), the slots (entity, option, nav arg kind) and its style tag. Numbers,
    enums and our own candidate ids only."""
    if not out:
        return None
    i = int(np.argmax(out["act"]))
    v: dict = {"act": FX.ACTS[i], "p": round(float(out["act"][i]), 3)}
    cands = m.meta.get("ptr_cands") or {}
    for name in ("reply", "ent"):
        if name in out:
            pr = np.asarray(out[name])
            top = [int(j) for j in np.argsort(-pr)[:3]]
            ids = cands.get(name) or []
            v[name] = {"i": top[0], "p": round(float(pr[top[0]]), 3), "top3": top,
                       "id": ids[top[0]][0] if top[0] < len(ids) and isinstance(ids[top[0]], list) else
                       (ids[top[0]] if top[0] < len(ids) else None)}
    if "opt" in out:
        j = int(np.argmax(out["opt"]))
        v["opt"] = {"i": j, "p": round(float(out["opt"][j]), 3)}
    if "nav_arg" in out:
        j = int(np.argmax(out["nav_arg"]))
        v["nav_arg"] = {"kind": FX.NAV_ARGS[j], "p": round(float(out["nav_arg"][j]), 3)}
    if "nav" in out:
        j = int(np.argmax(out["nav"]))
        v["nav"] = FX.NAV_INTENTS[j]
    if "style" in out:
        j = int(np.argmax(out["style"]))
        v["style"] = {"tag": FX.STYLE_TAGS[j], "p": round(float(out["style"][j]), 3)}
    return v


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
        self.rstate: dict = {}             # round 12: each routed model's own recurrent state
        self.prev: dict | None = None
        self.cur: dict | None = None
        self.n = 0
        self.turn_words = 0                # round 14: partial / final words seen since the current turn started
        self.snap: dict | None = None      # round 15: the pre-routing record of the turn being decided (perceive)
        self.state15 = None                # round 15: the raw shadow model's own recurrent state
        self.out15: dict | None = None     # ... and its outputs at the latest step

    def wants_perception(self) -> bool:
        """Round 15: the pre-routing snapshot is taken for the generator (a sink: training data) and when the raw
        shadow model is loaded; otherwise perceive() is a no-op (no extra model-server calls in the app)."""
        return self.sink is not None or (self.run_model and r15_model() is not None)

    async def perceive(self, ev: dict):
        """Round 15, called by the Session once per kid turn BEFORE the router decides (session._turn): the record of
        this turn end as it stands before any routing bookkeeping, plus Arc Tagger's read and the embedder's vector of
        the words, fetched for every turn on every path. The raw feature set reads this snapshot at the turn end, so
        its inputs never depend on the route. Shadow only: a timeout or a model-server error leaves `perc` empty."""
        self.snap = None
        if not self.wants_perception():
            return
        import asyncio
        from .. import models_client
        text = ev.get("text") or ""
        perc: dict = {}
        try:
            out, vec = await asyncio.wait_for(asyncio.gather(models_client.tag(text, "assistant"),
                                                             models_client.embed([text], "query")),
                                              timeout=None if self.sink is not None else PERCEIVE_TIMEOUT_S)
            perc = {"tag": FX.tag_view(out), "emb": (vec or [None])[0]}
            R15_STATS["perceived"] += 1
        except Exception:  # noqa: BLE001 (shadow: never let the perception read touch the turn)
            R15_STATS["perceive_fail"] += 1
        keep = getattr(self.sess, "_r7_prev", None)     # features.record remembers the previous turn: not twice
        try:
            rec = FX.record(self.sess, ev, None)
        finally:
            self.sess._r7_prev = keep
        rec["perc"] = perc
        self.snap = rec

    def step(self, ev: dict, read: dict | None = None) -> dict | None:
        self._close()
        rec = FX.record(self.sess, ev, read)
        if rec["kind"] in ("turn_end", "typed"):
            sn, self.snap = self.snap, None
            if sn is not None and (sn.get("text") or "") == (rec.get("text") or ""):
                rec["raw"] = sn          # round 15: the raw set reads the pre-routing snapshot of this turn end
        self.turn_words = turn_words_next(rec["kind"], self.turn_words)
        out = None
        if self.run_model:
            m15 = r15_model()
            if m15 is not None:          # round 15: shadow only, its own state; never consulted by a decision
                try:
                    self.out15, self.state15 = m15.step(self.state15, m15.feats(rec, self.prev), *FX.step_tokens(rec))
                    R15_STATS["steps"] += 1
                except Exception:  # noqa: BLE001
                    self.out15 = None
        if self.run_model:
            m = model()
            if m is not None:
                x = FX.step_feats(rec, self.prev)
                toks, wtok, wfeat = FX.step_tokens(rec)
                out, self.state = m.step(self.state, x, toks, wtok, wfeat)
                rm = routed_models() if mode() == "guarded" else {}
                if rm:       # round 12: every routed model steps on every event too (its state must follow the stream)
                    ro = {}
                    for name, mr in rm.items():
                        ro[name], self.rstate[name] = mr.step(self.rstate.get(name), x, toks, wtok, wfeat)
                    out = {**out, "_routed": ro}
        self.cur = {"rec": rec, "out": out, "decisions": [], "r": None, "i": self.n,
                    "bare": bare_turn(rec, self.turn_words), "out15": self.out15 if self.run_model else None}
        if rec["kind"] in ("turn_end", "typed"):
            self.turn_words = 0
        self.prev = rec
        self.n += 1
        STATS["steps"] += 1
        return out

    def emitted(self, ds: list[dict]):
        if self.cur is not None:
            self.cur["decisions"] += ds
            o15 = self.cur.get("out15")
            if o15 is not None and "style" in o15 and self.cur["rec"]["kind"] in ("turn_end", "typed"):
                # round 15 (shadow): the style head next to what steering chose for the line we say; logged, never used
                for d in ds:
                    tag = (d.get("style") or {}).get("tag") if d.get("t") == "say" else None
                    if tag:
                        R15_STATS["style_n"] += 1
                        R15_STATS["style_agree"] += int(FX.STYLE_TAGS[int(np.argmax(o15["style"]))] == tag)
                        self.cur["style_used"] = tag
                        break

    def turn_result(self, r: dict):
        if self.cur is not None:
            self.cur["r"] = {k: r.get(k) for k in ("action", "command", "nlu", "source", "needs_confirm", "place")}
            self.cur["r"]["brain"] = (r.get("readout") or {}).get("brain")
            if r.get("say"):         # round 15: the line the engine speaks (the reply head's teacher label)
                self.cur["r"]["say"] = str(r["say"])[:400]

    def flush(self):
        self._close()

    def bare(self) -> bool:
        """The current step is a heard turn end with no ear read-out at all (bare_turn): the rules decide it."""
        return bool((self.cur or {}).get("bare"))

    def explain(self, out: dict | None, text: str) -> dict:
        """The turn log (turnlog.py v2), read-only: at this turn end, the situation class, whether the bare-turn guard
        holds, the primary model's act / p (`shadow`) and each routed file's (`routed`), and (guarded) which weight file each path would
        consult: the class's policy turn, the navigation fill and the lesson-answer silencing (None = the rules)."""
        rec = (self.cur or {}).get("rec") or {}
        md = mode()
        cls = situation(rec, text)
        d: dict = {"mode": md, "cls": cls, "bare": self.bare()}
        m = model() if md != "off" else None
        if m is not None:
            d["weights"] = f"{m.meta.get('data') or '?'}/{m.meta.get('size_name') or '?'}"
        if out:
            a, p = self.model_act(out)
            d["shadow"] = {"act": a, "p": round(p, 3)}        # the primary weights' own choice (shadow), act or not
            ro = out.get("_routed") or {}
            if ro:
                d["routed"] = {n: {"act": self.model_act(o)[0], "p": round(self.model_act(o)[1], 3)} for n, o in ro.items()}
        m15 = r15_model() if md != "off" else None
        o15 = (self.cur or {}).get("out15")
        if m15 is not None and o15 is not None:      # round 15: shadow only, what the raw model would do
            d["r15"] = r15_view(m15, o15)
        if md == "guarded" and m is not None:
            thr = m.meta.get("policy") or DEFAULT_POLICY
            who = lambda c: (thr.get("routes") or {}).get(c) or ("weights" if c in (thr.get("classes") or ()) else None)  # noqa: E731
            d["picked"] = {"turn": who(cls), "nav": who("nav"), "answer": who("answer")}
        elif md == "on" and m is not None:
            d["picked"] = {"turn": "weights", "nav": "weights", "answer": "weights"}
        return d

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
                if (rc or ma == "command") and ra != "navigate":    # navigation never reaches the NLU
                    mc = FX.decode_command(cur["out"], FX.words_of(cur["rec"]["text"])) if ma == "command" else None
                    STATS["commands"] += 1
                    STATS["command_agree"] += int(bool(rc and mc and FX.same_command(rc, mc)) or (not rc and not mc))
                STATS["recent"].append({"text": cur["rec"]["text"][:80], "rules": ra, "model": ma, "p": round(p, 3)})
        o15 = cur.get("out15")
        if o15 is not None and cur["rec"]["kind"] in ("turn_end", "typed"):
            m15 = r15_model()
            v = r15_view(m15, o15) if m15 is not None else None
            if v is not None:
                R15_STATS["turns"] += 1
                R15_STATS["act_agree"] += int(v["act"] == ra)
                rp = v.get("reply") or {}
                cands = ((m15.meta.get("ptr_cands") or {}).get("reply") or [])
                R15_STATS["recent"].append({"rules": ra, "r15": v["act"], "p": v["p"], "nav_arg": (v.get("nav_arg") or {}).get("kind"),
                                            "opt": (v.get("opt") or {}).get("i"), "ent": (v.get("ent") or {}).get("id"),
                                            "reply": cands[rp["i"]] if rp and rp.get("i", 1 << 30) < len(cands) else None,
                                            "style": (v.get("style") or {}).get("tag"), "style_used": cur.get("style_used")})
        if self.sink is not None:
            self.sink.append({"rec": cur["rec"], "r": cur["r"], "rules_act": ra,
                              "decisions": [_slim(d) for d in cur["decisions"]]})

    # ---- `on` mode -------------------------------------------------------------------------------------------------
    def decide_answer(self, out: dict | None) -> bool:
        """A lesson step's answer (router outcome `answer`), `on` mode: True = the model is sure enough it is room
        chatter / not an answer to silence it (answer_policy). Off unless the weights carry a fitted threshold."""
        md = mode()
        if md not in ("on", "guarded") or not out or self.bare():
            return False
        m = model()
        thr = (m.meta.get("policy") if m is not None else None) or DEFAULT_POLICY
        if md == "guarded":
            pk = pick(thr, "answer", out, policies())
            return bool(pk) and answer_policy(*pk)
        return answer_policy(out, thr)

    def decide_nav(self, out: dict | None, offer: str | None) -> str | None:
        """`on` mode, a routed turn the router did not navigate: the model's navigation intent, or None."""
        md = mode()
        if md not in ("on", "guarded") or not out or self.bare():
            return None
        m = model()
        thr = (m.meta.get("policy") if m is not None else None) or DEFAULT_POLICY
        if md == "guarded":
            pk = pick(thr, "nav", out, policies())
            return nav_policy(pk[0], pk[1], offer=bool(offer)) if pk else None
        return nav_policy(out, thr, offer=bool(offer))

    def decide_turn(self, out: dict | None, text: str, rules_guard: bool) -> dict | None:
        """At a turn end, `on` mode: the model's decision if it may override the rules, else None (rules decide).
        -> {"act": "ignore"|"ask_clarify"|"command", "command"?: Command}."""
        md = mode()
        if md not in ("on", "guarded") or not out or self.bare():
            return None
        from ..mission import nlu
        rc = [c for c in map(nlu.valid, nlu.parse(text).get("commands") or []) if c]
        m = model()
        thr = (m.meta.get("policy") if m is not None else None) or DEFAULT_POLICY
        if md == "guarded":
            pk = pick(thr, situation((self.cur or {}).get("rec"), text), out, policies())
            if not pk:
                return None
            out, thr = pk
            thr = {**thr, **(thr.get("guarded") or {})}
        thr = learned_thr(thr, self.sess)
        b = self.sess.belief
        return policy(out, FX.words_of(text), rc, rules_guard, thr,
                      mission=bool(b.get("mission_id")) and b.get("mode") == "mission")


DEFAULT_POLICY = {"conf": CONF, "cmd": CONF, "ignore": CONF, "ask": CONF, "veto": None, "answer_ignore": None,
                  "ignore_min_words": None,
                  "nav": None}


# On-device learning (backend/app/learn/policy.py): the only policy keys a cadet's learning may move, and how far. Moves
# are only ever towards MORE careful (a higher `ignore` bar), so the shipped weights' decisions change only for turns
# whose p(ignore) falls between the shipped value and the learned one.
LEARN_BOUNDS = {"ignore": (0.95, 0.99)}


def learned_thr(thr: dict, sess) -> dict:
    lrn = getattr(sess, "learning", None)
    if lrn is None:
        return thr
    try:
        ov = lrn.policy_overrides() or {}
    except Exception:  # noqa: BLE001
        return thr
    out = dict(thr)
    for k, (lo, hi) in LEARN_BOUNDS.items():
        if k in ov and k in thr and thr[k] is not None:
            out[k] = min(hi, max(lo, max(float(thr[k]), float(ov[k]))))
    return out


def nav_policy(out: dict | None, thr: dict, offer: bool = False) -> str | None:
    """Round 7: the model navigates where the router did not (it ignored, answered or sent the turn to the brain /
    the mission NLU): only with the `nav` head (weights from round 7 on), only when p(act = navigate) and p(intent) are
    both >= thr["nav"] (fit on val to add no wrong actions; None = off), only for intents it can run without an
    argument it cannot know (features.NAV_ACTIONABLE), and taking an offer only while one is on screen.
    -> the nav intent, or None."""
    v = thr.get("nav")
    if v is None or not out or "nav" not in out:
        return None
    i = int(np.argmax(out["act"]))
    if FX.ACTS[i] != "navigate" or float(out["act"][i]) < v:
        return None
    nv = np.asarray(out["nav"])
    j = int(np.argmax(nv))
    intent = FX.NAV_INTENTS[j]
    if intent not in FX.NAV_ACTIONABLE or float(nv[j]) < v:
        return None
    if intent in ("accept_offer", "decline_offer") and not offer:
        return None
    return intent


def answer_policy(out: dict, thr: dict) -> bool:
    """Router said `answer` (a lesson step is waiting): the model may only SILENCE it, never answer or navigate in its
    place, and only when p(ignore) >= thr["answer_ignore"] (fit on val by evaluate.fit_policy to add no misses of real
    answers there; None = off, the rules' routing stands). The cost of a wrong silence is one more try for the kid;
    the cost of chatter graded as an answer is a miss on a step the kid never answered."""
    v = thr.get("answer_ignore")
    if v is None or not out:
        return False
    i = int(np.argmax(out["act"]))
    return FX.ACTS[i] == "ignore" and float(out["act"][i]) >= v


def policy(out: dict, words: list[str], rules_cmds: list[dict], rules_guard: bool, thr: dict,
           mission: bool = True) -> dict | None:
    """The cost-aware decision layer (ONE definition: runtime `on` and director_model/evaluate.py). A wrong action costs
    far more than a clarifying ask, so per-act thresholds are fit on val (evaluate.fit_policy) to add no wrong actions
    over the rules there:
      * the privacy guard always wins (rules);
      * the rules read a command (rules_cmds): it stands, unless thr["veto"] is set and the model is at least that sure
        the turn is NOT a command (a question / chatter / unclear) -> ask_clarify (mission mode only: an Academy
        command step's answer IS a command; never on yes/no);
      * no rules command: the model may fill a command (p >= thr["cmd"], the decoded Command passes nlu.valid),
        ignore (p >= thr["ignore"]) or ask (p >= thr["ask"]); else the rules decide (None).
    -> {"act": "ignore"|"ask_clarify"|"command", "command"?, "clarify"?} or None."""
    if rules_guard or not out:
        return None
    i = int(np.argmax(out["act"]))
    act, p = FX.ACTS[i], float(out["act"][i])
    if rules_cmds:
        v = thr.get("veto")
        if v is not None and mission and act in ("answer", "ignore", "ask_clarify", "navigate") and p >= v and \
                rules_cmds[0].get("type") not in ("confirm", "cancel"):
            return {"act": "ask_clarify", "clarify": clarify_options(out)}
        return None
    if act == "command" and min(p, out["_conf"] if "_conf" in out else cmd_conf(out)) >= thr.get("cmd", CONF):
        c = out["_cmd"] if "_cmd" in out else FX.decode_command(out, words)   # (_cmd/_conf: evaluate's memo)
        if c is not None:
            return {"act": "command", "command": c}
        return None
    if act == "ignore" and p >= thr.get("ignore", CONF):
        # round 9: never silence a very short turn (it is usually a real answer or a screen control said plainly,
        # e.g. "far side"); the model's silencing wins are on longer room talk and echo. None = no minimum.
        mw = thr.get("ignore_min_words")
        if mw and len([w for w in words if w]) < mw:
            return None
        return {"act": "ignore"}
    if act == "ask_clarify" and p >= thr.get("ask", CONF):
        return {"act": "ask_clarify", "clarify": clarify_options(out)}
    return None


def cmd_conf(out: dict) -> float:
    """How sure the model is of the command it would fill: the weakest of its type and main-slot probabilities."""
    ct = np.asarray(out["cmd_type"])
    k = int(np.argmax(ct))
    ps = [float(ct[k])]
    t = FX.CMD_TYPES[k]
    if t == "rule":
        ps.append(float(np.max(out["rule_when"])))
        t = FX.CMD_TYPES[int(np.argmax(out["sub_type"]))]
    if t == "allocate":
        ps += [float(np.max(out["load_to"])), float(np.max(out["amount"]))]
    elif t == "dispatch":
        ps.append(float(np.max(out["task"])))
    elif t == "query":
        ps.append(float(np.max(out["query"])))
    return min(ps)


LOAD_SAY = {"shields": "shields", "life_support": "life support", "greenhouse": "greenhouse", "science": "science",
            "rover": "rover", "comms": "radio", "heaters": "heaters"}


def clarify_options(out: dict) -> list[str]:
    """The model's two most likely base parts when it is torn between them ("Did you mean shields or heaters?")."""
    pl = np.asarray(out.get("load_to") if out.get("load_to") is not None else [])
    ct = out.get("cmd_type")
    if pl.size < 3 or ct is None or FX.CMD_TYPES[int(np.argmax(ct))] != "allocate":
        return []
    order = [j for j in np.argsort(-pl[1:]) + 1][:2]
    if pl[order[1]] < 0.15:
        return []
    return [LOAD_SAY.get(FX.LOADS[j], FX.LOADS[j]) for j in order]


def _slim(d: dict) -> dict:
    keep = ("t", "priority", "style", "nudge", "hint", "action", "source", "level", "holder", "voice", "proactive",
            "text")      # round 15: a say line's text (the reply head's teacher label; the generator's sink only)
    return {k: d[k] for k in keep if k in d}


def attach(sess, sink: list | None = None) -> Shadow | None:
    if sink is None and mode() == "off":
        return None
    return Shadow(sess, sink=sink, run_model=None if sink is None else False)
