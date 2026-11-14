"""Director table cases (docs/REVAMP.md §3.5), claim check, and moment cutting."""
import asyncio

import pytest

from app import claims, knowledge, models_client
from app.config import settings
from app.director import direct
from app.gazetteer import Gazetteer
from app.moments import MAX_S, MIN_S, MomentIndex, cut_clip
from app.readout import summarize

GAZ = Gazetteer(settings.data_dir / "places.json")
IDX = MomentIndex(settings.data_dir / "index/clips.json")
NO_ARC = {"available": False}
KEYS = {"action", "say", "place", "view", "moment", "ask", "claims", "readout", "source", "corrected", "decisions"}  # decisions: additive (docs/SESSION_CONTRACT.md §2)


def ask(text, read=NO_ARC, context=None):
    return asyncio.run(direct(text, read, GAZ, IDX, context))


def arc(mentions):
    return {"available": True, "act": [], "intent": [], "mentions": mentions, "numbers": [], "pii": [],
            "hard_pii": [], "complete": True}


@pytest.fixture(autouse=True)
def offline_arc(monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", none)


# ---- Director table ---------------------------------------------------------------------------------------------------
def test_response_shape_is_the_contract():
    for text in ["show me Tycho", "what did the crew say about Hertzsprung", "show me the far side", "tell me a joke"]:
        assert set(ask(text)) == KEYS


def test_pii_guard_never_reaches_the_brain(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("embedder called on PII")
    monkeypatch.setattr(models_client, "embed", boom)
    raw = {"spans": [{"family": "pii", "type": "safety.pii.street_address", "text": "42 Oak Street"}],
           "utterances": [{}], "events": []}
    r = ask("my name is Maya and I live at 42 Oak Street near Tycho", summarize(raw))
    assert r["action"] == "guard" and r["place"] is None and "private" in r["say"]


def test_self_correction():
    r = ask("show me Tycho, wait no I mean Copernicus")
    assert r["place"] == "copernicus" and r["corrected"] and r["action"] == "fly"


def test_fly_says_a_card_line():
    r = ask("show me Tycho")
    assert r["action"] == "fly" and r["view"] == {"lat": -43.3, "lon": -11.2}
    card = knowledge.get(GAZ, IDX.facts).cards["place:tycho"]
    assert r["say"] in card["answers"]["about"] and all(c["status"] == "verified" for c in r["claims"])


def test_attribute_rules_pick_the_template():
    assert "85 km" in ask("how big is Tycho")["say"]
    assert "near side" in ask("where is Tycho")["say"]
    r = ask("when did Apollo 11 Eagle land")
    assert "July 20, 1969" in r["say"] and r["place"] == "apollo11_lm_eagle"


def test_crew_request_plays_moment_inside_clip_bounds():
    r = ask("what did the astronauts say about Hertzsprung")
    assert r["action"] == "play" and r["place"] == "hertzsprung"
    m = r["moment"]
    clip = next(c for c in IDX.clips if c["id"] == m["clip_id"])
    assert 0 <= m["t0"] < m["t1"] <= clip["dur"] and "hertzsprung" in m["places"]
    assert m["t1"] - m["t0"] <= MAX_S + 1 and r["say"].endswith("Listen!")


def test_crew_request_uses_last_place_from_context():
    r = ask("what did the crew say about it", context={"last_place": "vavilov"})
    assert r["action"] == "play" and r["place"] == "vavilov"


@pytest.mark.parametrize("text,place", [("is the moon made of cheese", "aristarchus"),
                                        ("the moon has no craters", "orientale"),
                                        ("the moon makes its own light", None)])
def test_misconception_gets_gentle_correction(text, place):
    r = ask(text)
    assert r["action"] == "say" and r["source"] == "misconception" and r["place"] == place
    if place:
        assert r["moment"] is None or place in r["moment"]["places"]


def test_ask_band_single_candidate():
    r = ask("show me Vavilof", arc(["Vavilof"]))  # fuzzy 85.7: inside 82-88
    assert r["action"] == "ask" and r["ask"]["options"] == ["vavilov"] and "Vavilov" in r["ask"]["question"]


def test_ask_band_two_close_candidates(monkeypatch):
    p = GAZ.places
    monkeypatch.setattr(GAZ, "candidates", lambda m, **k: [(p["ohm"], 92.0), (p["glushko"], 89.0)])
    r = ask("show me Zorbix", arc(["Zorbix"]))
    assert r["action"] == "ask" and r["ask"]["options"] == ["ohm", "glushko"]


def test_confident_fuzzy_link_flies():
    r = ask("show me Hertzprung", arc(["Hertzprung"]))
    assert r["action"] == "fly" and r["place"] == "hertzsprung"


def test_emotion_confused_is_shorter_and_bored_gets_mission():
    long = ask("show me Orientale")["say"]
    short = ask("show me Orientale", context={"emotion": "confused"})["say"]
    assert len(short) < len(long)
    assert "mission" in ask("this is boring", context={"emotion": "bored"})["say"].lower()


def test_jargon_question_uses_glossary():
    r = ask("what does albedo mean")
    assert r["action"] == "say" and "bright" in r["say"].lower()


def test_far_side_view():
    assert ask("show me the far side")["action"] == "view"


# ---- claim check -----------------------------------------------------------------------------------------------------
def test_claim_check_catches_wrong_number():
    cl = asyncio.run(claims.verify_draft("Tycho is 500 km wide. Its bright rays stretch more than 1,500 km.", ["tycho"],
                                         GAZ, IDX.facts))
    assert [c["status"] for c in cl] == ["removed", "verified"] and "not on the fact sheet" in cl[0]["source"]


def test_claim_check_blocks_places_not_in_play():
    cl = asyncio.run(claims.verify_draft("Tycho is right next to Copernicus.", ["tycho"], GAZ, IDX.facts))
    assert cl[0]["status"] == "removed"


def test_every_place_template_passes_the_claim_check():
    """Templates are filled from the data, so the safety net should never fire on them."""
    b = knowledge.get(GAZ, IDX.facts)
    for c in b.cards.values():
        if c["kind"] != "place":
            continue
        for attr, lines in c["answers"].items():
            for line in lines:
                cl = asyncio.run(claims.verify_draft(line, [c["place"]], GAZ, IDX.facts))
                assert all(x["status"] == "verified" for x in cl), (c["id"], attr, line, cl)


def test_estimated_place_size_is_never_said():
    say, cl, _ = asyncio.run(claims.guide_line(["integrity"], "how big is it", GAZ, IDX.facts))
    assert "km" not in say and "estimate" in say


def test_numbers_parse():
    vals = [v for _, v in claims.numbers_in("about 3.8 billion years, three rings, 1,500 km, one of the biggest")]
    assert vals == [3.8e9, 1500, 3]


# ---- moments ---------------------------------------------------------------------------------------------------------
def test_moments_never_split_an_utterance():
    for c in IDX.clips:
        words = c["words"]
        dur = c["dur"]
        t = lambda i: words[i][0] if i < len(words) else dur  # noqa: E731
        ms = [m for m in IDX.moments if m["clip_id"] == c["id"]]
        cuts = {m["words"][0] for m in ms} | {m["words"][1] for m in ms}
        for a, b in c["utterances"]:
            if t(b) - t(a) <= MAX_S:  # only over-long utterances may be subdivided
                assert not any(a < x < b for x in cuts), (c["id"], a, b)
        assert ms[0]["words"][0] == 0 and ms[-1]["words"][1] == len(words)
        for x, y in zip(ms, ms[1:]):
            assert x["words"][1] == y["words"][0]


def test_moment_lengths_and_fields():
    for m in IDX.moments:
        assert m["t0"] < m["t1"]
        assert m["t1"] - m["t0"] <= MAX_S * 1.6
        assert all(set(j) == {"t", "word", "explain"} and m["t0"] <= j["t"] <= m["t1"] for j in m["jargon"])
    in_range = [m for m in IDX.moments if MIN_S <= m["t1"] - m["t0"] <= MAX_S]
    assert len(in_range) >= 0.8 * len(IDX.moments)


def test_cut_clip_defensive_speaker_and_awe():
    clip = {"id": "x", "dur": 30.0, "words": [[i * 1.0, f"w{i}", "Christina Koch"] for i in range(30)],
            "utterances": [[0, 10], [10, 20], [20, 30]], "tags": [{"i": 3, "type": "FEATURE", "f": "tycho"}]}
    meta = {"awe_peaks": [{"t": 4.0, "score": 0.9}]}
    ms = cut_clip(clip, meta, {}, IDX.facts)
    assert ms[0]["speaker"] == "Christina Koch" and ms[0]["awe"] == 0.9 and ms[0]["places"] == ["tycho"]
    assert [m["words"] for m in ms] == [[0, 20], [20, 30]]


def test_moments_for_place_ranked_max5():
    ms = IDX.for_place("hertzsprung")
    assert 0 < len(ms) <= 5 and all("hertzsprung" in m["places"] for m in ms)


def test_unsafe_moments_are_never_ranked():
    assert all(m["kid_safe"] for p in GAZ.places for m in IDX.for_place(p))


def test_bridge_never_says_a_speaker_number():
    from app.director import _bridge
    assert _bridge({"speaker": "1"}).startswith("The crew")
    assert _bridge({"speaker": 0}).startswith("The crew")
    assert _bridge({"speaker": "Christina Koch"}).startswith("Christina")
