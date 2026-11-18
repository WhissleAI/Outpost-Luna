"""[0.3.12] /api/health tells the voice bar which ear it waits for (frontend/src/engine.js warmState): with no
Deepgram fallback, a failed local ear means "Voice off · type" at once."""
from app import main


def test_voice_route_without_fallback(monkeypatch):
    monkeypatch.setattr(main.settings, "deepgram_api_key", "")
    assert main.voice_route() == {"ear": "arc", "fallback": False}


def test_voice_route_with_fallback(monkeypatch):
    monkeypatch.setattr(main.settings, "deepgram_api_key", "k")
    assert main.voice_route()["fallback"] is True
