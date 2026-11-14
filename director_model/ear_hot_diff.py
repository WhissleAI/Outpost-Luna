"""Side by side: the base vs hot decodes of the ear eval (ear_hot_eval.py), where they differ.
  python3 director_model/ear_hot_diff.py [--set chatter] [--tag _part] [--n 40]"""
import argparse
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent / "cache" / "ear_hot"


def n(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower())).strip()


ap = argparse.ArgumentParser()
ap.add_argument("--set", default="")
ap.add_argument("--tag", default="")
ap.add_argument("--n", type=int, default=40)
ap.add_argument("--var", default="hot")
a = ap.parse_args()
jobs = {j["key"]: j for j in map(json.loads, open(OUT / "jobs.jsonl"))}
b = {d["key"]: d for d in map(json.loads, open(OUT / f"dec_base{a.tag}.jsonl"))}
h = {d["key"]: d for d in map(json.loads, open(OUT / f"dec_{a.var}{a.tag}.jsonl"))}
k = 0
for key, d in h.items():
    j = jobs[key]
    if a.set and j["set"] != a.set or key not in b or n(b[key]["hyp"]) == n(d["hyp"]):
        continue
    print(f"{j['set']:8} {j['frame'].get('screen'):8} ref={j['text']!r}\n   base={b[key]['hyp']!r}\n   hot ={d['hyp']!r} "
          f"rescored={d.get('rescored')} conf={d.get('conf')}")
    k += 1
    if k >= a.n:
        break
