"""Build the optional `moon_views` asset's folder: open Moon data beyond NASA's own pack (docs/MEDIA.md "Moon views"):
one real Apollo surface photo per landing site, the USGS Unified Geologic Map of the Moon as a "Rock ages" globe layer,
the Smithsonian's Apollo 11 Command Module Columbia in 3D and Lunar Sample Compendium facts for the Moon rocks tray.

    make moon-views          # = this script under uv (Pillow + certifi), then asset_pack.py --only moon_views
    uv run --no-project --with pillow --with certifi python -I scripts/moon_views_build.py [--keep-raw]

Everything is fetched at BUILD time into a raw cache of its own (MOON_VIEWS_RAW, default <repo>/.cache/moon_views_raw),
converted, and staged in MOON_VIEWS_SRC (default backend/data/cache/moon_views, gitignored), which scripts/asset_pack.py
packs into outpost-luna-v2-moon_views.tar. Downloads are pinned by sha256 (PINS); a changed upstream file stops the
build until its licence is re-checked (--repin). Nothing downloaded is executed: the GeoTIFF is read by Pillow, the GLB
by gltf-transform (scripts/nasa_views_glb.mjs, the nasa_views model step, reused as is).

Layout (the app's contract: backend/app/moon_views.py, frontend/src/media/moon_views.js):
    NOTICE  index.json  photos/<site>.jpg  layers/rock_ages.png  models/columbia.glb
Licences: every entry's licence_class is pd | cc0 (by / by-sa allowed by the contract; nothing here needs them).
Skipped on purpose (docs/MEDIA.md): LROC NAC crops (PDS products are 0.2-2 GB mosaics; no practical crop in time),
JAXA, ISRO, CNSA, UNESCO, GVP, Seshat, OSM (licence problems).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # nasa_views_build (fetch, jpg, npm_tools, glb); explicit for -I
import nasa_views_build as nv   # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("MOON_VIEWS_RAW", ROOT / ".cache/moon_views_raw"))
OUT = Path(os.environ.get("MOON_VIEWS_SRC", ROOT / "backend/data/cache/moon_views"))
PINS_FILE = Path(__file__).with_name("moon_views.pins.json")
CREDIT = ("Uses open Moon data: NASA images and Lunar Sample Compendium (public domain), the USGS Unified Geologic Map "
          "of the Moon (CC0) and Smithsonian NASM 3D (CC0); not endorsed by NASA, the USGS or the Smithsonian.")
LICENCE_CLASSES = ("pd", "cc0", "by", "by-sa")

# ---- photos: one per Apollo landing site (NASA Image and Video Library; public domain) --------------------------------
PHOTOS = [   # site, nasa_id, title, caption (kid-sized, from NASA's own description)
    ("apollo11", "AS11-40-5903", "Buzz Aldrin walks near Eagle",
     "Buzz Aldrin on the Moon beside the leg of the Lunar Module Eagle, 20 July 1969. Neil Armstrong took the picture."),
    ("apollo12", "AS12-48-7133", "Two spacecraft on the Moon",
     "Apollo 12 landed close to Surveyor 3, a robot that had been there for two and a half years. Both are in this photo."),
    ("apollo14", "AS14-66-9306", "Apollo 14's Lunar Module, Antares",
     "The Lunar Module Antares at Fra Mauro, with a flare from the bright Sun, February 1971."),
    ("apollo15", "AS15-86-11603", "Jim Irwin at the rover",
     "Jim Irwin works at the first Lunar Roving Vehicle near Hadley Rille, 31 July 1971."),
    ("apollo16", "AS16-113-18339", "John Young's jump salute",
     "John Young leaps off the ground in the Moon's low gravity while saluting the flag at Descartes, April 1972."),
    ("apollo17", "AS17-140-21496", "Jack Schmitt and the split boulder",
     "Geologist Jack Schmitt beside a huge split boulder in the Taurus-Littrow valley, December 1972."),
]

# ---- layer: USGS Unified Geologic Map of the Moon, 1:5M, 2020 (Fortezzo, Spudis, Harrel; CC0) --------------------------
GEO_ZIP = "https://asc-astropedia.s3.us-west-2.amazonaws.com/Moon/Geology/Ancillary/unified_geologic_map_of_the_moon_raster.zip"
GEO_TIF = "Unified_Geologic_Map_of_the_Moon_RASTER/numerical_versions/Unified_Geologic_Map_of_the_Moon_64ppd.tif"
GEO_CSV = "Unified_Geologic_Map_of_the_Moon_RASTER/numerical_versions/Dn_GeologicUnit_RGBcolor.csv"
GEO_PAGE = "https://astrogeology.usgs.gov/search/map/unified_geologic_map_of_the_moon_1_5m_2020"
# the five periods, youngest first: one blue ramp, light (young) -> dark (old). Boundaries are approximate (Wilhelms
# 1987, USGS Professional Paper 1348). Units that span two periods ("Eratosthenian-Imbrian") take the younger one.
AGES = [
    ("Copernican", "#cde2fb", "Copernican: younger than 1.1 billion years (fresh craters)"),
    ("Eratosthenian", "#86b6ef", "Eratosthenian: 3.2 to 1.1 billion years"),
    ("Imbrian", "#3987e5", "Imbrian: 3.85 to 3.2 billion years (most dark maria)"),
    ("Nectarian", "#1c5cab", "Nectarian: 3.92 to 3.85 billion years"),
    ("Pre-Nectarian", "#0d366b", "Pre-Nectarian: older than 3.92 billion years"),
]
LAYER_W = 2048

# ---- model: Apollo 11 Command Module Columbia, exterior (Smithsonian NASM, 3D package; CC0) -----------------------------
COLUMBIA_GLB = ("https://3d-api.si.edu/content/document/3d_package:d8c6457e-4ebc-11ea-b77f-2e728ce88125/resources/"
                "apollo_exterior-150k-4096.glb")
COLUMBIA_PAGE = "https://airandspace.si.edu/collection-objects/command-module-apollo-11/nasm_A19700102000"
COLUMBIA_EVIDENCE = ("Smithsonian Open Access API record ld1-1643400021979-1643400025078-0: metadata_usage access CC0, 3d_voyager "
                     "media usage access CC0; the NASM object page says 'Open Access (CC0)'")
MAX_MODEL_BYTES = 6_000_000

# ---- facts: Lunar Sample Compendium (C. Meyer, NASA JSC; public domain), for the nasa_views rocks -----------------------
LSC = "https://curator.jsc.nasa.gov/lunar/lsc/"
ROCK_FACTS = {   # rock id (nasa_views rocks) -> short facts, checked against the compendium PDF named in `source`
    "15016": ["It weighs 923.7 grams.", "Gas bubbles make up about half of the rock.",
              "Dated to about 3.3 billion years old.", "Its lava came from more than 250 km deep inside the Moon."],
    "60025": ["It weighs 1,836 grams.", "Dated to about 4.36 billion years old.",
              "It is almost pure plagioclase, a light mineral that floated to the top of a Moon-wide magma ocean.",
              "It was collected near the Lunar Module."],
    "76535": ["It weighs 155.5 grams.", "It formed about 4.2 billion years ago, about 47 km below the surface.",
              "It was picked up with a rake at Station 6."],
    "70017": ["It weighs 2,957 grams.", "Its lava crystallized about 3.7 billion years ago.",
              "It has lain at the surface for about 220 million years.",
              "Pieces of it were given to many countries, with a speech to 'the children of the world'."],
    "65035": ["It weighs 446 grams.", "It landed while its glass coat was still molten, like a bomb from an impact.",
              "Its exposure age, about 2.3 million years, says it came from South Ray Crater."],
}


# ------------------------------------------------------------------------------------------------- helpers
def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def pinned(key: str, p: Path, repin: bool, pins: dict) -> Path:
    h = sha256(p)
    if pins.get(key) and pins[key] != h and not repin:
        sys.exit(f"{key}: changed upstream (sha256 {h[:12]} != pinned {pins[key][:12]}); re-check its licence, then --repin")
    pins[key] = h
    return p


def build_photos(repin: bool, pins: dict) -> list[dict]:
    out = []
    for site, nid, title, caption in PHOTOS:
        hit = nv.get_json(f"https://images-api.nasa.gov/search?nasa_id={nid}")["collection"]["items"][0]
        d, lo = hit["data"][0], nid.lower()
        # the asset folder's case differs per item (as11-… vs AS12-…): take the ~orig.jpg its own collection lists
        orig = next(u for u in nv.get_json(hit["href"]) if u.endswith("~orig.jpg")).replace("http://", "https://", 1)
        if not orig.startswith("https://images-assets.nasa.gov/image/"):
            sys.exit(f"{nid}: unexpected asset host {orig}")
        src = pinned(f"photo_{site}", nv.fetch(orig, RAW / f"photos/{lo}.jpg"),
                     repin, pins)
        w, h = nv.jpg(src, OUT / f"photos/{site}.jpg", 1600, q=84)
        out.append({"id": site, "file": f"photos/{site}.jpg", "site": site, "title": title, "caption": caption,
                    "nasa_id": d["nasa_id"], "date": d["date_created"][:10], "credit": "NASA",
                    "licence": "Public domain (NASA image; not subject to copyright in the US)", "licence_class": "pd",
                    "source": f"https://images.nasa.gov/details/{d['nasa_id']}", "w": w, "h": h,
                    "alt": f"{title}: {caption}"})
        print(f"  photo {site:9s} {nid}  {w}x{h}", flush=True)
    return out


def build_rock_ages(repin: bool, pins: dict) -> dict:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = 300_000_000   # 23040 x 11520, a USGS raster we downloaded ourselves
    z = pinned("usgs_geology", nv.fetch(GEO_ZIP, RAW / "geology/unified_geologic_map_of_the_moon_raster.zip"), repin, pins)
    with zipfile.ZipFile(z) as zf:
        rows = zf.read(GEO_CSV).decode("utf-8").splitlines()
        tif = zf.read(GEO_TIF)
    import csv
    period = {}
    for r in csv.DictReader(rows):
        age = r["Unit_Age"].strip()
        first = next((a for a, *_ in AGES if age.lower().startswith(a.lower())), None)   # "Eratosthenian-Imbrian" -> Eratosthenian
        if first is None:
            sys.exit(f"geology: unit {r['Unit']} has an age we do not map: {age!r}")
        period[int(r["DN"])] = [a for a, *_ in AGES].index(first)
    src = Image.open(io.BytesIO(tif))
    if src.size != (23040, 11520):
        sys.exit(f"geology: expected the 64 ppd raster (23040 x 11520), got {src.size}")
    import numpy as np
    small = np.asarray(src.resize((LAYER_W, LAYER_W // 2), Image.NEAREST)).astype(np.int64)   # unit numbers: never blended
    lut = np.full(max(256, int(small.max()) + 1), 255, dtype=np.uint8)   # 255 = no unit (clear)
    for dn, k in period.items():
        lut[dn] = k
    k = np.ascontiguousarray(lut[np.clip(small, 0, len(lut) - 1)])   # period index per pixel, 255 = none
    out = Image.frombytes("P", (k.shape[1], k.shape[0]), k.tobytes())
    pal = []
    for _, hexc, _ in AGES:
        pal += [int(hexc[i:i + 2], 16) for i in (1, 3, 5)]
    out.putpalette(pal + [0, 0, 0] * (256 - len(AGES)))
    alpha = bytes([255] * len(AGES) + [0] * (256 - len(AGES)))
    share = {a: float((k == i).mean()) for i, (a, *_) in enumerate(AGES)}
    if min(share.values()) < 0.005 or sum(share.values()) < 0.97:
        sys.exit(f"geology: unexpected period shares {share}")
    dst = OUT / "layers/rock_ages.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, "PNG", optimize=True, transparency=alpha)
    print("  layer shares " + ", ".join(f"{a} {v:.0%}" for a, v in share.items()), flush=True)
    print(f"  layer rock_ages  {out.size[0]}x{out.size[1]}  {dst.stat().st_size / 1e3:.0f} KB", flush=True)
    return {"id": "rock_ages", "file": "layers/rock_ages.png", "title": "Rock ages",
            "caption": "The USGS geologic map of the whole Moon, coloured by age. Pale blue is young, dark blue is very old.",
            "bounds": {"west": -180, "south": -90, "east": 180, "north": 90}, "opacity": 0.62,
            "legend": [{"color": c, "label": lab} for _, c, lab in AGES],
            "note": "Period boundaries are approximate (Wilhelms 1987). Units that span two periods show the younger one.",
            "credit": "USGS Astrogeology: Fortezzo, C.M., Spudis, P.D. and Harrel, S.L. (2020), Unified Geologic Map of the Moon, 1:5M",
            "licence": "CC0 (USGS record use constraint: 'CC0, but please cite authors')", "licence_class": "cc0",
            "licence_evidence": GEO_PAGE, "source": GEO_PAGE, "data_url": GEO_ZIP,
            "alt": "A map of the whole Moon in five shades of blue, from pale young craters to dark ancient highlands."}


def build_columbia(repin: bool, pins: dict) -> dict:
    nv.RAW = RAW   # the npm toolchain lives in our raw cache
    nm = nv.npm_tools()
    src = pinned("columbia", nv.fetch(COLUMBIA_GLB, RAW / "models/apollo_exterior-150k-4096.glb"), repin, pins)
    r = nv.glb(nm, OUT / "models/columbia.glb", [src], {"pivot": "center", "ratio": 0.5, "error": 0.001, "tex": 1024, "scale": 0.01})   # cm -> m
    if r["bytes"] > MAX_MODEL_BYTES:
        sys.exit(f"columbia: {r['bytes'] / 1e6:.1f} MB is over the {MAX_MODEL_BYTES / 1e6:.0f} MB budget")
    print(f"  model columbia   {r['bytes'] / 1e6:.2f} MB  size {r['size']}", flush=True)
    return {"id": "columbia", "file": "models/columbia.glb", "title": "Apollo 11 Command Module Columbia",
            "story": ("Columbia carried Neil Armstrong, Buzz Aldrin and Michael Collins to the Moon and back in July 1969. "
                      "It is the only part of Apollo 11 that came home."),
            "credit": "Smithsonian National Air and Space Museum (3D model, CC0)",
            "licence": "CC0 1.0 (Smithsonian Open Access)", "licence_class": "cc0", "licence_evidence": COLUMBIA_EVIDENCE,
            "source": COLUMBIA_PAGE, "data_url": COLUMBIA_GLB, "size": r["size"], "bytes": r["bytes"],
            "modified": "simplified to 50 % of its triangles, textures WebP <= 1024 px, meshopt (scripts/nasa_views_glb.mjs)"}


def rock_facts() -> dict:
    return {rid: {"facts": f, "source": f"{LSC}{rid}.pdf", "credit": "Lunar Sample Compendium (C. Meyer, NASA JSC)",
                  "licence_class": "pd"} for rid, f in ROCK_FACTS.items()}


def notice(idx: dict) -> str:
    lines = [CREDIT, "",
             "NASA images and text are generally not subject to copyright in the United States "
             "(https://www.nasa.gov/nasa-brand-center/images-and-media/); NASA is acknowledged as the source.", ""]
    lines += [f"Photo {p['nasa_id']} ({p['title']}): NASA, {p['source']} (public domain)" for p in idx["photos"]]
    lines += [f"Layer {l['title']}: {l['credit']}. {l['licence']}. {l['source']}" for l in idx["layers"]]
    lines += [f"3D model {m['title']}: {m['credit']}. {m['licence']}. {m['source']}. Modified: {m['modified']}." for m in idx["models"]]
    lines += [f"Moon rock {k} facts: {v['credit']}, {v['source']} (public domain)" for k, v in idx["rock_facts"].items()]
    return "\n".join(lines) + "\n"


def validate_index(idx: dict, root: Path | None = None) -> list[str]:
    """Problems with an index.json (empty = fine). With root, every listed file must exist there."""
    err = []
    if idx.get("schema") != 1 or idx.get("pack") != "moon_views":
        err.append("schema must be 1 and pack 'moon_views'")
    if idx.get("credit") != CREDIT:
        err.append("credit: must be the exact credit sentence")
    for sec, prefix, keys in (("photos", "photos/", ("id", "file", "site", "title", "caption", "nasa_id", "credit", "source", "alt")),
                              ("layers", "layers/", ("id", "file", "title", "bounds", "legend", "credit", "source", "alt")),
                              ("models", "models/", ("id", "file", "title", "credit", "source", "size"))):
        items = idx.get(sec)
        if not isinstance(items, list) or not items:
            err.append(f"{sec}: must be a non-empty list")
            continue
        for x in items:
            at = f"{sec}/{x.get('id') if isinstance(x, dict) else x}"
            if not isinstance(x, dict):
                err.append(f"{at}: not an object")
                continue
            err += [f"{at}: missing {k}" for k in keys if x.get(k) in (None, "", [])]
            if x.get("licence_class") not in LICENCE_CLASSES:
                err.append(f"{at}: licence_class must be one of {LICENCE_CLASSES} (never nc, nd or unknown)")
            f = x.get("file")
            if not isinstance(f, str) or not f.startswith(prefix) or ".." in f or f.count(".") != 1:
                err.append(f"{at}: bad file {f!r}")
            elif root is not None and not (root / f).is_file():
                err.append(f"{at}: {f} not found")
            if not str(x.get("source", "")).startswith("https://"):
                err.append(f"{at}: source must be https")
    for k, v in (idx.get("rock_facts") or {}).items():
        if not (isinstance(v, dict) and v.get("facts") and all(len(t) <= 140 for t in v["facts"]) and v.get("licence_class") in LICENCE_CLASSES):
            err.append(f"rock_facts/{k}: facts (each <= 140 characters) and a licence_class")
    return err


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep-raw", action="store_true")
    ap.add_argument("--repin", action="store_true", help="accept changed upstream files (after re-checking their licences)")
    a = ap.parse_args()
    print(f"moon_views: raw {RAW} -> {OUT}", flush=True)
    pins = json.loads(PINS_FILE.read_text()) if PINS_FILE.exists() else {}
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    idx = {"schema": 1, "pack": "moon_views", "version": "1", "credit": CREDIT,
           "photos": build_photos(a.repin, pins), "layers": [build_rock_ages(a.repin, pins)],
           "models": [build_columbia(a.repin, pins)], "rock_facts": rock_facts()}
    bad = validate_index(idx, OUT)
    if bad:
        sys.exit("index.json invalid:\n  " + "\n  ".join(bad))
    (OUT / "index.json").write_text(json.dumps(idx, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "NOTICE").write_text(notice(idx), encoding="utf-8")
    PINS_FILE.write_text(json.dumps(pins, indent=1, sort_keys=True) + "\n")
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"moon_views staged: {total / 1e6:.1f} MB", flush=True)
    if total > 30_000_000:
        sys.exit("moon_views is over its 30 MB budget")
    if not a.keep_raw:
        for d in RAW.iterdir():
            if d.name != "node":
                shutil.rmtree(d) if d.is_dir() else d.unlink()


if __name__ == "__main__":
    main()
