"""The self-echo loop (packaged app, mission cabin during a storm): the open mic heard the app's own voice, hums and
filler ("Mm-mm.", "Oh.") and answered them with "I don't know that one yet. Try: show me the giant bullseye…", whose
example command was heard back and answered again. Every turn here comes in exactly as the ear posts it."""
import asyncio

import pytest

from app import director, models_client, session as sessions
from app.config import settings
from app.gazetteer import Gazetteer
from app.mission import capcom, registry
from app.moments import MomentIndex

SITE, SEED = "shackleton_rim", 7
UNKNOWN_FULL_OLD = "I don't know that one yet. Try: show me the giant bullseye or where did Apollo 11 land?"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(scope="module")
def world():
    return Gazetteer(settings.data_dir / "places.json"), MomentIndex(settings.data_dir / "index/clips.json")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    async def no_arc(*a, **k):
        return None
    monkeypatch.setattr(models_client, "tag", no_arc)
    director.RULES.clear()
    director.PENDING.clear()
    capcom._explained.clear()


def run(c):
    return asyncio.run(c)


def make(world, screen="cabin", mode="mission"):
    clock = Clock()
    s = sessions.Session("hf-1", world[0], world[1], clock=clock, registry=registry)
    if mode == "mission":
        m = registry.create(SITE, SEED)
        run(s.handle({"t": "hello", "mode": "mission", "mission_id": m.id}))
    else:
        run(s.handle({"t": "hello", "mode": mode}))
    run(s.handle({"t": "ui", "event": "screen", "screen": screen}))
    s.clock_obj = clock
    return s


def hear(s, text, dd=None, advance=1.0):
    """One turn exactly as /ws/listen posts it: start, (arc), end."""
    s.clock_obj.t += advance
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    if dd is not None:
        run(s.handle({"t": "arc", "device_directed": dd}))
    run(s.handle({"t": "turn", "state": "end", "text": text}))


def play(s, did, text, dur=2.0):
    """The client reports one line of our own voice (floor.js playback events carry the text)."""
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": did, "text": text}))
    s.clock_obj.t += dur
    run(s.handle({"t": "playback", "kind": "guide", "state": "end", "id": did}))


def says(s):
    return [d["text"] for d in s.outbox if d["t"] == "say"]


def spoken_unknowns(s):
    return sum(t.startswith("I don't know that one yet") for t in says(s))


def test_filler_and_hums_are_never_answered(world):
    s = make(world)
    for t in ["Oh.", "Mm-mm.", "um", "hmm", "Uh-huh.", "Mm.", "Ah!", "Huh?", "oh no", "uh, um"]:
        hear(s, t, dd=0.9, advance=5)
    assert says(s) == []
    assert all(r["outcome"] == "ignore" for r in s.routes)


def test_our_own_lines_fed_back_are_never_answered(world):
    s = make(world)
    lines = ["Storm is here! Into the shelter, and shields up.", "Houston can hear us. Comm window open.",
             "I don't know that one yet.", UNKNOWN_FULL_OLD, "Copy, commander. Shields now get 40 percent."]
    for i, line in enumerate(lines):
        play(s, f"g{i}", line)
        hear(s, line, dd=0.9, advance=0.3)                    # the mic heard the whole line
        hear(s, line.split(".")[0], dd=0.9, advance=0.3)      # or just its first sentence
    assert says(s) == [], s.routes
    # the example command inside the old fallback line, heard a few seconds after it played
    play(s, "g9", UNKNOWN_FULL_OLD)
    hear(s, "show me the giant bullseye", dd=0.95, advance=4)
    assert says(s) == []


def test_echo_of_an_older_line_not_only_the_current_one(world):
    s = make(world)
    play(s, "a", "Storm coming. Get ready: shields up or go to the shelter.")
    play(s, "b", "Houston can hear us. Comm window open.")
    hear(s, "get ready shields up or go to the shelter", dd=0.9, advance=3)
    assert says(s) == []


def test_while_speaking_only_barge_in_worthy_turns_get_through(world):
    s = make(world)
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": "p", "text": "The storm is over. All clear!"}))
    hear(s, "yeah", dd=0.9, advance=0.2)
    hear(s, "shields", advance=0.2)
    assert says(s) == []
    hear(s, "move twenty percent to the heaters", dd=0.95, advance=0.2)
    assert any("heater" in t.lower() for t in says(s))


def test_the_loop_is_broken(world):
    """Speak whatever we say back into the ear, ten times over: one answer at most, then silence."""
    s = make(world)
    hear(s, "what is the weirdest thing about the moon's dust", dd=0.95)
    n0 = len(says(s))
    assert n0 >= 1, "the real question is answered once"
    for i in range(10):
        for j, t in enumerate(says(s)[-2:]):
            play(s, f"l{i}{j}", t, dur=1.5)
            hear(s, t, dd=0.9, advance=0.4)
            hear(s, "Mm-mm.", dd=0.8, advance=0.4)
    assert len(says(s)) == n0


def test_unknown_only_for_clear_questions_and_once_per_30s(world):
    s = make(world, screen="library", mode="cadet")
    for t in ["the cat is on the sofa", "I like pizza", "okay so then we went home", "blue"]:
        hear(s, t, dd=0.9, advance=2)
    assert spoken_unknowns(s) == 0 and not [d for d in s.outbox if d["t"] == "answer"]
    hear(s, "what is the name of the moon's pet dog", dd=0.95, advance=2)
    first = [d for d in s.outbox if d["t"] == "answer"]
    assert len(first) == 1 and first[0]["r"]["say"] == "I don't know that one yet."
    hear(s, "who is the moon's favourite football player", dd=0.95, advance=5)
    assert len([d for d in s.outbox if d["t"] == "answer"]) == 1, "never the fallback back to back (30 s)"
    hear(s, "who is the moon's favourite football player today", dd=0.95, advance=31)
    assert len([d for d in s.outbox if d["t"] == "answer"]) == 2


def test_unknown_spoken_line_carries_no_example_commands(world):
    r = asyncio.run(director.direct("what is the name of the moon's pet dog", {"available": False}, *world))
    assert r["say"] == "I don't know that one yet."
    card = next(d for d in r["decisions"] if d["t"] == "card")
    say = next(d for d in r["decisions"] if d["t"] == "say")
    assert "bullseye" in card["body"] and "bullseye" not in say["text"]


def test_two_adults_chatting_in_the_cabin_get_nothing(world):
    s = make(world)
    for t in ["did you pick up the milk on the way home", "yeah I put it in the fridge next to the juice",
              "we should call your mom tonight about the weekend"]:
        hear(s, t, dd=0.2, advance=3)
    assert says(s) == []


def test_the_kid_can_answer_an_offer_right_away(world):
    """ "…Say next when you're ready." -> "next" half a second later is the kid, not the echo of our offer."""
    s = make(world, screen="patch", mode="academy")
    run(s.handle({"t": "ui", "event": "screen", "screen": "patch", "offer": "next_lesson"}))
    play(s, "o", "Patch earned, Nova: Moon Scout! Next up: Space words. Say next when you're ready.")
    hear(s, "next", dd=0.9, advance=0.5)
    assert s.routes[-1]["outcome"] == "navigate"
    # but the same word heard WHILE the offer plays is its echo
    s.clock_obj.t += 3
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": "o2", "text": "Say next when you're ready."}))
    hear(s, "next", dd=0.9, advance=0.2)
    assert s.routes[-1]["reason"] == "echo"


def test_a_quick_answer_repeating_the_prompt_is_heard(world):
    s = make(world, screen="lesson", mode="academy")
    run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": "tap"}))
    play(s, "q", "Now tap Shackleton crater, inside the gold ring at the pole.")
    hear(s, "Shackleton", dd=0.9, advance=0.9)   # after the 600 ms hard-mute tail
    assert s.routes[-1]["outcome"] == "answer"


def live_turn(s, text, dd=0.9, gap=0.02):
    """A turn exactly as the live path posts it (tools/handsfree_run.py Live.turn over WS /ws/session): it starts
    `gap` s after the last event we sent (one WS hop), with no idle time before it."""
    s.clock_obj.t += gap
    run(s.handle({"t": "turn", "state": "start", "text": ""}))
    run(s.handle({"t": "arc", "device_directed": dd}))
    s.clock_obj.t += 0.3 * max(1, len(text.split()))
    run(s.handle({"t": "turn", "state": "end", "text": text}))


@pytest.mark.parametrize("screen,offer,lines,word", [
    ("patch", "next_lesson", ["Roger. Shackleton crater. Our outpost goes here.",
                              "Patch earned: Moon Scout. Nice work, Nova.", "Ready for the next lesson?"], "next"),
    ("patch", "next_lesson", ["Roger. Shackleton crater. Our outpost goes here. Next up: Lessons from Apollo. "
                              "Say next when you're ready."], "next"),            # the RC's exact line
    ("patch", "next_lesson", ["Patch earned: Moon Scout. Nice work, Nova.", "Ready for the next lesson?"], "yes"),
    ("patch", "mission", ["Check Ride patch earned. You're qualified, Commander Nova.", "Ready to take command?"],
     "take command"),
    ("debrief", "fly_again", ["Mission paused. Fly again?"], "fly again"),
])
def test_the_offers_answer_right_after_its_echo_navigates(world, screen, offer, lines, word):
    """The live RC loop: our offer plays (playback start / end, as floor.js reports them), the mic hears it back
    (echo, ignored), and the kid's "next" arrives a few ms after the echo's playback ended, inside the 0.3 s ear-lag
    tail. It was routed `ignore (echo)` on every retry and the kid never left the patch screen."""
    s = make(world, screen=screen, mode="academy")
    run(s.handle({"t": "ui", "event": "screen", "screen": screen, "offer": offer}))
    for i, line in enumerate(lines):                       # the app's lines, each reported start .. end
        play(s, f"o{i}", line, dur=min(2.0, 0.25 * len(line.split())))
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": "echo", "text": lines[-1]}))
    live_turn(s, lines[-1])                                # our own line heard back while it plays
    assert s.routes[-1]["reason"] == "echo"
    run(s.handle({"t": "playback", "kind": "guide", "state": "end", "id": "echo"}))
    live_turn(s, word)                                     # the kid, right away
    r = s.routes[-1]
    assert r["outcome"] == "navigate", r
    assert r["intent"] in ("next", "accept_offer", "take_command", "fly_again"), r
    assert says(s) == []


def test_an_offer_word_while_the_offer_is_still_on_air_is_its_echo(world):
    """The other side of the same rule: our line is still playing at the turn start -> its echo, not a yes."""
    s = make(world, screen="patch", mode="academy")
    run(s.handle({"t": "ui", "event": "screen", "screen": "patch", "offer": "next_lesson"}))
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": "o", "text": "Ready for the next lesson?"}))
    live_turn(s, "next lesson", gap=0.4)
    assert s.routes[-1]["reason"] == "echo"
    live_turn(s, "next", gap=0.1)
    assert s.routes[-1]["reason"] == "echo"


def test_a_step_answer_right_after_the_prompts_echo_is_graded(world):
    """Same tail on a lesson step: the prompt says the answer ("Copy means I heard you") and the kid says it right
    after the echo. While the echo still plays it stays an echo."""
    s = make(world, screen="lesson", mode="academy")
    run(s.handle({"t": "ui", "event": "screen", "screen": "lesson", "step_type": "choice",
                  "step_options": ["I heard you", "Write it down", "Say it again"]}))
    line = "Radio is noisy, so crews keep it short. Copy means I heard you. What does \"copy\" mean on the radio?"
    play(s, "p", line)
    run(s.handle({"t": "playback", "kind": "guide", "state": "start", "id": "echo", "text": line}))
    live_turn(s, line)
    assert s.routes[-1]["reason"] == "echo"
    live_turn(s, "I heard you")
    assert s.routes[-1]["reason"] == "echo"
    s.clock_obj.t += 1.0                                   # (not the same turn twice within 1 s: Session._dup)
    run(s.handle({"t": "playback", "kind": "guide", "state": "end", "id": "echo"}))
    live_turn(s, "I heard you")
    assert s.routes[-1]["outcome"] == "answer", s.routes[-1]
