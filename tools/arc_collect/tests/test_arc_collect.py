"""Dry-run tests for the Arc recording kit. No audio device, no speech engine, no sound: sounddevice is replaced by
fakesd.FakeSoundDevice (an in-memory loopback that "plays" into a fake mic with a delay, a low-pass and attenuation).

    uv run --with pytest --with numpy --with soundfile python -m pytest tools/arc_collect/tests -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

KIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(KIT))

import align  # noqa: E402
import arc_collect  # noqa: E402
import devices as dv  # noqa: E402
from fakesd import DEVICES, FakeSoundDevice  # noqa: E402
from session import Recorder, Timeline, seg_entry, validate_manifest  # noqa: E402


def _run_chirp(tmp_path, delay_s, rate=48000, atten=0.3, noise_db=-60.0, blocksize=512):
    sd = FakeSoundDevice(delay_s=delay_s, atten=atten, noise_db=noise_db, rates=(rate,))
    tl = Timeline(rate)
    tl.silence(0.5)
    ch = align.chirp(rate)
    c = tl.add(ch, kind="chirp", gain_db=-12.0)
    tl.silence(1.5)
    din, dout = sd.query_devices(0), sd.query_devices(1)
    res = Recorder(sd, tl, rate, din, dout, 2, tmp_path, blocksize=blocksize).run()
    mic, sr = sf.read(str(tmp_path / "mic.wav"), dtype="float32")
    return align.find_delay(mic, ch * c["gain"], c["start"], sr), res


@pytest.mark.parametrize("delay_s,rate,atten,noise_db", [
    (0.0237, 48000, 0.3, -60.0),
    (0.0123, 48000, 0.05, -50.0),       # quiet speakers, noisier room
    (0.0871, 44100, 0.2, -55.0),        # another device rate
    (0.2503, 48000, 0.1, -55.0),        # a Bluetooth-sized round trip
])
def test_chirp_recovers_the_loopback_delay_within_1ms(tmp_path, delay_s, rate, atten, noise_db):
    r, res = _run_chirp(tmp_path, delay_s, rate, atten, noise_db)
    assert r["reliable"], r
    assert abs(r["delay_s"] - delay_s) < 0.001, (r, delay_s)
    assert res["frames"] == sf.info(str(tmp_path / "ref.wav")).frames


def test_find_delay_flags_a_deaf_mic():
    sr = 48000
    ch = align.chirp(sr)
    mic = np.random.default_rng(0).normal(0, 1e-3, sr * 2).astype(np.float32)
    assert not align.find_delay(mic, ch, 0, sr)["reliable"]


def test_ref_wav_is_exactly_what_was_played(tmp_path):
    rate = 48000
    sd = FakeSoundDevice(delay_s=0.03, rates=(rate,))
    tl = Timeline(rate)
    rng = np.random.default_rng(1)
    for g in (0.0, -6.0, -12.0):
        tl.add((rng.normal(0, 0.1, rate // 2)).astype(np.float32), gain_db=g, kind="x")
        tl.silence(0.3)
    Recorder(sd, tl, rate, sd.query_devices(0), sd.query_devices(1), 2, tmp_path).run()
    ref, _ = sf.read(str(tmp_path / "ref.wav"), dtype="float32")
    want = tl.render(0, len(ref))
    assert np.array_equal(ref, want)
    mic, _ = sf.read(str(tmp_path / "mic.wav"), dtype="float32")
    d = int(round(0.03 * rate))
    c = np.corrcoef(mic[d: d + rate], ref[: rate])[0, 1]
    assert c > 0.8                      # the mic hears the reference, delayed


def test_resample_file_keeps_alignment(tmp_path):
    for sr in (48000, 44100):
        x = np.zeros(sr * 3, np.float32)
        at = int(1.2345 * sr)
        x[at] = 0.9
        sf.write(str(tmp_path / "a.wav"), x, sr, subtype="FLOAT")
        n = align.resample_file(str(tmp_path / "a.wav"), str(tmp_path / "b.wav"), 16000, block=50000)
        y, r = sf.read(str(tmp_path / "b.wav"), dtype="float32")
        assert r == 16000 and len(y) == n
        assert abs(len(y) - len(x) * 16000 / sr) <= 2
        assert abs(int(np.argmax(np.abs(y))) - at * 16000 / sr) <= 1.0
        # the streaming version matches the whole-array one
        z = align.resample(x, sr, 16000)
        assert np.max(np.abs(z[: len(y)] - y)) < 2e-4


def test_echo_dry_run_writes_a_valid_manifest(tmp_path, capsys):
    rc = arc_collect.main(["echo", "--dry-run", "--yes", "--minutes", "1.2", "--out", str(tmp_path)], inp=_no_input)
    assert rc == 0
    d = next(tmp_path.glob("echo-*"))
    m = json.loads((d / "manifest.json").read_text())
    assert validate_manifest(m, d) == []
    assert m["status"] == "complete" and m["dry_run"] is True
    assert m["latency"]["measured_roundtrip_s"] == pytest.approx(0.0237, abs=0.001)
    kinds = {s["kind"] for s in m["segments"]}
    assert {"chirp", "noise_floor", "voice_pack", "os_voice"} <= kinds
    assert len(m["levels_db"]) == 4
    assert all(k in m["machine"] for k in ("os", "os_version", "model"))
    blob = json.dumps(m).lower()
    assert "serial" not in blob and str(Path.home()).lower() not in blob
    for f in ("mic.wav", "ref.wav", "mic_16k.wav", "ref_16k.wav", "README.txt"):
        assert (d / f).exists()
    out = capsys.readouterr().out
    assert "PLAY SOUND" in out and "minutes" in out


def test_ctrl_c_midway_keeps_the_recording_and_a_valid_manifest(tmp_path):
    rate = 48000
    sd = FakeSoundDevice(rates=(rate,))
    ns = arc_collect.parser().parse_args(["echo", "--dry-run", "--minutes", "1"])
    notes = []
    tl, chirps, ch = arc_collect.build_echo(ns, rate, __import__("random").Random(1), notes)
    din, dout = sd.query_devices(0), sd.query_devices(1)
    m = arc_collect.base_manifest("echo", ns, sd, din, dout, rate, 2, [])
    m["notes"] = notes

    def tick(pos):
        if pos > 20 * rate:
            raise KeyboardInterrupt

    res = Recorder(sd, tl, rate, din, dout, 2, tmp_path).run(on_tick=tick, tick_s=0.001)
    assert res["interrupted"] and 0 < res["frames"] < tl.total
    m = arc_collect.finalize(tmp_path, m, tl, res, chirps, ch)
    assert m["status"] == "stopped_early"
    assert validate_manifest(m, tmp_path) == []
    assert m["segments"][-1]["end_frame"] <= res["frames"]
    assert sf.info(str(tmp_path / "mic.wav")).frames == res["frames"]


def _answers(*xs):
    it = iter(xs)

    def inp(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return inp


def _no_input(prompt=""):
    raise EOFError


@pytest.mark.parametrize("answers", [
    (),                                   # no answer at all (EOF)
    ("",),
    ("maybe",),
    ("child", "yes"),                     # a parent must type I AGREE
    ("child", "I AGREE", "no"),           # and agree to share
    ("adult", "i agree please"),
])
def test_consent_gate_blocks(answers):
    assert arc_collect.consent_gate(_answers(*answers)) is None


def test_consent_gate_accepts_and_records_who():
    c = arc_collect.consent_gate(_answers("child", "I agree", "I AGREE"))
    assert c["speaker"] == "child" and c["parent_present_and_agreed"] and c["share_with_arc_team"]
    c = arc_collect.consent_gate(_answers("adult", "I AGREE"))
    assert c["speaker"] == "adult" and c["parent_present_and_agreed"] is None


def test_guided_without_consent_opens_no_stream_and_saves_nothing(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(arc_collect, "get_sd", lambda *a, **k: opened.append(1) or FakeSoundDevice())
    rc = arc_collect.main(["guided", "--dry-run", "--yes", "--out", str(tmp_path)], inp=_answers("child", "no"))
    assert rc == 2 and opened == [] and list(tmp_path.iterdir()) == []


def test_guided_dry_run_labels_every_prompt(tmp_path):
    rc = arc_collect.main(["guided", "--dry-run", "--yes", "--minutes", "2", "--out", str(tmp_path)],
                          inp=_answers("adult", "I AGREE"))
    assert rc == 0
    d = next(tmp_path.glob("guided-*"))
    m = json.loads((d / "manifest.json").read_text())
    assert validate_manifest(m, d) == []
    assert json.loads((d / "consent.json").read_text())["agreed"] is True
    labels = {p["label"] for p in m["prompts"]}
    assert labels <= {"addressed", "not_addressed", "barge_in"} and len(m["prompts"]) >= 6
    for p in m["prompts"]:
        assert p["say"] and p["now_s"] >= p["ready_s"]
        assert "shown_now_s" in p                      # the screen showed it, on the stream clock
        if p["label"] == "barge_in":                  # the app was talking during the window
            assert p["app_line"]["start_s"] <= p["window_start_s"]


def test_render_lines_dry_run(tmp_path):
    rc = arc_collect.main(["render-lines", "--dry-run", "--max-lines", "4", "--out", str(tmp_path)])
    assert rc == 0
    d = next(tmp_path.glob("render-lines-*"))
    m = json.loads((d / "manifest.json").read_text())
    assert m["status"] == "complete" and len(m["renders"]) == 4 * len(m["voices"])
    for r in m["renders"]:
        assert sf.info(str(d / r["file_16k"])).samplerate == 16000


def test_check_dry_run(tmp_path, capsys):
    assert arc_collect.main(["check", "--dry-run", "--out", str(tmp_path)]) == 0
    assert arc_collect.main(["check", "--dry-run", "--fake-denied", "--no-voices", "--out", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "pure digital silence" in out and "Privacy" in out


def test_rate_mismatch_and_bluetooth():
    devs = [dict(DEVICES[0], default_samplerate=44100.0), DEVICES[1], DEVICES[2]]
    sd = FakeSoundDevice(devices=devs, rates=(44100,))
    rate, notes = dv.choose_rate(sd, sd.query_devices(0), sd.query_devices(1), 2, 48000)
    assert rate == 44100 and any("44100" in n for n in notes)
    assert dv.is_bluetooth("Sam's AirPods Pro") and dv.is_bluetooth("Headphones (WH-1000XM4 Stereo)")
    assert dv.looks_builtin_speaker("MacBook Pro Speakers") and dv.looks_builtin_speaker("Speakers (Realtek(R) Audio)")
    assert not dv.looks_builtin_speaker("BlackHole 2ch")
    assert dv.scrub_name("Sam's AirPods Pro") == "Owner's AirPods Pro"
    assert dv.scrub_name("Alex’s iPhone Microphone") == "Owner's iPhone Microphone"


def test_echo_refuses_bluetooth_speakers_without_yes(tmp_path, monkeypatch):
    monkeypatch.setattr(arc_collect, "get_sd", lambda *a, **k: FakeSoundDevice(default=(0, 2)))
    rc = arc_collect.main(["echo", "--dry-run", "--yes", "--out", str(tmp_path)], inp=_answers("no"))
    assert rc == 2 and list(tmp_path.iterdir()) == []


def test_yes_needs_dry_run():
    with pytest.raises(SystemExit):
        arc_collect.main(["echo", "--yes"])


def test_seg_entry_cuts_at_the_recording_end():
    tl = Timeline(1000)
    s = tl.add(np.ones(500, np.float32), kind="x", text="hi")
    assert seg_entry(s, 1000, 200, 0)["truncated"] is True
    assert seg_entry(tl.add(np.ones(10, np.float32), kind="y"), 1000, 200, 1) is None
