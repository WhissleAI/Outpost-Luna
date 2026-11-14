"""Space words: every term sourced, the four vocab step types graded by tap and by voice, the public course hides the
answer, /api/glossary, and the attempt route steers vocab lines slower with the word stressed (docs/VOCABULARY.md)."""
import pytest
from fastapi.testclient import TestClient

from app.academy import content, vocab
from app.academy.grade import grade
from app.main import app


def _opt(acc, term):
    return next(o["id"] for o in vocab.options(acc) if o["term"] == term)


def test_every_glossary_term_has_a_real_source():
    T = vocab.terms()
    assert len(T) >= 25
    for t in T.values():
        assert t["explain"] and t["source"]["url"].startswith("https://www.nasa.gov/"), t["term"]
        assert t["source"]["clip_id"] and t["source"]["t"] >= 0


def test_course_has_space_words_lesson_and_sprinkled_steps():
    assert content.check() == []
    les = content.lesson("words")
    assert les["badge"]["name"] == "Word Explorer"
    assert {s["accept"]["type"] for s in les["steps"]} == set(vocab.VOCAB_TYPES)
    for lid in ("moon", "history", "power"):
        assert any(s["accept"]["type"].startswith("vocab_") for s in content.lesson(lid)["steps"])
    assert content.course()["lessons"][-1]["id"] == "checkride"      # the check ride stays last


def test_public_vocab_steps_hide_the_answer():
    pub = next(l for l in content.public()["lessons"] if l["id"] == "words")
    for s in pub["steps"]:
        a = s["accept"]
        assert "distractors" not in a and a["source"]["url"]
        for o in a.get("options", []):
            assert set(o) == {"id", "label"} and o["id"].startswith("o")
    match = next(s["accept"] for s in pub["steps"] if s["accept"]["type"] == "vocab_match")
    assert any("bright" in o["label"] for o in match["options"])   # meanings are the labels


M = {"type": "vocab_match", "term": "albedo", "distractors": ["regolith", "terminator"]}
F = {"type": "vocab_fill", "term": "earthrise", "sentence": "the crew sees an ____.", "distractors": ["earthset", "corona"]}
L = {"type": "vocab_listen", "term": "crater", "distractors": ["basin", "limb"]}
S = {"type": "vocab_say", "term": "regolith"}


def test_match_by_tap_and_voice():
    st = {"accept": M}
    assert grade(st, {"choice": _opt(M, "albedo")})[0]
    assert not grade(st, {"choice": _opt(M, "regolith")})[0]
    assert grade(st, {"text": "albedo is how bright a surface is"})[0]
    assert grade(st, {"text": "how bright or dark it is in sunlight"})[0]
    assert not grade(st, {"text": "the moon's dusty rocky soil"})[0]
    assert not grade(st, {"text": "albedo"})[0]                    # naming the word isn't the meaning


@pytest.mark.parametrize("heard,ok", [("regolith", True), ("Regolith!", True), ("reggolith", True),
                                      ("it's called regolis", True), ("rocks", False), ("", False)])
def test_say_is_fuzzy_on_ear_words(heard, ok):
    assert grade({"accept": S}, {"text": heard})[0] is ok


def test_fill_and_listen_by_tap_and_voice():
    assert grade({"accept": F}, {"choice": _opt(F, "earthrise")})[0]
    assert grade({"accept": F}, {"text": "earth rise"})[0]
    assert not grade({"accept": F}, {"text": "earthset"})[0]
    assert grade({"accept": L}, {"text": "a crater"})[0]
    assert not grade({"accept": L}, {"text": "basin"})[0]
    assert not grade({"accept": L}, {"choice": _opt(L, "limb")})[0]


def test_glossary_endpoint_and_attempt_route():
    with TestClient(app) as c:
        g = c.get("/api/glossary").json()
        assert any(t["term"] == "albedo" for t in g["terms"])
        assert c.get("/api/glossary/regolith").json()["source"]["clip_id"]
        assert c.get("/api/glossary/nope").status_code == 404
        les = content.lesson("words")
        k = next(i for i, s in enumerate(les["steps"]) if s["accept"]["type"] == "vocab_say")
        r = c.post("/api/academy/attempt", json={"lesson_id": "words", "step": k, "input": {"text": "rocks"}}).json()
        assert r["status"] == "retry"
        say = next(d for d in r["decisions"] if d["t"] == "say")
        assert say["style"]["situation"] == "vocab" and say["style"]["controls"]["rate"] < 0
        r = c.post("/api/academy/attempt", json={"lesson_id": "words", "step": k, "input": {"text": "regolith"}}).json()
        assert r["status"] == "passed" and r["term"]["term"] == "regolith"
        say = next(d for d in r["decisions"] if d["t"] == "say")
        assert say["style"]["vocab"] == ["regolith"]
