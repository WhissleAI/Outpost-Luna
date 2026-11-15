"""The narration rule (app/narration.py): the voice says "millisieverts" where the screen shows "mSv"."""
import asyncio
import json
from pathlib import Path

from app import narration, tts

CASES = [
    ("Doctors count radiation in mSv. So what is an mSv?", "Doctors count radiation in millisieverts. So what is a millisievert?"),
    ("Correct. One mSv is about 10 chest x-rays.", "Correct. One millisievert is about 10 chest x-rays."),
    ("Radiation high: 0.42 mSv an hour.", "Radiation high: 0.42 millisieverts an hour."),
    ("Dose rate 0.12 mSv/h.", "Dose rate 0.12 millisieverts an hour."),
    ("Crew dose: 14.2 of 50 mSv.", "Crew dose: 14.2 of 50 millisieverts."),
    ("Your crew took 12.0 game-mSv.", "Your crew took 12.0 game millisieverts."),
    ("An mSv measures radiation dose.", "A millisievert measures radiation dose."),
    ("No units here.", "No units here."),
]


def test_spoken_forms():
    for shown, said in CASES:
        assert narration.spoken(shown) == said


def test_frontend_mirror_has_the_same_cases():
    js = (Path(__file__).resolve().parents[2] / "frontend/tests/narration.test.js").read_text()
    for shown, said in CASES:
        assert json.dumps(shown) in js and json.dumps(said) in js, shown


def test_word_timings_map_back_to_the_display_words():
    shown = "Dose rate 0.12 mSv/h now."
    said = narration.spoken(shown)                     # "Dose rate 0.12 millisieverts an hour now."
    spans = ",".join(f"{i * 100}-{i * 100 + 90}" for i in range(len(said.split())))
    out = narration.display_timings(shown, said, spans).split(",")
    assert len(out) == len(shown.split())
    assert out[3] == "300-590"                         # "mSv/h" covers "millisieverts an hour"
    assert out[4] == "600-690"
    assert narration.display_timings("So what is an mSv?", narration.spoken("So what is an mSv?"), "0-1,2-3,4-5,6-7,8-9") == \
        "0-1,2-3,4-5,6-7,8-9"                          # one word for one word: unchanged


def test_the_course_step_still_shows_msv_and_speaks_millisieverts():
    course = json.loads((Path(__file__).resolve().parents[1] / "data/academy/course.json").read_text())
    prompts = [s["prompt"] for L in course["lessons"] for s in L.get("steps", [])]
    step = next(p for p in prompts if "So what is an mSv" in p)
    assert "mSv" in step                               # the screen text is unchanged
    assert "mSv" not in narration.spoken(step) and "millisievert" in narration.spoken(step)


def test_tts_engines_get_the_spoken_form(monkeypatch, tmp_path):
    seen = {}

    async def fake_os(text, st, place):
        seen["text"], seen["next"] = text, place.get("next")
        n = len(text.split())
        return b"RIFF", ",".join(f"{i}-{i + 1}" for i in range(n)), "say"

    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts, "_os_tts", fake_os)
    monkeypatch.setattr(tts, "finish", lambda audio, st, words, last: (audio, words, None))
    r = asyncio.run(tts.speak("So what is an mSv?", "capcom", None, 0, 2, "One mSv is a dose."))
    assert seen["text"] == "So what is a millisievert?"
    assert seen["next"] == "One millisievert is a dose."
    assert len(r.headers["X-TTS-Words"].split(",")) == len("So what is an mSv?".split())
