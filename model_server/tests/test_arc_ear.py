"""Arc ear (/v1/stream?ear=arc): message shapes with a fake Arc stream, and a live run on the bullseye fixture."""
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import arc_ear, arcmeta
from app.main import app

FIX = Path(__file__).resolve().parents[2] / "backend/tests/fixtures/bullseye_16k.s16le"
CHUNK = 1280   # 80 ms


class FakeArc:
    """Scripted Arc stream: partial words while voiced, a final on end_turn()."""

    def __init__(self, script):
        self.script, self.i, self.ctx, self.names, self.closed = script, 0, None, None, False

    def feed(self, x):
        out = self.script[self.i] if self.i < len(self.script) else {}
        self.i += 1
        return out

    def end_turn(self, wait=True, context=None):
        return {"transcript": [{"text": "shields to forty", "start": 0.0, "end": 0.9}]}

    def flush(self):
        return {}

    def set_context(self, **kw):
        self.ctx = kw

    def set_names(self, names):
        self.names = names

    def close(self):
        self.closed = True


def fake_stream(script):
    es = arc_ear.EarStream.__new__(arc_ear.EarStream)
    es.s, es.last_key, es.compute_s, es.audio_s = FakeArc(script), None, 0.0, 0.0
    es.vad, es.turns = arc_ear.Vad(), arc_ear.TurnTracker()
    return es


def pcm(voiced: bool) -> bytes:
    rng = np.random.default_rng(1)
    x = rng.standard_normal(CHUNK) * (0.2 if voiced else 0.0)
    return (x * 32767).clip(-32768, 32767).astype("<i2").tobytes()


def live(cc):
    return {"live": {"t": 0, "utt": {"command_complete": cc, "device_directed": 0.9}}}


def test_turn_start_words_eager_end_shapes():
    p = lambda t: {"transcript_partial": {"text": t, "final": False}, **live(0.7)}  # noqa: E731
    script = [{}, p("shields"), p("shields to"), p("shields to forty")] + [live(0.7)] * 12
    es = fake_stream(script)
    msgs = []
    for i in range(len(script)):
        msgs += es.feed_all(pcm(i < 4))
    tw = [m for m in msgs if m["t"] in ("words", "turn")]
    assert tw[0] == {"t": "turn", "state": "start", "text": "shields"}
    assert {"t": "words", "text": "shields to 40", "final": False} in tw      # written form
    states = [m["state"] for m in tw if m["t"] == "turn"]
    assert states == ["start", "eager", "end"]
    assert tw[-2] == {"t": "words", "text": "shields to 40", "final": True}
    assert tw[-1] == {"t": "turn", "state": "end", "text": "shields to 40"}
    # end at ~600 ms of silence after the last voiced chunk, eager before it
    assert es.turns.ends[0]["reason"] == "silence"
    assert 0.55 <= es.turns.ends[0]["at"] - es.turns.ends[0]["last_voice"] <= 0.75
    arc = [m for m in msgs if m["t"] == "arc"]
    assert arc and {"command_complete", "device_directed", "speaker", "act", "intent"} <= set(arc[0])


def test_resumed_after_eager_and_arc_pause_final():
    p = lambda t, cc=0.8: {"transcript_partial": {"text": t, "final": False}, **live(cc)}  # noqa: E731
    voiced = [1, 1, 0, 0, 0, 0, 1, 1, 0]
    script = [p("go"), p("go to"), live(0.8), live(0.8), live(0.8), live(0.8), p("go to the"), p("go to the rover"),
              {"transcript": [{"text": "go to the rover", "start": 0, "end": 1.0}]}]
    es = fake_stream(script)
    msgs = []
    for v in voiced:
        msgs += es.feed_all(pcm(bool(v)))
    states = [m["state"] for m in msgs if m["t"] == "turn"]
    assert states == ["start", "eager", "resumed", "end"]
    assert es.turns.ends[0]["reason"] == "arc_pause"
    assert [m for m in msgs if m["t"] == "words"][-1] == {"t": "words", "text": "go to the rover", "final": True}


def test_no_turn_for_silence_only():
    es = fake_stream([live(0.1)] * 20)
    msgs = []
    for _ in range(20):
        msgs += es.feed_all(pcm(False))
    assert not [m for m in msgs if m["t"] in ("words", "turn")]


def test_decoder_context_from_context_frame():
    from app.stream_context import StreamContext
    es = fake_stream([])
    ack = StreamContext().update({"t": "context", "names": ["Shackleton"], "terms": ["shields"], "topic": "moon base"}, es)
    assert es.s.ctx["names"] == ["Shackleton"] and es.s.ctx["terms"] == ["shields"] and es.s.ctx["topic"] == "moon base"
    assert es.s.names == ["Shackleton"]
    assert ack["terms_to_arc"] is True and ack["topic_to_arc"] is True


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_ear_unavailable_is_reported(client, monkeypatch):
    monkeypatch.setitem(arcmeta.STATE, "decoder", False)
    with client.websocket_connect("/v1/stream?ear=arc") as ws:
        m = ws.receive_json()
        assert m["t"] == "ear" and m["available"] is False and "decoder" in m["reason"]


@pytest.mark.skipif(not FIX.exists(), reason="fixture missing")
def test_live_bullseye_through_arc_ear(client):
    if True:
        c = client
        h = c.get("/health").json()["models"]
        if not h.get("arc_ear", {}).get("available"):
            pytest.skip(f"Arc ear not loaded: {arcmeta.STATE['error']}")
        x = FIX.read_bytes() + bytes(2 * 16000 * 2)    # + 2 s silence
        with c.websocket_connect("/v1/stream?ear=arc") as ws:
            assert ws.receive_json()["t"] == "ear"
            ws.send_text(json.dumps({"t": "context", "names": ["Bullseye"], "topic": "moon"}))
            got = []
            for i in range(0, len(x), 2 * CHUNK):
                ws.send_bytes(x[i:i + 2 * CHUNK])
            ws.send_text(json.dumps({"t": "stop"}))
            while True:
                try:
                    got.append(ws.receive_json())
                except Exception:  # noqa: BLE001 (closed)
                    break
                if got[-1].get("t") == "turn" and got[-1]["state"] == "end":
                    break
    words = [m for m in got if m["t"] == "words"]
    turns = [m["state"] for m in got if m["t"] == "turn"]
    assert words and words[-1]["final"] and "bull" in words[-1]["text"].lower()
    assert turns[0] == "start" and turns[-1] == "end"
    assert any(m["t"] == "context_ack" and m["terms_to_arc"] for m in got)


def test_final_uses_arcs_written_form_with_linked_names():
    t = arc_ear.TurnTracker()
    out = {"transcript": [{"text": "can we land near malapart"}], "transcript_written": [{"text": "can we land near Malapert"}]}
    msgs = t.on_arc(out)
    assert msgs[-2] == {"t": "words", "text": "can we land near Malapert", "final": True}
    # counts disagree -> text-only written form
    assert arc_ear.with_written({"transcript": [{"text": "a"}], "transcript_written": []}) == [{"text": "a"}]
