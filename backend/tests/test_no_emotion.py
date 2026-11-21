"""[D6] "No emotion" is checkable in code (docs/BRAIN.md §6, docs/BRAIN_SIGNALS_AUDIT.md R7, D6).

The app never infers, stores or uses a kid's feelings: no affect stream is relayed or accepted, no line or voice style
changes with one, and nothing in the brain holds one. The EU AI Act (Art 5(1)(f)) prohibits emotion recognition in
education institutions, so this guard fails the build if the plumbing comes back.

The only allowed mentions sit on a line marked `D6`: the drop list (session.NO_AFFECT) and the learned Director's
frozen input columns (director_model/features.py: the shipped weights expect them; nothing feeds them).
"""
import asyncio
import re
from pathlib import Path

from app import session as sessions, steering
from app.director_model import features

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [*(ROOT / "backend" / "app").rglob("*.py"), *(ROOT / "frontend" / "src").rglob("*.js")]
WORDS = re.compile(r"emotion|\baffect\b|sentiment", re.I)


def test_no_affect_plumbing_in_the_app_source():
    hits = []
    for f in SOURCES:
        if "node_modules" in f.parts:
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if WORDS.search(line) and "D6" not in line:
                hits.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()[:120]}")
    assert not hits, "affect plumbing is back (D6):\n" + "\n".join(hits)


def test_sources_were_scanned():
    names = {f.name for f in SOURCES}
    assert {"session.py", "director.py", "steering.py", "brain.js", "main.js", "voice.js"} <= names


def test_session_drops_an_affect_stream():
    s = sessions.Session("t-d6")
    for t in sorted(sessions.NO_AFFECT):
        asyncio.run(s.handle({"t": t, "label": "frustrated", "p": 0.9}))
    assert not s.outbox and not s.history
    assert all("emo" not in k for k in s.belief["kid"])


def test_style_has_no_affect_input():
    assert "emotion" not in steering.style_for.__code__.co_varnames
    assert not hasattr(steering, "AFFECT")


def test_director_features_read_neutral_only():
    """The frozen one-hot columns: exactly emo_neutral is set, whatever the record says."""
    names = features.FEATS
    emo = [i for i, n in enumerate(names) if n.startswith("emo_")]
    assert emo and names[emo[0]] == "emo_neutral"
