"""[arch QA 0.5.2] A typed (or clearly meant) wrong answer on a word / place step is a real try: the router answers it,
the grader counts a miss and the hint ladder climbs, then the reveal. Noise, filler and our own echo stay ignored."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import session as sessions
from app.academy import content
from app.academy.routes import shown_line
from app.turn_router import Ctx, route
from tests.test_archaeology_course import _drop_caches

LAST_TTS = "What's the word for studying layers in the ground?"


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv(content.DEV_COURSE_ENV, "archaeology")
    _drop_caches()
    yield
    monkeypatch.delenv(content.DEV_COURSE_ENV, raising=False)
    _drop_caches()


def _ctx(st, **k):
    base = dict(screen="lesson", source="typed", dd=None, lessons=sessions._lessons(), sites=sessions._sites(),
                callsigns=sessions.CALLSIGNS, recent=[LAST_TTS], step=st, step_type=st["accept"]["type"])
    base.update(k)
    return Ctx(**base)


def _kw():
    st = content.lesson("archaeology:layers")["steps"][3]
    assert st["accept"]["type"] == "keywords"
    return st


def test_typed_wrong_words_are_tries_on_keywords_and_intent_steps(dev):
    kw = _kw()
    find = content.lesson("archaeology:what_is")["steps"][1]    # "Find Mesa Verde National Park…"
    assert find["accept"]["type"] == "intent"
    for text in ("history", "geology", "it is called history"):
        r = route(text, _ctx(kw))
        assert r["outcome"] == "answer" and r.get("sure"), (text, r)
    for text in ("Colorado", "Denver"):
        r = route(text, _ctx(find))
        assert r["outcome"] == "answer" and r.get("sure"), (text, r)


def test_noise_echo_and_filler_stay_ignored(dev):
    kw = _kw()
    for text in ("um", "Oh.", "hmm", "okay"):
        assert route(text, _ctx(kw, source="listen", dd=0.9))["outcome"] == "ignore", text
        assert route(text, _ctx(kw))["outcome"] == "ignore", text   # typed filler: no content word, not a try
    # our own voice, heard back while it plays
    assert route(LAST_TTS, _ctx(kw, source="listen", dd=0.9, speaking=True))["outcome"] == "ignore"
    # one room word Arc is NOT sure about is still too thin to grade
    assert route("geology", _ctx(kw, source="listen", dd=0.5))["outcome"] == "ignore"
    assert route("geology", _ctx(kw, source="listen", dd=None))["outcome"] == "ignore"
    # a confident spoken word on a word step is a try
    assert route("geology", _ctx(kw, source="listen", dd=0.95))["outcome"] == "answer"


def test_guess_steps_and_the_ride_never_get_the_sure_flag(dev):
    pred = content.lesson("archaeology:layers")["steps"][0]
    assert pred["accept"]["type"] == "predict"
    assert not route("history", _ctx(pred)).get("sure")      # a guess step never counts a miss
    assert not route("history", _ctx(_kw(), screen="ride")).get("sure")


def test_attempt_counts_a_sure_wrong_word_as_a_miss_then_hints_then_reveals(dev):
    from app.main import app
    lid, i = "archaeology:layers", 3
    with TestClient(app) as c:
        def post(text, misses, sure=True, step_s=5):
            return c.post("/api/academy/attempt", json={"lesson_id": lid, "step": i, "misses": misses, "step_s": step_s,
                                                        "input": {"text": text, **({"sure": True} if sure else {})}}).json()
        assert post("history", 0, sure=False)["status"] == "ignored"      # unsure, one word: as before
        r1 = post("history", 0)
        assert r1["status"] == "hint" and r1["say"], r1
        r2 = post("geology", 1)
        assert r2["status"] == "hint" and r2.get("phrase"), r2          # rung 2: the words are on the card
        r3 = post("geology", 2, step_s=60)
        assert r3["status"] == "passed" and r3["shown"] and r3["say"].startswith("Here it is."), r3
        assert post("um", 0)["status"] == "ignored"                       # filler, even typed


def test_reveal_line_drops_unearned_praise():
    a = "archaeology:dating"
    assert shown_line("Right. Anyone can re-measure a dated beam.", a) == "Here it is. Anyone can re-measure a dated beam."
    assert shown_line("That's it. Nearly 5,000 sites.", a) == "Here it is. Nearly 5,000 sites."
    assert shown_line("Stratigraphy: reading layers.", a) == "Here it is. Stratigraphy: reading layers."
    assert shown_line("Correct.", a) == "Here it is."
    # the Moon keeps its recorded reveal lines (voice pack) as they were
    assert shown_line("Right. Half the Moon is always sunny.", "phases") == "Here it is. Right. Half the Moon is always sunny."


def test_a_wrong_guess_is_acknowledged_in_a_course_pack(dev):
    from app.main import app
    lid = "archaeology:what_is"
    with TestClient(app) as c:
        r = c.post("/api/academy/attempt", json={"lesson_id": lid, "step": 0, "input": {"choice": "treasure"}}).json()
    assert r["status"] == "passed" and r["say"].startswith("You guessed: Treasure to collect. Clues."), r


def test_layers_hint_two_glows_the_next_layer_without_saying_it(dev):
    from app.academy import arch_steps
    st = content.lesson("archaeology:layers")["steps"][1]
    assert st["accept"]["type"] == "layers"
    h = arch_steps.hint(st, 2, [])
    assert h.get("answer") and "phrase" not in h and "glows" in h["say"]


def test_describe_steps_carry_their_picture_url(dev):
    pub = {l["id"]: l for l in content.public()["lessons"]}
    for lid in ("archaeology:survey", "archaeology:stuff"):
        st = pub[lid]["steps"][4]
        assert st["accept"]["type"] == "describe" and st["photo"]["url"].startswith("/api/courses/archaeology/media/")
    from app.main import app
    with TestClient(app) as c:
        assert c.get(pub["archaeology:survey"]["steps"][4]["photo"]["url"]).status_code == 200


def test_download_phase_from_the_desktop_flag(tmp_path):
    from app import course_packs
    f = tmp_path / "flag"
    for text, want in (("100 200", None), ("200 200 verify", "verify"), ("200 200 install", "install"), ("", None),
                       ("200 200 nonsense", None)):
        f.write_text(text)
        assert course_packs.phase(f) == want, text
        assert course_packs.progress(f) == (None if not text else round(int(text.split()[0]) / 200, 3))
