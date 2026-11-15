#!/usr/bin/env python3
"""Build the offline terrain tiles for the Outpost Luna cabin window (SITE / ROVER / EARTH views).

Run once, at build time only. The app never fetches anything at runtime: the tiles this writes into
frontend/public/terrain/ are bundled into dist/ by `npm run build` and ship inside the desktop installer.

    uv run --no-project --with numpy==2.1.3 --with pillow==11.0.0 python frontend/tools/build_terrain.py

Sources (NASA open data; credits and URLs are also in docs/NASA_DATASETS.md):
  * LRO LOLA polar gridded DEMs, PDS Geosciences node (LRO-L-LOLA-4-GDR-V1.0), mirrored at imbrium.mit.edu:
      LDEM_75S_120M  (120 m/px, 75S-90S)  -> context tile, 512 px at 240 m/px  (123 km across)
      LDEM_80S_40M   ( 40 m/px, 80S-90S)  -> site tile,    512 px at  40 m/px  (20.5 km across)
      LDEM_85S_10M   ( 10 m/px, 85S-90S)  -> rover tile,   512 px at  10 m/px  (5.1 km across)
    16-bit little-endian integers, height = DN * 0.5 m above the 1737.4 km sphere, south polar stereographic.
    Only the rows a tile needs are fetched, with one HTTP Range request per tile (8-31 MB each); nothing else
    is kept on disk.
  * NASA SVS 2915 "Blue Marble" (bluemarble-2048.png) -> earth.jpg, 1024x512, for the Earth in the sky.

Each tile is a lossless 8-bit RGB PNG with the height packed as (DN - dn_min) = R*256 + G, so a browser
decodes it exactly (browsers would quantise a 16-bit PNG to 8 bits through <canvas>). meta.json says how
to unpack it and where the tile sits.
"""
from __future__ import annotations

import io
import json
import math
import pathlib
import sys
import time
import urllib.request

import numpy as np
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "frontend" / "public" / "terrain"
SITES = ROOT / "backend" / "data" / "mission" / "sites.json"
BASE = "https://imbrium.mit.edu/DATA/LOLA_GDR/POLAR/IMG/"
R_M = 1737400.0
UA = {"User-Agent": "outpost-luna-terrain-build/1.0"}

# level -> (product, native m/px, native lines (= samples), projection offset, output px, decimation)
LEVELS = {
    "context": ("LDEM_75S_120M", 120, 7624, 3811.5, 512, 2),
    "site": ("LDEM_80S_40M", 40, 15200, 7599.5, 512, 1),
    "rover": ("LDEM_85S_10M", 10, 30336, 15167.5, 512, 1),
}
EARTH_URL = "https://svs.gsfc.nasa.gov/vis/a000000/a002900/a002915/bluemarble-2048.png"


def polar_xy(lat: float, lon: float) -> tuple[float, float]:
    """South polar stereographic (PDS LOLA convention), metres. Longitude 0 points to +y (top of the map)."""
    t = 2 * R_M * math.tan(math.pi / 4 + math.radians(lat) / 2)
    return t * math.sin(math.radians(lon)), t * math.cos(math.radians(lon))


def fetch_range(url: str, start: int, end: int) -> bytes:
    req = urllib.request.Request(url, headers={**UA, "Range": f"bytes={start}-{end - 1}"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            if len(data) != end - start:
                raise IOError(f"short read {len(data)} != {end - start}")
            return data
        except Exception as e:  # noqa: BLE001 - retry any network error
            print(f"   retry {attempt + 1}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"could not fetch {url}")


def cut(level: str, lat: float, lon: float) -> tuple[np.ndarray, dict]:
    prod, scale, n, off, px, dec = LEVELS[level]
    x, y = polar_xy(lat, lon)
    s0, l0 = off + x / scale, off - y / scale          # 0-based sample/line of the site
    span = px * dec
    ls, ss = int(round(l0 - span / 2)), int(round(s0 - span / 2))
    if ls < 0 or ss < 0 or ls + span > n or ss + span > n:
        raise SystemExit(f"{level}: tile falls off {prod}")
    rec = n * 2
    raw = fetch_range(BASE + prod + ".IMG", ls * rec, (ls + span) * rec)
    a = np.frombuffer(raw, dtype="<i2").reshape(span, n)[:, ss:ss + span].astype(np.int32)
    if dec > 1:
        a = a.reshape(px, dec, px, dec).mean(axis=(1, 3)).round().astype(np.int32)
    mpp = scale * dec
    # exact map position of the tile's pixel centres, so the client can place the site to the metre
    cx = ((ss + span / 2 - 0.5) - off) * scale
    cy = -((ls + span / 2 - 0.5) - off) * scale
    return a, {"product": prod, "m_per_px": mpp, "px": px, "center_x_m": cx, "center_y_m": cy,
               "site_x_m": x, "site_y_m": y, "src_line0": ls, "src_sample0": ss}


def write_tile(a: np.ndarray, path: pathlib.Path) -> dict:
    dmin, dmax = int(a.min()), int(a.max())
    q = (a - dmin).astype(np.uint32)
    if q.max() > 65535:
        raise SystemExit("height range too large to pack")
    rgb = np.zeros(a.shape + (3,), np.uint8)
    rgb[..., 0], rgb[..., 1] = q >> 8, q & 255
    Image.fromarray(rgb, "RGB").save(path, optimize=True, compress_level=9)
    return {"dn_min": dmin, "dn_max": dmax, "dn_scale_m": 0.5, "bytes": path.stat().st_size}


def main() -> None:
    sites = json.loads(SITES.read_text())["sites"]
    only = set(sys.argv[1:])
    OUT.mkdir(parents=True, exist_ok=True)
    index = {"credit": "LRO LOLA polar DEMs (NASA/GSFC/MIT, PDS Geosciences). Inspired by NASA's Artemis program. "
                       "Uses NASA open data; not endorsed by NASA.",
             "levels": list(LEVELS), "sites": {}}
    for s in sites:
        if only and s["id"] not in only:
            continue
        d = OUT / s["id"]
        d.mkdir(exist_ok=True)
        meta = {"id": s["id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"], "levels": {}}
        for lv in LEVELS:
            t = time.time()
            a, m = cut(lv, s["lat"], s["lon"])
            m.update(write_tile(a, d / f"{lv}.png"))
            c = a[a.shape[0] // 2 - 2:a.shape[0] // 2 + 2, a.shape[1] // 2 - 2:a.shape[1] // 2 + 2]
            m["site_h_m"] = float(c.mean()) * 0.5
            meta["levels"][lv] = m
            print(f"{s['id']:18s} {lv:8s} {m['product']} {m['m_per_px']:>4} m/px  h {m['dn_min'] / 2:8.0f}..{m['dn_max'] / 2:7.0f} m"
                  f"  site {m['site_h_m']:7.0f} m  {m['bytes'] / 1e3:6.0f} kB  {time.time() - t:4.1f}s")
        (d / "meta.json").write_text(json.dumps(meta, indent=1))
        index["sites"][s["id"]] = f"{s['id']}/meta.json"
    if not only:
        (OUT / "index.json").write_text(json.dumps(index, indent=1))
    earth = OUT / "earth.jpg"
    if not earth.exists():
        with urllib.request.urlopen(urllib.request.Request(EARTH_URL, headers=UA), timeout=120) as r:
            im = Image.open(io.BytesIO(r.read())).convert("RGB")
        im.resize((1024, 512), Image.LANCZOS).save(earth, quality=86, optimize=True, progressive=True)
        print(f"earth.jpg {earth.stat().st_size / 1e3:.0f} kB")
    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"terrain assets: {total / 1e6:.2f} MB in {OUT}")


if __name__ == "__main__":
    main()
