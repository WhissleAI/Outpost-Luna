"""Router v2: 3D cabin panel navigation and the voice bar. "open the comm panel" once reached the mission NLU as an
order and turned the radio OFF; panel phrases must be navigation and the NLU must never see them."""
import asyncio

import pytest

from app import director, models_client, session as sessions
from app.config import settings
from app.gazetteer import Gazetteer
from app.mission import capcom, nlu, registry
from app.moments import MomentIndex
from app.turn_router import Ctx, route

PANELS = [
    ("open the power panel", "panel_power"), ("show the power panel", "panel_power"), ("go to the power", "panel_power"),
    ("open the comm panel", "panel_comm"), ("open the comms", "panel_comm"), ("show me the radio panel", "panel_comm"),
    ("go to the communications station", "panel_comm"), ("open the radio", "panel_comm"),
    ("open the habitat panel", "panel_habitat"), ("go to the hab", "panel_habitat"), ("show the habitat panel", "panel_habitat"),
    ("open the rover panel", "panel_rover"), ("go to the rover station", "panel_rover"),
    ("open the radiation panel", "panel_radiation"), ("show the radiation panel", "panel_radiation"),
    ("back", "panel_back"), ("back to my seat", "panel_back"), ("go back to my seat", "panel_back"),
    ("close the panel", "panel_back"), ("seat", "panel_back"), ("okay open the comm panel please", "panel_comm"),
]
ORDERS = ["turn off the radio", "radio off", "shields to 40", "more power to the heaters", "send the rover for ice",
          "check the power", "how is the power"]
# the Systems drawer (docs/GAMEPLAY.md §17): "show power" shows the panel (it was a status question for CAPCOM; "check the
# power" still is one)
SYSTEMS = [("show power", "power"), ("show the power", "power"), ("show me the radiation", "radiation"), ("show the shields", "radiation"),
           ("open life support", "life"), ("show the radio", "radio"), ("show me the air", "life"), ("systems", None), ("show systems", None),
           ("open the systems", None), ("next panel", "next"), ("previous panel", "prev"), ("close systems", "close"), ("hide the drawer", "close"),
           ("the life support panel", "life"), ("show the rover panel", "panel_rover")]
VBAR = [("move the voice bar to the top", "move the voice bar to the top"),
        ("move the voice bar to the top right", "move the voice bar to the top right"),
        ("put the voice bar on the right", "move the voice bar to the right"),
        ("move the mic bar to the bottom left", "move the voice bar to the bottom left"),
        ("move the voice bar to the bottom centre", "move the voice bar to the bottom centre"),
        ("move the voice bar to the bottom middle", "move the voice bar to the bottom centre"),
        ("reset the voice bar", "reset the voice bar"), ("restore the voice bar position", "reset the voice bar")]
SCREENS = ["map", "callsign", "lesson", "lesson_done", "ride", "patch", "brief", "cabin", "debrief", "library"]


def cabin(**k):
    return Ctx(screen="cabin", source="listen", dd=0.9, **k)


@pytest.mark.parametrize("text,intent", PANELS)
def test_panel_phrases_route_to_navigation_in_the_cabin(text, intent):
    r = route(text, cabin())
    assert (r["outcome"], r.get("intent")) == ("navigate", intent), r


@pytest.mark.parametrize("text", ORDERS)
def test_orders_and_status_stay_orders(text):
    assert route(text, cabin())["outcome"] == "order"


@pytest.mark.parametrize("text,arg", SYSTEMS)
def test_systems_drawer_words_route_to_navigation(text, arg):
    r = route(text, cabin())
    if arg == "panel_rover":   # a console's name with "panel" keeps its panel intent (the client opens the drawer's panel)
        assert (r["outcome"], r.get("intent")) == ("navigate", "panel_rover"), r
        return
    assert (r["outcome"], r.get("intent"), r.get("arg")) == ("navigate", "systems", arg), r


def test_systems_words_only_in_the_cabin():
    assert route("next panel", Ctx(screen="map", source="listen", dd=0.9)).get("intent") != "systems"


def test_rover_view_is_not_the_rover_panel():
    assert route("show me the rover", cabin())["intent"] == "view_rover"


@pytest.mark.parametrize("screen", SCREENS)
@pytest.mark.parametrize("text,canon", VBAR)
def test_voice_bar_routes_to_a11y_on_every_screen(screen, text, canon):
    r = route(text, Ctx(screen=screen, source="listen", dd=0.9, step_type="choice" if screen in ("lesson", "ride") else None))
    assert (r["outcome"], r["intent"], r["arg"]) == ("navigate", "a11y", canon), (screen, r)


# ---- through the session: the NLU never sees a panel phrase, the radio keeps its power ---------------------------
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


def test_panel_phrases_never_reach_the_nlu(world, monkeypatch):
    seen = []
    real_parse, real_understand = nlu.parse, nlu.understand

    def parse(text, *a, **k):
        seen.append(text)
        return real_parse(text, *a, **k)

    async def understand(text, *a, **k):
        seen.append(text)
        return await real_understand(text, *a, **k)
    monkeypatch.setattr(nlu, "parse", parse)
    monkeypatch.setattr(nlu, "understand", understand)

    clock = Clock()
    s = sessions.Session("panels", world[0], world[1], clock=clock, registry=registry)
    m = registry.create("shackleton_rim", 7)
    asyncio.run(s.handle({"t": "hello", "mode": "mission", "mission_id": m.id}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "cabin"}))
    comms0 = dict(m.loads)["comms"]
    for text, intent in PANELS:
        clock.t += 5
        asyncio.run(s.handle({"t": "turn", "state": "start", "text": ""}))
        asyncio.run(s.handle({"t": "arc", "device_directed": 0.9}))
        asyncio.run(s.handle({"t": "turn", "state": "end", "text": text}))
        nav = [d for d in s.outbox if d["t"] == "nav"][-1]
        assert nav["intent"] == intent, (text, nav)
    assert seen == [], f"the NLU saw panel phrases: {seen}"
    assert m.loads["comms"] == comms0, "a panel phrase changed the radio power"
    assert not [d for d in s.outbox if d["t"] == "say"]
    # and a real order still goes to the NLU
    clock.t += 5
    asyncio.run(s.handle({"t": "typed", "text": "turn off the radio"}))
    assert seen and any("radio" in t for t in seen)


def test_voice_bar_nav_carries_the_canonical_command(world):
    s = sessions.Session("vbar", world[0], world[1], clock=Clock(), registry=registry)
    asyncio.run(s.handle({"t": "hello", "mode": "academy"}))
    asyncio.run(s.handle({"t": "ui", "event": "screen", "screen": "map"}))
    asyncio.run(s.handle({"t": "typed", "text": "put the voice bar on the right", "source": "voice"}))
    nav = [d for d in s.outbox if d["t"] == "nav"][-1]
    assert nav["intent"] == "a11y" and nav["text"] == "move the voice bar to the right"
    assert nav["heard"] == "put the voice bar on the right"
