"""Round 14 (code only; director_model/RESULTS.md, round 13 "Next"): the runtime guard for turns with no ear read-out.

A heard turn end with no partial words since its start and no ear extras on its final words (no ABI 2 read-out, no
names, no decoder text) is the backend tests' bare form ("a" with no arc read and no partials); no live ear sends it.
Round 13's r13 xl, routed in `answer`, silenced exactly that bare "a" in the lesson tests. Now the model never decides
such a turn (it may not silence an answer, navigate or override a turn there): the rules do. The same "a" with the
ear's read-out is the model's to decide as before.
"""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app import director, models_client, session as sessions
from app.academy import content, grade
from app.config import settings
from app.director_model import features as FX, runtime as RT
from app.gazetteer import Gazetteer
from app.mission import capcom, registry
from app.moments import MomentIndex

LESSON = "history"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _act(name, p=0.99):
    a = np.full(len(FX.ACTS), (1 - p) / (len(FX.ACTS) - 1), np.float32)
    a[FX.ACTS.index(name)] = p
    return a


NAV_INTENT = next(i for i in FX.NAV_INTENTS if i in FX.NAV_ACTIONABLE and i not in ("accept_offer", "decline_offer"))


def _nav_out():
    nv = np.full(len(FX.NAV_INTENTS), 0.001, np.float32)
    nv[FX.NAV_INTENTS.index(NAV_INTENT)] = 0.99
    return {"act": _act("navigate"), "nav": nv}


class SureIgnore:
    """Stands in for the loaded weights: sure every step is room chatter (p(ignore) 0.99), with a policy that routes
    every class to it and silences a lesson answer at p(ignore) >= 0.5."""
    F = FX.F

    def __init__(self):
        self.meta = {"policy": {**RT.DEFAULT_POLICY, "classes": list(RT.SITUATIONS) + ["nav", "answer"],
                                "answer_ignore": 0.5, "ignore": 0.5, "nav": 0.5, "ignore_min_words": None}}

    def step(self, state, x, toks, wtok, wfeat):
        return {"act": _act("ignore")}, state


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture
def guarded(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()
    monkeypatch.setenv("DIRECTOR_MODEL", "guarded")
    m = SureIgnore()
    monkeypatch.setattr(RT, "model", lambda: m)
    monkeypatch.setattr(RT, "routed_models", lambda: {})
    return m


def run(c):
    return asyncio.run(c)


def lesson_session(world, sid):
    clock = Clock()
    s = sessions.Session(sid, world[0], world[1], clock=clock, registry=registry)
    st = content.lesson(LESSON)["steps"][0]
    opts = [say[0] for _, say in grade.step_options(st["accept"])]
    run(s.handle({"t": "hello", "mode": "cadet"}))
    run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": st["accept"]["type"],
                  "step_options": opts, "lesson_id": LESSON, "step": 0}))
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": "a1",
                  "text": "Apollo 11 landed on a mare. What does mare mean?"}))
    clock.t += 1.8
    run(s.handle({"t": "playback", "kind": "guide", "state": "end", "id": "a1"}))
    clock.t += 2.0
    s.clock_obj = clock
    return s


def answers(s):
    return [d for d in s.outbox if d["t"] == "nav" and d.get("intent") == "answer"]


EAR = {"uconf": 0.93, "min_wconf": 0.9, "wconf": [0.93], "nbest": [], "walts": [], "disfl": [], "quantities": [],
       "n_dropped": 0, "almost": [], "speech_s": 0.4, "max_pause_s": 0.0, "end_silence_s": 0.5, "playback_leak": None,
       "playback": None, "barge": False, "barge_p": None, "eot": 0.6}


def hear_bare(s, text):
    """The backend tests' form: a turn start with no words, the turn end with the text. No arc read, no partials."""
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    s.clock_obj.t += 0.4
    run(s.handle({"t": "turn", "state": "end", "text": text}))


def hear_live(s, text):
    """As the ABI 2 live ear sends it: a partial, the final words with the ear's read-out, the turn end."""
    run(s.handle({"t": "turn", "state": "start", "text": text}))
    run(s.handle({"t": "words", "text": text, "final": False, "n_stable": 1, "eot": 0.3}))
    s.clock_obj.t += 0.3
    run(s.handle({"t": "words", "text": text, "final": True, "spoken": text, "names": [], "tags": [], "conf": None,
                  "alts": [], "decoder_text": text, "agree": 1.0, **EAR}))
    s.clock_obj.t += 0.2
    run(s.handle({"t": "turn", "state": "end", "text": text}))


def test_a_bare_lesson_answer_is_never_silenced_or_taken_by_the_model(world, guarded):
    s = lesson_session(world, "r14-bare")
    assert s.dm is not None and RT.mode() == "guarded"
    hear_bare(s, "a")
    assert s.dm.bare(), "a turn end with no partials and no ear read-out is bare"
    assert len(answers(s)) == 1, "the rules' routing stands: the bare 'a' goes to the step as its answer"
    assert s.routes[-1]["outcome"] == "answer"
    # nor may the model navigate it or override it (decide_nav / decide_turn), however sure it is
    assert s.dm.decide_nav(_nav_out(), None) is None
    assert s.dm.decide_turn({"act": _act("ignore")}, "a", False) is None
    assert s.dm.decide_answer({"act": _act("ignore")}) is False


def test_the_same_answer_with_the_ears_read_out_is_the_models_to_decide(world, guarded):
    s = lesson_session(world, "r14-live")
    hear_live(s, "a")
    assert not s.dm.bare()
    # the sure-ignore model silences it (the guard is what kept the bare form with the rules)
    assert answers(s) == [] and s.routes[-1]["outcome"] == "ignore" and s.routes[-1]["reason"] == "model_chatter"
    assert s.dm.decide_nav(_nav_out(), None) == NAV_INTENT


def test_turn_words_count_resets_per_turn():
    n = 0
    for k in ("turn_start", "words", "words", "arc"):
        n = RT.turn_words_next(k, n)
    assert n == 2
    assert RT.turn_words_next("turn_start", 5) == 0
    assert RT.bare_turn({"kind": "turn_end"}, 0) and not RT.bare_turn({"kind": "turn_end"}, 1)
    assert not RT.bare_turn({"kind": "turn_end", "ear": {"conf": None}}, 0)
    assert not RT.bare_turn({"kind": "typed"}, 0) and not RT.bare_turn(None, 0)


def test_a_turn_after_a_closed_turn_counts_from_zero(world, guarded):
    """A bare turn end right after a heard turn (no turn start in between) is still bare: the count closes at every
    turn end, so the previous turn's partials never make the next turn look heard."""
    s = lesson_session(world, "r14-close")
    hear_live(s, "the second one")
    assert s.dm.turn_words == 0
    s.clock_obj.t += 3.0
    s.belief["kid"]["ear"] = None      # (the ear's extras stay on the kid until the next turn start; drop them here)
    run(s.handle({"t": "turn", "state": "end", "text": "a"}))
    assert s.dm.bare()


def test_gen_sessions_embedder_problem_names_why():
    """gen_sessions refuses to generate without the embedder the app has (rounds 12-13 silently trained without it).
    Imported in a subprocess: gen_sessions sets DIRECTOR_MODEL=off for its own process at import."""
    dm = Path(__file__).resolve().parents[2] / "director_model"
    code = ("import gen_sessions as G\n"
            "assert G.embedder_problem(None).startswith('no model server')\n"
            "assert G.embedder_problem({}).startswith('no model server')\n"
            "assert 'no embedder' in G.embedder_problem({'ok': True})\n"
            "assert 'EMBED_MODEL_DIR' in G.embedder_problem({'embedder': {'loaded': False}})\n"
            "assert G.embedder_problem({'embedder': {'loaded': False, 'error': 'gone'}}) == 'gone'\n"
            "assert G.embedder_problem({'embedder': {'loaded': True}}) is None\n"
            "assert G.embedder_problem({'ok': True, 'models': {'embedder': {'loaded': True}}}) is None\n"
            "assert 'EMBED_MODEL_DIR' in G.embedder_problem({'ok': True, 'models': {'embedder': {'loaded': False}}})\n"
            "print('ok')\n")
    env = {**os.environ, "MODEL_SERVER_URL": "http://127.0.0.1:1"}
    r = subprocess.run([sys.executable, "-c", code], cwd=dm, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-2000:]
