"""Round 8 cheap rule fixes (director_model/RESULTS.md, round 8): video controls inside the ear's tails, prep help /
wait / repeats, offer replies with fillers, Houston the city, and our own shown lines heard back."""
import pytest

from app import turn_router as R
from app.mission import nlu


@pytest.mark.parametrize("text,want", [("play the video with lena hargrove", "video_play"),
                                       ("next pause at 12 p m", "video_pause"), ("close the video", "video_stop"),
                                       ("stop it for a sec", "video_pause"), ("wait pause ready", "video_pause"),
                                       ("pause it it s good", "video_pause")])
def test_video_control_inside_a_short_turn(text, want):
    out = R.route(text, R.Ctx(screen="video", source="listen", dd=0.8))
    assert out["outcome"] == "navigate" and out["intent"] == want, out


@pytest.mark.parametrize("text", ["and then the astronauts had to pause before they could play golf on the moon",
                                  "the crew said we will stop here", "next lesson please now"])
def test_video_narration_is_never_a_command(text):
    assert R.route(text, R.Ctx(screen="video", source="listen", dd=0.8))["outcome"] == "ignore"


def test_video_fuzzy_needs_arc_to_say_directed():
    assert R.route("play the video with lena", R.Ctx(screen="video", source="listen", dd=0.1))["outcome"] == "ignore"


@pytest.mark.parametrize("text,want,arg", [("we don t have flour", "prep_help", "missing"),
                                           ("i can t find the flashlight", "prep_help", "missing"),
                                           ("give me a minute", "prep_wait", None), ("give me a minute to leave", "prep_wait", None),
                                           ("i m done i m done i m done", "prep_done", None),
                                           ("let s say it again let s say it again", "prep_help", None)])
def test_prep_help_wait_and_repeats(text, want, arg):
    out = R.route(text, R.Ctx(screen="prep", offer="prep_task", source="listen", dd=0.8))
    assert out["outcome"] == "navigate" and out["intent"] == want and out.get("arg") == arg, out


def test_prep_where_is_still_a_question():
    assert R.route("where s the flour", R.Ctx(screen="prep", offer="prep_task", source="listen", dd=0.8))["outcome"] == "question"


@pytest.mark.parametrize("text,want", [("not now", "decline_offer"), ("okay so", "accept_offer"),
                                       ("not like now", "decline_offer"), ("ready all day ready olly", "accept_offer"),
                                       ("alright okay oh it s good", "accept_offer"),
                                       ("not now but a late one minute", "decline_offer")])
def test_offer_replies_with_fillers_and_tails(text, want):
    out = R.route(text, R.Ctx(screen="map", offer="practice", source="listen", dd=0.8))
    assert out["outcome"] == "navigate" and out["intent"] == want, out


@pytest.mark.parametrize("text", ["okay what is that", "no i don t know"])
def test_offer_lead_is_not_a_question_or_chatter(text):
    out = R.route(text, R.Ctx(screen="map", offer="practice", source="listen", dd=0.8))
    assert out.get("intent") not in ("accept_offer", "decline_offer"), out


def test_houston_the_city_is_never_a_call():
    assert nlu.clause("between dallas and houston")[0] is None
    assert nlu.clause("we flew from dallas to houston")[0] is None
    assert nlu.clause("call houston")[0]["type"] == "call_houston"
    assert nlu.clause("houston we have a problem")[0]["type"] == "call_houston"


def test_shown_line_heard_back_is_echo_but_advice_taken_is_not():
    shown = ["Sample logged. Science +2.", "That's okay. You can skip this one, or use something else you have.",
             "Ready for the next lesson?"]
    cabin = R.Ctx(screen="cabin", source="listen", dd=0.8, shown=shown)
    assert R.route("sample logged science plus two", cabin)["outcome"] == "ignore"
    prep = R.Ctx(screen="prep", offer="prep_task", source="listen", dd=0.8, shown=shown)
    assert R.route("skip this one", prep)["intent"] == "prep_skip"
    offer = R.Ctx(screen="map", offer="next_lesson", source="listen", dd=0.8, shown=shown)
    assert R.route("ready for the next lesson", offer)["intent"] == "accept_offer"


def test_spoken_shown_skips_questions():
    t = [100.0]
    sp = R.Spoken(clock=lambda: t[0]) if "clock" in R.Spoken.__init__.__code__.co_varnames else None
    if sp is None:
        pytest.skip("Spoken takes no clock")
    sp.show("Sample logged. Science +2.")
    sp.show("Ready for the next lesson?")
    t[0] = 150.0
    assert sp.shown() == ["Sample logged. Science +2."]
    t[0] = 100.0 + R.SHOWN_WINDOW_S + 1
    assert sp.shown() == []
