"""The Archaeology Field Library's draped regional picture (backend/data/courses/archaeology/media/four_corners_region.jpg),
seamless. `make arch-region`.

USGS The National Map's imagery service (USGSImageryOnly, public domain) answers a 2,000 px export of the Four Corners
with four state-sized tiles of different years and colour (Utah, Colorado, Arizona, New Mexico): on the globe it read as
two mismatched squares with a seam and a colour jump (owner playtest, 0.5.5). The same service at 500 px comes from one
seamless whole-region source, too soft to drape on its own. So: the sharp export keeps its detail, and each state tile
keeps only its fine detail (taken inside the tile, so nothing leaks over a border, and brought to one contrast), laid
on the soft picture's colour. The picture's own edges are feathered on the globe (globe.js setOverlay feather), so it
reads as a deliberate inset.

    uv run --no-project --with pillow --with numpy python -I scripts/arch_region_overlay.py [--check FILE]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "backend/data/courses/archaeology/media"
OUT = MEDIA / "four_corners_region.jpg"
B = {"west": -110.2, "south": 35.7, "east": -106.9, "north": 38.0}   # library.json overlays[0].bounds
SIZE = (2000, 1394)
SVC = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
# the state lines the source tiles meet on: 37 N (UT/CO | AZ/NM) and 109.05 W (UT/AZ | CO/NM)
SEAM_LAT, SEAM_LON = 37.0, -109.05


def fetch(w: int, h: int) -> np.ndarray:
    q = (f"bbox={B['west']},{B['south']},{B['east']},{B['north']}&bboxSR=4326&imageSR=4326&size={w},{h}"
         "&format=jpg&f=image")
    req = urllib.request.Request(f"{SVC}?{q}", headers={"User-Agent": "outpost-luna-build"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return np.asarray(Image.open(io.BytesIO(r.read())).convert("RGB"), dtype=np.float32)


def seam_xy(w: int, h: int) -> tuple[int, int]:
    x = round((SEAM_LON - B["west"]) / (B["east"] - B["west"]) * w)
    y = round((B["north"] - SEAM_LAT) / (B["north"] - B["south"]) * h)
    return x, y


def _box(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Mean over a 2r+1 window along one axis (edges padded by reflection)."""
    pad = [(0, 0)] * a.ndim; pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="reflect"), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis); lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def _blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian-like blur (three box passes per axis, the classic approximation) of a float HxWxC array."""
    r = max(1, int(round((np.sqrt(4 * sigma * sigma + 1) - 1) / 2)))
    for axis in (0, 1):
        for _ in range(3):
            a = _box(a, r, axis)
    return a


def harmonise(sharp: np.ndarray, soft: np.ndarray, sigma: float = 6.0) -> np.ndarray:
    """Colour from the seamless `soft` picture, detail from `sharp`: out = soft (upsampled) + (sharp - its own blur), where
    the blur is taken inside each state tile only (normalised convolution), so no tile's colour leaks across a border.
    The detail of each tile is scaled to the same contrast (one tile is hazier than the rest). -> uint8."""
    h, w, _ = sharp.shape
    ref = np.asarray(Image.fromarray(soft.astype(np.uint8)).resize((w, h), Image.BICUBIC), dtype=np.float32)
    ref = _blur(ref, sigma * 0.5)   # the soft picture's own JPEG blocks
    sx, sy = seam_xy(w, h)
    tiles = [(slice(0, sy), slice(0, sx)), (slice(0, sy), slice(sx, w)), (slice(sy, h), slice(0, sx)), (slice(sy, h), slice(sx, w))]
    detail = np.zeros_like(sharp)
    for ys, xs in tiles:
        m = np.zeros((h, w, 1), np.float32); m[ys, xs] = 1
        low = _blur(sharp * m, sigma) / np.maximum(_blur(m, sigma), 1e-4)
        detail[ys, xs] = (sharp - low)[ys, xs]
    spread = [float(np.std(detail[ys, xs])) for ys, xs in tiles]
    for (ys, xs), sp in zip(tiles, spread):
        detail[ys, xs] *= float(np.median(spread)) / max(sp, 1e-3)
    # the export's tiles also carry a 1-2 px light edge on the border itself: the detail fades out over a few px each
    # side of a border (a soft taper, never a blank strip with hard edges)
    def taper(n, at, half=6):
        d = np.abs(np.arange(n) - at + 0.5)
        return np.clip((d - 1.5) / half, 0, 1) ** 0.5
    detail *= taper(h, sy)[:, None, None] * taper(w, sx)[None, :, None]
    return np.clip(ref + detail, 0, 255).astype(np.uint8)


def seam_step(img: np.ndarray) -> float:
    """Mean colour jump across the two borders vs. the picture's ordinary row-to-row change (1.0 = no seam)."""
    a = img.astype(np.float32); h, w, _ = a.shape; sx, sy = seam_xy(w, h)
    def jump(m, i):
        return float(np.abs(m[i + 3].mean(0) - m[i - 4].mean(0)).mean())
    rows, cols = a.mean(1), a.mean(0)   # per-row / per-column mean colour
    base = float(np.median([jump(rows, i) for i in range(10, h - 10, 25)]))
    return max(jump(rows, sy), jump(cols, sx)) / max(base, 1e-3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", type=Path, help="only print the seam score of a picture")
    a = ap.parse_args()
    if a.check:
        print(json.dumps({"file": str(a.check), "seam": round(seam_step(np.asarray(Image.open(a.check).convert("RGB"))), 2)}))
        return
    sharp, soft = fetch(*SIZE), fetch(500, 348)
    out = harmonise(sharp, soft)
    print(json.dumps({"seam_before": round(seam_step(sharp.astype(np.uint8)), 2), "seam_after": round(seam_step(out), 2)}))
    buf = io.BytesIO(); Image.fromarray(out).save(buf, "JPEG", quality=86, optimize=True, progressive=True)
    OUT.write_bytes(buf.getvalue())
    cr = MEDIA / "credits.json"; credits = json.loads(cr.read_text())
    for c in credits if isinstance(credits, list) else credits.get("items", []):
        if c.get("file") == OUT.name:
            c.update(bytes=len(buf.getvalue()), sha256=hashlib.sha256(buf.getvalue()).hexdigest(), width=SIZE[0], height=SIZE[1])
            c["note"] = ("Built by scripts/arch_region_overlay.py: the fine detail of the 2,000 px USGS export (per state tile) on the colour "
                         "of the same service's seamless 500 px picture of the same ground (no seam at 37 N / 109.05 W).")
    cr.write_text(json.dumps(credits, indent=1, ensure_ascii=False) + "\n")
    print("wrote", OUT, len(buf.getvalue()))


if __name__ == "__main__":
    sys.exit(main())
