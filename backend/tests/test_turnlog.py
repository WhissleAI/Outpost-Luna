"""The on-device turn log (app/turnlog.py, docs/DIRECTOR_LOOP.md): on by default in the client (prefs.improve), written
only on the client's word, text only, redacted, capped with rotation, and outcome signals joined by turn id. v2 fields
and the playtest: test_turnlog_v2.py."""
import asyncio
import json

import pytest

from app import session as sessions, turnlog
from app.config import settings
from app.gazetteer import Gazetteer
from app.mission import registry
from app.moments import MomentIndex

_W: list = []


def world():
    if not _W:
        _W.extend([Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")])
    return _W


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def lines(d):
    out = []
    for f in turnlog.Store(d).files():
        out += [json.loads(x) for x in f.read_text().splitlines()]
    return out


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    monkeypatch.setenv("TURNLOG_DIR", str(tmp_path))
    return tmp_path


def sess(clock, improve=True, mission=False):
    s = sessions.Session("tl", world()[0], world()[1], clock=clock, registry=registry)
    hello = {"t": "hello", "mode": "mission" if mission else "cadet"}
    if mission:
        hello["mission_id"] = registry.create("shackleton_rim", 3).id
    asyncio.run(s.handle(hello))
    if improve:
        asyncio.run(s.handle({"type": "prefs", "improve": True}))
    return s


def turn(s, clock, text, dd=0.9, dt=3.0):
    clock.t += dt
    asyncio.run(s.handle({"t": "turn", "state": "start", "text": ""}))
    asyncio.run(s.handle({"t": "arc", "device_directed": dd}))
    clock.t += 0.8
    asyncio.run(s.handle({"t": "turn", "state": "end", "text": text}))


def test_a_session_without_the_clients_word_writes_nothing(logdir):
    # the client turns it on (prefs.improve, default true, sent on every connect); headless tools and the generator
    # never send prefs, so the backend's own default stays off
    assert sessions.PREF_DEFAULTS["improve"] is False
    clock = Clock()
    s = sess(clock, improve=False)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    turn(s, clock, "what is a crater")
    assert s.prefs["improve"] is False
    assert lines(logdir) == []


def test_only_an_explicit_true_turns_it_on():
    assert sessions.clean_prefs({"improve": "yes"})["improve"] is False
    assert sessions.clean_prefs({"improve": 1})["improve"] is False
    assert sessions.clean_prefs({"improve": True})["improve"] is True
    assert sessions.clean_prefs({"filter": "strict"}, {**sessions.PREF_DEFAULTS, "improve": True})["improve"] is True


def test_a_turn_is_text_features_only(logdir):
    clock = Clock()
    s = sess(clock)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": "choice",
                          "step_options": ["Never", "Only at full Moon"]}))
    turn(s, clock, "Never!", dd=0.82)
    (r,) = lines(logdir)
    assert r["k"] == "turn" and r["text"] == "never" and r["src"] == "listen"
    assert r["frame"] == {"screen": "lesson", "step_type": "choice", "offer": None,
                          "options": ["never", "only at full moon"], "lesson_id": None, "step": None}
    assert r["router"]["outcome"] == "answer" and r["director"]["final"] == "answer"
    assert r["arc"]["dd"] == 0.82
    assert "tl" not in json.dumps(r).replace('"tl"', "")  # never the session id
    assert set(r) >= {"audio", "mode", "day", "t", "id"} and not any(k in r for k in ("audio_b64", "pcm", "wav"))


@pytest.mark.parametrize("text,want", [
    ("my name is Maya Lopez", "my name is <name>"),
    ("call me Nova", "call me <name>"),
    ("Comet here, more power to shields", "<callsign> here more power to shields"),
    ("i live at 42 oak street", "i live at <address>"),
    ("my phone number is 555 123 4567", "my phone number is <number>"),
    ("set shields to 40", "set shields to 40"),
])
def test_redaction(text, want):
    assert turnlog.redact(text) == want


def test_a_guarded_turn_is_stored_as_private(logdir):
    clock = Clock()
    s = sess(clock)
    asyncio.run(s.handle({"t": "typed", "text": "my name is maya and i live on oak street"}))
    (r,) = [x for x in lines(logdir) if x["k"] == "turn"]
    assert r["text"] == "<private>" and r.get("guard") is True
    assert "maya" not in json.dumps(r) and "oak" not in json.dumps(r)


def test_repeat_after_an_ignore_is_a_signal(logdir):
    clock = Clock()
    s = sess(clock)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    turn(s, clock, "what is a crater", dd=0.2)        # ignored: Arc said not directed
    turn(s, clock, "what is a crater", dd=0.9, dt=2.0)
    ts = [x for x in lines(logdir) if x["k"] == "turn"]
    sig = [x for x in lines(logdir) if x["k"] == "signal"]
    assert ts[0]["router"]["outcome"] == "ignore"
    assert [(x["sig"], x["ref"]) for x in sig] == [("repeat", ts[0]["id"])]


def test_no_right_after_and_a_cancelled_confirm(logdir):
    clock = Clock()
    s = sess(clock, mission=True)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "cabin"}))
    asyncio.run(s.handle({"t": "typed", "text": "turn off life support"}))    # risky: asks to confirm
    clock.t += 2
    asyncio.run(s.handle({"t": "typed", "text": "no"}))
    ts = [x for x in lines(logdir) if x["k"] == "turn"]
    sig = {x["sig"]: x["ref"] for x in lines(logdir) if x["k"] == "signal"}
    assert ts[0]["director"]["confirm"] is True
    assert sig.get("confirm_cancel") == ts[0]["id"]


def test_retap_and_hint_signals(logdir):
    clock = Clock()
    s = sess(clock)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": "keywords",
                          "lesson_id": "comms", "step": 1}))
    turn(s, clock, "heaters forty")
    clock.t += 1
    asyncio.run(s.handle({"t": "ui", "event": "lesson_result", "status": "hint"}))
    clock.t += 1
    asyncio.run(s.handle({"t": "ui", "event": "tap_place", "id": "tycho"}))
    clock.t += 1
    asyncio.run(s.handle({"t": "ui", "event": "tap_place", "id": "tycho"}))
    sig = [x["sig"] for x in lines(logdir) if x["k"] == "signal"]
    assert sig == ["hint", "retap"]


def test_rotation_caps_the_folder(tmp_path):
    st = turnlog.Store(tmp_path, cap=20_000)
    for i in range(400):
        st.append({"k": "turn", "i": i, "pad": "x" * 100})
    sizes = [f.stat().st_size for f in st.files()]
    assert len(sizes) == 2 and sum(sizes) <= 20_000
    assert st.stats()["turns"] > 0
    assert st.clear() == 2 and st.files() == []
