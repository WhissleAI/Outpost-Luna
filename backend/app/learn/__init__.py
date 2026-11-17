"""On-device learning (docs/ON_DEVICE_LEARNING.md): the installed app gets better for each child on their own computer.
Nothing leaves the device, no audio is kept, and only small learned settings are stored (app/learn/store.py).

  Learner(profile)  one cadet: personal name aliases (aliases.py), speech habits (habits.py), Director thresholds
                    (policy.py); profile-<id>.json
  device()          this computer: the echo path (echo.py); device.json

App-agnostic like the entity layer: it needs a Registry (app/entities) and nothing of Outpost Luna's. The session
(app/session.py) feeds it evidence and reads the tuned values back; the API (app/learn/api.py) shows and resets it.
"""
from __future__ import annotations

import threading
import time

from . import store
from .aliases import PersonalAliases
from .echo import DeviceEcho
from .habits import Habits
from .policy import Policy

V = 1
_LOCK = threading.Lock()
_PROFILES: dict[str, "Learner"] = {}
_DEVICE: "DeviceLearner | None" = None


class Learner:
    """One cadet's learning. Thread-safe enough for the session's single event loop; saves are atomic."""

    def __init__(self, profile: str, reg=None, clock=time.time, persist: bool = True):
        from ..entities import registry
        self.profile = store.profile_id(profile)
        self.clock = clock
        self.persist = persist
        st = store.read(f"profile-{self.profile}") if persist else {}
        self.created = float(st.get("created") or clock())
        self.aliases = PersonalAliases(reg or registry(), st, clock=clock)
        self.habits = Habits(st)
        self.policy = Policy(st)
        self.dirty = False

    def body(self) -> dict:
        return {"v": V, "kind": "profile", "profile": self.profile, "created": self.created, "updated": self.clock(),
                **self.aliases.state(), **self.habits.state(), **self.policy.state()}

    def save(self) -> bool:
        self.dirty = False
        return store.write(f"profile-{self.profile}", self.body()) if self.persist else True

    def touch(self):
        self.dirty = True
        self.save()

    def reset(self) -> None:
        if self.persist:
            store.remove(f"profile-{self.profile}")
        self.__init__(self.profile, self.aliases.reg, self.clock, self.persist)

    # ---- the tuned values the app reads ----
    def tuning(self) -> dict:
        return {"end_silence_s": self.habits.end_silence_s(), "near_score": self.habits.near_score(),
                "almost_min_p": self.habits.almost_min_p(), "link_act_p": self.policy.link_act_p,
                "model_policy": self.policy.policy_overrides()}

    def describe(self, include_aliases: bool = True) -> dict:
        """The "What the app has learned" view (and, with include_aliases False, the diagnostics file's copy)."""
        reg = self.aliases.reg
        al = []
        for a in self.aliases.aliases:
            e = reg.get(a["id"])
            row = {"id": a["id"], "name": e.name if e else a["id"], "times": int(a.get("n", 1)),
                   "uses": int(a.get("uses", 0))}
            if include_aliases:
                row["heard"] = a["heard"]
            al.append(row)
        h, p = self.habits, self.policy
        out = {"profile": self.profile, "aliases": al, "pending": len(self.aliases.pending),
               "habits": {"end_silence_s": h.end_silence_s(), "turns": h.turns, "cut_offs": h.cuts,
                          "pace_wps": round(h.pace_ema, 2) if h.pace_ema else None,
                          "offers": h.offers, "offers_yes": h.offers_yes,
                          "near_score": h.near_score(), "almost_min_p": h.almost_min_p()},
               "policy": {"link_act_p": p.link_act_p, "model_ignore": p.model_ignore}}
        if include_aliases:
            out["habits"]["yes_words"] = sorted(w for w in h.yes_words if h.is_yes(w))
            out["habits"]["no_words"] = sorted(w for w in h.no_words if h.is_no(w))
        else:
            out["habits"]["yes_words"] = len([w for w in h.yes_words if h.is_yes(w)])
            out["habits"]["no_words"] = len([w for w in h.no_words if h.is_no(w)])
            out["blocked"] = len(self.aliases.blocked)
        return out


class DeviceLearner:
    def __init__(self, clock=time.time, persist: bool = True, default_thr: float | None = None):
        from .echo import THR_DEFAULT
        self.persist, self.clock = persist, clock
        st = store.read("device") if persist else {}
        self.echo = DeviceEcho(st, clock=clock, default_thr=THR_DEFAULT if default_thr is None else default_thr)
        self._n = 0

    def save(self) -> bool:
        if not self.persist:
            return True
        return store.write("device", {"v": V, "kind": "device", "updated": self.clock(), **self.echo.state()})

    def maybe_save(self, every: int = 5) -> None:
        self._n += 1
        if self._n % every == 0:
            self.save()

    def reset(self) -> None:
        if self.persist:
            store.remove("device")
        self.__init__(self.clock, self.persist, self.echo.default_thr)


def for_profile(profile: str | None) -> Learner:
    pid = store.profile_id(profile)
    with _LOCK:
        if pid not in _PROFILES:
            _PROFILES[pid] = Learner(pid)
        return _PROFILES[pid]


def device() -> DeviceLearner:
    global _DEVICE
    with _LOCK:
        if _DEVICE is None:
            _DEVICE = DeviceLearner()
        return _DEVICE


def forget_all() -> int:
    """Settings → Reset, and Reset learning for everyone: files and the in-memory copies."""
    global _DEVICE
    with _LOCK:
        _PROFILES.clear()
        _DEVICE = None
    return store.clear_all()


def forget_cached() -> None:
    """Drop the in-memory copies (tests; LEARN_DIR changed)."""
    global _DEVICE
    with _LOCK:
        _PROFILES.clear()
        _DEVICE = None
