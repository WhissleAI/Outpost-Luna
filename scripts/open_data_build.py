"""Build the open-data views beyond NASA for both courses (docs/OPEN_DATA.md): USGS, ESA/Copernicus and NOAA data,
converted at BUILD time into small pictures in each course's media/ folder, credited in its media/credits.json.

    make open-data            # = both parts below, under uv
    uv run --no-project --with numpy --with pillow --with tifffile --with imagecodecs --with rasterio --with matplotlib \
        python -I scripts/open_data_build.py [moon] [archaeology]

moon         backend/data/courses/moon/media/ (ships in the app, like backend/data; no pack to upload)
  moon_age.jpg     USGS Unified Geologic Map of the Moon, 1:5M, 2020 (Fortezzo, Spudis, Harrel; CC0), its 49 units
                   coloured by the five lunar periods, over the LRO colour map's light and shade. 4096 x 2048.
  moon_height.jpg  LRO LOLA colour shaded relief (USGS Astrogeology, from NASA GSFC's LOLA DEM; public domain). 4096 x 2048.
archaeology  backend/data/courses/archaeology/media/ (the course pack course_archaeology: rebuild + upload)
  s2_mesa_verde_true.jpg   Copernicus Sentinel-2 L2A (ESA), 17 June 2024, true colour (TCI), 37.12-37.36 N, 108.62-108.32 W
  s2_mesa_verde_nir.jpg    the same scene in near-infrared false colour (B08, B04, B03)
  co652_chart.png          the course's own ITRDB CO652 tree-ring chronology (NOAA NCEI), drawn as a chart

Downloads go to a raw cache (OPEN_DATA_RAW, default <repo>/.cache/open_data_raw, gitignored). The app never fetches any
of it. Every output is written with its credit, licence, source_url, alt, size and sha256 merged into credits.json.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("OPEN_DATA_RAW", ROOT / ".cache/open_data_raw"))
COURSES = ROOT / "backend/data/courses"
UA = "outpost-luna-asset-pack"

GEO_ZIP = "https://asc-astropedia.s3.us-west-2.amazonaws.com/Moon/Geology/Ancillary/unified_geologic_map_of_the_moon_raster.zip"
GEO_PAGE = "https://astrogeology.usgs.gov/search/map/unified_geologic_map_of_the_moon_1_5m_2020"
GEO_TIF = "Unified_Geologic_Map_of_the_Moon_RASTER/numerical_versions/Unified_Geologic_Map_of_the_Moon_64ppd.tif"
GEO_CSV = "Unified_Geologic_Map_of_the_Moon_RASTER/Dn_GeologicUnit_RGBcolor.csv"
LOLA_WMS = ("https://planetarymaps.usgs.gov/cgi-bin/mapserv?map=/maps/earth/moon_simp_cyl.map&SERVICE=WMS&VERSION=1.1.1"
            "&REQUEST=GetMap&LAYERS=LOLA_color&SRS=EPSG:4326&BBOX=-180,-90,180,90&WIDTH=4096&HEIGHT=2048"
            "&FORMAT=image/jpeg&STYLES=")
LOLA_PAGE = "https://astrogeology.usgs.gov/search/map/moon_lro_lola_color_shaded_relief_388m_v4"
# the LRO colour map the app's globe already uses (backend/pipeline/fetch_media.py; `make data`)
MOON_MAP = Path(os.environ.get("MOON_MAP", ROOT / "backend/data/media/img/moon4k.jpg"))

# The five lunar periods, oldest first; colours chosen to read apart on a dark globe (and in grey for colour-blind
# viewers: lightness rises with youth). Ages: Wilhelms 1987, USGS Professional Paper 1348.
PERIODS = [
    ("Pre-Nectarian", (120, 72, 160)),
    ("Nectarian", (70, 110, 205)),
    ("Imbrian", (60, 170, 150)),
    ("Eratosthenian", (215, 180, 70)),
    ("Copernican", (255, 236, 170)),
]

# one tile of one pass (17 June 2024, cloud 0.07 %): 12SYG reaches 108.75 W, this orbit's swath covers the whole park
S2_SCENES = ["https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/S2A_12SYG_20240617_0_L2A"]
S2_BOUNDS = (-108.62, 37.12, -108.32, 37.36)   # west, south, east, north: the park's tableland (park level only)


def fetch(url: str, dst: Path) -> Path:
    if dst.exists() and dst.stat().st_size:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  get {url[:110]}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=600) as r, open(dst.with_suffix(".part"), "wb") as f:
        while b := r.read(1 << 20):
            f.write(b)
    dst.with_suffix(".part").replace(dst)
    return dst


def credit(course: str, entry: dict) -> None:
    """Merge one file's credit into the course's media/credits.json (keyed by file), with its size and sha256."""
    media = COURSES / course / "media"
    p = media / entry["file"]
    from PIL import Image
    with Image.open(p) as im:
        entry |= {"width": im.width, "height": im.height}
    entry |= {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    cf = media / "credits.json"
    cur = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else []
    cur = [c for c in cur if c.get("file") != entry["file"]] + [entry]
    cf.write_text(json.dumps(cur, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  wrote {course}/media/{entry['file']} ({entry['bytes'] / 1e6:.2f} MB)")


# ---- the Moon -----------------------------------------------------------------------------------------------------
def moon() -> None:
    import numpy as np
    import tifffile
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    out = COURSES / "moon/media"
    out.mkdir(parents=True, exist_ok=True)
    W, H = 4096, 2048

    # Age map: the geologic map's unit (DN) -> its period -> a colour, light and shade from the LRO map
    z = zipfile.ZipFile(fetch(GEO_ZIP, RAW / "unified_geologic_map_of_the_moon_raster.zip"))
    rows = list(csv.DictReader(io.TextIOWrapper(z.open(GEO_CSV), encoding="utf-8")))
    lut = np.zeros((256, 3), np.float32)
    names = [p for p, _ in PERIODS]
    for r in rows:
        age = r["Unit_Age"].strip()
        if age not in names:
            age = age.split("-")[0]                         # "Eratosthenian-Imbrian" -> the younger bound
        lut[int(r["DN"])] = PERIODS[names.index(age)][1]
    dn = tifffile.imread(io.BytesIO(z.read(GEO_TIF))).astype(np.int16)   # 11520 x 23040, -180..180, 90..-90
    sy, sx = dn.shape[0] / H, dn.shape[1] / W
    dn = dn[(np.arange(H) * sy + sy / 2).astype(int)][:, (np.arange(W) * sx + sx / 2).astype(int)]   # nearest: keep units
    rgb = lut[np.clip(dn, 0, 255)]
    if not MOON_MAP.exists():
        sys.exit(f"{MOON_MAP} is missing: run `make data` (backend/pipeline/fetch_media.py) or set MOON_MAP")
    with Image.open(MOON_MAP) as m:
        lum = np.asarray(m.convert("L").resize((W, H), Image.LANCZOS), np.float32) / 255.0
    shade = 0.35 + 1.0 * (lum / max(float(np.percentile(lum, 99)), 1e-3))
    img = np.clip(rgb * np.clip(shade, 0, 1.25)[..., None], 0, 255).astype(np.uint8)
    Image.fromarray(img).save(out / "moon_age.jpg", "JPEG", quality=84, optimize=True, progressive=True)
    credit("moon", {
        "file": "moon_age.jpg",
        "title": "Unified Geologic Map of the Moon, 1:5M, 2020: units coloured by period (equirectangular)",
        "credit": "USGS Astrogeology Science Center: Fortezzo, Spudis and Harrel (2020), Unified Geologic Map of the Moon; "
                  "shading from the NASA LRO colour map",
        "licence": "CC0 (USGS: \"CC0, but please cite authors\")",
        "source_url": GEO_PAGE,
        "alt": "Map of the whole Moon coloured by the age of its surface: purple oldest highlands, blue and green basins, "
               "gold younger lava plains and pale yellow young craters.",
        "derived": "64 px/degree unit raster -> 4096 x 2048 nearest; each unit's Unit_Age (the younger bound for a "
                   "two-period unit) -> one of 5 colours; times the LRO colour map's brightness.",
    })

    # Height map: USGS's LOLA colour shaded relief, from its map service at the globe's own size
    raw = fetch(LOLA_WMS, RAW / "lola_color_4096.jpg")
    with Image.open(raw) as im:
        im.convert("RGB").resize((W, H)).save(out / "moon_height.jpg", "JPEG", quality=84, optimize=True, progressive=True)
    credit("moon", {
        "file": "moon_height.jpg",
        "title": "Moon LRO LOLA Color Shaded Relief 388m v4 (equirectangular)",
        "credit": "USGS Astrogeology Science Center, from the LRO LOLA elevation model (NASA Goddard Space Flight Center)",
        "licence": "Public domain (USGS: \"Use Constraints: Public domain\")",
        "source_url": LOLA_PAGE,
        "alt": "Map of the whole Moon coloured by height: blue and purple low basins, green plains, orange and red high "
               "far-side highlands, with craters shaded in relief.",
    })


# ---- Archaeology ----------------------------------------------------------------------------------------------------
def archaeology() -> None:
    import numpy as np
    from PIL import Image
    out = COURSES / "archaeology/media"
    items = [json.loads(fetch(u, RAW / f"s2_{u.rsplit('/', 1)[1]}.json").read_text()) for u in S2_SCENES]
    item = items[0]
    when = item["properties"]["datetime"][:10]
    W = 1600

    def read(href, bands=None):
        import rasterio
        from rasterio.vrt import WarpedVRT
        from rasterio.transform import from_bounds
        from rasterio.enums import Resampling
        w, s, e, n = S2_BOUNDS
        h = int(round(W * (n - s) / (e - w)))
        # the output grid itself (a lat/lon plate carree of the bounds): no window clipping at a tile's edge
        with rasterio.Env(AWS_NO_SIGN_REQUEST="YES", GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            with rasterio.open(href) as src, WarpedVRT(src, crs="EPSG:4326", transform=from_bounds(w, s, e, n, W, h),
                                                       width=W, height=h, resampling=Resampling.bilinear) as v:
                return v.read(bands)

    def mosaic(asset, bands):
        a = None
        for it in items:
            b = read(it["assets"][asset]["href"], bands)
            a = b if a is None else np.where((a == 0).all(axis=0, keepdims=True), b, a)
        return a

    tci = mosaic("visual", [1, 2, 3]).astype(np.float32)
    if (tci == 0).all(axis=0).mean() > 0.001:
        sys.exit("Sentinel-2: the scene does not cover the whole box")
    # TCI is already 8-bit; a gentle stretch so the tableland reads on a small card
    lo, hi = np.percentile(tci, 1), np.percentile(tci, 99.5)
    tci = np.clip((tci - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
    Image.fromarray(np.moveaxis(tci, 0, -1)).save(out / "s2_mesa_verde_true.jpg", "JPEG", quality=84, optimize=True)
    nir, red, green = (mosaic(b, [1])[0].astype(np.float32) for b in ("nir", "red", "green"))
    fc = np.stack([nir, red, green])
    for i in range(3):
        lo, hi = np.percentile(fc[i], 1), np.percentile(fc[i], 99.5)
        fc[i] = np.clip((fc[i] - lo) / (hi - lo), 0, 1) ** 0.9 * 255
    Image.fromarray(np.moveaxis(fc.astype(np.uint8), 0, -1)).save(out / "s2_mesa_verde_nir.jpg", "JPEG", quality=84, optimize=True)
    common = {"licence": "Free, full and open (Copernicus Sentinel data legal notice, Regulation (EU) 1159/2013)",
              "source_url": "https://registry.opendata.aws/sentinel-2-l2a-cogs/",
              "licence_url": "https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
              "scene": " + ".join(it["id"] for it in items), "bounds": dict(zip(("west", "south", "east", "north"), S2_BOUNDS))}
    credit("archaeology", {"file": "s2_mesa_verde_true.jpg", **common,
        "title": f"Mesa Verde, Sentinel-2 true colour ({when})",
        "credit": f"Contains modified Copernicus Sentinel data {when[:4]} (ESA)",
        "alt": "Satellite view of the Mesa Verde tableland in summer: dark green pinyon-juniper forest, paler burned "
               "areas, and canyons running south."})
    credit("archaeology", {"file": "s2_mesa_verde_nir.jpg", **common,
        "title": f"Mesa Verde, Sentinel-2 near-infrared false colour ({when})",
        "credit": f"Contains modified Copernicus Sentinel data {when[:4]} (ESA)",
        "alt": "The same view of Mesa Verde in false colour: living plants bright red, burned and bare ground grey-green."})

    # The tree-ring chart: the course's own CO652 chronology, 25-year smoothing, the late-1200s drought marked
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = json.loads((COURSES / "archaeology/rings/itrdb_co652.json").read_text())
    yrs, idx, depth = (np.array(d[k], float) for k in ("years", "index", "sample_depth"))
    keep = (depth >= 5) & (yrs <= 2000)
    yrs, idx = yrs[keep], idx[keep]
    k = 25
    sm = np.convolve(idx, np.ones(k) / k, mode="same")
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    fig.patch.set_facecolor("#10151c")
    ax.set_facecolor("#10151c")
    ax.axvspan(1276, 1299, color="#e08a2e", alpha=0.6, lw=0)
    ax.text(1288, 1.42, "1276–1299", color="#f1b57a", ha="center", fontsize=9)
    ax.plot(yrs, idx, color="#6e8aa6", lw=0.5, alpha=0.3)
    ax.plot(yrs[k:-k], sm[k:-k], color="#e8eef5", lw=1.8)
    ax.axhline(1.0, color="#8b97a6", lw=0.6, ls=(0, (3, 3)))
    ax.set_xlim(yrs[0], yrs[-1])
    ax.set_ylim(0.3, 1.55)
    ax.set_ylabel("ring width (1 = average)", color="#c9d3de", fontsize=9)
    ax.set_xlabel("year (CE)", color="#c9d3de", fontsize=9)
    ax.set_title("Mesa Verde Douglas-fir tree rings: wide = wet years, narrow = dry", color="#e8eef5", fontsize=11, loc="left")
    ax.tick_params(colors="#c9d3de", labelsize=8)
    for s in ax.spines.values():
        s.set_color("#3a4656")
    fig.tight_layout()
    fig.savefig(out / "co652_chart.png", facecolor=fig.get_facecolor())
    plt.close(fig)
    from PIL import Image as _I
    with _I.open(out / "co652_chart.png") as im:   # a palette PNG is a third the size and looks the same
        im.convert("RGB").quantize(64).save(out / "co652_chart.png", optimize=True)
    credit("archaeology", {"file": "co652_chart.png",
        "title": "Mancos River + Mesa Verde Douglas-fir ring-width chronology (ITRDB CO652), years with 5+ trees",
        "credit": "Data: Stahle et al. (2015), NOAA NCEI World Data Service for Paleoclimatology (ITRDB CO652); chart by Outpost Luna",
        "licence": "Open data from NOAA NCEI, cited as the study asks",
        "source_url": "https://www.ncei.noaa.gov/access/paleo-search/study/19080",
        "alt": "Line chart of tree-ring width at Mesa Verde from about 900 to 2000 CE, with a shaded band at 1276 to 1299 "
               "where the rings are narrow."})


def main() -> int:
    want = set(sys.argv[1:]) or {"moon", "archaeology"}
    if "moon" in want:
        print("Moon: USGS geologic age map + LOLA height map")
        moon()
    if "archaeology" in want:
        print("Archaeology: Sentinel-2 (ESA/Copernicus) + NOAA tree-ring chart")
        archaeology()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
