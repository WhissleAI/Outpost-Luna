"""Fixes from the owner's rc/2 first-timer play (rc/3):
- a wrong lesson tap names the place it hit when one is within reach ("That's Sea of Rains."), not "Not there";
- "take command" on the picker is always the take-command intent (the selected row flies), never a site pick."""
import pytest

from app import session as sessions
from app.academy import guide
from app.turn_router import Ctx, route

LESSONS, SITES = sessions._lessons(), sessions._sites()


def test_a_tap_just_outside_a_mare_rim_names_it():
    assert guide.tapped_name({"lat": 52, "lon": -15.6}) == "Sea of Rains"     # ~1 degree outside Imbrium's rim
    assert guide.tapped_name({"lat": 33, "lon": -15.6}) == "Sea of Rains"     # inside


def test_a_tap_far_from_any_place_names_nothing():
    assert guide.tapped_name({"lat": 0, "lon": 180}) is None
    assert guide.tapped_name({"lat": -30, "lon": 120}) is None


def test_the_clients_nearest_place_is_named_when_the_rim_test_misses():
    assert guide.tapped_name({"lat": 0, "lon": 180, "place": "imbrium"}) == "Sea of Rains"
    assert guide.tapped_name({"lat": 0, "lon": 180, "place": "no_such_place"}) is None


def test_the_ladder_leads_with_the_place_hit():
    st = {"accept": {"type": "tap", "place": "tranquillitatis"}, "hint": "It's the dark patch right of the middle.",
          "fail": "Not there."}
    out = guide.ladder(st, 0, {"tap": {"lat": 52, "lon": -15.6}}, {})
    assert out["say"].startswith("That's Sea of Rains."), out["say"]


@pytest.mark.parametrize("text", ["take command", "Take command.", "take command please", "I'll take command",
                                  "start the mission", "launch"])
def test_take_command_on_the_picker_is_never_a_site_pick(text):
    c = Ctx(screen="brief", offer="take_command", source="listen", dd=0.9, lessons=LESSONS, sites=SITES,
            callsigns=sessions.CALLSIGNS)
    r = route(text, c)
    assert r["outcome"] == "navigate" and r["intent"] == "take_command", r
