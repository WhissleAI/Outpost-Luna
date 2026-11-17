"""Director thresholds, per child: small moves inside hard bounds, from confirmations (docs/ON_DEVICE_LEARNING.md).
No retraining: the shipped weights (r10, guarded) are never changed; only two thresholds the rules and the guarded
policy compare against may move, and only inside these bounds:

  link_act_p    director.LINK_ACT_P (0.99): act on the ear's link at this p, else ask "Did you mean …?".
                Bounds [LINK_MIN, 0.99]: it may come DOWN one step at a time when this kid keeps saying yes to offers made
                for links just under it (p in [LINK_MIN, 0.99)), and goes straight back to 0.99 on a "no" in that band.
  model_ignore  the guarded model's `ignore` threshold (weights.json policy.ignore, 0.95). Bounds [0.95, IGNORE_MAX]: it
                may only go UP (more careful), when the model silenced a turn and the kid said it again right away.

With nothing learned both are exactly the shipped values, so the shipped model makes identical decisions
(tests/test_learn.py::test_policy_bounds_keep_shipped_decisions).
"""
from __future__ import annotations

LINK_SHIPPED, LINK_MIN, LINK_STEP = 0.99, 0.97, 0.01
LINK_MIN_YES = 6                  # offers in the band, all but at most one confirmed, before a step down
IGNORE_SHIPPED, IGNORE_MAX, IGNORE_STEP = 0.95, 0.99, 0.01
IGNORE_REPEATS = 2                # "said it again" after a model ignore, per step up


class Policy:
    def __init__(self, state: dict | None = None):
        p = (state or {}).get("policy") or {}
        self.link_act_p = float(p.get("link_act_p", LINK_SHIPPED))
        self.band_yes = int(p.get("band_yes", 0))
        self.band_no = int(p.get("band_no", 0))
        self.model_ignore = float(p.get("model_ignore", IGNORE_SHIPPED))
        self.repeats = int(p.get("repeats", 0))
        self._clamp()

    def _clamp(self):
        self.link_act_p = round(min(LINK_SHIPPED, max(LINK_MIN, self.link_act_p)), 3)
        self.model_ignore = round(min(IGNORE_MAX, max(IGNORE_SHIPPED, self.model_ignore)), 3)

    def state(self) -> dict:
        return {"policy": {"link_act_p": self.link_act_p, "band_yes": self.band_yes, "band_no": self.band_no,
                           "model_ignore": self.model_ignore, "repeats": self.repeats}}

    def observe_link_offer(self, p: float | None, said_yes: bool) -> None:
        """The answer to an offer made for a low-p ear link (director "confirm")."""
        if p is None or not (LINK_MIN <= float(p) < LINK_SHIPPED):
            return
        if said_yes:
            self.band_yes += 1
            if self.band_yes >= LINK_MIN_YES and self.band_no <= max(0, self.band_yes // LINK_MIN_YES - 1):
                self.link_act_p -= LINK_STEP
                self.band_yes = 0
        else:
            self.band_no += 1
            self.link_act_p = LINK_SHIPPED       # one "no" in the band: back to the shipped value
            self.band_yes = 0
        self._clamp()

    def observe_model_ignore_repeated(self) -> None:
        self.repeats += 1
        if self.repeats >= IGNORE_REPEATS:
            self.model_ignore += IGNORE_STEP
            self.repeats = 0
        self._clamp()

    def policy_overrides(self) -> dict:
        """What the guarded policy may use instead of the weights' own values (only keys that moved)."""
        return {"ignore": self.model_ignore} if self.model_ignore != IGNORE_SHIPPED else {}
