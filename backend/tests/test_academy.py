"""Junior Astronaut Academy: the course is complete and sourced; every accept type grades; the check ride passes and fails."""
import pytest
from fastapi.testclient import TestClient

from app.academy import content, grade as g, ride
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_course_validates():
    assert content.check() == []
    c = content.course()
    assert 6 <= len(c["lessons"]) <= 9          # v4: 8 lessons and the check ride
    assert c["lessons"][-1]["id"] == "checkride" and c["lessons"][-1]["badge"]["id"] == c["pass_badge"]
    for l in c["lessons"]:
        assert l["facts"] and all(f["source"]["url"].startswith("http") for f in l["facts"])
        for s in l["steps"]:
            assert s["accept"] and s["hint"] and s["success"] and s["fail"]


def test_check_catches_unsourced_number(monkeypatch):
    c = content.course()
    bad = {**c, "lessons": [{**c["lessons"][0], "facts": [{"text": "Shackleton is 999 km wide.", "from": ["facts.json"],
                                                            "source": {"title": "x", "url": "https://planetarynames.wr.usgs.gov/"}},
                                                           {"text": "No source.", "from": ["facts.json"]}]}]}
    monkeypatch.setattr(content, "course", lambda: bad)
    probs = content.check()
    assert any("999" in p for p in probs) and any("without a {title,url}" in p for p in probs)


def test_longest_night_is_recomputed_from_horizons():
    assert content.longest_dark_h("malapert_massif") == 157
    assert content.longest_dark_h("shackleton_rim") == 0


def test_public_course_hides_answers():
    pub = content.public()
    for l in pub["lessons"]:
        for s in l["steps"]:
            assert "answer" not in s["accept"] and "expect" not in s["accept"]


INTENT = {"accept": {"type": "intent", "place": "shackleton"}}
TAP = {"accept": {"type": "tap", "place": "lcross_centaur_impact", "also": ["lcross_impact"], "radius_deg": 8}}
CMD = {"accept": {"type": "command", "expect": {"type": "shelter", "on": True}}}
MORE = {"accept": {"type": "command", "expect": {"type": "allocate", "to": "heaters", "more": True}}}
KW = {"accept": {"type": "keywords", "all": [["shield", "shields"], ["40", "forty"]]}}
ANY = {"accept": {"type": "keywords", "any": [["say again", "repeat"]]}}
CH = {"accept": {"type": "choice", "answer": "a8", "options": [{"id": "a8", "label": "Apollo 8", "say": ["eight"]},
                                                                 {"id": "a11", "label": "Apollo 11", "say": ["eleven"]}]}}


@pytest.mark.parametrize("step,inp,ok", [
    (INTENT, {"text": "show me the south pole"}, True),
    (INTENT, {"text": "take me to Shackleton"}, True),
    (INTENT, {"text": "show me Tycho"}, False),
    (INTENT, {"tap": {"lat": -88, "lon": 100}}, True),
    (TAP, {"tap": "lcross_impact"}, True),
    (TAP, {"tap": {"lat": -84.0, "lon": -50.0}}, True),
    (TAP, {"tap": {"lat": 20.0, "lon": 30.0}}, False),
    (TAP, {"tap": "tycho"}, False),
    (CMD, {"text": "everyone to the shelter"}, True),
    (CMD, {"text": "go hide in the shelter now"}, True),
    (CMD, {"text": "send the rover for ice"}, False),
    (MORE, {"text": "more power to the heaters"}, True),
    (MORE, {"text": "less power to the heaters"}, False),
    (MORE, {"text": "more power to the shields"}, False),
    (KW, {"text": "Copy, shields to forty"}, True),
    (KW, {"text": "copy shields to 40 percent"}, True),
    (KW, {"text": "copy that"}, False),
    (ANY, {"text": "say again please"}, True),
    (ANY, {"text": "okay"}, False),
    (CH, {"choice": "a8"}, True),
    (CH, {"choice": "a11"}, False),
    (CH, {"text": "it was apollo eight"}, True),
    (CH, {"text": "apollo eight or eleven"}, False),   # names both: not an answer
])
def test_grading(step, inp, ok):
    assert g.grade(step, inp)[0] is ok


def test_attempt_api_retry_hint_pass_badge(client):
    pub = client.get("/api/academy/course").json()
    assert [l["id"] for l in pub["lessons"]][:3] == ["moon", "phases", "power"]   # map order (LEARNING_DESIGN §11)
    A = lambda step, inp, misses=0: client.post("/api/academy/attempt", json={  # noqa: E731
        "lesson_id": "moon", "step": step, "input": inp, "misses": misses}).json()
    r = A(0, {"text": "show me tycho"})                                 # rung 1: the hint, and the place glows
    assert r["status"] == "hint" and r["rung"] == 1 and "dark plain" in r["hint"] and r["focus"] == ["tranquillitatis"]
    r = A(0, {"text": "tycho"}, 1)                                      # rung 2: the place gets its label
    assert r["status"] == "hint" and r["rung"] == 2 and r["label"] == ["tranquillitatis"]
    assert "Sea of Tranquility" in r["say"]
    r = A(0, {"text": "where neil armstrong landed"})
    assert r["status"] == "passed" and r["next_step"] == 1 and "badge" not in r
    assert r["decisions"][0]["t"] == "lesson" and r["decisions"][1]["t"] == "say"
    r = A(1, {"text": "yes, always"})                                   # earth_view: near side
    assert r["status"] == "passed" and r["answer"] == "yes"
    r = A(2, {"text": "time warp four please"})                          # video: words that aren't Watch / Skip
    assert r["status"] == "ignored"                                     # ... never count as a miss
    r = A(2, {"choice": "skip"})                                        # video: Skip (or offline) still moves on
    assert r["status"] == "passed" and r["next_step"] == 3 and r["watched"] is False
    assert r["say"] == "Yes. Far side, not dark side."                  # the reveal, said either way
    r = A(3, {"view": {"lat": 0, "lon": 175}})                          # globe_side: camera on the far side
    assert r["status"] == "passed"
    r = A(4, {"text": "tycho"}, 2)                                      # third miss: CAPCOM shows it and moves on
    assert r["status"] == "passed" and r["shown"] and r["shown_answer"] == {"place": "shackleton"}
    assert r["say"].startswith("Here it is.") and r["badge"]["id"] == "scout" and "next_step" not in r
    assert client.post("/api/academy/attempt", json={"lesson_id": "nope", "step": 0, "input": {}}).status_code == 404


GOOD = ["yes", "Houston, any space weather?", "everyone to the shelter", "come out of the shelter", "send the rover for ice"]


def _ride(client, answers):
    s = client.post("/api/academy/ride").json()
    rid, step, out = s["ride_id"], 0, None
    for a in answers:
        out = client.post("/api/academy/attempt", json={"lesson_id": "checkride", "step": step, "ride_id": rid,
                                                        "input": {"text": a}}).json()
        step = out.get("next_step", step)
    return out


def test_check_ride_pass(client):
    out = _ride(client, GOOD)
    assert out["status"] == "done" and out["passed"] and out["badge"]["id"] == "commander" and out["unlocks"] == "mission"
    assert "Mars" in out["fact"] and "Mars" not in out["say"]   # the Mars delay is on the result card, not spoken
    assert out["state"]["mission_time_h"] == 138 + 48 and out["state"]["resources"]["dose_msv"] < 50


def test_check_ride_storm_without_shelter_fails(client):
    wrong = ["yes", "Houston, any space weather?", "end shift", "end shift", "end shift",   # 3 misses: storm hits
             "come out of the shelter", "send the rover for ice"]
    out = _ride(client, wrong)
    assert out["status"] == "done" and out["passed"] is False and "badge" not in out


def test_shelter_cuts_storm_dose(client):
    good = _ride(client, GOOD)["state"]["resources"]["dose_msv"]
    # "x" is not a try (grade.plausible): ignored, no miss. Three real wrong orders let the storm hit.
    bad = _ride(client, ["yes", "Houston, any space weather?", "x", "more power to the heaters", "end shift",
                         "send the rover for ice", "come out of the shelter", "send the rover for ice"])
    assert bad["state"]["resources"]["dose_msv"] > good * 2


def test_ride_is_deterministic():
    from app.academy.content import lesson
    a, b = ride.start(lesson("checkride")["ride"]), ride.start(lesson("checkride")["ride"])
    ride.advance(a, "end"); ride.advance(b, "end")
    assert ride.hud(a)["resources"] == ride.hud(b)["resources"]


def test_readback_paraphrase_passes_on_the_same_command():
    import asyncio
    import json as _json

    from app.academy import grade as g
    from app.config import settings as _s
    c = _json.loads((_s.data_dir / "academy/course.json").read_text())
    steps = [s for les in c["lessons"] for s in les["steps"] if s["accept"]["type"] == "keywords"]
    heaters, again = steps[0], steps[1]
    assert not g.grade(heaters, {"text": "okay I'll make the heating forty percent"})[0]
    assert asyncio.run(g.similar(heaters, "okay I'll make the heating forty percent"))
    assert not asyncio.run(g.similar(heaters, "heaters to 14 percent"))           # numbers are never paraphrased
    assert g.grade(again, {"text": "could you repeat that"})[0]
    assert not g.grade(again, {"text": "roger"})[0]


# ---- the hint ladder (app/academy/guide.py, docs/PLAYTEST.md) ----------------------------------------------------------
def _att(client, lid, step, inp, misses=0):
    return client.post("/api/academy/attempt", json={"lesson_id": lid, "step": step, "input": inp, "misses": misses}).json()


def _step(lid, kind):
    L = next(l for l in content.course()["lessons"] if l["id"] == lid)
    return next(k for k, s in enumerate(L["steps"]) if s["accept"]["type"] == kind)


def test_ladder_says_what_tap_hit_and_what_to_do(client):
    k = _step("history", "route")
    cop = g.gaz().places["copernicus"]
    r = _att(client, "history", k, {"taps": [{"lat": cop.lat, "lon": cop.lon}]})
    assert r["status"] == "hint" and r["say"].startswith("That's Copernicus.") and "bullseye" in r["say"]
    assert r["focus"] == ["orientale"]


def test_route_progress_is_not_a_miss(client):
    k = _step("history", "route")
    o, h = (g.gaz().places[x] for x in ("orientale", "ohm"))
    r = _att(client, "history", k, {"taps": [{"lat": o.lat, "lon": o.lon}]})
    assert r["status"] == "progress" and r["got"] == ["orientale"] and r["next"] == "ohm"
    r = _att(client, "history", k, {"taps": [{"lat": o.lat, "lon": o.lon}], "text": "ohm"})   # the rest by voice
    assert r["status"] == "passed"
    r = _att(client, "history", k, {"taps": [{"lat": o.lat, "lon": o.lon}, {"lat": h.lat, "lon": h.lon}]})
    assert r["status"] == "passed"


def test_ladder_rung2_per_kind(client):
    k = _step("history", "choice")
    r = _att(client, "history", k, {"choice": "rover"}, 1)
    assert r["rung"] == 2 and r["eliminate"] in ("rover", "ice")
    k = _step("comms", "keywords")
    r = _att(client, "comms", k, {"text": "set the heaters"}, 1)   # a real try (names the heaters), missing the number
    assert r["phrase"].startswith("set the heaters") and "heaters" not in r["say"].lower()   # words on screen only
    k = _step("power", "command")
    r = _att(client, "power", k, {"text": "shields up"}, 1)        # a real order, the wrong one
    assert r["cue"]["to"] == "heaters"


def test_big_place_tap_anywhere_counts():
    st = {"accept": {"type": "intent", "place": "orientale"}}
    o = g.gaz().places["orientale"]
    assert g.grade(st, {"tap": {"lat": o.lat + 12, "lon": o.lon}})[0]          # on the bullseye, off its centre


def test_every_miss_line_short_and_actionable():
    from app.academy import guide
    for l in content.course()["lessons"]:
        if l.get("ride"):
            continue
        for s in l["steps"]:
            if s["accept"]["type"] == "predict":
                continue
            for m in (0, 1):
                out = guide.ladder(s, m, {"text": "um"}, {"got": []})
                assert len(out["say"].split()) <= 20, out["say"]
                assert out["say"].strip() not in ("Not that one.", "Not quite.", "Not there."), (l["id"], s["prompt"])
