"""ASR error model for Arc Mini's ear, fitted on the REAL ear-eval decodes (feat/local-ear
backend/tests/fixtures/ear_eval: 40 kid-style lines x 2 Steer TTS voices, half with classroom noise, decoded by Arc
v1.1 Mini under 4 settings), plus generic noise.

  build:  python ear_errors.py build      -> data/error_model.json (fitted on the ODD item ids only; even ids are the
                                             held-out real test set `ear_real`, see gen_sessions.py)
  use:    EM = ErrorModel.load(); EM.corrupt(words, rng, noisy=True) -> (heard_words, align)

What the real decodes show (and the model reproduces):
  * name substitutions: Shackleton -> chuckleton, Tycho -> tiger / typho, Vavilov -> vav love, Malapert -> malipart,
    de Gerlache -> digo lockheed, Cabeus -> cabins, Orientale -> oriental, regolith -> regular life, Koch -> coggie
  * near words: comms -> comes, end -> and, shields -> shield, ice in -> icing, capcom -> captain, 2 -> to
  * numbers mostly survive as digits (23/24); teen/ty confusions and 2/to, 4/for are added generically
  * in noise, hallucinated TAILS: "so so so so", "okay okay okay", "mm-mm mm-mm", "is it is it", stray phrases
  * dropped / inserted short words; false starts and fillers (generic)
`align[i]` is the index of the source word heard as word i (-1 = inserted), so labels can tell when a slot word was
destroyed.
"""
from __future__ import annotations

import difflib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "backend"))
from app.director_model.features import STOP, norm  # noqa: E402

DATA = HERE / "data"
EAR = HERE.parent / "backend" / "tests" / "fixtures" / "ear_eval"
# the current Arc ear (main) first, then two earlier decoder settings kept in data/ (same audio, older decodes)
SOURCES = [EAR / "results_arc_final.json", EAR / "results_arc_ctx_bias.json", DATA / "ear_eval_arc_tuned.json",
           DATA / "ear_eval_arc.json"]


def item_num(cid: str) -> int:
    return int(re.sub(r"\D", "", cid) or 0)


def ear_rows(which: str = "fit", sources=None):
    """Real (ref, hyp, noisy, condition) rows. which='fit' -> odd ids (error model), 'test' -> even ids."""
    out = []
    for f in sources or SOURCES:
        if not Path(f).exists():
            continue
        d = json.loads(Path(f).read_text())
        for cond, v in d["conditions"].items():
            for r in v["rows"]:
                odd = item_num(r["id"]) % 2 == 1
                if (which == "fit") == odd:
                    out.append({"ref": r["ref"], "hyp": r["hyp"], "noisy": bool(r["noisy"]), "cond": f"{Path(f).stem}:{cond}",
                                "id": r["id"], "clip": r["clip"], "states": r.get("states") or []})
    return out


def build():
    subs = defaultdict(Counter)
    tails, n_words, n_sub, n_del, n_ins = [], Counter(), Counter(), Counter(), Counter()
    for r in ear_rows("fit"):
        a, b = norm(r["ref"]).split(), norm(r["hyp"]).split()
        key = "noisy" if r["noisy"] else "clean"
        sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
        n_words[key] += len(a)
        last_ref_j = 0
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                last_ref_j = j2
            elif op == "replace":
                n_sub[key] += i2 - i1
                if i2 - i1 <= 3 and j2 - j1 <= 3:
                    subs[" ".join(a[i1:i2])][" ".join(b[j1:j2])] += 1
                last_ref_j = j2
            elif op == "delete":
                n_del[key] += i2 - i1
            elif op == "insert":
                if i1 >= len(a):          # after the reference ended: a hallucinated tail
                    tails.append(" ".join(b[j1:j2]))
                else:
                    n_ins[key] += j2 - j1
        _ = last_ref_j
    rates = {k: {"sub": n_sub[k] / max(1, n_words[k]), "del": n_del[k] / max(1, n_words[k]),
                 "ins": n_ins[k] / max(1, n_words[k])} for k in ("clean", "noisy")}
    n_noisy = sum(1 for r in ear_rows("fit") if r["noisy"])
    model = {"_note": "fitted by ear_errors.py build on the odd ear-eval ids", "rates": rates,
             "tail_rate_noisy": len(tails) / max(1, n_noisy), "tails": tails,
             "subs": {k: dict(v) for k, v in subs.items()}}
    (DATA / "error_model.json").write_text(json.dumps(model, indent=1))
    print(json.dumps({"rates": rates, "tails": len(tails), "subs": len(subs)}, indent=1))


# generic confusions (kid speech + a small streaming decoder), applied on top of the fitted table
NEAR = {"shields": ["shield", "she'll"], "comms": ["comes", "calms"], "end": ["and", "in"], "ice": ["eyes", "i"],
        "heaters": ["heater", "eaters"], "rover": ["rover's", "roller"], "science": ["signs"], "power": ["our", "tower"],
        "greenhouse": ["green house"], "shelter": ["shelters", "shell to"], "houston": ["hughes ton", "huston"],
        "radiation": ["radiate shun"], "oxygen": ["ox again"], "storm": ["store"], "buggy": ["bug e"],
        "percent": ["per cent", "presents"], "capcom": ["captain", "cap com"], "roger": ["rodger"], "copy": ["coffee"],
        "crater": ["creator", "greater"], "life": ["light"], "support": ["sport"], "more": ["four"],
        "send": ["sent", "and"], "turn": ["term"], "the": ["a"]}
NUM_CONF = {"13": "30", "30": "13", "14": "40", "40": "14", "15": "50", "50": "15", "16": "60", "60": "16",
            "17": "70", "70": "17", "18": "80", "80": "18", "19": "90", "90": "19", "2": "to", "4": "for", "8": "ate"}
FILLERS = ["um", "uh", "like", "so"]


class ErrorModel:
    def __init__(self, d: dict):
        self.d = d
        self.subs = {tuple(k.split()): [(v.split(), c) for v, c in vs.items()] for k, vs in d["subs"].items()}
        self.maxn = max((len(k) for k in self.subs), default=1)
        self.tails = [t.split() for t in d["tails"] if t.strip()]

    @classmethod
    def load(cls, path: Path = DATA / "error_model.json"):
        return cls(json.loads(path.read_text()))

    def corrupt(self, ws: list[str], rng: random.Random, noisy: bool = False, level: float = 1.0):
        """-> (heard words, align). level scales the generic noise (0 = only the fitted substitutions)."""
        rates = self.d["rates"]["noisy" if noisy else "clean"]
        p_sub = min(0.35, rates["sub"] * level + 0.02 * level)
        p_del = min(0.15, rates["del"] * level + 0.01 * level)
        out, al = [], []
        i = 0
        if rng.random() < 0.08 * level and len(ws) > 3:          # false start: "send the send the rover"
            k = rng.randint(1, 2)
            out += ws[:k] + ([rng.choice(FILLERS)] if rng.random() < 0.5 else [])
            al += [-1] * (len(out))
        while i < len(ws):
            hit = None
            for n in range(min(self.maxn, len(ws) - i), 0, -1):    # the real Arc confusions first
                key = tuple(ws[i:i + n])
                if key in self.subs and rng.random() < 0.6:
                    vs = self.subs[key]
                    tot = sum(c for _, c in vs)
                    x = rng.random() * tot
                    for v, c in vs:
                        x -= c
                        if x <= 0:
                            hit = (n, v)
                            break
                    break
            if hit:
                n, v = hit
                out += v
                al += [-1] * len(v)
                i += n
                continue
            w = ws[i]
            r = rng.random()
            if r < p_del and w in STOP:
                i += 1
                continue
            if r < p_sub:
                if w in NUM_CONF and rng.random() < 0.5:
                    out.append(NUM_CONF[w]); al.append(-1)
                elif w in NEAR:
                    out += rng.choice(NEAR[w]).split(); al += [-1] * len(out[len(al):])
                elif len(w) >= 7 and rng.random() < 0.5:               # a long name split / misheard
                    cut = rng.randint(3, len(w) - 3)
                    out += [w[:cut], w[cut:]]; al += [-1, -1]
                else:
                    out.append(w); al.append(i)
            else:
                out.append(w); al.append(i)
            if rng.random() < 0.03 * level:
                out.append(rng.choice(FILLERS)); al.append(-1)
            i += 1
        if noisy and self.tails and rng.random() < self.d["tail_rate_noisy"] * 0.6 * level:
            t = rng.choice(self.tails)
            out += t; al += [-1] * len(t)
        return out, al


def partials(ws: list[str], rng: random.Random, revise: float = 0.15):
    """The ear's word stream for one turn: partial word lists (1-2 new words each) with occasional revisions (the
    newest word shown wrong, then fixed), ending with the final words."""
    out, i = [], 0
    while i < len(ws):
        i = min(len(ws), i + rng.choice([1, 1, 2]))
        cur = list(ws[:i])
        if i < len(ws) and rng.random() < revise and cur:
            w = cur[-1]
            cur[-1] = (NEAR.get(w) or [w[:max(1, len(w) - 2)]])[0].split()[0]
        out.append(cur)
    return out


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        build()
    else:
        em = ErrorModel.load()
        rng = random.Random(0)
        for s in ["send the rover to shackleton", "shields to 40", "how deep is vavilov crater", "end shift"]:
            print(s, "->", [" ".join(em.corrupt(s.split(), rng, noisy=k)[0]) for k in (False, True)])
