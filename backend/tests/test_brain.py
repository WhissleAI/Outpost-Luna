"""The Brain's grown-up numbers (app/brain.py, docs/BRAIN.md §4): counts only; no words, names or call signs leave."""
import datetime as dt
import json

from fastapi.testclient import TestClient

from app import brain, learn, turnlog


def _turn(src="listen", day=None, outcome="answer", room="calm", guard=False, text="<callsign> fly to tycho"):
    r = {"k": "turn", "v": 2, "s": "ab12", "id": "ab12-1", "day": day or dt.date.today().isoformat(), "text": text,
         "src": src, "router": {"outcome": outcome}, "room": {"state": room, "listen": "open"}}
    if guard:
        r["text"], r["guard"] = "<private>", True
    return json.dumps(r)


def test_talk_counts_voice_typed_answered_room_and_signals():
    lines = [_turn(), _turn(src="typed"), _turn(src="ptt", outcome="ignore", room="busy"), _turn(guard=True),
             json.dumps({"k": "signal", "sig": "hint", "ref": "x"}), json.dumps({"k": "signal", "sig": "pass", "ref": "y"}),
             json.dumps({"k": "signal", "sig": "secret", "ref": "z"}), "not json", json.dumps([1, 2])]
    c = brain.talk_counts(lines)
    assert c["turns"] == 4 and c["voice"] == 3 and c["typed"] == 1
    assert c["answered"] == 3 and c["passed_by"] == 1 and c["guarded"] == 1
    assert c["room"] == {"calm": 3, "busy": 1, "loud": 0}
    assert c["signals"]["hint"] == 1 and c["signals"]["pass"] == 1 and "secret" not in c["signals"]
    assert c["days"] == 1


def test_talk_counts_window_skips_old_days():
    old = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    since = (dt.date.today() - dt.timedelta(days=29)).isoformat()
    c = brain.talk_counts([_turn(day=old), _turn()], since)
    assert c["turns"] == 1


def test_summary_has_no_words_names_or_call_signs(tmp_path, monkeypatch):
    monkeypatch.setenv("TURNLOG_DIR", str(tmp_path))
    st = turnlog.Store(tmp_path)
    for ln in (_turn(text="nova says shackleton is cold"), _turn(src="typed", text="my name is alex"), _turn(guard=True)):
        st.append(json.loads(ln))
    monkeypatch.setattr(turnlog, "STORE", st)
    lr = learn.for_profile("p1")
    lr.aliases.confirm("ticko", "tycho", p=0.95)
    lr.save()
    from app.main import app
    body = TestClient(app).get("/api/brain/summary?profile=p1").json()
    assert body["talk"]["turns"] == 3 and body["talk"]["voice"] == 2 and body["safety"]["guarded"] == 1
    assert body["adapted"]["names"] == 1 and body["words"] is False
    raw = json.dumps(body).lower()
    for w in ("ticko", "tycho", "nova", "shackleton", "alex", "callsign", "private"):
        assert w not in raw, w


def test_summary_needs_the_token(monkeypatch):
    from app.main import app
    monkeypatch.setenv("LUNA_TOKEN", "t" * 43)
    c = TestClient(app)
    assert c.get("/api/brain/summary").status_code == 401
    assert c.get("/api/brain/summary", headers={"X-Luna-Token": "t" * 43}).status_code == 200


def test_adapted_view_counts_only():
    lr = learn.for_profile("p2")
    v = brain.adapted_view("p2")
    assert v == {"names": 0, "wait_s": 0.5, "turns": 0, "waits_longer": False}
    lr.aliases.confirm("ticko", "tycho", p=0.95)
    lr.save()
    assert brain.adapted_view("p2")["names"] == 1


def test_router_hears_my_brain_on_any_screen():
    from app import turn_router as R
    for screen in ("map", "lesson", "library", "brief", "debrief"):
        ctx = R.Ctx(screen=screen)
        for said in ("my brain", "open my brain", "show me my brain", "what have I learned", "how does the outpost think"):
            assert R.nav_intent(said, ctx) == ("brain", None), (screen, said)
    assert R.nav_intent("show my patches", R.Ctx(screen="map"))[0] == "map"


# ---- D9 (docs/BRAIN_SIGNALS_AUDIT.md §2): the day window, the profanity / privacy split, the flags' token ----

def _sig(sig, day=None):
    r = {"k": "signal", "v": 2, "s": "ab12", "ref": "ab12-0", "sig": sig}
    if day is not None:
        r["day"] = day
    return json.dumps(r)


def test_signals_honour_the_day_window():
    today = dt.date.today().isoformat()
    old = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    since = (dt.date.today() - dt.timedelta(days=29)).isoformat()
    lines = [_sig("hint", today), _sig("hint", old), _sig("pass", old), _sig("repeat")]   # the last: no day (pre-D9)
    c = brain.talk_counts(lines, since)
    assert c["signals"]["hint"] == 1 and c["signals"]["pass"] == 0 and c["signals"]["repeat"] == 0
    assert brain.talk_counts(lines)["signals"]["hint"] == 2   # no window: everything counts


def test_signal_lines_carry_the_day(tmp_path):
    st = turnlog.Store(tmp_path)

    class _S:
        prefs = {"improve": True}
        screen, belief = {}, {}

        @staticmethod
        def clock():
            return 1.0
    lg = turnlog.SessionLog(_S(), st)
    lg._signal({"id": "x-0"}, "hint", 1.0)
    rec = json.loads(st.path.read_text().splitlines()[0])
    assert rec["k"] == "signal" and rec["day"] == dt.date.today().isoformat()


def test_profanity_is_split_from_privacy():
    masked = json.loads(_turn(guard=True))
    masked["router"] = {"outcome": "ignore", "reason": "safety"}
    c = brain.talk_counts([json.dumps(masked), _turn(guard=True), _turn(guard=True), _turn()])
    assert c["filtered"] == 1 and c["privacy"] == 2 and c["guarded"] == 3


def test_summary_safety_split(tmp_path, monkeypatch):
    st = turnlog.Store(tmp_path)
    masked = json.loads(_turn(guard=True))
    masked["router"] = {"outcome": "ignore", "reason": "safety"}
    st.append(masked)
    st.append(json.loads(_turn(guard=True)))
    monkeypatch.setattr(turnlog, "STORE", st)
    from app.main import app
    sf = TestClient(app).get("/api/brain/summary?profile=p1").json()["safety"]
    assert sf["filtered"] == 1 and sf["privacy"] == 1 and sf["guarded"] == 2


def test_safety_flags_need_the_token(monkeypatch):
    from app.main import app
    monkeypatch.setenv("LUNA_TOKEN", "t" * 43)
    c = TestClient(app)
    assert c.get("/api/safety/flags").status_code == 401
    assert c.get("/api/safety/flags", headers={"X-Luna-Token": "x" * 43}).status_code == 401
    r = c.get("/api/safety/flags", headers={"X-Luna-Token": "t" * 43})
    assert r.status_code == 200 and "flags" in r.json()
