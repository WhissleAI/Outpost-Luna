import pytest

from app import claims, llm
from app.config import settings


@pytest.fixture(autouse=True)
def no_network_llm(monkeypatch):
    """Tests never call the real LLM; a test that wants one monkeypatches claims._complete itself."""
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    claims._client = None
    llm._client = None
