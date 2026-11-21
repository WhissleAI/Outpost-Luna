"""Archaeology step types (docs/COURSES.md §3.2): layers, rings, hillshade, decide. Graders, hint ladder, public shape,
content checks, and the attempt API on a synthetic lesson (the course's own lessons: test_archaeology_course.py)."""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient

from app.academy import arch_steps as A, content, grade as g, guide, routes

LAYERS = {"type": "layers",
          "layers": [{"id": "topsoil", "label": "Topsoil", "say": ["top soil"], "h": 1},
                     {"id": "collapse", "label": "Roof fall", "say": ["collapse", "rubble", "roof"], "h": 1.4},
                     {"id": "ash", "label": "Ash", "say": ["ashes"], "h": 0.6, "finds": "charcoal"},
                     {"id": "floor", "label": "Floor", "say": ["house floor"], "h": 0.6, "finds": "sherd"},
                     {"id": "rock", "label": "Sandstone", "say": ["bedrock"], "h": 1}],
          "pit": {"id": "pit", "label": "Pit", "say": ["hole"], "from": "topsoil", "to": "ash"},
          "order": ["rock", "floor", "ash", "collapse", "pit", "topsoil"]}
RINGS = {"type": "rings", "series": "test_series", "master": [1200, 1290], "beam": [1226, 1275], "start": 1250}
HILL = {"type": "hillshade", "need": 2,
        "image": {"low": "a_low.jpg", "high": "a_high.jpg", "w": 1400, "h": 1000, "alt": "Lidar of a mesa top",
                  "credit": "USGS 3DEP", "source": {"title": "USGS 3DEP", "url": "https://www.usgs.gov/3d-elevation-program"}},
        "targets": [{"id": "house", "label": "Far View House", "say": ["far view"], "x": 0.3, "y": 0.4, "r": 0.05},
                    {"id": "lake", "label": "Mummy Lake", "say": ["reservoir", "lake"], "x": 0.7, "y": 0.6, "r": 0.06}]}
LAW = {"title": "ARPA (1979)", "text": "Taking artifacts from federal land needs a permit.",
       "source": {"title": "NPS", "url": "https://www.nps.gov/subjects/archeology/laws-regulations-guidelines.htm"}}
DECIDE = {"type": "decide", "law": LAW,
          "options": [{"id": "leave", "label": "Photograph it and leave it", "say": ["photo", "leave it"], "best": True,
                       "reply": "That's the call. Where it lies is part of the record."},
                      {"id": "take", "label": "Take it home", "say": ["take it", "keep it"],
                       "reply": "Tempting. But moved, it loses its place in the story. Leave it."}]}


@pytest.fixture(autouse=True)
def fake_series(tmp_path, monkeypatch):
    import json
    years = list(range(1150, 1300))
    idx = [round(1 + 0.6 * ((y * 7919) % 13 - 6) / 6, 3) for y in years]
    (tmp_path / "test_series.json").write_text(json.dumps({"id": "test_series", "years": years, "index": idx,
                                                           "title": "Test", "source": {"title": "t", "url": "https://x"}}))
    monkeypatch.setattr(A, "_SERIES_DIRS", [tmp_path])
    A.series.cache_clear()
    yield
    A.series.cache_clear()


def G(acc, inp):
    return g.grade({"accept": acc}, inp)


# ---- layers --------------------------------------------------------------------------------------------------------
def test_layers_in_order_by_voice():
    assert G(LAYERS, {"text": "sandstone, floor, ash, roof fall, pit, topsoil"})[0]
    assert G(LAYERS, {"text": A.answer_for({"accept": LAYERS})})[0]


def test_layers_build_up_over_turns_and_chips():
    ok, x = G(LAYERS, {"text": "bedrock then the house floor"})
    assert not ok and x == {"got": ["rock", "floor"], "next": "ash"}
    ok, x = G(LAYERS, {"choice": "ash", "got": x["got"]})
    assert not ok and x["got"] == ["rock", "floor", "ash"]
    ok, x = G(LAYERS, {"choice": "topsoil", "got": x["got"]})
    assert not ok and x["wrong"] == "topsoil" and x["got"] == ["rock", "floor", "ash"]
    assert G(LAYERS, {"text": "collapse, pit, topsoil", "got": ["rock", "floor", "ash"]})[0]
    assert G(LAYERS, {"text": "topsoil", "got": ["floor"]})[1]["got"] == []      # got must be a valid prefix


def test_the_intrusive_pit_trap_by_voice_and_by_chip():
    ok, x = G(LAYERS, {"text": "sandstone, floor, ash, pit, roof fall, topsoil"})
    assert not ok and x["trap"] == "pit" and x["cuts"] == ["collapse"] and x["got"] == ["rock", "floor", "ash"]
    ok, x = G(LAYERS, {"choice": "pit", "got": ["rock", "floor"]})
    assert not ok and x["trap"] == "pit" and x["cuts"] == ["collapse", "ash"]
    assert A.pit_cuts(LAYERS) == ["collapse", "ash"]


def test_layers_trap_hint_explains_cutting_never_wrong():
    st = {"accept": LAYERS, "hint": "The bottom layer went down first.", "fail": "Not quite."}
    h = guide.ladder(st, 0, {}, {"got": ["rock", "floor"], "trap": "pit", "cuts": ["collapse", "ash"]})
    assert h["trap"] == "pit" and "cuts through the roof fall and ash" in h["say"] and "wrong" not in h["say"].lower()
    h2 = guide.ladder(st, 1, {}, {"got": ["rock"]})
    assert h2["answer"] == "floor" and "phrase" not in h2   # [arch QA] it glows; its name is not handed over


def test_layers_plausible_and_room_talk():
    st = {"accept": LAYERS}
    assert g.plausible(st, "ash")
    assert g.plausible(st, "the pit")
    assert not g.plausible(st, "um okay")


# ---- rings ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,ok", [("1275", True), ("twelve seventy five", True), ("it's 1276", True),
                                     ("1274", True), ("1273", False), ("twelve hundred and seventy five", True),
                                     ("the outer ring is 1300", False)])
def test_rings_year_within_one(text, ok):
    assert G(RINGS, {"text": text})[0] is ok


def test_rings_lock_in_choice_and_offsets():
    ok, x = G(RINGS, {"choice": "1275"})
    assert ok and x == {"year": 1275, "off": 0}
    ok, x = G(RINGS, {"choice": "1260"})
    assert not ok and x["off"] == -15


def test_rings_hint_says_which_way_to_slide():
    st = {"accept": RINGS, "hint": "Match the narrow rings.", "fail": "Not that year."}
    assert "later: slide the beam right" in guide.ladder(st, 0, {}, {"year": 1260, "off": -15})["say"]
    assert "earlier: slide the beam left" in guide.ladder(st, 0, {}, {"year": 1290, "off": 15})["say"]
    assert guide.ladder(st, 1, {}, {"year": 1290, "off": 15})["cue"] == {"rings": "align"}


def test_rings_only_a_year_is_a_try():
    st = {"accept": RINGS}
    assert g.plausible(st, "twelve seventy five")
    assert not g.plausible(st, "hmm let me see")


def test_rings_public_has_real_widths_not_the_answer():
    p = A.public_accept(RINGS, course="archaeology")
    assert p["master"]["from"] == 1200 and len(p["master"]["w"]) == 91
    assert p["beam"]["n"] == 50 and p["beam"]["w"] == A.widths("test_series", 1226, 1275)
    assert p["beam"]["w"] == p["master"]["w"][26:76]               # the beam IS the master's own years: a real match
    assert "1275" not in str({k: v for k, v in p.items() if k not in ("master", "beam")}) and p["start"] == 1250


def test_year_words():
    assert A.year_of("one thousand two hundred eighty one") == 1281
    assert A.year_of("twelve oh five") == 1205
    assert A.year_of("eighteen point six years") is None


# ---- hillshade -----------------------------------------------------------------------------------------------------
def test_hillshade_taps_build_up_and_repeat_is_not_a_miss():
    ok, x = G(HILL, {"tap": {"x": 0.31, "y": 0.41}})
    assert not ok and x["got"] == ["house"] and x["new"] == ["house"] and x["next"] == "lake"
    ok, x = G(HILL, {"tap": {"x": 0.31, "y": 0.41}, "got": ["house"]})
    assert not ok and x.get("again")
    ok, x = G(HILL, {"tap": {"x": 0.1, "y": 0.1}, "got": ["house"]})
    assert not ok and x["new"] == []
    assert G(HILL, {"tap": {"x": 0.72, "y": 0.62}, "got": ["house"]})[0]


def test_hillshade_by_voice_names():
    assert G(HILL, {"text": "Far View House and the reservoir"})[0]
    assert G(HILL, {"text": A.answer_for({"accept": HILL})})[0]


def test_hillshade_hint_glows_then_shows():
    st = {"accept": HILL, "hint": "Look for straight shadow edges.", "fail": "Nothing there."}
    assert guide.help_rung(st, 2, ["house"])["focus"] == ["lake"]
    assert guide.help_rung(st, 3, ["house"])["answer"] == "lake"


def test_hillshade_public_urls_and_no_coordinates():
    p = A.public_accept(HILL, course="archaeology")
    assert p["image"]["low_url"] == "/api/courses/archaeology/media/a_low.jpg"
    assert all(set(t) <= {"id", "label", "x", "y", "r"} for t in p["targets"]) and p["need"] == 2
    bad = copy.deepcopy(HILL)
    bad["targets"][0]["lat"] = 37.2
    assert any("coordinates" in e for e in A.check_step({"accept": bad}))


# ---- decide --------------------------------------------------------------------------------------------------------
def test_decide_every_option_passes_with_its_own_reply_and_the_law():
    ok, x = G(DECIDE, {"choice": "take"})
    assert ok and x["best"] is False and x["better"] == "leave" and x["law"]["title"] == "ARPA (1979)"
    ok, x = G(DECIDE, {"text": "I'd photograph it and leave it"})
    assert ok and x["best"] is True and "better" not in x
    assert G(DECIDE, {"text": "two"})[1]["choice"] == "take"             # by its number
    assert G(DECIDE, {"text": "what a nice day"}) == (False, {})


def test_decide_checks_never_wrong_and_one_best():
    assert A.check_step({"accept": DECIDE}) == []
    bad = copy.deepcopy(DECIDE)
    bad["options"][1]["reply"] = "Wrong! Never do that."
    bad["options"][1]["best"] = True
    errs = A.check_step({"accept": bad})
    assert any("never say wrong" in e for e in errs) and any("exactly one best" in e for e in errs)


# ---- content checks ------------------------------------------------------------------------------------------------
def test_layers_checks_superposition_and_the_pit():
    assert A.check_step({"accept": LAYERS}) == []
    bad = copy.deepcopy(LAYERS)
    bad["order"] = ["rock", "floor", "pit", "ash", "collapse", "topsoil"]
    assert any("younger than every layer it cuts" in e for e in A.check_step({"accept": bad}))
    bad["order"] = ["floor", "rock", "ash", "collapse", "pit", "topsoil"]
    assert any("oldest at the bottom" in e for e in A.check_step({"accept": bad}))


def test_rings_checks():
    assert A.check_step({"accept": RINGS}) == []
    assert any("does not cover" in e for e in A.check_step({"accept": {**RINGS, "master": [1000, 1290]}}))
    assert any("8 years off" in e for e in A.check_step({"accept": {**RINGS, "start": 1272}}))


# ---- the attempt API on a synthetic lesson ---------------------------------------------------------------------------
def _lesson():
    step = lambda acc, **kw: {"prompt": "Do it.", "accept": acc, "hint": "Look closely.", "success": "Nice work.",  # noqa: E731
                              "fail": "Not yet.", **kw}
    return {"id": "t-arch", "title": "T", "brief": "B.", "badge": {"id": "t-arch", "name": "T"},
            "steps": [step(LAYERS), step(RINGS), step(HILL), step(DECIDE)]}


@pytest.fixture
def client(monkeypatch):
    les = _lesson()
    monkeypatch.setattr(content, "lesson", lambda lid: les if lid == "t-arch" else None)
    from app.main import app
    with TestClient(app) as c:
        yield c


def _post(c, i, inp, misses=0, step_s=60):
    return c.post("/api/academy/attempt", json={"lesson_id": "t-arch", "step": i, "input": inp, "misses": misses,
                                                 "step_s": step_s}).json()


def test_api_layers_progress_trap_and_pass(client):
    r = _post(client, 0, {"text": "sandstone and floor"})
    assert r["status"] == "progress" and r["got"] == ["rock", "floor"] and r["say"] == "Yes: Sandstone, Floor. What came next?"
    r = _post(client, 0, {"text": "pit", "got": ["rock", "floor", "ash"]})
    assert r["status"] == "hint" and "cuts through the roof fall" in r["say"] and r["got"] == ["rock", "floor", "ash"]
    r = _post(client, 0, {"text": "roof fall, pit, topsoil", "got": ["rock", "floor", "ash"]})
    assert r["status"] == "passed"


def test_api_rings_miss_then_pass(client):
    r = _post(client, 1, {"choice": "1262"})
    assert r["status"] == "hint" and "slide the beam right" in r["say"]
    assert _post(client, 1, {"text": "um"})["status"] == "ignored"
    assert _post(client, 1, {"text": "twelve seventy five"})["status"] == "passed"


def test_api_hillshade(client):
    r = _post(client, 2, {"tap": {"x": 0.3, "y": 0.4}})
    assert r["status"] == "progress" and r["say"] == "Yes: Far View House. 1 more to find."
    assert _post(client, 2, {"tap": {"x": 0.3, "y": 0.4}, "got": ["house"]})["status"] == "ignored"
    r = _post(client, 2, {"tap": {"x": 0.05, "y": 0.9}, "got": ["house"]}, misses=2)
    assert r["status"] == "passed" and r["shown"] and r["shown_answer"] == {"targets": ["house", "lake"]}


def test_api_decide_own_reply_law_and_last_step_badge(client):
    r = _post(client, 3, {"choice": "take"})
    assert r["status"] == "passed" and r["say"].startswith("Tempting.") and r["law"]["title"] == "ARPA (1979)"
    assert r["better"] == "leave" and r["badge"]["id"] == "t-arch"
    assert _post(client, 3, {"text": "the weather is nice today outside"})["status"] == "ignored"


def test_help_route_for_new_types(client):
    for i in range(4):
        r = client.post("/api/academy/hint", json={"lesson_id": "t-arch", "step": i, "rung": 1}).json()
        assert r["status"] == "help" and r["say"], i


def test_routes_answer_of():
    assert routes._answer_of({"accept": RINGS}) == {"year": 1275}
    assert routes._answer_of({"accept": DECIDE}) == {"choice": "leave"}
