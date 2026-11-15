"""The narration rule: what a line SAYS can differ from what the screen SHOWS.

"mSv" stays "mSv" on screen (course cards, the cockpit's dose readout), but every voice says "millisieverts": the OS
voices (macOS `say`, Windows WinRT / SAPI) and Aura read the unit as the letters "M S V", which a kid can't map to
anything, and the open mic then heard "m s v" coming back and cut the line (owner bug, Flight School Radiation step 5).

tts.speak() applies spoken() to the text (and the next sentence) before any engine, so the rule is engine-agnostic.
The word timings the engine returns are for the spoken words; display_timings() maps them back onto the display words,
so the captions (which show the screen text) stay in step. frontend/src/narration.js mirrors the table for the
browser-voice fallback and the echo references; tests/test_narration.py and frontend/tests/narration.test.js check
the same cases.
"""
from __future__ import annotations

import difflib
import re

RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(\d+(?:\.\d+)?)\s*mSv\s*/\s*h\b"), r"\1 millisieverts an hour"),
    (re.compile(r"\bmSv\s*/\s*h\b"), "millisieverts an hour"),
    (re.compile(r"\bgame-mSv\b"), "game millisieverts"),
    (re.compile(r"\b([Aa])n\s+mSv\b"), r"\1 millisievert"),
    (re.compile(r"\b([Oo]ne|1)\s+mSv\b"), r"\1 millisievert"),
    (re.compile(r"\bmSv\b"), "millisieverts"),
]


def spoken(text: str) -> str:
    """The spoken form of a line (unchanged when no rule applies)."""
    t = text or ""
    for rx, to in RULES:
        t = rx.sub(to, t)
    return t


def display_timings(display: str, said: str, words: str) -> str:
    """Word timings ("startMs-endMs,…", one per whitespace word of `said`) → one per word of `display`.

    Equal word counts pass through. Otherwise the two word lists are aligned (difflib on lower-cased words): a kept word
    keeps its timing, a replaced run of display words shares the span of the spoken words that replaced it.
    """
    if not words or display == said:
        return words
    d, s = display.split(), said.split()
    try:
        spans = [tuple(int(x) for x in p.split("-")) for p in words.split(",")]
    except ValueError:
        return ""
    if len(spans) != len(s):
        return ""
    if len(d) == len(s):
        return words
    out: list[tuple[int, int] | None] = [None] * len(d)
    sm = difflib.SequenceMatcher(a=[w.lower() for w in d], b=[w.lower() for w in s], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                out[i1 + k] = spans[j1 + k]
        elif op == "replace" or op == "delete":
            if j2 > j1:
                a, b = spans[j1][0], spans[j2 - 1][1]
            else:   # deleted: a zero-length span at the next spoken word's start
                a = b = spans[j1][0] if j1 < len(spans) else (spans[-1][1] if spans else 0)
            n = i2 - i1
            for k in range(n):
                out[i1 + k] = (a + (b - a) * k // n, a + (b - a) * (k + 1) // n)
        # "insert" (spoken words with no display word): their time folds into the neighbours' gap
    last = 0
    for k, v in enumerate(out):
        if v is None:
            v = (last, last)
        out[k] = v
        last = v[1]
    return ",".join(f"{a}-{b}" for a, b in out)
