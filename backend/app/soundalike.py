"""Sound-alike matching of heard words against what the screen expects (round 7, docs/HANDSFREE.md).

Most wrong turns are mishears before anything else sees them: the Arc ear hears "Malapart must be" for "Malapert
Massif", "eyes" for "ice", "four side" for "far side", "comp panel" for "comm panel". The grader and the router compare
the heard words with a SHORT list of what this screen expects (the step's options, keywords and places; the offer's
words; the panel names), so a sound-alike of one of them can be read as that word.

Small, offline, no dependencies:
  key(word)        a Double-Metaphone-style consonant key (initial vowel -> A, voiced = unvoiced, silent letters dropped)
  similar(a, b)    0..1: normalised edit distance of the phonetic keys of the two phrases (spaces removed, so
                   "mallow pert" ~ "malapert", "shackle ton" ~ "shackleton") blended with the spelling similarity
  repair(text, vocab)   the heard text with each span that sounds like a vocab phrase replaced by it

What it never does (the plausible gate and the room yes/no rules stay in charge of chatter):
  - it never rewrites function words or fillers ("is", "i see", "oh", "okay"): every word of a rewritten span must be
    a content word, so "i see" never becomes "ice" and "i know" never becomes "no";
  - it never rewrites a word that already is a vocab word, a number, or a word shorter than 3 letters;
  - short targets (a key of <= 2 sounds, like "ice" = AS) need an exact sound match and a minimum spelling overlap;
  - callers use it only after the exact match failed, and only against the screen's own short list.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from functools import lru_cache

MIN_SCORE = 0.74          # similar() for a span to be read as a vocab phrase
VOWELS = set("aeiouy")

# Words that are never rewritten (function words, fillers, acknowledgements, chatter): the plausible gate's list plus a
# few sound-alike traps ("see" -> "sea"/"ice", "know" -> "no", "eye" alone is kept: "eyes" is a real mishear of "ice").
STOP = frozenset("""
a an the of and or but nor so if then than to too for from by with without in on at into onto off out up down over
is are was were be been being am it its this that these those there here they them their we us our you your i me
my mine he she him her his hers do does did done doing don dont doesn isn wasn can could would should will shall
might must may have has had having not no yes yeah yep yup nope okay ok alright right well like just really very
oh ohh ooh ah ahh uh uhh um umm hmm mm mmm huh wow whoa hey hi hello sure thing things stuff gonna wanna got get
gets let lets what whats when where who whom why how which wait sorry please thanks thank maybe guess think mean know
see saw say said look go going went come came want one two three four five six seven eight nine ten s t m ll re ve d
""".split()) - {"four"}       # "four side" is the classic mishear of "far side": four is a content word here


def norm(text: str) -> str:
    t = (text or "").lower().replace("'", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t)).strip()


@lru_cache(maxsize=8192)
def key(word: str) -> str:
    """A Double-Metaphone-style key: consonant classes, initial vowel = A, silent letters dropped.
    ice -> AS, eyes -> AS, malapert -> MLPRT, malapart -> MLPRT, far -> FR, four -> FR, sight -> ST, side -> ST."""
    w = re.sub(r"[^a-z]", "", (word or "").lower())
    if not w:
        return ""
    for a, b in (("kn", "n"), ("gn", "n"), ("pn", "n"), ("wr", "r"), ("ps", "s")):
        if w.startswith(a):
            w = b + w[2:]
            break
    if w.startswith("x"):
        w = "s" + w[1:]
    if w.startswith("wh"):
        w = "w" + w[2:]
    out: list[str] = []
    n = len(w)
    i = 0

    def at(k):
        return w[k] if 0 <= k < n else ""

    while i < n:
        c = w[i]
        nx, pv = at(i + 1), at(i - 1)
        if c in VOWELS:
            if i == 0:
                out.append("A")
            i += 1
            continue
        if c == pv and c != "c":
            i += 1
            continue
        code, step = "", 1
        if c == "b":
            code = "" if (pv == "m" and i == n - 1) else "P"
        elif c == "c":
            if nx == "h":
                code, step = ("K" if at(i + 2) in ("r", "l") else "X"), 2
            elif nx in ("i", "e", "y"):
                code = "S"
            elif nx == "k":
                code, step = "K", 2
            else:
                code = "K"
        elif c == "d":
            code, step = ("J", 2) if (nx == "g" and at(i + 2) in ("e", "i", "y")) else ("T", 1)
        elif c == "g":
            if nx == "h":
                if i + 2 >= n or at(i + 2) not in VOWELS:   # night, sight, though: silent
                    code, step = "", 2
                else:
                    code, step = "K", 2
            elif nx == "n" and (i + 2 >= n or w[i + 2:] in ("ed", "s")):
                code = ""
            elif nx in ("i", "e", "y"):
                code = "J"
            else:
                code = "K"
        elif c == "h":
            code = "H" if (nx in VOWELS and pv not in ("c", "s", "p", "t", "g")) and (i == 0 or pv in VOWELS) else ""
        elif c == "k":
            code = "" if pv == "c" else "K"
        elif c == "p":
            code, step = ("F", 2) if nx == "h" else ("P", 1)
        elif c == "q":
            code = "K"
        elif c == "s":
            if nx == "h" or (nx == "i" and at(i + 2) in ("o", "a")):
                code, step = "X", 2 if nx == "h" else 1
            elif nx == "c" and at(i + 2) == "h":
                code, step = "X", 3
            else:
                code = "S"
        elif c == "t":
            if nx == "h":
                code, step = "0", 2
            elif nx == "i" and at(i + 2) in ("o", "a"):
                code = "X"
            else:
                code = "T"
        elif c == "v":
            code = "F"
        elif c == "w" or c == "y":
            code = c.upper() if nx in VOWELS else ""
        elif c == "x":
            code = "KS"
        elif c == "z":
            code = "S"
        elif c == "j":
            code = "J"
        elif c in "flmnr":
            code = c.upper()
        if code and not (out and out[-1] == code):
            out.append(code)
        i += step
    return "".join(out)


def phrase_key(text: str) -> str:
    """The phonetic key of a whole phrase, with word boundaries removed ("mallow pert" = "malapert")."""
    ws = norm(text).split()
    if not ws:
        return ""
    k = key(ws[0])
    for w in ws[1:]:
        kw = key(w)
        if kw.startswith("A") and len(kw) > 1:     # an inner word's initial vowel is not a sound of its own
            kw = kw[1:]
        if kw and k and kw[0] == k[-1]:
            kw = kw[1:]
        k += kw
    return k


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def similar(heard: str, target: str) -> float:
    """0..1 sound-alike score of two phrases: 0.65 phonetic (edit distance of the keys) + 0.35 spelling."""
    ka, kb = phrase_key(heard), phrase_key(target)
    if not ka or not kb:
        return 0.0
    ph = 1.0 - _lev(ka, kb) / max(len(ka), len(kb))
    if min(len(ka), len(kb)) <= 2 and ka != kb:      # short keys ("AS" ice): only an exact sound match counts
        ph = min(ph, 0.4)
    sa, sb = norm(heard).replace(" ", ""), norm(target).replace(" ", "")
    sp = SequenceMatcher(None, sa, sb).ratio()
    return 0.65 * ph + 0.35 * sp


def content(w: str) -> bool:
    return len(w) >= 3 and w not in STOP and not w.isdigit()


def ok_span(span: list[str]) -> bool:
    """A heard span that may be rewritten: it starts with a content word, at least half of it is content words, and
    nothing in it is a number ("malapart must" yes; "i see", "must be", "it s" no)."""
    if not span or not content(span[0]) or any(w.isdigit() or len(w) < 2 for w in span):
        return False
    return 2 * sum(content(w) for w in span) >= len(span)


def vocab_of(phrases) -> list[str]:
    """Normalised, deduplicated vocab phrases (longest first, so "far side" wins over "far")."""
    seen, out = set(), []
    for p in phrases or []:
        q = norm(str(p))
        if q and q not in seen and any(content(w) or len(w) >= 3 for w in q.split()):
            seen.add(q)
            out.append(q)
    return sorted(out, key=lambda x: (-len(x.split()), -len(x)))


def best_span(text: str, vocab, min_score: float = MIN_SCORE) -> tuple[str, str, float, int, int] | None:
    """The best (heard span, vocab phrase, score, i, j) where heard words i..j-1 sound like a vocab phrase that is not
    already in the text; None when nothing reaches min_score."""
    ws = norm(text).split()
    vs = vocab_of(vocab)
    if not ws or not vs:
        return None
    t = " " + " ".join(ws) + " "
    # words already heard as a vocab phrase (or repaired into one) are never rewritten again ("near side" stays)
    held = set()
    for v in vs:
        vw = v.split()
        for i in range(len(ws) - len(vw) + 1):
            if ws[i:i + len(vw)] == vw:
                held.update(range(i, i + len(vw)))
    best = None
    for v in vs:
        if f" {v} " in t:
            continue
        m = len(v.split())
        vk = phrase_key(v)
        if not vk:
            continue
        for k in sorted({max(1, m - 1), m, m + 1}):
            for i in range(0, len(ws) - k + 1):
                span = ws[i:i + k]
                if not ok_span(span) or held.intersection(range(i, i + k)):
                    continue
                s = similar(" ".join(span), v)
                # a short single-sound target ("ice") needs real spelling overlap too ("eyes" yes, "guys" no)
                if len(vk) <= 2 and SequenceMatcher(None, "".join(span), v.replace(" ", "")).ratio() < 0.28:
                    continue
                if s >= min_score and (best is None or s > best[2] + 1e-9):
                    best = (" ".join(span), v, s, i, i + k)
    return best


def repair(text: str, vocab, min_score: float = MIN_SCORE, max_edits: int = 3) -> tuple[str, list[dict]]:
    """The heard text with up to `max_edits` sound-alike spans replaced by the vocab phrase they sound like.
    -> (repaired text, [{"heard", "as", "score"}]). Unchanged text and [] when nothing sounds close enough."""
    ws = norm(text).split()
    edits: list[dict] = []
    for _ in range(max_edits):
        b = best_span(" ".join(ws), vocab, min_score)
        if b is None:
            break
        span, v, s, i, j = b
        ws = ws[:i] + v.split() + ws[j:]
        edits.append({"heard": span, "as": v, "score": round(s, 3)})
    return " ".join(ws), edits


def match(text: str, phrases, min_score: float = MIN_SCORE) -> tuple[str, float] | None:
    """The one phrase of `phrases` that the text names, exactly or by sound (the best score); None when none does or
    when two different phrases tie (an ambiguous mishear is no answer)."""
    t = " " + norm(text) + " "
    vs = vocab_of(phrases)
    exact = [v for v in vs if f" {v} " in t]
    if exact:
        return exact[0], 1.0
    scored = []
    for v in vs:
        b = best_span(text, [v], min_score)
        if b:
            scored.append((b[2], v))
    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[1][0] >= scored[0][0] - 0.02 and scored[1][1] != scored[0][1]:
        return None
    return scored[0][1], scored[0][0]
