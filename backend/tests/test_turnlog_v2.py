"""Turn log v2 (0.4.3, app/turnlog.py) and a grown-up's Playtest session (app/playtest.py), docs/DIRECTOR_LOOP.md §1 / §1b:
what the Director saw at each turn (the ear's ABI 2 read-out, the situation class, every path's decision), the new
outcome signals, redaction of every new field (no names, call sign or audio in the text log), the playtest's consent,
clips, export zip and import (director_model/import_logs.py), and the real-turn class gate (director_model/eval_real.py)
on a small synthetic playtest zip."""
import asyncio
import io
import json
import sys
import wave
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import models_client, playtest, session as sessions, turnlog
from app.config import settings
from app.gazetteer import Gazetteer
from app.mission import registry
from app.moments import MomentIndex

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "director_model"))
import eval_real as ER  # noqa: E402
import import_logs as IL  # noqa: E402

_W: list = []
TYCHO = {"heard": "tycho", "entity": "Tycho", "state": "linked", "p": 0.97, "tag": "lunar_feature",
         "kind": "lunar_feature", "t0": 0.9, "t1": 1.3}
PCM = (b"\x10\x00\xf0\xff" * 8000)        # 1 s of a quiet square wave, 16 kHz mono PCM16


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


def sess(clock, improve=True, mission=False, sid="tl2"):
    s = sessions.Session(sid, world()[0], world()[1], clock=clock, registry=registry)
    hello = {"t": "hello", "mode": "mission" if mission else "cadet", "callsign": "Comet"}
    if mission:
        hello["mission_id"] = registry.create("shackleton_rim", 3).id
    asyncio.run(s.handle(hello))
    asyncio.run(s.handle({"type": "prefs", "improve": improve}))
    return s


def ear_turn(s, clock, text, ear=None, dd=0.9, pcm=None, partials=True):
    clock.t += 4.0
    asyncio.run(s.handle({"t": "turn", "state": "start", "text": ""}))
    if partials:
        asyncio.run(s.handle({"t": "words", "text": text.split()[0], "final": False}))
    asyncio.run(s.handle({"t": "arc", "device_directed": dd}))
    if ear is not None:
        asyncio.run(s.handle({"t": "words", "text": text, "final": True, **ear}))
    clock.t += 0.8
    m = {"t": "turn", "state": "end", "text": text}
    if pcm:
        m["_pcm"] = pcm
    asyncio.run(s.handle(m))


EAR13 = {"uconf": 0.91, "min_wconf": 0.62, "eot": 0.2, "n_dropped": 0, "names": [], "agree": 1.0,
         "decoder_text": "never", "spoken": "never"}
EAR = {"spoken": "tell me about tycho comet", "names": [TYCHO], "decoder_text": "Tell me about Tycho, Comet.",
       "agree": 0.8, "uconf": 0.91, "min_wconf": 0.42, "eot": 0.31, "n_dropped": 1, "playback_leak": 0.12,
       "playback": False, "barge": True, "barge_p": 0.66, "speech_s": 1.4, "max_pause_s": 0.2, "end_silence_s": 0.5,
       "almost": [{"heard": "tie go", "candidate": "Copernicus", "p": 0.71}],
       "quantities": [{"type": "percent", "value": 40, "unit": "%", "text": "forty percent"}],
       "disfl": [{"i": 2, "w": "um", "kind": "filler"}], "clean_text": "tell me about Tycho Comet"}


def test_v2_logs_what_the_director_saw_with_no_names(logdir):
    clock = Clock()
    s = sess(clock)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "library"}))
    ear_turn(s, clock, "tell me about tycho comet", EAR)
    (r,) = [x for x in lines(logdir) if x["k"] == "turn"]
    assert r["v"] == turnlog.VERSION == 2
    e = r["ear"]
    assert e["uconf"] == 0.91 and e["min_wconf"] == 0.42 and e["eot"] == 0.31 and e["dropped"] == 1
    assert e["agree"] == 0.8 and e["dec"] is True and e["barge"] is True and e["barge_p"] == 0.66
    assert e["playback_leak"] == 0.12 and e["playback"] is False and e["speech_s"] == 1.4
    assert e["names"] == [{"p": 0.97, "state": "linked", "kind": "lunar_feature"}]
    assert e["almost"] == [{"p": 0.71}] and e["qty"] == [{"kind": "percent", "value": 40}] and e["disfl"] == 1
    seen = r["seen"]
    assert seen["cls"] in ("hot", "short", "echo", "video", "quiet") and seen["bare"] is False
    assert seen["e13"]["uconf"] == 0.91 and seen["e13"]["almost"] is True and seen["link"]["linked"] is True
    d = r["director"]
    assert d["mode"] == "guarded" and "picked" in d and d["final"]
    assert "rules" in d and d.get("weights")
    assert isinstance(d["model"], str) and d["shadow"]["act"] == d["model"]     # v1's `model` keeps its meaning
    assert r["text"] == "tell me about tycho <callsign>"           # place names stay in the text (the signal)
    # `entities` (registry ids of what the turn named, never words) predates v2 and is not under test here
    raw = json.dumps({k: v for k, v in r.items() if k not in ("text", "entities")}).lower()
    for bad in ("tycho", "copernicus", "comet", "tie go", "forty", "spoken", "candidate", "decoder_text", "clean_text",
                "pcm", "riff"):
        assert bad not in raw, bad


def test_a_typed_turn_has_no_ear_and_the_bare_turn_is_flagged(logdir):
    clock = Clock()
    s = sess(clock)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": "choice",
                          "step_options": ["A dark flat sea", "A tall mountain"]}))
    ear_turn(s, clock, "a", ear=None, partials=False)          # the backend tests' bare form: no read-out at all
    asyncio.run(s.handle({"t": "typed", "text": "what is a mare"}))
    t1, t2 = [x for x in lines(logdir) if x["k"] == "turn"]
    assert t1["ear"] is None and t1["seen"]["bare"] is True
    assert t2["ear"] is None and t2["seen"]["bare"] is False


def test_pass_and_undo_signals(logdir):
    clock = Clock()
    s = sess(clock)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": "choice",
                          "step_options": ["Never", "Only at full Moon"]}))
    ear_turn(s, clock, "never", EAR13)
    clock.t += 1
    asyncio.run(s.handle({"t": "ui", "event": "lesson_result", "status": "passed"}))
    m = sess(Clock(), mission=True, sid="tl2m")
    m.clock.t += 5
    asyncio.run(m.handle({"t": "ui", "event": "screen", "screen": "cabin"}))
    asyncio.run(m.handle({"t": "typed", "text": "turn on power save"}))
    m.clock.t += 5
    asyncio.run(m.handle({"t": "typed", "text": "turn off power save"}))
    ls = lines(logdir)
    ts = {x["text"]: x for x in ls if x["k"] == "turn"}
    sig = [(x["sig"], x["ref"]) for x in ls if x["k"] == "signal"]
    assert ("pass", ts["never"]["id"]) in sig
    assert ts["turn on power save"]["director"]["cmd"] == {"type": "power_save", "on": True}
    assert ("undo", ts["turn on power save"]["id"]) in sig
    items = {}
    IL.run(IL.files_of([str(logdir)]), logdir / "rt.json", logdir / "rev", quiet=True)
    items = {x["id"]: x for x in json.loads((logdir / "rt.json").read_text())["items"]}
    assert items[ts["never"]["id"]]["gold"]["act"] == "answer" and items[ts["never"]["id"]]["conf"] == 0.9
    assert items[ts["never"]["id"]]["ear"]["uconf"] == 0.91 and items[ts["never"]["id"]]["ear"]["names"] == []           # the read-out replayed on the final words
    assert ts["turn on power save"]["id"] not in items                 # undone: a person decides (review)


def test_room_state_is_logged_when_the_estimator_is_present(logdir):
    clock = Clock()
    s = sess(clock)
    s.room_state = lambda: {"state": "busy", "level_db": -31.2, "voices": 2, "note": "Two kids talking"}
    asyncio.run(s.handle({"t": "typed", "text": "what is a crater"}))
    (r,) = [x for x in lines(logdir) if x["k"] == "turn"]
    assert r["room"] == {"state": "busy", "level_db": -31.2, "voices": 2, "note": None}


def test_playtest_needs_consent_and_logs_even_with_the_switch_off(logdir):
    with pytest.raises(ValueError):
        playtest.start(False)
    assert playtest.active() is False
    clock = Clock()
    s = sess(clock, improve=False)
    ear_turn(s, clock, "what is a crater", EAR, pcm=PCM)
    assert lines(logdir) == []                                # off, no playtest: nothing at all
    playtest.start(True)
    ear_turn(s, clock, "how deep is shackleton", EAR, pcm=PCM)
    asyncio.run(s.handle({"t": "typed", "text": "my name is maya"}))   # private: no words, never audio
    ts = [x for x in lines(logdir) if x["k"] == "turn"]
    assert len(ts) == 2
    assert ts[0]["wav"] == f"playtest/{ts[0]['id']}.wav"
    w = wave.open(str(logdir / ts[0]["wav"]))
    assert (w.getframerate(), w.getnchannels(), w.getnframes()) == (16000, 1, 16000)
    assert ts[1]["guard"] is True and "wav" not in ts[1]
    assert "maya" not in json.dumps(ts)
    st = playtest.status()
    assert st["on"] and st["clips"] == 1 and st["turns"] == 2
    playtest.stop()
    ear_turn(s, clock, "what about tycho", EAR, pcm=PCM)
    assert len([x for x in lines(logdir) if x["k"] == "turn"]) == 2      # stopped: the log is off again
    assert turnlog.STORE.clear() == 2 and turnlog.STORE.clips() == []     # Delete what's saved: text + audio


def test_playtest_turns_itself_off(logdir, monkeypatch):
    playtest.start(True)
    t0 = playtest.STATE["since"]
    monkeypatch.setattr(playtest, "_now", lambda: t0 + playtest.MAX_S + 1)
    assert playtest.active() is False


def test_recorder_cuts_a_turn_with_preroll_only_while_on():
    r = playtest.Recorder(ring_s=10)
    r.feed(b"\x01\x00" * 16000, on=False)
    assert r.buf == b"" and r.mark({"t": "turn", "state": "end"}) is None
    r.feed(b"\x01\x00" * 32000, on=True)                 # 2 s before the turn opens
    r.mark({"t": "turn", "state": "start"})
    r.feed(b"\x02\x00" * 16000, on=True)                 # 1 s of turn
    clip = r.mark({"t": "turn", "state": "end"})
    assert len(clip) == int((playtest.PRE_S + 1.0) * playtest.BYTES_S)
    r.feed(b"\x01\x00" * 16000 * 20, on=True)
    assert len(r.buf) == 10 * playtest.BYTES_S           # the ring keeps RING_S only


def test_playtest_routes(logdir):
    from app.main import app
    c = TestClient(app)
    assert c.post("/api/playtest/start", json={"consent": True}).status_code == 400          # not the page
    assert c.post("/api/playtest/start", json={}, headers={"X-Outpost-Reset": "1"}).status_code == 400
    r = c.post("/api/playtest/start", json={"consent": True}, headers={"X-Outpost-Reset": "1"})
    assert r.status_code == 200 and r.json()["on"] is True
    assert c.get("/api/playtest").json()["on"] is True
    z = c.post("/api/playtest/export", json={"app_version": "0.4.3"})
    assert z.status_code == 200 and z.content[:4] == b"PK\x03\x04"
    man = json.loads(zipfile.ZipFile(io.BytesIO(z.content)).read("manifest.json"))
    assert man["format"] == "outpost-luna-playtest" and man["app_version"] == "0.4.3"
    assert c.post("/api/playtest/stop").json()["on"] is False


def _playtest_zip(logdir) -> Path:
    """A small synthetic playtest: a few real Session turns with the playtest on, exported by the app's own code."""
    clock = Clock()
    s = sess(clock)
    playtest.start(True)
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    ear_turn(s, clock, "what is a crater", EAR, dd=0.2, pcm=PCM)          # ignored (not directed) ...
    ear_turn(s, clock, "what is a crater", EAR, dd=0.95, pcm=PCM)         # ... repeated: the ignore was wrong
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": "choice",
                          "step_options": ["Never", "Only at full Moon"]}))
    ear_turn(s, clock, "never", EAR13, pcm=PCM)
    clock.t += 1
    asyncio.run(s.handle({"t": "ui", "event": "lesson_result", "status": "passed"}))
    body, man = playtest.export_zip("0.4.3-test")
    playtest.stop()
    assert man["clips"] == 3 and man["turns"] == 3
    names = zipfile.ZipFile(io.BytesIO(body)).namelist()
    assert {"manifest.json", "README.txt", "turns.jsonl"} <= set(names)
    assert all(n.startswith("playtest/") and n.endswith(".wav") for n in names if n.endswith(".wav"))
    out = logdir / "fixture" / "outpost-luna-playtest-2026-11-19.zip"
    out.parent.mkdir()
    out.write_bytes(body)
    return out


def test_import_a_playtest_zip_and_its_clips(logdir):
    z = _playtest_zip(logdir)
    zip_bad = logdir / "evil.zip"                       # a member name that tries to leave the folder is ignored
    with zipfile.ZipFile(zip_bad, "w") as zz:
        zz.writestr("../../escape.wav", b"x")
        zz.writestr("turns.jsonl", "")
    out, rev, aud = logdir / "rt.json", logdir / "rev", logdir / "audio"
    res = IL.run(IL.files_of([str(z), str(zip_bad)]), out, rev, quiet=True, audio_dir=aud)
    assert res["turns"] == 3 and res["versions"] == {2: 3} and res["clips"] >= 2
    rows = [json.loads(x) for x in (aud / z.stem / "clips.jsonl").read_text().splitlines()]
    assert all((aud / z.stem / r["wav"]).exists() and r["gold"]["act"] for r in rows)
    assert not (logdir / "escape.wav").exists() and not any(p.name == "escape.wav" for p in logdir.rglob("*"))


def test_eval_real_on_a_synthetic_playtest_zip(logdir, capsys):
    z = _playtest_zip(logdir)
    res = ER.main(["--log", str(z), "--out", str(logdir / "eval.json")])
    txt = capsys.readouterr().out
    assert "| class | turns | rules ok (wrong) | shipped ok (wrong) | extra wrong | ok |" in txt
    assert res["all"]["n"] == 3
    assert res["all"]["rules_ok"] >= 1 and res["all"]["ship_wrong"] == 0
    assert "Decided live by:" in txt and "Shipped in this checkout:" in txt
    assert json.loads((logdir / "eval.json").read_text())["turns"] == 3


def test_eval_real_reads_v1_lines_as_unknown_class(tmp_path):
    rows = [{"k": "turn", "v": 1, "s": "ab", "id": "ab-0", "text": "next", "nw": 1, "router": {"outcome": "navigate"},
             "frame": {"screen": "lesson_done"}, "arc": {}, "director": {"final": "navigate", "rules": "navigate"}}]
    (tmp_path / "turns.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    res = ER.gate(ER.rows_of(IL.files_of([str(tmp_path)]), reviewed={}))
    assert res["unknown"]["n"] == 1 and res["all"]["ship_ok"] == 1
