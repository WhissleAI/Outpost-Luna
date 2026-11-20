"""Speech learning steps (docs/SPEECH_LEARNING.md): the read / vocab / summary graders, fluency, the feedback engine
(template, guard, safety fallback, the optional rewrite's fallbacks), the routes, and the three Moon sample lessons."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app import models_client
from app.academy import content, feedback as fb, grade as g, speech
from app.main import app
from tools.handsfree_run import answer_for

c = TestClient(app)
LESSONS = ("reading", "wordlab", "retell")


def step(lid: str, kind: str) -> dict:
    return next(s for s in content.lesson(lid)["steps"] if s["accept"]["type"] == kind)


READ = step("reading", "read")
VOCAB = step("wordlab", "vocab")
SUMMARY = step("retell", "summary")


def G(st, inp):
    return g.grade(st, inp)


def post(lid, i, inp, **kw):
    return c.post("/api/academy/attempt", json={"lesson_id": lid, "step": i, "input": inp, **kw}).json()


def idx(lid, kind):
    return next(i for i, s in enumerate(content.lesson(lid)["steps"]) if s["accept"]["type"] == kind)


# ---- read ----------------------------------------------------------------------------------------------------------
def test_sentences_split_the_passage():
    ss = speech.sentences(READ["accept"]["passage"]["text"])
    assert len(ss) == 7 and ss[2].startswith("LRO measured below minus 246") and ss[-1].startswith("Moon ice")


@pytest.mark.parametrize("inp", [{"choice": "a"}, {"text": "sunlight never reaches the floor"}, {"text": "a"},
                                 {"text": "the first one"}])
def test_read_choice_question_by_tap_key_and_words(inp):
    ok, ex = G(READ, inp)
    assert not ok and ex["got"] == ["q1"] and ex["next"] == "q2"


def test_read_wrong_choice_is_a_miss_on_that_question():
    ok, ex = G(READ, {"text": "it rains on the moon"})
    assert not ok and ex["got"] == [] and ex["next"] == "q1" and ex["choice"] == "b"


def test_read_say_and_find_questions():
    ok, ex = G(READ, {"text": "cabeus crater", "got": ["q1"]})
    assert ex["got"] == ["q1", "q2"]
    for inp in ({"choice": "s7"}, {"text": "sentence seven"}, {"text": "the last one"},
                {"text": "moon ice could give astronauts water air and rocket fuel"}):
        ok, ex = G(READ, {**inp, "got": ["q1", "q2"]})
        assert ok and ex["got"] == ["q1", "q2", "q3"], inp
    ok, ex = G(READ, {"text": "sentence two", "got": ["q1", "q2"]})
    assert not ok and ex["sentence"] == 1


def test_read_find_sentence_ignores_ties_and_too_few_words():
    t = READ["accept"]["passage"]["text"]
    assert speech.sentence_of(t, {}, "moon") is None
    assert speech.sentence_of(t, {}, "the cloud it kicked up held water") == 5


def test_read_got_is_a_valid_prefix_only():
    ok, ex = G(READ, {"choice": "a", "got": ["q3", "q1"]})
    assert ex["got"] == ["q1"]


# ---- vocab ---------------------------------------------------------------------------------------------------------
def test_vocab_public_hides_answers_and_shuffles_traps_in():
    pub = speech.public_accept(VOCAB["accept"])
    crater = next(i for i in pub["items"] if i["id"] == "crater")
    assert {o["label"] for o in crater["options"]} == {"crater", "basin", "creator"}
    assert all(set(o) == {"id", "label"} for o in crater["options"])
    assert "answer" not in str(pub) and "ok" not in str(next(i for i in pub["items"] if i["kind"] == "sentence"))


def test_vocab_say_the_word_and_traps_are_never_accepted():
    ok, ex = G(VOCAB, {"text": "crater"})
    assert ex["got"] == ["crater"] and ex["next"] == "lava"
    ok, ex = G(VOCAB, {"text": "larva", "got": ["crater"]})
    assert not ok and ex["trap"] == "larva" and ex["got"] == ["crater"]
    ok, ex = G(VOCAB, {"text": "lava", "got": ["crater"]})
    assert ex["got"] == ["crater", "lava"]
    ok, ex = G(VOCAB, {"text": "exterminator", "got": ["crater", "lava"]})
    assert not ok and ex["trap"] == "exterminator"


def test_vocab_pick_by_tap_and_by_key():
    opts = speech.word_options(speech.item_by_id(VOCAB["accept"], "crater"))
    right = next(o for o in opts if o["kind"] == "term")
    trap = next(o for o in opts if o["kind"] == "trap")
    assert G(VOCAB, {"choice": right["id"]})[1]["got"] == ["crater"]
    ok, ex = G(VOCAB, {"choice": trap["id"]})
    assert not ok and ex["trap"] == "creator"
    k = opts.index(right)
    assert G(VOCAB, {"text": "abcd"[k]})[1]["got"] == ["crater"]


def test_vocab_use_it_in_a_sentence_spoken_or_picked():
    got = ["crater", "lava", "terminator"]
    ok, _ = G(VOCAB, {"text": "regolith", "got": got})
    assert not ok                          # the word alone is not a sentence
    ok, _ = G(VOCAB, {"text": "the rover drove over the dusty regolith", "got": got})
    assert ok
    sopts = speech.sentence_options(speech.item_by_id(VOCAB["accept"], "regolith"))
    assert G(VOCAB, {"choice": next(o["id"] for o in sopts if o["ok"]), "got": got})[0]
    assert not G(VOCAB, {"choice": next(o["id"] for o in sopts if not o["ok"]), "got": got})[0]


def test_vocab_plan_from_spaced_repetition_is_validated():
    acc = {**VOCAB["accept"], "ask": 2}
    assert speech.vocab_plan(acc, ["lava", "nope", "lava", "regolith"]) == ["lava", "regolith"]
    assert speech.vocab_plan(acc, None) == ["crater", "lava"]
    ok, ex = G({**VOCAB, "accept": acc}, {"text": "lava", "plan": ["lava", "terminator"]})
    assert ex["got"] == ["lava"] and ex["next"] == "terminator"


# ---- summary -------------------------------------------------------------------------------------------------------
KID = "an astronaut dropped a hammer and a feather on the moon and they landed at the same time"


def test_summary_lexical_coverage():
    ok, ex = speech.grade_summary(SUMMARY["accept"], {}, KID)
    assert ok and ex["got"] == ["drop", "together"] and ex["missing"] == ["air", "who"]


def test_summary_ear_spellings_and_cumulative_turns():
    ok, ex = speech.grade_summary(SUMMARY["accept"], {}, "he droped a hamer and a fether")
    assert not ok and ex["new"] == ["drop"]
    ok, ex = speech.grade_summary(SUMMARY["accept"], {"got": ex["got"]}, "there was no air so they fell together")
    assert ok and ex["got"] == ["drop", "together", "air"] and ex["new"] == ["together", "air"]


def test_summary_embedder_and_mentions_add_points():
    ok, ex = speech.grade_summary(SUMMARY["accept"], {}, "something about space", embed_hits=["air"],
                                  mentions=["Apollo 15"])
    assert ok and ex["got"] == ["air", "who"] and ex["how"] == {"air": ["meaning"], "who": ["mention"]}


def test_summary_off_topic_covers_nothing():
    ok, ex = speech.grade_summary(SUMMARY["accept"], {}, "i like pizza and my dog is called rex")
    assert not ok and ex["got"] == []


# ---- fluency -------------------------------------------------------------------------------------------------------
PASS = "Near the Moon's south pole, some craters are so deep that sunlight never reaches their floors."


def test_fluency_counts_correct_words_and_pace():
    f = speech.fluency(PASS, "near the moons south pole some craters are so deep that sunlight never reaches their floors", 8)
    assert f["correct"] == f["of"] == 16 and f["wcpm"] == 120 and not f["skipped"] and f["repeats"] == 0


def test_fluency_skips_repeats_and_early_stop():
    f = speech.fluency(PASS, "near the moons south pole some some craters are so that sunlight", 6)
    assert f["skipped"] == ["deep"] and f["repeats"] == 1 and f["read_to"] == 12 and f["correct"] == 11


def test_fluency_nothing_heard_and_short_time():
    assert speech.fluency(PASS, "", 3)["correct"] == 0
    assert speech.fluency(PASS, "near the moons south pole", 2)["wcpm"] is None   # under 5 s: no pace


# ---- feedback engine -----------------------------------------------------------------------------------------------
ACC = SUMMARY["accept"]


def test_template_names_covered_and_one_missing_in_2_or_3_sentences():
    lines = fb.template(ACC, ["drop", "together"], ["air", "who"], fb.LEVELS["moon"], key="retell")
    text = " ".join(lines)
    assert 2 <= len(lines) <= 3 and "hammer and a feather" in text and "together" in text
    assert "no air" in text and "Apollo 15" not in text
    assert all(len(x.split()) <= 14 for x in lines) and len(text.split()) <= 36
    assert not fb.BANNED.search(text)


def test_template_all_covered_and_budget_shrink():
    lines = fb.template(ACC, ["drop", "together", "air", "who"], [], fb.LEVELS["moon"])
    assert lines[-1] in fb.ALL_DONE and len(" ".join(lines).split()) <= 36
    assert fb.guard(" ".join(lines), ACC, ["drop", "together", "air", "who"], [])[0]


def test_template_passes_its_own_guard():
    for cov, miss in ((["drop"], ["together", "air", "who"]), (["air", "who"], ["drop", "together"])):
        lines = fb.template(ACC, cov, miss, fb.LEVELS["moon"])
        assert fb.guard(" ".join(lines), ACC, cov, miss)[0], lines


@pytest.mark.parametrize("text,why", [
    ("Nice try. You said they dropped a hammer and a feather. That answer is wrong though.", "banned_word"),
    ("You said they dropped a hammer and a feather. One more point: the Moon has no air. Damn good job.", "safety"),
    ("You said they dropped a hammer and a feather in 1999. One more key point: the Moon has no air.", "new_number"),
    ("You said a hammer and a feather fell. Also, the Moon is made of cheese and lava lamps.", "new_words"),
    ("You said they dropped a hammer and a feather.", "sentences"),
    ("You said they dropped a hammer and a feather. They hit the ground together. Great.", "missing_not_named"),
    ("Good listening. Remember the Moon has no air to slow the feather. Next time add more.", "covered_not_named"),
    ("I am an AI model. You said they dropped a hammer and a feather. The Moon has no air.", "banned_word"),
])
def test_guard_rejects_unsafe_off_rubric_and_off_shape(text, why):
    ok, reason = fb.guard(text, ACC, ["drop"], ["air", "together"])
    assert not ok and reason.startswith(why), reason


def test_guard_takes_arc_tagger_safety_tags():
    good = "You said they dropped a hammer and a feather. One more key point: the Moon has no air to slow the feather."
    assert fb.guard(good, ACC, ["drop"], ["air"])[0]
    tags = [{"tag": "safety.toxicity", "p": 0.9, "thr": 0.5, "on": True}]
    assert fb.guard(good, ACC, ["drop"], ["air"], safety_tags=tags) == (False, "safety")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_feedback_template_by_default_and_rewrite_only_when_asked():
    f = run(fb.summary_feedback(ACC, ["drop", "together"], ["air", "who"], KID, "retell"))
    assert f["engine"] == "template" and 2 <= len(f["lines"]) <= 3
    f = run(fb.summary_feedback(ACC, ["drop"], ["air"], KID, "retell", rich=True))
    assert f["engine"] == "template" and f["why"] == "off"       # no local server configured


def test_feedback_rewrite_passes_guard_or_falls_back(monkeypatch):
    async def good(msgs):
        assert "Covered: an astronaut dropped a hammer and a feather" in msgs[1]["content"]
        return "You said an astronaut dropped a hammer and a feather. One more key point: the Moon has no air."

    async def unsafe(msgs):
        return "You said a hammer and a feather. The Moon has no air, damn."

    async def boom(msgs):
        raise RuntimeError("server down")

    async def invent(msgs):
        return "You said a hammer and a feather dropped. The Moon has no air, and aliens built Apollo."
    f = run(fb.summary_feedback(ACC, ["drop"], ["air"], KID, "retell", rich=True, rewrite_fn=good))
    assert f["engine"] == "rewrite" and len(f["lines"]) == 2
    for bad, why in ((unsafe, "safety"), (boom, "no_reply"), (invent, "new_words")):
        f = run(fb.summary_feedback(ACC, ["drop"], ["air"], KID, "retell", rich=True, rewrite_fn=bad))
        assert f["engine"] == "template" and f["why"].startswith(why) and f["lines"] == fb.template(
            ACC, ["drop"], ["air"], fb.LEVELS["moon"], key="retell")


def test_rewrite_server_is_loopback_only(monkeypatch):
    monkeypatch.setenv("OUTPOST_SUMMARY_LLM", "1")
    monkeypatch.setenv("OUTPOST_SUMMARY_LLM_URL", "http://127.0.0.1:8486")
    assert fb.llm_url() == "http://127.0.0.1:8486"
    for url in ("https://api.example.com", "http://10.0.0.5:8486", "http://evil.localhost.example:1"):
        monkeypatch.setenv("OUTPOST_SUMMARY_LLM_URL", url)
        assert fb.llm_url() is None
    monkeypatch.setenv("OUTPOST_SUMMARY_LLM", "0")
    monkeypatch.setenv("OUTPOST_SUMMARY_LLM_URL", "http://127.0.0.1:8486")
    assert fb.llm_url() is None


def test_level_budgets_follow_the_course():
    assert fb.level_for("retell") == fb.LEVELS["moon"]
    assert fb.level_for("archaeology:dating") == fb.LEVELS["archaeology"]


# ---- routes --------------------------------------------------------------------------------------------------------
def test_route_read_flow_progress_hint_reveal_and_pass():
    i = idx("reading", "read")
    r = post("reading", i, {"text": "it rains"})
    assert r["status"] == "hint" and "first sentence" in r["say"]
    r = post("reading", i, {"choice": "a"})
    assert r["status"] == "progress" and r["got"] == ["q1"] and "LCROSS" in r["say"]
    r = post("reading", i, {"text": "the outpost", "got": ["q1"]}, misses=2, step_s=30)
    assert r["status"] == "progress" and r["shown"] and r["got"] == ["q1", "q2"] and "Cabeus" in r["say"]
    r = post("reading", i, {"choice": "s7", "got": ["q1", "q2"]})
    assert r["status"] == "passed" and r["next_step"] == i + 1


def test_route_room_talk_is_ignored_never_a_miss():
    assert post("reading", idx("reading", "read"), {"text": "um"})["status"] == "ignored"
    assert post("retell", idx("retell", "summary"), {"long_text": "okay so"})["status"] == "ignored"
    assert post("retell", idx("retell", "summary"), {"long_text": "the shit hammer fell"})["status"] == "ignored"


def test_route_vocab_trap_note_then_pass():
    i = idx("wordlab", "vocab")
    r = post("wordlab", i, {"text": "creator"})
    assert r["status"] == "hint" and "makes things" in r["say"] and r["trap"] == "creator"
    got = []
    for word in ("crater", "lava", "terminator"):
        r = post("wordlab", i, {"text": word, "got": got})
        got = r["got"]
    assert r["status"] == "progress" and "sentence" in r["say"]
    r = post("wordlab", i, {"text": "our rover rolled across the gray regolith", "got": got})
    assert r["status"] == "passed" and r["next_step"] == i + 1


def test_route_summary_progress_then_feedback_never_a_grade():
    i = idx("retell", "summary")
    r = post("retell", i, {"long_text": "an astronaut dropped a hammer and a feather"})
    assert r["status"] == "progress" and r["got"] == ["drop"] and r["say"].endswith("What happened when they landed?")
    r = post("retell", i, {"long_text": "and they landed at the same time", "got": r["got"]})
    assert r["status"] == "passed" and r["engine"] == "template" and 2 <= len(r["feedback"]) <= 3
    assert "no air" in r["say"] and not fb.BANNED.search(r["say"])


def test_route_summary_embedder_counts(monkeypatch):
    async def emb(texts, kind="query", timeout=None):   # the clause and the "no air" phrasings point the same way
        return [[1.0, 0.0] if ("vacuum" in t or "air" in t or "nothing up there" in t) else [0.0, 1.0] for t in texts]
    monkeypatch.setattr(models_client, "embed", emb)
    r = post("retell", idx("retell", "summary"), {"long_text": "they dropped a hammer and a feather and nothing up there slowed it"})
    assert r["status"] == "passed" and set(r["got"]) >= {"drop", "air"} and "meaning" in r["how"]["air"]


def test_route_summary_nothing_new_hints_then_shows_a_model_summary():
    i = idx("retell", "summary")
    r = post("retell", i, {"long_text": "it was a cool video about space stuff"})
    assert r["status"] == "hint" and "?" in r["say"]
    r = post("retell", i, {"long_text": "it was a cool video about space stuff"}, misses=2, step_s=40)
    assert r["status"] == "passed" and r["shown"] and "David Scott" in r["say"]


def test_route_help_rungs_per_question():
    i = idx("reading", "read")
    h = c.post("/api/academy/hint", json={"lesson_id": "reading", "step": i, "rung": 2}).json()
    assert h["eliminate"] in ("b", "c")
    h = c.post("/api/academy/hint", json={"lesson_id": "reading", "step": i, "rung": 3, "got": ["q1", "q2"]}).json()
    assert h["sentence"] == 6 and "sentence 7" in h["say"]


def test_route_fluency_counts_only():
    i = idx("reading", "read")
    r = c.post("/api/academy/fluency", json={"lesson_id": "reading", "step": i, "seconds": 8,
                                              "text": "near the moons south pole some craters are so deep that sunlight never reaches their floors"}).json()
    assert r["correct"] == 16 and r["wcpm"] == 120 and "text" not in r and r["lines"][0] == f"You read 16 of {len(speech.tokens(READ['accept']['passage']['text']))} words."
    r = c.post("/api/academy/fluency", json={"lesson_id": "reading", "step": i, "text": "hello there"}).json()
    assert r["correct"] == 0 and "try again" in r["say"].lower()


def test_public_course_has_no_answer_keys():
    pub = {l["id"]: l for l in content.public()["lessons"]}
    for lid in LESSONS:
        s = str([st for st in pub[lid]["steps"] if st["accept"]["type"] in speech.SPEECH_TYPES])
        assert "'answer'" not in s and "'ok'" not in s and "'traps'" not in s and "'say': [" not in s


def test_sample_lessons_fly_hands_free_by_voice():
    """Every sample lesson plays to its patch with the words a voice-only cadet would say (tools/handsfree_run)."""
    from app.academy import vocab
    for lid in LESSONS:
        les = content.lesson(lid)
        badge = None
        for i, st in enumerate(les["steps"]):
            got, kind = [], st["accept"]["type"]
            for _ in range(8):
                inp = {"text": answer_for(st, vocab=vocab, got=got), **({"got": got} if got else {})}
                if kind == "summary":
                    inp = {"long_text": inp.pop("text"), **inp}
                r = post(lid, i, inp)
                assert r["status"] in ("passed", "progress"), (lid, i, r)
                if r["status"] == "passed":
                    badge = r.get("badge") or badge
                    break
                got = r["got"]
        assert badge and badge["id"] == les["badge"]["id"]


def test_course_check_is_clean_and_the_lessons_follow_the_rules():
    assert content.check() == []
    for lid in LESSONS:
        les = content.lesson(lid)
        assert les["track"] == "explorer" and les["unlock_after"] == "checkride" and len(les["steps"]) <= 5


def test_check_step_catches_authoring_mistakes():
    bad_read = {"type": "read", "passage": {"text": "One. Two."}, "questions": [{"id": "q", "kind": "say", "prompt": "x"}]}
    assert len(speech.check_step({}, bad_read)) >= 3
    bad_vocab = {"type": "vocab", "items": [{"id": "a", "term": "crater"}, {"id": "a", "term": "lava", "kind": "sentence"}]}
    assert speech.check_step({}, bad_vocab)
    bad_sum = {"type": "summary", "source": {"kind": "video", "media": "nope"}, "points": [{"id": "p", "label": "x"}]}
    assert len(speech.check_step({}, bad_sum)) >= 3
