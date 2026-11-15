"""Re-score some sets of a finished round with each model's already-fitted policy (no val needed), and patch the
round's eval JSONs: used when a set is regenerated after the run (round 8: the OS-voice / video echo sets once their
real-ear decodes existed).

  python3 director_model/reeval.py --data director_model/data/ds_r8 --run director_model/runs/<date>-r8 \
      --sets cls_voice_echo_os,cls_video_echo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as E  # noqa: E402
import train as TR  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--sets", required=True)
    ap.add_argument("--sizes", default="m,xl")
    a = ap.parse_args()
    d, run, sets = Path(a.data), Path(a.run), a.sets.split(",")
    sh = json.loads((run / "eval_shipped.json").read_text())
    ship = E.NumpyModel(Path(sh["weights"]))
    for s in sets:
        sh["sets"][s] = E.evaluate_set(ship, d, s, sh["thr_when"], sh["policy"])
    (run / "eval_shipped.json").write_text(json.dumps(sh, indent=1))
    for size in a.sizes.split(","):
        f = run / size / "eval_candidate.json"
        ev = json.loads(f.read_text())
        cfg = json.loads((run / size / "cand" / "train.json").read_text())
        m = TR.make(cfg["F"], cfg["size_name"])
        m.load_state_dict(torch.load(run / size / "cand" / "model.pt", map_location="cpu"))
        m.eval()
        pol = {k: v for k, v in ev["policy"].items() if k != "fit"}
        for s in sets:
            ev["sets"][s] = E.evaluate_set(m, d, s, ev["thr_when"], pol)
        f.write_text(json.dumps(ev, indent=1))
        (run / size / "eval_shipped.json").write_text(json.dumps(sh, indent=1))
        print(size, {s: (ev["sets"][s]["on"]["act_acc"], ev["sets"][s]["on"]["wrong_actions"]) for s in sets})
    print("shipped", {s: (sh["sets"][s]["on"]["act_acc"], sh["sets"][s]["on"]["wrong_actions"]) for s in sets},
          "rules", {s: (sh["sets"][s]["rules"]["act_acc"], sh["sets"][s]["rules"]["wrong_actions"]) for s in sets})


if __name__ == "__main__":
    main()
