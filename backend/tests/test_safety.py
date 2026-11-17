"""[P0] Kid-turn safety: Arc Tagger's safety tags first, the offline word list as the backstop (app/safety.py)."""
from fastapi.testclient import TestClient

from app import safety
from app import turn_router as R
from app.main import app

REAL_READ = safety.tagger_read   # captured at import, before conftest's autouse stub replaces it per test

OWNER = "shit shit oh"   # the owner's room: Arc returned no profanity tag, a spurious pii.leak 0.99, device_directed 0.91
OWNER_ARC = [{"tag": "safety.pii.leak", "p": 0.99, "thr": 0.5, "on": True}]


def test_word_list_catches_what_the_tagger_missed():
    c = safety.classify(OWNER, OWNER_ARC)
    assert c["mask"] and c["words"]
    assert safety.mask_profanity("Shit. Shit.") == "S***. S***."


def test_tagger_flag_masks_even_without_a_listed_word():
    c = safety.classify("you are so dumb", [{"tag": "safety.toxicity.insult_harassment", "p": 0.91, "thr": 0.6, "on": True}])
    assert c["mask"] and not c["words"]


def test_flags_need_on_and_p_over_threshold():
    assert not safety.classify("hello", [{"tag": "safety.profanity", "p": 0.4, "thr": 0.6, "on": True}])["mask"]
    assert not safety.classify("hello", [{"tag": "safety.profanity", "p": 0.9, "thr": 0.6, "on": False}])["mask"]
    assert safety.classify("i want to hurt myself", [{"tag": "safety.crisis.self_harm", "p": 0.8, "thr": 0.5, "on": True}])["care"]


def test_a_false_pii_flag_does_not_hide_normal_text():
    c = safety.classify("where did apollo eleven land", OWNER_ARC)
    assert c["pii"] and not c["mask"] and not c["care"]


def test_moon_words_pass():
    for t in ["Hell crater", "open the cockpit", "pass the shields", "Scunthorpe"]:
        assert not safety.has_profanity(t), t


def test_router_never_routes_a_rude_turn():
    for screen in ("library", "map", "cabin", "callsign"):
        rt = R.route(OWNER, R.Ctx(screen=screen, source="voice", dd=0.91))
        assert rt["outcome"] == "ignore" and rt["reason"] == "safety" and not rt.get("notice"), (screen, rt)
    rt = R.route("what is that crater", R.Ctx(screen="library", source="voice", dd=0.9, unsafe=True))
    assert rt["outcome"] == "ignore"
    rt = R.route("A shit", R.Ctx(screen="lesson", step_type="choice", step_options=["A", "B"], source="typed"))
    assert rt["outcome"] == "ignore"


def test_audit2_router_fixes():
    """[audit2] "back to the map" mid-lesson navigates; a typed turn never vanishes silently."""
    for t in ("back to the map", "go to the map", "take me to the map", "show me the map", "go back to the map"):
        rt = R.route(t, R.Ctx(screen="lesson", step_type="choice", step_options=["I heard you", "Say again"], source="voice"))
        assert rt["outcome"] == "navigate" and rt["intent"] == "map", (t, rt)
    rt = R.route("hi", R.Ctx(screen="map", source="typed"))
    assert rt["outcome"] == "ignore" and rt["notice"]
    rt = R.route("Zed", R.Ctx(screen="callsign", source="typed", callsigns=["Nova"]))
    assert rt["outcome"] == "answer"
    rt = R.route("hello there", R.Ctx(screen="callsign", source="voice", callsigns=["Nova"]))
    assert rt["outcome"] == "ignore"


def test_a_rude_turn_is_never_graded():
    cl = TestClient(app)
    r = cl.post("/api/academy/attempt", json={"lesson_id": "moon", "step": 0, "input": {"text": "shit Sea of Tranquility"}, "misses": 0})
    assert r.status_code == 200 and r.json()["status"] == "ignored"


def test_crisis_backstop_is_specific():
    assert safety.classify("i want to kill myself")["care"]
    assert not safety.classify("kill the heaters")["care"]
    assert not safety.classify("the shields kill the radiation")["care"]


# ---- the session: the ear's Arc read rides on the turn; safety decides before the router ----
import asyncio  # noqa: E402

import pytest  # noqa: E402

from app import director, models_client, session as sessions  # noqa: E402
from app.config import settings  # noqa: E402
from app.gazetteer import Gazetteer  # noqa: E402
from app.moments import MomentIndex  # noqa: E402


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture()
def tagger(monkeypatch):
    seen = {"safety": []}

    async def fake_tag(text, domain="assistant", command_context=None):
        seen.setdefault("calls", []).append({"domain": domain, "command_context": command_context})
        return {"utterances": [{"safety": seen["safety"]}]}

    async def read(text, command_context=False):   # the real tagger_read over a fake /v1/tag (conftest stubs it elsewhere)
        return await REAL_READ(text, command_context)
    monkeypatch.setattr(models_client, "tag", fake_tag)
    monkeypatch.setattr(safety, "tagger_read", read)
    director.RULES.clear()
    director.PENDING.clear()
    return seen


def make(world, screen="library", mode="cadet"):
    s = sessions.Session("sf-1", world[0], world[1])
    asyncio.run(s.handle({"t": "hello", "mode": mode}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": screen}))
    return s


def heard(s):
    return [d for d in s.outbox if d["t"] == "heard"]


def test_session_owner_turn_is_ignored_silently_and_never_shown(world, tagger):
    tagger["safety"] = OWNER_ARC
    s = make(world)
    asyncio.run(s.handle({"t": "typed", "text": "Shit. Shit.", "source": "voice", "dd": 0.91, "safety": OWNER_ARC}))
    h = heard(s)[-1]
    assert h["outcome"] == "ignore" and h["reason"] == "safety" and h["text"] == "" and h["safety"]
    assert not [d for d in s.outbox if d["t"] in ("say", "card", "answer")]
    assert s.routes[-1]["text"] == "[safety]"


def test_session_tagger_flag_alone_ignores_a_library_question(world, tagger):
    tagger["safety"] = [{"tag": "safety.toxicity.insult_harassment", "p": 0.95, "thr": 0.6, "on": True}]
    s = make(world)
    asyncio.run(s.handle({"t": "typed", "text": "what is that ugly crater you idiot", "source": "typed"}))
    assert heard(s)[-1]["reason"] == "safety"


def test_session_false_pii_flag_still_answers(world, tagger):
    tagger["safety"] = [{"tag": "safety.pii.leak", "p": 0.99, "thr": 0.6, "on": True}]
    s = make(world)
    asyncio.run(s.handle({"t": "typed", "text": "where did apollo 11 land", "source": "typed"}))
    h = heard(s)[-1]
    assert h["outcome"] != "ignore" and h["text"] == "where did apollo 11 land" and not h.get("safety")


def test_session_client_copy_uses_its_own_arc_read_not_a_stale_one(world, tagger):
    s = make(world)
    asyncio.run(s.handle({"t": "typed", "text": "did you call your mother about sunday", "source": "voice", "dd": 0.1}))
    assert heard(s)[-1]["reason"] == "not_directed"
    asyncio.run(s.handle({"t": "typed", "text": "where did apollo 11 land", "source": "voice", "dd": 0.95}))
    assert heard(s)[-1]["outcome"] != "ignore"


def test_session_crisis_gets_the_care_line_and_a_flag(world, tagger):
    s = make(world, screen="map", mode="academy")
    asyncio.run(s.handle({"t": "typed", "text": "i want to kill myself", "source": "typed"}))
    assert [d["text"] for d in s.outbox if d["t"] == "say"] == [safety.CARE_LINE]
    assert s.flags and s.flags[-1]["kind"] == "care" and "text" not in s.flags[-1]
    tagger["safety"] = [{"tag": "safety.child.grooming_cue", "p": 0.3, "thr": 0.6, "on": True}]   # below threshold
    s2 = make(world)
    asyncio.run(s2.handle({"t": "typed", "text": "tell me about the far side", "source": "typed"}))
    assert not s2.flags


# ---- Arc Tagger 0.5: the kids domain, command_context on command screens, the grooming backstop ----
def test_grooming_backstop_is_specific():
    for t in ("send me a picture of yourself", "Send me a pic of you", "dont tell your parents",
              "don’t tell your mom about this", "add me on snap", "meet me in person", "send me a selfie",
              "keep it a secret from your dad"):
        c = safety.classify(t)
        assert c["care"] and "safety.child.grooming_cue" in c["tags"], t
    for t in ("show me a picture of the moon", "send me a picture of tycho", "send the rover a picture",
              "keep the secret base", "meet me at the crater", "tell your parents", "add me to the crew",
              "send the photos to houston"):
        assert not safety.classify(t)["care"], t


def test_command_screens():
    assert all(safety.command_context(s) for s in ("cabin", "brief", "ride"))
    assert not any(safety.command_context(s) for s in ("library", "map", "lesson", "callsign", "video", None, ""))


@pytest.mark.parametrize("screen,mode,cc", [("library", "cadet", False), ("map", "cadet", False),
                                            ("cabin", "mission", True), ("ride", "academy", True)])
def test_session_asks_the_kids_domain_with_command_context(world, tagger, screen, mode, cc):
    s = make(world, screen=screen, mode=mode)
    asyncio.run(s.handle({"t": "typed", "text": "kill the heaters", "source": "typed"}))
    kids = [c for c in tagger["calls"] if c["domain"] == "kids"]
    assert kids == [{"domain": "kids", "command_context": cc}]   # the safety read (once per turn)
    assert all(c["command_context"] is None for c in tagger["calls"] if c["domain"] != "kids")   # Director: as before
    assert not s.flags


def test_session_grooming_phrase_gets_the_care_line(world, tagger):
    s = make(world)
    asyncio.run(s.handle({"t": "typed", "text": "someone said send me a picture of yourself", "source": "typed"}))
    assert [d["text"] for d in s.outbox if d["t"] == "say"] == [safety.CARE_LINE]
    assert s.flags[-1]["tags"] == ["safety.child.grooming_cue"]
