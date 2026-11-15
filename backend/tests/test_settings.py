"""Settings (docs/VOICES.md): GET /api/voices + previews, prefs on the session (voice, rate, expressiveness, filter,
level), the filter levels in the router, and level passed through to the mission sim and the Academy."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import director, models_client, session as sessions, steering, tts, voices
from app import turn_router as tr
from app.config import settings
from app.gazetteer import Gazetteer
from app.main import app
from app.mission import registry
from app.moments import MomentIndex
from app.turn_router import Ctx, route

SITE, SEED = "shackleton_rim", 7
LAST_TTS = "Copy, commander. Shields now get 40 percent of the power."


def run(c):
    return asyncio.run(c)


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


@pytest.fixture
def sess(world):
    m = registry.create(SITE, SEED)
    s = sessions.Session("set-1", world[0], world[1], clock=Clock(), registry=registry)
    run(s.handle({"t": "hello", "mode": "mission", "mission_id": m.id, "role": None}))
    s.m = m
    return s


@pytest.fixture
def os_calls(monkeypatch, tmp_path):
    calls = []

    async def fake(text, style, place):
        calls.append({"text": text, **style})
        return b"RIFFfake", ""

    monkeypatch.setattr(tts, "_os_tts", fake)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "c")
    monkeypatch.setattr(settings, "tts_engine", "os")
    return calls


def other_voice() -> str:
    """An installed voice that is not the guide's (the role's) own."""
    return next(v for v in voices.ids() if v != voices.resolve("guide"))


# ---- the OS voices ----------------------------------------------------------------------------------------------------
def test_voices_api_shape():
    with TestClient(app) as c:
        r = c.get("/api/voices")
    assert r.status_code == 200
    vs = r.json()
    assert isinstance(vs, list) and [v["id"] for v in vs] == [v["id"] for v in voices.curated()]
    assert all(set(v) == {"id", "name", "desc", "preview_url"} for v in vs)
    assert vs[0]["id"] == voices.resolve("guide")                  # best first: the default guide voice
    assert "com.apple.eloquence.en-US.Reed" not in {v["id"] for v in vs}   # low-quality voices stay out of the picker
    assert all(v["preview_url"] == f"/api/voices/preview/{v['id']}.wav" for v in vs)


def test_previews_render_on_demand_through_the_tts_cache(os_calls):
    with TestClient(app) as c:
        v = c.get("/api/voices").json()[1]
        r = c.get(v["preview_url"])
        assert r.status_code == 200 and r.headers["x-tts-voice"] == v["id"]
        assert c.get(v["preview_url"]).headers["x-tts-cache"] == "hit"
        assert c.get("/api/voices/preview/voice_9999.wav").status_code == 404
        assert c.get("/api/voices/preview/../voices.json").status_code == 404
    assert len(os_calls) == 1 and os_calls[0]["tts_voice"] == v["id"] and os_calls[0]["text"] == voices.PREVIEW_LINE


def test_roles_and_unknown_ids():
    assert voices.allowed("capcom") and voices.allowed(other_voice())
    assert not voices.allowed("voice_1085") and not voices.allowed(None) and not voices.allowed("com.apple.voice.Nope")
    assert voices.resolve("capcom") == "com.apple.voice.Aman.premium" and voices.resolve("x") == "x"


# ---- prefs on the session ----------------------------------------------------------------------------------------------
def say(s, voice, text="Hello there, cadet."):
    run(s.emit([director.decision("say", text=text, voice=voice)]))
    return s.outbox[-1]


def test_default_prefs_leave_decisions_unchanged(sess):
    d = say(sess, "guide")
    assert d["style"] == steering.style_for("guide", "Hello there, cadet.")
    assert sess.prefs == sessions.PREF_DEFAULTS and sess.level == "cadet"


def test_prefs_voice_goes_to_the_guide_only(sess):
    v = other_voice()
    run(sess.handle({"type": "prefs", "voice": v, "rate": 1.25, "expressiveness": 0.9}))
    assert say(sess, "guide")["style"]["tts_voice"] == v
    assert say(sess, "capcom")["style"]["tts_voice"] == steering.VOICES["capcom"]     # its role, resolved in /api/tts
    assert say(sess, "houston")["style"]["tts_voice"] == steering.VOICES["houston"]
    run(sess.handle({"type": "prefs", "voice_all": True}))      # partial update: the voice stays
    assert sess.prefs["voice"] == v
    for p in ("guide", "capcom", "houston", "story"):
        assert say(sess, p)["style"]["tts_voice"] == v


def test_prefs_reject_unknown_values(sess):
    run(sess.handle({"type": "prefs", "voice": "voice_9999", "rate": "fast", "expressiveness": 7, "filter": "loose",
                     "level": "admiral"}))
    assert sess.prefs["voice"] is None and sess.prefs["rate"] == 1.0
    assert sess.prefs["expressiveness"] == 1.0 and sess.prefs["filter"] == "normal" and sess.prefs["level"] == "cadet"
    run(sess.handle({"type": "prefs", "rate": 9}))
    assert sess.prefs["rate"] == steering.SPEED_RANGE[1]


def test_tts_request_carries_the_voice_and_rate(sess, os_calls):
    v = other_voice()
    run(sess.handle({"type": "prefs", "voice": v, "rate": 1.25}))
    d = say(sess, "guide", "The rover found ice near the south pole.")
    run(tts.speak(d["text"], d["voice"], d["style"]))
    body = os_calls[-1]
    want, pace, _ = steering.delivery(steering.style_for("guide", d["text"])["controls"], 1.25)
    assert body["tts_voice"] == v
    assert body["pace"] == pace and body["controls"]["rate"] == want["rate"]   # baseline + the rate setting
    # CAPCOM keeps its voice but gets the rate
    d = say(sess, "capcom", "Copy, commander. Shields to 40.")
    run(tts.speak(d["text"], d["voice"], d["style"]))
    assert os_calls[-1]["tts_voice"] == voices.resolve("capcom") and os_calls[-1]["pace"] == pace


def test_explicit_speed_query_wins_over_settings(os_calls):
    st = {**steering.style_for("guide", "Hello."), "speed": 1.5}
    with TestClient(app) as c:
        r = c.get("/api/tts", params={"text": "Hello.", "voice": "guide", "style": json.dumps(st), "speed": 0.75})
    assert r.status_code == 200 and os_calls[-1]["pace"] == steering.speed_steer(0.75)[1]


def test_client_written_line_with_settings_only(os_calls):
    """A client-written line can send only the Settings as its style: the persona default style, with them."""
    v = other_voice()
    with TestClient(app) as c:
        c.get("/api/tts", params={"text": "Badge earned!", "voice": "guide",
                                  "style": json.dumps({"tts_voice": v, "speed": 1.25})})
        c.get("/api/tts", params={"text": "Badge earned!", "voice": "guide",
                                  "style": json.dumps({"tts_voice": "voice_9999"})})
    assert os_calls[0]["tts_voice"] == v and os_calls[0]["tag"] == steering.PERSONA_BASE["guide"]["tag"]
    assert os_calls[1]["tts_voice"] == voices.resolve("guide")           # not installed: the persona's own voice


@pytest.mark.parametrize("e", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_expressiveness_mapping(e):
    st = steering.style_for("guide", "We made it to the Moon!", situation="badge")
    tag, c, perf = steering.with_expressiveness(st["tag"], st["controls"], st["perform"], e)
    k = 2 * (e - 0.5)
    assert c["f0_iqr"] == round(st["controls"]["f0_iqr"] + (0.8 if k > 0 else 1.4) * k, 2)
    assert perf["strength"] == pytest.approx(0.4 + 0.6 * e)
    assert c["rate"] == st["controls"]["rate"] and c["loud"] == st["controls"]["loud"]   # urgency/pace untouched
    assert tag == ("contentment" if e < 0.25 else "pride")


def test_expressiveness_reaches_the_engine_and_never_calms_an_alarm(sess, os_calls):
    run(sess.handle({"type": "prefs", "expressiveness": 0.0}))
    alarm = director.decision("say", text="Storm is here! Into the shelter.", voice="capcom", situation="storm_alert")
    run(sess.emit([alarm]))
    d = sess.outbox[-1]
    run(tts.speak(d["text"], d["voice"], d["style"]))
    body = os_calls[-1]
    base = steering.SITUATIONS["storm_alert"]
    want, _, _ = steering.delivery(base["controls"])          # the 1x delivery baseline, expressiveness aside
    assert body["tag"] == base["tag"] and body["controls"]["rate"] == want["rate"]
    assert body["controls"]["loud"] == want["loud"] and body["controls"]["f0_iqr"] == -1.4
    assert body["perform"]["strength"] == 0.4


def test_prefs_over_the_websocket(world):
    v = other_voice()
    with TestClient(app) as c, c.websocket_connect("/ws/session") as ws:
        ws.send_json({"t": "hello", "session": "ws-set-1", "mode": "cadet"})
        assert ws.receive_json()["t"] == "ready"
        ws.send_json({"type": "prefs", "voice": v, "rate": 0.75, "expressiveness": 0.2, "filter": "strict",
                      "level": "commander", "voice_all": False})
        ack = ws.receive_json()
    assert ack == {"t": "prefs", "applied": {"voice": v, "voice_all": False, "rate": 0.75, "expressiveness": 0.2,
                                             "filter": "strict", "level": "commander", "listen": "handsfree", "volume": 1.0,
                                             "improve": False}}
    s = sessions.get("ws-set-1", create=False)
    assert s.level == "commander" and s.filter_thresholds() == tr.FILTERS["strict"]


def test_prefs_can_ride_on_hello(world):
    s = sessions.Session("set-hello", world[0], world[1], clock=Clock(), registry=registry)
    run(s.handle({"t": "hello", "mode": "cadet", "prefs": {"filter": "relaxed", "level": "commander"}}))
    assert s.prefs["filter"] == "relaxed" and s.level == "commander"


# ---- listen: handsfree | ptt ------------------------------------------------------------------------------------------
def test_ptt_ignores_open_mic_turns_but_not_ptt_or_typed(sess, monkeypatch):
    turns = []

    async def fake_direct(text, read, gaz, index, ctx):
        turns.append(text)
        return {"action": "none", "say": "", "source": "none", "decisions": []}
    monkeypatch.setattr(director, "direct", fake_direct)
    sess.screen = {"screen": "cabin"}
    run(sess.handle({"t": "prefs", "type": "prefs", "listen": "ptt"}))
    assert sess.prefs["listen"] == "ptt"
    # the ear relay: start, words, end -> no floor, no turn
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    assert sess.belief["floor"] != "kid"
    run(sess.handle({"t": "words", "text": "shields to forty please"}))
    run(sess.handle({"t": "turn", "state": "end", "text": "shields to forty please"}))
    run(sess.handle({"t": "typed", "text": "shields to fifty", "source": "voice"}))   # the client's open-mic copy
    assert turns == []
    run(sess.handle({"t": "typed", "text": "shields to sixty", "source": "ptt"}))
    sess.clock.t += 10
    run(sess.handle({"t": "typed", "text": "rover to the crater", "source": "typed"}))
    assert turns == ["shields to sixty", "rover to the crater"]
    # back to hands-free: the ear's turns count again
    run(sess.handle({"t": "prefs", "listen": "handsfree"}))
    sess.clock.t += 10
    run(sess.handle({"t": "turn", "state": "start", "text": ""}))
    run(sess.handle({"t": "turn", "state": "end", "text": "science to ten"}))
    assert turns[-1] == "science to ten"


def test_ptt_open_mic_never_barges_in(sess):
    run(sess.handle({"t": "prefs", "listen": "ptt"}))
    d = say(sess, "capcom", "The storm is coming, get to the shelter now.")
    run(sess.handle({"t": "playback", "kind": "guide", "state": "start", "id": d["id"]}))
    sess.belief["kid"]["open"] = True
    n = len(sess.outbox)
    run(sess.handle({"t": "words", "text": "hey wait tell me about the crater"}))
    assert not [x for x in sess.outbox[n:] if x["t"] in ("cancel", "floor")]


# ---- filter levels -> router thresholds ---------------------------------------------------------------------------
def ctx(level, screen="map", **k):
    lo, hi = tr.thresholds(level)
    base = dict(screen=screen, source="listen", dd=0.9, recent=[LAST_TTS], dd_min=lo, dd_strong=hi,
                lessons=sessions._lessons(), sites=sessions._sites(), callsigns=sessions.CALLSIGNS)
    base.update(k)
    return Ctx(**base)


def test_normal_is_todays_thresholds():
    assert tr.thresholds("normal") == (0.5, 0.7) == (tr.DD_MIN, tr.DD_STRONG)
    assert tr.thresholds(None) == tr.thresholds("bogus") == (0.5, 0.7)
    lo_r, hi_r = tr.FILTERS["relaxed"]
    lo_s, hi_s = tr.FILTERS["strict"]
    assert lo_r < 0.5 < lo_s and hi_r < 0.7 < hi_s


Q = "what is the biggest crater on the moon"


@pytest.mark.parametrize("level,dd,want", [
    ("relaxed", 0.3, "ignore"), ("normal", 0.3, "ignore"), ("strict", 0.3, "ignore"),
    ("relaxed", 0.6, "question"), ("normal", 0.6, "ignore"), ("strict", 0.6, "ignore"),
    ("relaxed", 0.75, "question"), ("normal", 0.75, "question"), ("strict", 0.75, "ignore"),
    ("relaxed", 0.9, "question"), ("normal", 0.9, "question"), ("strict", 0.9, "question"),
])
def test_filter_levels_move_the_device_directed_gate(level, dd, want):
    assert route(Q, ctx(level, dd=dd))["outcome"] == want


@pytest.mark.parametrize("level,want", [("relaxed", "question"), ("normal", "ignore"), ("strict", "ignore")])
def test_filter_levels_move_the_barge_in_bar(level, want):
    """While we speak, a >= 3-word turn needs dd >= dd_strong (0.6: relaxed lets it through, normal does not)."""
    r = route(Q, ctx(level, dd=0.6, speaking=True, playing=True, recent=["Here is a fact about the Moon."]))
    assert r["outcome"] == want
    if want == "ignore":
        assert r["reason"] in ("speaking", "not_directed")


@pytest.mark.parametrize("level", list(tr.FILTERS))
def test_echo_and_filler_rules_are_the_same_at_every_level(level):
    for t in ("Oh.", "um", "Mm-mm.", "Uh-huh.", "hmm"):
        assert route(t, ctx(level, dd=1.0))["reason"] == "filler"
    assert route(LAST_TTS, ctx(level, dd=1.0, speaking=True, playing=True))["reason"] == "echo"
    assert route("shields now get 40 percent", ctx(level, dd=1.0, playing=True))["reason"] == "echo"
    assert route("next", ctx(level, dd=0.1, screen="patch", offer="next_lesson"))["outcome"] == "navigate"


@pytest.mark.parametrize("level,dd,barge", [("relaxed", 0.4, True), ("normal", 0.4, False), ("normal", 0.55, True),
                                            ("strict", 0.55, False), ("strict", 0.7, True)])
def test_session_filter_reaches_barge_in_and_routing(sess, level, dd, barge):
    run(sess.handle({"type": "prefs", "filter": level}))
    sess.belief["kid"]["device_directed"] = dd
    assert sess._is_barge("wait tell me about the crater") is barge
    c = sess.route_ctx("listen")
    assert (c.dd_min, c.dd_strong) == tr.FILTERS[level]


# ---- level: passed through ----------------------------------------------------------------------------------------
def test_level_reaches_the_director_and_the_mission(sess, monkeypatch):
    seen = {}

    async def fake_direct(text, read, gaz, index, ctx):
        seen.update(ctx)
        return {"action": "say", "say": "Copy.", "source": "mission", "decisions": []}
    monkeypatch.setattr(director, "direct", fake_direct)
    assert sess.m.level == "cadet"
    run(sess.handle({"type": "prefs", "level": "commander"}))
    assert sess.m.level == "commander"
    sess.screen = {"screen": "cabin"}
    run(sess.handle({"t": "typed", "text": "shields to 40"}))
    assert seen["level"] == "commander" and seen["mission"]["level"] == "commander"


def test_level_on_mission_start_and_academy_attempt():
    with TestClient(app) as c:
        r = c.post("/api/mission/start", json={"site": SITE, "seed": 3, "level": "commander"})
        assert r.status_code == 200
        assert registry.get(r.json()["id"]).level == "commander"
        assert c.post("/api/mission/start", json={"site": SITE, "level": "admiral"}).status_code == 422
        les = c.get("/api/academy/course").json()["lessons"][0]
        a = c.post("/api/academy/attempt", json={"lesson_id": les["id"], "step": 0, "input": {"text": "hmm"},
                                                 "level": "commander"})
        b = c.post("/api/academy/attempt", json={"lesson_id": les["id"], "step": 0, "input": {"text": "hmm"}})
    assert a.status_code == b.status_code == 200
    assert a.json()["status"] == b.json()["status"]       # no behaviour change from the level (yet)


def test_switching_the_macs_system_voice_renders_new_audio(os_calls):
    """The system voice (`say` with no -v) is one id whatever voice the parent picked: the cache key names that voice."""
    from conftest import FAKE_VOICES
    sysv = {"id": "system", "name": "Your Mac's system voice", "desc": "Nora (Siri)", "quality": "siri",
            "system_voice": "com.apple.siri.natural.Nora", "picker": True}
    voices.set_catalog({**FAKE_VOICES, "roles": {**FAKE_VOICES["roles"], "guide": "system"},
                        "voices": [sysv, *FAKE_VOICES["voices"]]})
    assert voices.cache_tag("system") == "system@com.apple.siri.natural.Nora"
    assert voices.cache_tag("com.apple.voice.Tara.premium") == "com.apple.voice.Tara.premium"
    with TestClient(app) as c:
        a = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "guide"})
        voices.set_catalog({**FAKE_VOICES, "roles": {**FAKE_VOICES["roles"], "guide": "system"},
                            "voices": [{**sysv, "system_voice": "com.apple.siri.natural.Aaron"}, *FAKE_VOICES["voices"]]})
        b = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "guide"})
        c2 = c.get("/api/tts", params={"text": "Hello cadet.", "voice": "guide"})
    assert a.headers["x-tts-voice"] == "system" and a.headers["x-tts-cache"] == "miss"
    assert b.headers["x-tts-cache"] == "miss" and c2.headers["x-tts-cache"] == "hit" and len(os_calls) == 2
