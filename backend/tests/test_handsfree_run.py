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
    assert c.bad_unknowns == 0, out         # ... and it is attributed to that question (the live PASS rule)
    panel = [r for r in s.routes if r["text"] in ("open the comm panel", "back to my seat")]
    assert [r.get("intent") for r in panel] == ["panel_comm", "panel_back"], panel
    routes = [r for r in s.routes if r["outcome"] != "ignore"]
    assert {r["outcome"] for r in routes} >= {"navigate", "answer", "order", "question"}
    # The live echo path ran: on every patch screen our offer was heard back (echo) and the kid's "next", a few ms
    # after that echo's playback ended, still navigated on the first try (the RC looped here forever).
    patch = [r for r in s.routes if r["screen"] == "patch"]
    offers = [i for i, r in enumerate(patch) if r["reason"] == "echo" and r["text"] in hf.OFFER.values()]
    assert len(offers) == len(content.course()["lessons"]) - 1, patch
    assert all(patch[i + 1]["text"] == "next" and patch[i + 1]["outcome"] == "navigate" for i in offers), patch


def test_live_course_is_matched_by_lesson_id():
    """main_live joins the server's public course with the local answer keys by id, not by position."""
    full = content.course()
    public = {"lessons": [{k: v for k, v in L.items() if k != "steps"} for L in reversed(full["lessons"])]}
    joined = hf.with_course(public, full)
    keys = {L["id"]: L["steps"] for L in full["lessons"]}
    assert [L["id"] for L in joined["lessons"]] == [L["id"] for L in reversed(full["lessons"])]
    assert all(L["steps"] is keys[L["id"]] for L in joined["lessons"])
    with pytest.raises(SystemExit):
        hf.with_course({"lessons": [{"id": "no_such_lesson"}]}, full)


def test_course_order_is_the_current_one():
    """The script walks the course in its own order (next_lesson); this is the order the UI and the docs use."""
    assert [L["id"] for L in content.course()["lessons"]] == \
        ["moon", "history", "comms", "power", "radiation", "life", "checkride"]
