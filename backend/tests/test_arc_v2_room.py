"""Arc Transcriber Space v2 room read-outs (docs/ARC_V2.md): kept on the turn's ear read in SHADOW. Nothing decides on
them: not the echo drop, not the router, not the safety path, not the Director's features. The addressee and kids-safety
outputs are BETA and must never trigger an automatic action."""
import asyncio

import numpy as np
import pytest

from app import session as sessions
from app.config import settings
from app.director_model import features as FX
from app.gazetteer import Gazetteer
from app.moments import MomentIndex

ROOM = {"act": {"label": "command", "p": 0.91, "probs": {"command": 0.91}},
        "addressee": {"label": "other_person", "p": 0.97, "probs": {}, "beta": True},
        "safety": {"above_threshold": ["crisis.self_harm", "pii.leak"], "max_p": 0.99, "beta": True},
        "end_of_turn": 0.02, "playback": 1.0, "playback_max": 1.0, "media": 1.0, "live_speech": 0.0,
        "reference": True, "ms": 6.1}
BASE = {"names": [{"heard": "tycho", "entity": "Tycho", "state": "linked", "p": 0.5}], "spoken": "fly to tycho",
        "decoder_text": "Fly to Tycho", "agree": 0.4, "playback_leak": 0.1, "playback": False, "barge": False,
        "eot": 0.8}


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture()
def explorer(world):
    s = sessions.Session("v2room", world[0], world[1])
    asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    return s


def test_room_is_kept_on_the_ear_read(explorer):
    asyncio.run(explorer.on_listen({"t": "words", "final": True, "text": "fly to Tycho", "conf": None, "alts": [],
                                    **BASE, "room": ROOM}))
    assert explorer.belief["kid"]["ear"]["room"] == ROOM


def test_room_never_drops_a_turn_as_echo():
    """The playback head reads 1.0 here and the canceller's leak 0.1: the shipped rule (leak) decides."""
    assert sessions.ear_playback({**BASE, "room": ROOM}) is False
    assert sessions.ear_playback({**BASE, "playback_leak": 0.9, "room": {**ROOM, "playback": 0.0}}) is True


def _route(sess, room):
    sess.belief["kid"]["ear"] = {**BASE, **({"room": room} if room else {})}
    asyncio.run(sess._turn("fly to tycho", "listen"))
    return {k: sess.routes[-1].get(k) for k in ("outcome", "reason")}


def test_the_same_turn_routes_the_same_with_or_without_room(world):
    """A BETA addressee of other_person and BETA safety flags change nothing: same route, same reason."""
    a = sessions.Session("v2a", world[0], world[1])
    b = sessions.Session("v2b", world[0], world[1])
    for s in (a, b):
        asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
        asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    assert _route(a, ROOM) == _route(b, None)


def test_room_never_reaches_the_director_features(explorer):
    from app.director_model import runtime
    explorer.belief["kid"]["ear"] = dict(BASE)
    rec0 = FX.record(explorer, {"t": "turn", "state": "end", "text": "fly to tycho"}, {"available": False})
    explorer._r7_prev = None
    explorer.belief["kid"]["ear"] = {**BASE, "room": ROOM}
    rec1 = FX.record(explorer, {"t": "turn", "state": "end", "text": "fly to tycho"}, {"available": False})
    x0, x1 = FX.step_feats(rec0, None), FX.step_feats(rec1, None)
    assert np.array_equal(x0, x1)      # every slot, the round-13 block included
    if runtime.model() is not None:
        for m in [runtime.model(), *runtime.routed_models().values()]:
            o0, _ = m.step(None, x0, *FX.step_tokens(rec0))
            o1, _ = m.step(None, x1, *FX.step_tokens(rec1))
            assert all(np.array_equal(np.asarray(o0[k]), np.asarray(o1[k])) for k in o0)
