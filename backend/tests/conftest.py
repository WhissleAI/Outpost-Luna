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
