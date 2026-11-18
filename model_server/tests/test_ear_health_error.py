"""[0.3.12] The ear's /health carries its load error, so the voice bar says "Voice off · type" at once instead of
"Starting voice…" for three minutes (frontend/src/engine.js warmState)."""
from app import arcmeta


def test_failed_ear_reports_its_error(monkeypatch):
    monkeypatch.setitem(arcmeta.STATE, "arc", None)
    monkeypatch.setitem(arcmeta.STATE, "error", "FileNotFoundError: libarc not built")
    ear = arcmeta.health()["arc_ear"]
    assert ear["available"] is False and ear["decoder_loaded"] is False
    assert ear["error"] == "FileNotFoundError: libarc not built"


def test_loaded_ear_has_no_error(monkeypatch):
    monkeypatch.setitem(arcmeta.STATE, "arc", object())
    monkeypatch.setitem(arcmeta.STATE, "error", "an old failure")
    monkeypatch.setitem(arcmeta.STATE, "engine", None)
    assert arcmeta.health()["arc_ear"]["error"] is None
