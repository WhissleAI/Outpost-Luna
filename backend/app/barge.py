"""Barge-in tuning and the short commands that may interrupt a line on their own (server side).

Mirrors frontend/src/barge.js (BARGE_TUNING, STOP, NAV): the client decides barge-in for the open mic; the session's
own check (session.Session._is_barge, on the ear relay's words) uses these so both sides agree on what a command is.
tests/test_barge.py checks the two tables stay the same.
"""
from __future__ import annotations

import re

from .gazetteer import norm

LINE_GRACE_S = 0.6        # no barge-in in a line's first 600 ms (frontend BARGE_TUNING.LINE_GRACE_MS)

STOP = {"stop", "wait", "pause", "quiet", "be quiet", "never mind", "nevermind", "hold on", "hang on", "stop talking",
        "stop please", "wait please", "stop stop", "wait wait", "shush", "silence", "enough", "cancel", "stop it capcom",
        "okay stop", "ok stop"}
NAV = {"skip", "next", "skip it", "skip this", "next one", "next please", "go back", "say again", "repeat",
       "repeat that", "say that again", "go on", "move on"}
_LEAD = re.compile(r"^(?:okay|ok|um|uh|hey|capcom|please) ")
_TAIL = re.compile(r" (?:please|capcom|now)$")


def _key(text: str) -> str:
    q = " ".join(norm(text or "").replace("'", "").split())
    return _TAIL.sub("", _LEAD.sub("", q))


def is_command(text: str) -> bool:
    k = _key(text)
    return k in STOP or k in NAV


def is_stop(text: str) -> bool:
    return _key(text) in STOP
