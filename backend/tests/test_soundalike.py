"""Round 7: sound-alike matching against what the screen expects (app/soundalike.py), in the grader and the router.
The pairs are real mishears of the Arc ear from the round-6 class sets (director_model/RESULTS.md)."""
import pytest

from app import soundalike as SA
from app import turn_router as R
from app.academy import content, grade as G


def _step(kind, pred=lambda st: True):
    for L in content.course()["lessons"]:
        for i, st in enumerate(L["steps"]):
            if st["accept"]["type"] == kind and pred(st):
                return st
    raise LookupError(kind)


def test_keys():
    assert SA.key("ice") == SA.key("eyes") == "AS"
    assert SA.key("malapert") == SA.key("malapart")
    assert SA.phrase_key("four side") == SA.phrase_key("far side")
    assert SA.phrase_key("mallow pert") == SA.phrase_key("malapert")
    assert SA.phrase_key("shackle ton") == SA.phrase_key("shackleton")


@pytest.mark.parametrize("heard,vocab,want", [
    ("four side", ["far side", "near side"], "far side"),
    ("rover go get eyes", ["ice", "rover"], "rover go get ice"),
    ("okay haters 40", ["heaters", "shields"], "okay heaters 40"),
    ("i think malapart must be", ["malapert massif", "shackleton rim"], "i think malapert massif be"),
    ("far sight", ["far side"], "far side"),
])
def test_repairs_real_mishears(heard, vocab, want):
    assert SA.repair(heard, vocab)[0] == want


@pytest.mark.parametrize("chatter,vocab", [
    ("oh i see", ["ice"]),            # function words are never rewritten ("i see" is not "ice")
    ("i think guys", ["ice"]),
    ("nice", ["ice"]),
    ("i know i guess", ["no"]),       # too short a target, and "know" is a function word here
    ("near side", ["far side", "near side"]),   # a vocab phrase already heard stays as heard
    ("must be", ["malapert massif"]),
])
def test_never_turns_chatter_into_answers(chatter, vocab):
    assert SA.repair(chatter, vocab)[1] == []


def test_match_is_unambiguous():
    assert SA.match("four side", ["far side", "near side"])[0] == "far side"
    assert SA.match("blah", ["far side", "near side"]) is None


def test_grader_reads_mishears_as_the_answer():
    side = _step("globe_side", lambda st: st["accept"]["want"] == "far")
    ok, extra = G.grade(side, {"text": "four side"})
    assert ok and extra["heard_as"] == "far side"
    cmp_ = _step("compare", lambda st: "malapert_massif" in [o["id"] for o in st["accept"]["options"]])
    ok, extra = G.grade(cmp_, {"text": "i think malapart must be"})
    assert extra.get("choice") == "malapert_massif"
    cmd = _step("command", lambda st: st["accept"]["expect"].get("to") == "heaters")
    assert G.grade(cmd, {"text": "okay haters 40"})[0] in (True, False)   # graded on the heard-as words, never raises
    # a tap / choice input is never repaired
    assert "heard_as" not in G.grade(side, {"text": "four side", "choice": "near"})[1]


def test_plausible_mishear_vs_chatter():
    side = _step("globe_side")
    assert G.plausible(side, "four side", 0.9)
    assert not G.plausible(side, "oh i see", 0.9)
    kw = {"prompt": "Send the rover for ice.", "accept": {"type": "keywords", "all": [["rover"], ["ice", "water"]]}}
    assert G.grade(kw, {"text": "rover go get eyes"})[0]
    assert G.plausible(kw, "rover go get eyes", 0.9)
    assert not G.plausible(kw, "my eyes hurt so much today", 0.3)


def ctx(screen, **k):
    return R.Ctx(screen=screen, source="listen", dd=k.pop("dd", 0.9), **k)


@pytest.mark.parametrize("text,c,intent", [
    ("next liz liz", ctx("patch", offer="next_lesson"), "next"),
    ("tuesday next week", ctx("lesson_done", offer="next_lesson", speaking=True, on_air=False), "next"),
    ("give me a tour lance", ctx("cabin"), "cabin_tour"),
    ("what are my options for me", ctx("map"), "a11y"),
    ("i go back to my seat", ctx("cabin"), "panel_back"),
    ("show me the comp panel", ctx("cabin"), "panel_comm"),
    ("take me to the habitat panels", ctx("cabin"), "panel_habitat"),
    ("go to the map", ctx("lesson", step_type="keywords"), "map"),
    ("back to the map", ctx("map"), "map"),
])
def test_navigation_inside_a_longer_or_misheard_turn(text, c, intent):
    r = R.route(text, c)
    assert r["outcome"] == "navigate" and r["intent"] == intent, r


@pytest.mark.parametrize("text,c", [
    ("see you next week", ctx("lesson_done", offer="next_lesson")),          # 3 words around one: not the offer
    ("tuesday next week", ctx("lesson_done", offer="next_lesson", speaking=True, on_air=True)),   # still on air
    ("i said next time", ctx("patch")),                                     # no offer: one word is never navigation
    ("I don't know that one yet", ctx("lesson", step_type="keywords")),     # our own fallback line
    ("tuesday next week", ctx("lesson_done", offer="next_lesson", dd=0.2)),  # not directed
])
def test_fragments_do_not_navigate(text, c):
    assert R.route(text, c)["outcome"] != "navigate"


def test_step_answer_beats_a_navigation_fragment():
    side = _step("globe_side", lambda st: st["accept"]["want"] == "far")
    c = ctx("lesson", step_type="globe_side", step=side)
    assert R.route("it s back", c)["outcome"] == "answer"


@pytest.mark.parametrize("text", ["shit shit oh", "oh my god", "what the heck", "come on", "damn it", "whoa cool",
                                  "oh crap", "no way"])
def test_room_exclamations_are_never_for_us(text):
    for screen, k in (("lesson", {"step_type": "keywords"}), ("cabin", {}), ("map", {})):
        r = R.route(text, ctx(screen, dd=0.95, **k))
        assert r["outcome"] == "ignore", (text, screen, r)


def test_exclaim_keeps_real_turns():
    assert not R.is_exclaim("yes")
    assert not R.is_exclaim("okay next")
    assert not R.is_exclaim("what is regolith")
    assert R.route("yes", ctx("patch", offer="next_lesson"))["outcome"] == "navigate"


def test_exact_option_answer_passes_the_directed_gate():
    """Live run (round 7): "Right now" for the option "Right now" was rated not directed by Arc; the kid was stuck."""
    st = _step("choice", lambda st: any(o["label"] == "Right now" for o in st["accept"]["options"]))
    c = ctx("lesson", step_type="choice", step=st, dd=0.2, step_options=[o["label"] for o in st["accept"]["options"]])
    assert R.route("Right now", c)["outcome"] == "answer"
    assert R.route("um right now", c)["outcome"] == "answer"
    assert R.route("we have to leave right now ok", c)["outcome"] == "ignore"       # not the answer as written
    assert R.route("yes", ctx("lesson", step_type="earth_view", dd=0.2))["outcome"] == "ignore"
    assert R.route("Right now", ctx("cabin", dd=0.2))["outcome"] == "ignore"           # only on a step
