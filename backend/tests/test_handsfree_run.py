"""The whole app hands-free, no clicks (tools/handsfree_run.py in-process): call sign -> every lesson by voice ->
check ride -> mission -> orders -> end shift x3 -> debrief -> fly again, with room noise and our own echo mixed in
at every screen. Zero replies to noise; "I don't know that one yet" only for a real question."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import director, models_client, session as sessions
from app.academy import content, vocab
from app.mission import capcom, registry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import handsfree_run as hf  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()


def test_scripted_handsfree_run(capsys):
    from app.main import S, app
    lines: list[str] = []
    with TestClient(app) as http:
        clock = Clock()
        s = sessions.Session("hf-run", S["gaz"], S["index"], clock=clock, registry=registry)
        t = hf.InProc(s, http, clock)
        c = hf.Client(t, content.course(), S["gaz"], vocab, log=lines.append)

        async def go():
            await s.handle({"t": "hello", "mode": "academy"})
            await hf.script(c, shifts=3)
        asyncio.run(go())
    out = "\n".join(lines)
    if os.environ.get("HANDSFREE_TRACE"):   # the kid's turns + our lines, for replaying against older code
        Path(os.environ["HANDSFREE_TRACE"]).write_text(json.dumps({"turns": t.trace, "spoken": c.spoken}, indent=1))
        Path(os.environ["HANDSFREE_TRACE"]).with_suffix(".txt").write_text(out)
    print(out)
    assert c.qualified, out[-3000:]
    assert len(c.badges) == len(content.course()["lessons"]), c.badges
    assert c.mid and c.mscreen == "cabin", "fly again started a new shift"
    assert c.replies_to_noise == 0, out
    assert c.unknowns() <= 1, out           # only the one real question may get the honest fallback
    panel = [r for r in s.routes if r["text"] in ("open the comm panel", "back to my seat")]
    assert [r.get("intent") for r in panel] == ["panel_comm", "panel_back"], panel
    routes = [r for r in s.routes if r["outcome"] != "ignore"]
    assert {r["outcome"] for r in routes} >= {"navigate", "answer", "order", "question"}
