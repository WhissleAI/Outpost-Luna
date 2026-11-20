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
    assert 6 <= len(c["lessons"]) <= 16         # v4: 8 lessons and the check ride; 0.5: + 4 Field School; + 3 speech lessons
    assert c["lessons"][-1]["id"] == "checkride" and c["lessons"][-1]["badge"]["id"] == c["pass_badge"]
    for l in c["lessons"]:
        assert l["facts"] and all(f["source"]["url"].startswith("http") for f in l["facts"])
        for s in l["steps"]:
            assert s["accept"] and s["hint"] and s["success"] and s["fail"]


def test_check_catches_unsourced_number(monkeypatch):
    c = content.course()
    bad = {**c, "lessons": [{**c["lessons"][0], "facts": [{"text": "Shackleton is 98765 km wide.", "from": ["facts.json"],
                                                            "source": {"title": "x", "url": "https://planetarynames.wr.usgs.gov/"}},
                                                           {"text": "No source.", "from": ["facts.json"]}]}]}
    monkeypatch.setattr(content, "course", lambda: bad)
    probs = content.check()
    assert any("98765" in p for p in probs)   # (999 is a substring of 1999 in facts.json) and any("without a {title,url}" in p for p in probs)


def test_longest_night_is_recomputed_from_horizons():
    # JPL Horizons against the real LOLA skyline at each outpost (pipeline/site_physics.py; was one calibrated angle:
    # 157 h and 0 h). Shackleton Rim's spot starts the window in a ridge's shadow.
    assert content.longest_dark_h("malapert_massif") == 74
    assert content.longest_dark_h("shackleton_rim") == 53


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


# [0.4.1] the storm procedure: read Houston's order back, act, confirm
GOOD = ["yes", "Houston, any space weather?", "all crew into the shelter", "everyone to the shelter",
        "in the shelter, copy", "come out of the shelter", "send the rover for ice"]


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
    assert out["state"]["mission_time_h"] == 168 + 48 and out["state"]["resources"]["dose_msv"] < 50


def test_check_ride_storm_without_shelter_fails(client):
    wrong = ["yes", "Houston, any space weather?", "all crew into the shelter",
             "end shift", "end shift", "end shift",   # 3 misses: no shelter
             "in the shelter, copy", "come out of the shelter", "send the rover for ice"]
    out = _ride(client, wrong)
    assert out["status"] == "done" and out["passed"] is False and "badge" not in out


def test_shelter_cuts_storm_dose(client):
    good = _ride(client, GOOD)["state"]["resources"]["dose_msv"]
    # "x" is not a try (grade.plausible): ignored, no miss. Three real wrong orders let the storm hit.
    bad = _ride(client, ["yes", "Houston, any space weather?", "all crew into the shelter", "x",
                         "more power to the heaters", "end shift", "send the rover for ice", "in the shelter, copy",
                         "come out of the shelter", "send the rover for ice"])
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


# ---- novice playtest 2026-11-16 (docs/playtest/NOVICE_PLAYTEST_2026-11-16.md) ------------------------------------------
def test_check_ride_earth_is_really_up_when_the_question_says_so(client):
    """#11: step 1 says "Earth is up over the rim"; the clock bar must agree for the whole ride."""
    s = client.post("/api/academy/ride").json()
    assert s["state"]["env"]["earth_elev_deg"] > 0.5
    from app.academy import ride as rides
    r = rides.get(s["ride_id"])
    rides.advance(r, "end")
    assert rides.hud(r)["env"]["earth_elev_deg"] > 0.5
    L = content.lesson("checkride")
    assert all("day 2" not in st["prompt"].lower() for st in L["steps"])   # the clock says Day 8, not day 2


def test_help_climbs_the_ladder_without_a_miss(client):
    """#1: "help" / "I don't know" climb highlight -> label -> show; never the last miss line, never a miss."""
    k = _step("moon", "intent")
    r1, r2, r3 = (client.post("/api/academy/hint", json={"lesson_id": "moon", "step": k, "rung": n}).json() for n in (1, 2, 3))
    assert [r["rung"] for r in (r1, r2, r3)] == [1, 2, 3] and all(r["status"] == "help" for r in (r1, r2, r3))
    assert r1["focus"] == ["tranquillitatis"] and "label" not in r1
    assert r2["label"] == ["tranquillitatis"] and "Sea of Tranquility" in r2["say"]
    assert r3["show"] and r3["say"].startswith("Here it is") and "Tap" in r3["say"]
    assert "That's" not in r1["say"] + r2["say"] + r3["say"]


def test_help_rungs_for_every_step_say_what_to_do():
    from app.academy import guide
    for L in content.course()["lessons"]:
        if L.get("ride"):
            continue
        for s in L["steps"]:
            for n in (1, 2, 3):
                out = guide.help_rung(s, n)
                assert out["say"] and len(out["say"].split()) <= 20, (L["id"], s["prompt"], n, out["say"])
                if n == 3 and s["accept"]["type"] in ("choice", "compare", "earth_view"):
                    assert out["answer"] and out["say"].startswith("Here's the answer"), out


def test_terminator_help_draws_and_shows_the_line(client):
    k = _step("phases", "terminator")
    r = client.post("/api/academy/hint", json={"lesson_id": "phases", "step": k, "rung": 3}).json()
    assert r["line_lon"] == -45 and r["label_line"] and r["show"]
    st = content.lesson("phases")["steps"][k]
    assert st["globe"]["view_lon"] == st["accept"]["sun_lon"] - 90   # the edge runs down the middle of the view


def test_a_find_step_that_opens_glowing_labels_on_the_first_miss(client):
    """#5: the target glows from the start (the client sends rung 1), so the first miss adds the label."""
    k = _step("moon", "intent")
    cop = g.gaz().places["copernicus"]
    r = client.post("/api/academy/attempt", json={"lesson_id": "moon", "step": k, "misses": 0, "rung": 1,
                                                   "input": {"tap": {"lat": cop.lat, "lon": cop.lon}}}).json()
    assert r["rung"] == 2 and r["label"] == ["tranquillitatis"] and r["say"].startswith("That's Copernicus.")


def test_cabeus_is_labelled_cabeus():
    """#6: the label says the word the prompt asks for, not "LCROSS Centaur rocket impact site"."""
    from app.academy import guide
    L = content.lesson("life")
    st = next(s for s in L["steps"] if s["accept"]["type"] == "tap")
    assert "Cabeus crater" in st["prompt"] and guide.label_of(st, st["accept"]["place"]) == "Cabeus crater"
    assert "Cabeus crater" in guide.ladder(st, 1, {}, {})["say"] and "LCROSS Centaur" not in guide.ladder(st, 1, {}, {})["say"]
    pub = next(l for l in content.public()["lessons"] if l["id"] == "life")
    assert next(s for s in pub["steps"] if s["accept"]["type"] == "tap")["accept"]["label"] == "Cabeus crater"
    assert L["place"]["name"] == "Cabeus crater"


def test_video_guess_is_checked_after_the_video_or_skip(client):
    """#7: guess chips; the reply says whether the guess was right, then the answer, watched or skipped."""
    k = next(j for j, s in enumerate(content.lesson("phases")["steps"]) if s.get("media") == "lunar_eclipse")
    pub = next(l for l in content.public()["lessons"] if l["id"] == "phases")["steps"][k]["accept"]
    assert [o["id"] for o in pub["guess"]["options"]] == ["shadow", "cloud", "sun"] and "answer" not in pub["guess"]
    att = lambda v: client.post("/api/academy/attempt", json={"lesson_id": "phases", "step": k, "input": {"video": v}}).json()  # noqa: E731
    r = att({"watched": False, "skipped": True, "guess": "shadow"})
    assert r["status"] == "passed" and r["correct"] and r["say"].startswith("You guessed it!") and "Earth's shadow" in r["say"]
    r = att({"watched": True, "seconds": 30, "guess": "cloud"})
    assert not r["correct"] and r["answer"] == "shadow" and r["say"].startswith("Good guess.")
    r = att({"watched": False, "skipped": True})          # no guess: still the answer
    assert r["status"] == "passed" and "Earth's shadow" in r["say"]
    for L in content.course()["lessons"]:              # every "Guess, then watch" step has chips
        for s in L["steps"]:
            if s["accept"]["type"] == "video" and "guess" in s["prompt"].lower():
                assert s["accept"].get("guess", {}).get("options"), s["prompt"]


def test_wrong_order_teaches_never_say_again(client):
    """#10: "Shields up" in a storm: why it's not the one, then what to do; never "Say again?"."""
    k = _step("radiation", "command")
    r = _att(client, "radiation", k, {"text": "shields up"})
    assert r["status"] == "hint" and r["say"].startswith("Shields help a little") and "shelter" in r["say"].lower()
    for L in content.course()["lessons"]:
        for s in L["steps"]:
            assert not s["fail"].startswith("Say again"), (L["id"], s["prompt"])
    s = client.post("/api/academy/ride").json()
    rid = s["ride_id"]
    for st, a in enumerate(["yes", "Houston, any space weather?", "all crew into the shelter"]):
        client.post("/api/academy/attempt", json={"lesson_id": "checkride", "step": st, "ride_id": rid, "input": {"text": a}})
    r = client.post("/api/academy/attempt", json={"lesson_id": "checkride", "step": 3, "ride_id": rid,
                                                   "input": {"text": "shields up"}}).json()
    assert r["say"].startswith("Shields help a little") and "Say again" not in r["say"]


def test_come_out_leaves_the_shelter():
    """#13: kid words for the order the step expects."""
    st = content.lesson("checkride")["steps"][5]
    for t in ("come out", "everyone come out", "come out of the shelter", "get out"):
        assert g.grade(st, {"text": t})[0], t
        assert g.plausible(st, t), t
    assert not g.grade(content.lesson("checkride")["steps"][3], {"text": "come out"})[0]   # never the opposite order


def test_ride_never_says_the_same_sentence_twice(client):
    """#27: "Copy. Crew in the shelter. Crew in the shelter." -> the sim's news only."""
    from app.academy.routes import _new_news
    assert _new_news("Copy. Crew in the shelter.", "Crew in the shelter. Much less radiation, but science stops.") == \
        "Much less radiation, but science stops."
    assert _new_news("Copy. Crew is out. Back to work.", "Crew is out. Science can start again.") == "Science can start again."


def test_ride_hud_names_the_site_and_counts_its_own_days(client):
    """[0.3.12] The cabin clock read "Day 8 · Shift 1 ·" on a two-day ride: the HUD carries the site and the ride's day."""
    s = client.post("/api/academy/ride").json()["state"]
    assert s["site"]["name"].startswith("Shackleton")
    assert s["ride"] == {"day": 1, "days": 2}
    end = _ride(client, GOOD)["state"]
    assert end["ride"]["day"] == 2 and end["ride"]["days"] == 2


def test_ride_houston_answers_once(client):
    """[0.3.12] Check ride step 2 gave two replies (CAPCOM's success line, then Houston's, ~33 words). One reply, Houston's
    own, with the 1.3 s light-time line, 20 words or fewer."""
    out = _ride(client, GOOD[:2])
    assert out["status"] == "passed" and out["next_step"] == 2
    assert "sim_say" not in out
    assert out["say"].startswith("Houston here.") and "1.3 seconds" in out["say"]
    assert "Copy. Houston sees" not in out["say"]
    assert len(out["say"].split()) <= 20, out["say"]
    says = [d for d in out["decisions"] if d["t"] == "say"]
    assert len(says) == 1 and says[0]["text"] == out["say"]


def test_predict_waits_for_a_guess(client):
    """[0.3.12] Predict before watch: on a guess step, words that are not a guess are never a miss, so they never reveal
    the answer (it took a few unrelated typed lines and a slow minute to get "Here it is." before any guess)."""
    from app.academy.content import lesson
    les = lesson("phases")
    k = next(j for j, st in enumerate(les["steps"]) if st["accept"]["type"] == "predict")
    for misses in range(4):
        r = client.post("/api/academy/attempt", json={"lesson_id": "phases", "step": k, "misses": misses, "step_s": 120,
                                                      "input": {"text": "I think the moon is really cool tonight"}}).json()
        assert r["status"] == "ignored" and r["say"] == "", r
    r = client.post("/api/academy/attempt", json={"lesson_id": "phases", "step": k,
                                                  "input": {"choice": les["steps"][k]["accept"]["options"][0]["id"]}}).json()
    assert r["status"] == "passed"


def _ride_to(client, n):
    s = client.post("/api/academy/ride").json()
    for st, a in enumerate(GOOD[:n]):
        client.post("/api/academy/attempt", json={"lesson_id": "checkride", "step": st, "ride_id": s["ride_id"],
                                                   "input": {"text": a}})
    return s["ride_id"]


def _ride_att(client, rid, step, inp):
    return client.post("/api/academy/attempt", json={"lesson_id": "checkride", "step": step, "ride_id": rid,
                                                      "input": inp}).json()


def test_ride_storm_is_the_real_procedure(client):
    """[0.4.1] Houston calls the order -> readback (voice or taps, word by word) -> the act -> "In the shelter, copy"."""
    steps = content.lesson("checkride")["steps"]
    assert [s["accept"]["type"] for s in steps[2:5]] == ["sequence", "command", "sequence"]
    assert steps[2]["alert"] and "Houston: all crew into the shelter" in steps[2]["prompt"]
    assert len(steps[2]["prompt"].split("Houston: ")[1].split()) <= 20
    rid = _ride_to(client, 2)
    r = _ride_att(client, rid, 2, {"text": "all crew"})                      # half a readback: progress, no miss
    assert r["status"] == "progress" and r["got"] == ["crew"] and r["next"] == "shelter"
    r = _ride_att(client, rid, 2, {"text": "into the shelter", "got": ["crew"]})
    assert r["status"] == "passed" and r["next_step"] == 3
    assert not r["state"]["shelter"]                                        # a readback is words: nobody moved yet
    r = _ride_att(client, rid, 3, {"text": "everyone into the shelter"})
    assert r["status"] == "passed" and r["state"]["shelter"]
    r = _ride_att(client, rid, 4, {"choice": "in"})                          # the confirm by tap: chip by chip
    assert r["status"] == "progress"
    r = _ride_att(client, rid, 4, {"choice": "copy", "got": ["in"]})
    assert r["status"] == "passed" and r["say"].startswith("Houston copies") and r["next_step"] == 5


def test_ride_wrong_action_in_the_storm_still_counts_wrong(client):
    """Leave the shelter during the alert is a wrong order (graded, taught), never a pass."""
    rid = _ride_to(client, 3)
    r = _ride_att(client, rid, 3, {"text": "leave the shelter"})
    assert r["status"] == "hint" and r["say"].startswith("Wrong way") and not r["state"]["shelter"]
    r = _ride_att(client, rid, 3, {"text": "more power to the shields"})
    assert r["status"] == "hint" and r["say"].startswith("Shields help a little")
