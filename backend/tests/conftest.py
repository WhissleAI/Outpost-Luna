import os

os.environ.setdefault("VIDEO_PREFETCH", "0")   # NASA video: tests never start the background download (app/video.py)

import pytest

from app import models_client


@pytest.fixture(autouse=True)
def no_embedder(monkeypatch, request):
    """Tests run without the model server's embedder (rules + card aliases only) unless a test patches embed itself."""
    if "real_embedder" in request.keywords:
        return

    async def off(texts, kind="query", timeout=None):
        return None
    monkeypatch.setattr(models_client, "embed", off)


@pytest.fixture(autouse=True)
def no_safety_tagger(monkeypatch):
    """[P0] Tests don't call the model server's tagger for a turn's safety tags (the word list still runs); a test that
    wants tags patches app.safety.tagger_read itself (tests/test_safety.py)."""
    from app import safety

    async def none(text):
        return []
    monkeypatch.setattr(safety, "tagger_read", none)
