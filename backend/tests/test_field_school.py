"""Field School (0.5, docs/LEARNING_DESIGN.md §12): the three new step types (describe, sequence, rounds), their hint
ladder and reveal, the four lessons, and the track that opens after the check ride."""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.academy import content, grade as g, guide, vocab
from app.main import app
from tools.handsfree_run import answer_for

FIELD = ["observe", "craters", "rocks", "fieldkit"]
DESC = {"type": "describe", "need": 3}
SEQ = {"type": "sequence", "items": [{"id": "photo", "label": "Photo", "say": ["photo", "picture"]},
                                     {"id": "sample", "label": "Sample", "say": ["sample"]},
                                     {"id": "bag", "label": "Bag", "say": ["bag"]}]}
RND = {"type": "rounds", "options": [{"id": "rake", "label": "Rake", "say": ["rake"]},
                                     {"id": "tongs", "label": "Tongs", "say": ["tongs"]},
                                     {"id": "scoop", "label": "Scoop", "say": ["scoop", "spoon"]}],
       "rounds": [{"id": "pebbles", "prompt": "Pebbles?", "answer": "rake", "hint": "Many small rocks.", "yes": "Yes."},
                  {"id": "soil", "prompt": "Soil?", "answer": "scoop", "hint": "Like a spoon.", "yes": "Yes."}]}


def G(acc, inp):
    return g.grade({"accept": acc}, inp)


# ---- describe: forgiving keyword coverage ------------------------------------------------------------------------
def test_describe_counts_descriptor_kinds_not_right_answers():
    ok, x = G(DESC, {"text": "it's huge and round with long shadows"})
    assert ok and x["got"] == ["size", "shape", "shadow"] and x["missing"] == ["tone", "texture"]
    ok, x = G(DESC, {"text": "it's tiny"})                  # nothing is "wrong": small is a size word too
    assert not ok and x["got"] == ["size"] and x["new"] == ["size"]


def test_describe_adds_up_over_turns_and_chips():
    ok, x = G(DESC, {"text": "it is big", "got": []})
    ok, x = G(DESC, {"text": "and bright", "got": x["got"]})
    assert not ok and x["got"] == ["size", "tone"] and x["new"] == ["tone"]
    ok, x = G(DESC, {"choice": "texture", "got": x["got"]})   # a chip: its kind's first word
    assert ok and x["got"] == ["size", "tone", "texture"]
    assert G(DESC, {"text": "bumpy", "got": ["size", "bogus"]})[1]["got"] == ["size", "texture"]   # unknown kinds dropped


@pytest.mark.parametrize("text,kind", [("the sunlit side", "shadow"), ("it's light grey", "tone"),
                                       ("a smooth floor", "texture"), ("an oval", "shape"), ("about 90 km", "size")])
def test_describe_words(text, kind):
    assert kind in G(DESC, {"text": text})[1]["got"]


def test_describe_room_talk_is_not_a_try_but_a_descriptor_is():
    st = {"accept": DESC}
    assert g.plausible(st, "big")                   # one descriptor word is a real try (it adds to the report)
    assert not g.plausible(st, "um okay")


# ---- sequence: a readback in order -------------------------------------------------------------------------------
def test_sequence_in_order_by_voice_or_chips():
    assert G(SEQ, {"text": "photo, sample, bag"})[0]
    ok, x = G(SEQ, {"text": "photo then bag"})
    assert not ok and x == {"got": ["photo"], "next": "sample"}
    ok, x = G(SEQ, {"choice": "sample", "got": ["photo"]})
    assert not ok and x["got"] == ["photo", "sample"] and x["next"] == "bag"
    ok, x = G(SEQ, {"choice": "photo", "got": ["photo", "sample"]})   # the wrong chip
    assert not ok and x["wrong"] == "photo" and x["got"] == ["photo", "sample"]
    assert G(SEQ, {"text": "bag", "got": ["photo", "sample"]})[0]
    assert G(SEQ, {"text": "bag", "got": ["sample"]})[1]["got"] == []   # got must be a prefix


# ---- rounds: one question, several times ---------------------------------------------------------------------------
def test_rounds_one_at_a_time():
    ok, x = G(RND, {"text": "the rake"})
    assert not ok and x["got"] == ["pebbles"] and x["next"] == "soil"
    ok, x = G(RND, {"text": "rake", "got": ["pebbles"]})
    assert not ok and x["got"] == ["pebbles"] and x["choice"] == "rake"
    assert G(RND, {"text": "a spoon", "got": ["pebbles"]})[0]
    assert G(RND, {"text": "number 3", "got": ["pebbles"]})[0]          # by its number
    assert not G(RND, {"text": "i like rocks"})[1].get("got")


# ---- the attempt API: progress, praise, hints, show ------------------------------------------------------------------
def _step(lid, kind):
    les = content.lesson(lid)
    return next(i for i, s in enumerate(les["steps"]) if s["accept"]["type"] == kind)


def _post(c, lid, i, inp, misses=0, step_s=60):
    return c.post("/api/academy/attempt", json={"lesson_id": lid, "step": i, "input": inp, "misses": misses,
                                                 "step_s": step_s}).json()


def test_describe_flow_praises_what_they_got_and_asks_for_the_missing_kind():
    i = _step("observe", "describe")
    with TestClient(app) as c:
        r = _post(c, "observe", i, {"text": "it's really big"})
        assert r["status"] == "progress" and r["got"] == ["size"] and r["say"].startswith("Good: size.")
        assert "what shape is it?" in r["say"]
        r = _post(c, "observe", i, {"text": "it looks really cool to me today", "got": ["size"]})   # adds nothing: a miss
        assert r["status"] == "hint" and r["got"] == ["size"] and "You have size." in r["say"]
        r = _post(c, "observe", i, {"text": "round and bright", "got": ["size"]})
        assert r["status"] == "passed" and r["say"].startswith("You noted size, shape and bright or dark.")
        r = _post(c, "observe", i, {"text": "it looks pretty amazing today", "got": []}, misses=2)
        assert r["status"] == "passed" and r["shown"] and r["shown_answer"]["say"]       # CAPCOM shows an example


def test_rounds_flow_and_the_reveal_moves_to_the_next_round():
    lid = "fieldkit"
    i = _step(lid, "rounds")
    rs = content.lesson(lid)["steps"][i]["accept"]["rounds"]
    with TestClient(app) as c:
        r = _post(c, lid, i, {"text": "rake"})
        assert r["status"] == "progress" and r["got"] == [rs[0]["id"]] and rs[1]["prompt"] in r["say"]
        r = _post(c, lid, i, {"text": "hammer", "got": r["got"]})
        assert r["status"] == "hint" and r["hint"] == rs[1]["hint"]
        r = _post(c, lid, i, {"text": "scoop", "got": [rs[0]["id"]]}, misses=2)    # third miss: shown, next round
        assert r["status"] == "progress" and r["shown"] and r["shown_answer"] == {"choice": "tongs"}
        assert r["got"] == [rs[0]["id"], rs[1]["id"]] and r["say"].startswith("Here it is: Tongs.")


def test_sequence_flow():
    lid = "fieldkit"
    i = _step(lid, "sequence")
    with TestClient(app) as c:
        r = _post(c, lid, i, {"text": "photo, describe"})
        assert r["status"] == "progress" and r["got"] == ["photo", "describe"] and "What comes next?" in r["say"]
        r = _post(c, lid, i, {"choice": "bag", "got": r["got"]})
        assert r["status"] == "hint"
        r = _post(c, lid, i, {"text": "sample, bag, call it in", "got": ["photo", "describe"]})
        assert r["status"] == "passed" and r.get("badge", {}).get("name") == "Field Ready"


def test_help_ladder_for_field_steps():
    st = content.lesson("fieldkit")["steps"][_step("fieldkit", "rounds")]
    h = guide.help_rung(st, 2, got=["pebbles"])
    assert h["eliminate"] != "tongs" and "crossed one out" in h["say"]
    assert guide.help_rung(st, 3, got=["pebbles"])["answer"] == "tongs"
    d = content.lesson("observe")["steps"][_step("observe", "describe")]
    assert guide.help_rung(d, 1, got=["size", "shape"])["say"] == "You have size and shape. Is it bright or dark?"
    assert guide.help_rung(d, 2, got=[])["phrase"] == d["example"]


@pytest.mark.parametrize("lid", FIELD)
def test_each_lesson_can_be_flown_by_voice(lid):
    """The hands-free script's answers pass every step (building up Field steps over turns)."""
    les = content.lesson(lid)
    with TestClient(app) as c:
        for i, st in enumerate(les["steps"]):
            got: list = []
            for _ in range(8):
                r = _post(c, lid, i, {"text": answer_for(st, vocab=vocab, got=got), **({"got": got} if got else {})})
                if r["status"] == "passed":
                    break
                assert r["status"] == "progress", (lid, i, r)
                got = r["got"]
            assert r["status"] == "passed" and not r.get("shown"), (lid, i, r)
    assert r["badge"]["id"] == les["badge"]["id"]


# ---- the lessons ----------------------------------------------------------------------------------------------------
def test_field_school_track():
    c = content.course()
    ids = [l["id"] for l in c["lessons"]]
    assert [l["id"] for l in c["lessons"] if l.get("track") == "field"] == FIELD
    assert ids[-1] == "checkride" and ids.index("fieldkit") < ids.index("checkride")
    for lid in FIELD:
        l = content.lesson(lid)
        assert l["unlock_after"] == "checkride" and not l.get("ride")
        assert len(l["steps"]) <= 5 and l["steps"][0]["accept"]["type"] == "predict", lid   # predict first
        assert l.get("ngss") and set(l["ngss"]) & {"MS-ESS1-3", "HS-ESS1-6"}, lid
        assert l.get("clip") or l.get("photo"), lid
    assert {s["accept"]["type"] for l in FIELD for s in content.lesson(l)["steps"]} >= {"describe", "sequence", "rounds"}
    assert content.lesson("observe")["badge"]["name"] == "Moon Observer"
    assert content.check() == []


def test_field_school_lines_fit_the_copy_budgets():
    for lid in FIELD:
        for s in content.lesson(lid)["steps"]:
            for r in s["accept"].get("rounds", []):
                assert len(f"{r['yes']} {r['prompt']}".split()) <= 20, r          # a round's spoken progress line
                assert len(r["yes"].split()) <= 8, r
            assert len(s["success"].split()) <= 8 and len(s["fail"].split()) <= 6, s["success"]
            if s["accept"]["type"] == "describe":   # praise for all five kinds + the success line
                assert len(f"You noted {g.describe_label(list(g.DESCRIBE))}. {s['success']}".split()) <= 20


def test_public_field_steps_hide_the_answers():
    for l in content.public()["lessons"]:
        for s in l["steps"]:
            a = s["accept"]
            if a["type"] == "rounds":
                assert all("answer" not in r and "hint" not in r for r in a["rounds"])
                assert all(set(o) == {"id", "label"} for o in a["options"])
            if a["type"] == "sequence" and not a.get("readback"):   # shown out of order (a readback: as heard)
                full = content.lesson(l["id"])["steps"][l["steps"].index(s)]["accept"]["items"]
                assert [o["id"] for o in a["items"]] != [o["id"] for o in full]
            if a["type"] == "describe":
                assert [c["id"] for c in a["cats"]] == list(g.DESCRIBE) and all(len(c["chips"]) == 2 for c in a["cats"])


def test_rock_rounds_name_real_pack_samples_with_text_fallbacks():
    st = content.lesson("rocks")["steps"][_step("rocks", "rounds")]
    rocks = [r["rock"] for r in st["accept"]["rounds"]]
    assert rocks == ["15016", "60025", "79115"] and all(r.get("clue") for r in st["accept"]["rounds"])


def test_field_facts_are_sourced_and_unverified_figures_stay_out():
    text = json.dumps([content.lesson(l) for l in FIELD])
    assert "382" not in text and not re.search(r"look odd", text, re.I)   # unverified: never shown (§12.4)
    concepts = json.loads((content.DATA / "learning" / "concepts.json").read_text())["concepts"]
    for k in ("crew_describe", "impact_craters", "maria_lava", "apollo_samples", "sampling_tools", "sampling_routine",
              "geology_training"):
        assert concepts[k]["source"]["url"].startswith("https://") and concepts[k]["checked"].startswith("2026-11-17")
