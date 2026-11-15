"""The cabin tour card never covers the window HUD (owner's rc/2 play: the card hid "Day 1 · Shift 1" and the site
name). Walks all 12 Cadet beats in the 3D cabin and asserts, for each, that the card's box does not intersect the
clock (day, shift, site) or the sky readout. Optional --shots DIR saves a JPEG of the first beat and the last beat.

  uv run --with playwright python frontend/tools/tour_clear.py --base http://127.0.0.1:5398 [--shots DIR]
"""
import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

SEED = """try{ localStorage.setItem('atm-theme','dark'); localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-prefs', JSON.stringify({level:'cadet'})); }catch(e){}"""
MEASURE = """() => { const box = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; };
  const card = document.querySelector('.m-tour'), hud = [...document.querySelectorAll('.cb-clock, .cb-sky')].filter(e => e.getClientRects().length);
  return { eye: (card.querySelector('.t-eye') || {}).textContent, card: box(card), hud: hud.map(e => [e.className, ...box(e)]) }; }"""


def hits(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def run(base, shots, sizes):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    fails = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--autoplay-policy=no-user-gesture-required", "--use-gl=angle", "--use-angle=swiftshader"])
        for vw, vh in sizes:
            pg = b.new_page(viewport={"width": vw, "height": vh})
            pg.set_default_timeout(180000)
            pg.add_init_script(SEED)
            pg.goto(base)
            pg.wait_for_selector("#mStart")
            pg.wait_for_timeout(1500)
            pg.evaluate("document.getElementById('mStart').click()")
            pg.wait_for_selector(".m-tour:not([hidden])")
            n = pg.evaluate("document.querySelectorAll('.m-tour .t-dots i').length")
            for k in range(n):
                pg.wait_for_timeout(1600)   # the camera settles and the card re-docks
                m = pg.evaluate(MEASURE)
                bad = [h[0] for h in m["hud"] if hits(m["card"], h[1:])]
                ok = not bad and m["hud"]
                print(f"  {'ok  ' if ok else 'FAIL'} {vw}x{vh} {m['eye']}: card top {m['card'][1]:.0f}, HUD bottom "
                      f"{max((h[4] for h in m['hud']), default=0):.0f}{'  covers ' + ', '.join(bad) if bad else ''}")
                if not ok:
                    fails.append(f"{vw}x{vh} beat {k + 1}")
                if shots and k in (0, n - 1):
                    pg.screenshot(path=os.path.join(shots, f"tour-docked-{vw}x{vh}-{k + 1:02d}.jpg"), type="jpeg", quality=58, timeout=300000)
                pg.evaluate("document.querySelector('.m-tour .t-next').click()")
            pg.close()
        b.close()
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 0 if not fails else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5398")
    ap.add_argument("--shots", default="")
    ap.add_argument("--sizes", default="1280x720,1440x900")
    a = ap.parse_args()
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    sys.exit(run(a.base, a.shots, [tuple(map(int, s.split("x"))) for s in a.sizes.split(",")]))
