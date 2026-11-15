"""[qa] The debrief chart and the picker get the fields they need to be honest (docs/QA.md)."""
from app.mission import sim

SITE = "connecting_ridge"
# an idle crew lives long enough to sit through storms here (at the ridge it now runs out of power in the first, real,
# 58-hour dark of the LOLA skyline, before any storm)
STORM_SITE = "de_gerlache_rim"


def test_every_shift_inside_a_storm_is_marked_storm_active():
    """A 12-24 h storm spans 2-4 shifts; the chart shades all of them, not just the shift it started in."""
    m = sim.new_mission("qa", STORM_SITE, 1)
    while not m.over:
        sim.advance(m, 1)
    marked = [s for s in m.shifts if s["storm_active"]]
    assert marked, "a mission with storms marks some shifts"
    for s in m.shifts:
        hours = range(int(s["t_h"]) - sim.SHIFT_H, int(s["t_h"]))
        assert s["storm_active"] == any(st.active(h) for st in m.storms for h in hours)
    started = [s for s in m.shifts if "solar_storm" in s["events"]]
    assert len(marked) >= len(started)


def test_public_site_explains_ice_power_and_radio():
    by = {s["id"]: sim.public_site(s) for s in sim.sites()}
    rim, floor = by["shackleton_rim"], by["shackleton_floor"]
    assert rim["rover_to_ice_h"] and not rim["ice"]            # "6 h away", not "No ice"
    assert floor["power_from"] == {"site": "shackleton_rim", "pretend_tech": True}
    assert floor["comm_from"]["pretend_tech"] is True
    assert rim["power_from"] is None and rim["comm_from"] is None
