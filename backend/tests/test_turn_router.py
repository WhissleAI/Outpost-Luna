"""The hands-free router (app/turn_router.py): every screen x every outcome, plus the noise that must stay silent."""
import pytest

from app import session as sessions
from app.turn_router import Ctx, clear_question, echo_of, is_filler, route

LESSONS, SITES = sessions._lessons(), sessions._sites()
LAST_TTS = "Copy, commander. Shields now get 40 percent of the power."


def ctx(screen, **k):
    base = dict(screen=screen, source="listen", dd=0.9, lessons=LESSONS, sites=SITES, callsigns=sessions.CALLSIGNS,
                recent=[LAST_TTS])
    base.update(k)
    return Ctx(**base)


def out(text, c):
    return route(text, c)["outcome"]


SCREENS = {   # screen -> extra context
    "map": {"offer": "next_lesson"},
    "callsign": {},
    "lesson": {"step_type": "choice", "step_options": ["I heard you", "Go faster", "Stop"]},
    "lesson_done": {"offer": "next_step"},
    "ride": {"step_type": "command"},
    "patch": {"offer": "next_lesson"},
    "brief": {"offer": "take_command"},
    "cabin": {},
    "debrief": {"offer": "fly_again"},
    "library": {},
}
NOISE = ["Oh.", "um", "Mm-mm.", "hmm", "Uh-huh.", LAST_TTS, "shields now get 40 percent"]
CHAT = ["did you pick up the milk on the way home", "yeah I put it in the fridge next to the juice"]


@pytest.mark.parametrize("screen", SCREENS)
def test_ignore_noise_echo_and_chatter_everywhere(screen):
    for t in NOISE:
        assert out(t, ctx(screen, **SCREENS[screen])) == "ignore", (screen, t)
    for t in CHAT:   # two adults talking: Arc says not device-directed
        assert out(t, ctx(screen, dd=0.2, **SCREENS[screen])) == "ignore", (screen, t)


@pytest.mark.parametrize("screen", SCREENS)
def test_navigation_works_everywhere(screen):
    for t, intent in [("go to the academy", "academy"), ("say that again", "repeat"), ("slower please", "slower"),
                      ("access settings", "settings"), ("go to mission", "go_mission"), ("start lesson 3", "lesson"),
                      ("patch map", "map"), ("library", "library")]:
        r = route(t, ctx(screen, **SCREENS[screen]))
        assert (r["outcome"], r.get("intent")) == ("navigate", intent), (screen, t, r)


@pytest.mark.parametrize("screen", SCREENS)
def test_a_question_works_anywhere(screen):
    c = ctx(screen, **SCREENS[screen])
    q = "what is the biggest crater on the moon"
    assert out(q, c) in ("question", "order" if screen == "cabin" else "question"), screen
    if screen not in ("lesson", "ride", "callsign"):
        assert out(q, c) in ("question",) or screen == "cabin"


def test_per_screen_preferences():
    # lesson step: an utterance is an answer
    assert out("it means I heard you", ctx("lesson", **SCREENS["lesson"])) == "answer"
    assert out("show me the near side", ctx("lesson", step_type="intent")) == "answer"   # intent answers are requests
    assert out("set the shields to forty percent", ctx("lesson", step_type="keywords")) == "answer"
    assert out("more power to the heaters", ctx("ride", step_type="command")) == "answer"
    # patch screen: next / yes
    for t in ("next", "yes", "okay next", "next lesson"):
        r = route(t, ctx("patch", **SCREENS["patch"]))
        assert r["outcome"] == "navigate" and r["intent"] in ("next", "accept_offer"), t
    # lesson done: next
    assert route("next", ctx("lesson_done", **SCREENS["lesson_done"]))["intent"] == "next"
    assert route("yeah", ctx("lesson_done", **SCREENS["lesson_done"]))["intent"] == "accept_offer"
    # map: start, by title
    assert route("start", ctx("map"))["intent"] == "start"
    assert route("lessons from apollo", ctx("map")) == {"outcome": "navigate", "reason": "intent", "intent": "lesson",
                                                         "arg": "history"}
    assert route("lesson three", ctx("map"))["arg"] == LESSONS[2][0]
    # brief: pick a site, take command
    r = route("pick Malapert", ctx("brief"))
    assert (r["intent"], r["arg"]) == ("pick_site", "malapert_massif")
    assert route("take command", ctx("brief"))["intent"] == "take_command"
    assert route("yes", ctx("brief", offer="take_command"))["intent"] == "accept_offer"
    # cabin: orders, views, debrief; "end shift" is an order there
    assert out("send the rover for ice", ctx("cabin")) == "order"
    assert out("shields to 40", ctx("cabin", recent=[], older=[LAST_TTS])) == "order"   # not an echo 5 s later
    assert out("end shift", ctx("cabin")) == "order"
    assert route("zoom out", ctx("cabin"))["intent"] == "view_orbit"
    assert route("show the rover", ctx("cabin"))["intent"] == "view_rover"
    assert route("debrief", ctx("cabin"))["intent"] == "debrief"
    # debrief: fly again
    assert route("fly again", ctx("debrief", offer="fly_again"))["intent"] == "fly_again"
    assert route("yes", ctx("debrief", offer="fly_again"))["intent"] == "accept_offer"
    # library: questions to the brain
    assert out("show me the rovers left on the moon", ctx("library")) == "question"
    # call sign
    assert out("call me Nova", ctx("callsign")) == "answer"


def test_speaking_gate_lets_only_barge_in_worthy_turns_through():
    c = ctx("cabin", speaking=True, dd=0.9)
    assert out("yeah", c) == "ignore" and out("the rover", c) == "ignore"
    assert out("move twenty percent to the heaters", c) == "order"
    assert route("say that again", c)["intent"] == "repeat"
    assert out("move twenty percent to the heaters", ctx("cabin", speaking=True, dd=0.4)) == "ignore"


def test_too_short_and_notice():
    r = route("crater", ctx("map", dd=0.95))
    assert r["outcome"] == "ignore" and r["notice"]
    assert route("crater", ctx("map", dd=None))["notice"] is False


def test_typed_turns_skip_the_noise_gates():
    assert out("um what is regolith", ctx("library", source="typed", dd=None)) == "question"
    assert out("shields now get 40 percent", ctx("cabin", source="typed", dd=None)) == "order"


def test_helpers():
    assert is_filler("Mm-mm.") and is_filler("Oh.") and is_filler("uh, um") and not is_filler("next")
    assert not is_filler("no") and not is_filler("yes")
    assert route("set the shields to forty percent", ctx("lesson", step_type="keywords",
                 recent=["Commander, set the shields to forty percent."]))["outcome"] == "answer"   # a readback
    assert echo_of("the storm is over", ["Okay.", "The storm is over. All clear, Commander!"])
    assert not echo_of("what is the rover made of", ["Charlie Duke drove the rover."])
    assert clear_question("what is the biggest crater") and clear_question("tell me about the far side")
    assert not clear_question("oh") and not clear_question("the cat is on the sofa")
    assert not clear_question("what is the biggest crater", dd=0.3)
