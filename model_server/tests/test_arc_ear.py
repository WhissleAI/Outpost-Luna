"""The ear (/v1/stream?ear=arc, Arc Transcriber Space): turn logic with a fake model, and live runs on REAL voices
(the Artemis II crew audio: the model is trained to ignore synthetic TTS, so real voices are the test)."""
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import arc_ear, arcmeta
from app.main import app

DATA = Path(__file__).resolve().parents[2] / "backend/data"
CHUNK = 1280   # 80 ms
# 7 s of Reid Wiseman on Artemis II (NASA audio, art002a000025-reid-tourist.mp3, 0-7 s, 16 kHz s16le): a REAL voice
FIX = Path(__file__).resolve().parents[2] / "backend/tests/fixtures/crew_orientale_16k.s16le"


class FakeModel:
    """Scripted Arc Transcriber Space: transcribe() returns the text for the audio length it is given."""

    def __init__(self, text="set the shields to forty percent", names=None, directed=0.93, events=None, by_len=None):
        self.text, self.names_out, self.directed, self.events, self.by_len = text, names or [], directed, events, by_len
        self.calls, self.names_seen = [], []

    def transcribe(self, pcm, domain="assistant", no_events=False, no_bias=False, names=None):
        self.calls.append({"n": len(pcm), "partial": no_events})
        self.names_seen.append(names)
        text = self.by_len(len(pcm)) if self.by_len else self.text
        ws = text.split()
        words = [{"w": w, "t0": 0.2 + 0.3 * i, "t1": 0.45 + 0.3 * i} for i, w in enumerate(ws)]
        utts = [{"t0": 0.0, "t1": len(pcm) / 16000, "text": text, "words": words, "tags": [], "act": None,
                 "intent": None, "directed_head": self.directed, "directed": self.directed >= 0.5}] if text else []
        return {"utts": utts, "names": [] if no_events else self.names_out,
                "events": [] if no_events else (self.events or []), "ms": 1.0}


def pcm(voiced: bool, seed=1) -> bytes:
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(CHUNK) * (0.2 if voiced else 0.0)
    return (x * 32767).clip(-32768, 32767).astype("<i2").tobytes()


def run(es, pattern):
    msgs = []
    for v in pattern:
        msgs += es.feed_all(pcm(bool(v)))
    return msgs


def test_turn_start_words_arc_end_order():
    m = FakeModel()
    es = arc_ear.EarStream(model=m)
    msgs = run(es, [0] * 3 + [1] * 12 + [0] * 10)
    kinds = [(x["t"], x.get("state"), x.get("final")) for x in msgs]
    assert kinds[0] == ("turn", "start", None)
    assert ("words", None, False) in kinds
    # the segment's arc read comes BEFORE the final words and the turn end (the session gates the turn on it)
    assert kinds[-3:] == [("arc", None, None), ("words", None, True), ("turn", "end", None)]
    fin = msgs[-2]
    assert fin["text"] == "set the shields to 40%" and fin["spoken"] == "set the shields to forty percent"
    assert msgs[-3]["directed_head"] == 0.93 and msgs[-3]["device_directed"] == arc_ear.app_dd(0.93) and msgs[-3]["directed"] is True and msgs[-3]["speech"] is True
    assert m.calls[-1]["partial"] is False and any(c["partial"] for c in m.calls[:-1])
    end = es.ends[0]
    assert end["reason"] == "silence" and 0.45 <= end["at"] - end["last_voice"] <= 0.6


def test_tts_echo_or_noise_is_not_a_turn_but_events_go_out():
    """The model hears no words (TTS leaking into the mic, a door slam): no turn, no words; the arc read still goes."""
    m = FakeModel(text="", events=[{"label": "scene.door", "t0": 0.1, "t1": 0.4, "p": 0.8},
                                   {"label": "meta.channel.telephone", "t0": 0, "t1": 1, "p": 0.99}])
    es = arc_ear.EarStream(model=m)
    msgs = run(es, [1] * 10 + [0] * 10)
    assert not [x for x in msgs if x["t"] in ("words", "turn")]
    arc = [x for x in msgs if x["t"] == "arc"]
    assert len(arc) == 1 and arc[0]["speech"] is False
    assert arc[0]["audio_events"] == [{"label": "scene.door", "t0": 0.1, "t1": 0.4, "p": 0.8}]   # meta.* left out


def test_no_turn_for_silence_only():
    m = FakeModel()
    es = arc_ear.EarStream(model=m)
    assert run(es, [0] * 30) == [] and m.calls == []


def test_linked_names_replace_the_heard_words():
    names = [{"t0": 0.8, "t1": 1.35, "tag": "entity.mention.mission", "heard": "artemis two", "entity": "Artemis II",
              "kb_index": 0, "state": "linked", "p": 0.97, "src": "decoder", "via": None, "show": True},
             {"t0": 1.4, "t1": 1.6, "tag": "entity.mention.lunar_feature", "heard": "tie co", "entity": None,
              "kb_index": -1, "state": "abstain", "p": 0.4, "src": "decoder", "via": None, "show": True}]
    m = FakeModel(text="when did artemis two fly", names=names)
    es = arc_ear.EarStream(model=m, names=[{"name": "Artemis II", "kind": "mission", "aliases": ["Artemis 2"]}])
    msgs = run(es, [1] * 8 + [0] * 10)
    fin = [x for x in msgs if x["t"] == "words" and x["final"]][0]
    assert fin["text"] == "when did Artemis II fly"
    assert fin["names"][0] == {"heard": "artemis two", "entity": "Artemis II", "state": "linked", "p": 0.97,
                               "tag": "entity.mention.mission", "kind": "mission"}
    assert fin["names"][1]["state"] == "abstain" and fin["names"][1]["entity"] is None
    assert m.names_seen[-1] == [{"name": "Artemis II", "kind": "mission", "aliases": ["Artemis 2"]}]


def test_names_list_from_the_context_frame_is_capped_and_kinded():
    from app.stream_context import StreamContext
    es = arc_ear.EarStream(model=FakeModel())
    names = ["Shackleton"] + [{"name": f"Place {i}", "kind": "site"} for i in range(60)]
    ack = StreamContext().update({"t": "context", "names": names}, es)
    assert ack["names_to_arc"] is True
    assert len(es.names) == 40 and es.names[0] == {"name": "Shackleton", "kind": "place"}


def test_end_turn_closes_now_and_partial_text_survives_an_empty_final():
    state = {"n": 0}

    def by_len(n):          # partials hear "go to the rover"; the final (whole segment) hears nothing
        state["n"] += 1
        return "go to the rover" if state["n"] == 1 else ""
    es = arc_ear.EarStream(model=FakeModel(by_len=by_len))
    msgs = run(es, [1] * 9)
    msgs += es.end_turn_all()
    assert [x.get("state") for x in msgs if x["t"] == "turn"] == ["start", "end"]
    assert [x for x in msgs if x["t"] == "words"][-1]["text"] == "go to the rover"
    assert es.ends[0]["reason"] == "end_turn"


def test_metadata_only_mode_emits_only_arc():
    es = arc_ear.EarStream(model=FakeModel(), metadata_only=True)
    msgs = run(es, [1] * 10 + [0] * 10)
    assert [x["t"] for x in msgs] == ["arc"]


def test_display_text_written_form():
    u = {"text": "move twenty percent to the rover", "words": []}
    assert arc_ear.display_text(u, []) == "move 20% to the rover"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_ear_unavailable_is_reported(client, monkeypatch):
    monkeypatch.setitem(arcmeta.STATE, "arc", None)
    monkeypatch.setitem(arcmeta.STATE, "error", "not loaded (test)")
    with client.websocket_connect("/v1/stream?ear=arc") as ws:
        m = ws.receive_json()
        assert m["t"] == "ear" and m["available"] is False and "not loaded" in m["reason"]


def test_live_real_crew_voice_links_a_name(client):
    """Reid Wiseman, Artemis II (real voice): "I'm just gonna take out Orientale for a second" -> linked."""
    if not client.get("/health").json()["models"]["arc_ear"]["available"]:
        pytest.skip(f"Arc Transcriber Space not loaded: {arcmeta.STATE['error']}")
    x = FIX.read_bytes() + bytes(2 * 16000)
    with client.websocket_connect("/v1/stream?ear=arc") as ws:
        assert ws.receive_json()["t"] == "ear"
        assert ws.receive_json()["t"] == "emotion"
        ws.send_text(json.dumps({"t": "context", "names": [
            {"name": "Orientale Basin", "kind": "lunar_feature", "aliases": ["Orientale", "Mare Orientale"]},
            {"name": "Hertzsprung", "kind": "lunar_feature"}, {"name": "Reid Wiseman", "kind": "crew"}]}))
        got = [ws.receive_json()]
        for i in range(0, len(x), 2 * CHUNK):
            ws.send_bytes(x[i:i + 2 * CHUNK])
        ws.send_text(json.dumps({"t": "stop"}))
        while True:
            try:
                got.append(ws.receive_json())
            except Exception:  # noqa: BLE001 (closed)
                break
    assert got[0]["t"] == "context_ack" and got[0]["names_to_arc"]
    fin = [m for m in got if m["t"] == "words" and m["final"]]
    assert fin, got
    text = " ".join(m["text"] for m in fin)
    assert "zoom" in text.lower() and "Orientale Basin" in text
    assert any(n["entity"] == "Orientale Basin" and n["state"] == "linked" for m in fin for n in m["names"])
    arc = [m for m in got if m["t"] == "arc"]
    assert arc and all(m["device_directed"] is not None and m["device_directed"] < 0.5 for m in arc)   # crew talk


def test_start_comes_before_the_arc_read_when_only_the_final_has_words():
    """A client resets its per-turn device-directed read on "start" (frontend/src/voice.js): start must come first."""
    es = arc_ear.EarStream(model=FakeModel(), s=arc_ear.EarSettings(ear_partial_every_s=0))
    msgs = run(es, [1] * 6 + [0] * 10)
    assert [(x["t"], x.get("state")) for x in msgs] == [("turn", "start"), ("arc", None), ("words", None),
                                                         ("turn", "end")]


def test_wordless_segment_has_no_device_directed_read():
    """Real noise beds read 0.6-0.9 on the head with no words: a wordless segment must not look directed."""
    es = arc_ear.EarStream(model=FakeModel(text="", directed=0.9))
    arc = [x for x in run(es, [1] * 10 + [0] * 10) if x["t"] == "arc"]
    assert arc[0]["device_directed"] is None and arc[0]["directed"] is None and arc[0]["speech"] is False


def test_directed_head_is_mapped_onto_the_router_scale():
    f = arc_ear.app_dd
    assert f(None) is None and f(0.0) == 0.0 and f(1.0) == 1.0
    assert f(0.05) == 0.5 and f(0.5) == 0.7          # knee -> DD_MIN, strong_at -> DD_STRONG (turn_router.py)
    xs = [f(i / 100) for i in range(101)]
    assert xs == sorted(xs)                           # monotonic


# ---- "show me the south pole" -> "South North Pole" (0.3.0): a partial-span link that contradicts its neighbour ----
def _w(*pairs):
    return [{"w": w, "t0": a, "t1": b} for w, a, b in pairs]


SOUTH = [{"text": "Show me the South Pole", "words": _w(("Show", 0.1, 0.3), ("me", 0.3, 0.4), ("the", 0.4, 0.5),
                                                      ("South", 0.5, 0.8), ("Pole", 0.8, 1.1))}]


def test_guard_abstains_a_tail_link_that_contradicts_the_word_before_it():
    names = [{"t0": 0.8, "t1": 1.1, "heard": "Pole", "entity": "North Pole", "state": "linked", "p": 0.98, "tag": None}]
    g = arc_ear.guard_names(names, SOUTH)
    assert g[0]["state"] == "abstain"
    assert arc_ear.display_text(SOUTH[0], g) == "Show me the South Pole"      # was "Show me the South North Pole"


def test_guard_keeps_links_that_fit():
    the_pole = [{"text": "Show me the Pole", "words": _w(("Show", 0.1, 0.3), ("me", 0.3, 0.4), ("the", 0.4, 0.5),
                                                       ("Pole", 0.5, 0.8))}]
    ok = [
        ({"t0": 0.5, "t1": 0.8, "heard": "Pole", "entity": "North Pole", "state": "linked", "p": 0.9}, the_pole),  # stop word
        ({"t0": 0.5, "t1": 1.1, "heard": "South Pole", "entity": "South Pole", "state": "linked", "p": 1.0}, SOUTH),  # whole
        ({"t0": 0.5, "t1": 0.8, "heard": "Shackleton", "entity": "Shackleton crater", "state": "linked", "p": 0.97},
         [{"text": "fly to Shackleton", "words": _w(("fly", 0.1, 0.3), ("to", 0.3, 0.5), ("Shackleton", 0.5, 0.8))}]),
    ]
    for n, utts in ok:
        assert arc_ear.guard_names([n], utts)[0]["state"] == "linked", n


def test_stream_final_shows_south_pole_and_does_not_link_north():
    m = FakeModel(text="Show me the South Pole",
                  names=[{"t0": 1.4, "t1": 1.65, "heard": "Pole", "entity": "North Pole", "state": "linked", "p": 0.97,
                          "tag": None}])
    es = arc_ear.EarStream(model=m, names=[{"name": "North Pole", "kind": "lunar_feature"}])
    msgs = run(es, [0] * 3 + [1] * 14 + [0] * 10)
    fin = [x for x in msgs if x["t"] == "words" and x["final"]][0]
    assert fin["text"] == "Show me the South Pole"
    assert [n["state"] for n in fin["names"]] == ["abstain"]


def test_partials_come_often_enough_to_read_as_streaming():
    # the old back-off (2x the decode cost, every 0.5 s) gave a 1.3 s command one partial at ~0.7 s and the next just
    # before the final; with the defaults now a 1.1 s voiced stretch gets >= 3 partials
    assert arc_ear.ear_settings.ear_partial_every_s <= 0.3 and arc_ear.ear_settings.ear_partial_backoff <= 1.5
    m = FakeModel(by_len=lambda n: " ".join(["word"] * max(1, n // 6000)))
    es = arc_ear.EarStream(model=m)
    msgs = run(es, [0] * 3 + [1] * 14 + [0] * 10)
    assert len([x for x in msgs if x["t"] == "words" and not x["final"]]) >= 3


def test_guard_widens_a_head_link_over_the_rest_of_the_name():
    utts = [{"text": "Tell me about Artemis two", "words": _w(("Tell", 0.1, 0.3), ("me", 0.3, 0.4), ("about", 0.4, 0.6),
                                                             ("Artemis", 0.6, 1.0), ("two", 1.0, 1.2))}]
    names = [{"t0": 0.6, "t1": 1.0, "heard": "Artemis", "entity": "Artemis II", "state": "linked", "p": 0.99}]
    g = arc_ear.guard_names(names, utts)
    assert g[0]["state"] == "linked" and g[0]["heard"] == "Artemis two" and g[0]["t1"] == 1.2
    assert arc_ear.display_text(utts[0], g) == "Tell me about Artemis II"      # was "Tell me about Artemis II two"
