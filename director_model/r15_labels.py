"""Round 15: the candidate sets of the raw model's pointer heads, their embeddings, and the per-step labels.

  reply  the lines the Director can say, scored by a dot product between the model state and each line's embedding:
           card     every knowledge-card answer line (knowledge/cards.py, the brain's `answers`)
           course   every course step's prompt / hint / success / fail / reveal line (academy content)
           fixed    the Director's, CAPCOM's and the narration's fixed lines (module constants), the CAPCOM / offer
                    lines the generator plays (pools.CAPCOM_LINES, pools.OFFERS)
           seen     the lines the rules engine actually spoke in the TRAIN sets (gen_sessions meta r15.say), numbers
                    masked: the data-driven form of the Director's templates ("Copy. Shields up 30 percent.").
                    Never from val / test.
         label = the line the engine spoke at the turn end (teacher: the clean run), matched to a candidate: the same
         words with numbers masked, else the longest candidate the line contains (a callback "You asked about Tycho
         earlier." before a card line). An unmatched line stays unlabeled (-1) and counts as a coverage miss.
  ent    index 0 = no entity; then every gazetteer place (places.json), keyed by its name + kind. Label = the place
         the rules answered about (`r.place`) or the site the router picked (pick_site), on turn ends whose gold act
         is not ignore / wait / guard (0 there when the turn names none).

Writes <data>/r15_cands.npz (reply_emb, ent_emb: the embedder's doc vectors), <data>/r15_cands.json (kinds, texts,
ids; local only, data/ds* is git-ignored) and <set>.r15.npz (y_reply, y_ent aligned with the set's steps).
The embeddings come from the model server's embedder (MODEL_SERVER_URL; the round's own private server).

  MODEL_SERVER_URL=http://127.0.0.1:8371 python director_model/r15_labels.py --data director_model/data/ds_r15
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
sys.path.insert(0, str(HERE))
assert ":8200" not in os.environ.get("MODEL_SERVER_URL", ""), "never use the live demo model server"

TRAIN_SETS = ("train", "train_cov")
NO_ENT_ACTS = ("ignore", "wait", "guard")


def norm_line(t: str) -> str:
    t = (t or "").lower().replace("’", "'")
    t = re.sub(r"\d+(\.\d+)?", "#", t)
    return " ".join(re.findall(r"[a-z#']+", t))


def h8(t: str) -> str:
    return hashlib.sha1(norm_line(t).encode()).hexdigest()[:8]


def static_lines() -> list[tuple[str, str]]:
    """(kind, line) of every line the app can say from its data and code (no generated data)."""
    from app import director, narration
    from app.academy import content as AC
    from app.config import settings
    from app.gazetteer import Gazetteer
    from app.knowledge import get as brain
    from app.mission import capcom
    import pools as P
    out: list[tuple[str, str]] = []
    gaz = Gazetteer(settings.data_dir / "places.json")
    facts = json.loads((settings.data_dir / "facts.json").read_text())
    b = brain(gaz, facts)
    for c in b.cards.values():
        for lines in c["answers"].values():
            out += [("card", ln) for ln in lines if isinstance(ln, str)]
    for L in AC.course()["lessons"]:
        for st in L["steps"]:
            for k in ("prompt", "hint", "success", "fail", "reveal"):
                v = st.get(k)
                for ln in (v if isinstance(v, list) else [v]):
                    if isinstance(ln, str) and ln.strip():
                        out.append(("course", ln))
    for mod in (director, capcom, narration):
        for k, v in vars(mod).items():
            if k.isupper() and isinstance(v, str) and len(v.split()) >= 2 and not k.endswith(("_RE", "POLICY")):
                out.append(("fixed", v))
    out += [("fixed", ln) for ln in P.CAPCOM_LINES] + [("fixed", v[0]) for v in P.OFFERS.values()]
    return out


def load_meta(p: Path) -> list[dict]:
    return [json.loads(line) for line in open(p)]


def build_cands(data: Path, sets: list[str]) -> tuple[list, list]:
    """-> (reply candidates [(kind, line)], entity ids [None, place ids...])."""
    seen: dict = {}
    for name in sets:
        if not name.startswith(TRAIN_SETS):
            continue
        for m in load_meta(data / f"{name}.meta.jsonl"):
            say = ((m.get("r15") or {}).get("say") or "").strip()
            if say:
                seen[norm_line(say)] = seen.get(norm_line(say)) or say
    out, have = [], set()
    for kind, ln in static_lines() + [("seen", v) for v in seen.values()]:
        k = norm_line(ln)
        if k and k not in have:
            have.add(k)
            out.append((kind, ln))
    from app.config import settings
    from app.gazetteer import Gazetteer
    gaz = Gazetteer(settings.data_dir / "places.json")
    ents = [None] + sorted(gaz.places)
    return out, ents


class Matcher:
    def __init__(self, cands: list):
        self.keys = [norm_line(t) for _, t in cands]
        self.exact = {k: i for i, k in enumerate(self.keys)}
        self.by_len = sorted([(len(k), i) for i, k in enumerate(self.keys) if len(k) >= 16], reverse=True)

    def __call__(self, say: str | None) -> int:
        if not say:
            return -1
        k = norm_line(say)
        if k in self.exact:
            return self.exact[k]
        for _, i in self.by_len:            # the longest candidate the spoken line contains
            if self.keys[i] in k:
                return i
        return -1


async def embed_all(texts: list[str]) -> np.ndarray:
    from app import models_client
    v = await models_client.embed(texts, "doc", timeout=300.0)
    if v is None:
        raise SystemExit("r15_labels: the model server's embedder is not reachable (MODEL_SERVER_URL)")
    return np.asarray(v, np.float32)


def place_text(p) -> str:
    return f"{p.name} ({p.kind})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    d = Path(a.data)
    sets = sorted(f.name[:-len(".meta.jsonl")] for f in d.glob("*.meta.jsonl"))
    cands, ents = build_cands(d, sets)
    from app.config import settings
    from app.gazetteer import Gazetteer
    gaz = Gazetteer(settings.data_dir / "places.json")
    reply_emb = asyncio.run(embed_all([t for _, t in cands]))
    ent_emb = asyncio.run(embed_all(["no place"] + [place_text(gaz.places[e]) for e in ents[1:]]))
    np.savez_compressed(d / "r15_cands.npz", reply_emb=reply_emb, ent_emb=ent_emb)
    (d / "r15_cands.json").write_text(json.dumps({"reply": [[k, t] for k, t in cands], "ent": ents}))
    kinds = {}
    for k, _ in cands:
        kinds[k] = kinds.get(k, 0) + 1
    print(f"reply candidates {len(cands)} {kinds}; entity candidates {len(ents)}", flush=True)
    match = Matcher(cands)
    eidx = {e: i for i, e in enumerate(ents)}
    cov: dict = {}
    for name in sets:
        z = np.load(d / f"{name}.npz")
        T = int(z["off"][-1])
        ms = load_meta(d / f"{name}.meta.jsonl")
        assert len(ms) == T, (name, len(ms), T)
        yr, ye = np.full(T, -1, np.int64), np.full(T, -1, np.int64)
        c = {"say": 0, "matched": 0, "ent": 0, "ent_place": 0, "ent_unknown": 0}
        for t, m in enumerate(ms):
            r = m.get("r15")
            if not m.get("end") or r is None:
                continue
            if r.get("say"):
                c["say"] += 1
                j = match(r["say"])
                if j >= 0:
                    yr[t] = j
                    c["matched"] += 1
            if m.get("gold_act") not in NO_ENT_ACTS and m.get("gold_act") is not None:
                pl = r.get("place")
                if pl and pl not in eidx:
                    c["ent_unknown"] += 1
                    continue
                ye[t] = eidx[pl] if pl else 0
                c["ent"] += 1
                c["ent_place"] += int(bool(pl))
        np.savez_compressed(d / f"{name}.r15.npz", y_reply=yr, y_ent=ye)
        cov[name] = c
        print(f"  {name}: {c}", flush=True)
    (d / "r15_coverage.json").write_text(json.dumps(cov, indent=1))


if __name__ == "__main__":
    main()
