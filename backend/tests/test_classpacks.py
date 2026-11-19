"""Class lessons (docs/CURRICULUM.md): the validator, the loader (never crashes), the course merge, grading through the
ordinary attempt API, and the guarded store API."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.academy import classpacks, content

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = json.loads((ROOT / "docs/class_packs/sample_room12.json").read_text())
HDR = {"X-Outpost-Class": "1", "Origin": "http://testserver"}


@pytest.fixture(autouse=True)
def class_dir(tmp_path, monkeypatch):
    d = tmp_path / "class"
    monkeypatch.setattr(classpacks, "DIR", d)
    classpacks._STATE["preview"] = None
    classpacks.reload()
    yield d
    classpacks._STATE["preview"] = None
    monkeypatch.setattr(classpacks, "DIR", None)
    classpacks.reload()


def pack(**over):
    p = copy.deepcopy(SAMPLE)
    p.update(over)
    return p


def msgs(errs):
    return " | ".join(f"{e['at']}: {e['msg']}" for e in errs)


# ---- validator ------------------------------------------------------------------------------------------------------
def test_the_sample_pack_is_valid():
    errs, warns = classpacks.validate(pack())
    assert errs == [] and warns == []


@pytest.mark.parametrize("mutate, at, words", [
    (lambda p: p["lessons"][0].update(title="A title that is far too long for a pin"), "lessons[0].title", "characters"),
    (lambda p: p["lessons"][0].update(title="Know your Moon"), "lessons[0].title", "NASA lesson"),
    (lambda p: p["lessons"][0].update(brief="One. Two. Three."), "lessons[0].brief", "1 or 2 sentences"),
    (lambda p: p["lessons"][0].update(place="atlantis"), "lessons[0].place", "place"),
    (lambda p: p["lessons"][0]["steps"][1].update(place="nowhere"), "lessons[0].steps[1].place", "place"),
    (lambda p: p["lessons"][0]["steps"][0].update(prompt=" ".join(["word"] * 21)), "lessons[0].steps[0].prompt", "20"),
    (lambda p: p["lessons"][0]["steps"][2].update(success="Correct and here are far too many words for success."),
     "lessons[0].steps[2].success", "8"),
    (lambda p: p["lessons"][0]["steps"][2].update(fail="No no no no no no no."), "lessons[0].steps[2].fail", "6"),
    (lambda p: p["lessons"][0]["steps"][2].update(options=["Big crater", "Small crater"]), "lessons[0].steps[2].options[1]", "share"),
    (lambda p: p["lessons"][0]["steps"][2].update(answer=7), "lessons[0].steps[2].answer", "right"),
    (lambda p: p["lessons"][0]["steps"][3].update(words=[]), "lessons[0].steps[3].words", "word"),
    (lambda p: p["lessons"][0]["steps"][3].update(prompt='Say "ejecta" back.'), "lessons[0].steps[3].prompt", "quote"),
    (lambda p: p["lessons"][0]["steps"][0].update(reveal=""), "lessons[0].steps[0].reveal", "reveal"),
    (lambda p: p["lessons"][0]["steps"][0].update(kind="dance"), "lessons[0].steps[0].kind", "kind"),
    (lambda p: p["lessons"][0]["facts"][0].update(source={"title": "x", "url": "http://plain.example"}),
     "lessons[0].facts[0].source", "https"),
    (lambda p: p["lessons"][0]["facts"][0].pop("source"), "lessons[0].facts[0].source", "source"),
    (lambda p: p["lessons"][0]["patch"].update(name="Three Word Patch"), "lessons[0].patch.name", "2"),
    (lambda p: p.update(id="Room 12!"), "id", "id"),
    (lambda p: p.update(format="something-else"), "format", "lesson pack"),
    (lambda p: p.update(lessons=[]), "lessons", "lesson"),
    (lambda p: p["lessons"][0].update(title="Craters 🌕"), "lessons[0].title", "emoji"),
])
def test_each_rule_names_the_field(mutate, at, words):
    p = pack()
    mutate(p)
    errs, _ = classpacks.validate(p)
    hit = [e for e in errs if e["at"] == at]
    assert hit, f"expected an error at {at}; got {msgs(errs)}"
    assert any(words.lower() in e["msg"].lower() for e in hit), msgs(hit)


def test_fail_plus_hint_budget_and_defaults():
    p = pack()
    p["lessons"][0]["steps"][2].update(fail="Not quite, look again.", hint="Look at the very bottom of the Moon near the pole now")
    errs, _ = classpacks.validate(p)
    assert any("10" in e["msg"] for e in errs if e["at"] == "lessons[0].steps[2].hint")
    p = pack()
    for s in p["lessons"][0]["steps"]:
        s.pop("success", None), s.pop("fail", None), s.pop("hint", None)
    assert classpacks.validate(p)[0] == []
    st = classpacks.compile_pack(p)[0]["steps"]
    assert all(s["success"] and s["fail"] and s["hint"] for s in st)


def test_warnings_do_not_block():
    p = pack()
    p["lessons"][0]["steps"].insert(1, copy.deepcopy(p["lessons"][0]["steps"][0]))
    errs, warns = classpacks.validate(p)
    assert errs == [] and any("same kind" in w["msg"] for w in warns)


def test_not_a_pack_at_all():
    for bad in (None, [], "text", 3):
        errs, _ = classpacks.validate(bad)
        assert errs


# ---- compile + course merge -----------------------------------------------------------------------------------------
def test_compiled_lesson_is_an_ordinary_course_lesson():
    L = classpacks.compile_pack(pack())[0]
    assert L["id"] == "c-room-12-craters" and L["track"] == "class" and L["pack"] == {"id": "room-12", "title": "Room 12 Moon unit"}
    assert L["badge"] == {"id": "c-room-12-craters", "name": "Crater Spotter", "glyph": "C"}
    types = [s["accept"]["type"] for s in L["steps"]]
    assert types == ["predict", "intent", "choice", "keywords"]
    assert all(f["source"]["url"].startswith("https://") for f in L["facts"])
    assert content.ACCEPT_TYPES and set(types) <= set(content.ACCEPT_TYPES)


def test_saved_pack_joins_the_course_after_nasa_and_check_stays_nasa_only(class_dir):
    n = len(content.nasa_course()["lessons"])
    errs, _ = classpacks.save(pack())
    assert errs == []
    ls = content.course()["lessons"]
    assert len(ls) == n + 1 and ls[-1]["id"] == "c-room-12-craters"
    assert ls[:n] == content.nasa_course()["lessons"]            # NASA lessons untouched, in front
    pub = {l["id"]: l for l in content.public()["lessons"]}
    les = pub["c-room-12-craters"]
    assert les["track"] == "class" and "answer" not in json.dumps(les["steps"][2]["accept"])
    assert content.check() == []                                  # the NASA checks never see Class lessons
    from app import session
    assert ("c-room-12-craters", "Craters up close") in session._lessons()   # voice: "lesson craters up close"
    assert classpacks.delete("room-12")
    assert len(content.course()["lessons"]) == n


def test_loader_skips_bad_files_and_never_raises(class_dir):
    class_dir.mkdir(parents=True)
    (class_dir / "a-good.json").write_text(json.dumps(pack()))
    (class_dir / "b-not-json.json").write_text("{ nope")
    (class_dir / "c-invalid.json").write_text(json.dumps(pack(id="other", lessons=[{"id": "x"}])))
    (class_dir / "d-dup.json").write_text(json.dumps(pack()))
    (class_dir / "e-huge.json").write_text(" " * (classpacks.MAX_BYTES + 1))
    (class_dir / "f-list.json").write_text("[1, 2]")
    classpacks.reload()
    assert [p["id"] for p in classpacks.packs()] == ["room-12"]
    probs = {p["file"]: p["msg"] for p in classpacks.problems()}
    assert set(probs) == {"b-not-json.json", "c-invalid.json", "d-dup.json", "e-huge.json", "f-list.json"}
    assert "not a JSON file" in probs["b-not-json.json"] and "Add a title" in probs["c-invalid.json"]
    assert "already uses the id" in probs["d-dup.json"] and "bigger than" in probs["e-huge.json"]
    assert any(l["id"] == "c-room-12-craters" for l in content.course()["lessons"])


def test_unreadable_dir_is_just_empty(monkeypatch, tmp_path):
    f = tmp_path / "file"
    f.write_text("x")
    monkeypatch.setattr(classpacks, "DIR", f / "class")   # a path under a file: can't exist
    classpacks.reload()
    assert classpacks.packs() == [] and content.course()["lessons"] == content.nasa_course()["lessons"]


# ---- grading through the attempt API ----------------------------------------------------------------------------------
def test_a_class_lesson_plays_through_the_attempt_api():
    from app.main import app
    c = TestClient(app)
    assert c.put("/api/class/packs/room-12", json=pack(), headers=HDR).status_code == 200
    lid = "c-room-12-craters"
    att = lambda step, inp, **kw: c.post("/api/academy/attempt", json={"lesson_id": lid, "step": step, "input": inp, **kw}).json()
    r = att(0, {"choice": "a"})
    assert r["status"] == "passed"
    r = att(1, {"tap": {"lat": 9.6, "lon": -20.1}})                     # Copernicus
    assert r["status"] == "passed", r
    r = att(2, {"text": "copernicus"})
    assert r["status"] in ("retry", "hint"), r
    r = att(2, {"text": "it's shackleton"})
    assert r["status"] == "passed", r
    r = att(3, {"text": "ejecta"})
    assert r["status"] in ("passed", "done"), r


# ---- the store API ------------------------------------------------------------------------------------------------------
def test_writes_need_the_app_itself_and_bad_packs_get_clear_messages():
    from app.main import app
    c = TestClient(app)
    assert c.put("/api/class/packs/room-12", json=pack()).status_code == 403
    assert c.put("/api/class/packs/room-12", json=pack(), headers={**HDR, "Origin": "https://evil.example"}).status_code == 403
    bad = pack()
    bad["lessons"][0]["place"] = "atlantis"
    r = c.put("/api/class/packs/room-12", json=bad, headers=HDR)
    assert r.status_code == 422 and any(e["at"] == "lessons[0].place" for e in r.json()["errors"])
    assert c.get("/api/class/packs").json()["packs"] == []
    r = c.put("/api/class/packs/room-12", content=b"{not json", headers={**HDR, "Content-Type": "application/json"})
    assert r.status_code == 422
    assert c.put("/api/class/packs/other", json=pack(), headers=HDR).status_code == 422   # id mismatch
    assert c.put("/api/class/packs/room-12", json=pack(), headers=HDR).json()["ok"] is True
    got = c.get("/api/class/packs/room-12").json()
    assert got["id"] == "room-12" and "saved_at" not in got
    listed = c.get("/api/class/packs").json()
    assert listed["packs"][0]["lessons"] == ["c-room-12-craters"]
    v = c.post("/api/class/validate", json=bad).json()
    assert v["ok"] is False and v["errors"]
    places = c.get("/api/class/places").json()
    assert {"copernicus", "shackleton"} <= {p["id"] for p in places}
    assert c.delete("/api/class/packs/room-12").status_code == 403
    assert c.delete("/api/class/packs/room-12", headers=HDR).status_code == 200
    assert c.delete("/api/class/packs/room-12", headers=HDR).status_code == 404


def test_two_packs_may_not_share_a_lesson_title():
    assert classpacks.save(pack())[0] == []
    errs, _ = classpacks.save(pack(id="room-13"))
    assert any("Another pack" in e["msg"] for e in errs)


def test_preview_plays_without_saving_and_is_marked():
    from app.main import app
    c = TestClient(app)
    r = c.post("/api/class/preview", json={"pack": pack(), "lesson": 0}, headers=HDR).json()
    assert r["ok"] and r["lesson_id"] == "c-preview-craters"
    L = content.lesson("c-preview-craters")
    assert L and L["preview"] is True
    assert classpacks.packs() == []                               # nothing saved
    assert c.delete("/api/class/preview", headers=HDR).status_code == 200
    assert content.lesson("c-preview-craters") is None


def test_reset_everything_removes_class_packs_start_over_keeps_them(class_dir, monkeypatch):
    from app import reset
    assert class_dir in reset.targets("all")["all"] and class_dir not in reset.targets("start")["start"]
