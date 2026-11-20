"""Summary feedback (docs/SPEECH_LEARNING.md §3): what a cadet hears after a spoken summary.

Offline first. v1 is a template: it names the key points covered and one missing point, in 2-3 short encouraging
sentences, never a grade, a score or "wrong". The words come only from the step's rubric (point labels written by the
lesson author), so the feedback can never state a fact the lesson does not hold.

Optional (off by default, a spike: docs/SPEECH_LEARNING.md §4): a small local instruct model (llama.cpp's server on
loopback only) may REWRITE those same results into the same 2-3 sentence shape, a little warmer and closer to the
cadet's own words. Its output must pass `guard()` (sentence and word budgets for the course's reading level, banned
words, the profanity list and Arc Tagger's kids safety tags, numbers and content words only from the rubric and the
cadet's words, the missing point and a covered point named), else the template is used. Any failure (off, slow, down,
unsafe, off-rubric) falls back to the template. Nothing leaves the computer.
"""
from __future__ import annotations

import hashlib
import ipaddress
import os
import re
from urllib.parse import urlparse

from . import speech

# Reading levels (owner decision 2: each course carries its own level). Moon: docs/COPY.md (kids 7-12); Archaeology:
# grades 9-12. Budgets for one feedback: words per sentence, words in all.
LEVELS = {
    "moon": {"sentence": 14, "total": 36},
    "archaeology": {"sentence": 20, "total": 50},
}
DEFAULT_LEVEL = "moon"
OPENERS = ("Nice summary.", "Good listening.", "Well told.", "Good work.")
ALL_DONE = ("That covers every key point.", "You got every key point.")
BANNED = re.compile(r"\b(wrong|incorrect|grade[sd]?|scor(e|es|ed|ing)|fail(ed|s|ing)?|bad|mistakes?|poor|errors?|"
                    r"points? off|ai|model|assistant|chatbot|robot|language model|as an)\b", re.I)
# Words a rewrite may add beyond the rubric and the cadet's words (warmth and glue only, no facts).
WARM = set(speech.content(
    "nice good great well told work job summary summaries listening listened listen key point points one more also "
    "remember next time try add adding mention mentioned forgot forget missed miss left out part parts important "
    "idea ideas cover covered covering every all both clear clearly really love liked like way keep going explained "
    "explain told telling talked talk noticed notice included include thing still awesome super strong careful "
    "detail details nicely spot spotted main video article watched read reading heard story"))


def level_for(lesson_id: str | None) -> dict:
    course = (lesson_id or "").split(":", 1)[0] if ":" in (lesson_id or "") else DEFAULT_LEVEL
    return LEVELS.get(course, LEVELS[DEFAULT_LEVEL])


def _join(xs: list[str]) -> str:
    xs = [x.rstrip(".") for x in xs]
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1] if xs else ""


def _pick(options, key: str) -> str:
    return options[int(hashlib.sha1(key.encode()).hexdigest(), 16) % len(options)]


def _wc(t: str) -> int:
    return len(t.split())


def split_sentences(t: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join((t or "").split())) if s]


def labels(acc: dict, ids: list[str]) -> list[str]:
    by = {p["id"]: p for p in acc["points"]}
    return [by[i]["label"] for i in ids if i in by]


def template(acc: dict, covered: list[str], missing: list[str], level: dict | None = None, key: str = "") -> list[str]:
    """The v1 feedback: 2-3 sentences. Names the covered points (up to 2 when space is short) and one missing point."""
    lv = level or LEVELS[DEFAULT_LEVEL]
    cov, miss = labels(acc, covered), labels(acc, missing[:1])
    opener = _pick(OPENERS, key + "|" + ",".join(covered))
    tail = f"One more key point: {miss[0]}." if miss else _pick(ALL_DONE, key)
    for n in (len(cov), 2, 1):
        said = f"You said {_join(cov[:n])}." if cov else ""
        tries = [[opener, said, tail], [said, tail]]
        if n == 2 and len(cov) >= 2:   # two long points: one sentence each
            tries.append([f"You said {cov[0].rstrip('.')}.", f"You also said {cov[1].rstrip('.')}.", tail])
        for lines in tries:
            lines = [x for x in lines if x]
            if all(_wc(x) <= lv["sentence"] for x in lines) and sum(map(_wc, lines)) <= lv["total"]:
                return lines
    return [x for x in (f"You said {cov[0]}." if cov else opener, f"One more key point: {miss[0]}." if miss else
                        _pick(ALL_DONE, key)) if x]


def progress_line(acc: dict, new: list[str], missing: list[str]) -> str:
    """A turn that added a point but not enough yet: what was heard, then a nudge (the next point's question)."""
    by = {p["id"]: p for p in acc["points"]}
    said = f"Yes: {_join(labels(acc, new))}." if new else ""
    ask = by[missing[0]]["ask"] if missing else ""
    return " ".join(x for x in (said, ask) if x)


# ---- the guard (every rewrite passes it, or the template is used) ---------------------------------------------------
def _allowed(acc: dict, kid_text: str) -> set[str]:
    words = list(WARM)
    for p in acc["points"]:
        for t in [p["label"], p.get("ask", ""), *p.get("say", []), *p.get("terms", [])]:
            words += speech.content(t)
    words += speech.content(kid_text or "")
    words += speech.content(acc.get("example", ""))
    return set(words)


def _names(text: str, label: str, share: float) -> bool:
    want = set(speech.content(label))
    have = speech.content(text)
    if not want:
        return False
    hit = sum(any(speech.word_close(w, h) for h in have) for w in want)
    return hit >= max(1, int(share * len(want) + 0.5))


def guard(text: str, acc: dict, covered: list[str], missing: list[str], kid_text: str = "",
          level: dict | None = None, safety_tags: list | None = None) -> tuple[bool, str]:
    """(ok, reason). The rules a rewrite must keep before it is shown or said."""
    from .. import safety
    lv = level or LEVELS[DEFAULT_LEVEL]
    t = " ".join((text or "").split())
    if not t:
        return False, "empty"
    ss = split_sentences(t)
    if not 2 <= len(ss) <= 3:
        return False, "sentences"
    if any(_wc(s) > lv["sentence"] for s in ss) or _wc(t) > lv["total"]:
        return False, "length"
    if BANNED.search(t):
        return False, "banned_word"
    if re.search(r"[*#_`<>\[\]{}|\\]|https?://", t):
        return False, "markup"
    cls = safety.classify(t, safety_tags)
    if cls["mask"] or cls["care"]:
        return False, "safety"
    allowed_text = " ".join([*(p["label"] for p in acc["points"]), *(w for p in acc["points"] for w in p.get("say", [])),
                             kid_text or "", acc.get("example", "")])
    nums_ok = set(re.findall(r"\d+(?:\.\d+)?", allowed_text))
    if any(n not in nums_ok for n in re.findall(r"\d+(?:\.\d+)?", t)):
        return False, "new_number"
    allowed = _allowed(acc, kid_text)
    unknown = [w for w in speech.content(t) if not any(speech.word_close(w, a) for a in allowed)]
    if len(set(unknown)) > 1:
        return False, "new_words:" + ",".join(sorted(set(unknown))[:4])
    if missing and not _names(t, labels(acc, missing[:1])[0], 0.6):
        return False, "missing_not_named"
    if covered and not any(_names(t, lab, 0.5) for lab in labels(acc, covered)):
        return False, "covered_not_named"
    other_missing = labels(acc, missing[1:])
    for lab in other_missing:   # a point the cadet did not cover must not be praised as covered
        if _names(t, lab, 0.8) and re.search(r"\byou (said|told|mentioned|covered|explained)\b", t, re.I):
            return False, "praised_uncovered"
    return True, "ok"


# ---- the optional local rewrite (spike) ---------------------------------------------------------------------------
SYSTEM = ("You rewrite feedback for a student's spoken summary. Use ONLY the facts given. Write 2 or 3 short, warm "
          "sentences. Name what the student covered and the one missing point. Never grade, score or say wrong. "
          "No new facts, no numbers that are not given, no questions, no lists, no emoji.")


def prompt(acc: dict, covered: list[str], missing: list[str], kid_text: str, level: dict) -> list[dict]:
    cov, miss = labels(acc, covered), labels(acc, missing[:1])
    user = (f"Student said: \"{' '.join((kid_text or '').split()[:80])}\"\n"
            f"Covered: {'; '.join(cov) or 'nothing yet'}\n"
            f"Missing: {miss[0] if miss else 'none'}\n"
            f"At most {level['sentence']} words per sentence, {level['total']} words in all.\nFeedback:")
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def llm_url() -> str | None:
    """The local rewrite server, or None. Loopback only: nothing may leave the computer (School network mode)."""
    if os.environ.get("OUTPOST_SUMMARY_LLM", "") not in ("1", "on", "true"):
        return None
    url = os.environ.get("OUTPOST_SUMMARY_LLM_URL", "http://127.0.0.1:8486")
    host = urlparse(url).hostname or ""
    try:
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
            return None
    except ValueError:
        return None
    return url


async def rewrite(messages: list[dict], url: str, timeout_s: float = 4.0) -> str | None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as c:
            r = await c.post(url.rstrip("/") + "/v1/chat/completions",
                             json={"messages": messages, "temperature": 0.2, "max_tokens": 90, "stream": False})
            r.raise_for_status()
            return (r.json()["choices"][0]["message"]["content"] or "").strip()
    except Exception:   # noqa: BLE001  (any failure: the template)
        return None


async def summary_feedback(acc: dict, covered: list[str], missing: list[str], kid_text: str = "",
                           lesson_id: str | None = None, rich: bool = False, rewrite_fn=None) -> dict:
    """{lines, say, engine: template|rewrite, why?}. `rich` = the grown-up setting asked for the rewrite; it runs only
    when the local server is configured (llm_url) or a rewrite_fn is given (tests, the eval tool)."""
    lv = level_for(lesson_id)
    base = template(acc, covered, missing, lv, key=lesson_id or "")
    out = {"lines": base, "say": " ".join(base), "engine": "template"}
    if not rich:
        return out
    url = llm_url()
    if rewrite_fn is None and not url:
        return {**out, "why": "off"}
    msgs = prompt(acc, covered, missing, kid_text, lv)
    try:
        text = await (rewrite_fn(msgs) if rewrite_fn else rewrite(msgs, url))
    except Exception:   # noqa: BLE001
        text = None
    if not text:
        return {**out, "why": "no_reply"}
    tags = []
    try:
        from .. import safety
        tags = await safety.tagger_read(text)
    except Exception:   # noqa: BLE001
        tags = []
    ok, why = guard(text, acc, covered, missing, kid_text, lv, tags)
    if not ok:
        return {**out, "why": why}
    lines = split_sentences(text)
    return {"lines": lines, "say": " ".join(lines), "engine": "rewrite"}
