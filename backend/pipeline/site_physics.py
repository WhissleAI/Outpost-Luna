"""Build the landing-site navigator's real NASA data, at BUILD time (the app never fetches it).

    cd backend && uv run python -m pipeline.site_physics            # fetch (cached) + numbers + layers
    cd backend && uv run python -m pipeline.site_physics numbers     # backend/data/sites_physics.json (+ sites.json engine fields)
    cd backend && uv run python -m pipeline.site_physics layers      # the 4 polar overlay PNGs + site-layers tar + sha256
    cd backend && uv run python -m pipeline.site_physics clean       # delete the raster cache (about 0.9 GB)

Inputs (all public NASA archives; each one is cited per field in sites_physics.json and in backend/data/SOURCES.md):
  * LOLA polar illumination products (Mazarico et al. 2011 method, 2016 release), PDS LOLA node "EXTRAS/ILLUMINATION":
      AVGVISIB_*            average solar-disc visibility over 18.6 years, hourly steps  -> yearly sunlight %
      AVGVISIB_*_EARTH      the same for the Earth's disc                                -> Earth in view %
      LPSR_*                permanently shadowed regions                                -> distance to the nearest PSR
  * LOLA gridded slope (LDSM) and topography (LDEM), PDS LOLA node "DATA/LOLA_GDR/POLAR"   -> slope, horizon profile
  * LRO Diviner Polar Resource Product (Paige et al. 2010), PDS Geosciences                -> temperatures, ice depth
  * JPL Horizons (Sun and Earth azimuth/elevation from each site, hourly, a whole year)    -> longest darkness
Each product is a polar stereographic grid (sphere 1737.4 km, true scale at the pole). The 60 m products cover to about
85 S; sites outside them use the 120 m products.

Rasters go into one cache (backend/data/cache/nasa, gitignored; NASA_CACHE overrides) and can be deleted afterwards
(`clean`): the outputs are small. Stdlib + numpy only (the PNG writer is zlib).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import struct
import sys
import tarfile
import time
import zlib
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
DATA = BACKEND / "data"
MISSION = DATA / "mission"
OUT_JSON = DATA / "sites_physics.json"
CACHE = Path(os.environ.get("NASA_CACHE", DATA / "cache" / "nasa"))
LAYERS_OUT = Path(os.environ.get("SITE_LAYERS_OUT", DATA / "cache" / "site_layers"))   # dev: the backend serves these
R_M = 1737400.0

LOLA = "http://imbrium.mit.edu"
PRP_URL = "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/dlre_prp_south.tab"
HORIZONS = "https://ssd.jpl.nasa.gov/api/horizons.api"

# ---------- sources (one per field; the UI shows the short label and links the url) ----------
SRC = {
    "illum": {"label": "LOLA illumination (NASA LRO)", "title": "LRO LOLA average solar illumination, south pole "
              "(Mazarico et al. 2011 method; PDS product AVGVISIB_*_201608)",
              "url": "https://pgda.gsfc.nasa.gov/products/69", "doi": "https://doi.org/10.1016/j.icarus.2010.10.030"},
    "earth": {"label": "LOLA Earth visibility (NASA LRO)", "title": "LRO LOLA average Earth visibility, south pole "
              "(PDS product AVGVISIB_*_201608_EARTH)", "url": "https://pgda.gsfc.nasa.gov/products/69"},
    "psr": {"label": "LOLA shadow map (NASA LRO)", "title": "LRO LOLA permanently shadowed regions, south pole "
            "(PDS product LPSR_*_201608)", "url": "https://pgda.gsfc.nasa.gov/products/69"},
    "slope": {"label": "LOLA slope (NASA LRO)", "title": "LRO LOLA gridded slope, south pole (PDS LDSM_85S_40M, "
              "LDSM_75S_120M)", "url": "https://pds-geosciences.wustl.edu/missions/lro/lola.htm"},
    "dem": {"label": "LOLA topography (NASA LRO)", "title": "LRO LOLA gridded topography (PDS LDEM_75S_120M)",
            "url": "https://pds-geosciences.wustl.edu/missions/lro/lola.htm"},
    "diviner": {"label": "Diviner temperatures (NASA LRO)", "title": "LRO Diviner South Polar Resource Product "
                "(Paige et al. 2010, Science 330:479; PDS LRO-L-DLRE-5-PRP-V2.0)",
                "url": "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/",
                "doi": "https://doi.org/10.1126/science.1187726"},
    "horizons": {"label": "JPL Horizons + LOLA terrain", "title": "JPL Horizons Sun and Earth positions (hourly, "
                 "2026) against the LOLA terrain horizon (LDEM_75S_120M), computed by this pipeline",
                 "url": "https://ssd-api.jpl.nasa.gov/doc/horizons.html"},
    "artemis2024": {"label": "NASA, Oct 2024", "title": "NASA Provides Update on Artemis III Moon Landing Regions "
                    "(Oct 2024)", "url": "https://www.nasa.gov/news-release/nasa-provides-update-on-artemis-iii-moon-landing-regions/"},
    "artemis2022": {"label": "NASA, Aug 2022", "title": "NASA Identifies Candidate Regions for Landing Next Americans "
                    "on Moon (Aug 2022)", "url": "https://www.nasa.gov/news-release/nasa-identifies-candidate-regions-for-landing-next-americans-on-moon/"},
    "criteria": {"label": "NASA, LPSC 2026", "title": "George et al., Artemis III site selection update: downselection "
                 "from thirteen to nine candidate regions (NASA NTRS 20250011660)",
                 "url": "https://ntrs.nasa.gov/citations/20250011660"},
    "lroc": {"label": "LROC NAC mosaics", "title": "LROC NAC low-Sun controlled mosaics of the Artemis III candidate "
             "regions (Henriksen et al. 2023); centre from the product name", "url": "https://data.lroc.im-ldi.com/lroc/rdr_product_select"},
    "regionmap": {"label": "NASA region map", "title": "Position read off NASA's map of the 9 regions (NTRS "
                  "20250011660, Image 1), georeferenced on 6 LROC centres; about +/-5 km",
                  "url": "https://ntrs.nasa.gov/citations/20250011660"},
    "viper": {"label": "NASA VIPER", "title": "NASA VIPER mission overview: top speed 0.72 km/h (0.45 mph); drives on "
              "slopes up to 15 deg (NASA, VIPER lunar operations)",
              "url": "https://ntrs.nasa.gov/api/citations/20230011558/downloads/VIPER%20Mission%20Overview%20Presentation-%20CATIE%20Expo.pdf"},
}

# The 9 candidate regions on NASA's Oct 2024 list. Centres: LROC NAC mosaic products where one exists (the product
# name holds the centre to 0.1 deg), else read off NASA's region map (see SRC["regionmap"]). Regions are about 15 km
# across (NASA 2022), so each region's numbers are for its best-lit spot within 7.5 km, with the range over the region.
REGIONS = [
    {"id": "a3_peak_near_cabeus_b", "name": "Peak near Cabeus B", "lat": -83.6, "lon": 291.2, "pos": "lroc",
     "pos_ref": "NAC_ROI_CABEUSPKLO1_P836S2912"},
    {"id": "a3_haworth", "name": "Haworth", "lat": -86.72, "lon": 338.0, "pos": "regionmap"},
    {"id": "a3_malapert_massif", "name": "Malapert Massif", "lat": -86.0, "lon": 0.3, "pos": "lroc",
     "pos_ref": "NAC_ROI_MALAPERTLO1_P860S0003", "site": "malapert_massif"},
    {"id": "a3_mons_mouton_plateau", "name": "Mons Mouton Plateau", "lat": -84.3, "lon": 30.6, "pos": "lroc",
     "pos_ref": "NAC_ROI_MOUTNPLTLO1_P843S0306"},
    {"id": "a3_mons_mouton", "name": "Mons Mouton", "lat": -85.29, "lon": 30.94, "pos": "regionmap"},
    {"id": "a3_nobile_rim_1", "name": "Nobile Rim 1", "lat": -85.3, "lon": 36.61, "pos": "regionmap"},
    {"id": "a3_nobile_rim_2", "name": "Nobile Rim 2", "lat": -83.9, "lon": 58.7, "pos": "lroc",
     "pos_ref": "NAC_ROI_NOBILE02LO1_P839S0587"},
    {"id": "a3_de_gerlache_rim_2", "name": "de Gerlache Rim 2", "lat": -88.5, "lon": 293.3, "pos": "lroc",
     "pos_ref": "NAC_ROI_DEGERRIMLO1_P885S2933", "site": "de_gerlache_rim"},
    {"id": "a3_slater_plain", "name": "Slater Plain", "lat": -86.92, "lon": 126.84, "pos": "regionmap"},
]
# Regions on NASA's 2022 list of 13 that were dropped in 2024 and that our playable sites stand in for.
DROPPED_2022 = {"shackleton_rim": "Peak Near Shackleton", "connecting_ridge": "Connecting Ridge"}

PAD_SLOPE_DEG = 10.0       # navigator rule: the outpost's spot must be flatter than this (landers need gentle ground)
SITE_RADIUS_KM = 1.0       # our 5 sites: best-lit spot within 1 km of the published point
REGION_RADIUS_KM = 7.5     # a region is about 15 km across
SHALLOW_ICE_M = 1.0        # Diviner: "ice stable within 1 m of the surface" (a rover's drill reaches it)
VIPER_KMH = 0.72           # NASA VIPER's top speed (0.45 mph)
OBSERVER_M = 2.0           # horizon from 2 m above the ground (a person, a solar panel's base)
YEAR = ("2026-01-01", "2027-01-01")
# Overlays: a square polar stereographic map centred on the pole, +/- EXTENT_KM, 2048 px (about 205 m/px).
EXTENT_KM = 210.0
LAYER_PX = 2048


# ======================================================================================================== fetch
RASTERS = {   # name -> archive path (without .IMG/.LBL)
    "ill60": "EXTRAS/ILLUMINATION/IMG/AVGVISIB_85S_060M_201608",
    "earth60": "EXTRAS/ILLUMINATION/IMG/AVGVISIB_85S_060M_201608_EARTH",
    "psr60": "EXTRAS/ILLUMINATION/IMG/LPSR_85S_060M_201608",
    "ill120": "EXTRAS/ILLUMINATION/IMG/AVGVISIB_75S_120M_201608",
    "earth120": "EXTRAS/ILLUMINATION/IMG/AVGVISIB_75S_120M_201608_EARTH",
    "psr120": "EXTRAS/ILLUMINATION/IMG/LPSR_75S_120M_201608",
    "slope40": "DATA/LOLA_GDR/POLAR/IMG/LDSM_85S_40M",
    "slope120": "DATA/LOLA_GDR/POLAR/IMG/LDSM_75S_120M",
    "dem120": "DATA/LOLA_GDR/POLAR/IMG/LDEM_75S_120M",
}


def _get(url: str, dest: Path, stream=None) -> None:
    import httpx
    for attempt in range(4):
        try:
            with httpx.stream("GET", url, timeout=120, follow_redirects=True) as r:
                r.raise_for_status()
                if stream:
                    stream(r.iter_lines())
                    return
                tmp = dest.with_suffix(dest.suffix + ".part")
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
                return
        except Exception as e:   # network hiccup: retry, then give up loudly
            print(f"  retry {attempt + 1}: {type(e).__name__}", file=sys.stderr)
            time.sleep(3 + 5 * attempt)
    raise RuntimeError(f"download failed: {url}")


def fetch() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, path in RASTERS.items():
        base = path.rsplit("/", 1)[1]
        for ext in (".LBL", ".IMG"):
            dest = CACHE / (base + ext)
            if not dest.exists():
                print("fetch", base + ext, file=sys.stderr)
                _get(f"{LOLA}/{path}{ext}", dest)
    prp = CACHE / "diviner_prp_south.npz"
    if not prp.exists():   # 605 MB of ASCII, streamed straight into a 40 MB array file (never stored)
        print("fetch Diviner PRP south (streamed)", file=sys.stderr)
        cols: dict[str, list] = {k: [] for k in ("lon", "lat", "temp_avg", "temp_max", "ice_depth")}

        def take(lines):
            first = True
            for line in lines:
                if first:
                    first = False
                    continue
                p = line.split(",")
                if len(p) < 15:
                    continue
                for k, i in (("lon", 9), ("lat", 10), ("temp_avg", 12), ("temp_max", 13), ("ice_depth", 14)):
                    cols[k].append(float(p[i]))
        _get(PRP_URL, prp, stream=take)
        np.savez_compressed(prp, **{k: np.array(v, np.float32) for k, v in cols.items()})


def clean() -> None:
    shutil.rmtree(CACHE, ignore_errors=True)
    print("removed", CACHE, file=sys.stderr)


# ======================================================================================================== rasters
class Raster:
    """One PDS polar stereographic IMG (int16), read through its label. value = DN * scale + offset."""

    def __init__(self, name: str):
        base = RASTERS[name].rsplit("/", 1)[1]
        lbl = (CACHE / f"{base}.LBL").read_text()
        num = lambda key: float(re.search(rf"^\s*{key}\s*=\s*([-\d.]+)", lbl, re.M).group(1))
        self.name, self.base = name, base
        self.n = int(num("LINES"))
        self.scale_m = num("MAP_SCALE")
        self.off_px = num("LINE_PROJECTION_OFFSET")
        self.k = num("SCALING_FACTOR")
        self.b = num("OFFSET") if name not in ("dem120",) else 0.0   # DEM: height above 1737.4 km, not the radius
        self.dn = np.memmap(CACHE / f"{base}.IMG", dtype="<i2", mode="r", shape=(self.n, self.n))
        self.half_m = self.n / 2 * self.scale_m
        self.nodata = 0 if name.startswith("slope") else None   # LDSM: DN 0 marks a gap (it would read as 45 deg)

    def rc(self, x_m: float, y_m: float) -> tuple[float, float]:
        return self.off_px - y_m / self.scale_m, self.off_px + x_m / self.scale_m

    def covers(self, x_m: float, y_m: float, margin_m: float = 0) -> bool:
        return abs(x_m) + margin_m < self.half_m and abs(y_m) + margin_m < self.half_m

    def disk(self, x_m: float, y_m: float, radius_m: float):
        """Values, x, y (metres) of every pixel within radius of (x, y)."""
        r0, c0 = self.rc(x_m, y_m)
        k = int(math.ceil(radius_m / self.scale_m))
        ri, ci = int(round(r0)), int(round(c0))
        rs, cs = slice(max(0, ri - k), min(self.n, ri + k + 1)), slice(max(0, ci - k), min(self.n, ci + k + 1))
        raw = self.dn[rs, cs]
        v = raw.astype(np.float64) * self.k + self.b
        if self.nodata is not None:
            v[raw == self.nodata] = np.nan
        rr, cc = np.mgrid[rs, cs]
        xx = (cc - self.off_px) * self.scale_m
        yy = (self.off_px - rr) * self.scale_m
        m = (xx - x_m) ** 2 + (yy - y_m) ** 2 <= radius_m ** 2
        return v[m], xx[m], yy[m]

    def at(self, x_m: float, y_m: float) -> float:
        r, c = self.rc(x_m, y_m)
        dn = self.dn[int(round(r)), int(round(c))]
        return float("nan") if dn == self.nodata else float(dn) * self.k + self.b

    def nearest(self, x_m: np.ndarray, y_m: np.ndarray) -> np.ndarray:
        r, c = self.rc(x_m, y_m)
        r = np.clip(np.round(r).astype(int), 0, self.n - 1)
        c = np.clip(np.round(c).astype(int), 0, self.n - 1)
        raw = self.dn[r, c]
        v = raw.astype(np.float64) * self.k + self.b
        if self.nodata is not None:
            v[raw == self.nodata] = np.nan
        return v

    def bilinear(self, r: np.ndarray, c: np.ndarray) -> np.ndarray:
        r = np.clip(r, 0, self.n - 1.001)
        c = np.clip(c, 0, self.n - 1.001)
        r0, c0 = np.floor(r).astype(int), np.floor(c).astype(int)
        fr, fc = r - r0, c - c0
        d = self.dn
        v = (d[r0, c0] * (1 - fr) * (1 - fc) + d[r0, c0 + 1] * (1 - fr) * fc + d[r0 + 1, c0] * fr * (1 - fc)
             + d[r0 + 1, c0 + 1] * fr * fc)
        return v * self.k + self.b


def ps_xy(lat: float, lon: float) -> tuple[float, float]:
    """South polar stereographic x, y (metres), as the LOLA products use them."""
    r = 2 * R_M * math.tan(math.radians(90 + lat) / 2)
    return r * math.sin(math.radians(lon)), r * math.cos(math.radians(lon))


def ps_latlon(x: float, y: float) -> tuple[float, float]:
    r = math.hypot(x, y)
    return -(90 - 2 * math.degrees(math.atan(r / (2 * R_M)))), math.degrees(math.atan2(x, y))


_R: dict[str, Raster] = {}


def raster(name: str) -> Raster:
    if name not in _R:
        _R[name] = Raster(name)
    return _R[name]


def pick(kind: str, x: float, y: float, margin_m: float) -> Raster:
    """The finest product that covers the point (60 m / 40 m inside 85 S, else 120 m)."""
    fine = {"ill": "ill60", "earth": "earth60", "psr": "psr60", "slope": "slope40"}[kind]
    r = raster(fine)
    return r if r.covers(x, y, margin_m) else raster({"ill": "ill120", "earth": "earth120", "psr": "psr120",
                                                       "slope": "slope120"}[kind])


# ======================================================================================================== Diviner
_PRP = None


def prp():
    """Diviner PRP triangles (centre lat/lon -> stereographic x, y), binned on a 1 km grid for nearest lookups."""
    global _PRP
    if _PRP is None:
        d = np.load(CACHE / "diviner_prp_south.npz")
        lat, lon = d["lat"].astype(np.float64), d["lon"].astype(np.float64)
        r = 2 * R_M * np.tan(np.radians(90 + lat) / 2)
        x, y = r * np.sin(np.radians(lon)), r * np.cos(np.radians(lon))
        _PRP = {"x": x, "y": y, "tavg": d["temp_avg"], "tmax": d["temp_max"], "ice": d["ice_depth"]}
    return _PRP


def diviner_near(x: float, y: float, radius_m: float) -> dict:
    p = prp()
    m = (p["x"] - x) ** 2 + (p["y"] - y) ** 2 <= radius_m ** 2
    if not m.any():
        return {}
    i = np.argmin((p["x"] - x) ** 2 + (p["y"] - y) ** 2)
    return {"tavg": float(p["tavg"][i]), "tmax": float(p["tmax"][i]),
            "tavg_range": [float(np.percentile(p["tavg"][m], 10)), float(np.percentile(p["tavg"][m], 90))],
            "tmax_range": [float(np.percentile(p["tmax"][m], 10)), float(np.percentile(p["tmax"][m], 90))]}


def nearest_ice(x: float, y: float, max_depth_m: float = 0.0) -> tuple[float, float, float] | None:
    """Nearest Diviner triangle where water ice is stable at most max_depth_m down: (km, x, y).
    PRP ice_depth: 0 = stable at the surface; -1 (only where the yearly maximum stays under ~100 K) is read as the
    same, colder case; -999 = deeper than 2.87 m or never."""
    p = prp()
    m = (p["ice"] >= -1) & (p["ice"] <= max_depth_m)
    if not m.any():
        return None
    d2 = (p["x"][m] - x) ** 2 + (p["y"][m] - y) ** 2
    i = int(np.argmin(d2))
    return math.sqrt(d2[i]) / 1000, float(p["x"][m][i]), float(p["y"][m][i])


def nearest_psr(x: float, y: float, search_km: float = 40) -> float | None:
    """Distance (km) to the nearest permanently shadowed pixel (LOLA LPSR)."""
    r = pick("psr", x, y, search_km * 1000)
    v, xx, yy = r.disk(x, y, search_km * 1000)
    m = v > 0.75   # DN 20000 -> 1.0 = permanent shadow; 0 -> 0.5 = no data; -20000 -> 0 = lit
    if not m.any():
        return None
    return float(np.sqrt(((xx[m] - x) ** 2 + (yy[m] - y) ** 2).min()) / 1000)


# ======================================================================================================== horizon
def horizon_profile(x: float, y: float, n_az: int = 720, max_km: float = 220.0) -> np.ndarray:
    """Terrain horizon elevation (deg) for azimuths 0..360 (north = away from the pole, east = +lon), from the LOLA
    120 m DEM, with the Moon's curvature. Observer OBSERVER_M above the ground."""
    dem = raster("dem120")
    lat, lon = ps_latlon(x, y)
    h0 = float(dem.bilinear(np.array([dem.rc(x, y)[0]]), np.array([dem.rc(x, y)[1]]))[0]) + OBSERVER_M
    rr = math.hypot(x, y) or 1.0
    north = np.array([x, y]) / rr                       # away from the pole
    east = np.array([math.cos(math.radians(lon)), -math.sin(math.radians(lon))])
    d = np.concatenate([np.arange(240, 5000, 60.0), np.arange(5000, 30000, 120.0), np.arange(30000, max_km * 1000, 240.0)])
    az = np.radians(np.arange(n_az) * 360.0 / n_az)
    out = np.empty(n_az)
    for k, a in enumerate(az):
        u = math.cos(a) * north + math.sin(a) * east
        px, py = x + u[0] * d, y + u[1] * d
        ok = (np.abs(px) < dem.half_m - 240) & (np.abs(py) < dem.half_m - 240)
        r, c = dem.rc(px[ok], py[ok])
        h = dem.bilinear(r, c)
        drop = d[ok] ** 2 / (2 * R_M)                    # the ground curves away
        out[k] = np.degrees(np.arctan2(h - drop - h0, d[ok])).max()
    return out


def horizons_azel(body: str, lat: float, lon: float, start: str, stop: str, step: str = "1 h") -> np.ndarray:
    """[(az_deg, el_deg)] of body from a point on the Moon (JPL Horizons, topocentric, smooth ground). Cached."""
    key = hashlib.sha1(f"{body}|{lat:.4f}|{lon:.4f}|{start}|{stop}|{step}".encode()).hexdigest()[:16]
    f = CACHE / f"horizons_{key}.json"
    if f.exists():
        return np.array(json.loads(f.read_text()))
    import httpx
    params = {"format": "json", "COMMAND": f"'{body}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
              "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'coord@301'", "COORD_TYPE": "'GEODETIC'",
              "SITE_COORD": f"'{lon % 360:.4f},{lat:.4f},0'", "START_TIME": f"'{start}'", "STOP_TIME": f"'{stop}'",
              "STEP_SIZE": f"'{step}'", "QUANTITIES": "'4'", "CSV_FORMAT": "'YES'", "ANG_FORMAT": "'DEG'"}
    for attempt in range(5):
        r = httpx.get(HORIZONS, params=params, timeout=120)
        if r.status_code == 200 and "$$SOE" in r.json().get("result", ""):
            break
        time.sleep(3 + 4 * attempt)
    res = r.json()["result"]
    rows = []
    for line in res.split("$$SOE")[1].split("$$EOE")[0].strip().splitlines():
        p = [s.strip() for s in line.split(",")]
        rows.append([float(p[3]), float(p[4])])
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows))
    return np.array(rows)


SUN_RADIUS_DEG = 0.267     # "sunlit" = any part of the solar disc above the terrain (as the LOLA product counts it)
EARTH_RADIUS_DEG = 0.95    # the Earth's disc seen from the Moon (about 1.9 deg across)


def visible(azel: np.ndarray, prof: np.ndarray, disc_deg: float) -> np.ndarray:
    n = len(prof)
    idx = np.round(azel[:, 0] / 360.0 * n).astype(int) % n
    return azel[:, 1] + disc_deg > prof[idx]


def longest_run(mask: np.ndarray, value: bool) -> int:
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v == value else 0
        best = max(best, cur)
    return best


# ======================================================================================================== numbers
def r1(v, nd=0):
    return None if v is None else (round(v, nd) if nd else int(round(v)))


def measure(lat: float, lon: float, radius_km: float) -> dict:
    """Every number for one place: the best-lit spot within radius_km, its values and the ranges over the disk."""
    x0, y0 = ps_xy(lat, lon)
    rad = radius_km * 1000
    ill = pick("ill", x0, y0, rad)
    v, xx, yy = ill.disk(x0, y0, rad)
    slope = pick("slope", x0, y0, rad)
    sl_at = slope.nearest(xx, yy)
    flat = sl_at <= PAD_SLOPE_DEG                    # nan (a gap in the slope map) is never "flat"
    pool = np.nonzero(flat)[0] if flat.sum() >= 5 else np.arange(len(v))
    hi = np.percentile(v[pool], 99)                  # the best-lit flat spot (p99, so one noisy pixel never wins)
    cand = pool[v[pool] >= hi]
    i = cand[np.argmin((xx[cand] - x0) ** 2 + (yy[cand] - y0) ** 2)]
    bx, by = float(xx[i]), float(yy[i])
    blat, blon = ps_latlon(bx, by)
    earth = pick("earth", bx, by, rad)
    ev, _, _ = earth.disk(x0, y0, rad)
    s_near, _, _ = slope.disk(bx, by, 250)            # the pad: the 500 m around the spot
    s_all, _, _ = slope.disk(x0, y0, rad)
    psr_km = nearest_psr(bx, by)
    ice = nearest_ice(bx, by, 0.0)                    # the ice run: where ice can sit right at the surface
    shallow = nearest_ice(bx, by, SHALLOW_ICE_M)
    temps = diviner_near(bx, by, 600)
    # the ice drive: straight-line distance; the slope along it from the LOLA slope map
    drive = None
    if ice:
        km, ix, iy = ice
        t = np.linspace(0, 1, max(2, int(km * 1000 / 120)))
        sl = pick("slope", (bx + ix) / 2, (by + iy) / 2, km * 500 + 500)
        path = sl.nearest(bx + (ix - bx) * t, by + (iy - by) * t)
        drive = {"km": km, "mean_slope_deg": float(np.nanmean(path)), "max_slope_deg": float(np.nanpercentile(path, 95))}
    return {"spot": {"lat": round(blat, 3), "lon": round(blon % 360, 3), "x_m": round(bx), "y_m": round(by),
                     "offset_km": round(math.hypot(bx - x0, by - y0) / 1000, 2)},
            "sunlight_pct": float(v[i] * 100), "sunlight_range": [float(np.percentile(v, 10) * 100), float(v[i] * 100)],
            "ill_product": ill.base,
            "earth_pct": float(earth.at(bx, by) * 100), "earth_range": [float(np.percentile(ev, 10) * 100),
                                                                       float(np.percentile(ev, 90) * 100)],
            "earth_product": earth.base,
            "slope_deg": float(np.nanmean(s_near)), "slope_range": [float(np.nanpercentile(s_all, 10)),
                                                                    float(np.nanpercentile(s_all, 90))],
            "slope_product": slope.base, "pad_flat": bool(flat[i]),
            "psr_km": psr_km, "ice": ice, "shallow_km": shallow[0] if shallow else None, "drive": drive, "temps": temps}


def darkness(spot: dict) -> dict:
    """Longest darkness and this year's sunlight / Earth time at the spot: Horizons Sun & Earth vs the LOLA horizon."""
    lat, lon = spot["lat"], spot["lon"]
    prof = horizon_profile(spot["x_m"], spot["y_m"])
    sun = horizons_azel("10", lat, lon, *YEAR)
    earth = horizons_azel("399", lat, lon, *YEAR)
    lit = visible(sun, prof, SUN_RADIUS_DEG)
    up = visible(earth, prof, EARTH_RADIUS_DEG)
    return {"year_sun_pct": float(lit.mean() * 100), "longest_dark_h": longest_run(lit, False),
            "year_earth_pct": float(up.mean() * 100), "longest_no_earth_h": longest_run(up, False),
            "horizon_max_deg": float(prof.max()), "profile": prof}


def range_of(lo, hi, nd=0, value=None):
    """[lo, hi] rounded, widened to hold the spot's own value (the spot can be the area's best or flattest)."""
    if value is not None:
        lo, hi = min(lo, value), max(hi, value)
    return [r1(lo, nd), r1(hi, nd)]


def place_record(p: dict, m: dict, dk: dict, kind: str) -> dict:
    t = m["temps"]
    c = lambda k: None if k is None else round(k - 273.15)
    ice_km = m["ice"][0] if m["ice"] else None
    rec = {
        "id": p["id"], "name": p["name"], "kind": kind, "lat": p["lat"], "lon": round(((p["lon"] + 180) % 360) - 180, 3),
        "spot": m["spot"],
        "sunlight_pct": {"value": r1(m["sunlight_pct"]), "range": range_of(*m["sunlight_range"]), "unit": "% of the time",
                         "basis": f"average over 18.6 years (hourly) at the best-lit spot flatter than {PAD_SLOPE_DEG:g} deg "
                                  f"within {p['radius_km']:g} km; range: 10th percentile to the best nearby", "source": "illum", "product": m["ill_product"]},
        "longest_dark_h": {"value": dk["longest_dark_h"], "unit": "hours",
                           "range": [round(dk["longest_dark_h"] / 24, 1), None],
                           "basis": "longest stretch in 2026 with no part of the Sun above the LOLA terrain horizon, "
                                    "seen from 2 m up at the spot", "source": "horizons"},
        "earth_pct": {"value": r1(m["earth_pct"]), "range": range_of(*m["earth_range"], value=m["earth_pct"]), "unit": "% of the time",
                      "basis": "average over 18.6 years at the spot (any part of Earth's disc in view); range over "
                               "the area (10th-90th percentile)", "source": "earth", "product": m["earth_product"]},
        "slope_deg": {"value": r1(m["slope_deg"], 1), "range": range_of(*m["slope_range"], 1, value=m["slope_deg"]), "unit": "degrees",
                      "basis": "mean slope within 250 m of the spot; range over the area (10th-90th percentile)",
                      "source": "slope", "product": m["slope_product"]},
        "psr_km": {"value": None if m["psr_km"] is None else round(m["psr_km"], 1), "unit": "km",
                   "basis": "straight-line distance to the nearest permanently shadowed ground", "source": "psr"},
        "ice_km": {"value": None if ice_km is None else round(ice_km, 1), "unit": "km",
                   "range": [None if m["shallow_km"] is None else round(m["shallow_km"], 1),
                             None if ice_km is None else round(ice_km, 1)],
                   "basis": "straight-line distance to the nearest ground cold enough (Diviner) for water ice to last "
                            f"right at the surface; range starts at ice buried under at most {SHALLOW_ICE_M:g} m. "
                            "Where ice CAN last, not a detection", "source": "diviner"},
        "temp_c": {"value": c(t.get("tavg")), "range": [c(t.get("tavg")), c(t.get("tmax"))], "unit": "deg C",
                   "basis": "Diviner: yearly average to yearly maximum surface temperature at the spot",
                   "source": "diviner"},
        "check": {"year_sun_pct": r1(dk["year_sun_pct"]), "year_earth_pct": r1(dk["year_earth_pct"]),
                  "longest_no_earth_h": dk["longest_no_earth_h"],
                  "note": "2026 only (JPL Horizons vs the LOLA horizon): a cross-check of the 18.6-year LOLA averages"},
    }
    if m["drive"]:
        rec["drive_to_ice"] = {"km": round(m["drive"]["km"], 1), "mean_slope_deg": round(m["drive"]["mean_slope_deg"], 1),
                               "steep_slope_deg": round(m["drive"]["max_slope_deg"], 1), "source": "slope"}
    return rec


def rover_hours(drive: dict | None) -> int | None:
    """Game rule (flagged in the UI): hours one way at NASA VIPER's top speed, slower on slopes (half speed at 15 deg,
    VIPER's design slope limit). At least 1 h."""
    if not drive:
        return None
    speed = VIPER_KMH * max(0.25, 1 - drive["mean_slope_deg"] / 30)
    return max(1, int(math.ceil(drive["km"] / speed)))


def numbers() -> dict:
    sites = json.loads((MISSION / "sites.json").read_text())
    places = []
    for s in sites["sites"]:
        places.append(({"id": s["id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"], "radius_km": SITE_RADIUS_KM},
                       "site"))
    for g in REGIONS:
        places.append(({**g, "radius_km": REGION_RADIUS_KM}, "region"))
    out = []
    for p, kind in places:
        print("measure", p["id"], file=sys.stderr)
        m = measure(p["lat"], p["lon"], p["radius_km"])
        if p.get("id") == "shackleton_floor":
            # the crater floor is the ice site itself: no "best-lit spot" hunt (it would climb the wall)
            m = measure_floor(p)
        dk = darkness(m["spot"])
        rec = place_record(p, m, dk, kind)
        rec["rover_to_ice_h"] = 0 if p["id"] == "shackleton_floor" else rover_hours(m["drive"])
        rec["rover_basis"] = {"game_rule": True, "source": "viper",
                              "basis": f"hours one way to the ice: the straight-line distance at NASA VIPER's top speed "
                                       f"({VIPER_KMH} km/h), slower on slopes (half speed at 15 deg, VIPER's design limit)"}
        if kind == "region":
            rec["status"] = "nasa_2024"
            rec["position"] = {"source": p["pos"], **({"product": p["pos_ref"]} if p.get("pos_ref") else {})}
            if p.get("site"):
                rec["site"] = p["site"]
        else:
            st = next(x for x in sites["sites"] if x["id"] == p["id"])
            rec["status"] = "nasa_2024" if st.get("status") == "nasa_2024" else (
                "dropped_2022" if p["id"] in DROPPED_2022 else "studied")
            if p["id"] in DROPPED_2022:
                rec["was_2022"] = DROPPED_2022[p["id"]]
            rec["playable"] = True
        out.append(rec)
    doc = {"schema": 1, "built": time.strftime("%Y-%m-%d"),
           "note": "Built by backend/pipeline/site_physics.py from NASA LRO (LOLA, Diviner) products and JPL Horizons; "
                   "every field names its source. See backend/data/SOURCES.md.",
           "sources": SRC, "criteria": criteria(), "places": out}
    OUT_JSON.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    print("wrote", OUT_JSON, file=sys.stderr)
    return doc


WINDOW = ("2026-04-08 00:00", "2026-04-18 00:00")   # the mission's 10 days (pipeline/mission_data.py)


def engine(doc: dict) -> None:
    """Carry the real numbers into the mission engine through its existing site parameters (sites.json + the
    ephemeris files), never a fork of the sim:
      * power and comms windows: each hour's terrain horizon at the Sun's and the Earth's azimuth (LOLA, at the outpost
        spot) beside the Horizons elevations the sim already reads (sun_terrain_deg / earth_terrain_deg);
      * the year figure: sunlight_pct = the LOLA 18.6-year average at the spot (was Bussey et al. 2010);
      * the ice run: rover_to_ice_h from the distance to surface-stable ice at VIPER's speed, slower on slopes, and
        rover_slope_power, the extra battery a steep drive costs (both game rules on real distances and slopes)."""
    path = MISSION / "sites.json"
    sites = json.loads(path.read_text())
    byid = {p["id"]: p for p in doc["places"]}
    for s in sites["sites"]:
        p = byid[s["id"]]
        spot = p["spot"]
        prof = horizon_profile(spot["x_m"], spot["y_m"])
        ef = MISSION / f"ephemeris_{s['id']}.json"
        eph = json.loads(ef.read_text())
        sun = horizons_azel("10", s["lat"], s["lon"], *WINDOW)
        earth = horizons_azel("399", s["lat"], s["lon"], *WINDOW)
        assert len(sun) == len(eph["sun_elev_deg"]) == len(earth), s["id"]
        n = len(prof)
        at = lambda azel, disc: [round(float(prof[int(round(a / 360 * n)) % n] - disc), 3) for a, _ in azel]
        eph["sun_terrain_deg"] = at(sun, SUN_RADIUS_DEG)
        eph["earth_terrain_deg"] = at(earth, EARTH_RADIUS_DEG)
        eph["terrain"] = {
            "spot": {k: spot[k] for k in ("lat", "lon")},
            "rule": "in view when the body's centre elevation (Horizons) is above *_terrain_deg: the LOLA terrain "
                    "horizon at the body's azimuth, minus the disc's radius (any part of the disc counts)",
            "source": {"title": SRC["horizons"]["title"], "url": SRC["horizons"]["url"]}}
        ef.write_text(json.dumps(eph, indent=1))
        lit = [e > h for e, h in zip(eph["sun_elev_deg"], eph["sun_terrain_deg"])]
        up = [e > h for e, h in zip(eph["earth_elev_deg"], eph["earth_terrain_deg"])]
        s["sunlight_pct"] = p["sunlight_pct"]["value"]
        s["sunlight_basis"] = "yearly average over 18.6 years, LOLA (NASA LRO), at the outpost spot"
        s["window_sunlit_pct"] = round(100 * sum(lit) / len(lit))
        s["earth_visible_pct"] = round(100 * sum(up) / len(up))
        s["window_basis"] = ("our model of 2026-04-08 to 04-18: JPL Horizons Sun and Earth positions against the real "
                             "LOLA terrain horizon at the outpost spot")
        s["rover_to_ice_h"] = 0 if s.get("ice") else p["rover_to_ice_h"]
        d = p.get("drive_to_ice") or {}
        s["rover_slope_power"] = 0 if s.get("ice") else int(round(d.get("mean_slope_deg", 0) / 5))
        s["physics_id"] = p["id"]
        for src in (SRC["illum"], SRC["horizons"], SRC["diviner"]):
            if not any(x.get("url") == src["url"] and x.get("title") == src["title"] for x in s["sources"]):
                s["sources"].append({"title": src["title"], "url": src["url"]})
    path.write_text(json.dumps(sites, indent=1, ensure_ascii=False) + "\n")
    print("engine fields ->", path, file=sys.stderr)


def measure_floor(p: dict) -> dict:
    x, y = ps_xy(p["lat"], p["lon"])
    ill, earth, slope = pick("ill", x, y, 2000), pick("earth", x, y, 2000), pick("slope", x, y, 2000)
    v, _, _ = ill.disk(x, y, 1000)
    ev, _, _ = earth.disk(x, y, 1000)
    s_near, _, _ = slope.disk(x, y, 250)
    s_all, _, _ = slope.disk(x, y, 1000)
    lat, lon = ps_latlon(x, y)
    ice = nearest_ice(x, y, 0.0)
    shallow = nearest_ice(x, y, SHALLOW_ICE_M)
    return {"spot": {"lat": round(lat, 3), "lon": round(lon % 360, 3), "x_m": round(x), "y_m": round(y), "offset_km": 0.0},
            "sunlight_pct": ill.at(x, y) * 100, "sunlight_range": [float(np.percentile(v, 10) * 100), float(np.percentile(v, 99) * 100)],
            "ill_product": ill.base, "earth_pct": earth.at(x, y) * 100,
            "earth_range": [float(np.percentile(ev, 10) * 100), float(np.percentile(ev, 90) * 100)], "earth_product": earth.base,
            "slope_deg": float(np.nanmean(s_near)), "slope_range": [float(np.nanpercentile(s_all, 10)), float(np.nanpercentile(s_all, 90))], "pad_flat": True,
            "slope_product": slope.base, "psr_km": nearest_psr(x, y), "ice": ice, "shallow_km": shallow[0] if shallow else None,
            "drive": {"km": ice[0], "mean_slope_deg": float(np.nanmean(s_near)), "max_slope_deg": float(np.nanmean(s_near))} if ice else None,
            "temps": diviner_near(x, y, 600)}


def criteria() -> dict:
    """NASA's own criteria for Artemis III regions (NTRS 20250011660; Aug 2022 release), as the navigator scores them."""
    return {
        "source": "criteria",
        "items": [
            {"id": "power", "label": "Power", "field": "sunlight_pct", "why": "Solar illumination for the whole surface stay"},
            {"id": "comms", "label": "Talk to Earth", "field": "earth_pct", "why": "Direct-to-Earth radio: more Earth visibility is preferred"},
            {"id": "ice", "label": "Ice access", "field": "ice_km", "why": "Close enough to permanently shadowed ground for a moonwalk or a drive"},
            {"id": "safety", "label": "Safe landing", "field": "slope_deg", "why": "Low slopes for a safe landing"},
        ],
    }


# ======================================================================================================== layers
def _png(path: Path, rgba: np.ndarray) -> None:
    """RGBA (h, w, 4) or grayscale (h, w) uint8 -> PNG (stdlib zlib)."""
    gray = rgba.ndim == 2
    h, w = rgba.shape[:2]
    raw = b"".join(b"\x00" + rgba[r].tobytes() for r in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0 if gray else 6, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(data)


def _ramp(v: np.ndarray, stops: list[tuple[float, tuple]]) -> np.ndarray:
    xs = [s[0] for s in stops]
    out = np.zeros(v.shape + (4,), np.float64)
    for ch in range(4):
        out[..., ch] = np.interp(v, xs, [s[1][ch] for s in stops])
    return out


LAYERS = {
    "sunlight": {"title": "Sunlight", "unit": "% of the time", "source": "illum", "raster": "ill120",
                 "ramp": [(0, (20, 30, 110, 190)), (0.15, (40, 50, 120, 120)), (0.35, (90, 90, 110, 30)),
                          (0.5, (220, 140, 40, 130)), (0.65, (250, 190, 50, 215)), (0.8, (255, 240, 150, 245))],
                 "mul": 100, "legend": [[0, "0%"], [35, "35%"], [50, "50%"], [65, "65%"], [80, "80%+"]]},
    "slope": {"title": "Slope", "unit": "degrees", "source": "slope", "raster": "slope120",
              "ramp": [(0, (40, 170, 90, 120)), (8, (150, 210, 80, 170)), (15, (250, 190, 50, 200)),
                       (25, (230, 80, 40, 220)), (35, (150, 20, 30, 235))], "mul": 1,
              "legend": [[0, "0°"], [8, "8°"], [15, "15°"], [25, "25°+"]]},
    "ice": {"title": "Ice & shadow", "unit": "", "source": "psr", "raster": "psr120",
            "legend": [["psr", "Never sees the Sun"], ["surface", "Cold enough for ice on the surface"]]},
    "earth": {"title": "Earth view", "unit": "% of the time", "source": "earth", "raster": "earth120",
              "ramp": [(0, (30, 30, 40, 40)), (0.2, (40, 80, 160, 150)), (0.5, (60, 140, 230, 190)),
                       (0.8, (110, 210, 250, 215)), (1.0, (220, 250, 255, 235))], "mul": 100,
              "legend": [[0, "0%"], [20, "20%"], [50, "50%"], [100, "100%"]]},
}


def _grid():
    s = 2 * EXTENT_KM * 1000 / LAYER_PX
    c = (np.arange(LAYER_PX) + 0.5) * s - EXTENT_KM * 1000
    X, Y = np.meshgrid(c, -c)                   # row 0 = +y (lon 0 up, as on NASA's region map)
    return X, Y


def layers() -> dict:
    LAYERS_OUT.mkdir(parents=True, exist_ok=True)
    X, Y = _grid()
    meta = {"schema": 1, "projection": "south polar stereographic, sphere 1737.4 km, lon 0 up, east clockwise",
            "extent_km": EXTENT_KM, "px": LAYER_PX, "layers": {}}
    # the base map every layer sits on: LOLA shaded relief (Sun from the upper left, 45 deg up)
    dem = raster("dem120")
    z = dem.bilinear(*dem.rc(X.ravel(), Y.ravel())).reshape(X.shape)
    px = 2 * EXTENT_KM * 1000 / LAYER_PX
    gy, gx = np.gradient(z * 2.5, px)               # 2.5x vertical exaggeration: crater rims read at this scale
    gy = -gy                                         # rows run north to south
    az, alt = math.radians(315), math.radians(45)
    slope_r = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    shade = np.sin(alt) * np.cos(slope_r) + np.cos(alt) * np.sin(slope_r) * np.cos(az - aspect)
    rel = np.clip(18 + 190 * np.clip(shade, 0, 1) ** 1.6, 0, 255).astype(np.uint8)
    _png(LAYERS_OUT / "relief.png", rel)
    meta["base"] = {"file": "relief.png", "title": "Terrain", "credit": SRC["dem"]["title"], "url": SRC["dem"]["url"],
                    "bytes": (LAYERS_OUT / "relief.png").stat().st_size}
    for lid, L in LAYERS.items():
        r = raster(L["raster"])
        rr, cc = r.rc(X.ravel(), Y.ravel())
        if lid == "ice":
            psr = r.bilinear(rr, cc).reshape(X.shape) > 0.75
            rgba = np.zeros(X.shape + (4,), np.float64)
            rgba[psr] = (60, 110, 240, 190)
            p = prp()
            s = 2 * EXTENT_KM * 1000 / LAYER_PX
            for lo, hi, col in ((-1, 0.0, (215, 252, 255, 250)),):   # ice-stable at the surface (the ice-run target)
                m = (p["ice"] >= lo) & (p["ice"] <= hi)
                ci = ((p["x"][m] + EXTENT_KM * 1000) / s).astype(int)
                ri = ((EXTENT_KM * 1000 - p["y"][m]) / s).astype(int)
                ok = (ci >= 0) & (ci < LAYER_PX) & (ri >= 0) & (ri < LAYER_PX)
                for dr in (0, 1):                   # a Diviner triangle (~0.5 km) covers about 2-3 px here
                    for dc in (0, 1):
                        rgba[np.minimum(ri[ok] + dr, LAYER_PX - 1), np.minimum(ci[ok] + dc, LAYER_PX - 1)] = col
        elif lid == "slope":
            v = r.nearest(X.ravel(), Y.ravel()).reshape(X.shape)
            rgba = _ramp(np.nan_to_num(v, nan=0.0), [(a, col) for a, col in L["ramp"]])
            rgba[np.isnan(v)] = 0                     # a gap in the LOLA slope map stays clear
        else:
            v = r.bilinear(rr, cc).reshape(X.shape)
            rgba = _ramp(v, [(a, col) for a, col in L["ramp"]])
        out = np.clip(rgba, 0, 255).astype(np.uint8)
        f = LAYERS_OUT / f"{lid}.png"
        _png(f, out)
        meta["layers"][lid] = {"file": f.name, "title": L["title"], "unit": L["unit"], "legend": L["legend"],
                               "credit": SRC[L["source"]]["title"], "url": SRC[L["source"]]["url"],
                               "bytes": f.stat().st_size,
                               "ramp": [[round(v * L.get("mul", 1), 2), list(c)] for v, c in L["ramp"]] if "ramp" in L else
                               [["psr", [60, 110, 240, 190]], ["surface", [215, 252, 255, 250]]],
                               **({"credit2": SRC["diviner"]["title"]} if lid == "ice" else {})}
        print("layer", lid, f.stat().st_size, file=sys.stderr)
    (LAYERS_OUT / "layers.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")
    (LAYERS_OUT / "NOTICE").write_text(NOTICE)
    return meta


NOTICE = ("Polar map layers for Outpost Luna's landing-site navigator, built by backend/pipeline/site_physics.py from "
          "NASA Lunar Reconnaissance Orbiter data: LOLA illumination, Earth visibility and permanent shadow (Mazarico et "
          "al. 2011, PGDA product 69), LOLA slope (PDS LDSM_75S_120M) and the Diviner Polar Resource Product (Paige et "
          "al. 2010). NASA data are not subject to copyright in the United States. Not endorsed by NASA.\n")


def pack() -> dict:
    """site-layers tar (deterministic: sorted, mtime 0, uid/gid 0) + sha256, for the first-run asset manifest."""
    files = sorted(p for p in LAYERS_OUT.iterdir() if p.is_file() and not p.name.endswith(".tar"))
    tar = LAYERS_OUT.parent / "outpost-luna-site-layers.tar"
    with tarfile.open(tar, "w", format=tarfile.USTAR_FORMAT) as t:
        for p in files:
            info = tarfile.TarInfo(p.name)
            info.size, info.mtime, info.uid, info.gid, info.mode = p.stat().st_size, 0, 0, 0, 0o644
            with open(p, "rb") as fh:
                t.addfile(info, fh)
    h = hashlib.sha256(tar.read_bytes()).hexdigest()
    entry = {"id": "site_layers", "file": tar.name, "sha256": h, "size": tar.stat().st_size,
             "unpacked_size": sum(p.stat().st_size for p in files), "n_files": len(files),
             "files": [{"path": p.name, "size": p.stat().st_size} for p in files]}
    (LAYERS_OUT.parent / "site_layers.asset.json").write_text(json.dumps(entry, indent=1) + "\n")
    print("tar", tar, entry["size"], h, file=sys.stderr)
    return entry


MANIFESTS = [BACKEND.parent / "desktop" / "assets.manifest.json", BACKEND.parent / "site" / "assets" / "manifest.json"]


def manifest(entry: dict | None = None) -> list[str]:
    """0.3 line: put the optional `site_layers` asset into both first-run manifests (scripts/asset_manifest.py's copies),
    as the LAST entry, in its own block. The url stays null until the tar is uploaded (scripts/upload_assets.py); the
    app works without it ("Map layers downloading…"). A changed sha256 drops a stale url. No manifest (0.2): no-op."""
    entry = entry or json.loads((LAYERS_OUT.parent / "site_layers.asset.json").read_text())
    done = []
    for f in MANIFESTS:
        if not f.exists():
            continue
        doc = json.loads(f.read_text())
        old = next((a for a in doc["assets"] if a["id"] == "site_layers"), None)
        url = old.get("url") if old and old.get("sha256") == entry["sha256"] else None
        new = {"id": "site_layers", "title": "Landing-site map layers (NASA LRO)", "required": False,
               "file": entry["file"], "url": url, "sha256": entry["sha256"], "size": entry["size"],
               "unpacked_size": entry["unpacked_size"], "n_files": entry["n_files"], "env": "SITE_LAYERS_DIR",
               "subdir": "", "licence": ["NOTICE"], "files": entry["files"], "version": "1", "min_app": "0.3.0",
               "max_app": None, "requires": [],
               "note": "Optional: the site navigator's polar map layers (backend/pipeline/site_physics.py layers; "
                       "docs/SITE_NAVIGATOR.md). The app works without them."}
        doc["assets"] = [a for a in doc["assets"] if a["id"] != "site_layers"] + [new]
        f.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        done.append(str(f))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", nargs="?", default="all", choices=["all", "fetch", "numbers", "layers", "clean"])
    a = ap.parse_args()
    if a.step == "clean":
        clean()
        return
    if a.step in ("all", "fetch"):
        fetch()
    if a.step in ("all", "numbers"):
        engine(numbers())
    if a.step in ("all", "layers"):
        layers()
        print("manifests:", manifest(pack()) or "none (0.2 line)", file=sys.stderr)


if __name__ == "__main__":
    main()
