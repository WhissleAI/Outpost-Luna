"""Runs Arc Tagger v0.3 (native int8, via Head Start's ctypes binding) over the crew transcripts and a few
kid questions, and prints what it finds. Output from 2026-11-13: docs/tagger_probe_2026-11-13.txt.

  HEADSTART=~/Desktop/work/whissle/headstart
  $HEADSTART/.venv/bin/python scripts/probe_tagger.py
"""
import json, os, sys, time
from pathlib import Path

HS = Path(os.environ.get("HEADSTART", Path.home() / "Desktop/work/whissle/headstart"))
sys.path.insert(0, str(HS))
os.chdir(HS)  # the binding resolves vendor/ and models/ relative to the Head Start repo
from server.tagger import Tagger  # noqa: E402

TX = Path(__file__).resolve().parent.parent / "data/transcripts"
FEAT = {"aristarchus", "orientale", "oriental", "ohm", "glushko", "hertzsprung", "vavilov", "integrity",
        "carroll", "carol", "earth", "moon", "orion", "reiner", "gamma"}
on = lambda L: [x["tag"].split(".")[-1] for x in (L or []) if x.get("on")]


def words_of(p):
    d = json.load(open(p))
    return [w["word"].strip() for s in d["segments"] for w in s.get("words", []) if w["word"].strip()]


for dom in ("news", "talk"):
    for p in sorted(TX.glob("*.json")):
        t = Tagger(domain=dom); w = words_of(p); t0 = time.time(); out = t.tag_text(" ".join(w)); dt = (time.time() - t0) * 1000
        ent = [s for s in out["spans"] if s["family"] == "entity"]
        num = [s for s in out["spans"] if s["family"] == "number" and s["type"] != "entity.numeral"]
        n_feat = sum(x.lower().strip(".,!?") in FEAT for x in w)
        hit = [s for s in ent if any(k in s["text"].lower() for k in FEAT)]
        print(f"\n=== [{dom}] {p.stem[:40]} | {len(w)} words | {dt:.0f} ms | {dt / len(w):.2f} ms/word")
        print(f" feature words: {n_feat}; entity spans: {len(ent)}; spans on a feature word: {len(hit)}")
        print(" entity spans:", [(s["type"].split(".")[-1], s["text"], round(s["score"], 2)) for s in ent][:25])
        print(" number spans:", [(s["type"].split(".")[-1], s["text"]) for s in num][:12])
        print(" events:", sorted({e.get("type") for e in out["events"]}))
        t.close()

print("\n=== KID QUESTIONS (domain=assistant)")
for q in ["show me where Neil Armstrong landed", "what did the astronauts say about the yellow part",
          "show me Tycho, wait no I mean Copernicus", "how big is Orientale", "is there ice on the Moon",
          "my name is Maya and I live at 42 Oak Street", "play the part where they saw the Earth",
          "why is the Moon gray", "the moon is made of cheese right", "you are stupid"]:
    t = Tagger(domain="assistant"); out = t.tag_text(q); u = (out.get("utterances") or [{}])[0]
    print(f"- {q!r}\n   spans", [(s["type"].split(".")[-1], s["text"]) for s in out["spans"] if s["type"] != "entity.numeral"],
          "| act", on(u.get("act")), "| intent", on(u.get("intent")), "| safety", on(u.get("safety")),
          "| events", [e.get("type") for e in out["events"]])
    t.close()
