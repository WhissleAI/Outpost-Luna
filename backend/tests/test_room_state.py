"""The automatic room state on the session (frontend/src/room.js, docs/HANDSFREE.md "Room state", SESSION_CONTRACT §7):
a busy / loud room raises the dd gates one level above the kid's filter; room_listen hold / type ignores open-mic turns
until the room is calm; Space and typed turns always count; nothing is a setting and the kid's own choice is never
loosened."""
import pytest

from app import director
from app import turn_router as tr
from tests.test_settings import run, sess, world, offline  # noqa: F401  (fixtures)


@pytest.mark.parametrize("level,room,want", [
    ("relaxed", "calm", "relaxed"), ("relaxed", "busy", "normal"), ("normal", "busy", "strict"),
    ("strict", "busy", "strict"), ("normal", "loud", "strict"), ("normal", None, "normal"), (None, "busy", "strict"),
    ("bogus", "calm", "normal"), ("normal", "bogus", "normal"),
])
def test_room_filter_is_one_level_stricter_never_looser(level, room, want):
    assert tr.room_filter(level, room) == want


def test_prefs_room_raises_the_session_thresholds(sess):
    assert sess.filter_thresholds() == tr.FILTERS["normal"]
    run(sess.handle({"t": "prefs", "type": "prefs", "filter": "normal", "room": "busy", "room_listen": "open"}))
    assert sess.prefs["room"] == "busy" and sess.prefs["filter"] == "normal"   # the kid's choice itself is unchanged
    assert sess.filter_thresholds() == tr.FILTERS["strict"]
    run(sess.handle({"t": "prefs", "room": "calm"}))
    assert sess.filter_thresholds() == tr.FILTERS["normal"]


def test_bad_room_values_are_ignored(sess):
    run(sess.handle({"t": "prefs", "room": "party", "room_listen": "shout"}))
    assert sess.prefs["room"] == "calm" and sess.prefs["room_listen"] == "open"
    assert not sess.ptt_only()


@pytest.mark.parametrize("rl", ["hold", "type"])
def test_room_hold_ignores_open_mic_but_not_space_or_typed(sess, monkeypatch, rl):
    turns = []

    async def fake_direct(text, read, gaz, index, ctx):
        turns.append(text)
        return {"action": "none", "say": "", "source": "none", "decisions": []}
    monkeypatch.setattr(director, "direct", fake_direct)
    sess.screen = {"screen": "cabin"}
    run(sess.handle({"t": "prefs", "room": "busy", "room_listen": rl}))
    assert sess.ptt_only()
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    run(sess.handle({"t": "turn", "state": "end", "text": "shields to forty please"}))
    run(sess.handle({"t": "typed", "text": "shields to fifty", "source": "voice"}))
    assert turns == []
    run(sess.handle({"t": "typed", "text": "shields to sixty", "source": "ptt"}))
    sess.clock.t += 10
    run(sess.handle({"t": "typed", "text": "rover to the crater", "source": "typed"}))
    assert turns == ["shields to sixty", "rover to the crater"]
    # calm again: open voice
    run(sess.handle({"t": "prefs", "room": "calm", "room_listen": "open"}))
    assert not sess.ptt_only()
    sess.clock.t += 10
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    run(sess.handle({"t": "turn", "state": "end", "text": "science to ten"}))
    assert turns[-1] == "science to ten"


def test_kids_ptt_setting_stays_when_the_room_calms(sess):
    run(sess.handle({"t": "prefs", "listen": "ptt", "room": "calm", "room_listen": "open"}))
    assert sess.ptt_only()
