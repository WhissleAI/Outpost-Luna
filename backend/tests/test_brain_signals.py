"""feat/brain-signals (docs/BRAIN.md "Signals → Brain"): the safety ledger (retention, reset, auth, no words), the turn
log's profile / course / day on every line and its 30-day retention, the summary's date window and profile / course
filters, the guard category enum, behaviour counts that skip echoes, and the academy's misconception kind."""
import asyncio
import datetime as dt
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import brain, reset as R, safety, safety_ledger, session as sessions, turnlog
from app.academy import routes as academy_routes
from app.config import settings
from app.gazetteer import Gazetteer
from app.moments import MomentIndex

TODAY = dt.date.today()
D = lambda n: (TODAY - dt.timedelta(days=n)).isoformat()  # noqa: E731


# ---------- the safety ledger ----------
def test_ledger_counts_per_profile_day_kind_and_never_holds_words(tmp_path):
    lg = safety_ledger.Ledger(tmp_path)
    assert lg.record("p2", "language", "wordlist", "school", "moon")
    assert lg.record("p2", "language", "wordlist", "school", "moon")
    assert lg.record("p1", "care", "phrase", "map", "archaeology")
    assert not lg.record("p1", "aggressive", "tagger")          # no trait labels: unknown kinds are refused
    assert lg.record("my name is alex", "unkind", "tagger", "I said shit", "Alex's course")
    es = lg.entries()
    assert {(e["p"], e["kind"], e["n"]) for e in es} == {("p2", "language", 2), ("p1", "care", 1), ("p1", "unkind", 1)}
    raw = (tmp_path / "ledger.json").read_text().lower()
    for w in ("alex", "shit", "said", "name"):
        assert w not in raw, w
    assert lg.counts("p2") == {"language": 2, "unkind": 0, "care": 0, "personal_info": 0, "unsafe_request": 0}


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes")
def test_ledger_file_is_private(tmp_path):
    lg = safety_ledger.Ledger(tmp_path)
    lg.record("p1", "care", "tagger")
    assert (tmp_path / "ledger.json").stat().st_mode & 0o777 == 0o600


def test_ledger_retention_care_30_days_others_60(tmp_path):
    lg = safety_ledger.Ledger(tmp_path)
    lg.record("p1", "care", "tagger", today=D(29))
    lg.record("p1", "care", "tagger", today=D(30))
    lg.record("p1", "language", "wordlist", today=D(59))
    lg.record("p1", "language", "wordlist", today=D(60))
    kept = {(e["kind"], e["day"]) for e in lg.entries()}
    assert kept == {("care", D(29)), ("language", D(59))}
    # the expired entries are gone from the file too, not just hidden
    raw = (tmp_path / "ledger.json").read_text()
    assert D(30) not in raw and D(60) not in raw


def test_care_banner_rows_and_dismissal_keep_the_entry(tmp_path):
    lg = safety_ledger.Ledger(tmp_path)
    lg.record("p1", "care", "phrase", "map", "moon", today=D(2))
    lg.record("p1", "care", "tagger", "school", "archaeology", today=D(2))
    lg.record("p3", "care", "tagger", today=D(1))
    rows = lg.care()
    assert [(r["profile"], r["day"], r["n"], r["dismissed"]) for r in rows] == [("p3", D(1), 1, False), ("p1", D(2), 2, False)]
    assert sorted(rows[1]["courses"]) == ["archaeology", "moon"]
    assert lg.dismiss_care("p1", D(2)) == 2
    assert [r["dismissed"] for r in lg.care("p1")] == [True]
    assert lg.entries("p1", ("care",)), "dismissing hides the banner, the entry stays until its 30 days are up"
    lg.record("p1", "care", "tagger", "map", "moon", today=D(2))   # a new cue the same day shows the banner again
    assert lg.care("p1")[0]["dismissed"] is False


def test_kinds_of_maps_the_safety_result_to_ledger_kinds():
    k = safety_ledger.kinds_of
    assert k(safety.classify("i want to kill myself")) == [("care", "phrase")]
    assert k(safety.classify("shit")) == [("language", "wordlist")]
    tox = [{"tag": "safety.toxicity.insult_harassment", "p": 0.9, "thr": 0.6, "on": True}]
    assert k(safety.classify("you are so dumb", tox)) == [("unkind", "tagger")]
    pii = [{"tag": "safety.pii.leak", "p": 0.99, "thr": 0.6, "on": True}]
    assert k(safety.classify("my address is", pii)) == [("personal_info", "tagger")]
    care = [{"tag": "safety.crisis.self_harm", "p": 0.9, "thr": 0.5, "on": True}]
    assert k(safety.classify("i feel bad", care)) == [("care", "tagger")]
    assert k(safety.classify("where is tycho")) == []


def _client(token=None, monkeypatch=None):
    from app.main import app
    if token:
        monkeypatch.setenv("LUNA_TOKEN", token)
    return TestClient(app)


def test_flags_api_needs_the_token_and_reads_the_ledger(monkeypatch):
    safety_ledger.LEDGER.record("p2", "care", "phrase", "map", "moon")
    safety_ledger.LEDGER.record("p2", "language", "wordlist", "map", "moon")
    c = _client("t" * 43, monkeypatch)
    assert c.get("/api/safety/flags").status_code == 401
    assert c.post("/api/safety/flags/dismiss", json={"profile": "p2", "day": TODAY.isoformat()}).status_code in (401, 403)
    h = {"X-Luna-Token": "t" * 43}
    body = c.get("/api/safety/flags", headers=h).json()
    assert [(f["kind"], f["profile"], f["day"]) for f in body["flags"]] == [("care", "p2", TODAY.isoformat())]
    assert body["line"] == safety.CARE_LINE and body["retain_days"] == 30 and body["words"] is False
    assert c.get("/api/safety/flags?profile=p1", headers=h).json()["flags"] == []
    assert c.post("/api/safety/flags/dismiss", headers=h, json={"profile": "p2", "day": TODAY.isoformat()}).json()["dismissed"] == 1
    assert c.get("/api/safety/flags", headers=h).json()["flags"][0]["dismissed"] is True


def test_reset_clears_the_ledger_and_it_is_never_in_a_playtest_export(tmp_path, monkeypatch):
    monkeypatch.setenv("TURNLOG_DIR", str(tmp_path / "turnlog"))
    st = turnlog.Store(tmp_path / "turnlog")
    monkeypatch.setattr(turnlog, "STORE", st)
    st.append({"k": "turn", "id": "a-1", "day": TODAY.isoformat(), "text": "hi"})
    safety_ledger.LEDGER.record("p1", "care", "phrase")
    from app import playtest
    data, _ = playtest.export_zip("test")
    import io
    import zipfile
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert not [n for n in names if "ledger" in n or "safety" in n], names
    assert safety_ledger.ledger_dir() in R.targets("start")["start"]
    R.reset("start")
    assert safety_ledger.LEDGER.entries() == []
    assert not safety_ledger.LEDGER.path.exists()


# ---------- the session's safety path writes the ledger (care included), skipping echoes / not-meant-for-us ----------
@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture()
def no_tagger(monkeypatch):
    async def read(text, command_context=False):
        return []
    monkeypatch.setattr(safety, "tagger_read", read)


def _sess(world, profile="p3", screen="map"):
    s = sessions.Session("bs-1", world[0], world[1])
    asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
    asyncio.run(s.handle({"type": "prefs", "profile": profile, "improve": True}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": screen}))
    return s


def test_session_care_goes_to_the_ledger_with_profile_and_course(world, no_tagger):
    s = _sess(world, "p3")
    asyncio.run(s.handle({"t": "typed", "text": "i want to kill myself", "source": "typed"}))
    es = safety_ledger.LEDGER.entries("p3")
    assert [(e["kind"], e["src"], e["course"], e["screen"]) for e in es] == [("care", "phrase", "moon", "map")]
    assert "kill" not in safety_ledger.LEDGER.path.read_text()


def test_session_language_count_skips_turns_not_meant_for_the_app(world, no_tagger):
    s = _sess(world, "p4")
    asyncio.run(s.handle({"t": "typed", "text": "shit that is cool", "source": "voice", "dd": 0.1}))
    assert safety_ledger.LEDGER.entries("p4") == []          # talking to someone else: not a behaviour count
    asyncio.run(s.handle({"t": "typed", "text": "shit where is tycho", "source": "typed"}))
    assert [(e["kind"], e["src"]) for e in safety_ledger.LEDGER.entries("p4")] == [("language", "wordlist")]


# ---------- the turn log: profile, course and day on every line; guard enum; 30-day retention ----------
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _lines(d):
    out = []
    for f in turnlog.Store(d).files():
        out += [json.loads(x) for x in f.read_text().splitlines()]
    return out


def test_turns_and_signals_carry_profile_course_and_day(world, tmp_path, monkeypatch, no_tagger):
    monkeypatch.setenv("TURNLOG_DIR", str(tmp_path))
    clock = Clock()
    s = sessions.Session("bs-2", world[0], world[1], clock=clock)
    asyncio.run(s.handle({"t": "hello", "mode": "cadet"}))
    asyncio.run(s.handle({"type": "prefs", "profile": "p5", "improve": True}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    for _ in range(2):
        clock.t += 2
        asyncio.run(s.handle({"t": "typed", "text": "where is tycho crater", "source": "typed"}))
    ls = _lines(tmp_path)
    turns = [x for x in ls if x["k"] == "turn"]
    sigs = [x for x in ls if x["k"] == "signal"]
    assert turns and all(t["profile"] == "p5" and t["course"] == "moon" for t in turns)
    assert sigs and all(g["day"] == TODAY.isoformat() and g["profile"] == "p5" and g["course"] == "moon" for g in sigs)


def test_guard_category_is_logged_never_the_words(tmp_path, monkeypatch):
    st = turnlog.Store(tmp_path)
    s = type("S", (), {"prefs": {"improve": True, "profile": "p2"}, "clock": lambda self: 1.0})()
    lg = turnlog.SessionLog(s, st)
    for kind in ("language", True):
        lg.finish({"k": "turn", "id": f"x-{kind}", "text": "shit tycho", "router": {"outcome": "ignore"}}, None, guard=kind)
    a, b = _lines(tmp_path)
    assert a["guard"] is True and a["guard_kind"] == "language" and a["text"] == "<private>"
    assert b["guard"] is True and "guard_kind" not in b
    assert turnlog.guard_kind(safety.classify("shit")) == "language"
    assert turnlog.guard_kind({"pii": True}) == "pii"
    tox = [{"tag": "safety.toxicity.insult_harassment", "p": 0.9, "thr": 0.6, "on": True}]
    assert turnlog.guard_kind(safety.classify("you are so dumb", tox)) == "unkind"


def test_turn_log_keeps_30_days_not_just_5_mb(tmp_path):
    st = turnlog.Store(tmp_path)
    st._pruned = TODAY.isoformat()     # write the old lines first without pruning
    for n in (0, 29, 30, 45):
        st.append({"k": "turn", "id": f"t{n}", "day": D(n)})
        st.append({"k": "signal", "ref": f"t{n}", "sig": "repeat", "day": D(n)})
    clip_dir = tmp_path / "playtest"
    clip_dir.mkdir()
    old, new = clip_dir / "old.wav", clip_dir / "new.wav"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    t = time.mktime((TODAY - dt.timedelta(days=40)).timetuple())   # portable (no %s on Windows)
    os.utime(old, (int(t), int(t)))
    removed = st.prune(force=True)
    assert removed == 5
    assert sorted(x["day"] for x in _lines(tmp_path) if x["k"] == "turn") == [D(29), D(0)]
    assert not old.exists() and new.exists()
    assert st.stats()["retain_days"] == 30


# ---------- the summary: date window, profile / course filters, behaviour skips echoes ----------
def _t(i, day=None, profile="p1", course="moon", **kw):
    r = {"k": "turn", "id": f"s-{i}", "day": day or TODAY.isoformat(), "src": "listen", "router": {"outcome": "answer"},
         "profile": profile, "course": course, "arc": {"dd": 0.9}}
    r.update(kw)
    return r


def _sig(ref, sig="repeat", day=None, profile="p1", course="moon"):
    r = {"k": "signal", "ref": ref, "sig": sig, "profile": profile, "course": course}
    if day is not False:
        r["day"] = day or TODAY.isoformat()
    return r


def test_signals_are_counted_inside_the_date_window_only():
    since = D(29)
    lines = [_t(1), _sig("s-1"), _t(2, day=D(40)), _sig("s-2", day=D(40)), _sig("s-x", day=False)]
    c = brain.talk_counts(lines, since, "p1")
    assert c["turns"] == 1 and c["signals"]["repeat"] == 1 and c["retried"] == 1


def test_summary_filters_by_profile_and_course():
    lines = [_t(1), _t(2, profile="p2"), _t(3, course="archaeology"), _sig("s-1", "negate"), _sig("s-2", profile="p2"),
             {k: v for k, v in _t(4).items() if k != "profile"}]
    assert brain.talk_counts(lines, None, "p1")["turns"] == 2
    c = brain.talk_counts(lines, None, "p1", "moon")
    assert c["turns"] == 1 and c["signals"]["negate"] == 1 and c["signals"]["repeat"] == 0
    assert brain.talk_counts(lines, None, "p2")["turns"] == 1
    assert brain.talk_counts(lines)["turns"] == 4


def test_behaviour_counts_skip_echo_and_low_device_directed_turns():
    lines = [_t(1, guard=True, guard_kind="language"),
             _t(2, guard=True, guard_kind="language", router={"outcome": "ignore", "reason": "echo"}),
             _t(3, guard=True, guard_kind="unkind", arc={"dd": 0.2}),
             _t(4, audio={"echo_share": 0.9}), _sig("s-4"),
             _t(5, guard=True, guard_kind="pii", arc={"dd": 0.1}),
             _t(6, ear={"barge": True}), _t(7, ear={"barge": True}, arc={"dd": 0.1})]
    c = brain.talk_counts(lines, None, "p1", sensitive=True)
    assert c["guard"] == {"pii": 1, "name": 0, "language": 1, "unkind": 0}
    assert c["signals"]["repeat"] == 0, "a signal on an echo turn is not counted"
    assert c["shadow"]["interruptions"] == 1
    assert sum(w["language"] for w in c["weekly"].values()) == 1
    off = brain.talk_counts(lines, None, "p1")
    assert set(off["guard"]) == {"pii", "name"} and "weekly" not in off


def test_summary_api_sensitive_counts_off_by_default(tmp_path, monkeypatch):
    st = turnlog.Store(tmp_path)
    for r in (_t(1, guard=True, guard_kind="language"), _t(2, guard=True, guard_kind="name"), _t(3, profile="p2")):
        st.append(r)
    monkeypatch.setattr(turnlog, "STORE", st)
    safety_ledger.LEDGER.record("p1", "care", "phrase")
    c = _client()
    body = c.get("/api/brain/summary?profile=p1&course=moon").json()
    assert body["talk"]["turns"] == 2 and body["profile"] == "p1" and body["course"] == "moon"
    assert body["safety"]["guard"] == {"pii": 0, "name": 1} and "weekly" not in body["safety"]
    assert body["safety"]["care"] == 1 and body["log"]["retain_days"] == 30
    on = c.get("/api/brain/summary?profile=p1&sensitive=1").json()
    assert on["safety"]["guard"]["language"] == 1 and on["safety"]["weekly"]
    assert c.get("/api/brain/summary?profile=p1&course=Alex%27s").json()["course"] is None


# ---------- the academy: a miss names its misconception kind (enum), never the answer ----------
def test_mixup_kinds():
    m = academy_routes.mixup_of
    assert m({"trap": "pit", "cuts": ["a"]}) == "pit"
    assert m({"trap": "larva"}) == "soundalike"
    assert m({"heard_order": "shields"}) == "order"
    assert m({"wrong": "layer2"}) == "sequence"
    assert m({"choice": "far"}) == "pick"
    assert m({}) is None and m(None) is None
    assert set(academy_routes.MIXUPS) == {"pit", "soundalike", "order", "sequence", "pick"}


def test_a_wrong_choice_reply_carries_its_mixup():
    from app.academy import content
    from app.main import app
    les = next(l for l in content.course()["lessons"]
               if any((s.get("accept") or {}).get("type") == "choice" for s in l["steps"]) and not l.get("ride"))
    i, st = next((i, s) for i, s in enumerate(les["steps"]) if (s.get("accept") or {}).get("type") == "choice")
    acc = st["accept"]
    wrong = next(o for o in acc["options"] if (o["id"] if isinstance(o, dict) else o) != acc["answer"])
    wid = wrong["id"] if isinstance(wrong, dict) else wrong
    r = TestClient(app).post("/api/academy/attempt", json={"lesson_id": les["id"], "step": i, "input": {"choice": wid},
                                                          "misses": 0}).json()
    assert r["status"] == "hint" and r.get("mixup") == "pick", r
