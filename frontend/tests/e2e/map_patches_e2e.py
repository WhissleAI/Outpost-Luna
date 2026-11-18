"""Flight School map: every earned patch is on screen, in colour (0.4.1 regression check).

The map faces the next stop. From lesson 3 on that stop is at the south pole, and seen from the pole the near-side
stops (Lessons 1 and 2) are round the limb, so their pins fade out. A cadet with two patches saw none of them, with
three, one. Each earned patch must be visible: as a visible pin with its earned art, or in the map header's strip
(academy/earned.js). Tapping a strip patch selects its lesson and brings its pin into view.

States: the owner's 0.4.0 progress (scout, watcher, sun: next stop polar), two patches (next stop polar, no earned
pin in view at all), one patch (next stop on the near side). Screenshots at 1440x900 go to --out.

    (backend serving frontend/dist, or a Vite dev server in front of one)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/map_patches_e2e.py --base http://127.0.0.1:5173 [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

COURSE = json.loads((Path(__file__).resolve().parents[3] / "backend" / "data" / "academy" / "course.json").read_text())
LESSON_OF = {l["badge"]["id"]: l["id"] for l in COURSE["lessons"]}

# which earned lessons can the cadet see, and how
SEEN = """() => {
  const vis = e => { if (!e) return false; const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none' || r.width < 8 || r.bottom < 0 || r.top > innerHeight || r.right < 0 || r.left > innerWidth) return false;
    let op = 1; for (let a = e; a; a = a.parentElement) op *= +getComputedStyle(a).opacity; return op > .5; };
  const out = {};
  document.querySelectorAll('.route .pin.is-done').forEach(b => { if (vis(b) && b.querySelector('svg.patch.is-earned')) (out[b.dataset.l] = out[b.dataset.l] || []).push('pin'); });
  document.querySelectorAll('.mp-patchbtn').forEach(b => { if (vis(b) && b.querySelector('svg.patch.is-earned')) (out[b.dataset.l] = out[b.dataset.l] || []).push('strip'); });
  return out; }"""
STATES = {"owner_040": ["scout", "watcher", "sun"], "two_patches": ["scout", "watcher"], "one_patch": ["scout"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5173")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    results: list[bool] = []

    def check(ok, msg):
        results.append(bool(ok)); print(("  ok  " if ok else "  FAIL ") + msg)

    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=LAUNCH_ARGS)
        for name, badges in STATES.items():
            ctx = b.new_context(viewport={"width": 1440, "height": 900}); silence(ctx)
            ctx.add_init_script("""try { if (!sessionStorage.getItem('mp-e2e')) { sessionStorage.setItem('mp-e2e', '1');
              localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('atm-mode', 'academy');
              localStorage.setItem('atm-academy', JSON.stringify({badges: %s, qualified: false})); } } catch (e) {}""" % json.dumps(badges))
            pg = ctx.new_page()
            errs = []; pg.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
            pg.goto(a.base); pg.wait_for_selector(".apanel.is-map .mp-card", timeout=30000)
            pg.wait_for_timeout(3000)   # the camera's flight to the next stop (1.3 s) and the pins' fade
            if a.out: pg.screenshot(path=f"{a.out}/map_patches-{name}-1440x900.png")
            seen = pg.evaluate(SEEN)
            for bid in badges:
                lid = LESSON_OF[bid]
                check(lid in seen, f"[{name}] the {bid} patch ({lid}) is on screen in colour: {seen.get(lid, 'not visible')}")
            check(pg.locator(".route .pin.is-done").count() == len(badges), f"[{name}] one done pin per earned lesson")
            if "scout" in badges and pg.locator('.mp-patchbtn[data-l="moon"]').count():
                pg.click('.mp-patchbtn[data-l="moon"]'); pg.wait_for_timeout(2500)
                check(pg.locator('.route .pin.is-sel[data-l="moon"]').count() == 1, f"[{name}] tapping the strip's patch selects its lesson")
                check("pin" in pg.evaluate(SEEN).get("moon", []), f"[{name}] ... and flies its pin into view")
                check(pg.locator('#aStart[data-l="moon"]').count() == 1, f"[{name}] ... with its card (Replay)")
            check(not errs, f"[{name}] no page errors {errs[:2]}")
            ctx.close()
        b.close()
    print(f"{sum(results)}/{len(results)} checks")
    sys.exit(0 if all(results) and results else 1)


if __name__ == "__main__":
    main()
