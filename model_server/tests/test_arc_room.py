"""Arc Transcriber Space v2 room read-outs (app/arc_room.py; docs/ARC_V2.md). The summary and the plumbing run without the
model; the libarc tap + room.onnx path runs on the real model when it is a v2 one (skips otherwise)."""
from pathlib import Path

import numpy as np
import pytest

from app import arc_ear, arc_room, arcmeta

FIX = Path(__file__).resolve().parents[2] / "backend/tests/fixtures/crew_orientale_16k.s16le"
CFG = {"file": "room.onnx", "frame_s": 0.08,
       "frames": ["app_playback", "media_playback", "live_speech", "end_of_turn", "room_tone"],
       "act": {"labels": ["question", "command", "confirmation", "chatter", "statement"]},
       "addressee": {"labels": ["device", "other_person", "reading_aloud"], "beta": True, "note": "BETA"},
       "safety": {"labels": ["profanity.mild", "pii.leak"], "thresholds": {"profanity.mild": 0.3, "pii.leak": 0.6},
                  "beta": True, "note": "BETA, not a safety system"}}


class FakeRoom(arc_room.Room):
    def __init__(self):        # no onnxruntime session: summary() only
        self.cfg, self.frame_s, self.frames = CFG, 0.08, CFG["frames"]
        self.addr, self.act, self.safety = CFG["addressee"]["labels"], CFG["act"]["labels"], CFG["safety"]["labels"]
        self.thr = CFG["safety"]["thresholds"]
        self.beta = ["addressee", "safety"]


def _raw(T=10, pb=0.0, eot_last=0.9):
    F = np.zeros((T, 5), np.float32)
    F[:, 0] = pb
    F[:, 2] = 0.9
    F[-1, 3] = eot_last
    return {"frames": F, "addressee": np.tile([0.7, 0.2, 0.1], (T, 1)).astype(np.float32),
            "act": np.array([0.1, 0.8, 0.05, 0.03, 0.02], np.float32), "safety": np.array([0.1, 0.7], np.float32),
            "ref_on": False}


def test_summary_matches_arc_audio_room():
    r = FakeRoom().summary(_raw(pb=0.9))
    assert r["act"]["label"] == "command" and r["act"]["p"] == pytest.approx(0.8)
    assert r["addressee"]["label"] == "device" and r["addressee"]["beta"] is True
    assert r["safety"]["beta"] is True and r["safety"]["above_threshold"] == ["pii.leak"]
    assert r["end_of_turn"] == pytest.approx(0.9) and r["playback"] == 1.0 and r["live_speech"] == 1.0
    assert FakeRoom().summary(_raw(pb=0.2))["playback"] == 0.0


def test_no_room_model_gives_no_readout(monkeypatch):
    monkeypatch.setitem(arc_room.STATE, "room", None)
    assert arc_room.readout(np.zeros((5, 512), np.float32), np.zeros(8000, np.float32)) is None
    assert arc_room.health()["loaded"] is False


def test_a_v1_model_folder_has_no_room(tmp_path, monkeypatch):
    for k in ("room", "error", "load_s"):
        monkeypatch.setitem(arc_room.STATE, k, arc_room.STATE[k])
    monkeypatch.setitem(arc_room.STATE, "room", None)
    (tmp_path / "config.json").write_text('{"backbone": {}}')
    assert arc_room.load(tmp_path) is None and "v1" in arc_room.STATE["error"]
    assert arc_room.load(None) is None


def test_reference_is_sample_aligned_with_the_turn():
    es = arc_ear.EarStream("assistant", model=object())
    es.live = True
    es.refs.append((1.0, np.ones(1600, np.float32)))      # plays from ear time 1.0 s for 0.1 s
    r = es._ref_for(0.9, 4800)                            # the turn: 0.9 .. 1.2 s
    assert r is not None and r[:1600].sum() == 0 and r[1600:3200].sum() == 1600 and r[3200:].sum() == 0
    assert es._ref_for(2.0, 1600) is None                 # nothing we played overlaps it


def test_room_off_asks_libarc_for_no_tap(monkeypatch):
    s = arc_ear.EarSettings(ear_room="off")
    es = arc_ear.EarStream("assistant", s=s, model=type("M", (), {"L": None})())
    monkeypatch.setitem(arc_room.STATE, "room", object())
    assert es._room_kw() == {}
    es.cfg = arc_ear.EarSettings(ear_room="shadow")
    assert es._room_kw() == {"tap": True}


@pytest.fixture(scope="module")
def v2():
    if arcmeta.STATE.get("arc") is None:
        arcmeta.load()
    m = arcmeta.STATE.get("arc")
    if m is None:
        pytest.skip(f"Arc Transcriber Space not loaded: {arcmeta.STATE['error']}")
    if arc_room.STATE["room"] is None:
        pytest.skip(f"no v2 room read-outs: {arc_room.STATE['error']}")
    return m


def test_tap_is_the_decode_memo_and_room_reads_it(v2):
    x = np.frombuffer(FIX.read_bytes(), dtype="<i2").astype(np.float32) / 32768.0
    out = v2.transcribe(x, tap=True)
    tap = out["tap"]
    assert tap.ndim == 2 and tap.shape[1] == 512 and abs(tap.shape[0] - len(x) / 1280) <= 2
    r = arc_room.readout(tap, x)
    assert r["act"]["label"] in r["act"]["probs"] and abs(sum(r["act"]["probs"].values()) - 1) < 0.01
    assert r["addressee"]["beta"] is True and r["safety"]["beta"] is True and r["reference"] is False
    r2 = arc_room.readout(tap, x, x)                      # the turn is our own playback
    assert r2["reference"] is True and r2["playback"] >= r["playback"]


def test_final_words_carry_room_in_shadow(v2):
    x = np.frombuffer(FIX.read_bytes(), dtype="<i2")
    es = arc_ear.EarStream("assistant")
    msgs = []
    for i in range(0, len(x), 1280):
        msgs += es.feed_all(x[i:i + 1280].tobytes())
    msgs += es.flush_all()
    fin = [m for m in msgs if m["t"] == "words" and m.get("final")]
    assert fin and all("room" in m and m["room"]["safety"]["beta"] for m in fin)
    assert all(m["conf"] is None and m["alts"] == [] for m in fin)    # the shipped Director's slots stay empty
