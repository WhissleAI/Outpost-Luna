"""Round 7: the ear's per-screen hot lists (app/hotlist.py) and the relay's context message."""
import json

from app import hotlist as H
from app.academy import content


def test_vocab_is_versioned_data_in_sync_with_the_sources():
    d = json.loads(H.VOCAB_FILE.read_text())
    assert d["v"] == H.source_hash(), "run `python -m app.hotlist build` in backend/ after changing the course data"
    assert H.vocab()["v"] == d["v"]
    for k in ("places", "hardware", "crew", "glossary", "sites", "course", "orders", "panels", "nav", "help", "callsigns"):
        assert d[k], k
    assert "Malapert" in d["places"] and "Buzz Aldrin" in d["crew"] and any("Lunar Module" in h for h in d["hardware"])


def test_lesson_step_words_are_the_strong_tier():
    L = content.course()["lessons"][0]
    for i, st in enumerate(L["steps"]):
        h = H.hot_lists({"screen": "lesson", "lesson_id": L["id"], "step": i, "step_type": st["accept"]["type"]}, st)
        assert len(h["step"]) <= H.MAX_STEP and len(h["screen"]) <= H.MAX_SCREEN
        assert not {w.lower() for w in h["step"]} & {w.lower() for w in h["screen"] + h["names"]}
        for o in st["accept"].get("options") or []:
            assert o["label"] in h["step"]


def test_screens_are_rich():
    lib = H.hot_lists({"screen": "library"})
    # the Moon screens are about names: places, crew and hardware get their own strong tier there
    assert len(lib["names"]) > 150 and "Shackleton" in lib["names"] and "Buzz Aldrin" in lib["names"]
    assert "regolith" in lib["screen"]
    cab = H.hot_lists({"screen": "cabin"})
    assert "heaters" in cab["step"] and "comm panel" in cab["step"] and "Malapert Massif" in cab["step"]
    assert "Comet" in H.hot_lists({"screen": "callsign"})["step"]
    off = H.hot_lists({"screen": "patch", "offer": "next_lesson"})
    assert off["step"][:2] == ["next", "yes"]


def test_hot_match_tiers():
    lists = H.hot_lists({"screen": "cabin"})
    m = H.hot_match("more power to the heaters", lists)
    assert m["step"] >= 1
    assert H.hot_match("i think malapart", H.hot_lists({"screen": "library"}))["screen_sa"] >= 0.8
    assert H.hot_match("", lists) == {"step": 0, "screen": 0, "step_sa": 0.0, "screen_sa": 0.0}


def test_session_hot_words_follow_the_screen():
    from app.session import Session
    s = Session("hot-1", None, None)
    s.screen = {"screen": "cabin"}
    assert "heaters" in s.hot_words()["step"]
    s.screen = {"screen": "callsign"}
    assert "Comet" in s.hot_words()["step"]
