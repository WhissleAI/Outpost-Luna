import json

from app.config import settings
from app.gazetteer import Gazetteer
from app.keyterms import MAX_TERMS, base_keyterms, clip_keyterms
from pipeline.build_index import words_of
from pipeline.transcribe_deepgram import normalize

GAZ = Gazetteer(settings.data_dir / "places.json")
DG = {"metadata": {"duration": 3.0}, "results": {
    "channels": [{"alternatives": [{"transcript": "", "words": []}]}],
    "utterances": [
        {"start": 0.1, "end": 1.0, "speaker": 0, "transcript": "Look, Orientale.",
         "words": [{"word": "look", "punctuated_word": "Look,", "start": 0.1, "end": 0.4, "confidence": 0.9,
                    "speaker": 0},
                   {"word": "orientale", "punctuated_word": "Orientale.", "start": 0.5, "end": 1.0,
                    "confidence": 0.8, "speaker": 0}]},
        {"start": 1.5, "end": 2.0, "speaker": 1, "transcript": "Wow.",
         "words": [{"word": "wow", "punctuated_word": "Wow.", "start": 1.5, "end": 2.0, "confidence": 0.99,
                    "speaker": 1}]}]}}


def test_normalize_keeps_words_of_working(tmp_path):
    d = normalize(DG, ["Orientale"])
    assert d["source"] == "deepgram nova-3" and d["speakers"] == 2
    p = tmp_path / "x.json"
    p.write_text(json.dumps(d))
    w = words_of(p)
    assert w[1][:3] == [0.5, "Orientale.", 0] and w[2][2] == 1 and w[2][3] == 2.0


def test_keyterms_within_deepgram_limits():
    b = base_keyterms(GAZ)
    assert 10 < len(b) <= MAX_TERMS <= 100
    assert sum(len(t.split()) for t in b) < 250  # well under 500 tokens
    assert "Orientale" in b and "bullseye" not in [t.lower() for t in b]
    assert clip_keyterms("Byrgius Alpha and Mare Humorum: Regolith Color", GAZ)[:2] == ["Byrgius Alpha", "Mare Humorum"]


def test_index_words_carry_speaker():
    idx = json.loads((settings.data_dir / "index/clips.json").read_text())
    c = idx["clips"][0]
    assert all(len(w) >= 2 and isinstance(w[0], float | int) for w in c["words"])
    assert "speakers" in c
