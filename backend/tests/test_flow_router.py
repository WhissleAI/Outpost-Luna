"""Flows (fix/flow-resume, frontend/src/flows.js): with a tour / crew clip / paused mission on screen (Ctx.flow), the
flow's words reach it on every screen; without one they keep their old meanings. Owner bug: "continue" on a stopped
Library tour did nothing (it routed to `start`, which the Library ignores)."""
import pytest

from app import turn_router as R


def nav(text, **k):
    return R.nav_intent(text, R.Ctx(**k))


@pytest.mark.parametrize("text", ["continue", "keep going", "go on", "resume", "carry on", "Okay, continue please",
                                  "resume the tour", "unpause"])
def test_resume_words_resume_a_paused_flow(text):
    assert nav(text, screen="library", flow="paused") == ("resume", None)
    assert nav(text, screen="map", flow="paused") == ("resume", None)


@pytest.mark.parametrize("text", ["stop", "pause", "wait", "hold on", "stop talking", "pause the tour", "hang on"])
def test_pause_words_pause_a_running_flow(text):
    assert nav(text, screen="library", flow="running") == ("pause", None)


def test_step_and_repeat_words_while_a_flow_is_on_screen():
    for flow in ("running", "paused"):
        assert nav("next stop", screen="library", flow=flow) == ("next", None)
        assert nav("previous", screen="library", flow=flow) == ("back", None)
        assert nav("again", screen="library", flow=flow) == ("repeat", None)


def test_without_a_flow_the_old_meanings_hold():
    assert nav("continue", screen="map") == ("start", None)
    assert nav("keep going", screen="map") == ("next", None)
    assert nav("stop", screen="library") is None
    assert nav("again", screen="library") is None


def test_running_flow_keep_going_is_not_a_resume_and_paused_stop_is_not_a_pause():
    assert nav("keep going", screen="library", flow="running") == ("next", None)   # the old meaning
    assert nav("stop", screen="library", flow="paused") is None


def test_cabin_the_clock_and_the_tour():
    # a paused mission clock: "continue" resumes it; "stop" / "go back" stay cabin words
    assert nav("continue", screen="cabin", flow="paused") == ("resume", None)
    assert nav("go back", screen="cabin", flow="paused") == ("panel_back", "seat")
    # the cabin tour (offer "tour"): stop pauses it, back is the beat before
    assert nav("stop", screen="cabin", flow="running", offer="tour") == ("pause", None)
    assert nav("previous", screen="cabin", flow="running", offer="tour") == ("back", None)


def test_route_lets_flow_words_through_the_filler_and_speaking_gates():
    # "stop it" is a room exclamation elsewhere (filler); with a running tour it is the kid's pause
    r = R.route("stop it", R.Ctx(screen="library", flow="running", source="voice", dd=0.9, speaking=True, playing=True))
    assert (r["outcome"], r.get("intent")) == ("navigate", "pause")
    r = R.route("stop it", R.Ctx(screen="library", source="voice", dd=0.9))
    assert r["outcome"] == "ignore"
    r = R.route("continue", R.Ctx(screen="library", flow="paused", source="voice", dd=0.8))
    assert (r["outcome"], r.get("intent")) == ("navigate", "resume")


def test_prep_continue_says_the_task_again():
    r = R.route("keep going", R.Ctx(screen="prep", source="voice", dd=0.8))
    assert (r["outcome"], r.get("intent")) == ("navigate", "prep_help")


def test_session_reads_the_flow_state_from_the_screen_frame():
    import asyncio
    from app import session as sessions
    from app.config import settings
    from app.gazetteer import Gazetteer
    from app.moments import MomentIndex
    s = sessions.Session("t-flow", Gazetteer(settings.data_dir / "places.json"),
                         MomentIndex(settings.data_dir / "index/clips.json"))
    asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "library", "flow": "library_tour",
                          "flow_state": "paused"}))
    assert s.route_ctx("voice").flow == "paused"
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "library"}))
    assert s.route_ctx("voice").flow is None
