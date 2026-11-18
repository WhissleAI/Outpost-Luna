"""Hesitation on a heard turn (docs/LEARNING_DESIGN.md §13): fillers, a long pause, or a turn the ear barely caught.

`hesitant(ear, text)` reads the ear's own per-turn signals (model_server/app/arc_ear.py, relayed by listen.py and kept
on the session's k["ear"], session.EAR_ABI2):

  disfl        the ear's disfluent words: "filler" (um, uh), "repeat", "fragment" (a cut-off word). Two of them, or
               one in a short turn ("um... Tycho"), read as hesitation. An ear without `disfl` (Deepgram Flux):
               the filler words in the text.
  max_pause_s  the longest pause inside the turn >= PAUSE_S. NOTE: the shipped ear ends a turn after 0.5-0.8 s of
               silence (EarSettings.ear_end_silence_s, learned within bounds by app/learn/habits.py), so a pause this
               long inside one turn only reaches us from an ear with a longer end silence. Kept for that ear.
  uconf        the least sure utterance of the turn under UCONF_LOW (the bottom decile of 758 real kid turns,
               docs/ARC_V2.md: p10 = 0.45).

What it is for: the client brings the next hint rung sooner (one early hint per step) on a Now-card step or a lesson
answer. It is a one-turn, in-session flag on the `heard` decision: never stored, never logged, never shown or said
("you sound unsure" is never a line), never a score.
"""
from __future__ import annotations

import re

PAUSE_S = 2.5
UCONF_LOW = 0.45
SHORT_TURN = 4          # words: one disfluency in a turn this short is enough
DISFL_KINDS = ("filler", "repeat", "fragment")
FILLER = re.compile(r"\b(?:u+m+|u+h+m*|e+r+m*|h+m+|a+h+|e+h+)\b")


def hesitant(ear: dict | None, text: str) -> bool:
    ear = ear or {}
    words = len(re.findall(r"[A-Za-z0-9']+", text or ""))
    d = ear.get("disfl")
    if isinstance(d, list) and d:
        n = sum(1 for x in d if isinstance(x, dict) and x.get("kind") in DISFL_KINDS)
    else:
        n = len(FILLER.findall((text or "").lower()))
    if n >= 2 or (n >= 1 and words <= SHORT_TURN):
        return True
    mp = ear.get("max_pause_s")
    if isinstance(mp, (int, float)) and mp >= PAUSE_S:
        return True
    uc = ear.get("uconf")
    return isinstance(uc, (int, float)) and words > 0 and uc < UCONF_LOW
