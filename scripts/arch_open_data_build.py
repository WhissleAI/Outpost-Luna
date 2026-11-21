"""Build the Archaeology course's open-data media (docs/COURSES.md §2, docs/MEDIA.md "Open data"): charts, a Sentinel-2
picture and a map layer, written into backend/data/courses/archaeology/media/ with their credits.

    make arch-open-data      # = uv run --no-project --with pillow --with pyshp --with rdata --with pandas \
                             #       --with rasterio --with certifi python -I scripts/arch_open_data_build.py

Everything is fetched at BUILD time (the app never fetches it) into a raw cache of its own (ARCH_DATA_RAW, default
<repo>/.cache/arch_open_data_raw, gitignored). Each source is pinned by sha256 (SOURCES): a changed upstream file stops
the build (`--repin` prints the new pins after you have re-checked its licence). Nothing downloaded is ever executed;
the R data file is parsed by `rdata` (a reader, no R), the shapefiles by `pyshp`, the GeoTIFF window by rasterio.

Outputs (media/, committed; the course pack carries them; app/course_library.py validates them):
  drought_mesa_verde.json      NOAA NCEI study 19059 (Stahle et al. 2015): cool-season moisture balance AD 722-2011
  tree_rings_1200_1320.json    ITRDB CO652 (already in rings/) + NM597, NM589, CO067 ring-width indices, AD 1200-1320
  radiocarbon_four_corners.json  p3k14c (CC0): dates per century in a Four Corners box. NO coordinates, NO site names;
                               samples on human remains or anything that could be (bone, collagen, teeth, hair,
                               coprolites/feces, Homo sapiens) and perishable artifacts that may be grave goods (textile,
                               leather, basketry, sandals) are excluded BEFORE counting: only a whitelist of materials
                               (charcoal, wood, seeds/maize, sediment) is kept
  s2_mesa_verde.jpg            Copernicus Sentinel-2 L2A true colour (AWS Open Data COG, Element 84 STAC), one window
  layer_rivers_states.png      Natural Earth 10m state lines + rivers, transparent, equirectangular over the overlay box
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("ARCH_DATA_RAW", ROOT / ".cache/arch_open_data_raw"))
D = ROOT / "backend/data/courses/archaeology"
MEDIA = D / "media"
UA = "outpost-luna-asset-pack"
ACCESSED = "2026-11-20"
NCEI_TERMS = ("No licence on the NCEI record (data-licence field empty; access constraints: None). NCEI use constraint: "
              "cite the publication, online resource and DOI.")

# url, sha256 of the file as downloaded (re-check the licence before re-pinning)
SOURCES = {
    "mv_ppe": ("https://www.ncei.noaa.gov/pub/data/paleo/treering/reconstructions/northamerica/usa/colorado/mesaverde2015p-pe.txt", None),
    "nm597": ("https://www.ncei.noaa.gov/pub/data/paleo/treering/chronologies/northamerica/usa/nm597.crn", None),
    "nm589": ("https://www.ncei.noaa.gov/pub/data/paleo/treering/chronologies/northamerica/usa/nm589.crn", None),
    "co067": ("https://www.ncei.noaa.gov/pub/data/paleo/treering/chronologies/northamerica/usa/co067.crn", None),
    "p3k14c": ("https://raw.githubusercontent.com/people3k/p3k14c/main/data/p3k14c_data.rda", None),
    "ne_states": ("https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces_lines.zip", None),
    "ne_rivers": ("https://naciscdn.org/naturalearth/10m/physical/ne_10m_rivers_lake_centerlines.zip", None),
    "ne_rivers_na": ("https://naciscdn.org/naturalearth/10m/physical/ne_10m_rivers_north_america.zip", None),   # supplement: Animas, Dolores, Chaco
}
PINS_FILE = Path(__file__).with_name("arch_open_data.pins.json")   # {key: sha256}; written by --repin

# The Library's overlay box (library.json overlays[0]): the layer lines up with the USGS picture under it
BOX = {"west": -110.2, "south": 35.7, "east": -106.9, "north": 38.0}
# p3k14c region: Mesa Verde, Hovenweep, Chimney Rock, Chaco and the San Juan basin (region level only)
RC_BOX = {"west": -110.0, "south": 36.0, "east": -107.0, "north": 38.0}
RC_KEEP = re.compile(r"^(charcoal|wood|seeds?|sediment)$", re.I)
RC_DROP = re.compile(r"bone|collagen|tooth|teeth|human|homo|burial|grave|skelet|cremat|apatite|dentin|enamel|hair|skin|"
                     r"tissue|mumm|coprolite|fec|cemeter|ossuar|textile|leather|bask|sandal|cordage|fiber|feather", re.I)
# Sentinel-2: one cloud-free summer scene (UTM 12 tile 12SYG holds all of Mesa Verde; 13SBB ends at -108.5); the item
# id pins it
S2_ITEM = "S2B_12SYG_20250925_0_L2A"   # 0.01 % cloud, no no-data over the box (June and July passes clip it)
S2_STAC = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items/" + S2_ITEM
S2_BOX = (-108.62, 37.12, -108.30, 37.36)   # west, south, east, north: Mesa Verde's tableland and its canyons
CHRONS = [   # key, ITRDB code, label (short), title, study, doi, investigators
    ("nm597", "NM597", "Gobernador (NM)", "Dean - Gobernador Archaeological+Modern - PIPO - ITRDB NM597", 22323,
     "https://doi.org/10.25921/h39a-8q18", "Dean, J.S.; Robinson, W.J."),
    ("nm589", "NM589", "Chuska Mts (NM)", "Guiterman - Narbona Pass, Chuska Mountains - PIPO - ITRDB NM589", 19280,
     "https://doi.org/10.25921/x84g-ny11", "Guiterman, C.H.; Baisan, C.H.; Dean, J.S."),
    ("co067", "CO067", "Dolores (CO)", "Harlan - Dolores - PIED - ITRDB CO067", 3467,
     "https://doi.org/10.25921/1k7k-0h18", "Harlan, T.P."),
]


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pins() -> dict:
    try:
        return json.loads(PINS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def fetch(key: str, repin: bool) -> bytes:
    url = SOURCES[key][0]
    dst = RAW / key / url.rsplit("/", 1)[1]
    if not (dst.exists() and dst.stat().st_size):
        dst.parent.mkdir(parents=True, exist_ok=True)
        import ssl
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300, context=ctx) as r:
            dst.write_bytes(r.read())
    b = dst.read_bytes()
    want = pins().get(key)
    if want and sha256(b) != want and not repin:
        sys.exit(f"{key}: {url} changed upstream (sha256 {sha256(b)[:12]} != pinned {want[:12]}); re-check it, then --repin")
    return b


def write_json(name: str, obj) -> Path:
    p = MEDIA / name
    p.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return p


def credit(p: Path, **kw) -> dict:
    b = p.read_bytes()
    out = {"file": p.name, **kw, "bytes": len(b), "sha256": sha256(b)}
    if p.suffix in (".jpg", ".png"):
        from PIL import Image
        with Image.open(p) as im:
            out["width"], out["height"] = im.size
    return out


# ------------------------------------------------------------------------------------------------- charts
def drought(repin: bool) -> dict:
    """Cool-season (Sept-May) P-PE reconstruction, each year + its 10-year spline, AD 722-2011."""
    txt = fetch("mv_ppe", repin).decode("utf-8", "replace")
    rows = [r.split("\t") for r in txt.splitlines() if r and not r.startswith("#") and r[0].isdigit()]
    yearly, smooth = [], []
    for r in rows:
        y, rec, rec10 = int(r[0]), float(r[2]), float(r[3])
        if rec > -99:
            yearly.append([y, rec])
        if rec10 > -99:
            smooth.append([y, rec10])
    chart = {"format": "outpost-luna-chart", "version": 1, "type": "line", "x_format": "year", "zero": True,
             "x_label": "Year", "y_label": "Wetter (+) or drier (-)",
             "series": [{"label": "Smoothed (10-year)", "points": smooth},
                        {"label": "Each year", "points": yearly, "faint": True}],
             "source": "NOAA NCEI study 19059, column P-PESept-Mayrec / rec10yr (cool-season P-PE)"}
    # the faint yearly line draws under the smoothed one: series order is draw order, so swap
    chart["series"] = chart["series"][::-1]
    p = write_json("drought_mesa_verde.json", chart)
    print(f"  drought  {len(yearly)} years {yearly[0][0]}-{yearly[-1][0]}  {p.stat().st_size / 1e3:.0f} KB")
    return credit(p, title="Mesa Verde, Colorado 1,300 Year Moisture Balance Reconstructions (cool-season P-PE)",
                  credit="Stahle et al. 2015, NOAA/WDS Paleoclimatology (NCEI)", licence=NCEI_TERMS, licence_class="by",
                  licence_evidence="https://www.ncei.noaa.gov/pub/data/metadata/published/paleo/iso/xml/noaa-recon-19059.xml",
                  source_url="https://www.ncei.noaa.gov/access/paleo-search/study/19059",
                  data_url=SOURCES["mv_ppe"][0],
                  citation=("Stahle, D.W.; Edmondson, J.R.; Burns, J.N.; Stahle, D.K.; Burnette, D.J.; Kvamme, E.; "
                            "LeQuesne, C.; Therrell, M.D. (2015-07-21): NOAA/WDS Paleoclimatology - Mesa Verde, Colorado "
                            "1,300 Year Moisture Balance Reconstructions. NOAA NCEI. https://doi.org/10.25921/zgv1-tw70. "
                            f"Accessed {ACCESSED}."),
                  alt="A line chart of wet and dry years at Mesa Verde from AD 722 to 2011, with the 1276-1299 Great Drought marked.")


def read_crn(b: bytes) -> dict[int, float]:
    """A Tucson-format .crn: <6-char id><4-char decade> then 10 x (4-digit index x1000, 3-digit sample depth)."""
    out = {}
    for line in b.decode("latin-1").splitlines():
        line = line.rstrip("\r")
        m = re.match(r"^.{6}([ \d-]{4})((?:[ \d-]{4}[ \d]{3}){1,10})", line)   # trailing text (a site code) is ignored
        if not m or not m.group(1).strip().lstrip("-").isdigit():   # header lines: "<id> 1 <name>"
            continue
        dec = int(m.group(1))
        vals = m.group(2)
        for k in range(len(vals) // 7):
            v = vals[k * 7: k * 7 + 4].strip()
            if v and v.lstrip("-").isdigit() and int(v) != 9990:
                out[dec + k] = int(v) / 1000
    return out


def tree_rings(repin: bool) -> list[dict]:
    co652 = json.loads((D / "rings/itrdb_co652.json").read_text())
    lo, hi = 1200, 1320
    series = [{"label": "Mesa Verde Douglas-fir (CO652)", "short": "Mesa Verde (CO)",
               "points": [[y, round(v, 3)] for y, v in zip(co652["years"], co652["index"]) if lo <= y <= hi]}]
    creds = []
    for key, code, short, title, study, doi, who in CHRONS:
        c = read_crn(fetch(key, repin))
        pts = [[y, round(c[y], 3)] for y in sorted(c) if lo <= y <= hi]
        if len(pts) < 40 or not 0.5 < sum(v for _, v in pts) / len(pts) < 1.5:
            sys.exit(f"{code}: unexpected chronology ({len(pts)} years in {lo}-{hi})")
        series.append({"label": f"{short.split(' (')[0]} ({code})", "short": short, "points": pts})
        creds.append(f"{who} ({title}), NOAA/WDS Paleoclimatology, {doi}")
    chart = {"format": "outpost-luna-chart", "version": 1, "type": "line", "x_format": "year",
             "x_label": "Year", "y_label": "Ring width (1 = average)", "series": series,
             "source": "ITRDB standard chronologies (.crn) as published; CO652 computed from its raw rings (rings/itrdb_co652.json)"}
    p = write_json("tree_rings_1200_1320.json", chart)
    print(f"  rings    {len(series)} chronologies AD {lo}-{hi}  {p.stat().st_size / 1e3:.0f} KB")
    return [credit(p, title="Four tree-ring chronologies of the Four Corners, AD 1200-1320 (ITRDB CO652, NM597, NM589, CO067)",
                   credit="International Tree-Ring Data Bank, NOAA/WDS Paleoclimatology (NCEI): Stahle et al. (CO652); "
                          + "; ".join(creds),
                   licence=NCEI_TERMS, licence_class="by",
                   licence_evidence="NCEI study records 19080, 22323, 19280, 3467 (dataLicense empty; ISO metadata use constraint: cite)",
                   source_url="https://www.ncei.noaa.gov/products/paleoclimatology/tree-ring",
                   data_url=[SOURCES[k][0] for k, *_ in CHRONS],
                   alt="Four wiggly lines of tree-ring widths from AD 1200 to 1320 that rise and fall together; narrow rings line up in drought years.")]


def radiocarbon(repin: bool) -> dict:
    import rdata
    raw = fetch("p3k14c", repin)
    tmp = RAW / "p3k14c" / "p3k14c_data.rda"
    df = rdata.read_rda(str(tmp))["p3k14c_data"]
    box = df[(df.Lat >= RC_BOX["south"]) & (df.Lat <= RC_BOX["north"]) & (df.Long >= RC_BOX["west"]) & (df.Long <= RC_BOX["east"])]
    kept, dropped, older = [], 0, 0
    for _, r in box.iterrows():
        mat = str(r["Material"]) if str(r["Material"]) != "<NA>" else ""
        text = " ".join(str(r[c]) for c in ("Material", "Taxa", "Period", "SiteName") if str(r[c]) not in ("<NA>", "nan"))
        if not RC_KEEP.match(mat.strip()) or RC_DROP.search(text) or not r["Age"] == r["Age"]:
            dropped += 1
            continue
        kept.append(1950 - int(r["Age"]))   # radiocarbon years BP -> an approximate (uncalibrated) year
    lo, hi = -1000, 1600
    bins = {b: 0 for b in range(lo, hi, 100)}
    for y in kept:
        b = y // 100 * 100
        if b in bins:
            bins[b] += 1
        elif b < lo:
            older += 1
    chart = {"format": "outpost-luna-chart", "version": 1, "type": "bar", "x_format": "year",
             "x_label": "Century (radiocarbon age, not calibrated)", "y_label": "Dated samples",
             "series": [{"label": "Radiocarbon dates", "points": [[b, n] for b, n in bins.items()]}],
             "kept": len(kept), "older": older, "excluded": dropped,
             "method": ("p3k14c records in the region box only; materials whitelisted (charcoal, wood, seeds, sediment); any "
                        "bone, collagen, teeth, hair, coprolites, Homo sapiens or possible grave goods excluded; counted per "
                        "century of (1950 - radiocarbon age). No coordinates, sites or lab ids are kept.")}
    p = write_json("radiocarbon_four_corners.json", chart)
    print(f"  14C      kept {len(kept)} (older than {lo}: {older}), excluded {dropped}  {p.stat().st_size / 1e3:.0f} KB")
    del raw
    return credit(p, title="Radiocarbon dates in the Four Corners region, per century (p3k14c)",
                  credit="p3k14c (Bird et al. 2022, Scientific Data 9:27), aggregated by Outpost Luna",
                  licence="CC0 1.0 (data); attribution requested", licence_class="cc0",
                  licence_evidence="https://github.com/people3k/p3k14c#licenses (\"Data: CC0 1.0\")",
                  source_url="https://www.p3k14c.org/", data_url=SOURCES["p3k14c"][0],
                  citation=("Bird, D., Miranda, L., Vander Linden, M. et al. p3k14c, a synthetic global database of "
                            "archaeological radiocarbon dates. Sci Data 9, 27 (2022). https://doi.org/10.1038/s41597-022-01118-7"),
                  sensitivity="Region-level counts only: no coordinates, site names or sample ids; human remains and possible grave goods excluded.",
                  alt="A bar chart of how many radiocarbon dates come from each century in the Four Corners region, rising after AD 500.")


# ------------------------------------------------------------------------------------------------- pictures
def sentinel() -> dict:
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds
    import ssl
    import certifi
    req = urllib.request.Request(S2_STAC, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as r:
        item = json.loads(r.read())
    href, date = item["assets"]["visual"]["href"], item["properties"]["datetime"][:10]
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", AWS_NO_SIGN_REQUEST="YES"):
        with rasterio.open(href) as src:
            b = transform_bounds("EPSG:4326", src.crs, *S2_BOX)
            a = src.read(window=from_bounds(*b, transform=src.transform))   # 3 x H x W, uint8 true colour (TCI)
    if a.shape[1] < 1000 or a.shape[2] < 1000 or (a.max(axis=0) == 0).mean() > 0.005:
        sys.exit(f"{S2_ITEM}: the window is clipped or has no-data ({a.shape}); pick a tile that covers S2_BOX")
    px = np.transpose(a, (1, 2, 0)).astype(np.float32)
    lo, hi = np.percentile(px, 0.5), np.percentile(px, 99.7)   # a gentle stretch: "modified" Copernicus data
    px = np.clip((px - lo) / max(1.0, hi - lo), 0, 1) ** 0.9 * 255
    im = Image.fromarray(px.astype(np.uint8), "RGB")
    im.thumbnail((2000, 2000), Image.LANCZOS)
    p = MEDIA / "s2_mesa_verde.jpg"
    im.save(p, "JPEG", quality=84, optimize=True, progressive=True)
    year = date[:4]
    print(f"  s2       {S2_ITEM} {im.size[0]}x{im.size[1]}  {p.stat().st_size / 1e6:.2f} MB")
    return credit(p, title=f"Mesa Verde from Sentinel-2 ({date}, natural colour, 10 m)",
                  credit=f"Contains modified Copernicus Sentinel data {year}",
                  licence=("Copernicus Sentinel data terms (free, full and open: reproduction, distribution, adaptation and "
                           "commercial use allowed; the source must be credited as \"Contains modified Copernicus Sentinel "
                           "data [year]\")"),
                  licence_class="by",
                  licence_evidence="https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice",
                  source_url="https://registry.opendata.aws/sentinel-2-l2a-cogs/",
                  data_url=f"{S2_STAC} (asset visual, window {S2_BOX})", acquired=date,
                  alt="Natural-colour satellite view of the Mesa Verde tableland, its long fingers cut by branching canyons, with green farm fields at the top left.")


def natural_earth(repin: bool) -> dict:
    import shapefile
    from PIL import Image, ImageDraw
    W = 2048
    H = round(W * (BOX["north"] - BOX["south"]) / (BOX["east"] - BOX["west"]))
    S = 2   # draw at 2x, then downsample (smooth lines)
    im = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    xy = lambda lon, lat: ((lon - BOX["west"]) / (BOX["east"] - BOX["west"]) * W * S,  # noqa: E731
                           (BOX["north"] - lat) / (BOX["north"] - BOX["south"]) * H * S)

    def shapes(key):
        z = zipfile.ZipFile(io.BytesIO(fetch(key, repin)))
        stem = [n for n in z.namelist() if n.endswith(".shp")][0][:-4]
        r = shapefile.Reader(shp=io.BytesIO(z.read(stem + ".shp")), dbf=io.BytesIO(z.read(stem + ".dbf")),
                             shx=io.BytesIO(z.read(stem + ".shx")))
        for sr in r.iterShapeRecords():
            if not hasattr(sr.shape, "bbox"):
                continue
            bb = sr.shape.bbox
            if bb[2] < BOX["west"] or bb[0] > BOX["east"] or bb[3] < BOX["south"] or bb[1] > BOX["north"]:
                continue
            rec = {k.lower(): v for k, v in sr.record.as_dict().items()}
            pts, parts = sr.shape.points, list(sr.shape.parts) + [len(sr.shape.points)]
            for a, b in zip(parts, parts[1:]):
                yield rec, [xy(x, y) for x, y in pts[a:b]]
    names = set()
    for rec, line in [*shapes("ne_rivers"), *shapes("ne_rivers_na")]:
        if rec.get("featurecla") not in ("River", "River (Intermittent)"):
            continue
        names.add(rec.get("name"))
        dry = "Intermittent" in rec["featurecla"]
        dr.line(line, fill=(5, 7, 11, 150), width=(5 if dry else 8) * S // 2, joint="curve")
        dr.line(line, fill=(159, 211, 255, 235) if dry else (79, 179, 255, 255), width=(2 if dry else 4) * S // 2, joint="curve")
    for rec, line in shapes("ne_states"):
        dr.line(line, fill=(5, 7, 11, 170), width=7 * S // 2, joint="curve")
        dr.line(line, fill=(255, 255, 255, 255), width=3 * S // 2, joint="curve")
    im = im.resize((W, H), Image.LANCZOS)
    p = MEDIA / "layer_rivers_states.png"
    im.save(p, "PNG", optimize=True)
    print(f"  layer    {W}x{H} rivers {sorted(n for n in names if n)}  {p.stat().st_size / 1e3:.0f} KB")
    return credit(p, title="State lines and rivers of the Four Corners (Natural Earth 1:10m)",
                  credit="Made with Natural Earth", licence="Public domain (Natural Earth terms of use)", licence_class="pd",
                  licence_evidence="https://www.naturalearthdata.com/about/terms-of-use/",
                  source_url="https://www.naturalearthdata.com/",
                  data_url=[SOURCES["ne_states"][0], SOURCES["ne_rivers"][0], SOURCES["ne_rivers_na"][0]],
                  rivers=sorted(n for n in names if n),
                  alt="Thin white state lines meeting at the Four Corners and blue lines for the San Juan, Animas, Dolores and other rivers.")


def merge_credits(new: list[dict]) -> None:
    p = MEDIA / "credits.json"
    cur = json.loads(p.read_text(encoding="utf-8"))
    by = {c["file"]: c for c in new}
    out = [by.pop(c["file"], c) for c in cur] + list(by.values())
    p.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repin", action="store_true", help="accept changed upstream files and rewrite the sha256 pins")
    ap.add_argument("--only", help="comma-separated: drought,rings,c14,s2,layer")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else {"drought", "rings", "c14", "s2", "layer"}
    print(f"arch open data: raw {RAW} -> {MEDIA}")
    creds = []
    if "drought" in only:
        creds.append(drought(a.repin))
    if "rings" in only:
        creds += tree_rings(a.repin)
    if "c14" in only:
        creds.append(radiocarbon(a.repin))
    if "s2" in only:
        creds.append(sentinel())
    if "layer" in only:
        creds.append(natural_earth(a.repin))
    for c in creds:
        c.setdefault("accessed", ACCESSED)
    merge_credits(creds)
    if a.repin or not PINS_FILE.exists():
        pin = pins()
        for k, (url, _) in SOURCES.items():
            f = RAW / k / url.rsplit("/", 1)[1]
            if f.exists():
                pin[k] = sha256(f.read_bytes())
        PINS_FILE.write_text(json.dumps(pin, indent=1, sort_keys=True) + "\n")
        print(f"  pins -> {PINS_FILE.relative_to(ROOT)}")
    # the same gate as app/course_library.py licence_problem (that module needs the backend env; this runs without it)
    bad = [c["file"] for c in json.loads((MEDIA / "credits.json").read_text())
           if c.get("licence_class") not in ("pd", "cc0", "by", "by-sa") or (c["licence_class"] == "by-sa" and c.get("modified") is not False)]
    if bad:
        sys.exit("credits: licence_class must be pd | cc0 | by | by-sa (unmodified): " + ", ".join(bad))


if __name__ == "__main__":
    main()
