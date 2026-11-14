"""Export a trained Director for the numpy runtime (backend/app/director_model/runtime.py): int8 weight matrices (one f32
scale per row; biases, norms, SSM scalars and the feature standardizer stay f32) -> weights.npz + weights.json, then
check
  1. streaming parity: runtime.Model.step one event at a time vs the torch parallel pass (SSD), both int8-dequantized;
  2. int8 vs float: torch float vs int8-rounded weights (max |dp| over heads);
  3. cost: numpy ms per step, file size;
and write the parity fixture backend/tests/fixtures/director_model_parity.npz (inputs + torch outputs of a few held-out
sessions) that backend/tests/test_director_model.py replays without torch.

  python3 export.py --run runs/r1_m --data data/ds_r1 [--split test_clean] [--thr eval.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import train as TR  # noqa: E402
from train import FX  # noqa: E402

BACKEND = HERE.parent / "backend"
OUT = BACKEND / "app" / "director_model"
FIXTURE = BACKEND / "tests" / "fixtures" / "director_model_parity.npz"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--split", default="test_clean")
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--eval", default="", help="evaluate.py json: thr_when + headline numbers go into weights.json")
    a = ap.parse_args()
    cfg = json.load(open(f"{a.run}/train.json"))
    model = TR.make(cfg["F"], cfg["size_name"])
    model.load_state_dict(torch.load(f"{a.run}/model.pt", map_location="cpu"))
    model.eval()
    sd = model.state_dict()
    qn = {n + ".weight" for n, m in model.named_modules() if isinstance(m, (torch.nn.Linear, torch.nn.Embedding))}
    arrs, deq = {}, {}
    for k, v in sd.items():
        v = v.detach().float().numpy()
        if k in qn and v.ndim == 2:
            s = np.abs(v).max(1) / 127.0 + 1e-12
            q = np.clip(np.round(v / s[:, None]), -127, 127).astype(np.int8)
            arrs[k + "::q"], arrs[k + "::s"] = q, s.astype(np.float32)
            deq[k] = torch.from_numpy(q.astype(np.float32) * s[:, None].astype(np.float32))
        else:
            arrs[k] = v.astype(np.float32)
    out = Path(a.out)
    np.savez_compressed(out / "weights.npz", **arrs)
    ev = json.load(open(a.eval)) if a.eval else {}
    meta = {"size": TR.SIZES[cfg["size_name"]], "size_name": cfg["size_name"], "params": cfg["params"], "F": cfg["F"],
            "heads": [[k, n] for k, n in TR.HEADS], "word_heads": list(FX.WORD_HEADS),
            "thr": {"when": ev.get("thr_when", 0.9)}, "run": Path(a.run).name, "data": Path(a.data).name,
            "trained": {k: cfg[k] for k in ("n_train_sessions", "n_train_steps", "best_step") if k in cfg}}
    (out / "weights.json").write_text(json.dumps(meta, indent=1))
    ss = TR.load_split(Path(a.data) / f"{a.split}.npz")[:a.n]
    q = TR.make(cfg["F"], cfg["size_name"])
    q.load_state_dict({**sd, **deq})
    q.eval()
    keys = [k for k, _ in TR.HEADS]
    d_q = 0.0
    tp = []
    with torch.no_grad():
        for s in ss:
            p1, p2 = TR.predict(model, [s])[0], TR.predict(q, [s])[0]
            d_q = max(d_q, max(float(np.abs(p1[k] - p2[k]).max()) for k in keys))
            tp.append(p2)
    sys.path.insert(0, str(BACKEND))
    import importlib
    import app.director_model.runtime as RT
    importlib.reload(RT)
    nm = RT.Model(out)
    d_s = {k: 0.0 for k in keys + list(FX.WORD_HEADS)}
    t_steps = []
    for s, p in zip(ss, tp):
        st = None
        for t in range(len(s["feats"])):
            t0 = time.perf_counter()
            r, st = nm.step(st, s["feats"][t], s["toks"][t], s["wtok"][t], s["wfeat"][t])
            t_steps.append(time.perf_counter() - t0)
            for k in keys:
                d_s[k] = max(d_s[k], float(np.abs(np.asarray(r[k]) - p[k][t]).max()))
            m = s["wtok"][t] > 0
            if m.any():
                for k in FX.WORD_HEADS:
                    d_s[k] = max(d_s[k], float(np.abs(r[k][m] - p[k][t][m]).max()))
    fx = {"feats": np.concatenate([s["feats"] for s in ss[:3]]), "toks": np.concatenate([s["toks"] for s in ss[:3]]),
          "wtok": np.concatenate([s["wtok"] for s in ss[:3]]), "wfeat": np.concatenate([s["wfeat"] for s in ss[:3]]),
          "off": np.cumsum([0] + [len(s["feats"]) for s in ss[:3]])}
    for k in keys + list(FX.WORD_HEADS):
        fx[f"p_{k}"] = np.concatenate([p[k] for p in tp[:3]])
    np.savez_compressed(FIXTURE, **fx)
    rep = {"file_bytes": os.path.getsize(out / "weights.npz"), "params": cfg["params"],
           "int8_vs_float_max_dp": round(d_q, 5),
           "numpy_stream_vs_torch_parallel_max_dp": {k: round(v, 6) for k, v in d_s.items()},
           "numpy_ms_per_step_p50": round(1000 * float(np.median(t_steps)), 3),
           "numpy_ms_per_step_p99": round(1000 * float(np.percentile(t_steps, 99)), 3)}
    (Path(a.run) / "export_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
