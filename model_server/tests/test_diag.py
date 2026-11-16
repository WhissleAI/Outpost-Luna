"""[#92] The model server's local metrics (app/diag.py, docs/DIAGNOSTICS.md): GET /metrics needs the token when one is
set, the ear's decode latency (partial vs final), RTF, queue wait and turns are counted, never the words."""
from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import arc_ear, arcmeta, decode_watchdog, diag
from app.main import app

CHUNK = 1280   # 80 ms


class FakeModel:
    """A scripted ear model (like tests/test_arc_ear.py's): the same text for any audio."""

    def __init__(self, text):
        self.text = text

    def transcribe(self, pcm, domain="assistant", no_events=False, no_bias=False, names=None):
        ws = self.text.split()
        words = [{"w": w, "t0": 0.2 + 0.3 * i, "t1": 0.45 + 0.3 * i} for i, w in enumerate(ws)]
        return {"utts": [{"t0": 0.0, "t1": len(pcm) / 16000, "text": self.text, "words": words, "tags": [], "act": None,
                          "intent": None, "directed_head": 0.9, "directed": True}], "names": [], "events": [], "ms": 1.0}


def run(es, pattern):
    rng = np.random.default_rng(1)
    for v in pattern:
        x = rng.standard_normal(CHUNK) * (0.2 if v else 0.0)
        es.feed_all((x * 32767).clip(-32768, 32767).astype("<i2").tobytes())

TOKEN = "model-server-token-abcdefghijklmnopqrstuvwxyz0123"


def test_same_file_as_the_backend():
    """One diagnostics module, two copies (separate packages in the desktop bundle): they must not drift."""
    here = Path(__file__).resolve().parents[1] / "app/diag.py"
    there = Path(__file__).resolve().parents[2] / "backend/app/diag.py"
    if not there.exists():
        pytest.skip("no backend checkout next to this model server")
    assert here.read_text() == there.read_text()


def test_metrics_endpoint_needs_the_token_when_one_is_set(monkeypatch):
    c = TestClient(app)
    assert c.get("/metrics").status_code == 200
    monkeypatch.setenv("LUNA_TOKEN", TOKEN)
    assert c.get("/metrics").status_code == 401
    assert c.get("/metrics", headers={"X-Luna-Token": "nope"}).status_code == 401
    r = c.get("/metrics", headers={"X-Luna-Token": TOKEN})
    assert r.status_code == 200
    d = r.json()
    assert {"counters", "histograms", "gauges", "rss_mb"} <= set(d) and "ear_sessions_open" in d["gauges"]


def c(name):
    return diag.METRICS.snapshot()["counters"].get(name, 0)


def h(name):
    return diag.METRICS.snapshot()["histograms"].get(name, {"n": 0})


def test_ear_decode_latency_rtf_and_turns_are_counted_without_words():
    said = "set the shields to forty percent"
    p0, f0, t0 = h("ear_decode_ms{kind=partial}")["n"], h("ear_decode_ms{kind=final}")["n"], c("ear_turns{end=silence}")
    es = arc_ear.EarStream(model=FakeModel(text=said))
    run(es, [0] * 3 + [1] * 12 + [0] * 10)
    assert h("ear_decode_ms{kind=partial}")["n"] > p0
    assert h("ear_decode_ms{kind=final}")["n"] == f0 + 1
    assert h("ear_rtf{kind=final}")["n"] >= 1 and h("ear_decode_ms{kind=final}")["p95"] is not None
    assert c("ear_turns{end=silence}") == t0 + 1
    assert said not in json.dumps(diag.METRICS.snapshot())


def test_queue_wait_and_decode_timeout_are_counted():
    q0, e0 = h("ear_queue_ms")["n"], c("errors{code=decode_timeout}")
    pool = ThreadPoolExecutor(max_workers=1)

    async def go():
        loop = asyncio.get_running_loop()
        assert await decode_watchdog.guarded(loop, pool, lambda: 7) == 7
        with pytest.raises(decode_watchdog.DecodeTimeout):
            await decode_watchdog.guarded(loop, pool, __import__("time").sleep, 0.3, limit=0.05)
    asyncio.run(go())
    pool.shutdown(wait=True)
    assert h("ear_queue_ms")["n"] >= q0 + 2
    assert c("errors{code=decode_timeout}") == e0 + 1


def test_model_reset_is_counted(monkeypatch):
    m = object()
    monkeypatch.setitem(arcmeta.STATE, "arc", m)
    monkeypatch.setitem(arcmeta.STATE, "resets", 0)
    r0 = c("model_resets{model=arc_ear}")
    assert arcmeta.reset_after_hang(m, "test", reload=lambda: None)
    assert c("model_resets{model=arc_ear}") == r0 + 1
