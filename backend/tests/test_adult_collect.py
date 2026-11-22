"""An adult's "Help improve Outpost Luna" (app/adult_collect.py, docs/ADULT_SESSIONS.md): the opt-in's gating (consent,
adult, the page's header, the profile it was turned on from), the label fields and outcome signals each collected turn
carries (turnlog `collect` / `reply`, misheard / barge / nav_back), audio as its own switch, the redacted export that
holds ONLY collected turns, "Delete everything", and the round trip through import_logs, eval_real and the label tool
(director_model/label_ui) into data/real_turns.json."""
import asyncio
import io
import json
import sys
import threading
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import adult_collect as AC, models_client, playtest, session as sessions, turnlog
from app.config import settings
from app.gazetteer import Gazetteer
from app.mission import registry
from app.moments import MomentIndex

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "director_model"))
sys.path.insert(0, str(ROOT / "director_model" / "label_ui"))
import eval_real as ER  # noqa: E402
import import_logs as IL  # noqa: E402
import serve as LU  # noqa: E402

PCM = (b"\x10\x00\xf0\xff" * 8000)
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


@pytest.fixture
def logdir(tmp_path, monkeypatch):
    monkeypatch.setenv("TURNLOG_DIR", str(tmp_path))
    monkeypatch.setenv("DIRECTOR_MODEL", "guarded")

    async def none(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", none)
    playtest.stop()
    yield tmp_path
    playtest.stop()


def lines(d):
    out = []
    for f in turnlog.Store(d).files():
        out += [json.loads(x) for x in f.read_text().splitlines()]
    return out


def sess(clock, profile="p2", improve=False, sid="ac", mission=False):
    s = sessions.Session(sid, world()[0], world()[1], clock=clock, registry=registry)
    hello = {"t": "hello", "mode": "mission" if mission else "cadet", "callsign": "Comet"}
    if mission:
        hello["mission_id"] = registry.create("shackleton_rim", 3).id
    asyncio.run(s.handle(hello))
    asyncio.run(s.handle({"type": "prefs", "improve": improve, "profile": profile}))
    return s


def ear_turn(s, clock, text, dd=0.9, pcm=None, gap=4.0):
    clock.t += gap
    asyncio.run(s.handle({"t": "turn", "state": "start", "text": ""}))
    asyncio.run(s.handle({"t": "arc", "device_directed": dd}))
    asyncio.run(s.handle({"t": "words", "text": text, "final": True, "uconf": 0.9, "eot": 0.3}))
    clock.t += 0.8
    m = {"t": "turn", "state": "end", "text": text}
    if pcm:
        m["_pcm"] = pcm
    asyncio.run(s.handle(m))


def turns(d):
    return [x for x in lines(d) if x["k"] == "turn"]


# --------------------------------------------------------------------------------------------------- the opt-in
def test_off_by_default_and_on_needs_consent_adult_and_a_profile(logdir):
    assert AC.state()["on"] is False and AC.on_for("p1") is False
    for kw in ({}, {"consent": True}, {"adult": True}, {"consent": True, "adult": True},
               {"consent": True, "adult": True, "profile": "kid"}):
        with pytest.raises(ValueError):
            AC.set_state(True, **kw)
    assert AC.state()["on"] is False
    st = AC.set_state(True, consent=True, adult=True, profile="p2")
    assert st["on"] is True and st["audio"] is False and st["profile"] == "p2"
    assert AC.on_for("p2") and not AC.on_for("p1") and not AC.audio_for("p2")
    AC.set_state(False)
    assert AC.state()["on"] is False


def test_an_older_consent_text_reads_as_off(logdir):
    (logdir / "collect.json").write_text(json.dumps({"on": True, "audio": True, "profile": "p1", "consent_v": 0}))
    assert AC.state()["on"] is False and AC.state()["profile"] is None


def test_it_switches_itself_off_after_4_hours(logdir, monkeypatch):
    t0 = 1_800_000_000.0
    monkeypatch.setattr(AC, "_now", lambda: t0)
    st = AC.set_state(True, consent=True, adult=True, profile="p2")
    assert st["on"] and st["until"] == t0 + AC.MAX_S == t0 + 4 * 3600 and st["max_s"] == 4 * 3600
    monkeypatch.setattr(AC, "_now", lambda: t0 + 3600)
    assert AC.set_state(True, audio=True, consent=True, adult=True, profile="p2")["until"] == t0 + AC.MAX_S, \
        "the audio switch keeps the clock"
    monkeypatch.setattr(AC, "_now", lambda: t0 + AC.MAX_S - 1)
    assert AC.on_for("p2") and AC.audio_any()
    monkeypatch.setattr(AC, "_now", lambda: t0 + AC.MAX_S)
    assert AC.on_for("p2") is False and AC.audio_any() is False and playtest.recording() is False
    assert AC.status()["on"] is False and AC.status()["until"] is None
    clock = Clock()                                   # expired: a turn of that profile is not collected
    s = sess(clock)
    ear_turn(s, clock, "what is a crater", pcm=PCM)
    assert turns(logdir) == []
    monkeypatch.setattr(AC, "_now", lambda: t0 + AC.MAX_S + 10)
    assert AC.set_state(True, consent=True, adult=True, profile="p2")["until"] == t0 + 2 * AC.MAX_S + 10   # on again


def test_it_is_off_when_the_app_starts_again_and_collected_turns_stay(logdir, monkeypatch):
    AC.set_state(True, consent=True, adult=True, profile="p2")
    clock = Clock()
    s = sess(clock)
    ear_turn(s, clock, "what is a crater")
    assert AC.status()["turns"] == 1 and AC.on_for("p2")
    monkeypatch.setattr(AC, "BOOT", "0123456789ab")   # the app quit; a new backend process reads the same file
    assert AC.state()["on"] is False and AC.on_for("p2") is False
    st = AC.status()
    assert st["on"] is False and st["turns"] == 1     # what was collected stays until exported or deleted
    body, man = AC.export_zip("x")
    assert man["turns"] == 1


def test_routes_need_the_page_header_and_consent(logdir):
    from app.main import app
    c = TestClient(app)
    body = {"on": True, "consent": True, "adult": True, "profile": "p1"}
    assert c.post("/api/collect", json=body).status_code == 400                       # not the page
    assert c.post("/api/collect", json={**body, "adult": False}, headers={"X-Outpost-Reset": "1"}).status_code == 400
    assert c.get("/api/collect").json()["on"] is False
    r = c.post("/api/collect", json=body, headers={"X-Outpost-Reset": "1"})
    assert r.status_code == 200 and r.json()["on"] is True and r.json()["profile"] == "p1"
    assert c.post("/api/collect/delete").status_code == 400                            # not the page
    assert c.post("/api/collect/export", json={"app_version": "0.5.8"}).status_code == 400   # not the page
    z = c.post("/api/collect/export", json={"app_version": "0.5.8"}, headers={"X-Outpost-Reset": "1"})
    assert z.status_code == 200 and z.content[:4] == b"PK\x03\x04"
    assert json.loads(zipfile.ZipFile(io.BytesIO(z.content)).read("manifest.json"))["format"] == AC.FORMAT
    assert c.post("/api/collect", json={"on": False}, headers={"X-Outpost-Reset": "1"}).json()["on"] is False


def test_a_kid_profile_is_never_collected(logdir):
    AC.set_state(True, audio=True, consent=True, adult=True, profile="p2")
    clock = Clock()
    kid = sess(clock, profile="p1", improve=True, sid="kid")                # a kid's profile, the log on by default
    ear_turn(kid, clock, "what is a crater", pcm=PCM)
    off = sess(Clock(), profile="p3", improve=False, sid="kid3")            # another profile, log off: nothing
    ear_turn(off, off.clock, "what is a crater", pcm=PCM)
    (t,) = turns(logdir)
    assert "collect" not in t and "reply" not in t and "wav" not in t       # the kid's turn: no tag, no reply, no audio
    assert turnlog.STORE.clips() == []
    assert AC.status()["turns"] == 0


# ----------------------------------------------------------------------------------------------- what a turn holds
def test_a_collected_turn_carries_the_labels_the_director_needs(logdir):
    AC.set_state(True, consent=True, adult=True, profile="p2")
    clock = Clock()
    s = sess(clock)                                   # improve off: collection alone turns the log on
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "library"}))
    ear_turn(s, clock, "tell me about tycho comet")
    (t,) = turns(logdir)
    assert t["collect"] is True and t["v"] == turnlog.VERSION
    assert t["text"] == "tell me about tycho <callsign>"
    assert t["frame"]["screen"] == "library" and t["arc"]["dd"] == 0.9 and t["ear"]["uconf"] == 0.9
    assert t["director"]["final"] and t["router"]["outcome"]
    rep = t["reply"]
    assert set(rep) == {"say", "nav", "place", "kinds"}
    assert rep["say"] and all("Comet" not in x and "comet" not in x.lower() for x in rep["say"])
    assert AC.status()["turns"] == 1


def test_navigation_and_order_slots_are_logged(logdir):
    AC.set_state(True, consent=True, adult=True, profile="p2")
    clock = Clock()
    s = sess(clock, mission=True, sid="acm")
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "cabin"}))
    asyncio.run(s.handle({"t": "typed", "text": "turn on power save"}))
    clock.t += 3
    asyncio.run(s.handle({"t": "typed", "text": "open the library"}))
    ts = {x["text"]: x for x in turns(logdir)}
    assert ts["turn on power save"]["director"]["cmd"] == {"type": "power_save", "on": True}
    nav = ts["open the library"]
    assert nav["director"]["final"] == "navigate"
    assert nav["reply"]["nav"]["intent"] and "nav" in nav["reply"]["kinds"]


def test_misheard_barge_and_nav_back_signals(logdir):
    AC.set_state(True, consent=True, adult=True, profile="p2")
    clock = Clock()
    s = sess(clock)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    ear_turn(s, clock, "what is a crater")
    ear_turn(s, clock, "no that s not what i said", gap=2.0)
    ear_turn(s, clock, "tell me about the sea of tranquility", gap=3.0)
    clock.t += 2
    asyncio.run(s.handle({"t": "ui", "event": "barge_in"}))            # talked over the answer
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    asyncio.run(s.handle({"t": "typed", "text": "open the library"}))
    clock.t += 1
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "library"}))   # the navigation ran ...
    clock.t += 3
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))       # ... and was taken back
    ls = lines(logdir)
    ts = {x["text"]: x["id"] for x in ls if x["k"] == "turn"}
    sig = {(x["sig"], x["ref"]) for x in ls if x["k"] == "signal"}
    assert ("misheard", ts["what is a crater"]) in sig
    assert ("barge", ts["tell me about the sea of tranquility"]) in sig
    assert ("nav_back", ts["open the library"]) in sig
    lab, conf, _ = IL.weak_label(next(x for x in ls if x.get("id") == ts["open the library"]),
                                 [x for x in ls if x.get("ref") == ts["open the library"]], {})
    assert lab == "ask_clarify" and conf < IL.REVIEW_MIN                    # a navigation taken back goes to a person


def test_audio_only_with_its_own_switch_and_never_for_a_private_turn(logdir):
    AC.set_state(True, consent=True, adult=True, profile="p2")
    clock = Clock()
    s = sess(clock)
    assert playtest.recording() is False                                   # the relay keeps no ring buffer yet
    ear_turn(s, clock, "what is a crater", pcm=PCM)
    assert "wav" not in turns(logdir)[0] and turnlog.STORE.clips() == []
    AC.set_state(True, audio=True, consent=True, adult=True, profile="p2")
    assert playtest.recording() is True
    ear_turn(s, clock, "how deep is shackleton", pcm=PCM)
    asyncio.run(s.handle({"t": "typed", "text": "my name is maya"}))
    t = turns(logdir)
    assert t[1]["wav"] == f"playtest/{t[1]['id']}.wav" and (logdir / t[1]["wav"]).exists()
    assert t[2]["guard"] is True and t[2]["text"] == "<private>" and "wav" not in t[2] and "reply" not in t[2]
    assert "maya" not in json.dumps(t)
    assert AC.status()["clips"] == 1


# ------------------------------------------------------------------------------------------- export and delete
def _session_with_mixed_log(logdir):
    """A kid's turns (log on by default) and an adult's collected turns (with audio) in the same turn log."""
    kid = sess(Clock(), profile="p1", improve=True, sid="kidm")
    ear_turn(kid, kid.clock, "what is a crater", pcm=PCM)
    AC.set_state(True, audio=True, consent=True, adult=True, profile="p2")
    clock = Clock()
    s = sess(clock, sid="adm")
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    ear_turn(s, clock, "what is a crater", dd=0.2, pcm=PCM)                 # ignored (not directed) ...
    ear_turn(s, clock, "what is a crater", dd=0.95, pcm=PCM)                # ... repeated
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": "choice",
                          "step_options": ["Never", "Only at full Moon"]}))
    ear_turn(s, clock, "never", pcm=PCM)
    clock.t += 1
    asyncio.run(s.handle({"t": "ui", "event": "lesson_result", "status": "passed"}))
    return kid, s


def test_export_holds_only_collected_turns_redacted_again(logdir):
    _session_with_mixed_log(logdir)
    # an older collected line whose words were never redacted (a call sign the client never sent, a phone number)
    turnlog.STORE.append({"k": "turn", "v": 2, "s": "deadbeef", "id": "deadbeef-0", "collect": True,
                          "text": "call 5551234567 star hopper", "reply": {"say": ["Copy, Star Hopper."]},
                          "router": {"outcome": "ignore"}, "director": {"final": "ignore"}, "_x": "drop me"})
    body, man = AC.export_zip("0.5.8-test")
    z = zipfile.ZipFile(io.BytesIO(body))
    rows = [json.loads(x) for x in z.read("turns.jsonl").decode().splitlines()]
    ts = [r for r in rows if r["k"] == "turn"]
    assert man["format"] == AC.FORMAT and man["speaker"] == "adult" and man["turns"] == 4 == len(ts)
    assert all(r["collect"] is True for r in ts)                          # never the kid's turn
    assert {r["s"] for r in ts} != {None} and len({r["s"] for r in ts}) == 2
    sigs = [r for r in rows if r["k"] == "signal"]
    assert sigs and all(s["ref"] in {t["id"] for t in ts} for s in sigs)
    old = next(r for r in ts if r["id"] == "deadbeef-0")
    assert old["text"] == "call <number> <callsign>" and old["reply"]["say"] == ["Copy, <callsign>."]
    assert "_x" not in old
    wavs = [n for n in z.namelist() if n.endswith(".wav")]
    assert len(wavs) == man["clips"] == 3 and all(n.startswith("playtest/") for n in wavs)
    kid_wav = [x for x in turns(logdir) if not x.get("collect")][0].get("wav")
    assert kid_wav is None                                                # the kid's turn never had audio
    raw = z.read("turns.jsonl").decode().lower()
    for bad in ("comet", "star hopper", "5551234567", "maya"):
        assert bad not in raw, bad


def test_delete_everything_keeps_the_rest_of_the_log(logdir):
    _session_with_mixed_log(logdir)
    assert AC.status()["turns"] == 3 and AC.status()["clips"] == 3
    res = AC.delete_all()
    assert res["turns"] == 0 and res["clips"] == 0 and res["deleted_clips"] == 3
    left = lines(logdir)
    assert len([x for x in left if x["k"] == "turn"]) == 1 and not any(x.get("collect") for x in left)
    assert turnlog.STORE.clips() == []


# ------------------------------------------------------------------------------------- review fixes before 0.5.8
@pytest.mark.parametrize("engine", ["graph", "legacy"])
def test_a_pii_flagged_turn_keeps_no_words_reply_or_clip(logdir, monkeypatch, engine):
    """Arc's PII tag marks the turn private at the safety step; the Director's own guard (no name given here) must not
    clear that flag again."""
    monkeypatch.setenv("TURN_ENGINE", engine)
    AC.set_state(True, audio=True, consent=True, adult=True, profile="p2")
    clock = Clock()
    s = sess(clock, sid=f"pii{engine}")
    clock.t += 4
    asyncio.run(s.handle({"t": "turn", "state": "start", "text": ""}))
    pii = [{"tag": "safety.pii.leak", "p": 0.99, "thr": 0.5, "on": True}]
    asyncio.run(s.handle({"t": "arc", "device_directed": 0.9, "safety": pii}))
    asyncio.run(s.handle({"t": "words", "text": "tell me about tycho", "final": True, "uconf": 0.9, "eot": 0.3}))
    clock.t += 0.8
    asyncio.run(s.handle({"t": "turn", "state": "end", "text": "tell me about tycho", "_pcm": PCM}))
    (t,) = turns(logdir)
    assert t["collect"] is True and t["guard"] is True and t["text"] == "<private>"
    assert "reply" not in t and "wav" not in t and turnlog.STORE.clips() == []
    assert "tell me about" not in json.dumps(lines(logdir))           # the words (entity ids stay, as on every turn)


def test_the_audio_switch_never_turns_collection_back_on(logdir, monkeypatch):
    from app.main import app
    t0 = 1_800_000_000.0
    monkeypatch.setattr(AC, "_now", lambda: t0)
    with pytest.raises(AC.NotOn):                                     # never turned on
        AC.set_state(True, audio=True, profile="p2", audio_only=True)
    AC.set_state(True, consent=True, adult=True, profile="p2")
    monkeypatch.setattr(AC, "_now", lambda: t0 + 60)
    st = AC.set_state(True, audio=True, profile="p2", audio_only=True)   # on: no consent needed, the clock kept
    assert st["on"] and st["audio"] and st["until"] == t0 + AC.MAX_S
    with pytest.raises(AC.NotOn):                                     # another profile's switch
        AC.set_state(True, audio=False, profile="p3", audio_only=True)
    monkeypatch.setattr(AC, "_now", lambda: t0 + AC.MAX_S + 1)       # it switched itself off
    c = TestClient(app)
    h = {"X-Outpost-Reset": "1"}
    r = c.post("/api/collect", json={"on": True, "audio": True, "consent": True, "adult": True, "profile": "p2",
                                     "audio_only": True}, headers=h)
    assert r.status_code == 409 and c.get("/api/collect").json()["on"] is False
    assert AC.on_for("p2") is False and AC.audio_any() is False


def test_the_recorder_asks_memory_not_the_disk_per_mic_frame(logdir, monkeypatch):
    t0 = 1_800_000_000.0
    monkeypatch.setattr(AC, "_now", lambda: t0)
    AC.set_state(True, audio=True, consent=True, adult=True, profile="p2")
    assert AC.audio_any() is True
    calls = []
    real = AC.state
    monkeypatch.setattr(AC, "state", lambda: calls.append(1) or real())
    rec = playtest.Recorder()
    for _ in range(200):
        rec.feed(b"\x00\x01" * 160)
    assert calls == [] and len(rec.buf) == 200 * 320                 # no file read per frame
    monkeypatch.setattr(AC, "_now", lambda: t0 + AC.MAX_S)          # the 4 hours are up: a clock check, no syscall
    assert AC.audio_any() is False and playtest.recording() is False and calls == []
    AC.set_state(False)
    monkeypatch.setattr(AC, "_now", lambda: t0)
    assert AC.audio_any() is False


def test_misheard_needs_i_said_at_the_start_of_the_turn():
    M = turnlog.MISHEARD
    for t in ("i said tycho", "no i said shields", "no that s not what i said", "you misheard", "wait i said tycho"):
        assert M.search(t), t
    for t in ("remember what i said about tycho", "tell me what i said", "did you hear what i said earlier"):
        assert not M.search(t), t


def test_playtest_export_leaves_out_the_adults_collected_turns_and_clips(logdir):
    playtest.start(True)
    kid = sess(Clock(), profile="p1", improve=True, sid="kidp")
    ear_turn(kid, kid.clock, "what is a crater", pcm=PCM)            # a Playtest clip
    _session_with_mixed_log(logdir)
    adult_ids = {t["id"] for t in turns(logdir) if t.get("collect")}
    assert len(turnlog.STORE.clips()) == 5                            # 2 kid playtest clips + 3 adult clips
    body, man = playtest.export_zip("0.5.8-test")
    z = zipfile.ZipFile(io.BytesIO(body))
    rows = [json.loads(x) for n in z.namelist() if n.endswith(".jsonl") for x in z.read(n).decode().splitlines()]
    assert rows and not any(r.get("collect") for r in rows)
    assert not any(r.get("ref") in adult_ids for r in rows if r["k"] == "signal")
    assert man["turns"] == len([r for r in rows if r["k"] == "turn"]) == 2
    wavs = sorted(n for n in z.namelist() if n.endswith(".wav"))
    assert len(wavs) == man["clips"] == 2 and not any(i in w for w in wavs for i in adult_ids)
    playtest.stop()


def test_adult_clips_do_not_use_up_the_playtest_cap(logdir, monkeypatch):
    _session_with_mixed_log(logdir)
    used = turnlog.STORE.stats()["clip_bytes"]
    assert used > 0 and AC.clip_bytes() == used
    monkeypatch.setattr(playtest, "CAP_BYTES", used + 10)
    playtest.start(True)
    assert playtest.save_clip("abcdef01-1", PCM) == "playtest/abcdef01-1.wav"   # the adult's clips don't count
    playtest.stop()


def test_delete_everything_runs_under_the_log_lock_and_reaches_the_rotated_file(logdir, monkeypatch):
    _session_with_mixed_log(logdir)
    size = turnlog.STORE.path.stat().st_size
    monkeypatch.setattr(turnlog.STORE, "cap", 2 * size + 20)          # the next line rotates the live file once
    turnlog.STORE.append({"k": "turn", "v": 2, "s": "feedf00d", "id": "feedf00d-0", "text": "x" * 60,
                          "router": {"outcome": "ignore"}, "director": None})
    in_rotated = [json.loads(x) for x in (logdir / "turns.1.jsonl").read_text().splitlines()]
    assert sum(1 for r in in_rotated if r.get("collect")) == 3          # every collected line is in the rotated file
    before = AC.status()["turns"]
    done = []
    with turnlog.STORE.lock:
        th = threading.Thread(target=lambda: done.append(AC.delete_all()))
        th.start()
        th.join(0.2)
        assert th.is_alive() and not done                              # it waits for the lock: nothing read early
    th.join(5)
    res = done[0]
    assert res["deleted_clips"] == 3 and res["turns"] == 0 and res["clips"] == 0 and before == 3
    assert not any(x.get("collect") for x in lines(logdir)) and turnlog.STORE.clips() == []


# --------------------------------------------------------------------------- import, eval and the label tool
def _export(logdir) -> Path:
    _session_with_mixed_log(logdir)
    body, _ = AC.export_zip("0.5.8-test")
    out = logdir / "fx" / "outpost-luna-help-2026-11-22.zip"
    out.parent.mkdir()
    out.write_bytes(body)
    return out


def test_import_round_trip_of_an_adult_export(logdir):
    z = _export(logdir)
    out, rev, aud = logdir / "rt.json", logdir / "rev", logdir / "audio"
    res = IL.run(IL.files_of([str(z)]), out, rev, quiet=True, audio_dir=aud)
    assert res["turns"] == 3 and res["clips"] >= 1
    items = json.loads(out.read_text())["items"]
    assert items and all(x["speaker"] == "adult" for x in items)
    never = next(x for x in items if x["text"] == "never")
    assert never["gold"]["act"] == "answer" and never["conf"] == 0.9 and "pass" in never["signals"]
    assert "reply" in never
    ev = ER.gate(ER.rows_of(IL.files_of([str(z)]), reviewed={}))
    assert ev["all"]["n"] >= 2


def test_label_tool_writes_real_turns_in_the_import_format(logdir):
    z = _export(logdir)
    out, rev = logdir / "data" / "real_turns.json", logdir / "data" / "review"
    L = LU.Labeller([str(z)], out, rev, logdir / "data" / "real_audio", by="kr")
    rows = L.turns()
    assert len(rows) == 3 and all(r["collect"] for r in rows)
    r0 = rows[0]
    assert {"text", "frame", "arc", "ear", "router", "director", "reply", "signals", "weak", "start",
            "candidates"} <= set(r0)
    assert r0["audio"] is True and L.audio(r0["id"])[:4] == b"RIFF"
    assert "Say again? I missed that." in r0["candidates"]
    # navigate, with the intent and its argument, held out
    L.label({"id": r0["id"], "act": "navigate", "nav": "library", "nav_arg": "tycho", "place": "tycho",
             "reply": "", "test": True})
    # an order with its slots
    L.label({"id": rows[1]["id"], "act": "command", "cmd": "allocate to=heaters amount=percent:40"})
    # skip
    L.label({"id": rows[2]["id"], "act": "skip"})
    for bad in ({"id": "nope", "act": "answer"}, {"id": r0["id"], "act": "dance"},
                {"id": r0["id"], "act": "navigate", "nav": "the moon"},
                {"id": r0["id"], "act": "command", "cmd": "allocate to heaters"},
                {"id": r0["id"], "act": "answer", "place": "<script>"}):
        with pytest.raises(ValueError):
            L.label(bad)
    items = {x["id"]: x for x in json.loads(out.read_text())["items"]}
    a = items[r0["id"]]
    assert a["gold"] == {"act": "navigate", "nav": "library", "nav_arg": "tycho", "place": "tycho", "reply": ""}
    assert a["split"] == "test" and a["conf"] == 1.0 and a["why"] == "reviewed" and a["labelled_by"] == "kr"
    b = items[rows[1]["id"]]
    assert b["gold"] == {"act": "command", "cmd": {"type": "allocate", "to": "heaters",
                                                   "amount": {"kind": "percent", "value": 40}}}
    assert rows[2]["id"] not in items                                      # skipped: out of the set
    # the item keeps the fields the generator reads (gen_sessions.logged_items)
    for k in ("text", "heard", "cat", "root", "gold", "conf", "frame", "split", "id"):
        assert k in a
    # reviewed rows are the import's own format: a fresh import applies them, and eval_real reads the navigation gold
    assert IL.load_reviewed(rev)[r0["id"]] == "navigate"
    rows2 = {r["id"]: r for r in LU.Labeller([str(z)], out, rev).turns()}
    assert rows2[r0["id"]]["start"]["act"] == "navigate" and rows2[r0["id"]]["start"]["test"] is True
    assert LU.parse_cmd(LU.cmd_text(b["gold"]["cmd"])) == b["gold"]["cmd"]


def test_label_tool_http_is_local_only(logdir):
    z = _export(logdir)
    L = LU.Labeller([str(z)], logdir / "rt.json", logdir / "rev", logdir / "aud")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), LU.make_handler(L))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        assert "<title>Turn labeller</title>" in page
        assert "http://" not in page.replace("http://127.0.0.1", "") and "https://" not in page   # no network
        ts = json.loads(urllib.request.urlopen(base + "/api/turns").read())
        assert len(ts) == 3
        req = urllib.request.Request(base + "/api/label", data=json.dumps({"id": ts[0]["id"], "act": "ignore"}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as e:                      # without the page's header
            urllib.request.urlopen(req)
        assert e.value.code == 403
        req.add_header("X-Label-UI", "1")
        assert json.loads(urllib.request.urlopen(req).read())["ok"] is True
        bad = urllib.request.Request(base + "/api/turns", headers={"Host": "evil.example"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad)
        assert e.value.code == 403
    finally:
        srv.shutdown()
