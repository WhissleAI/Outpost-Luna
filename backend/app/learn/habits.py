"""This child's speech habits: their own short yes / no words, their pace and pauses (docs/ON_DEVICE_LEARNING.md).

What it tunes, always inside fixed ranges:
  - end_silence_s(): the silence that closes a turn (the ear's EAR_END_SILENCE_S, shipped 0.5 s), in [0.5, 0.8]. Up when
    this kid's turns are being cut off (a turn closed while they were mid-sentence: the next turn follows within
    CUT_GAP_S and the first one's end-of-turn probability was low) or when they pause long inside turns; back down
    toward 0.5 when nothing was cut off for a while. A longer silence costs latency, so it only rises on evidence.
  - yes_word(w) / no_word(w): short replies the router does not know ("ya", "yesh", "nuh") learned when the kid then
    confirmed the offer by tapping it (yes) or tapped / said something else (no). Never a common content word.
  - near_score() / almost_min_p(): the "Did you mean …?" thresholds (director.NEAR_SCORE 0.8, ALMOST_MIN_P 0.5), moved
    by at most one step either way from this kid's answers to the offers: mostly "yes" -> offer a little more often;
    mostly "no" -> less often.
Numbers and counters only; the yes / no words are the only words kept, at most YESNO_CAP of each.
"""
from __future__ import annotations

from .aliases import COMMON

END_SILENCE = 0.5                      # shipped (model_server EarSettings.ear_end_silence_s)
END_MIN, END_MAX, END_STEP = 0.5, 0.8, 0.1
CUT_GAP_S = 1.0                        # the next turn starts this soon after a close: maybe a cut-off
CUT_EOT = 0.5                          # ... and the closed turn's end-of-turn p was under this
CUT_RATE_UP = 0.08                     # cut-offs per turn that raise the silence (over the last WINDOW turns)
WINDOW = 25
MIN_TURNS = 12
# The kid's typical longest pause inside a turn within this of the CURRENT end silence: raise (0.38 s at the shipped
# 0.5 s). Relative, not absolute: a pause can only be measured up to the end silence in force (a longer one ends the
# turn), so an absolute bar (the first version: 0.38 s at every setting) ratcheted a kid who pauses ~0.4 s from 0.5 to
# the 0.8 s cap and could never come back down (needs < 0.30 s): +0.3 s before every answer, for no cut-off.
PAUSE_MARGIN_S = 0.12
LONG_PAUSE_S = END_SILENCE - PAUSE_MARGIN_S
NEAR_SCORE, NEAR_MIN, NEAR_MAX = 0.8, 0.76, 0.86
ALMOST_MIN_P, ALMOST_MIN, ALMOST_MAX = 0.5, 0.45, 0.6
MIN_OFFERS = 8
YESNO_CAP = 8
YESNO_MIN = 2                          # times a reply was seen with that meaning before it counts


class Habits:
    def __init__(self, state: dict | None = None):
        h = (state or {}).get("habits") or {}
        self.end_silence = float(h.get("end_silence", END_SILENCE))
        self.turns = int(h.get("turns", 0))
        self.recent_cuts: list[int] = []          # this session only (not stored): 1 per cut-off turn
        self.cuts = int(h.get("cuts", 0))
        self.pause_ema = float(h.get("pause_ema", 0.0))
        self.pace_ema = float(h.get("pace_ema", 0.0))
        self.offers = int(h.get("offers", 0))
        self.offers_yes = int(h.get("offers_yes", 0))
        self.yes_words: dict[str, int] = {k: int(v) for k, v in (h.get("yes_words") or {}).items()}
        self.no_words: dict[str, int] = {k: int(v) for k, v in (h.get("no_words") or {}).items()}
        self._clamp()

    def _clamp(self):
        self.end_silence = round(min(END_MAX, max(END_MIN, self.end_silence)), 2)

    def state(self) -> dict:
        return {"habits": {"end_silence": self.end_silence, "turns": self.turns, "cuts": self.cuts,
                           "pause_ema": round(self.pause_ema, 3), "pace_ema": round(self.pace_ema, 3),
                           "offers": self.offers, "offers_yes": self.offers_yes,
                           "yes_words": dict(list(self.yes_words.items())[:YESNO_CAP]),
                           "no_words": dict(list(self.no_words.items())[:YESNO_CAP])}}

    # ---- turns ----
    def observe_turn(self, n_words: int, speech_s: float | None, max_pause_s: float | None, cut_off: bool) -> None:
        """One routed kid turn (never an echo): its word count, speech seconds, longest pause inside it, and whether it
        looks cut off (the session decides: the next turn came within CUT_GAP_S and this one's eot was low)."""
        self.turns += 1
        if speech_s and speech_s > 0.3 and n_words:
            pace = n_words / speech_s
            self.pace_ema = pace if self.pace_ema == 0 else 0.9 * self.pace_ema + 0.1 * pace
        if max_pause_s is not None and max_pause_s >= 0:
            self.pause_ema = max_pause_s if self.pause_ema == 0 else 0.85 * self.pause_ema + 0.15 * float(max_pause_s)
        self.recent_cuts = (self.recent_cuts + [1 if cut_off else 0])[-WINDOW:]
        self.cuts += 1 if cut_off else 0
        self._retune()

    def _retune(self):
        n = len(self.recent_cuts)
        if n < MIN_TURNS:
            return
        rate = sum(self.recent_cuts) / n
        near = self.end_silence - PAUSE_MARGIN_S
        if rate >= CUT_RATE_UP or self.pause_ema >= near:
            if self.end_silence < END_MAX:
                self.end_silence += END_STEP
                self.recent_cuts = []                 # judge the new setting on fresh turns
        elif rate == 0 and n >= WINDOW and self.pause_ema < near - 0.08 and self.end_silence > END_MIN:
            self.end_silence -= END_STEP / 2
            self.recent_cuts = []
        self._clamp()

    def mark_cut(self) -> None:
        """The previous turn turned out to be cut off (the session saw the next one follow at once)."""
        if self.recent_cuts:
            self.recent_cuts[-1] = 1
        else:
            self.recent_cuts = [1]
        self.cuts += 1
        self._retune()

    def end_silence_s(self) -> float:
        return self.end_silence

    # ---- the "Did you mean" offers ----
    def observe_offer(self, said_yes: bool) -> None:
        self.offers += 1
        self.offers_yes += 1 if said_yes else 0

    def _offer_step(self) -> int:
        """-1: offer more (mostly yes), +1: offer less (mostly no), 0: as shipped."""
        if self.offers < MIN_OFFERS:
            return 0
        r = self.offers_yes / self.offers
        return -1 if r >= 0.8 else 1 if r <= 0.4 else 0

    def near_score(self) -> float:
        s = self._offer_step()
        return NEAR_MIN if s < 0 else NEAR_MAX if s > 0 else NEAR_SCORE

    def almost_min_p(self) -> float:
        s = self._offer_step()
        return ALMOST_MIN if s < 0 else ALMOST_MAX if s > 0 else ALMOST_MIN_P

    # ---- short yes / no words ----
    @staticmethod
    def _word_ok(w: str) -> bool:
        ws = w.split()
        return 0 < len(ws) <= 2 and len(w) <= 12 and not any(x in COMMON - {"yeah", "yep", "yup", "nope", "nah", "no",
                                                                            "yes", "ok", "okay", "sure"} for x in ws)

    def observe_reply(self, reply: str, meant_yes: bool) -> str | None:
        """An unknown short reply to an offer, then the kid showed what it meant. -> the word when it now counts."""
        w = " ".join((reply or "").lower().split())
        if not self._word_ok(w):
            return None
        mine, other = (self.yes_words, self.no_words) if meant_yes else (self.no_words, self.yes_words)
        if w in other:            # used both ways: not a word we can trust
            other.pop(w, None)
            return None
        if w not in mine and len(mine) >= YESNO_CAP:
            return None
        mine[w] = mine.get(w, 0) + 1
        return w if mine[w] >= YESNO_MIN else None

    def is_yes(self, w: str) -> bool:
        return self.yes_words.get(" ".join((w or "").lower().split()), 0) >= YESNO_MIN

    def is_no(self, w: str) -> bool:
        return self.no_words.get(" ".join((w or "").lower().split()), 0) >= YESNO_MIN
