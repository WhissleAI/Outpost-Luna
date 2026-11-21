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


# ---- "what do I do?": the screen's current hint, on every screen (docs/PLAYTEST.md) ------------------------------------
@pytest.mark.parametrize("text", ["help", "what do I do", "what do I do now", "hint", "give me a hint", "I'm stuck",
                                  "I don't know", "what should I do", "I don't get it"])
@pytest.mark.parametrize("screen", ["lesson", "map", "cabin", "brief", "patch"])
def test_help_routes_to_the_hint(text, screen):
    r = route(text, ctx(screen, **SCREENS.get(screen, {})))
    assert r["outcome"] == "navigate" and r.get("intent") == "a11y", (text, screen, r)


@pytest.mark.parametrize("text", ["um I don't know", "uh, hmm, I don't know", "so what do I do", "okay um help",
                                  "umm idk"])
@pytest.mark.parametrize("source", ["typed", "voice"])
def test_a_hesitant_help_still_climbs_the_ladder(text, source):
    """[courses playtest] a novice's "um, I don't know" is the commonest help there is; one leading filler used to be
    stripped, two ("uh, hmm, …") left it an ignored non-answer. The client's a11y.js parseCommand strips the same."""
    r = route(text, ctx("lesson", step_type="keywords", source=source, dd=0.9 if source == "voice" else None))
    assert r["outcome"] == "navigate" and r.get("intent") == "a11y", (text, source, r)


def test_help_never_eats_an_answer():
    for text in ["say again", "help the crew", "orientale then ohm", "I don't know that one yet"]:
        r = route(text, ctx("lesson", step_type="keywords"))
        assert r.get("intent") != "a11y", (text, r)


@pytest.mark.parametrize("screen", ["map", "library", "lesson", "patch"])
def test_zoom_words_zoom_the_moon(screen):
    """Voice zoom (docs/GESTURES.md §Zoom): an eased step on the Moon, on every screen that shows it."""
    c = ctx(screen, **{k: v for k, v in SCREENS[screen].items()})
    for t in ["zoom in", "closer", "get closer", "a bit closer", "zoom in more"]:
        assert route(t, c)["intent"] == "zoom_in", t
    for t in ["zoom out", "farther", "further away", "zoom out a bit", "back out"]:
        assert route(t, c)["intent"] == "zoom_out", t


def test_zoom_words_in_the_cabin_stay_window_views():
    assert route("zoom out", ctx("cabin"))["intent"] == "view_orbit"
    assert route("zoom in", ctx("cabin"))["intent"] == "view_site"
    assert route("closer", ctx("cabin")).get("intent") != "zoom_in"


# ---- [0.4.1] crew talk: room talk never answers a guess or a choice ---------------------------------------------------
PREDICT = {"step_type": "predict", "step_options": ["Yes, Earth is up", "No, never from here"]}
NOWCHOICE = {"offer": "task", "step_options": ["Steer left", "Steer right"]}


@pytest.mark.parametrize("dd", [0.3, 0.55, 0.69])
def test_low_dd_never_answers_a_guess_or_a_choice(dd):
    for scr, extra, said in (("lesson", PREDICT, "yes earth is up"), ("lesson", PREDICT, "no"),
                             ("lesson", SCREENS["lesson"], "go faster"), ("ride", PREDICT, "yes"),
                             ("cabin", NOWCHOICE, "steer left")):
        r = route(said, ctx(scr, dd=dd, recent=[], **extra))
        assert r["outcome"] == "ignore" and r["reason"] == "crew_talk" and r["notice"], (scr, said, r)


def test_crew_talk_gate_only_where_it_belongs():
    # a clearly directed answer still answers; typed and Space-held turns carry no dd and are never gated
    assert out("yes earth is up", ctx("lesson", dd=0.8, recent=[], **PREDICT)) == "answer"
    assert out("yes earth is up", ctx("lesson", source="typed", dd=None, recent=[], **PREDICT)) == "answer"
    assert out("yes earth is up", ctx("lesson", source="ptt", dd=0.2, recent=[], **PREDICT)) == "answer"
    r = route("steer left", ctx("cabin", dd=0.9, recent=[], **NOWCHOICE))
    assert r["outcome"] == "navigate" and r["intent"] == "task_choice"
    assert route("steer left", ctx("cabin", source="typed", dd=None, recent=[], **NOWCHOICE))["intent"] == "task_choice"
    # other step kinds, a readback on the Now card and plain navigation keep their own rules
    assert route("send the rover for ice", ctx("ride", dd=0.6, recent=[], step_type="command"))["reason"] != "crew_talk"
    assert route("bag fourteen", ctx("cabin", dd=0.6, recent=[], offer="task", step_type="sequence",
                                     step_options=["Bag 14"]))["reason"] != "crew_talk"
    assert route("next lesson", ctx("lesson", dd=0.6, recent=[], **PREDICT))["reason"] != "crew_talk"
    # room talk that names no option stays silent as before (no "Crew talk" flash for every sentence)
    assert route("what time is dinner tonight mom", ctx("lesson", dd=0.3, recent=[], **PREDICT))["reason"] != "crew_talk"


def _ride_step(i):
    from app.academy import content
    return content.lesson("checkride")["steps"][i]


def test_crew_talk_offers_an_exact_answer_back_as_a_chip():
    """[0.4.1] A quiet kid's exact answer (Arc under dd_strong) is never dropped silently: the reply carries `pick`, the
    option it names, so the bar shows "Heard “…” · Use it". Chatter that names no option stays a plain ignore."""
    st = _ride_step(0)   # predict: Yes, Earth is up / No, never from here
    c = lambda **k: ctx("ride", dd=0.4, recent=[], step=st, step_type="predict",  # noqa: E731
                        step_options=[o["label"] for o in st["accept"]["options"]], **k)
    for said, oid in (("yes", "yes"), ("um never", "no"), ("Yes, Earth is up", "yes"), ("B", "no"), ("option one", "yes")):
        r = route(said, c())
        assert r["reason"] == "crew_talk" and r["pick"]["choice"] == oid and r["pick"]["heard"], (said, r)
        assert r["pick"]["label"] in ("Yes, Earth is up", "No, never from here")
    for said in ("yes I think so but mom said no", "earth is pretty", "what's for dinner"):
        r = route(said, c())
        assert "pick" not in r, (said, r)
    # the Now card: a short turn the matcher pins to one option
    r = route("left", ctx("cabin", dd=0.5, recent=[], **NOWCHOICE))
    assert r["reason"] == "crew_talk" and r["pick"] == {"label": "Steer left", "choice": None, "heard": "left"}
    # said again, clearly to us: it simply answers (no chip)
    loud = ctx("ride", dd=0.9, recent=[], step=st, step_type="predict", step_options=c().step_options)
    assert route("yes", loud)["outcome"] == "answer"


def test_first_run_course_pick_takes_a_course_name_or_skip():
    """[courses] The first-run pick (academy/ui.js "coursepick"): a course's name or a skip word is the answer; a
    question still works; a name inside a long sentence is not a pick."""
    c = lambda **k: ctx("coursepick", step_options=["The Moon", "Moon", "Archaeology"], **k)  # noqa: E731
    for t in ("the moon", "moon", "Archaeology", "archaeology please", "I want archaeology", "skip", "not now", "pick for me", "the moon course"):
        assert route(t, c())["reason"] == "course", t
    assert route("archaeology", c(source="typed", dd=None))["outcome"] == "answer"
    assert route("we were talking about archaeology at lunch with my friend today", c())["reason"] != "course"
    assert route("what is archaeology?", c())["outcome"] == "question"
    assert route("archaeology", ctx("map"))["reason"] != "course"   # only on the pick screen
