"""Train the Moonbase Cadet Director: a tiny streaming Mamba-3 over the session step stream (gen_sessions.py arrays).

Model (Head Start search-director family):
  [standardized step features (F) ; mean of hashed-token embeddings of the newest K words] -> Linear -> d
  -> n x (Mamba-3 block + GELU MLP) -> LayerNorm -> heads
  class heads (one Linear, sliced): act, when, cmd_type, sub_type, amount, load_to, load_from, task, query, rule_when,
  card_attr, style, s_rate, s_loud, s_f0_iqr, barge;  word heads over the last W words (w_load, w_num, w_task):
  dot(Wq h, emb(word)) + Wf word_feats + Wb h  (as Head Start's `keep`).
Every head is masked per step (-1 = unlabeled), so each data source labels only what it knows.

  python3 train.py --data data/ds --out runs/m --size m [--steps 4000] [--device cpu|mps]
Sizes: s ~30 K (d32, 1 block, 1024x8), m ~80 K (d48, 2 blocks, 2048x8), l ~250 K (d96, 3 blocks, 4096x8),
xl (round 7) d128, 4 blocks, 8192x16.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as Fn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "backend"))
from mamba3 import Mamba3Layer, mamba3_layer_ssd  # noqa: E402
from app.director_model import features as FX  # noqa: E402

SIZES = {"s": dict(d=32, layers=1, d_state=16, head_dim=16, buckets=1024, emb=8),
         "m": dict(d=48, layers=2, d_state=16, head_dim=16, buckets=2048, emb=8),
         "l": dict(d=96, layers=3, d_state=16, head_dim=32, buckets=4096, emb=8),
         # round 7: ~5-10x m, still < 1 M params, numpy int8 runtime (runtime.py reports its step latency)
         "xl": dict(d=128, layers=4, d_state=16, head_dim=32, buckets=8192, emb=16)}
HEADS = list(FX.HEADS.items())
NH = sum(n for _, n in HEADS)
W_LOSS = {"opt": 0.3, "nav_arg": 0.3, "reply": 0.5, "ent": 0.3,    # round 15 (raw set): slot + pointer heads
          "act": 1.0, "when": 0.5, "cmd_type": 0.6, "sub_type": 0.3, "amount": 0.5, "load_to": 0.5, "load_from": 0.3,
          "task": 0.4, "query": 0.4, "rule_when": 0.3, "card_attr": 0.5, "style": 0.2, "s_rate": 0.1, "s_loud": 0.1,
          "s_f0_iqr": 0.1, "barge": 0.5, "nav": 0.6, "w_load": 0.2, "w_num": 0.3, "w_task": 0.2, "fp_exec": 1.0}
ACT_END_W = 3.0
EXEC_IDX = tuple(FX.ACTS.index(a) for a in ("command", "confirm_yes", "confirm_no"))
FP_EXEC = 0.0             # --fp-exec: weight of the false-execution penalty           # act loss weight on decision steps (turn ends, rules acted) vs. waiting steps


class Director(nn.Module):
    def __init__(self, F, d=48, layers=2, d_state=16, head_dim=16, buckets=2048, emb=8, drop=0.1, heads=None,
                 ptr=None):
        """heads: [(name, n)] class heads (default the legacy HEADS); ptr (round 15): {name: (E [N, 384] fixed
        candidate embeddings, r)}: pointer heads scoring each candidate by (P e_c) . q(h) / sqrt(r)."""
        super().__init__()
        self.heads = list(heads or HEADS)
        nh = sum(n for _, n in self.heads)
        self.buckets = buckets
        self.register_buffer("mu", torch.zeros(F))
        self.register_buffer("sd", torch.ones(F))
        self.emb = nn.Embedding(buckets, emb, padding_idx=0)
        self.inp = nn.Linear(F + emb, d)
        self.blocks = nn.ModuleList([Mamba3Layer(d, d_state=d_state, rank=1, head_dim=head_dim) for _ in range(layers)])
        self.mlps = nn.ModuleList([nn.Sequential(nn.LayerNorm(d), nn.Linear(d, 2 * d), nn.GELU(), nn.Linear(2 * d, d),
                                                 nn.Dropout(drop)) for _ in range(layers)])
        self.drop = nn.Dropout(drop)
        self.norm = nn.LayerNorm(d)
        self.head = nn.Linear(d, nh)
        self.ptr_r = {}
        for name, (E, r) in (ptr or {}).items():
            self.register_buffer(f"ptr_{name}_E", torch.as_tensor(np.asarray(E), dtype=torch.float32))
            setattr(self, f"ptr_{name}_P", nn.Linear(int(np.asarray(E).shape[1]), r, bias=False))
            setattr(self, f"ptr_{name}_q", nn.Linear(d, r))
            self.ptr_r[name] = r
        nw = len(FX.WORD_HEADS)
        self.wq = nn.Linear(d, nw * emb)
        self.wf = nn.Linear(FX.WF, nw)
        self.wb = nn.Linear(d, nw)
        self.emb_dim = emb

    def _tok(self, t):
        return t.remainder(self.buckets) * (t > 0)

    def embed_in(self, feats, toks):
        e = self.emb(self._tok(toks))
        m = (toks > 0).float().unsqueeze(-1)
        bag = (e * m).sum(-2) / m.sum(-2).clamp(min=1)
        return self.drop(self.inp(torch.cat([(feats - self.mu) / self.sd, bag], -1)))

    def out(self, h, wtok, wfeat):
        h = self.norm(h)
        o = self.head(h)
        r, j = {}, 0
        for name, n in self.heads:
            r[name] = o[..., j] if n == 1 else o[..., j:j + n]
            j += n
        for name, rr in self.ptr_r.items():
            K = getattr(self, f"ptr_{name}_P")(getattr(self, f"ptr_{name}_E"))          # N r
            r[name] = getattr(self, f"ptr_{name}_q")(h) @ K.T / float(np.sqrt(rr))     # ... N
        we = self.emb(self._tok(wtok))                                    # ... W E
        q = self.wq(h).unflatten(-1, (len(FX.WORD_HEADS), self.emb_dim))  # ... 3 E
        wl = torch.einsum("...we,...ke->...wk", we, q) + self.wf(wfeat) + self.wb(h).unsqueeze(-2)
        for i, name in enumerate(FX.WORD_HEADS):
            r[name] = wl[..., i].masked_fill(wtok == 0, -1e4)
        return r

    def forward(self, feats, toks, wtok, wfeat):
        x = self.embed_in(feats, toks)
        for blk, mlp in zip(self.blocks, self.mlps):
            x = x + mamba3_layer_ssd(blk, x, chunk=64)
            x = x + mlp(x)
        return self.out(x, wtok, wfeat)

    @torch.no_grad()
    def step(self, state, feats, toks, wtok, wfeat):
        x = self.embed_in(feats[None], toks[None])
        state = state or [(None, None)] * len(self.blocks)
        new = []
        for (h, bx), blk, mlp in zip(state, self.blocks, self.mlps):
            y, h, bx = blk.step(x, h, bx)
            x = x + y
            x = x + mlp(x)
            new.append((h, bx))
        o = self.out(x, wtok[None], wfeat[None])
        return {k: v[0] for k, v in o.items()}, new


def make(F, size, drop=0.1, heads=None, ptr=None):
    return Director(F, **SIZES[size], drop=drop, heads=heads, ptr=ptr)


PTR_R = 64


def r15_spec(data_dir: Path) -> tuple[list, dict]:
    """Round 15: the raw model's heads: the legacy class heads + opt / nav_arg, and the reply / entity pointers over
    the candidate embeddings r15_labels.py wrote (data_dir / r15_cands.npz)."""
    z = np.load(Path(data_dir) / "r15_cands.npz")
    return HEADS + list(FX.HEADS_R15.items()), {"reply": (z["reply_emb"], PTR_R), "ent": (z["ent_emb"], PTR_R)}


def make_from_cfg(cfg: dict, data_dir: Path | None = None, drop: float = 0.1):
    """A model as train.json describes it (round 15: feat_set raw + its heads; older runs: the legacy Director)."""
    if cfg.get("r15"):
        heads, ptr = r15_spec(Path(cfg.get("cands_dir") or data_dir))
        return make(cfg["F"], cfg["size_name"], drop, heads, ptr)
    return make(cfg["F"], cfg["size_name"], drop)


# ------------------------------------------------------------------------------------------------- data
YKEYS = [k for k, _ in HEADS] + list(FX.WORD_HEADS)
PTR_KEYS = ["reply", "ent"]          # round 15 pointer heads (labels: <set>.r15.npz)


def load_split(path: Path, feat_set: str = "full") -> list[dict]:
    """Sessions of one set. feat_set "raw" (round 15): `feats` is the raw set (features.raw_feats, stored f16), and the
    reply / entity labels come from the side file r15_labels.py wrote (<set>.r15.npz)."""
    z = np.load(path)
    off = z["off"]
    keep = [k for k in z.files if k != "off" and not (k == "feats_raw" and feat_set != "raw")
            and not (k == "feats" and feat_set == "raw")]
    arrs = {k: z[k] for k in keep}
    if feat_set == "raw":
        arrs["feats"] = arrs.pop("feats_raw").astype(np.float32)
        side = Path(str(path)[:-4] + ".r15.npz")
        if side.exists():
            zs = np.load(side)
            arrs.update({k: zs[k] for k in zs.files})
    return [{k: v[off[i]:off[i + 1]] for k, v in arrs.items()} | {"i": i} for i in range(len(off) - 1)]


def batch(ss, crop=0, rng=None, heads=None):
    if crop:
        out = []
        for s in ss:
            n = len(s["feats"])
            if n > crop:
                a = rng.randrange(0, n - crop + 1) if rng.random() < 0.5 else 0
                s = {k: (v[a:a + crop] if hasattr(v, "__len__") else v) for k, v in s.items()}
            out.append(s)
        ss = out
    T = max(len(s["feats"]) for s in ss)
    B = len(ss)
    Fd = ss[0]["feats"].shape[1]          # the set's own width (legacy prefix, or the round-15 raw set)
    feats = np.zeros((B, T, Fd), np.float32); toks = np.zeros((B, T, FX.K), np.int64)
    wtok = np.zeros((B, T, FX.W), np.int64); wfeat = np.zeros((B, T, FX.W, FX.WF), np.float32)
    keys = [k for k, _ in (heads or HEADS)] + PTR_KEYS * bool(heads)
    lab = {k: np.full((B, T), -1, np.int64) for k in keys}
    lab.update({k: np.full((B, T, FX.W), -1, np.int64) for k in FX.WORD_HEADS})
    for i, s in enumerate(ss):
        n = len(s["feats"])
        feats[i, :n] = s["feats"]; toks[i, :n] = s["toks"]; wtok[i, :n] = s["wtok"]; wfeat[i, :n] = s["wfeat"]
        for k in keys + list(FX.WORD_HEADS):
            if f"y_{k}" in s:             # a label the set does not carry stays masked (-1)
                lab[k][i, :n] = s[f"y_{k}"]
    t = torch.from_numpy
    return t(feats), t(toks), t(wtok), t(wfeat), {k: t(v) for k, v in lab.items()}


def losses(o, lab, heads=None):
    L = {}
    for k, n in list(heads or HEADS) + [(p, 0) for p in PTR_KEYS if p in o]:
        y = lab[k]
        m = y >= 0
        if not m.any():
            L[k] = o[k].sum() * 0
            continue
        if n == 1:
            L[k] = Fn.binary_cross_entropy_with_logits(o[k][m], y[m].float())
        elif k == "act":
            w = torch.where(y[m] > 0, ACT_END_W, 1.0)
            L[k] = (Fn.cross_entropy(o[k][m], y[m], reduction="none") * w).sum() / w.sum()
            if FP_EXEC > 0:   # cost-sensitive: probability of executing (command / confirm) where the kid meant otherwise
                dec = m & (y > 0) & ~((y == EXEC_IDX[0]) | (y == EXEC_IDX[1]) | (y == EXEC_IDX[2]))
                if dec.any():
                    pe = torch.softmax(o[k][dec], -1)[:, list(EXEC_IDX)].sum(-1)
                    L["fp_exec"] = -torch.log1p(-pe.clamp(max=0.999)).mean()
        else:
            L[k] = Fn.cross_entropy(o[k][m], y[m])
    for k in FX.WORD_HEADS:
        y = lab[k]
        m = y >= 0
        L[k] = Fn.binary_cross_entropy_with_logits(o[k][m], y[m].float()) if m.any() else o[k].sum() * 0
    return sum(W_LOSS[k] * v for k, v in L.items()), {k: float(v.detach()) for k, v in L.items()}


@torch.no_grad()
def predict(model, ss, device="cpu"):
    """-> per session {head: probs [T, ...]} (softmax / sigmoid)."""
    model.eval()
    res = []
    hs = getattr(model, "heads", HEADS)
    for s in ss:
        f, tk, wt, wf, _ = batch([s], heads=hs if hs is not HEADS else None)
        o = model(f.to(device), tk.to(device), wt.to(device), wf.to(device))
        r = {}
        for k in getattr(model, "ptr_r", {}):
            r[k] = torch.softmax(o[k][0], -1).cpu().numpy()
        for k, n in hs:
            r[k] = (torch.sigmoid(o[k][0]) if n == 1 else torch.softmax(o[k][0], -1)).cpu().numpy()
        for k in FX.WORD_HEADS:
            r[k] = torch.sigmoid(o[k][0]).cpu().numpy()
        res.append(r)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE / "data" / "ds"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="m", choices=list(SIZES))
    ap.add_argument("--steps", type=int, default=4000)
    ap.add_argument("--bs", type=int, default=16)
    ap.add_argument("--crop", type=int, default=256)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--wd", type=float, default=0.05)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--tok-drop", type=float, default=0.15)
    ap.add_argument("--drop", type=float, default=0.1)
    ap.add_argument("--feat-noise", type=float, default=0.03)
    ap.add_argument("--patience", type=int, default=8, help="evals (every 200 steps) without val improvement")
    ap.add_argument("--fp-exec", type=float, default=0.0, help="weight of the false-execution penalty")
    ap.add_argument("--feats", default="full", choices=list(FX.FEATURE_SETS), help="round 15: the feature set "
                    "(full = the legacy vector every shipped file reads; raw = perception + state only)")
    ap.add_argument("--r15", action="store_true", help="round 15: the reply / entity pointer heads and the opt / "
                    "nav_arg slot heads (needs r15_labels.py's r15_cands.npz and <set>.r15.npz in --data)")
    a = ap.parse_args()
    global FP_EXEC
    FP_EXEC = a.fp_exec
    W_LOSS["fp_exec"] = a.fp_exec
    torch.set_num_threads(a.threads)
    torch.manual_seed(a.seed)
    rng = random.Random(a.seed)
    d = Path(a.data)
    # train.npz, or the generator's shards train_s*.npz (gen_sessions.py --shard; no merged copy on disk)
    fs = a.feats
    tr = load_split(d / "train.npz", fs) if (d / "train.npz").exists() else \
        [s for f in sorted(d.glob("train_s*.npz")) if not f.name.endswith(".r15.npz") for s in load_split(f, fs)]
    # round 8: the coverage sweep sessions (gen_sessions.py --cov-sessions), one file or its shards
    tr += [s for f in sorted(d.glob("train_cov*.npz")) if not f.name.endswith(".r15.npz") for s in load_split(f, fs)]
    va = load_split(d / "val.npz", fs)
    print(f"train {len(tr)} sessions {sum(len(s['feats']) for s in tr)} steps; val {len(va)}", flush=True)
    Fd = int(tr[0]["feats"].shape[1])
    heads, ptr = r15_spec(d) if a.r15 else (None, None)
    model = make(Fd, a.size, a.drop, heads, ptr)
    hs = model.heads if a.r15 else None
    allf = np.concatenate([s["feats"] for s in tr])
    model.mu.copy_(torch.from_numpy(allf.mean(0)))
    model.sd.copy_(torch.from_numpy(allf.std(0) + 1e-2))
    model.to(a.device)
    n = sum(p.numel() for p in model.parameters())
    print(f"params {n:,} ({a.size})", flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=a.wd)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=a.steps, pct_start=0.05)
    hist, best, bad, t0 = [], None, 0, time.time()

    def val_loss():
        model.eval()
        tot, n_ = {}, 0
        with torch.no_grad():
            for i in range(0, len(va), 32):
                f, tk, wt, wf, lab = batch(va[i:i + 32], heads=hs)
                _, parts = losses(model(f.to(a.device), tk.to(a.device), wt.to(a.device), wf.to(a.device)),
                                  {k: v.to(a.device) for k, v in lab.items()}, hs)
                k_ = len(va[i:i + 32])
                for k, v in parts.items():
                    tot[k] = tot.get(k, 0) + v * k_
                n_ += k_
        model.train()
        return {k: v / n_ for k, v in tot.items()}
    model.train()
    for step in range(1, a.steps + 1):
        ss = [tr[rng.randrange(len(tr))] for _ in range(a.bs)]
        f, tk, wt, wf, lab = batch(ss, a.crop, rng, heads=hs)
        if a.tok_drop > 0:
            tk = tk * (torch.rand(tk.shape) >= a.tok_drop)
        f, tk, wt, wf = f.to(a.device), tk.to(a.device), wt.to(a.device), wf.to(a.device)
        if a.feat_noise > 0:
            f = f + torch.randn_like(f) * model.sd * a.feat_noise
        loss, parts = losses(model(f, tk, wt, wf), {k: v.to(a.device) for k, v in lab.items()}, hs)
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step()
        if step % 200 == 0 or step == a.steps:
            v = val_loss()
            tot = sum(W_LOSS[k] * x for k, x in v.items())
            hist.append(dict(step=step, train=parts, val=v, val_total=tot))
            if a.r15:
                print("  r15 val " + " ".join(f"{k} {v[k]:.3f}" for k in ("opt", "nav_arg", "reply", "ent") if k in v),
                      flush=True)
            print(f"step {step} train {float(loss):.3f} val {tot:.3f} act {v['act']:.3f} cmd {v['cmd_type']:.3f} "
                  f"attr {v['card_attr']:.3f} when {v['when']:.3f} barge {v['barge']:.3f} ({time.time() - t0:.0f} s)",
                  flush=True)
            if best is None or tot < best[0]:
                best, bad = (tot, step, {k: x.detach().cpu().clone() for k, x in model.state_dict().items()}), 0
            else:
                bad += 1
                if bad >= a.patience:
                    print("early stop", flush=True)
                    break
    os.makedirs(a.out, exist_ok=True)
    torch.save(best[2], f"{a.out}/model.pt")
    json.dump(dict(args=vars(a), size=SIZES[a.size], size_name=a.size, params=n, F=Fd, feat_set=fs, r15=bool(a.r15),
                   cands_dir=str(d.resolve()) if a.r15 else None, best_step=best[1],
                   best_val=best[0], hist=hist, n_train_sessions=len(tr),
                   n_train_steps=int(sum(len(s["feats"]) for s in tr))), open(f"{a.out}/train.json", "w"), indent=1)
    print("saved", a.out, "best step", best[1], flush=True)


if __name__ == "__main__":
    main()
