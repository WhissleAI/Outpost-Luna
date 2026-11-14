"""The brain's "Did you mean A or B?" (app/knowledge/answer.py): no "??" when a label is itself a question, and no
offer of two unrelated cards from the low ask band. The live run's cabin question "what is the weirdest thing about
moon dust" got "Did you mean what the storm shelter is or Is the Moon made of cheese??"."""
import asyncio

import pytest

from app import director, knowledge, models_client, session as sessions
from app.config import settings
from app.gazetteer import Gazetteer
from app.knowledge import answer as ans
from app.mission import capcom, registry
from app.moments import MomentIndex

Q = "what is the weirdest thing about moon dust"
# The embedder's top hits for Q, measured on the live model server.
NEAR_TIE = [(0.507, "concept:shelter", "what"), (0.506, "misconception:no_craters", "misconception"),
            (0.485, "misconception:cheese", "misconception")]


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()


def fake_nearest(monkeypatch, hits):
    async def nearest(self, text, boost=None, only=None):
        return list(hits)
    monkeypatch.setattr(ans.Brain, "nearest", nearest)


def brain(world):
    return knowledge.get(world[0], world[1].facts)


def test_did_you_mean_strips_the_labels_own_punctuation():
    assert ans.did_you_mean(["what the storm shelter is", "Is the Moon made of cheese?"]) == \
        "Did you mean what the storm shelter is or Is the Moon made of cheese?"
    assert ans.did_you_mean(["Does the Moon have craters?"]) == "Did you mean Does the Moon have craters?"
    assert ans.did_you_mean(["Tycho.", "Copernicus!", "Kepler"]) == "Did you mean Tycho, Copernicus or Kepler?"
    assert "??" not in ans.did_you_mean(["a?", "b??"])


def test_a_real_ask_with_a_question_label_ends_in_one_question_mark(world, monkeypatch):
    b = brain(world)
    fake_nearest(monkeypatch, [(0.60, "concept:shelter", "what"), (0.58, "misconception:cheese", "misconception")])
    r = asyncio.run(b.answer("tell me the weird moon thing"))
    assert r["status"] == "ask"
    assert r["say"].endswith("?") and not r["say"].endswith("??"), r["say"]
    assert [o["label"] for o in r["options"]][1].endswith("?")      # the tap-able label keeps its own "?"


def test_unrelated_near_ties_below_the_floor_are_an_honest_unknown(world, monkeypatch):
    b = brain(world)
    fake_nearest(monkeypatch, NEAR_TIE)
    r = asyncio.run(b.answer(Q))
    assert r["status"] == "unknown" and r["say"] == ans.UNKNOWN and not r["options"]
    # at or above the floor it is still a "Did you mean"
    fake_nearest(monkeypatch, [(ans.ASK_FLOOR + 0.01, "concept:shelter", "what")] + NEAR_TIE[1:])
    assert asyncio.run(b.answer(Q))["status"] == "ask"


def test_in_the_cabin_the_question_gets_the_plain_unknown_once(world, monkeypatch):
    """The live path: a heard, device-directed question in the cabin -> "I don't know that one yet." (no options),
    and under the existing gate only once per 30 s."""
    fake_nearest(monkeypatch, NEAR_TIE)

    class Clock:
        t = 1000.0

        def __call__(self):
            return self.t
    clock = Clock()
    s = sessions.Session("dym-1", world[0], world[1], clock=clock, registry=registry)
    m = registry.create("shackleton_rim", 7)
    asyncio.run(s.handle({"t": "hello", "mode": "mission", "mission_id": m.id}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "cabin"}))

    def hear(text, advance):
        clock.t += advance
        asyncio.run(s.handle({"t": "turn", "state": "start", "text": ""}))
        asyncio.run(s.handle({"t": "arc", "device_directed": 0.95}))
        clock.t += 1.0
        asyncio.run(s.handle({"t": "turn", "state": "end", "text": text}))

    def says():
        return [d["text"] for d in s.outbox if d["t"] == "say"] + \
            [(d.get("r") or {}).get("say") for d in s.outbox if d["t"] == "answer"]
    hear(Q, 5)
    spoken = [t for t in says() if t]
    assert not any("Did you mean" in t for t in spoken), spoken
    assert sum(t.startswith("I don't know that one yet") for t in spoken) == 1, spoken
    hear(Q + " please", 5)
    assert sum(t.startswith("I don't know that one yet") for t in says() if t) == 1, "once per 30 s"
