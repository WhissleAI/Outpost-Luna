import os

os.environ.setdefault("VIDEO_PREFETCH", "0")   # NASA video: tests never start the background download (app/video.py)
# [#84] app/local_guard.py: Starlette's TestClient sends Host: testserver; no per-launch token unless a test sets one
# (tests/test_local_guard.py wraps the app in its own guard with a token).
os.environ["LUNA_ALLOWED_HOSTS"] = "testserver"
for _k in ("LUNA_TOKEN", "LUNA_DEV_COOKIE", "LUNA_ORIGINS"):
    os.environ.pop(_k, None)

import pytest

from app import models_client


@pytest.fixture(autouse=True)
def mission_saves(tmp_path_factory, monkeypatch):
    """[polish 2] Every mission auto-saves (app/mission/registry.py): tests save into a temp folder, never data/."""
    monkeypatch.setenv("MISSION_SAVE_DIR", str(tmp_path_factory.mktemp("saves")))


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

    async def none(text, command_context=False):
        return []
    monkeypatch.setattr(safety, "tagger_read", none)


# What GET /v1/tts/voices returns on a Mac with two premium voices (the model server ranks them; app/voices.py reads
# them). Tests never reach a model server for the voice list.
FAKE_VOICES = {
    "engine": "say", "timing": "estimated", "locale": "en-US", "default": "com.apple.voice.Tara.premium",
    "roles": {"guide": "com.apple.voice.Tara.premium", "capcom": "com.apple.voice.Aman.premium",
              "houston": "com.apple.voice.Aman.premium", "story": "com.apple.voice.Tara.premium"},
    "voices": [
        {"id": "com.apple.voice.Tara.premium", "name": "Tara", "locale": "en-IN", "gender": "female",
         "quality": "premium", "desc": "Premium · India · female", "rank": 0, "picker": True},
        {"id": "com.apple.voice.Aman.premium", "name": "Aman", "locale": "en-IN", "gender": "male",
         "quality": "premium", "desc": "Premium · India · male", "rank": 1, "picker": True},
        {"id": "com.apple.voice.compact.en-US.Samantha", "name": "Samantha", "locale": "en-US", "gender": "female",
         "quality": "compact", "desc": "Compact · US · female", "rank": 2, "picker": True},
        {"id": "com.apple.eloquence.en-US.Reed", "name": "Reed", "locale": "en-US", "gender": "",
         "quality": "eloquence", "desc": "Basic · US", "rank": 3, "picker": False},
    ],
}


@pytest.fixture(autouse=True)
def os_voice_catalog(monkeypatch):
    """The Settings voice list as a model server on a Mac would give it; no network."""
    from app import voices

    async def no_refresh():
        return None
    monkeypatch.setattr(voices, "refresh", no_refresh)
    monkeypatch.setattr(voices, "refresh_sync", lambda: None)
    voices.set_catalog(FAKE_VOICES)
    yield
    voices.set_catalog(None)


@pytest.fixture(autouse=True)
def no_voice_pack(monkeypatch, request):
    """Tests run without the recorded voice pack (docs/VOICE_PACK.md) unless marked `voice_pack`: the checked-in pack
    must not change what other tests expect (CAPCOM speaks in the guide voice while the pack is on)."""
    if "voice_pack" in request.keywords:
        return
    from app import tts
    monkeypatch.setattr(tts, "pack_version", lambda: "")


# [#92] app/diag.py: tests never write the developer's logs or daily metrics (a test that wants them sets its own dirs)
for _k in ("LUNA_LOG_DIR", "LUNA_DATA_DIR"):
    os.environ.pop(_k, None)
