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


def test_space_words_are_woven_into_the_lessons():
    """v3: no separate words lesson (docs/LEARNING_DESIGN.md §5); each word comes with a place or a clip."""
    assert content.check() == []
    assert content.lesson("words") is None and "words" in content.course()["retired_badges"]
    vocab_lessons = {l["id"] for l in content.course()["lessons"]
                     if any(s["accept"]["type"].startswith("vocab_") for s in l["steps"])}
    assert {"history", "life"} <= vocab_lessons
    assert content.course()["lessons"][-1]["id"] == "checkride"      # the check ride stays last


def _vocab_steps(pub=False):
    les = content.public()["lessons"] if pub else content.course()["lessons"]
    return [(l["id"], i, s) for l in les for i, s in enumerate(l["steps"]) if s["accept"]["type"].startswith("vocab_")]


def test_public_vocab_steps_hide_the_answer():
    steps = [s for _, _, s in _vocab_steps(pub=True)]
    for s in steps:
        a = s["accept"]
        assert "distractors" not in a and a["source"]["url"]
        for o in a.get("options", []):
            assert set(o) == {"id", "label"} and o["id"].startswith("o")
    match = next(s["accept"] for s in steps if s["accept"]["type"] == "vocab_match")
    assert any("lava" in o["label"] for o in match["options"])   # meanings are the labels


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
        lid, k, _ = next(x for x in _vocab_steps() if x[2]["accept"]["term"] == "regolith")
        r = c.post("/api/academy/attempt", json={"lesson_id": lid, "step": k, "input": {"text": "rocks"}}).json()
        assert r["status"] == "hint" and r["rung"] == 1   # the hint ladder starts at the first miss
        say = next(d for d in r["decisions"] if d["t"] == "say")
        assert say["style"]["situation"] == "vocab" and say["style"]["controls"]["rate"] < 0
        r = c.post("/api/academy/attempt", json={"lesson_id": lid, "step": k, "input": {"text": "regolith"}}).json()
        assert r["status"] == "passed" and r["term"]["term"] == "regolith"
        say = next(d for d in r["decisions"] if d["t"] == "say")
        assert r.get("badge") or say["style"]["vocab"] == ["regolith"]   # a patch line keeps its proud style
