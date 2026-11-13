"""Fetch and cache the real data the Mission Trainer runs on, into backend/data/mission/.

    cd backend && uv run python -m pipeline.mission_data [--only sites|ephemeris|donki|radiation]

Sources (all opened and checked when this was written):
  * JPL Horizons API (topocentric Sun/Earth elevation from a point on the Moon)
      https://ssd.jpl.nasa.gov/api/horizons.api  (docs: https://ssd-api.jpl.nasa.gov/doc/horizons.html)
  * DONKI (NASA CCMC space-weather database) via https://api.nasa.gov  (GST, SEP, CME endpoints)
  * IAU/USGS Gazetteer of Planetary Nomenclature (feature coordinates)
  * NASA Artemis III candidate landing region releases (2022, 2024)
  * Published radiation numbers (Chang'e 4 LND, NASA exposure limits) -> radiation.json (hand-curated, cited)

The game never calls the network: everything it needs is in data/mission/*.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "data" / "mission"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"
HORIZONS_DOC = "https://ssd-api.jpl.nasa.gov/doc/horizons.html"
DONKI = "https://api.nasa.gov/DONKI"
NASA_KEY = os.environ.get("NASA_API_KEY", "DEMO_KEY")

# Mission window: 10 days in April 2026, the month Artemis II flew around the Moon. Chosen (after scanning Mar-May 2026)
# because in these days Earth climbs from below the south-pole horizon to above it (a real comm blackout, then
# comm windows) and the Sun sinks low at the outer sites (night falls at Malapert): the pole's real seasons in 10 days.
WINDOW_START = "2026-04-08 00:00"
WINDOW_STOP = "2026-04-18 00:00"
# Calibration year for each site's effective horizon (see calibrate_horizon).
CAL_START, CAL_STOP = "2026-01-01", "2027-01-01"

ARTEMIS_2022 = {"title": "NASA Identifies Candidate Regions for Landing Next Americans on Moon (Aug 2022)",
                "url": "https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/"}
ARTEMIS_2024 = {"title": "NASA Provides Update on Artemis III Moon Landing Regions (Oct 2024)",
                "url": "https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/"}
BUSSEY = {"title": "Bussey et al. 2010, Illumination conditions of the south pole of the Moon derived using Kaguya "
                   "topography, Icarus 208", "url": "https://doi.org/10.1016/j.icarus.2010.03.028"}
MAZARICO = {"title": "Mazarico et al. 2011, Illumination conditions of the lunar polar regions using LOLA topography, "
                     "Icarus 211", "url": "https://doi.org/10.1016/j.icarus.2010.10.030"}
LCROSS = {"title": "NASA: Ice confirmed at the Moon's poles (M3 / Chandrayaan-1, 2018)",
          "url": "https://www.nasa.gov/news-release/ice-confirmed-at-the-moons-poles/"}


def iau(fid: int, name: str) -> dict:
    return {"title": f"IAU Gazetteer of Planetary Nomenclature: {name}",
            "url": f"https://planetarynames.wr.usgs.gov/Feature/{fid}"}


# lat/lon: IAU gazetteer centers where the site is a named feature; rim/ridge points are the high-illumination points
# reported by Bussey et al. 2010 (not IAU features). sunlight_pct is the approximate long-term average illumination
# reported in that literature (rounded; the floor is a permanently shadowed region). alt_km is approximate relief.
SITES = [
    {"id": "shackleton_rim", "name": "Shackleton Crater Rim", "lat": -89.68, "lon": -166.0, "alt_km": 1.9,
     "sunlight_pct": 86, "ice": False, "rover_to_ice_h": 6,
     "notes": "One of the sunniest spots on the Moon, on the rim of Shackleton crater (a 'Peak Near Shackleton' "
              "was an Artemis III candidate region in 2022). Ice is a short drive down into the crater.",
     "sources": [iau(5450, "Shackleton"), BUSSEY, ARTEMIS_2022]},
    {"id": "shackleton_floor", "name": "Shackleton Crater Floor", "lat": -89.67, "lon": 129.78, "alt_km": -2.5,
     "sunlight_pct": 0, "ice": True, "rover_to_ice_h": 0,
     "power_from": {"site": "shackleton_rim", "efficiency": 0.5,
                    "why": "Game assumption: solar arrays up on the sunny rim, power sent down a long cable (half lost)."},
     "comm_from": {"site": "shackleton_rim",
                   "why": "Game assumption: the crater walls hide Earth, so radio goes through a relay on the rim."},
     "notes": "Permanently shadowed: the Sun never reaches the floor, so it is colder than -170 C and can hold ice. "
              "Great for water, terrible for solar power.",
     "sources": [iau(5450, "Shackleton"), LCROSS, MAZARICO]},
    {"id": "connecting_ridge", "name": "Connecting Ridge", "lat": -89.44, "lon": -141.8, "alt_km": 1.6,
     "sunlight_pct": 82, "ice": False, "rover_to_ice_h": 12,
     "notes": "The ridge between Shackleton and de Gerlache craters; an Artemis III candidate region in 2022. "
              "Long sunlit stretches and views toward Earth.",
     "sources": [BUSSEY, ARTEMIS_2022]},
    {"id": "de_gerlache_rim", "name": "de Gerlache Crater Rim", "lat": -88.71, "lon": -68.7, "alt_km": 1.5,
     "sunlight_pct": 81, "ice": False, "rover_to_ice_h": 10,
     "notes": "Rim of de Gerlache crater ('de Gerlache Rim 2' is an Artemis III candidate region). Sunny rim next to "
              "a shadowed crater floor.",
     "sources": [iau(1439, "de Gerlache"), BUSSEY, ARTEMIS_2024]},
    {"id": "malapert_massif", "name": "Malapert Massif", "lat": -85.98, "lon": -1.67, "alt_km": 5.0,
     "sunlight_pct": 73, "ice": False, "rover_to_ice_h": 18,
     "notes": "A 5 km-tall mountain (Mons Malapert) on the Earth-facing side of the pole, so Earth is above the "
              "horizon much more often: best for talking to Houston, farther from ice. Artemis III candidate region.",
     "sources": [iau(16338, "Mons Malapert"), ARTEMIS_2024, BUSSEY]},
]


def horizons(body: str, lat: float, lon: float, alt_km: float, start: str, stop: str, step: str) -> list[tuple[str, float]]:
    """Topocentric apparent elevation of `body` (10=Sun, 399=Earth) from a point on the Moon. Ignores terrain."""
    params = {"format": "json", "COMMAND": f"'{body}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
              "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'coord@301'", "COORD_TYPE": "'GEODETIC'",
              "SITE_COORD": f"'{lon},{lat},{max(alt_km, 0)}'", "START_TIME": f"'{start}'", "STOP_TIME": f"'{stop}'",
              "STEP_SIZE": f"'{step}'", "QUANTITIES": "'4'", "CSV_FORMAT": "'YES'", "ANG_FORMAT": "'DEG'"}
    for attempt in range(4):
        r = httpx.get(HORIZONS, params=params, timeout=60)
        if r.status_code == 200:
            break
        time.sleep(2 + attempt * 3)
    r.raise_for_status()
    res = r.json()["result"]
    if "$$SOE" not in res:
        raise RuntimeError(f"Horizons returned no ephemeris: {res[-800:]}")
    rows = []
    for line in res.split("$$SOE")[1].split("$$EOE")[0].strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        # Date, solar-presence, interferer, Azi, Elev
        rows.append((parts[0], float(parts[4])))
    return rows


def calibrate_horizon(site: dict) -> float:
    """Effective flat horizon angle (deg) for the site: the Sun-elevation quantile over 2026 whose lit fraction
    matches the published average illumination. Real terrain is jagged; this one number stands in for it."""
    if site["sunlight_pct"] <= 0:
        return 90.0  # permanently shadowed
    rows = horizons("10", site["lat"], site["lon"], site["alt_km"], CAL_START, CAL_STOP, "6 h")
    elevs = sorted(e for _, e in rows)
    k = int(round(len(elevs) * (1 - site["sunlight_pct"] / 100)))
    k = min(max(k, 0), len(elevs) - 1)
    return round(elevs[k], 3)


def build_sites_and_ephemeris(only_sites: bool = False):
    out_sites = []
    for s in SITES:
        print("site", s["id"], file=sys.stderr)
        horizon = calibrate_horizon(s)
        sun = horizons("10", s["lat"], s["lon"], s["alt_km"], WINDOW_START, WINDOW_STOP, "1 h")
        earth = horizons("399", s["lat"], s["lon"], s["alt_km"], WINDOW_START, WINDOW_STOP, "1 h")
        assert len(sun) == len(earth) == 241, (len(sun), len(earth))
        lit = sum(e > horizon for _, e in sun) / len(sun)
        ev = sum(e > min(horizon, 0) for _, e in earth) / len(earth)
        site = {k: v for k, v in s.items()}
        site["horizon_deg"] = horizon
        site["earth_visible_pct"] = round(100 * ev)
        site["window_sunlit_pct"] = round(100 * lit)
        out_sites.append(site)
        eph = {
            "site": s["id"], "start_utc": WINDOW_START, "step_h": 1,
            "sun_elev_deg": [round(e, 3) for _, e in sun], "earth_elev_deg": [round(e, 3) for _, e in earth],
            "times_utc": [t for t, _ in sun],
            "horizon_deg": horizon,
            "notes": ("Apparent elevation of the Sun and Earth seen from this point on the Moon, hourly, from JPL "
                      "Horizons (topocentric observer, CENTER='coord@301', geodetic site). Horizons treats the "
                      "ground as a smooth sphere: it ignores mountains and crater walls. The game approximates terrain "
                      "with one effective horizon angle (horizon_deg) calibrated so the site's lit fraction over 2026 "
                      "matches the published average illumination. Earth counts as visible above min(horizon_deg, 0)."),
            "source": {"title": "JPL Horizons API", "url": HORIZONS_DOC},
        }
        (OUT / f"ephemeris_{s['id']}.json").write_text(json.dumps(eph, indent=1))
    doc = {"window": {"start_utc": WINDOW_START, "stop_utc": WINDOW_STOP,
                      "why": ("10 days in April 2026, the month Artemis II flew around the Moon. Earth rises from below the "
                              "horizon (comm blackout) to above it, and the Sun sinks low at the outer sites.")},
           "sources": [ARTEMIS_2022, ARTEMIS_2024, BUSSEY, MAZARICO, {"title": "JPL Horizons API", "url": HORIZONS_DOC}],
           "sites": out_sites}
    (OUT / "sites.json").write_text(json.dumps(doc, indent=1))


def donki(kind: str, start: str, end: str) -> list:
    for attempt in range(5):
        r = httpx.get(f"{DONKI}/{kind}", params={"startDate": start, "endDate": end, "api_key": NASA_KEY}, timeout=90)
        if r.status_code == 200:
            return r.json() or []
        print(f"DONKI {kind} {r.status_code}; retrying", file=sys.stderr)
        time.sleep(10 * (attempt + 1))
    r.raise_for_status()
    return []


# The curated storms (DONKI activity IDs are looked up from the fetched lists). severity/multiplier mapping:
#   severity 3 = SEP event with a G4-G5 storm (Kp >= 8) or a fast (>=2000 km/s) CME   -> dose x 6
#   severity 2 = SEP event or Kp 7 storm or CME >= 1200 km/s                            -> dose x 3
#   severity 1 = Kp 5-6 storm or CME < 1200 km/s                                         -> dose x 1.5
# Why: geomagnetic Kp measures Earth's response, not the Moon's; on the Moon (no magnetosphere) what matters is the
# energetic particles (SEP). We use SEP presence first, then storm/CME strength as a proxy for how big the event was.
SEVERITY_MULT = {1: 1.5, 2: 3.0, 3: 6.0}


def severity(ev: dict) -> int:
    kp, speed, sep = ev.get("kp_max") or 0, ev.get("cme_speed_kms") or 0, ev.get("sep")
    if (sep and kp >= 8) or speed >= 2000:
        return 3
    if sep or kp >= 7 or speed >= 1200:
        return 2
    return 1


def build_donki():
    start, end = "2017-09-01", "2025-12-31"
    gst = donki("GST", start, end)
    sep = donki("SEP", start, end)
    time.sleep(2)
    (OUT / "raw").mkdir(exist_ok=True)
    (OUT / "raw" / "donki_gst.json").write_text(json.dumps(gst))
    (OUT / "raw" / "donki_sep.json").write_text(json.dumps(sep))
    sep_days = {s["eventTime"][:10]: s for s in sep}
    events = []
    for g in gst:
        kp = max((k.get("kpIndex") or 0) for k in g.get("allKpIndex", []) or [{"kpIndex": 0}])
        if kp < 7:
            continue
        day = g["startTime"][:10]
        d0 = datetime.fromisoformat(day)
        near_sep = next((s for d, s in sep_days.items() if abs((datetime.fromisoformat(d) - d0).days) <= 4), None)
        events.append({"id": g["gstID"], "date": day, "type": "GST+SEP" if near_sep else "GST", "kp_max": kp,
                       "sep": bool(near_sep), "sep_id": near_sep["sepID"] if near_sep else None,
                       "link": g.get("link"), "cme_speed_kms": None})
    # Fastest CME per storm (from the CME list around each storm date): one small call per storm.
    for ev in events:
        d0 = datetime.fromisoformat(ev["date"])
        try:
            cmes = donki("CMEAnalysis", (d0 - timedelta(days=4)).date().isoformat(), d0.date().isoformat())
            speeds = [c.get("speed") or 0 for c in cmes if c.get("isMostAccurate")]
            ev["cme_speed_kms"] = round(max(speeds)) if speeds else None
        except Exception as e:  # rate-limited: keep the storm, mark speed unknown
            print("CME lookup failed", ev["date"], e, file=sys.stderr)
        time.sleep(1)
    for ev in events:
        ev["severity"] = severity(ev)
        ev["dose_multiplier"] = SEVERITY_MULT[ev["severity"]]
    write_donki(events)


def write_donki(events: list[dict]):
    doc = {"source": {"title": "DONKI: Space Weather Database Of Notifications, Knowledge, Information (NASA CCMC), "
                               "via api.nasa.gov", "url": "https://api.nasa.gov/#DONKI"},
           "mapping": {"severity_to_dose_multiplier": SEVERITY_MULT,
                       "rule": "3 = SEP + Kp>=8 storm or CME >= 2000 km/s; 2 = SEP, or Kp 7, or CME >= 1200 km/s; "
                               "1 = otherwise. On the Moon there is no magnetic field, so solar energetic particles "
                               "(SEP) matter most; Kp and CME speed stand in for event size."},
           "events": events}
    (OUT / "donki_events.json").write_text(json.dumps(doc, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["sites", "donki"], default=None)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.only in (None, "sites"):
        build_sites_and_ephemeris()
    if a.only in (None, "donki"):
        build_donki()


if __name__ == "__main__":
    main()
