"""Space words: vocabulary terms, their sources, and the four vocab step types (docs/VOCABULARY.md).

Every term comes from data/glossary.json (the kid explanation, <= 12 words). Its source is the NASA Artemis II crew
recording where the crew actually says it (data/index/clips.json: title, nasa.gov URL, clip id and the second it's
said), so "hear it" can also play the crew saying the word.

Step types (accept.type), graded by `grade()`:
  vocab_match   {term, distractors:[term,...]}   pick the meaning of `term` (tap an option, or say the meaning:
                                                 "albedo is how bright a surface is")
  vocab_say     {term}                           hear the word, say it back (Arc ear words, fuzzy matched)
  vocab_fill    {term, sentence, distractors}    fill the ____ in `sentence` (tap a word, or say it)
  vocab_listen  {term, distractors}              hear the meaning, pick the word (tap, or say it)
The client gets options with opaque ids (o1..oN, stable order), never the answer.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
from functools import lru_cache

from fastapi import APIRouter, HTTPException

from .content import DATA

VOCAB_TYPES = ("vocab_match", "vocab_say", "vocab_fill", "vocab_listen")
SAY_RATIO = 0.75     # difflib ratio for "say it back" (ASR spellings: "albido", "regolis")
PICK_RATIO = 0.8     # a spoken word picking a word option
STOP = frozenset("a an the of and or is are it its it's in on at to by for with that this when what how from out up "
                 "as be was were i you me my so like".split())

router = APIRouter()


def _norm(t: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", (t or "").lower().replace("’", "").replace("'", "")).split())


def _content(t: str) -> set[str]:
    return {w.rstrip("s") for w in _norm(t).split() if w not in STOP and len(w) > 2}


@lru_cache(maxsize=1)
def terms() -> dict[str, dict]:
    """term -> {term, explain, forms, source:{title,url,clip_id,t,kind}}."""
    g = json.loads((DATA / "glossary.json").read_text())["terms"]
    clips = json.loads((DATA / "index" / "clips.json").read_text())["clips"]
    texts = [(c, [_norm(w[1]) for w in c["words"]]) for c in clips]
    out: dict[str, dict] = {}
    for term, v in g.items():
        forms = [f.lower() for f in v.get("forms") or [term]]
        src = None
        for c, ws in texts:
            for i in range(len(ws)):
                for f in forms:
                    fw = f.split()
                    if ws[i:i + len(fw)] == fw:
                        src = {"kind": "crew", "title": f"NASA Artemis II crew audio: {c['title']}", "url": c["url"],
                               "clip_id": c["id"], "t": round(float(c["words"][i][0]), 2)}
                        break
                if src:
                    break
            if src:
                break
        out[term] = {"term": term, "explain": v["explain"], "forms": forms,
                     "source": src or {"kind": "glossary", "title": "Ask the Moon glossary", "url": ""}}
    return out


def term(name: str) -> dict | None:
    return terms().get((name or "").lower())


# ---- options -------------------------------------------------------------------------------------------------------
def _choices(acc: dict) -> list[str]:
    """The step's terms (answer + distractors) in a stable shuffled order."""
    names = [acc["term"], *acc.get("distractors", [])]
    return sorted(dict.fromkeys(names), key=lambda n: hashlib.sha1(f"{acc['term']}|{n}".encode()).hexdigest())


def options(acc: dict) -> list[dict]:
    """[{id, term, label}] with label = the meaning (match) or the word (fill, listen)."""
    out = []
    for k, n in enumerate(_choices(acc)):
        t = term(n)
        if not t:
            continue
        out.append({"id": f"o{k + 1}", "term": n, "label": t["explain"] if acc["type"] == "vocab_match" else n})
    return out


def public_accept(acc: dict) -> dict:
    """What the client may see for a vocab step: no answer id."""
    t = term(acc["term"]) or {}
    pub = {"type": acc["type"], "source": t.get("source")}
    if acc["type"] == "vocab_say":
        pub |= {"term": acc["term"], "explain": t.get("explain")}
    else:
        pub["options"] = [{"id": o["id"], "label": o["label"]} for o in options(acc)]
    if acc["type"] == "vocab_fill":
        pub["sentence"] = acc["sentence"]
    if acc["type"] == "vocab_listen":
        pub["explain"] = t.get("explain")          # spoken; shown on request (captions, deaf / hard-of-hearing kids)
    if acc["type"] == "vocab_match":
        pub["term"] = acc["term"]
    return pub


# ---- grading -------------------------------------------------------------------------------------------------------
def said_score(text: str, word: str) -> float:
    """How closely the ASR text contains `word`: 1.0 exact (plural ok), else the best difflib ratio over 1..n+1-word
    windows with spaces removed ("earth rise" → earthrise, "al bedo" → albedo, "regolis" → regolith)."""
    t, w = _norm(text), _norm(word)
    if not t or not w:
        return 0.0
    if re.search(rf"(?<![a-z0-9]){re.escape(w)}s?(?![a-z0-9])", t):
        return 1.0
    toks, n, best = t.split(), len(w.split()), 0.0
    for k in range(len(toks)):
        for m in (n, n + 1) if n > 1 else (1, 2):
            cand = "".join(toks[k:k + m])
            if cand:
                best = max(best, difflib.SequenceMatcher(None, cand, w.replace(" ", "")).ratio())
    return 1.0 if best == 1.0 else best


def said_word(text: str, word: str, ratio: float = SAY_RATIO) -> bool:
    """Did the kid say `word`? Exact, or fuzzy within `ratio`."""
    return said_score(text, word) >= ratio


def _pick_word(text: str, acc: dict) -> str | None:
    """A spoken answer that names one word option: the best match, above PICK_RATIO and clearly ahead of the next."""
    sc = sorted(((said_score(text, o["term"]), o["id"]) for o in options(acc)), reverse=True)
    if not sc or sc[0][0] < PICK_RATIO or (len(sc) > 1 and sc[0][0] - sc[1][0] < 0.08):
        return None
    return sc[0][1]


def _pick_meaning(text: str, acc: dict) -> str | None:
    """A spoken meaning: the option whose content words overlap the answer most (>= 2 words or >= 50%), uniquely."""
    said = _content(text) - _content(acc["term"])
    best, score, tie = None, 0.0, False
    for o in options(acc):
        want = _content(o["label"])
        hit = len(said & want)
        s = hit / max(1, len(want))
        if hit >= 2 or s >= 0.5:
            if s > score:
                best, score, tie = o["id"], s, False
            elif s == score:
                tie = True
    return None if tie else best


def grade(acc: dict, inp: dict) -> tuple[bool, dict]:
    kind, text = acc["type"], (inp or {}).get("text") or ""
    right = next((o["id"] for o in options(acc) if o["term"] == acc["term"]), None)
    if kind == "vocab_say":
        return said_word(text, acc["term"]), {"term": acc["term"]}
    choice = (inp or {}).get("choice")
    if not choice and text:
        choice = _pick_meaning(text, acc) if kind == "vocab_match" else _pick_word(text, acc)
    return bool(choice) and choice == right, {"choice": choice, "term": acc["term"]}


def check_step(acc: dict) -> list[str]:
    """Authoring problems in one vocab step."""
    probs = []
    for n in [acc.get("term"), *acc.get("distractors", [])]:
        if not term(n or ""):
            probs.append(f"unknown glossary term {n!r}")
    if acc.get("type") != "vocab_say" and len(acc.get("distractors", [])) < 1:
        probs.append("needs at least one distractor")
    if acc.get("type") == "vocab_fill" and "____" not in acc.get("sentence", ""):
        probs.append("vocab_fill sentence needs a ____ blank")
    return probs


# ---- GET /api/glossary -------------------------------------------------------------------------------------------
@router.get("/api/glossary")
def glossary():
    """Every space word with its kid meaning and source (highlight.js mini cards, the Space words lesson)."""
    return {"terms": list(terms().values())}


@router.get("/api/glossary/{name}")
def glossary_term(name: str):
    t = term(name)
    if not t:
        raise HTTPException(404, "no such term")
    return t
