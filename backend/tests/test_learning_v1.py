"""NASA Moon Learning & Media Plan v1: the two new lessons, video steps, Mission prep tasks, and the debrief's Learn more
mapping (frontend/src/story.js LEARN_MORE), checked against the course data and the sim's outcome names."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.academy import content
from app.academy.grade import grade, step_options
from app.main import app
from app.mission import gameplay, sim

ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "frontend" / "src" / "story.js"
words = lambda s: len(str(s).split())  # noqa: E731


def _videos():
    return [(l["id"], i, s) for l in content.course()["lessons"] for i, s in enumerate(l["steps"])
            if s["accept"]["type"] == "video"]


# ---- the course -----------------------------------------------------------------------------------------------------
def test_new_lessons_core_and_explorer_tracks():
    c = content.course()
    ids = [l["id"] for l in c["lessons"]]
    assert ids == ["moon", "phases", "power", "comms", "radiation", "life", "gravity", "history", "checkride"]
    track = {l["id"]: (l["track"], l.get("unlock_after_missions")) for l in c["lessons"]}
    assert track["gravity"] == ("explorer", 1) and track["history"] == ("explorer", 2)
    assert all(t == ("core", None) for k, t in track.items() if k not in ("gravity", "history"))
    ph, gr = content.lesson("phases"), content.lesson("gravity")
    assert ph["badge"]["name"] == "Moon Watcher" and set(ph["ngss"]) == {"1-ESS1-1", "MS-ESS1-1"}
    assert gr["badge"]["name"] == "Moonwalker" and gr["ngss"] == ["5-PS2-1"]
    # phases: predict -> phase loop -> terminator -> eclipse predict + crew clip -> eclipse video (the check folded in)
    assert [s["accept"]["type"] for s in ph["steps"]] == ["predict", "video", "terminator", "predict", "video"]
    assert [s["media"] for s in ph["steps"] if s.get("type") == "video"] == ["phases_loop", "lunar_eclipse"]
    clips = [ph["clip"]["clip_id"]] + [s["clip"]["clip_id"] for s in ph["steps"] if s.get("clip")]
    assert sorted(clips) == ["moon-during-eclipse-rare", "observing-pulsating-streamers-suns"]   # each clip once
    # gravity: feather or hammer -> the Apollo 15 drop -> backpack in kilos -> dust -> the word regolith
    assert [s["media"] for s in gr["steps"] if s.get("type") == "video"] == ["hammer_feather", "lunar_dust"]
    assert any("30 kilos" in s["prompt"] for s in gr["steps"])
    assert gr["steps"][-1]["accept"] == {"type": "vocab_say", "term": "regolith"}
    assert all(len(l["steps"]) <= 5 for l in c["lessons"] if not l.get("ride"))
    terms = [l["id"] for l in c["lessons"] for s in l["steps"] if s["accept"]["type"] == "terminator"]
    assert terms == ["phases"]                                               # one terminator step in the course


def test_briefs_never_give_away_a_prediction():
    """LEARNING_DESIGN §2: a brief sets up the question; it never says the answer the next predict / video asks for."""
    assert "far side" not in content.lesson("moon")["brief"].lower()
    assert "always" not in content.lesson("phases")["brief"].lower()
    assert "sharp" not in content.lesson("gravity")["brief"].lower()
    assert "skims" not in content.lesson("power")["brief"].lower()
    assert "nothing stops" not in content.lesson("radiation")["brief"].lower()


def test_spoken_style_in_the_new_lines():
    lines = [s[k] for l in content.course()["lessons"] for s in l["steps"] for k in ("prompt", "success", "reveal")
             if s.get(k)]
    assert not any("252,756" in t for t in lines)                            # numbers said the easy way
    assert not any("Artemis II" in t for t in lines)                         # spoken: "Artemis two"
    for lid in ("phases", "gravity"):
        for s in content.lesson(lid)["steps"]:
            assert words(s["success"]) <= 8, (lid, s["success"])
    assert content.lesson("life")["clip"]["note"] == "She says dark side. She means the night side."


def test_hooks_in_existing_lessons():
    media = {l: [s["media"] for s in content.lesson(l)["steps"] if s.get("type") == "video"]
             for l in ("moon", "radiation", "life")}
    assert media == {"moon": ["far_side_view"], "radiation": ["moon_weather"], "life": ["psr"]}
    moon = content.lesson("moon")["steps"]
    k = next(i for i, s in enumerate(moon) if s.get("media") == "far_side_view")
    assert "far side" in moon[k]["say"].lower() and "sunlight" in moon[k]["say"].lower()
    assert moon[k]["reveal"] == "Yes. Far side, not dark side."
    assert content.lesson("radiation")["steps"][0]["media"] == "moon_weather"      # the hook opens the lesson
    life = content.lesson("life")["steps"]
    assert life[0]["media"] == "psr" and life[1]["accept"]["type"] == "predict"    # psr before the LCROSS predict
    assert content.lesson("life")["patch_video"]["media"] == "water_extraction"     # at the patch, not a step
    assert any("CRaTER" in f["text"] and "2009" in f["text"] for f in content.lesson("radiation")["facts"])


def test_history_has_the_verified_artemis_facts():
    facts = " ".join(f["text"] for f in content.lesson("history")["facts"])
    assert "252,756 miles" in facts and "April 6, 2026" in facts
    assert "Artemis III is a 2027 test flight in Earth orbit" in facts and "early 2028" in facts
    assert "Moon Base" in facts and "pretend" in facts
    assert "IAU has not approved" in facts          # Integrity / Carroll: proposed, not official (Gazetteer, Nov 2026)


def test_cold_trap_wording_and_second_source():
    c = json.loads((content.DATA / "learning" / "concepts.json").read_text())["concepts"]["psr_cold"]
    assert "coldest spots measured" in c["text"] and "-246" in c["text"]
    assert {s["url"] for s in c["sources"]} >= {"https://www.nasa.gov/reference/moonbase-about/"}
    moon = " ".join(f["text"] for f in content.lesson("moon")["facts"])
    assert "coldest spots measured" in moon and "-235" not in moon


# ---- video steps ------------------------------------------------------------------------------------------------------
def test_every_video_step_is_valid_and_names_a_known_video():
    vs = _videos()
    assert len(vs) == 7
    for lid, i, s in vs:
        assert content.check_video_step(s) == [], (lid, i)
        assert s["media"] in content.VIDEO_IDS
        assert words(s["say"]) <= 20 and words(s["reveal"]) <= 20
    for l in content.course()["lessons"]:
        types = [s["accept"]["type"] for s in l["steps"]]
        assert all(not (a == b == "video") for a, b in zip(types, types[1:])), l["id"]   # never two in a row


@pytest.mark.parametrize("mutate,problem", [
    (lambda s: s.update(media="moon_cheese"), "unknown video media"),
    (lambda s: s.update(prompt="something else"), "prompt must equal say"),
    (lambda s: s.update(reveal="", success=""), "needs reveal"),
    (lambda s: s.update(say=" ".join(["word"] * 21), prompt=" ".join(["word"] * 21)), "say over 20 words"),
    (lambda s: s["accept"].update(media="psr"), "accept.media must match"),
    (lambda s: s["accept"].update(options=[{"id": "watch", "label": "Watch"}]), "watch and skip"),
])
def test_video_step_validator_catches_bad_steps(mutate, problem):
    s = copy.deepcopy(_videos()[0][2])
    mutate(s)
    assert any(problem in p for p in content.check_video_step(s)), content.check_video_step(s)


def test_course_check_rejects_a_bad_video_step(monkeypatch):
    c = copy.deepcopy(content.course())
    next(st for st in c["lessons"][0]["steps"] if st.get("type") == "video")["media"] = "not_a_video"
    monkeypatch.setattr(content, "course", lambda: c)
    assert any("unknown video media" in p for p in content.check())


def test_video_grading_never_blocks():
    st = _videos()[0][2]
    for c in ("watch", "watched", "skip", "offline"):
        assert grade(st, {"choice": c})[0]
    assert grade(st, {"text": "watch it"}) == (True, {"watched": True})
    assert grade(st, {"text": "skip"}) == (True, {"watched": False})
    assert not grade(st, {"text": "the hammer"})[0]
    assert [i for i, _ in step_options(st["accept"])] == ["watch", "skip"]


def test_video_step_through_the_api():
    lid, k, st = next(v for v in _videos() if v[0] == "life" and v[1] == 0)
    with TestClient(app) as c:
        pub = next(l for l in c.get("/api/academy/course").json()["lessons"] if l["id"] == lid)["steps"][k]
        assert pub["type"] == "video" and pub["media"] == "psr" and pub["reveal"] and pub["say"]
        assert pub["accept"] == {"type": "video", "media": "psr", "options": [{"id": "watch", "label": "Watch"},
                                                                              {"id": "skip", "label": "Skip"}]}
        r = c.post("/api/academy/attempt", json={"lesson_id": lid, "step": k, "input": {"text": "what is for lunch"}}).json()
        assert r["status"] == "ignored"                          # not Watch / Skip: never a miss
        r = c.post("/api/academy/attempt", json={"lesson_id": lid, "step": k, "input": {"choice": "watched"}}).json()
        assert r["status"] == "passed" and r["say"] == st["reveal"] and r["watched"] is True and r["next_step"] == 1
        ph = content.lesson("phases")["steps"]                   # phases ends on a video: Skip earns the patch
        r = c.post("/api/academy/attempt", json={"lesson_id": "phases", "step": len(ph) - 1,
                                                 "input": {"choice": "skip"}}).json()
        assert r["status"] == "passed" and r["badge"]["id"] == "watcher" and r["watched"] is False


# ---- Mission prep -----------------------------------------------------------------------------------------------------
PREP_AT = {"moon": "crater_drop", "phases": "oreo_phases", "gravity": "feather_coin", "power": "low_sun",
           "radiation": "ray_shield", "life": "make_regolith"}


def test_six_prep_tasks_on_their_lessons():
    got = {l["id"]: l["prep"]["id"] for l in content.course()["lessons"] if l.get("prep")}
    assert got == PREP_AT
    for lid in PREP_AT:
        p = content.lesson(lid)["prep"]
        assert content.check_prep(p) == [], lid
        assert 1 <= len(p["steps"]) <= 3 and p["steps"][-1].endswith("Tell me when it's ready.")
        assert not any(re.search(r"\bdone\b", t, re.I) for t in p["steps"])   # never speak the trigger word
        assert all(words(t) <= 20 for t in p["steps"])
        assert re.search(r"nasa\.gov|jpl\.nasa\.gov", p["source"]["url"]), p["source"]   # the NASA activity, in data
    assert content.lesson("moon")["prep"]["grown_up"] and content.lesson("power")["prep"]["grown_up"]
    assert not content.lesson("phases")["prep"]["grown_up"]


@pytest.mark.parametrize("mutate,problem", [
    (lambda p: p["steps"].append("One more thing. Tell me when it's ready."), "1 to 3 spoken steps"),
    (lambda p: p["steps"].__setitem__(-1, "All finished."), "must end with"),
    (lambda p: p["steps"].__setitem__(-1, "Say done when you're done. Tell me when it's ready."), "trigger word"),
    (lambda p: p.update(source={"title": "x", "url": "http://example.com"}), "https url"),
    (lambda p: p.update(grown_up="yes"), "grown_up must be true or false"),
    (lambda p: p["steps"].__setitem__(0, " ".join(["word"] * 21)), "over 20 words"),
])
def test_prep_validator_catches_bad_tasks(mutate, problem):
    p = copy.deepcopy(content.lesson("phases")["prep"])
    mutate(p)
    assert any(problem in x for x in content.check_prep(p)), content.check_prep(p)


def test_public_course_keeps_prep_for_the_client():
    with TestClient(app) as c:
        l = next(l for l in c.get("/api/academy/course").json()["lessons"] if l["id"] == "phases")
        assert l["prep"]["title"] == "Oreo phases" and len(l["prep"]["steps"]) == 3


# ---- debrief Learn more (story.js) and lesson numbers --------------------------------------------------------------
def _learn_more() -> dict:
    block = re.search(r"export const LEARN_MORE = \{(.*?)\n\};", STORY.read_text(), re.S).group(1)
    out = {}
    for m in re.finditer(r"^  (\w+): \{(.*?)\},?$", block, re.S | re.M):
        body = m.group(2)
        med = re.search(r'media: (null|"(\w+)")', body)
        onl = re.search(r'online: "(\w+)"', body)
        out[m.group(1)] = {"media": med.group(2) if med else None, "online": onl.group(1) if onl else None,
                           "fact": re.search(r'fact: "([^"]+)"', body).group(1)}
    return out


def test_learn_more_maps_every_sim_outcome_to_a_known_video_or_a_fact():
    lm = _learn_more()
    outcomes = set(re.findall(r'm\.outcome(?:, m\.lose_reason)? = True, "(\w+)"',
                              (ROOT / "backend/app/mission/sim.py").read_text()))
    assert outcomes == {"life_support_out", "dose_limit", "power_out", "survived"}
    assert set(lm) == outcomes
    assert lm["dose_limit"] == {**lm["dose_limit"], "media": "moon_weather", "online": "solar_eruptions"}
    assert lm["power_out"]["media"] is None                    # no video yet: a fact card
    assert lm["life_support_out"]["media"] == "water_extraction" and lm["survived"]["media"] == "meet_crew"
    for e in lm.values():
        assert all(x is None or x in content.VIDEO_IDS for x in (e["media"], e["online"]))
        assert words(e["fact"]) <= 20
    assert lm["dose_limit"]["online"] in content.VIDEO_MEDIA["online"]      # online-only pick is a YouTube video


def test_explorer_lessons_validate(monkeypatch):
    c = copy.deepcopy(content.course())
    g = next(l for l in c["lessons"] if l["id"] == "gravity")
    g.pop("unlock_after_missions")
    c["lessons"][-1]["track"] = "sideways"
    monkeypatch.setattr(content, "course", lambda: c)
    probs = content.check()
    assert any("unlock_after_missions" in p for p in probs) and any("track must be" in p for p in probs)


def test_mission_lesson_numbers_follow_the_course():
    order = [l["id"] for l in content.course()["lessons"] if not l.get("ride") and l["track"] == "core"]
    assert gameplay.LESSON_NO == {lid: k + 1 for k, lid in enumerate(order)}
    callbacks = dict(re.findall(r'lesson: "(\w+)", n: (\d+)', STORY.read_text()))
    assert callbacks and all(gameplay.LESSON_NO[l] == int(n) for l, n in callbacks.items()), callbacks
    assert sim.MISSION_H > 0   # the sim module still imports with the course-driven numbers
