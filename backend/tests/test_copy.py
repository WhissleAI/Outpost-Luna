"""Copy rules (docs/COPY.md): no emoji anywhere, and every spoken line is 20 words or fewer.

Scans frontend/src/story.js, data/academy/course.json and the backend's spoken lines (CAPCOM readbacks and status,
Houston, the guide's fallbacks, sim events and shift reports, session alerts, check-ride results)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app import director
from app.academy import content
from app.mission import capcom, sim

ROOT = Path(__file__).resolve().parents[2]
STORY = ROOT / "frontend/src/story.js"
COURSE = ROOT / "backend/data/academy/course.json"
SPOKEN_MAX = 20
# Emoji and pictographs (incl. the variation selector and joiner that build them). Plain typography (… “ ” · –) is fine.
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF\uFE0F\u200D\u20E3]")
BACKEND_COPY = ["app/mission/capcom.py", "app/mission/sim.py", "app/mission/nlu.py", "app/director.py",
                "app/session.py", "app/knowledge/answer.py", "app/knowledge/cards.py", "app/academy/routes.py",
                "app/academy/grade.py", "app/turn_router.py"]


def words(s: str) -> int:
    return len(s.split())


def strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)


# ---- no emoji --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", [STORY, COURSE, *(ROOT / "backend" / p for p in BACKEND_COPY)], ids=lambda p: p.name)
def test_no_emoji(path):
    bad = [(i + 1, line.strip()[:80]) for i, line in enumerate(path.read_text().splitlines()) if EMOJI.search(line)]
    assert not bad, f"emoji in {path.name}: {bad}"


# ---- story.js: on-screen budgets and the spoken templates ----------------------------------------------------------
def _js_block(name: str) -> str:
    src = STORY.read_text()
    m = re.search(rf"export const {name} = (\{{.*?\n\}}|\[.*?\n\]);", src, re.S)
    assert m, name
    return m.group(1)


def _quoted(block: str) -> list[str]:
    return [a or b for a, b in re.findall(r'"([^"]*)"|`([^`]*)`', block)]


def test_story_spoken_lines_short():
    for name in ("CAPCOM", "OFFER", "CALLBACKS", "LESSON_STORY", "MENTOR", "DEBRIEF"):
        for s in _quoted(_js_block(name)):
            # a template: count each ${…} as one word, and the CALLBACK lead-in ("Remember Lesson 4?") adds 3
            n = words(re.sub(r"\$\{[^}]*\}", "X", s)) + (3 if name == "CALLBACKS" else 0)
            assert n <= SPOKEN_MAX, f"{name}: {s!r} has {n} words"


def test_story_on_screen_budgets():
    for s in _quoted(_js_block("LESSON_BLURB")):
        assert words(s) <= 12, s
    for s in _quoted(_js_block("BEATS")):
        assert words(s) <= 12, s
    sub = re.search(r'sub: "([^"]*)"', _js_block("SCHOOL")).group(1)
    assert words(sub) <= 12
    for k in ("save", "random"):
        assert words(re.search(rf'{k}: "([^"]*)"', _js_block("CALLSIGN_COPY")).group(1)) <= 3


def test_credit_line_exact():
    assert 'export const CREDIT = "Inspired by NASA\'s Artemis program. Uses NASA open data; not endorsed by NASA.";' \
        in STORY.read_text()


# ---- course.json: everything CAPCOM says in a lesson -----------------------------------------------------------------
def test_course_spoken_lines_short():
    c = json.loads(COURSE.read_text())
    for l in c["lessons"]:
        lines = [l["brief"]]
        for s in l["steps"]:
            lines += [s["prompt"], s["success"], s["fail"],
                      s["fail"] + " Hint: " + s["hint"],          # academy/routes.py: the hint after two misses
                      "Time's up. " + s["hint"]]                  # a missed check-ride order
        for line in lines:
            assert words(line) <= SPOKEN_MAX, f"{l['id']}: {line!r} has {words(line)} words"
        assert words(l["title"]) <= 6 and len(l["title"]) <= 24, l["title"]   # fits 2 lines under a patch stop
        for s in l["steps"]:
            assert len(s["prompt"]) <= 90, f"{l['id']}: prompt over 90 characters: {s['prompt']!r}"
            assert "say it, or tap" not in s["prompt"].lower() and "or say it" not in s["prompt"].lower(), s["prompt"]
            if s["accept"]["type"] == "keywords" and s["accept"].get("all"):
                assert re.search(r'"[^"]+"', s["prompt"]), f"{l['id']}: a readback prompt keeps its quoted order"


def test_course_still_valid():
    assert content.check() == []


# ---- backend spoken lines ------------------------------------------------------------------------------------------
STATE = {"resources": {"power_pct": 54.2, "life_support_pct": 22, "dose_msv": 14.2, "dose_limit_msv": 50,
                       "dose_rate_msv_h": 0.35},
         "env": {"in_sun": False, "earth_visible": False, "next_comm_window_h": 31,
                 "storm": {"active": True, "name": "Real solar storm, May 2024"}},
         "loads": dict(sim.DEFAULT_LOADS), "alerts": []}


def _commands():
    for to in capcom.NAMES:
        for amt in ({"kind": "none"}, {"kind": "all"}, {"kind": "half"}, {"kind": "percent", "value": 40},
                    {"kind": "little", "value": 1}, {"kind": "delta", "value": 20}, {"kind": "delta", "value": -20}):
            yield {"type": "allocate", "to": to, "amount": amt}
            yield {"type": "allocate", "to": to, "amount": amt, "from": "life_support"}
    for task in capcom.TASK_SAY:
        yield {"type": "dispatch", "task": task, "target": "shackleton_floor"}
    yield from ({"type": "shelter", "on": True}, {"type": "shelter", "on": False}, {"type": "end_shift"},
                {"type": "confirm"}, {"type": "cancel"}, {"type": "call_houston"})
    for when in capcom.WHEN_SAY:
        yield {"type": "rule", "when": when, "then": {"type": "allocate", "to": "life_support", "amount": {"kind": "percent", "value": 40}}}


def test_capcom_lines_short():
    lines = [capcom.readback(c, STATE) for c in _commands()]
    for what in ("power", "oxygen", "dose", "storm", "comms", "all"):
        lines += [capcom.status(what, STATE, f"copy-{what}"), capcom.status(what, {"resources": {}, "env": {}})]
    lines += [capcom.houston("", STATE)[0], capcom.houston("", {**STATE, "env": {"earth_visible": True}})[0],
              capcom.houston("Houston, how much power do we have?", {**STATE, "env": {"earth_visible": True}})[0],
              capcom.status("all", None), *capcom.TERMS.values()]
    for line in lines:
        assert line and words(line) <= SPOKEN_MAX, f"{line!r} has {words(line)} words"


def test_guide_fallbacks_short_and_never_example_commands():
    lines = [director.FAR, director.NEAR, director.EARTHRISE, director.SAY_AGAIN, director.UNKNOWN, director.GUARD,
             director.MISSION, director.NO_MOMENT, director.NOT_STARTED,
             *(m[1] for m in director.MISCONCEPTIONS), *(t[2] for t in director.TOURS), *(s[2] for s in director.SOUNDS)]
    for line in lines:
        assert words(line) <= SPOKEN_MAX, line
    for fallback in (director.SAY_AGAIN, director.UNKNOWN, director.GUARD, director.NOT_STARTED):
        assert "“" not in fallback and '"' not in fallback and "try:" not in fallback.lower(), fallback


def test_sim_event_and_shift_lines_short():
    texts = []
    for site in [s["id"] for s in sim.sites()]:
        m = sim.new_mission(f"copy-{site}", site, 7)
        texts += [e["text"] for e in m.log]
        sim.apply_command(m, {"type": "dispatch", "task": "collect_ice"})
        for _ in range(40):
            r = sim.apply_command(m, {"type": "end_shift"})
            texts.append(r["say"])
            texts += [e["text"] for e in r["events"]]
            if m.over:
                break
    assert len(texts) > 20
    for t in texts:
        assert words(t) <= SPOKEN_MAX, f"{t!r} has {words(t)} words"


def test_session_alert_lines_short():
    src = (ROOT / "backend/app/session.py").read_text()
    lines = re.findall(r'text="([^"]+)"', src) + re.findall(r'line = \("([^"]+)"', src)
    assert lines
    for line in lines:
        assert words(line) <= SPOKEN_MAX, line


# ---- accuracy (docs/COPY.md "Accuracy"; feat/artemis-ref docs/ACCURACY_AUDIT.md) -------------------------------------
BANNED = [
    (r"Artemis III hasn.t landed|Artemis III, the first landing|first landing near the south pole", "Artemis III is a 2027 Earth-orbit test; the first landing is Artemis IV (planned)"),
    (r"\bG[1-5]\b|geomagnetic storm at", "at the Moon it is a solar particle storm (G/Kp are Earth's magnetic field)"),
    (r"real NASA data|NASA source", "over-claim: some data is from other agencies and papers; some tech is pretend"),
    (r"the plan is a shelter", "no NASA plan for a soil shelter; it is a studied idea"),
]


@pytest.mark.parametrize("path", [STORY, COURSE], ids=lambda p: p.name)
def test_no_outdated_or_overclaiming_copy(path):
    text = path.read_text()
    for pat, why in BANNED:
        m = re.search(pat, text)
        assert not m, f"{path.name}: {m.group(0)!r}: {why}"


def test_pretend_tech_label():
    src = STORY.read_text()
    assert 'export const PRETEND_TECH = "Pretend tech";' in src
    tip = re.search(r'export const PRETEND_TECH_TIP = "([^"]+)";', src).group(1)
    assert words(tip) == 10, tip
