"""Before / after of the owner's moment (Cadet, first mission, Malapert Massif): skip the tour, raise the shields, and
shoot the cabin. Before (rc/4), the Now strip kept saying "Set power, then End shift."; after, it says what happened
and what's next. Run against any build:

  uv run --with playwright python frontend/tools/gameplay_shots.py --base http://127.0.0.1:5311 --out docs/img/gameplay --tag before
  uv run --with playwright python frontend/tools/gameplay_shots.py --base http://127.0.0.1:5310 --out docs/img/gameplay --tag after
"""
import argparse
import glob
import os

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

SEED = """try{ localStorage.clear(); localStorage.setItem('atm-theme','dark'); localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-prefs', JSON.stringify({level:'cadet'}));
  localStorage.setItem('outpost-tour-done:Comet','1'); }catch(e){}"""
NOW = "() => { const n = document.querySelector('#cbNow'); return n && !n.hidden ? n.innerText.replace(/\\s+/g, ' ').trim() : null; }"


def main(base, out, tag, sizes):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--mute-audio", "--use-gl=angle", "--use-angle=swiftshader"])
        for vw, vh in sizes:
            pg = b.new_page(viewport={"width": vw, "height": vh})
            pg.set_default_timeout(120000)
            pg.add_init_script(SEED)
            pg.goto(base)
            pg.wait_for_selector('.mx-site[data-site="malapert_massif"]')
            pg.wait_for_timeout(1200)
            pg.click('.mx-site[data-site="malapert_massif"]')
            pg.click("#mStart")
            pg.wait_for_selector("#cbNow:not([hidden])")
            pg.wait_for_timeout(3000)
            print(f"{tag} {vw}x{vh} start: {pg.evaluate(NOW)}")
            pg.screenshot(path=os.path.join(out, f"{tag}-{vw}x{vh}-1-start.jpg"), type="jpeg", quality=62, timeout=300000)
            pg.evaluate("document.getElementById('cbShPlus').click()")   # the owner changed the shield power
            pg.wait_for_timeout(2500)
            print(f"{tag} {vw}x{vh} after shields: {pg.evaluate(NOW)}")
            pg.screenshot(path=os.path.join(out, f"{tag}-{vw}x{vh}-2-after-shields.jpg"), type="jpeg", quality=62, timeout=300000)
            pg.close()
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--sizes", default="1280x720")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    main(a.base, a.out, a.tag, [tuple(map(int, s.split("x"))) for s in a.sizes.split(",")])
