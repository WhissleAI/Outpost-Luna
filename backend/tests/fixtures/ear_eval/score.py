"""Scoring for the ear eval: WER after normalization (lowercase, no punctuation, number words -> digits), exact name hits,
number hits. Shared by eval_arc.py (model_server venv) and eval_flux.py (backend venv); stdlib only."""
import re

ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
        "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
        "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


def norm(t: str) -> list[str]:
    t = (t or "").lower().replace("%", " percent ").replace("-", " ").replace("’", "'")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    toks, out, i = t.split(), [], 0
    while i < len(toks):
        w = toks[i]
        if w in TENS:
            v = TENS[w]
            if i + 1 < len(toks) and toks[i + 1] in ONES and 0 < ONES[toks[i + 1]] < 10:
                v += ONES[toks[i + 1]]
                i += 1
            out.append(str(v))
        elif w in ONES:
            out.append(str(ONES[w]))
        elif w == "hundred" and out and out[-1].isdigit():
            out[-1] = str(int(out[-1]) * 100)
        else:
            out.append(w.strip("'"))
        i += 1
    return [w for w in out if w]


def edits(r: list[str], h: list[str]) -> int:
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)]


def has(hyp_toks: list[str], phrase: str) -> bool:
    p = norm(phrase)
    return any(hyp_toks[i:i + len(p)] == p for i in range(len(hyp_toks) - len(p) + 1)) if p else True


def score(item: dict, hyp: str) -> dict:
    r, h = norm(item["text"]), norm(hyp)
    return {"err": edits(r, h), "n": len(r),
            "names": [has(h, n) for n in item["names"]], "numbers": [str(x) in h for x in item["numbers"]]}


def summarize(rows: list[dict]) -> dict:
    E, N = sum(r["err"] for r in rows), sum(r["n"] for r in rows)
    nm = [x for r in rows for x in r["names"]]
    nu = [x for r in rows for x in r["numbers"]]
    return {"clips": len(rows), "wer": round(E / max(N, 1), 3), "names": f"{sum(nm)}/{len(nm)}",
            "name_acc": round(sum(nm) / max(len(nm), 1), 3), "numbers": f"{sum(nu)}/{len(nu)}",
            "number_acc": round(sum(nu) / max(len(nu), 1), 3)}
