"""Screenshot the Earth globe spike (docs/COURSES.md §6). Silent and headless (tools/silent.py).

  python frontend/tools/spike_earth_globe.py --url http://localhost:<vite port> --out <dir> [--map /spike/bm.jpg]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import silent  # noqa: E402,F401  (mute + headless, before Playwright launches)
from playwright.sync_api import sync_playwright  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--map", default="")
    ap.add_argument("--sizes", default="1440x900,1280x720")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    q = f"?map={a.map}" if a.map else ""
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=angle", "--use-angle=swiftshader", "--mute-audio"])
        for size in a.sizes.split(","):
            w, h = (int(x) for x in size.split("x"))
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto(a.url.rstrip("/") + "/tools/spike_earth_globe.html" + q)
            pg.wait_for_function("!document.getElementById('loading')", timeout=60000)
            pg.wait_for_timeout(2500)   # the fly-to (1.3 s) and a frame or two
            f = out / f"earth_globe_mesa_verde-{size}.jpg"
            pg.screenshot(path=str(f), type="jpeg", quality=82)
            print(f)
            pg.close()
        b.close()


if __name__ == "__main__":
    main()
