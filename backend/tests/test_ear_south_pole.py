"""'Show me the south pole' must go south (Arc Transcriber Space ear, 0.3.0).

The ear's linker took the one-word span "Pole" -> the list entry "North Pole" (16/16 test clips): the turn read
"South North Pole" and the director routed on the linked entity, so it flew to the north pole. Fixed in two layers:
the names list now has a "South Pole" entry (names_list.py), and the model server turns a partial-span link that
contradicts its neighbour into `abstain` (model_server/app/arc_ear.py guard_names)."""
from pathlib import Path

from app import director
from app.gazetteer import Gazetteer
from app.names_list import screen_names

GAZ = Gazetteer(Path(__file__).resolve().parents[1] / "data" / "places.json")


def test_names_list_has_south_pole_on_the_map_and_in_lessons():
    for screen in ("map", "library", "lesson"):
        names = [n["name"] for n in screen_names({"screen": screen})]
        assert "South Pole" in names and "North Pole" in names, screen


def _route(text, ear_names):
    place, how, _ = director._link(text.lower(), {"ear_names": ear_names, "available": True}, GAZ)
    return place, how


def test_linked_south_pole_routes_to_shackleton():
    place, how = _route("show me the south pole", [{"heard": "South Pole", "entity": "South Pole", "state": "linked",
                                                   "p": 1.0}])
    assert place is not None and "north" not in place.id and place.id == "shackleton", (place, how)


def test_abstained_north_pole_link_does_not_fly_north():
    place, how = _route("show me the south pole", [{"heard": "Pole", "entity": "North Pole", "state": "abstain",
                                                   "p": 0.95}])
    assert place is not None and place.id == "shackleton", (place, how)


def test_north_pole_still_goes_north():
    place, how = _route("show me the north pole", [{"heard": "North Pole", "entity": "North Pole", "state": "linked",
                                                   "p": 1.0}])
    assert place is not None and place.id == "north_pole", (place, how)
