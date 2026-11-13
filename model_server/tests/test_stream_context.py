"""The {"t":"context"} side channel on WS /v1/stream (app/stream_context.py), without loading Arc."""
from app.stream_context import StreamContext


class FakeArcStream:
    def __init__(self):
        self.names = None

    def set_names(self, names):
        self.names = names


class FakeMeta:
    def __init__(self):
        self.s = FakeArcStream()
        self.audio_s = 3.25


def test_names_reach_arc_and_terms_are_recorded():
    ms, ctx = FakeMeta(), StreamContext()
    ack = ctx.update({"t": "context", "names": ["Shackleton", {"name": "Houston"}], "terms": ["mSv"],
                      "mission": {"power_pct": 72}}, ms)
    assert ms.s.names == ["Shackleton", {"name": "Houston"}]
    assert ack == {"t": "context_ack", "v": 1, "names": 2, "terms": 1, "names_to_arc": True, "terms_to_arc": False,
                   "at_audio_s": 3.25}
    out = ctx.decorate({"t": "arc", "act": None})
    assert out["context"] == {"v": 1, "names": 2, "terms": 1, "telemetry": {"power_pct": 72}}


def test_without_arc_stream_context_is_recorded_only():
    ctx = StreamContext()
    ack = ctx.update({"t": "context", "names": ["Shackleton"], "telemetry": [{"power": 70}, {"power": 69}]})
    assert ack["names_to_arc"] is False and ack["at_audio_s"] is None
    assert [f["frame"] for f in ctx.frames] == [{"power": 70}, {"power": 69}]
    assert ctx.decorate({"t": "emotion"}) == {"t": "emotion"}
