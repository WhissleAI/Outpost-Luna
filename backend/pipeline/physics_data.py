"""Build backend/data/physics/physics.json: the NASA physics numbers behind the cabin's gauges (docs/PHYSICS.md).

    cd backend && uv run --with tifffile==2025.5.10 python -m pipeline.physics_data [--cache DIR] [--offline]

Run at BUILD time only; the app reads the small JSON and never calls NASA. Two kinds of numbers:

  * Sampled here, per outpost site: the LRO Diviner seasonal polar NIGHT minimum (Williams et al. 2019; 240 m
    GeoTIFFs from the Diviner team), in a ~1 km box around the site's spot. The spot is the landing-site navigator's
    (data/sites_physics.json, pipeline/site_physics.py), so every number about a site comes from the same place.
    The navigator's table is the one source for each site's sunlight, Earth view, slopes, drive to ice and yearly
    average / maximum temperature (Diviner Polar Resource Product); physics.py reads those from it, never twice.
  * Curated (CURATED below): published NASA values (DSNE, the Lunar Surface Data Book, NTRS reports, nasa.gov pages,
    the CRaTER team's event list), each with its source id and where it sits in that source. backend/data/physics/
    SOURCES.md lists every source with its URL and its use.

All polar rasters: spherical polar stereographic, R = 1737.4 km, true scale at the pole, central longitude 0.
rho = 2R tan((90 - |lat|) / 2), x = rho sin(lon), y = rho cos(lon); image columns grow with x, rows with -y (checked:
only this orientation puts LOLA permanent-shadow pixels on Diviner-cold pixels, and Shackleton's inner wall reads
26-32 degrees on the slope map).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import httpx
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "physics" / "physics.json"
SITES_JSON = ROOT / "data" / "mission" / "sites.json"
R_M = 1737400.0
HALF_M = 500.0

DIVINER = "https://luna1.diviner.ucla.edu/~jpierre/diviner/level4_polar/additional_maps/polar_south_80_{s}_{q}-float.tif"
NAV_JSON = ROOT / "data" / "sites_physics.json"


def site_coords() -> dict:
    """Each outpost site's spot: the navigator's (sites_physics.json), else the site's own coordinates."""
    spots = {p["id"]: (p["spot"]["lat"], p["spot"]["lon"]) for p in json.loads(NAV_JSON.read_text())["places"]
             if p.get("kind") == "site" and p.get("spot")} if NAV_JSON.exists() else {}
    return {s["id"]: spots.get(s["id"], (s["lat"], s["lon"])) for s in json.loads(SITES_JSON.read_text())["sites"]}


def download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    return dest


def stereo_xy(lat: float, lon: float) -> tuple[float, float]:
    rho = 2 * R_M * math.tan(math.radians(90 - abs(lat)) / 2)
    return rho * math.sin(math.radians(lon)), rho * math.cos(math.radians(lon))


def stats(v: np.ndarray) -> dict | None:
    v = v[np.isfinite(v)]
    if not v.size:
        return None
    return {"median": round(float(np.median(v)), 1), "p90": round(float(np.percentile(v, 90)), 1),
            "min": round(float(v.min()), 1), "max": round(float(v.max()), 1), "n_px": int(v.size)}


# ---------------------------------------------------------------- Diviner seasonal maps (Williams et al. 2019)
DIV_X0, DIV_Y0, DIV_PX = -304005.54, 304005.54, 240.03595736281088   # GeoTIFF upper-left corner and pixel (m)


def sample_diviner(cache: Path, sites: dict) -> dict:
    import tifffile
    out: dict = {k: {} for k in sites}
    for season in ("summer", "winter"):
        for q in ("min",):
            f = download(DIVINER.format(s=season, q=q), cache / "diviner" / f"polar_south_80_{season}_{q}-float.tif")
            a = tifffile.imread(f)
            cx = DIV_X0 + (np.arange(a.shape[1]) + 0.5) * DIV_PX
            cy = DIV_Y0 - (np.arange(a.shape[0]) + 0.5) * DIV_PX
            for sid, (lat, lon) in sites.items():
                x, y = stereo_xy(lat, lon)
                cols = np.where(np.abs(cx - x) <= HALF_M)[0]
                rows = np.where(np.abs(cy - y) <= HALF_M)[0]
                out[sid][f"{season}_{q}_k"] = stats(a[np.ix_(rows, cols)].ravel().astype(float))
    return out


# ---------------------------------------------------------------- curated NASA values (each with its source id)
def V(value, src, where, **k):
    return {"value": value, "source": src, "where": where, **k}


CURATED = {
    "power": {
        "solar_constant_w_m2": V(1361, "tsi", "NASA GSFC solar irradiance: TSIS-1 1361.6 ± 0.3 W/m² (2019 minimum)"),
        "cell_efficiency": V(0.30, "sst_soa", "NASA SST State of the Art §3.2.1, Table 3-1: multi-junction nominal 30% "
                                              "(29.5-32.2% beginning of life)"),
        "li_ion_wh_kg": V([150, 270], "sst_soa", "NASA SST State of the Art §3.4.1: commercial Li-ion 150-270 Wh/kg"),
        "habitat_array_kw": V([10, 15], "sh_tcs", "NASA MSFC Surface Habitat (crew of 4): solar array 10-15 kW"),
        "habitat_night_kwh": V([155, 540], "sh_tcs", "Surface Habitat survive-the-night energy, 155 kWh nominal to "
                                                     "540 kWh with no mitigation"),
        "fsp_kw": V(40, "fsp", "NASA Fission Surface Power: at least 40 kW"),
        "south_pole_max_sun_deg": V(7.5, "databook", "Lunar Surface Data Book §6.3.1"),
        "sun_disk_deg": V(0.53, "sunfact", "NASA Sun fact sheet: apparent diameter from Earth 31.6'-32.7' (the Moon "
                                           "is as far from the Sun)"),
    },
    "life": {
        "o2_kg_per_person_day": V(0.9, "bvad", "NASA BVAD (NASA/TP-2015-218570/REV2) Table 3-31: oxygen consumed "
                                               "0.895 kg/CM-d nominal; Table 4-1 range 0.61-1.08"),
    },
    "radiation": {
        "crater_quiet_gcr": {
            "mgy_per_h": V(0.0134, "crater", "Schwadron et al. 2012: 11.7 cGy/yr at the 2009 solar minimum peak, at the "
                                             "lunar surface, in water"),
            "msv_per_h": V(0.057, "crater", "0.0134 mGy/h × <Q> 4.3 (Chang'e 4 LND's measured quality factor, Zhang 2020) "
                                            "= 0.057 mSv/h: the same as Chang'e 4's 57.1 µSv/h", derived=True),
            "on_change4_day_ugy_per_h": V(13.29, "change4", "Zhang 2020: CRaTER 13.29 µGy/h on 2 Feb 2019 (water, surface) "
                                                            "vs LND 13.2 µGy/h"),
        },
        "crater_sep_events": [
            {"id": "C12-020", "dates": "2012-01-20/2012-02-07", "peak_mgy_per_h": 61.8, "total_gy": 1.85, "source": "crater_events"},
            {"id": "C12-064", "dates": "2012-03-04/2012-03-19", "peak_mgy_per_h": 46.7, "total_gy": 1.34, "source": "crater_events"},
            {"id": "C14-005", "dates": "2014-01-05/2014-01-10", "peak_mgy_per_h": 19.5, "total_gy": 0.50, "source": "crater_events"},
        ],
        "sep_note": "CRaTER's event list gives thin-shield doses (skin-like); detector and medium are not stated. The "
                    "game's storm multipliers (x1.25 to x8) are far below these peaks: scaled for the game.",
    },
    "ice": {
        "lcross_water_wt_pct": V(5.6, "lcross", "Colaprete et al. 2010: 5.6 ± 2.9% by mass at the Cabeus impact site; "
                                                "the Lunar Surface Data Book §3.2.5 gives 'on the order of five percent'",
                                 range=[2.7, 8.5]),
        "lend_polar_weh_wt_pct": V(0.13, "lend", "NTRS 20180004020: poleward of 88 deg ~140 ppmw = 0.13 ± 0.02 wt% WEH"),
        "ice_cold_trap_k": V(110, "diviner_team", "Diviner team: surfaces below 110 K cold-trap water for a billion years"),
    },
    "regolith": {
        "conductivity_surface_w_mk": V([0.0009, 0.0015], "dsne", "DSNE Rev H Table 3.4.6.2-1, 0-2 cm"),
        "conductivity_deep_w_mk": V([0.010, 0.015], "dsne", "DSNE Rev H Table 3.4.6.2-1, 2-15 cm"),
        "density_g_cm3": V(1.58, "dsne", "DSNE Rev H §3.4.2.3.1: 1.58 ± 0.05 g/cm³ in the top 30 cm"),
        "specific_heat_j_kgk": V({"100K": 287, "200K": 564, "300K": 773}, "dsne", "DSNE Rev H Table 3.4.6.2.2-1"),
        "emissivity": V([0.95, 0.98], "dsne", "DSNE Rev H Table 3.4.6.1.1-1, south pole"),
    },
    "rover": {
        "viper_mass_kg": V(450, "viper", "NASA VIPER in depth: 450 kg"),
        "viper_peak_w": V(450, "viper", "NASA VIPER in depth: peak power 450 W"),
        "viper_battery_wh": V(5420, "viper_ntrs", "NTRS 20240013903: battery 5,420 Wh (start of life, 0 C)"),
        "viper_max_slope_deg": V(15, "viper_ntrs", "NTRS 20240013903: slopes up to 15 deg (requirement)"),
        "lrv_wh_per_km": V(67, "a15_report", "Apollo 15 Mission Report §8.2: 1.87 Ah/km × 36 V nominal", derived=True),
    },
    "temperature_reference": {
        "equator_noon_k": V(391, "dsne", "DSNE Rev H Table 3.4.6.3-1"),
        "equator_predawn_k": V(96, "dsne", "DSNE Rev H Table 3.4.6.3-1"),
        "coldest_psr_k": V(18, "databook", "Lunar Surface Data Book §4.8"),
    },
}

# The outpost model: how the game's percent maps to real units. Game scale, anchored on NASA's Surface Habitat study:
# the sim's full-Sun charge is 6 %/h of the battery (sim.SOLAR_GEN), so a 15 kW array (the top of the habitat's
# 10-15 kW) means a 250 kWh battery, inside the habitat's 155-540 kWh survive-the-night range.
OUTPOST_MODEL = {
    "array_kw": V(15, "sh_tcs", "top of the NASA Surface Habitat's 10-15 kW solar array"),
    "battery_kwh": V(250, "outpost_model", "array_kw / sim.SOLAR_GEN (6 %/h): game scale", derived=True),
    "heater_full_duty_share_pct": V(20, "game", "game rule: a 20% heater share = heaters on all the time (100% duty)"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(ROOT / "data" / "cache" / "physics"))
    ap.add_argument("--offline", action="store_true", help="re-write the curated values, keep the sampled ones")
    a = ap.parse_args()
    cache = Path(a.cache)
    sites = site_coords()
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    if a.offline:
        sampled = old.get("sampled") or {}
    else:
        print("sampling the Diviner night minimum at", ", ".join(sites), file=sys.stderr)
        sampled = {"diviner_seasonal": sample_diviner(cache, sites), "half_box_m": HALF_M, "coords": sites}
    per_site = {}
    for sid in sites:
        dv = sampled["diviner_seasonal"][sid]
        per_site[sid] = {"diviner": {"min_k": V(dv["winter_min_k"]["median"], "diviner",
                                                "winter night minimum, box median (Williams 2019), at the navigator's spot",
                                                range=[dv["winter_min_k"]["min"], dv["summer_min_k"]["max"]])}}
    sources = json.loads((OUT.parent / "sources.json").read_text())
    doc = {"note": "Built by backend/pipeline/physics_data.py; sources in SOURCES.md. The app never calls NASA.",
           "sources": sources, "outpost_model": OUTPOST_MODEL, **CURATED, "sites": per_site, "sampled": sampled}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print("wrote", OUT, f"({OUT.stat().st_size // 1024} KB)", file=sys.stderr)


if __name__ == "__main__":
    main()
