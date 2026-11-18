"""Build the optional `nasa_views` asset's folder: real NASA sky, 3D models, Moon rocks, photos, the Sun on 14 May 2024
and the IAU names around the south pole and the Apollo sites (docs/MEDIA.md "NASA views"; backend/data/SOURCES.md).

    make nasa-views          # = this script under uv (OpenEXR + numpy + Pillow), then asset_pack.py --only nasa_views
    uv run --no-project --with OpenEXR --with numpy --with pillow python -I scripts/nasa_views_build.py [--keep-raw]

Everything is fetched at BUILD time (the app never fetches it): downloads go into a raw cache (NASA_VIEWS_RAW, default
<repo>/.cache/nasa_views_raw, a folder of their own), are converted, and the result is staged in NASA_VIEWS_SRC
(default backend/data/cache/nasa_views, gitignored), which scripts/asset_pack.py packs into outpost-luna-v2-nasa_views.tar.
The raw downloads are deleted afterwards (--keep-raw keeps them; the npm toolchain in <raw>/node is kept as a cache).

Layout of the staged folder (the app's contract: backend/app/nasa_views.py, frontend):
    NOTICE  index.json  sky/starmap_4k.jpg  models/<id>.glb  rocks/<id>.glb  images/<id>.jpg  sdo/<NN>.jpg
    names/moon_names.json
Models: scripts/nasa_views_glb.mjs (gltf-transform: merge, centre, simplify, WebP <= 1024 px, EXT_meshopt_compression).
The app's GLTFLoader needs the meshopt decoder (three/examples/jsm/libs/meshopt_decoder.module.js) and reads WebP.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # asset_pack (tls); explicit, so `python -I` works too

ROOT = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("NASA_VIEWS_RAW", ROOT / ".cache/nasa_views_raw"))   # a folder of its own (gitignored)
OUT = Path(os.environ.get("NASA_VIEWS_SRC", ROOT / "backend/data/cache/nasa_views"))
UA = "outpost-luna-asset-pack"
CREDIT = ("Uses NASA open data and 3D models (NASA 3D Resources; NASA/Astromaterials 3D, CC0; USGS Astrogeology); "
          "not endorsed by NASA.")
NPM = ["@gltf-transform/core@4.5.1", "@gltf-transform/extensions@4.5.1", "@gltf-transform/functions@4.5.1",
       "draco3dgltf@1.5.7", "meshoptimizer@0.22.0", "sharp@0.35.5"]   # sharp = the one gltf-transform's ndarray-pixels pins

# ---- sky: SVS 4851 Deep Star Maps 2020 (celestial, plate carree, RA 0h at the centre, RA increasing to the left) -------
SVS = "https://svs.gsfc.nasa.gov/vis/a000000/a004800/a004851/"
SKY = {"file": "sky/starmap_4k.jpg", "title": "Deep Star Maps 2020",
       "credit": "NASA/Goddard Space Flight Center Scientific Visualization Studio", "source": "https://svs.gsfc.nasa.gov/4851",
       "projection": "equirect_celestial", "ra0_u": 0.5, "ra_increases": "left",
       "note": "Hipparcos-2, Tycho-2 and Gaia DR2 stars plus the Milky Way; ICRF/J2000; 4096 x 2048, linear EXR -> gamma 2.2"}

# ---- models: NASA 3D Resources (https://science.nasa.gov/3d-resources/) ------------------------------------------------
M3D = "https://assets.science.nasa.gov/content/dam/science/cds/3d/resources/model/"
# id, title, page, [glb paths under M3D], options (nasa_views_glb.mjs: pivot, ratio = simplify, scale -> metres)
MODELS = [
    ("apollo_lm", "Apollo Lunar Module", "https://science.nasa.gov/3d-resources/apollo-lunar-module/",
     ["apollo-lunar-module/Apollo%20Lunar%20Module.glb"], {}),
    ("hdu", "Habitat Demonstration Unit", "https://science.nasa.gov/3d-resources/habitat-demonstration-unit/",
     ["habitat-demonstration-unit/Habitat%20Demonstration%20Unit%20(part%201).glb",
      "habitat-demonstration-unit/Habitat%20Demonstration%20Unit%20(part%202).glb"], {"scale": 0.01}),   # cm -> m
    ("rassor", "RASSOR (Regolith Advanced Surface Systems Operations Robot)",
     "https://science.nasa.gov/3d-resources/regolith-advanced-surface-systems-operations-robot-rassor/",
     ["regolith-advanced-surface-systems-operations-robot-(rassor)/"
      "Regolith%20Advanced%20Surface%20Systems%20Operations%20Robot%20(RASSOR).glb"], {"ratio": 0.12, "error": 0.002}),
    ("mcc", "Mission Control Room (Johnson Space Center)", "https://science.nasa.gov/3d-resources/jsc-mission-control-room/",
     ["jsc-mission-control-room/JSC%20Mission%20Control%20Room.glb"], {}),
    ("lro", "Lunar Reconnaissance Orbiter", "https://science.nasa.gov/3d-resources/lunar-reconnaissance-orbiter-b/",
     ["lunar-reconnaissance-orbiter-(b)/Lunar%20Reconnaissance%20Orbiter%20(B).glb"], {}),
    # LADEE's source units are not metres: scaled so it stands its real 2.37 m (NSSDCA 2013-047A)
    ("ladee", "LADEE (Lunar Atmosphere and Dust Environment Explorer)",
     "https://science.nasa.gov/3d-resources/lunar-atmosphere-and-dust-environment-explorer-ladee/",
     ["lunar-atmosphere-and-dust-environment-explorer-(ladee)/"
      "Lunar%20Atmosphere%20and%20Dust%20Environment%20Explorer%20(LADEE).glb"], {"scale": 0.0371}),
]

# ---- rocks: Astromaterials 3D (NASA JSC ARES; public domain, credit NASA) -----------------------------------------------
A3D = "https://ares-a3d.s3.us-gov-east-1.amazonaws.com/samples/"
A3D_META = "https://ares.jsc.nasa.gov/astromaterials3d/explorer/lunar_sample_metadata.json"
# id, metadata key, short name, a kid-sized story condensed from the sample's own story in the metadata JSON
ROCKS = [
    ("15016", "15016-0", "Seatbelt basalt",
     "Dave Scott spotted this bubbly lava rock from the rover and said he had stopped to fix his seatbelt, so he could "
     "grab it. The holes are gas bubbles from lava."),
    ("60025", "60025-241", "Ancient anorthosite",
     "One of the oldest Moon rocks, about 4.4 billion years old. It floated up as light crystals on the magma ocean that "
     "once covered the Moon, making the bright highlands."),
    ("76535", "76535-0", "Gem-like troctolite",
     "Many call it the most beautiful Apollo rock: big olivine and plagioclase crystals that cooled slowly, maybe over "
     "100 million years, deep in the Moon's early crust."),
    ("70017", "70017-8", "High-titanium basalt",
     "Lava that erupted 3.7 billion years ago and cooled into the floor of the valley where Apollo 17 landed. No water "
     "ever touched it, so it looks just as it formed."),
    ("79115", "79115-0", "Regolith breccia",
     "Moon soil and rock bits glued together by impacts. Apollo 17 astronauts broke it off a boulder on the rim of Van "
     "Serg Crater to learn how the crater formed."),
    ("65035", "65035-0", "Glass-coated breccia",
     "\"Look at the glass-covered one right there, John!\" said Charlie Duke. Its glassy coat was splashed on by a "
     "meteorite impact near South Ray Crater."),
]

# ---- images: NASA Image and Video Library (public domain) --------------------------------------------------------------
IMAGES = [
    ("earthrise", "AS08-14-2383", "Earthrise",
     "Earth rising over the Moon's horizon, seen by the Apollo 8 crew from lunar orbit on 24 December 1968.",
     ["earth", "apollo", "apollo8"]),
    ("earthset", "art002e009284", "Earthset over the lunar limb",
     "A tiny crescent Earth beside the Moon's edge, photographed by the Artemis II crew 36 minutes before Earthset on "
     "6 April 2026.", ["earth", "artemis", "artemis2"]),
    ("art002e014211", "art002e014211", "A distant crescent of home",
     "The Moon and a small crescent Earth in one frame, seen from Orion as Artemis II approached the far side.",
     ["earth", "artemis", "artemis2"]),
    ("geology_iceland_2026", "jsc2026e405549", "Artemis geology training in Iceland",
     "Astronaut Zena Cardman and NASA geologists study Iceland's Moon-like lava fields on a training expedition.",
     ["training", "geology", "artemis"]),
    ("geology_iceland_2024", "jsc2024e055124", "Artemis II crew geology training",
     "Artemis II backup crew member Jenni Gibbons (Canadian Space Agency) learns field geology in Iceland.",
     ["training", "geology", "artemis2"]),
]
FORBIDDEN_IDS = re.compile(r"com-axiom|axemu-axiom", re.I)

# ---- SDO: AIA 131 browse frames of 14 May 2024 (AR 13664's X8.7 flare peaked 16:51 UTC) --------------------------------
SDO_DAY = "https://sdo.gsfc.nasa.gov/assets/img/browse/2024/05/14/"
SDO_N = 16
SDO_FLARE = "1651"
SDO_AROUND = ["1625", "1640", "1710"]   # a few more frames round the flare: the flash builds and fades
SDO = {"title": "The Sun on 14 May 2024", "region": "AR 13664", "wavelength": "AIA 131",
       "caption": "A day of the Sun in extreme ultraviolet. The bright flash at 16:51 UTC is an X8.7 flare from sunspot "
                  "region 13664, the strongest of its solar cycle so far; its storms reached Earth that May.",
       "credit": "NASA/SDO and the AIA science team", "source": "https://sdo.gsfc.nasa.gov/"}

# ---- names: Gazetteer of Planetary Nomenclature (IAU WGPSN / USGS Astrogeology) -----------------------------------------
NOMEN = "https://asc-planetarynames-data.s3.us-west-2.amazonaws.com/MOON_nomenclature_center_pts.zip"
APOLLO_SITES = {"Apollo 11": (0.67416, 23.47314), "Apollo 12": (-3.0128, -23.4219), "Apollo 14": (-3.64589, -17.47194),
                "Apollo 15": (26.13239, 3.6333), "Apollo 16": (-8.9734, 15.5011), "Apollo 17": (20.1911, 30.7723)}


# ------------------------------------------------------------------------------------------------- helpers
def fetch(url: str, dst: Path) -> Path:
    if dst.exists() and dst.stat().st_size:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    import asset_pack   # tls(): certifi + backend/data/video/intermediates.pem (svs.gsfc.nasa.gov sends no intermediate)
    tmp = dst.with_name(dst.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180, context=asset_pack.tls()) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    tmp.replace(dst)
    return dst


def get_json(url: str):
    import asset_pack
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60, context=asset_pack.tls()) as r:
        return json.loads(r.read().decode("utf-8"))


def jpg(src: Path, dst: Path, max_side: int, q: int = 85) -> tuple[int, int]:
    from PIL import Image
    im = Image.open(src).convert("RGB")
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=q, optimize=True, progressive=True)   # no EXIF carried over
    return im.size


def npm_tools() -> Path:
    nm = RAW / "node"
    if not all((nm / "node_modules" / p.rsplit("@", 1)[0]).exists() for p in NPM):
        nm.mkdir(parents=True, exist_ok=True)
        (nm / "package.json").write_text('{"private": true}\n')
        subprocess.run(["npm", "install", "--no-audit", "--no-fund", "--prefix", str(nm), *NPM], check=True)
    return nm / "node_modules"


def glb(nm: Path, out: Path, inputs: list[Path], opts: dict) -> dict:
    r = subprocess.run(["node", str(ROOT / "scripts/nasa_views_glb.mjs"), str(nm), str(out), json.dumps(opts),
                        *map(str, inputs)], check=True, capture_output=True, text=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


# ------------------------------------------------------------------------------------------------- steps
def build_sky() -> dict:
    import numpy as np
    import OpenEXR
    from PIL import Image
    exr = fetch(SVS + "starmap_2020_4k.exr", RAW / "sky/starmap_2020_4k.exr")
    a = OpenEXR.File(str(exr)).channels()["RGB"].pixels.astype(np.float32)   # linear, 0..1, 2048 x 4096
    px = (np.clip(a, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8)        # matches SVS's own *_print.jpg tone
    dst = OUT / SKY["file"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(px, "RGB").save(dst, "JPEG", quality=88, optimize=True, progressive=True)
    return dict(SKY)


def build_models(nm: Path) -> list[dict]:
    out = []
    for mid, title, page, paths, opts in MODELS:
        srcs = [fetch(M3D + p, RAW / "models" / f"{mid}_{i}.glb") for i, p in enumerate(paths)]
        r = glb(nm, OUT / f"models/{mid}.glb", srcs, {"pivot": "below", **opts})
        out.append({"id": mid, "file": f"models/{mid}.glb", "title": title, "credit": "NASA 3D Resources",
                    "source": page, "size": r["size"], "bytes": r["bytes"]})
        print(f"  model {mid:10s} {r['bytes'] / 1e6:5.2f} MB  size {r['size']}", flush=True)
    return out


def build_rocks(nm: Path) -> list[dict]:
    meta = get_json(A3D_META)
    out = []
    for rid, key, name, story in ROCKS:
        m, s = meta[key], get_json(A3D + f"{key}/{key}_A3D_EXPLORER_metadata.json")
        stem = s["mesh_filename"].rsplit(".", 1)[0]
        z = fetch(A3D + f"{key}/{s['mesh_foldername']}/{stem}.zip", RAW / f"rocks/{key}.zip")
        d = RAW / f"rocks/{key}"
        with zipfile.ZipFile(z) as zf:
            for i in zf.infolist():   # only the mesh, its material and its texture; names checked
                n = Path(i.filename).name
                if n.lower().endswith((".obj", ".mtl", ".jpg", ".png")) and n == i.filename:
                    d.mkdir(parents=True, exist_ok=True)
                    (d / n).write_bytes(zf.read(i))
        r = glb(nm, OUT / f"rocks/{rid}.glb", [d / s["mesh_filename"]], {"pivot": "center", "ratio": 0.2, "error": 0.0005})
        text = re.sub(r"<[^>]+>", " ", m.get("story", ""))
        mass = re.search(r"weighing ([\d.]+) kilogra", text)
        out.append({"id": rid, "file": f"rocks/{rid}.glb", "name": name, "mission": m["origin_category_title"],
                    "type": m["classification"], "collected": m.get("collected"),
                    "mass_g": round(float(mass.group(1)) * 1000) if mass else None, "story": story,
                    "size": r["size"], "bytes": r["bytes"], "credit": "NASA/Astromaterials 3D (CC0)",
                    "source": f"https://ares.jsc.nasa.gov/astromaterials3d/sample-details.htm?sample={key}"})
        print(f"  rock  {rid:10s} {r['bytes'] / 1e6:5.2f} MB  {m['classification']}", flush=True)
    return out


def build_images() -> list[dict]:
    out = []
    for iid, nasa_id, title, caption, tags in IMAGES:
        if FORBIDDEN_IDS.search(nasa_id):
            sys.exit(f"{nasa_id}: not a NASA image (Axiom); never used")
        d = get_json(f"https://images-api.nasa.gov/search?nasa_id={nasa_id}")["collection"]["items"][0]["data"][0]
        lo = nasa_id.lower()
        src = fetch(f"https://images-assets.nasa.gov/image/{lo}/{lo}~orig.jpg", RAW / f"images/{lo}.jpg")
        w, h = jpg(src, OUT / f"images/{iid}.jpg", 2048)
        out.append({"id": iid, "file": f"images/{iid}.jpg", "title": title, "caption": caption,
                    "date": d["date_created"][:10], "nasa_id": d["nasa_id"], "credit": "NASA",
                    "source": f"https://images.nasa.gov/details/{d['nasa_id']}", "w": w, "h": h, "tags": tags})
        print(f"  image {iid:22s} {w}x{h}", flush=True)
    return out


def build_sdo() -> dict:
    import asset_pack
    req = urllib.request.Request(SDO_DAY, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60, context=asset_pack.tls()) as r:
        names = sorted(set(re.findall(r'href="(20240514_(\d{6})_1024_0131\.jpg)"', r.read().decode())))
    if len(names) < SDO_N:
        sys.exit(f"SDO: only {len(names)} AIA 131 frames listed for 2024-05-14")
    pick = {names[round(i * (len(names) - 1) / (SDO_N - 2))] for i in range(SDO_N - 1)}
    def nearest(hhmm):
        return min(names, key=lambda n: abs(int(n[1][:2]) * 60 + int(n[1][2:4]) - (int(hhmm[:2]) * 60 + int(hhmm[2:]))))
    flare = nearest(SDO_FLARE)
    pick |= {flare, *map(nearest, SDO_AROUND)}
    frames = []
    for k, (fn, hms) in enumerate(sorted(pick)):
        src = fetch(SDO_DAY + fn, RAW / f"sdo/{fn}")
        jpg(src, OUT / f"sdo/{k:02d}.jpg", 1024, q=82)
        frames.append({"file": f"sdo/{k:02d}.jpg", "time": f"2024-05-14T{hms[:2]}:{hms[2:4]}:{hms[4:]}Z",
                       **({"flare": True} if fn == flare[0] else {})})
    print(f"  sdo   {len(frames)} frames (flare {flare[1]})", flush=True)
    return {**SDO, "frames": frames}


def read_dbf(b: bytes) -> list[dict]:
    """A dBASE III table (the shapefile's attributes), stdlib only."""
    n, hl, rl = struct.unpack("<IHH", b[4:12])
    fields, o = [], 32
    while b[o] != 0x0D:
        fields.append((b[o:o + 11].split(b"\0")[0].decode("ascii"), chr(b[o + 11]), b[o + 16]))
        o += 32
    rows = []
    for i in range(n):
        r = b[hl + i * rl: hl + (i + 1) * rl]
        if r[:1] == b"*":   # deleted
            continue
        p, row = 1, {}
        for name, typ, ln in fields:
            v = r[p:p + ln].decode("utf-8", "replace").strip()
            p += ln
            row[name] = (float(v) if v else None) if typ in "NF" else v
        rows.append(row)
    return rows


def build_names() -> dict:
    import math
    z = fetch(NOMEN, RAW / "names/MOON_nomenclature_center_pts.zip")
    with zipfile.ZipFile(z) as zf:
        rows = read_dbf(zf.read("MOON_nomenclature_center_pts.dbf"))

    def near(lat, lon):
        for site, (a, b) in APOLLO_SITES.items():
            c = math.sin(math.radians(lat)) * math.sin(math.radians(a)) + \
                math.cos(math.radians(lat)) * math.cos(math.radians(a)) * math.cos(math.radians(lon - b))
            if math.degrees(math.acos(max(-1.0, min(1.0, c)))) <= 1.5:
                return site
        return None
    out = []
    for r in rows:
        lat, lon = r.get("center_lat"), r.get("center_lon")
        if lat is None or lon is None or "Adopted" not in (r.get("approval") or ""):
            continue
        lon = lon - 360 if lon > 180 else lon
        site = near(lat, lon)
        if lat > -75 and not site:
            continue
        origin = re.sub(r"\s+", " ", r.get("origin") or "")
        out.append({"name": r["name"], "lat": round(lat, 4), "lon": round(lon, 4),
                    "km": round(r["diameter"], 2) if r.get("diameter") else None,
                    "type": (r.get("type") or "").split(",")[0].strip(),
                    "origin": origin if len(origin) <= 90 else origin[:87].rsplit(" ", 1)[0] + "…",
                    **({"near": site} if site else {})})
    out.sort(key=lambda x: (x["lat"], x["name"]))
    dst = OUT / "names/moon_names.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"  names {len(out)} features, {dst.stat().st_size / 1e3:.0f} KB", flush=True)
    return {"file": "names/moon_names.json", "count": len(out),
            "credit": "Gazetteer of Planetary Nomenclature, IAU WGPSN / USGS Astrogeology",
            "source": "https://planetarynames.wr.usgs.gov/",
            "filter": "IAU-adopted features at or south of 75 S, plus those within 1.5 deg of an Apollo landing site"}


def notice(idx: dict) -> str:
    lines = [CREDIT, "",
             "NASA images, video and 3D models are generally not subject to copyright in the United States "
             "(https://www.nasa.gov/nasa-brand-center/images-and-media/); NASA is acknowledged as the source. "
             "Nothing here implies NASA endorsement.", "",
             f"Sky: {idx['sky']['title']}, {idx['sky']['credit']}, {idx['sky']['source']}"]
    lines += [f"3D model: {m['title']}, {m['credit']}, {m['source']}" for m in idx["models"]]
    lines += [f"Moon rock {r['id']} ({r['type']}, {r['mission']}): NASA/Astromaterials 3D, public domain (CC0), {r['source']}"
              for r in idx["rocks"]]
    lines += [f"Photo {i['nasa_id']} ({i['title']}): NASA, {i['source']}" for i in idx["images"]]
    lines += [f"Sun: {idx['sdo']['wavelength']} frames of 2024-05-14, {idx['sdo']['credit']}, {idx['sdo']['source']}",
              f"Names: {idx['names']['credit']}, {idx['names']['source']} (public domain)"]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------------------------------------- the contract
def validate_index(idx: dict, root: Path | None = None) -> list[str]:
    """Problems with an index.json (empty = fine). With root, also checks that every listed file exists there."""
    err = []
    def need(obj, keys, where):
        for k in keys:
            if not isinstance(obj, dict) or obj.get(k) in (None, ""):
                err.append(f"{where}: missing {k}")
    def file_ok(rel, where, prefix):
        if not isinstance(rel, str) or not rel.startswith(prefix) or ".." in rel or rel.startswith("/"):
            err.append(f"{where}: bad file {rel!r}")
        elif root is not None and not (root / rel).is_file():
            err.append(f"{where}: {rel} not found")
    if idx.get("schema") != 1 or idx.get("pack") != "nasa_views":
        err.append("schema must be 1 and pack 'nasa_views'")
    if idx.get("credit") != CREDIT:
        err.append("credit: must be the exact credit sentence")
    sky = idx.get("sky")
    need(sky, ["file", "title", "credit", "source", "projection", "ra_increases"], "sky")
    if isinstance(sky, dict):
        file_ok(sky.get("file"), "sky", "sky/")
        if not isinstance(sky.get("ra0_u"), (int, float)) or not 0 <= sky["ra0_u"] <= 1:
            err.append("sky: ra0_u must be in 0..1")
        if sky.get("ra_increases") not in ("left", "right"):
            err.append("sky: ra_increases must be left or right")
    for sec, keys, prefix in (("models", ["id", "file", "title", "credit", "source", "size"], "models/"),
                              ("rocks", ["id", "file", "name", "mission", "type", "story", "credit", "source"], "rocks/"),
                              ("images", ["id", "file", "title", "caption", "date", "nasa_id", "credit", "source"], "images/")):
        items = idx.get(sec)
        if not isinstance(items, list) or not items:
            err.append(f"{sec}: must be a non-empty list")
            continue
        ids = [x.get("id") for x in items if isinstance(x, dict)]
        if len(ids) != len(set(ids)):
            err.append(f"{sec}: duplicate ids")
        for x in items:
            need(x, keys, f"{sec}/{x.get('id') if isinstance(x, dict) else x}")
            if isinstance(x, dict):
                file_ok(x.get("file"), f"{sec}/{x.get('id')}", prefix)
                if sec == "images" and FORBIDDEN_IDS.search(str(x.get("nasa_id"))):
                    err.append(f"images/{x.get('id')}: Axiom image ids are not NASA's")
                if sec == "rocks" and len(str(x.get("story", ""))) > 220:
                    err.append(f"rocks/{x.get('id')}: story over 220 characters")
                if sec == "models" and not (isinstance(x.get("size"), list) and len(x["size"]) == 3):
                    err.append(f"models/{x.get('id')}: size must be [x, y, z]")
    sdo = idx.get("sdo")
    need(sdo, ["title", "caption", "region", "credit", "source", "wavelength", "frames"], "sdo")
    if isinstance(sdo, dict):
        for f in sdo.get("frames") or []:
            need(f, ["file", "time"], "sdo/frame")
            file_ok(f.get("file"), "sdo/frame", "sdo/")
    names = idx.get("names")
    need(names, ["file", "count", "credit", "source"], "names")
    if isinstance(names, dict):
        file_ok(names.get("file"), "names", "names/")
    return err


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--keep-raw", action="store_true", help="keep the raw downloads (default: deleted after conversion)")
    a = ap.parse_args()
    print(f"nasa_views: raw {RAW} -> {OUT}", flush=True)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    nm = npm_tools()
    idx = {"schema": 1, "pack": "nasa_views", "version": "1", "credit": CREDIT,
           "sky": build_sky(), "models": build_models(nm), "rocks": build_rocks(nm), "images": build_images(),
           "sdo": build_sdo(), "names": build_names()}
    bad = validate_index(idx, OUT)
    if bad:
        sys.exit("index.json invalid:\n  " + "\n  ".join(bad))
    (OUT / "index.json").write_text(json.dumps(idx, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "NOTICE").write_text(notice(idx), encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    models = sum(p.stat().st_size for p in (OUT / "models").glob("*.glb"))
    print(f"nasa_views staged: {total / 1e6:.1f} MB ({models / 1e6:.1f} MB hardware models)", flush=True)
    if not a.keep_raw:
        for d in RAW.iterdir():
            if d.name != "node":   # the npm toolchain is a cache, not a download
                shutil.rmtree(d) if d.is_dir() else d.unlink()
        print("  raw downloads deleted", flush=True)


if __name__ == "__main__":
    main()
