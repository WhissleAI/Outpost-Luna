"""Round 7: the navigation policy, the appended features and the runtime's latency report."""
import numpy as np

from app.director_model import features as FX, runtime as RT


def out(act="navigate", p=0.99, nav="accept_offer", pn=0.99):
    a = np.full(len(FX.ACTS), (1 - p) / (len(FX.ACTS) - 1))
    a[FX.ACTS.index(act)] = p
    n = np.full(len(FX.NAV_INTENTS), (1 - pn) / (len(FX.NAV_INTENTS) - 1))
    n[FX.NAV_INTENTS.index(nav)] = pn
    return {"act": a, "nav": n}


def test_nav_policy_is_off_unless_fitted():
    assert RT.nav_policy(out(), {"nav": None}, offer=True) is None
    assert RT.nav_policy(out(), {}, offer=True) is None


def test_nav_policy_needs_both_probabilities_and_an_offer():
    thr = {"nav": 0.95}
    assert RT.nav_policy(out(), thr, offer=True) == "accept_offer"
    assert RT.nav_policy(out(), thr, offer=False) is None                  # no offer on screen: never take one
    assert RT.nav_policy(out(p=0.9), thr, offer=True) is None
    assert RT.nav_policy(out(pn=0.9), thr, offer=True) is None
    assert RT.nav_policy(out(act="ignore"), thr, offer=True) is None
    assert RT.nav_policy(out(nav="map"), thr) == "map"
    assert RT.nav_policy(out(nav="other"), thr) is None                    # not an intent it can run alone
    assert RT.nav_policy({"act": out()["act"]}, thr) is None                # older weights: no nav head


def test_features_are_append_only():
    assert FX.F_R5 == 169 and FX.F_R6 == 216 and FX.F > FX.F_R6
    assert FX.FEATS[FX.F_R6 - 1] == "lx_filler"
    assert FX.HEADS["nav"] == len(FX.NAV_INTENTS) and list(FX.HEADS)[-1] == "nav"


def test_nav_label_folds_the_offer():
    fr = {"screen": "patch", "offer": "next_lesson"}
    assert FX.nav_label("next", fr) == "accept_offer"
    assert FX.nav_label("yes please", fr) == "accept_offer"
    assert FX.nav_label("open the library", {"screen": "lesson"}) == "library"
    assert FX.nav_label("what is regolith", {"screen": "map"}) == "none"


def test_shipped_weights_report_latency():
    m = RT.model()
    if m is None:
        return
    lat = RT.measure_latency(m, 20)
    assert lat["p50_ms"] < 5.0
    assert RT.stats()["latency"] is not None
