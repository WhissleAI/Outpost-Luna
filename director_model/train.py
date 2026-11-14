"""Train the Moonbase Cadet Director: a tiny streaming Mamba-3 over the session step stream (gen_sessions.py arrays).

Model (Head Start search-director family):
  [standardized step features (F) ; mean of hashed-token embeddings of the newest K words] -> Linear -> d
  -> n x (Mamba-3 block + GELU MLP) -> LayerNorm -> heads
  class heads (one Linear, sliced): act, when, cmd_type, sub_type, amount, load_to, load_from, task, query, rule_when,
  card_attr, style, s_rate, s_loud, s_f0_iqr, barge;  word heads over the last W words (w_load, w_num, w_task):
  dot(Wq h, emb(word)) + Wf word_feats + Wb h  (as Head Start's `keep`).
Every head is masked per step (-1 = unlabeled), so each data source labels only what it knows.

  python3 train.py --data data/ds --out runs/m --size m [--steps 4000] [--device cpu|mps]
Sizes: s ~30 K (d32, 1 block, 1024x8), m ~80 K (d48, 2 blocks, 2048x8), l ~250 K (d96, 3 blocks, 4096x8).
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
         "l": dict(d=96, layers=3, d_state=16, head_dim=32, buckets=4096, emb=8)}
HEADS = list(FX.HEADS.items())
NH = sum(n for _, n in HEADS)
W_LOSS = {"act": 1.0, "when": 0.5, "cmd_type": 0.6, "sub_type": 0.3, "amount": 0.5, "load_to": 0.5, "load_from": 0.3,
          "task": 0.4, "query": 0.4, "rule_when": 0.3, "card_attr": 0.5, "style": 0.2, "s_rate": 0.1, "s_loud": 0.1,
          "s_f0_iqr": 0.1, "barge": 0.5, "w_load": 0.2, "w_num": 0.3, "w_task": 0.2}
ACT_END_W = 3.0           # act loss weight on decision steps (turn ends, rules acted) vs. waiting steps


class Director(nn.Module):
    def __init__(self, F, d=48, layers=2, d_state=16, head_dim=16, buckets=2048, emb=8, drop=0.1):
        super().__init__()
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
        self.head = nn.Linear(d, NH)
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
        for name, n in HEADS:
            r[name] = o[..., j] if n == 1 else o[..., j:j + n]
            j += n
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


def make(F, size, drop=0.1):
    return Director(F, **SIZES[size], drop=drop)


# ------------------------------------------------------------------------------------------------- data
YKEYS = [k for k, _ in HEADS] + list(FX.WORD_HEADS)


def load_split(path: Path) -> list[dict]:
    z = np.load(path)
    off = z["off"]
    arrs = {k: z[k] for k in z.files if k != "off"}
    return [{k: v[off[i]:off[i + 1]] for k, v in arrs.items()} | {"i": i} for i in range(len(off) - 1)]


def batch(ss, crop=0, rng=None):
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
    feats = np.zeros((B, T, FX.F), np.float32); toks = np.zeros((B, T, FX.K), np.int64)
    wtok = np.zeros((B, T, FX.W), np.int64); wfeat = np.zeros((B, T, FX.W, FX.WF), np.float32)
    lab = {k: np.full((B, T), -1, np.int64) for k, _ in HEADS}
    lab.update({k: np.full((B, T, FX.W), -1, np.int64) for k in FX.WORD_HEADS})
    for i, s in enumerate(ss):
        n = len(s["feats"])
        feats[i, :n] = s["feats"]; toks[i, :n] = s["toks"]; wtok[i, :n] = s["wtok"]; wfeat[i, :n] = s["wfeat"]
        for k in YKEYS:
            lab[k][i, :n] = s[f"y_{k}"]
    t = torch.from_numpy
    return t(feats), t(toks), t(wtok), t(wfeat), {k: t(v) for k, v in lab.items()}


def losses(o, lab):
    L = {}
    for k, n in HEADS:
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
    for s in ss:
        f, tk, wt, wf, _ = batch([s])
        o = model(f.to(device), tk.to(device), wt.to(device), wf.to(device))
        r = {}
        for k, n in HEADS:
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
    a = ap.parse_args()
    torch.set_num_threads(a.threads)
    torch.manual_seed(a.seed)
    rng = random.Random(a.seed)
    d = Path(a.data)
    tr = load_split(d / "train.npz")
    va = load_split(d / "val.npz")
    print(f"train {len(tr)} sessions {sum(len(s['feats']) for s in tr)} steps; val {len(va)}", flush=True)
    model = make(FX.F, a.size, a.drop)
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
                f, tk, wt, wf, lab = batch(va[i:i + 32])
                _, parts = losses(model(f.to(a.device), tk.to(a.device), wt.to(a.device), wf.to(a.device)),
                                  {k: v.to(a.device) for k, v in lab.items()})
                k_ = len(va[i:i + 32])
                for k, v in parts.items():
                    tot[k] = tot.get(k, 0) + v * k_
                n_ += k_
        model.train()
        return {k: v / n_ for k, v in tot.items()}
    model.train()
    for step in range(1, a.steps + 1):
        ss = [tr[rng.randrange(len(tr))] for _ in range(a.bs)]
        f, tk, wt, wf, lab = batch(ss, a.crop, rng)
        if a.tok_drop > 0:
            tk = tk * (torch.rand(tk.shape) >= a.tok_drop)
        f, tk, wt, wf = f.to(a.device), tk.to(a.device), wt.to(a.device), wf.to(a.device)
        if a.feat_noise > 0:
            f = f + torch.randn_like(f) * model.sd * a.feat_noise
        loss, parts = losses(model(f, tk, wt, wf), {k: v.to(a.device) for k, v in lab.items()})
        opt.zero_grad(); loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step()
        if step % 200 == 0 or step == a.steps:
            v = val_loss()
            tot = sum(W_LOSS[k] * x for k, x in v.items())
            hist.append(dict(step=step, train=parts, val=v, val_total=tot))
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
    json.dump(dict(args=vars(a), size=SIZES[a.size], size_name=a.size, params=n, F=FX.F, best_step=best[1],
                   best_val=best[0], hist=hist, n_train_sessions=len(tr),
                   n_train_steps=int(sum(len(s["feats"]) for s in tr))), open(f"{a.out}/train.json", "w"), indent=1)
    print("saved", a.out, "best step", best[1], flush=True)


if __name__ == "__main__":
    main()
