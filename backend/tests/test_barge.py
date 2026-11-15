"""Barge-in on the server: the session's own check on the ear relay's words (session._is_barge) and the command table,
which mirrors frontend/src/barge.js."""
import re
from pathlib import Path

from app import barge, turn_router as router


def _js_set(name: str) -> set[str]:
    js = (Path(__file__).resolve().parents[2] / "frontend/src/barge.js").read_text()
    m = re.search(rf"const {name} = new Set\(\[(.*?)\]\);", js, re.S)
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_command_tables_match_the_client():
    assert barge.STOP == _js_set("STOP")
    assert barge.NAV == _js_set("NAV")


def test_commands():
    for t in ["Stop.", "wait", "Be quiet!", "never mind", "okay stop", "stop please", "Skip.", "next please"]:
        assert barge.is_command(t), t
    for t in ["stop it", "wait what", "the rover", "go to the map"]:
        assert not barge.is_command(t), t
    assert barge.is_stop("Wait!") and not barge.is_stop("skip")


def test_echo_of_spelled_letters_and_the_spoken_form():
    line = "Doctors count radiation in mSv. So what is an mSv?"
    # the TTS read the unit as letters; the ear wrote them back one by one
    assert router.echo_of("doctors count radiation in m s v", [line])
    assert router.echo_of("so what is an m s v", [line])
    # the spoken form (narration.py) is a reference too
    assert router.echo_of("so what is a millisievert", [line])
    assert router.echo_of("doctors count radiation in millie sieverts", [line])
    assert not router.echo_of("a radiation dose", [line])
    assert not router.echo_of("go to the map", [line])
