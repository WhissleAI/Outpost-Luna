"""Speech learning steps (docs/SPEECH_LEARNING.md): read, vocab and summary. Course-agnostic; voice, typing, keys and
controller all answer them. Grading is rules + the ear's words; the summary step can add the local embedder and Arc
Tagger mentions (routes.py passes them in). No LLM here: feedback.py turns results into words.

accept types (each builds up over turns, like Field School: the reply's `got` comes back as input):
  read     {passage:{title,text,source}, questions:[{id, kind, prompt, hint, yes?, ...}], fluency?}
           kind choice  {options:[{id,label,say}], answer}
           kind say     {any:[[syn,...],...], answer_line}      a short spoken / typed answer
           kind find    {answer: sentence index}                tap the sentence, say its number, or read part of it
  vocab    {items:[{id, term, kind: word|sentence, define?, distractors?, traps?:[{word, note}], sentences?}], ask?}
           word: say or pick the word from its meaning (sound-alike traps are options and are never accepted);
           sentence: use it in a sentence (spoken / typed), or pick the sentence that uses it right (keys).
           The client may send `plan` (its spaced-repetition order of item ids); the server keeps only valid ids.
  summary  {source:{kind: video|article, media? | passage?}, points:[{id, label, ask, say:[phrasing,...],
           terms?}], need, example}
           a spoken summary; covered key points add up over turns (`got`); it is never marked wrong.
"""
from __future__ import annotations

import difflib
import hashlib
import re

SPEECH_TYPES = ("read", "vocab", "summary")
Q_KINDS = ("choice", "say", "find")
SAY_RATIO = 0.75          # a spoken word matching the target word (vocab.said_score)
TRAP_MARGIN = 0.05        # the target must sound closer than every trap by this much
POINT_WORD_RATIO = 0.84   # a summary word fuzzily matching a phrasing word (ear spellings)
PHRASING_SHARE = 0.75     # share of a phrasing's content words that must be heard (>= 1; all when 1 or 2 words)
FIND_SHARE = 0.5          # read-back of a sentence: share of the kid's content words in one sentence
MAX_SUMMARY_WORDS = 400

STOP = frozenset("""
a an the of and or but nor so if then than to too for from by with without in on at into onto off out up down over
is are was were be been being am it its this that these those there here they them their we us our you your i me
my mine he she him her his hers do does did doing don dont not no yes yeah okay ok oh um uh like just really very
well so what when where who why how which can could would should will shall might must may have has had got get
said says say tell told think thought about also because there s one ones thing things stuff
""".split())
_NUM_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
              "nine": "9", "ten": "10", "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
              "sixth": "6", "last": "-1"}


# ---- text helpers ----------------------------------------------------------------------------------------------------
def norm(text: str) -> str:
    t = (text or "").lower().replace("’", "'").replace("'", "")
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", t).split())


def tokens(text: str) -> list[str]:
    return norm(text).split()


def stem(w: str) -> str:
    for suf, rep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            return w[: len(w) - len(suf)] + rep
    return w


def content(text: str) -> list[str]:
    return [stem(w) for w in tokens(text) if w not in STOP and (len(w) > 2 or w.isdigit())]


def sentences(text: str) -> list[str]:
    """The passage's sentences, in order (the find-the-sentence question counts them from 1)."""
    t = " ".join(str(text or "").split())
    out: list[str] = []
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])", t):
        if out and ABBREV.search(out[-1]):   # "A.D. 550", "U.S. law", "Dr. Smith": not a sentence end
            out[-1] += " " + s
        elif s.strip():
            out.append(s.strip())
    return out


ABBREV = re.compile(r"(?:\b(?:[A-Z]\.){1,3}|\b(?:Mr|Mrs|Ms|Dr|St|Mt|vs|ca|approx|No)\.)$")


def word_close(a: str, b: str, ratio: float = POINT_WORD_RATIO) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 4:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= ratio


def said_score(text: str, word: str) -> float:
    from .vocab import said_score as s
    return s(text, word)


def _valid_prefix(got, ids: list[str]) -> list[str]:
    out = []
    for g in got or []:
        if len(out) < len(ids) and g == ids[len(out)]:
            out.append(g)
        else:
            break
    return out


def _stable(key: str, xs: list) -> list:
    return sorted(xs, key=lambda x: hashlib.sha1(f"{key}|{x}".encode()).hexdigest())


# ---- read ----------------------------------------------------------------------------------------------------------
def option_of(q: dict, inp: dict, text: str) -> str | None:
    """A choice question's option: a tapped id, its key ("b", "two"), or words naming exactly one option."""
    opts = q.get("options") or []
    if inp.get("choice"):
        return inp["choice"] if any(o["id"] == inp["choice"] for o in opts) else None
    if not text:
        return None
    from .grade import option_index, near_name
    k = option_index(text, len(opts))
    if k is not None:
        return opts[k]["id"]
    t = f" {norm(text)} "
    hits = [o["id"] for o in opts if any(f" {norm(w)} " in t for w in [o["label"], *o.get("say", [])] if norm(w))]
    if not hits:
        hits = [o["id"] for o in opts if near_name(text, [o["label"], *o.get("say", [])])]
    return hits[0] if len(hits) == 1 else None


def sentence_of(passage_text: str, inp: dict, text: str) -> int | None:
    """Find-the-sentence: a tapped sentence ("s3", 0-based index 2), "sentence three" / "the third one", or the kid
    reading part of it back (most of their content words sit in exactly one sentence)."""
    ss = sentences(passage_text)
    c = inp.get("choice") or ""
    m = re.fullmatch(r"s(\d+)", str(c))
    if m:
        k = int(m.group(1)) - 1
        return k if 0 <= k < len(ss) else None
    if not text:
        return None
    t = norm(text)
    m = re.fullmatch(r"(?:(?:it s|its|it is|i think|the|sentence|number|line)\s+)*(\w+)(?:\s+(?:one|sentence))?", t)
    if m and m.group(1) in {**_NUM_WORDS, **{str(k): str(k) for k in range(1, 13)}}:
        v = int(_NUM_WORDS.get(m.group(1), m.group(1)))
        k = len(ss) - 1 if v == -1 else v - 1
        return k if 0 <= k < len(ss) else None
    said = set(content(text))
    if len(said) < 2:
        return None
    best, score, tie = None, 0.0, False
    for k, s in enumerate(ss):
        have = set(content(s))
        hit = len(said & have)
        sc = hit / max(1, len(said))
        if hit >= 2 and sc >= FIND_SHARE:
            if sc > score + 1e-9:
                best, score, tie = k, sc, False
            elif abs(sc - score) <= 1e-9:
                tie = True
    return None if tie else best


def _say_ok(q: dict, text: str) -> bool:
    from .grade import _has, _norm
    t = _norm(text)
    if not t:
        return False
    ok_all = all(any(_has(t, w) for w in grp) for grp in q.get("all", []))
    ok_any = not q.get("any") or any(any(_has(t, w) for w in grp) for grp in q["any"])
    return ok_all and ok_any


def grade_read(acc: dict, inp: dict, text: str) -> tuple[bool, dict]:
    qs = acc["questions"]
    ids = [q["id"] for q in qs]
    got = _valid_prefix(inp.get("got"), ids)
    if len(got) >= len(qs):
        return True, {"got": got, "next": None}
    q = qs[len(got)]
    extra: dict = {"q": q["id"]}
    kind = q.get("kind")
    if kind == "choice":
        c = option_of(q, inp, text)
        ok = c is not None and c == q["answer"]
        if c:
            extra["choice"] = c
    elif kind == "find":
        k = sentence_of(acc["passage"]["text"], inp, text)
        ok = k is not None and k == int(q["answer"])
        if k is not None:
            extra["sentence"] = k
    else:   # say
        ok = _say_ok(q, text)
    if not ok:
        return False, {"got": got, "next": q["id"], **extra}
    got = got + [q["id"]]
    done = len(got) == len(qs)
    return done, {"got": got, "next": None if done else qs[len(got)]["id"], **extra}


# ---- vocab ---------------------------------------------------------------------------------------------------------
def define_of(item: dict) -> str:
    if item.get("define"):
        return item["define"]
    from .vocab import term
    t = term(item["term"]) or {}
    return t.get("explain", "")


def word_options(item: dict) -> list[dict]:
    """[{id, word, kind: term|distractor|trap}] in a stable shuffled order; ids are opaque (o1..oN)."""
    words = [(item["term"], "term")] + [(d, "distractor") for d in item.get("distractors", [])] + \
        [(t["word"], "trap") for t in item.get("traps", [])]
    seen, uniq = set(), []
    for w, k in words:
        if w.lower() not in seen:
            seen.add(w.lower())
            uniq.append((w, k))
    order = _stable(item["term"], [w for w, _ in uniq])
    kinds = dict(uniq)
    return [{"id": f"o{k + 1}", "word": w, "kind": kinds[w]} for k, w in enumerate(order)]


def sentence_options(item: dict) -> list[dict]:
    ss = item.get("sentences") or []
    order = _stable(item["term"], [s["label"] for s in ss])
    ok = {s["label"]: bool(s.get("ok")) for s in ss}
    return [{"id": f"s{k + 1}", "label": lab, "ok": ok[lab]} for k, lab in enumerate(order)]


def vocab_plan(acc: dict, plan) -> list[str]:
    """The items asked this time, in order: the client's spaced-repetition plan when it is valid, else the authored
    order; `ask` items (default all)."""
    ids = [it["id"] for it in acc["items"]]
    n = max(1, min(len(ids), int(acc.get("ask") or len(ids))))
    p = [x for x in dict.fromkeys(plan or []) if x in ids]
    if len(p) < n:
        p += [x for x in ids if x not in p]
    return p[:n]


def item_by_id(acc: dict, iid: str) -> dict | None:
    return next((it for it in acc["items"] if it["id"] == iid), None)


def _word_said(item: dict, text: str) -> tuple[bool, str | None]:
    """(said the term, the trap word said instead or None). The term must sound closer than every trap and option."""
    target = said_score(text, item["term"])
    others = [(said_score(text, o["word"]), o) for o in word_options(item) if o["kind"] != "term"]
    best_other = max(others, key=lambda x: x[0], default=(0.0, None))
    if best_other[1] is not None and best_other[0] >= SAY_RATIO and best_other[0] >= target:
        return False, best_other[1]["word"] if best_other[1]["kind"] == "trap" else None
    ok = target >= SAY_RATIO and (target == 1.0 or target - best_other[0] >= TRAP_MARGIN)
    return ok, None


def grade_vocab(acc: dict, inp: dict, text: str) -> tuple[bool, dict]:
    plan = vocab_plan(acc, inp.get("plan"))
    got = _valid_prefix(inp.get("got"), plan)
    if len(got) >= len(plan):
        return True, {"got": got, "next": None, "plan": plan}
    item = item_by_id(acc, plan[len(got)])
    extra: dict = {"item": item["id"], "term": item["term"], "plan": plan}
    ok = False
    if item.get("kind", "word") == "word":
        c = inp.get("choice")
        if c:
            o = next((o for o in word_options(item) if o["id"] == c), None)
            ok = bool(o and o["kind"] == "term")
            extra["choice"] = c
            if o and o["kind"] == "trap":
                extra["trap"] = o["word"]
        elif text:
            from .grade import option_index
            opts = word_options(item)
            k = option_index(text, len(opts))
            if k is not None:
                ok = opts[k]["kind"] == "term"
                extra["choice"] = opts[k]["id"]
                if opts[k]["kind"] == "trap":
                    extra["trap"] = opts[k]["word"]
            else:
                ok, trap = _word_said(item, text)
                if trap:
                    extra["trap"] = trap
    else:   # sentence: use the word in a sentence (spoken / typed), or pick the sentence that uses it right
        c = inp.get("choice")
        if c:
            o = next((o for o in sentence_options(item) if o["id"] == c), None)
            ok = bool(o and o["ok"])
            extra["choice"] = c
        elif text:
            ws = tokens(text)
            used = said_score(text, item["term"]) >= SAY_RATIO
            others = [w for w in ws if not word_close(w, norm(item["term"]).replace(" ", ""), 0.75)]
            ok = used and len(ws) >= 4 and len(set(others)) >= 3
            extra["used"] = used
    if not ok:
        return False, {"got": got, "next": item["id"], **extra}
    got = got + [item["id"]]
    done = len(got) == len(plan)
    return done, {"got": got, "next": None if done else plan[len(got)], **extra}


# ---- summary -------------------------------------------------------------------------------------------------------
def _phrasing_hit(phr: str, said: list[str]) -> bool:
    want = content(phr)
    if not want:
        return False
    hits = sum(any(word_close(w, s) for s in said) for w in want)
    need = len(want) if len(want) <= 2 else max(2, int(round(PHRASING_SHARE * len(want) + 0.49)))
    return hits >= need


def lexical_points(acc: dict, text: str) -> list[str]:
    """Key points whose accepted phrasings are in the words (content words, stemmed, fuzzy for ear spellings)."""
    said = content(text)
    return [p["id"] for p in acc["points"] if any(_phrasing_hit(ph, said) for ph in [*p.get("say", []), p["label"]])]


def mention_points(acc: dict, mentions: list[str] | None) -> list[str]:
    """Key points one of whose `terms` Arc Tagger marked as a mention in the kid's words."""
    ms = {norm(m) for m in mentions or [] if norm(m)}
    return [p["id"] for p in acc["points"] if any(norm(t) in ms for t in p.get("terms", []))] if ms else []


def clauses(text: str) -> list[str]:
    """The summary cut into short spans for the embedder (sentences, then 'and' / 'because' / 'so' joins)."""
    parts = []
    for s in re.split(r"[.!?;]+|\b(?:and then|then|because|so|but)\b", text or ""):
        s = " ".join(s.split())
        if len(s.split()) >= 2:
            parts.append(s)
    return parts[:24] or ([text] if (text or "").strip() else [])


def grade_summary(acc: dict, inp: dict, text: str, embed_hits: list[str] | None = None,
                  mentions: list[str] | None = None) -> tuple[bool, dict]:
    ids = [p["id"] for p in acc["points"]]
    prior = [g for g in (inp.get("got") or []) if g in ids]
    words = " ".join((text or "").split()[:MAX_SUMMARY_WORDS])
    lex = lexical_points(acc, words) if words else []
    men = mention_points(acc, mentions)
    emb = [p for p in (embed_hits or []) if p in ids]
    heard = set(lex) | set(men) | set(emb)
    got = [i for i in ids if i in set(prior) | heard]
    new = [i for i in got if i not in prior]
    need = max(1, min(int(acc.get("need") or 2), len(ids)))
    missing = [i for i in ids if i not in got]
    how = {i: [k for k, s in (("words", lex), ("mention", men), ("meaning", emb)) if i in s] for i in new}
    return len(got) >= need, {"got": got, "new": new, "missing": missing, "need": need, "how": how}


# ---- fluency (read it yourself aloud) ------------------------------------------------------------------------------
def align(passage: list[str], heard: list[str]) -> list[tuple[int | None, int | None]]:
    """Semi-global alignment of the heard words to the passage words (free passage gaps at both ends: the kid may
    start late or stop early). Pairs (passage index | None, heard index | None)."""
    n, m = len(passage), len(heard)
    MATCH, MIS, GAP = 2, -1, -1
    eq = [[word_close(passage[i], heard[j], 0.8) for j in range(m)] for i in range(n)]
    S = [[0] * (m + 1) for _ in range(n + 1)]
    B = [[0] * (m + 1) for _ in range(n + 1)]   # 1 diag, 2 up (skip passage), 3 left (extra heard)
    for j in range(1, m + 1):
        S[0][j], B[0][j] = S[0][j - 1] + GAP, 3
    for i in range(1, n + 1):
        S[i][0], B[i][0] = 0, 2                  # free leading passage gap
        for j in range(1, m + 1):
            d = S[i - 1][j - 1] + (MATCH if eq[i - 1][j - 1] else MIS)
            u = S[i - 1][j] + GAP
            lft = S[i][j - 1] + GAP
            S[i][j], B[i][j] = max((d, 1), (u, 2), (lft, 3))
    i = max(range(n + 1), key=lambda k: S[k][m])   # free trailing passage gap
    j, out = m, []
    out += [(k, None) for k in range(n - 1, i - 1, -1)]
    while i > 0 or j > 0:
        b = B[i][j] if i > 0 and j > 0 else (2 if i > 0 else 3)
        if b == 1:
            out.append((i - 1, j - 1) if eq[i - 1][j - 1] else (i - 1, None))
            if not eq[i - 1][j - 1]:
                out.append((None, j - 1))
            i, j = i - 1, j - 1
        elif b == 2:
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    return out[::-1]


def fluency(passage_text: str, heard_text: str, seconds: float | None = None) -> dict:
    """The read-aloud numbers: words read correctly (in the part read), words a minute, skipped words (up to 5,
    content words), repeats (a word said again right after it was read). Counts only: no label, no grade."""
    P, H = tokens(passage_text), tokens(heard_text)[:600]
    if not P or not H:
        return {"correct": 0, "of": len(P), "read_to": 0, "wcpm": None, "skipped": [], "repeats": 0, "heard": len(H)}
    pairs = align(P, H)
    matched = [p for p, h in pairs if p is not None and h is not None]
    if len(matched) < 3 or len(matched) < 0.3 * len(H):   # not a reading of this passage (room talk, a stray word)
        return {"correct": 0, "of": len(P), "read_to": 0, "wcpm": None, "skipped": [], "repeats": 0, "heard": len(H)}
    lo, hi = min(matched), max(matched)
    got = set(matched)
    skipped = []
    for k in range(lo, hi + 1):
        if k not in got and P[k] not in STOP and len(P[k]) > 2 and P[k] not in skipped:
            skipped.append(P[k])
    repeats, last = 0, []
    for p, h in pairs:
        if p is not None and h is not None:
            last = (last + [P[p]])[-3:]
        elif p is None and h is not None and any(word_close(H[h], w, 0.8) for w in last):
            repeats += 1
    secs = float(seconds) if seconds else 0.0
    wcpm = int(round(len(got) / (secs / 60.0))) if secs >= 5 else None
    return {"correct": len(got), "of": len(P), "read_to": hi + 1, "wcpm": wcpm, "skipped": skipped[:5],
            "repeats": repeats, "heard": len(H), "seconds": round(secs, 1) if secs else None}


# ---- client view, options, plausibility, authoring checks ----------------------------------------------------------
def public_accept(acc: dict) -> dict:
    """What the client may see: no answers."""
    t = acc["type"]
    if t == "read":
        p = acc["passage"]
        qs = []
        for q in acc["questions"]:
            pq = {"id": q["id"], "kind": q["kind"], "prompt": q["prompt"]}
            if q["kind"] == "choice":
                pq["options"] = [{"id": o["id"], "label": o["label"]} for o in q["options"]]
            qs.append(pq)
        return {"type": t, "passage": {"title": p.get("title", ""), "text": p["text"], "source": p.get("source"),
                                       "sentences": sentences(p["text"])},
                "questions": qs, "fluency": acc.get("fluency", True)}
    if t == "vocab":
        items = []
        for it in acc["items"]:
            pi = {"id": it["id"], "kind": it.get("kind", "word"), "define": define_of(it)}
            if pi["kind"] == "word":
                pi["options"] = [{"id": o["id"], "label": o["word"]} for o in word_options(it)]
            else:
                pi["term"] = it["term"]
                pi["options"] = [{"id": o["id"], "label": o["label"]} for o in sentence_options(it)]
            items.append(pi)
        return {"type": t, "items": items, "ask": len(vocab_plan(acc, None))}   # item ids, never the words (answers)
    if t == "summary":
        src = dict(acc["source"])
        if src.get("passage"):
            src["passage"] = {**src["passage"], "sentences": sentences(src["passage"]["text"])}
        return {"type": t, "source": src, "need": max(1, min(int(acc.get("need") or 2), len(acc["points"]))),
                "points": [{"id": p["id"]} for p in acc["points"]]}
    return {"type": t}


def current(acc: dict, got: list | None, plan: list | None = None) -> dict | None:
    """The question / item the kid is on."""
    if acc["type"] == "read":
        qs = acc["questions"]
        g = _valid_prefix(got, [q["id"] for q in qs])
        return qs[len(g)] if len(g) < len(qs) else None
    if acc["type"] == "vocab":
        p = vocab_plan(acc, plan)
        g = _valid_prefix(got, p)
        return item_by_id(acc, p[len(g)]) if len(g) < len(p) else None
    return None


def step_options(acc: dict, got: list | None = None) -> list[tuple[str, list[str]]]:
    cur = current(acc, got)
    if acc["type"] == "read" and cur and cur.get("kind") == "choice":
        return [(o["id"], [o["label"], *o.get("say", [])]) for o in cur["options"]]
    if acc["type"] == "vocab" and cur and cur.get("kind", "word") == "word":
        return [(o["id"], [o["word"]]) for o in word_options(cur)]
    return []


def step_vocab(acc: dict) -> list[str]:
    """Sound-alike targets: answer words of every question / item (not traps: a trap must never be repaired into the
    term)."""
    out: list[str] = []
    if acc["type"] == "read":
        for q in acc["questions"]:
            out += [w for grp in [*q.get("any", []), *q.get("all", [])] for w in grp]
            out += [w for o in q.get("options", []) for w in [o["label"], *o.get("say", [])]]
    if acc["type"] == "vocab":
        out += [it["term"] for it in acc["items"]] + [d for it in acc["items"] for d in it.get("distractors", [])]
    return out


def plausible(acc: dict, text: str) -> bool:
    """A real try at a speech step (never room talk): a summary needs 3+ content words; read / vocab take any
    content word of the step (an answer is often one word) or an option key."""
    cw = content(text)
    t = acc["type"]
    if t == "summary":
        return len(cw) >= 3
    if t == "vocab":
        return 1 <= len(tokens(text)) <= 40 and bool(cw or re.fullmatch(r"[a-d1-4]", norm(text)))
    if t == "read":   # a word of the answer, or an option / sentence key ("b", "two", "the last one")
        return bool(cw) or bool(set(tokens(text)) & {*_NUM_WORDS, "a", "b", "c", "d", *map(str, range(1, 13))})
    return False


def answer_of(acc: dict, got: list | None, plan: list | None = None) -> dict:
    """What the card shows when CAPCOM shows this question's / item's answer."""
    cur = current(acc, got, plan)
    if acc["type"] == "read" and cur:
        if cur["kind"] == "choice":
            return {"choice": cur["answer"]}
        if cur["kind"] == "find":   # the card's sentence buttons are s1..sN
            return {"sentence": int(cur["answer"]), "choice": f"s{int(cur['answer']) + 1}"}
        return {"say": cur.get("answer_line", "")}
    if acc["type"] == "vocab" and cur:
        if cur.get("kind", "word") == "word":
            return {"choice": next(o["id"] for o in word_options(cur) if o["kind"] == "term"), "say": cur["term"]}
        right = next((o for o in sentence_options(cur) if o["ok"]), None)
        return {"choice": right["id"] if right else None, "say": right["label"] if right else cur["term"]}
    if acc["type"] == "summary":
        return {"say": acc.get("example", "")}
    return {}


def label_of_answer(acc: dict, cur: dict) -> str:
    """The answer in words, for 'Here it is: ...'."""
    if acc["type"] == "read":
        if cur["kind"] == "choice":
            return next(o["label"] for o in cur["options"] if o["id"] == cur["answer"])
        if cur["kind"] == "find":
            return f"sentence {int(cur['answer']) + 1}"
        return cur.get("answer_line", "")
    if acc["type"] == "vocab":
        if cur.get("kind", "word") == "word":
            return cur["term"]
        right = next((o for o in sentence_options(cur) if o["ok"]), None)
        return right["label"] if right else cur["term"]
    return ""


def check_step(s: dict, acc: dict) -> list[str]:
    """Authoring problems in one speech step."""
    t, out = acc.get("type"), []
    if t == "read":
        p = acc.get("passage") or {}
        if not p.get("text"):
            out.append("read: passage needs text")
        src = p.get("source") or {}
        if not (src.get("title") and str(src.get("url", "")).startswith("https://")):
            out.append("read: passage needs a {title, https url} source")
        ss = sentences(p.get("text", ""))
        if not 2 <= len(ss) <= 12:
            out.append("read: passage of 2 to 12 sentences")
        qs = acc.get("questions") or []
        if not 2 <= len(qs) <= 4 or len({q.get("id") for q in qs}) != len(qs):
            out.append("read: 2 to 4 questions with unique ids")
        for q in qs:
            qid = q.get("id")
            if q.get("kind") not in Q_KINDS:
                out.append(f"read: {qid} kind must be one of {Q_KINDS}")
            for k in ("prompt", "hint"):
                if not q.get(k) or len(str(q[k]).split()) > 16:
                    out.append(f"read: {qid} needs a {k} of 16 words or fewer")
            if q.get("kind") == "choice" and q.get("answer") not in {o.get("id") for o in q.get("options", [])}:
                out.append(f"read: {qid} answer not among options")
            if q.get("kind") == "say" and not (q.get("any") or q.get("all")):
                out.append(f"read: {qid} needs any/all word groups")
            if q.get("kind") == "say" and not q.get("answer_line"):
                out.append(f"read: {qid} needs an answer_line (shown after 3 misses)")
            if q.get("kind") == "find" and not (isinstance(q.get("answer"), int) and 0 <= q["answer"] < len(ss)):
                out.append(f"read: {qid} answer must be a sentence index")
    elif t == "vocab":
        items = acc.get("items") or []
        if not 2 <= len(items) <= 8 or len({i.get("id") for i in items}) != len(items):
            out.append("vocab: 2 to 8 items with unique ids")
        for it in items:
            iid = it.get("id")
            if not it.get("term"):
                out.append(f"vocab: {iid} needs a term")
                continue
            if it["id"] != str(it["term"]).lower():
                out.append(f"vocab: {iid} id must be the word in lower case (spaced repetition keys on it)")
            if not define_of(it):
                out.append(f"vocab: {iid} needs a define line (or a glossary term)")
            elif len(define_of(it).split()) > 20:
                out.append(f"vocab: {iid} define over 20 words")
            if it.get("kind", "word") == "word" and len(word_options(it)) < 2:
                out.append(f"vocab: {iid} needs at least one distractor or trap")
            if it.get("kind") == "sentence":
                ss = it.get("sentences") or []
                if not 2 <= len(ss) <= 3 or sum(bool(x.get("ok")) for x in ss) != 1:
                    out.append(f"vocab: {iid} needs 2 or 3 sentences, exactly one ok")
            for tr in it.get("traps", []):
                if not tr.get("word") or not tr.get("note") or len(tr["note"].split()) > 10:
                    out.append(f"vocab: {iid} trap needs a word and a note of 10 words or fewer")
    elif t == "summary":
        src = acc.get("source") or {}
        if src.get("kind") not in ("video", "article"):
            out.append("summary: source.kind video or article")
        if src.get("kind") == "video":
            from .content import VIDEO_IDS
            if src.get("media") not in VIDEO_IDS:
                out.append(f"summary: media {src.get('media')!r} is not in the video catalog")
        if src.get("kind") == "article":
            p = src.get("passage") or {}
            if not p.get("text") or not str((p.get("source") or {}).get("url", "")).startswith("https://"):
                out.append("summary: article needs text and an https source")
        pts = acc.get("points") or []
        if not 2 <= len(pts) <= 5 or len({p.get("id") for p in pts}) != len(pts):
            out.append("summary: 2 to 5 key points with unique ids")
        for p in pts:
            if not p.get("label") or len(p["label"].split()) > 10:
                out.append(f"summary: {p.get('id')} needs a label of 10 words or fewer")
            if not p.get("ask") or len(p["ask"].split()) > 10:
                out.append(f"summary: {p.get('id')} needs an ask of 10 words or fewer")
            if not p.get("say"):
                out.append(f"summary: {p.get('id')} needs accepted phrasings (say)")
        if not 1 <= int(acc.get("need") or 2) <= len(pts):
            out.append("summary: need must be 1..number of points")
        if not acc.get("example") or len(acc["example"].split()) > 30:
            out.append("summary: needs an example summary of 30 words or fewer")
    return out
