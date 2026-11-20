"""The Archaeology course (docs/COURSES.md §3, P3): its lessons, sources, respect rules, copy budgets, and a flight of
every lesson by voice to its patch, behind the dev flag (OUTPOST_DEV_COURSE=archaeology). Without the flag the Moon is
exactly as before."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.academy import arch_steps, content, grade as g, vocab
from tools.handsfree_run import answer_for

ROOT = Path(__file__).resolve().parents[2]
D = content.DATA / "courses" / "archaeology"
RAW = json.loads((D / "course.json").read_text())
SOURCES = {s["id"]: s for s in json.loads((D / "sources.json").read_text())["sources"]}
MANIFEST = json.loads((ROOT / "docs/courses/archaeology/course.manifest.json").read_text())
IDS = ["what_is", "survey", "layers", "dating", "stuff", "law", "voices", "mesa_verde", "capstone", "chimney_rock"]
words = lambda t: len(str(t or "").split())   # noqa: E731


def _drop_caches():
    content.reload()
    g.gaz.cache_clear()
    arch_steps.series.cache_clear()


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setenv(content.DEV_COURSE_ENV, "archaeology")
    _drop_caches()
    yield
    monkeypatch.delenv(content.DEV_COURSE_ENV, raising=False)
    _drop_caches()


def test_without_the_flag_the_moon_is_unchanged():
    _drop_caches()
    assert content.dev_course() is None
    assert content.course()["lessons"][0]["id"] == "moon" and "course" not in content.public()
    assert g.gaz().places.get("mesa_verde") is None


def test_the_flag_only_takes_a_known_course(monkeypatch):
    for bad in ("moon", "../etc", "Archaeology", "nope"):
        monkeypatch.setenv(content.DEV_COURSE_ENV, bad)
        assert content.dev_course() is None, bad


def test_lessons_load_prefixed_and_check_clean(dev):
    c = content.course()
    assert [l["id"] for l in c["lessons"]] == [f"archaeology:{i}" for i in IDS]
    assert all(l["badge"]["id"].startswith("archaeology:") for l in c["lessons"])
    assert content.check(content.course_file("archaeology")) == []
    assert content.check() == []
    p = content.public()
    assert p["course"] == "archaeology" and p["reading_level"] == "9-12"


def test_the_manifest_lists_these_lessons_and_its_files_exist():
    assert MANIFEST["lessons"]["ids"] == IDS
    from app import courses
    errs, planned = courses.validate(MANIFEST)
    assert errs == [] and "courses/archaeology/course.json" not in planned


def test_every_fact_is_sourced_and_its_numbers_are_in_the_opened_source():
    for l in RAW["lessons"]:
        assert 2 <= len(l["facts"]) <= 6, l["id"]
        for f in l["facts"]:
            s = SOURCES[f["source_id"]]
            assert s["status"] in ("supported", "partly") and f["source"]["url"] == s["url"], f
            hay = s["quote"] + " " + s["note"]
            for n in re.findall(r"\d[\d,.]*\d|\d", f["text"]):
                assert n.rstrip(".") in hay or n.replace(",", "") in hay, (l["id"], n, f["text"])


def test_law_cards_cite_opened_sources():
    for l in RAW["lessons"]:
        for s in l["steps"]:
            a = s["accept"]
            if a["type"] == "decide":
                assert a["law"]["source"]["url"] in {x["url"] for x in SOURCES.values()}, a["law"]


def _texts(o, skip=("quote",)):
    """Every string in o, except quoted speakers' own words (they may say "disappear" to deny it)."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k not in skip:
                yield from _texts(v, skip)
    elif isinstance(o, list):
        for v in o:
            yield from _texts(v, skip)
    elif isinstance(o, str):
        yield o


@pytest.mark.parametrize("name", ["course.json", "places.json", "entities.json", "ear_vocab.json"])
def test_respect_words(name):
    """§1.5 rule 6: Ancestral Puebloans, never the old term; moved, never vanished / disappeared."""
    text = "\n".join(_texts(json.loads((D / name).read_text())))
    assert not re.search(r"anasazi|vanish|disappear|extinct|mysterious", text, re.I), name


def test_tribal_words_are_quoted_from_their_source_and_never_spoken():
    q = [s["quote"] for l in RAW["lessons"] for s in l["steps"] if s.get("quote")]
    assert q, "Many voices shows a descendant's own words"
    for x in q:
        assert x["text"] in SOURCES["indigenous_voice"]["quote"] and "Laguna Pueblo" in x["who"]
        assert x["text"] not in json.dumps([s["prompt"] for l in RAW["lessons"] for s in l["steps"]])


def test_park_level_places_only():
    ps = json.loads((D / "places.json").read_text())["places"]
    for p in ps:
        assert p["estimated"] and p["kind"] == "park" and round(p["lat"], 2) == p["lat"] and round(p["lon"], 2) == p["lon"]
    every = json.dumps(RAW)
    assert not re.search(r'"(lat|lon|latitude|longitude)"\s*:', every)
    targets = json.loads(json.dumps([s["accept"].get("targets") for l in RAW["lessons"] for s in l["steps"]]))
    assert "lat" not in json.dumps(targets)


def test_no_remains_on_screen():
    for l in RAW["lessons"]:
        assert "remains" not in l.get("photo", {}).get("alt", "")
        for s in l["steps"]:
            assert not re.search(r"\b(bones?|skeleton|burial|grave)\b", s["prompt"], re.I)


def test_copy_fits_the_course_reading_level():
    """Grades 9-12 (decision 2): denser than the Moon's, still budgeted. Prompts <= 20 words; every spoken reply <= 20."""
    for l in RAW["lessons"]:
        assert len(l["steps"]) <= 5 and l["badge"]["glyph"], l["id"]
        assert l["steps"][0]["accept"]["type"] in ("predict", "decide"), l["id"]   # a hook or a call first
        for s in l["steps"]:
            assert words(s["prompt"]) <= 20, s["prompt"]
            assert words(s["success"]) <= 20 and words(s.get("reveal")) <= 20, s["success"]
            assert words(s["hint"]) <= 14 and words(s["fail"]) <= 8, s["hint"]
            for o in s["accept"].get("options", []):
                assert words(o.get("reply")) <= 20
                assert words(o["label"]) <= 8, o["label"]


def test_the_voice_roles_are_explained_as_the_capcom_houston_analogy():
    r = RAW["roles"]
    assert r["capcom"]["name"] == "Field Director" and "CAPCOM" in r["capcom"]["analogy"]
    assert r["houston"]["name"] == "the Lab" and "Houston" in r["houston"]["analogy"] and "delay" in r["houston"]["analogy"]
    assert "CAPCOM" in RAW["lessons"][0]["brief"] and "Houston" in RAW["lessons"][0]["brief"]
    assert "Houston" in next(l for l in RAW["lessons"] if l["id"] == "dating")["brief"]


def test_teacher_note_says_review_before_a_pilot():
    n = RAW["teacher_note"]
    assert "Crow Canyon" in n and "tribal cultural office" in n and "before a classroom pilot" in n.lower()


def test_new_step_types_are_all_used():
    used = {s["accept"]["type"] for l in RAW["lessons"] for s in l["steps"]}
    assert {"layers", "rings", "hillshade", "decide"} <= used


def test_media_and_data_files_exist_with_credits():
    cred = {c["file"]: c for c in json.loads((D / "media" / "credits.json").read_text())}
    names = set()
    for l in RAW["lessons"]:
        if l.get("photo"):
            names.add(l["photo"]["file"])
        for s in l["steps"]:
            im = s["accept"].get("image") or {}
            names |= {im[k] for k in ("low", "high") if im.get(k)}
    names.add("earth5400.jpg")
    for n in names:
        assert (D / "media" / n).is_file(), n
        assert cred[n]["licence"] and cred[n]["source_url"].startswith("https://") and cred[n]["alt"], n
    assert (D / "media").stat() and sum(p.stat().st_size for p in (D / "media").iterdir()) < 15_000_000


def test_the_tree_ring_series_is_real_and_cited():
    s = arch_steps.series("itrdb_co652")
    assert s and s["first_year"] <= 1200 and s["last_year"] >= 1300 and "Stahle" in s["citation"]
    st = next(x for l in RAW["lessons"] for x in l["steps"] if x["accept"]["type"] == "rings")
    assert st["accept"]["beam"][1] == 1275 and arch_steps.check_step(st) == []


def test_public_course_hides_answer_keys(dev):
    for l in content.public()["lessons"]:
        for s in l["steps"]:
            a = s["accept"]
            if a["type"] == "layers":
                assert "order" not in a
            if a["type"] == "rings":
                assert "beam" in a and "1275" not in json.dumps({k: v for k, v in a.items() if k not in ("master", "beam")})
            if a["type"] == "decide":
                assert all(set(o) == {"id", "label"} for o in a["options"])
            if a["type"] == "hillshade":
                assert a["image"]["low_url"].startswith("/api/courses/archaeology/media/")
        if l.get("photo"):
            assert l["photo"]["url"].startswith("/api/courses/archaeology/media/")


def test_course_media_route(dev):
    from app.main import app
    with TestClient(app) as c:
        assert c.get("/api/courses/archaeology/media/earth5400.jpg").status_code == 200
        assert c.get("/api/courses/archaeology/media/..%2Fcourse.json").status_code == 404
        assert c.get("/api/courses/archaeology/media/nope.jpg").status_code == 404
        assert any(p["id"] == "mesa_verde" for p in c.get("/api/places").json()["places"])


@pytest.mark.parametrize("lid", IDS)
def test_each_lesson_can_be_flown_by_voice_to_its_patch(dev, lid):
    from app.main import app
    full = f"archaeology:{lid}"
    les = content.lesson(full)
    with TestClient(app) as c:
        for i, st in enumerate(les["steps"]):
            got: list = []
            for _ in range(8):
                r = c.post("/api/academy/attempt", json={"lesson_id": full, "step": i, "misses": 0, "step_s": 60, "input": {
                    "text": answer_for(st, gaz=g.gaz(), vocab=vocab, got=got), **({"got": got} if got else {})}}).json()
                if r["status"] == "passed":
                    break
                assert r["status"] == "progress", (lid, i, r)
                got = r["got"]
            assert r["status"] == "passed" and not r.get("shown"), (lid, i, r)
    assert r["badge"]["id"] == f"archaeology:{les['badge']['id'].split(':')[-1]}"


def test_entities_and_ear_vocab():
    from app.entities.registry import Registry
    reg = Registry.load(D / "entities.json")
    names = {e.name for e in reg.entities}
    assert {"dendrochronology", "kiva", "NAGPRA", "Mesa Verde", "Hopi", "Zuni", "Ute Mountain Ute"} <= names
    v = json.loads((D / "ear_vocab.json").read_text())
    assert set(v) >= {"v", "places", "nations", "terms", "laws"} and "Ancestral Puebloans" in v["nations"]
