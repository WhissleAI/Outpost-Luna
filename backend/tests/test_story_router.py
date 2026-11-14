"""Story and onboarding words in the hands-free router (docs/STORY.md): "what do I do?" (help), the cabin tour
("show me around", "next", "skip tour"), and that none of them leak into lessons or reach the mission NLU."""
import pytest

from app import session as sessions
from app.turn_router import Ctx, route

LESSONS, SITES = sessions._lessons(), sessions._sites()


def ctx(screen, **k):
    base = dict(screen=screen, source="listen", dd=0.9, lessons=LESSONS, sites=SITES, callsigns=sessions.CALLSIGNS)
    base.update(k)
    return Ctx(**base)


def nav(text, c):
    r = route(text, c)
    return (r.get("intent"), r.get("arg")) if r["outcome"] == "navigate" else (r["outcome"], None)


@pytest.mark.parametrize("text", ["what do I do?", "What do I do now", "help", "I'm lost", "what do I do next", "what should I do",
                                  "what's my job"])
@pytest.mark.parametrize("screen", ["cabin", "brief", "debrief", "map", "patch", "library"])
def test_help_is_a_nav_outside_lessons(text, screen):
    assert nav(text, ctx(screen))[0] == "help"


@pytest.mark.parametrize("screen,extra", [("lesson", {"step_type": "choice", "step_options": ["Near side", "Far side"]}),
                                          ("ride", {"step_type": "command"}), ("lesson_done", {"offer": "next_step"})])
def test_help_never_takes_a_lesson_turn(screen, extra):
    assert nav("what do I do", ctx(screen, **extra))[0] != "help"


def test_what_can_i_do_stays_on_the_a11y_path():
    # the client's a11y "what can I do" (options); in the cabin mission/ui.js answers it with the objective first
    assert nav("what can I do", ctx("cabin")) == ("a11y", None)


def test_tour_words_in_the_cabin():
    tour = ctx("cabin", offer="tour")
    assert nav("next", tour)[0] == "next"
    assert nav("yes", tour)[0] == "accept_offer"
    assert nav("skip tour", tour)[0] == "skip_tour"
    assert nav("skip", tour)[0] == "skip_tour"
    assert nav("show me around", ctx("cabin"))[0] == "cabin_tour"
    assert nav("give me the tour", ctx("cabin"))[0] == "cabin_tour"


def test_tour_words_only_in_the_cabin():
    assert nav("show me around", ctx("map"))[0] != "cabin_tour"
    assert nav("skip tour", ctx("library"))[0] != "skip_tour"
    # a bare "skip" outside the tour is not a tour word (and never a mission order)
    assert nav("skip", ctx("cabin"))[0] != "skip_tour"


def test_next_said_right_after_a_tour_line_is_the_kid():
    beat = "This is your window. Switch views: Orbit, Site, Rover, Earth."
    c = ctx("cabin", offer="tour", recent=[beat], playing=False, on_air=False)
    assert nav("next", c)[0] == "next"


def test_a_tour_line_heard_back_is_an_echo():
    beat = "Radiation: shields, and the storm shelter under its cover."
    c = ctx("cabin", offer="tour", recent=[beat], playing=True, on_air=True, speaking=True)
    assert route(beat, c)["outcome"] == "ignore"


def test_yes_in_the_cabin_without_the_tour_is_still_an_order():
    assert route("yes", ctx("cabin"))["outcome"] == "order"   # a confirm for the sim, as before
