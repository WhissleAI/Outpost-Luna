"""The brain's weekly counts and care flags (D1-D4: app/brain_counts.py, app/care_flags.py, docs/BRAIN.md §7).

Counts by kind and channel, never words; per cadet profile; independent of the turn log; 12 weeks; care flags kept
until a grown-up marks them seen, 30 days at most; Reset erases both.
"""
import asyncio
import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

from app import brain_counts as BC, care_flags as CF, session as sessions, turnlog
from app.config import settings
from app.gazetteer import Gazetteer
from app.moments import MomentIndex

TODAY = dt.date(2026, 11, 20)


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


def make(world, profile="p1", improve=False, listen="handsfree"):
    s = sessions.Session("bc-1", world[0], world[1])
    asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "library"}))
    asyncio.run(s.handle({"t": "prefs", "profile": profile, "improve": improve, "listen": listen}))
    return s


def say(s, text, source="typed", dd=None):
    m = {"t": "typed", "text": text, "source": source}
    if dd is not None:
        m["dd"] = dd
    asyncio.run(s.handle(m))


def files_text():
    d = BC.brain_dir()
    return "".join(p.read_text() for p in d.glob("*.json")) if d.exists() else ""


# ---------- the store ----------
def test_channel_bands():
    assert BC.channel("typed", None, 0.7) == "typed"
    assert BC.channel("ptt", 0.1, 0.7) == "ptt"
    assert BC.channel("listen", 0.9, 0.7) == "directed" and BC.channel("voice", 0.7, 0.7) == "directed"
    assert BC.channel("listen", 0.6, 0.7) == "room" and BC.channel("voice", None, 0.7) == "room"


def test_record_and_summary_per_cadet():
    BC.record_safety("p1", "profanity", "typed", TODAY)
    BC.record_safety("p1", "profanity", "room", TODAY)
    BC.record_safety("p2", "mask", "ptt", TODAY)
    BC.record_turn("p1", "listen", "answer", "busy", TODAY)
    BC.record_turn("p1", "typed", "ignore", "calm", TODAY)
    s1 = BC.summary("p1", TODAY - dt.timedelta(days=29), TODAY)
    assert s1["safety"]["profanity"] == {"typed": 1, "ptt": 0, "directed": 0, "room": 1}
    assert s1["safety"]["mask"] == {"typed": 0, "ptt": 0, "directed": 0, "room": 0}
    assert s1["talk"]["turns"] == 2 and s1["talk"]["voice"] == 1 and s1["talk"]["passed_by"] == 1
    assert s1["talk"]["room"]["busy"] == 1 and s1["talk"]["days"] == 1
    assert len(s1["weeks"]) == 4 and s1["weeks"][-1]["profanity"] == 2 and s1["weeks"][-1]["week"] == "2026-W47"
    assert BC.summary("p2", TODAY - dt.timedelta(days=29), TODAY)["safety"]["mask"]["ptt"] == 1


def test_unknown_kinds_and_channels_are_not_counted():
    assert not BC.record_safety("p1", "anger", "typed", TODAY)
    assert not BC.record_safety("p1", "profanity", "classroom", TODAY)
    assert files_text() == ""


def test_twelve_weeks_then_gone():
    old = TODAY - dt.timedelta(weeks=13)
    BC.record_safety("p1", "profanity", "typed", old)
    BC.record_safety("p1", "profanity", "typed", TODAY - dt.timedelta(weeks=11))
    BC.record_safety("p1", "profanity", "typed", TODAY)
    weeks = BC.load(TODAY)["weeks"]
    assert BC.week_of(old) not in weeks and BC.week_of(TODAY) in weeks
    assert BC.week_of(TODAY - dt.timedelta(weeks=11)) in weeks and len(weeks) == 2


def test_clean_keeps_only_numbers_weeks_profiles_and_enums():
    raw = {"weeks": {"2026-W47": {"p1": {"talk": {"turns": "7", "text": "my name is alex", "days": ["2026-11-20", "nope"]},
                                         "safety": {"profanity": {"typed": 2, "word": "shit"}, "secret": {"typed": 1}}},
                                  "Nova": {"talk": {"turns": 1}}},
                     "last week": {"p1": {}}}}
    c = BC.clean(raw, TODAY)
    txt = json.dumps(c)
    assert "alex" not in txt and "shit" not in txt and "Nova" not in txt and "secret" not in txt and "nope" not in txt
    assert c["weeks"]["2026-W47"]["p1"]["talk"]["turns"] == 7
    assert c["weeks"]["2026-W47"]["p1"]["safety"]["profanity"]["typed"] == 2


def test_file_is_private_and_atomic():
    BC.record_safety("p1", "pii", "typed", TODAY)
    p = BC.brain_dir() / "counts.json"
    assert p.exists() and (p.stat().st_mode & 0o777) == 0o600
    assert not list(BC.brain_dir().glob(".counts-*"))


def test_clear_one_cadet_or_all():
    BC.record_safety("p1", "pii", "typed", TODAY)
    BC.record_safety("p2", "pii", "typed", TODAY)
    BC.clear("p1")
    w = BC.load(TODAY)["weeks"][BC.week_of(TODAY)]
    assert "p1" not in w and "p2" in w
    BC.clear()
    assert BC.load(TODAY)["weeks"] == {}


# ---------- care flags ----------
def test_care_flags_dedupe_ack_and_expire():
    a = CF.add("p1", "self_harm", TODAY)
    b = CF.add("p1", "self_harm", TODAY)
    assert a["id"] == b["id"] and b["n"] == 2
    CF.add("p2", "grooming", TODAY)
    CF.add("p1", "grooming", TODAY - dt.timedelta(days=31))   # older than 30 days: dropped on read
    assert {f["kind"] for f in CF.open_flags("p1", TODAY)} == {"self_harm"}
    assert CF.ack(flag_id=a["id"]) == 1 and CF.open_flags("p1", TODAY) == []
    assert CF.ack(profile="p2") == 1 and CF.open_flags(None, TODAY) == []
    assert CF.add("p1", "a feeling", TODAY) is None


def test_kind_of_tags():
    assert CF.kind_of(["safety.crisis.self_harm"]) == "self_harm"
    assert CF.kind_of(["safety.child.grooming_cue", "safety.crisis.self_harm"]) == "grooming"
    assert CF.kind_of(["safety.profanity"]) is None


# ---------- the session writes them (D1-D4), with the turn log OFF (D2) ----------
def test_session_counts_profanity_by_channel_without_the_turn_log(world):
    s = make(world, improve=False)
    say(s, "this is shit")                                  # typed
    say(s, "shit", source="ptt")                            # push to talk
    say(s, "oh shit what was that", source="voice", dd=0.95)   # open mic, said to the app
    say(s, "shit shit oh", source="voice", dd=0.2)          # open mic, the room
    c = BC.summary("p1", dt.date.today() - dt.timedelta(days=6))
    assert c["safety"]["profanity"] == {"typed": 1, "ptt": 1, "directed": 1, "room": 1}
    txt = files_text().lower()
    assert "shit" not in txt and "what was that" not in txt


def test_session_counts_the_privacy_guard_as_pii(world):
    s = make(world)
    say(s, "my name is alex and i live on maple street")
    c = BC.summary("p1", dt.date.today())
    assert sum(c["safety"]["pii"].values()) == 1 and c["safety"]["pii"]["typed"] == 1
    assert "alex" not in files_text().lower() and "maple" not in files_text().lower()


def test_session_care_turn_persists_a_flag_for_the_cadet(world):
    s = make(world, profile="p3")
    say(s, "i want to kill myself")
    fl = CF.open_flags("p3")
    assert len(fl) == 1 and fl[0]["kind"] == "self_harm" and set(fl[0]) == {"id", "kind", "day", "profile", "n"}
    assert s.flags[-1]["profile"] == "p3"
    assert sum(BC.summary("p3", dt.date.today())["safety"]["care"].values()) == 1
    assert "kill" not in files_text()


def test_profile_switch_mid_session_moves_the_counts(world):
    """[D3] crew rotation: the client re-sends prefs with the cadet on turn; counts land on that cadet."""
    s = make(world, profile="p1")
    say(s, "this is crap")
    asyncio.run(s.handle({"t": "prefs", "profile": "p2"}))
    say(s, "crap", source="ptt")
    say(s, "where is tycho")
    p1 = BC.summary("p1", dt.date.today())
    p2 = BC.summary("p2", dt.date.today())
    assert p1["safety"]["profanity"]["typed"] == 1 and sum(p1["safety"]["profanity"].values()) == 1
    assert p2["safety"]["profanity"]["ptt"] == 1 and p2["talk"]["turns"] == 2


def test_tool_sessions_without_a_profile_write_nothing(world):
    s = sessions.Session("bc-tool", world[0], world[1])
    asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
    say(s, "this is shit")
    assert files_text() == ""


def test_turn_log_lines_carry_the_profile(world, tmp_path, monkeypatch):
    st = turnlog.Store(tmp_path)
    monkeypatch.setattr(turnlog, "STORE", st)
    s = make(world, profile="p2", improve=True)
    s.tlog.store = st
    say(s, "where is tycho")
    recs = [json.loads(x) for x in st.path.read_text().splitlines() if '"k":"turn"' in x]
    assert recs and recs[-1]["profile"] == "p2"


# ---------- the endpoints ----------
def test_summary_reads_the_store_for_this_cadet(world):
    from app.main import app
    s = make(world, profile="p2")
    say(s, "this is crap")
    say(s, "my name is alex")
    say(s, "i want to kill myself")
    c = TestClient(app)
    body = c.get("/api/brain/summary?profile=p2").json()
    assert body["scope"] == "cadet" and body["safety"]["filtered"] == 1 and body["safety"]["privacy"] == 1
    assert body["safety"]["by_kind"]["profanity"]["typed"] == 1 and body["safety"]["care"] == 1
    assert body["safety"]["care_flags"][0]["kind"] == "self_harm"
    raw = json.dumps(body).lower()
    for w in ("crap", "alex", "kill", "myself"):
        assert w not in raw
    other = c.get("/api/brain/summary?profile=p1").json()
    assert other["safety"]["care"] == 0 and other["safety"]["filtered"] == 0


def test_flag_endpoints_need_the_token_and_ack(world, monkeypatch):
    from app.main import app
    f = CF.add("p1", "grooming")
    monkeypatch.setenv("LUNA_TOKEN", "t" * 43)
    c = TestClient(app)
    H = {"X-Luna-Token": "t" * 43}
    assert c.post(f"/api/safety/flags/{f['id']}/ack").status_code == 401
    assert c.get("/api/safety/flags", headers=H).json()["flags"][0]["id"] == f["id"]
    assert c.post(f"/api/safety/flags/{f['id']}/ack", headers=H).json() == {"acked": 1}
    assert c.get("/api/safety/flags", headers=H).json()["flags"] == []
    CF.add("p2", "self_harm")
    assert c.post("/api/safety/flags/ack?profile=p2", headers=H).json() == {"acked": 1}
    assert c.post("/api/safety/flags/zz/ack", headers=H).status_code == 400
    assert c.delete("/api/brain/counts?profile=p1").status_code == 401
    assert c.delete("/api/brain/counts?profile=p1", headers=H).status_code == 200


def test_class_read_lists_every_cadet_counts_only():
    from app.main import app
    BC.record_safety("p1", "profanity", "typed")
    BC.record_turn("p2", "typed", "answer", "calm")
    body = TestClient(app).get("/api/brain/class?profiles=p1,p2,p9,bad").json()
    assert set(body["cadets"]) == {"p1", "p2", "p9"}
    assert body["cadets"]["p1"]["safety"]["filtered"] == 1 and body["cadets"]["p2"]["talk"]["turns"] == 1
    assert body["cadets"]["p9"]["talk"] is None


def test_reset_start_erases_counts_and_flags(monkeypatch):
    from app import reset as R
    BC.record_safety("p1", "profanity", "typed")
    CF.add("p1", "self_harm")
    assert BC.brain_dir() in R.targets("start")["start"]
    R.reset("start")
    assert BC.load()["weeks"] == {} and CF.open_flags() == []
