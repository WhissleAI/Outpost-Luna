"""The session's side of on-device learning: evidence in, tuned values out (docs/ON_DEVICE_LEARNING.md).

Session (app/session.py) calls:
  tune()                       -> {"end_silence_s", "ref_shift_s"} for the ear ({"t":"tune"}, sent by the listen relay)
  playback_threshold()         -> this computer's playback-leak threshold (session.ear_playback)
  read_extras()                -> what director._link may use: the learned aliases and the bounded thresholds
  policy_overrides()           -> the guarded Director policy's bounded thresholds (runtime.decide_turn)
  on_echo_delay(m)             one line's measured speaker -> mic delay (the ear's {"t":"echo_delay"})
  on_routed(text, source, rt, ear, echo)   every heard turn after the router: leak labels, pace, cut-offs, repeats
  on_offer(r, ear, echo)       the app just asked "Did you mean X?"
  on_reply(text, offer, echo)  the next turn's answer to it (yes / no / an unknown short word)
  on_pick(id)                  the kid tapped an option of the offer card
  on_model_ignore(text)        the guarded model silenced this turn

Never learns from a turn that was our own echo (`echo` is the router's text echo check OR the ear's playback flag),
from a "no", or while learning is off (LEARN=0).
"""
from __future__ import annotations

import os
import time

from .. import turn_router as router_
from . import device, for_profile
from .habits import CUT_EOT, CUT_GAP_S

OFFER_WINDOW_S = 30.0          # a tap on the offer card counts this long after the offer
REPEAT_S = 8.0                 # the kid says it again this soon after a model ignore: that ignore was wrong


def enabled() -> bool:
    return os.environ.get("LEARN", "1") not in ("0", "false", "off")


def _overlap(a: str, b: str) -> float:
    wa, wb = set(router_.words(a)), set(router_.words(b))
    return len(wa & wb) / max(1, len(wa)) if wa and wb else 0.0


class SessionLearning:
    def __init__(self, sess, clock=time.monotonic):
        self.sess, self.clock = sess, clock
        self.offer: dict | None = None
        self.unknown_reply: tuple[str, float] | None = None
        self.last_turn: dict | None = None
        self.ignored: tuple[str, float] | None = None

    # ---- who ----
    def learner(self):
        return for_profile(self.sess.prefs.get("profile")) if enabled() else None

    def device(self):
        return device() if enabled() else None

    # ---- tuned values out ----
    def tune(self) -> dict | None:
        lr, dv = self.learner(), self.device()
        if lr is None or dv is None:
            return None
        return {"end_silence_s": lr.habits.end_silence_s(), "ref_shift_s": dv.echo.ref_shift_s()}

    def playback_threshold(self, default: float) -> float:
        dv = self.device()
        return dv.echo.threshold() if dv is not None else default

    def read_extras(self) -> dict:
        lr = self.learner()
        if lr is None:
            return {}
        out = {"learn_tune": {"link_act_p": lr.policy.link_act_p, "near_score": lr.habits.near_score(),
                              "almost_min_p": lr.habits.almost_min_p()}}
        if lr.aliases.aliases:
            out["learned_aliases"] = lr.aliases.pairs()
        return out

    def policy_overrides(self) -> dict:
        lr = self.learner()
        return lr.policy.policy_overrides() if lr is not None else {}

    # ---- evidence in ----
    def on_echo_delay(self, m: dict) -> None:
        dv = self.device()
        if dv is not None and dv.echo.observe_delay(m.get("ms"), m.get("peak")):
            dv.maybe_save()

    def on_routed(self, text: str, source: str, rt: dict, ear: dict | None, echo: bool) -> None:
        if source not in ("listen", "voice"):
            return
        ear = ear or {}
        now = self.clock()
        dv, lr = self.device(), self.learner()
        leak = ear.get("playback_leak")
        if dv is not None and leak is not None:
            if rt.get("reason") == "echo":       # labelled by the words alone, never by the leak
                dv.echo.observe_leak(leak, "echo")
                dv.maybe_save()
            elif rt.get("outcome") != "ignore" and ear.get("barge") and not echo:
                dv.echo.observe_leak(leak, "kid")
                dv.maybe_save()
        if lr is None or echo or rt.get("outcome") == "ignore":
            return
        prev = self.last_turn
        start = self.sess.belief["kid"].get("start")
        if prev is not None and start is not None and 0 <= start - prev["end"] < CUT_GAP_S and \
                prev.get("eot") is not None and prev["eot"] < CUT_EOT:
            lr.habits.mark_cut()
        lr.habits.observe_turn(len(router_.words(text)), ear.get("speech_s"), ear.get("max_pause_s"), False)
        self.last_turn = {"end": now, "eot": ear.get("eot")}
        if self.ignored and now - self.ignored[1] <= REPEAT_S and _overlap(text, self.ignored[0]) >= 0.6:
            lr.policy.observe_model_ignore_repeated()
            self.ignored = None
        lr.touch()

    def on_model_ignore(self, text: str) -> None:
        self.ignored = (text, self.clock())

    def on_offer(self, r: dict, ear: dict | None, echo: bool) -> None:
        ask = r.get("ask") or {}
        opts = ask.get("options") or []
        self.offer = {"id": opts[0] if opts else r.get("place"), "options": list(opts), "heard": ask.get("heard"),
                      "p": ask.get("p"), "how": r.get("source"), "at": self.clock(), "echo": bool(echo)}
        self.unknown_reply = None

    def _answer(self, yes: bool, via: str) -> str | None:
        o, lr = self.offer, self.learner()
        if o is None or lr is None:
            return None
        self.offer = None
        lr.habits.observe_offer(yes)
        if o.get("how") == "ear_confirm":
            lr.policy.observe_link_offer(o.get("p"), yes)
        res = None
        if o.get("heard") and o.get("id"):
            if yes:
                res = lr.aliases.confirm(o["heard"], o["id"], p=o.get("p") if o.get("how") == "ear_near" else None,
                                         echo=o.get("echo", False), via=via)
            else:
                lr.aliases.reject(o["heard"], o["id"])
                res = "rejected"
        lr.touch()
        return res

    def on_reply(self, text: str, echo: bool) -> str | None:
        """The turn after an offer. -> "yes" / "no" (what it meant), or None (anything else)."""
        o = self.offer
        if o is None or self.clock() - o["at"] > OFFER_WINDOW_S:
            self.offer = None
            return None
        if echo:                       # our own voice: never an answer we learn from
            return None
        lr = self.learner()
        q = router_.norm(text)
        yes = bool(router_.YES.match(q)) or q in ("yes please", "yeah please", "that one", "yes that one", "uh huh") \
            or (lr is not None and lr.habits.is_yes(q))
        no = bool(router_.NO.match(q)) or (lr is not None and lr.habits.is_no(q))
        if yes:
            self._answer(True, "yes")
            return "yes"
        if no:
            self._answer(False, "no")
            return "no"
        if len(q.split()) <= 2:        # a short reply we do not know: the tap that follows tells us what it meant
            self.unknown_reply = (q, self.clock())
        return None

    def on_pick(self, pid: str | None) -> str | None:
        o = self.offer
        if o is None or not pid or self.clock() - o["at"] > OFFER_WINDOW_S:
            return None
        yes = pid == o.get("id")
        lr = self.learner()
        if self.unknown_reply and lr is not None and self.clock() - self.unknown_reply[1] <= OFFER_WINDOW_S:
            lr.habits.observe_reply(self.unknown_reply[0], meant_yes=yes)
        self.unknown_reply = None
        if pid in (o.get("options") or []) or yes:
            return self._answer(yes, "tap")
        return None
