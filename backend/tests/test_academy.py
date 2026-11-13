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
    assert 6 <= len(c["lessons"]) <= 7
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
    assert [l["id"] for l in pub["lessons"]][:2] == ["moon", "comms"]
    r = client.post("/api/academy/attempt", json={"lesson_id": "moon", "step": 0, "input": {"text": "show me tycho"}}).json()
    assert r["status"] == "retry" and "hint" not in r
    r = client.post("/api/academy/attempt", json={"lesson_id": "moon", "step": 0, "input": {"text": "tycho"}, "misses": 1}).json()
    assert r["status"] == "hint" and "south pole" in r["hint"]
    r = client.post("/api/academy/attempt", json={"lesson_id": "moon", "step": 0, "input": {"text": "show me the south pole"}}).json()
    assert r["status"] == "passed" and r["next_step"] == 1 and "badge" not in r
    assert r["decisions"][0]["t"] == "lesson" and r["decisions"][1]["t"] == "say"
    r = client.post("/api/academy/attempt", json={"lesson_id": "moon", "step": 1, "input": {"tap": "shackleton"}}).json()
    assert r["status"] == "passed"
    r = client.post("/api/academy/attempt", json={"lesson_id": "moon", "step": 2, "input": {"choice": "ice"}}).json()
    assert r["status"] == "passed" and r["badge"]["id"] == "scout" and "next_step" not in r
    assert client.post("/api/academy/attempt", json={"lesson_id": "nope", "step": 0, "input": {}}).status_code == 404


GOOD = ["more power to the shields", "everyone to the shelter", "come out of the shelter", "send the rover for ice"]


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
    assert out["state"]["mission_time_h"] == 48 and out["state"]["resources"]["dose_msv"] < 50


def test_check_ride_storm_without_shelter_fails(client):
    wrong = ["more power to the shields", "end shift", "end shift", "end shift",   # 3 misses: no shelter, storm hits
             "come out of the shelter", "send the rover for ice"]
    out = _ride(client, wrong)
    assert out["status"] == "done" and out["passed"] is False and "badge" not in out


def test_shelter_cuts_storm_dose(client):
    good = _ride(client, GOOD)["state"]["resources"]["dose_msv"]
    bad = _ride(client, ["more power to the shields", "x", "x", "x", "come out of the shelter", "send the rover for ice"])
    assert bad["state"]["resources"]["dose_msv"] > good * 2


def test_ride_is_deterministic():
    from app.academy.content import lesson
    a, b = ride.start(lesson("checkride")["ride"]), ride.start(lesson("checkride")["ride"])
    ride.advance(a, "end"); ride.advance(b, "end")
    assert ride.hud(a)["resources"] == ride.hud(b)["resources"]
