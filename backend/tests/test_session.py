"""Session Director (docs/SESSION_CONTRACT.md): streams in, belief, policy, several decisions out."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import director, models_client, session as sessions
from app.config import settings
from app.gazetteer import Gazetteer
from app.mission import capcom, registry, sim
from app.moments import MomentIndex

SITE, SEED = "shackleton_rim", 37     # seed 37: storms at 78 h (severity 3) and 184 h


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()


@pytest.fixture
def sess(world):
    clock = Clock()
    m = registry.create(SITE, SEED, level="commander")
    s = sessions.Session("t-1", world[0], world[1], clock=clock, registry=registry)
    run(s.handle({"t": "hello", "mode": "mission", "mission_id": m.id, "role": None, "prefs": {"level": "commander"}}))
    s.clock_obj, s.m = clock, m
    return s


def run(c):
    return asyncio.run(c)


def kinds(ds):
    return [d["t"] for d in ds]


def test_listen_turn_gives_several_decisions_in_order(sess):
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    assert sess.belief["floor"] == "kid"
    run(sess.handle({"t": "words", "text": "move 20% to shields and send the rover for ice"}))
    run(sess.handle({"t": "turn", "state": "end", "text": "move 20% to shields and send the rover for ice"}))
    ds = [d for d in sess.outbox if d["t"] != "floor"]
    assert kinds(ds)[:3] == ["hud", "card", "say"]
    assert all(d["id"] and isinstance(d["priority"], int) for d in ds)
    say = next(d for d in ds if d["t"] == "say")
    assert say["voice"] == "capcom" and "shields" in say["text"].lower()
    assert sess.m.loads["shields"] != sim.DEFAULT_LOADS["shields"] and sess.m.rover["busy"]
    # the same turn arriving again from the client (typed source "voice") counts once
    n = len(sess.outbox)
    run(sess.handle({"t": "typed", "text": "move 20% to shields and send the rover for ice", "source": "voice"}))
    assert len(sess.outbox) == n


def test_risky_command_says_then_asks_confirm_after_it(sess):
    run(sess.handle({"t": "typed", "text": "all power to science"}))
    ds = sess.outbox
    say = next(d for d in ds if d["t"] == "say")
    conf = next(d for d in ds if d["t"] == "ask_confirm")
    assert conf["after"] == say["id"] and conf["yes"] == {"t": "typed", "text": "yes"}


def test_storm_lookahead_alert_rides_with_the_answer(sess):
    sim.advance(sess.m, 12)            # t = 72 h; the storm starts at 78 h
    sess.ev_seen = len(sess.m.events)
    run(sess.handle({"t": "typed", "text": "how is power"}))
    al = [d for d in sess.outbox if d["t"] == "alert"]
    assert al and "next shift" in al[0]["text"] and al[0]["priority"] == director.P_CRITICAL


def _storm_event(sess):
    sim.advance(sess.m, 13)            # into the storm (78 h)
    sess.belief["state"] = None
    assert any(e["kind"] == "solar_storm" for e in sess.m.events[sess.ev_seen:])


def test_storm_event_proactive_only_when_floor_is_none(sess, monkeypatch):
    monkeypatch.setitem(sess.m.storms[0].event, "severity", 2)   # non-critical: must wait for the floor (shared dict)
    _storm_event(sess)
    run(sess.on_playback({"kind": "crew", "state": "start", "id": "x"}))
    run(sess.poll())
    assert not [d for d in sess.outbox if d["t"] == "say"], "never over the crew audio for a non-critical storm"
    run(sess.on_playback({"kind": "crew", "state": "end", "id": "x"}))
    ds = sess.outbox
    assert "alert" in kinds(ds) and "say" in kinds(ds)
    say = next(d for d in ds if d["t"] == "say")
    assert say["voice"] == "capcom" and "storm" in say["text"].lower()
    assert any(d["t"] == "card" and d.get("hint") for d in ds)


def test_critical_storm_never_over_the_kid(sess):
    _storm_event(sess)                               # severity 3: critical
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    run(sess.poll())
    assert "say" not in kinds(sess.outbox)
    run(sess.handle({"t": "ui", "event": "kid_done"}))
    al = next(d for d in sess.outbox if d["t"] == "alert" and d["level"] == "critical")
    assert al["priority"] == director.P_CRITICAL


def test_kid_start_mid_say_cancels_unplayed(sess):
    run(sess.handle({"t": "typed", "text": "what's the status"}))
    said = [d["id"] for d in sess.outbox if d["t"] == "say"]
    run(sess.on_playback({"kind": "guide", "state": "start", "id": said[0]}))
    assert sess.belief["floor"] == "guide"
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    run(sess.handle({"t": "words", "text": "status"}))               # 1 word: not yet a barge-in
    assert "cancel" not in kinds(sess.outbox)
    run(sess.handle({"t": "words", "text": "wait stop the rover"}))   # Arc's read not in yet: the client decides
    assert "cancel" not in kinds(sess.outbox)
    run(sess.handle({"t": "arc", "device_directed": 0.9}))
    run(sess.handle({"t": "words", "text": "wait stop the rover"}))   # still inside the line's first 600 ms
    assert "cancel" not in kinds(sess.outbox)
    sess.clock_obj.t += 1.0
    run(sess.handle({"t": "words", "text": "wait stop the rover"}))
    c = next(d for d in sess.outbox if d["t"] == "cancel")
    assert said[0] in c["ids"] and sess.belief["floor"] == "kid"


def test_server_barge_in_stop_word_and_echo(sess):
    """The session's own check is conservative: a stop word interrupts (past the grace window), our own line spelled
    back ("m s v") never does, room talk Arc rates as not directed never does."""
    sess.pending["s1"] = {"t": "say", "id": "s1", "priority": 3, "text": "Doctors count radiation in mSv. So what is an mSv?"}
    run(sess.on_playback({"kind": "guide", "state": "start", "id": "s1"}))
    sess.clock_obj.t += 1.0
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    run(sess.handle({"t": "words", "text": "so what is an m s v"}))
    run(sess.handle({"t": "arc", "device_directed": 0.95}))
    run(sess.handle({"t": "words", "text": "doctors count radiation in m s v"}))
    assert "cancel" not in kinds(sess.outbox)
    run(sess.handle({"t": "arc", "device_directed": 0.1}))
    run(sess.handle({"t": "words", "text": "can you pass the salt"}))
    assert "cancel" not in kinds(sess.outbox)
    run(sess.handle({"t": "words", "text": "Stop."}))
    assert sess.belief["floor"] == "kid"


def test_echo_of_our_own_line_is_not_a_barge_in(sess):
    sess.pending["s1"] = {"t": "say", "id": "s1", "priority": 3, "text": "Battery is at 80 percent and the Sun is up"}
    run(sess.on_playback({"kind": "guide", "state": "start", "id": "s1"}))
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    run(sess.handle({"t": "words", "text": "battery is at 80 percent"}))
    assert "cancel" not in kinds(sess.outbox)


def test_it_resolves_to_the_most_recent_change(sess):
    run(sess.poll())
    sess.m.loads = sim.reallocate(sess.m.loads, "greenhouse", 30)    # the kid moved greenhouse on the HUD
    run(sess.poll())
    assert sess.belief["referent"]["key"] == "greenhouse"
    assert sess.resolve_referent("give it more") == "give greenhouse more"
    run(sess.handle({"t": "typed", "text": "give it more"}))
    assert sess.m.loads["greenhouse"] > 30
    # telemetry: dose climbing is the latest change → "how is it" asks about dose
    sess.belief["referent"] = None
    s0 = sess.m.state()
    s1 = {**s0, "resources": {**s0["resources"], "dose_msv": s0["resources"]["dose_msv"] + 2}}
    sess._observe_state(s1)
    assert sess.resolve_referent("how is it doing") == "how is dose doing"
    assert sess.resolve_referent("give it more") == "give shields more"
    assert sess.resolve_referent("shields up") == "shields up"   # names a thing itself: untouched


def test_nudges_are_rate_limited(sess):
    clock = sess.clock_obj
    nudge = lambda: [director.decision("card", director.P_NUDGE, title="Coach", body="x", nudge=True)]  # noqa: E731
    sess.last_speech = clock.t - 2
    run(sess.offer(nudge()))
    assert not sess.outbox, "no nudge within 8 s of speech"
    clock.t += 10
    run(sess.offer(nudge()))
    assert len(sess.outbox) == 1
    clock.t += 10
    run(sess.offer(nudge()))
    assert len(sess.outbox) == 1, "at most one nudge per 30 s"
    clock.t += 25
    run(sess.offer(nudge()))
    assert len(sess.outbox) == 2


def test_chatter_gets_no_response(sess):
    run(sess.handle({"t": "arc", "device_directed": 0.1}))
    run(sess.handle({"t": "turn", "state": "end", "text": "did you see the game last night"}))
    assert [d for d in sess.outbox if d["t"] not in ("floor",)] == []


def test_upset_kid_during_alarm_gets_calm_short_lines(sess):
    _storm_event(sess)
    run(sess.poll())
    sess.outbox.clear()
    run(sess.handle({"t": "emotion", "label": "frustrated"}))
    run(sess.handle({"t": "typed", "text": "what's the status"}))
    say = next(d for d in sess.outbox if d["t"] == "say")
    assert say["text"].startswith("Okay, we've got this.") and len(say["text"].split()) <= 30


def test_role_from_hello_gates_commands(world):
    m = registry.create(SITE, SEED, ["power", "comms"])
    s = sessions.Session("t-2", *world, clock=Clock(), registry=registry)
    run(s.handle({"t": "hello", "mode": "mission", "mission_id": m.id, "role": "comms"}))
    run(s.handle({"t": "typed", "text": "shields to 40"}))
    say = next(d for d in s.outbox if d["t"] == "say")
    assert "Power" in say["text"] and m.loads["shields"] == sim.DEFAULT_LOADS["shields"]


def test_end_shift_button_through_the_session(sess):
    run(sess.handle({"t": "ui", "event": "end_shift"}))
    assert kinds(sess.outbox)[:3] == ["hud", "card", "say"] and sess.m.t_h == 6


def test_ask_endpoint_keeps_old_fields_and_adds_decisions():
    from app.main import app
    with TestClient(app) as c:
        r = c.post("/api/ask", json={"text": "show me the far side"}).json()
        assert r["action"] == "view" and r["say"] and "view" in r
        assert [d["t"] for d in r["decisions"]] == ["fly", "card", "say"]


def test_session_socket_round_trip():
    from app.main import app
    with TestClient(app) as c:
        with c.websocket_connect("/ws/session") as ws:
            ws.send_json({"t": "hello", "session": "sock-1", "mode": "cadet"})
            assert ws.receive_json()["t"] == "ready"
            ws.send_json({"t": "typed", "text": "show me the far side"})
            got = [ws.receive_json()["t"] for _ in range(3)]
            assert got == ["fly", "card", "say"]
