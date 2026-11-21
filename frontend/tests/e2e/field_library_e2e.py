"""Archaeology's Earth globe, Library and videos, end to end (docs/COURSES.md "Course library", src/field_library.js).

On the Archaeology course (played from source with OUTPOST_DEV_COURSE=archaeology):
  1. Field School map: the "Real views" ribbon shows real NASA / NPS pictures (loaded, same origin); the context Moon
     is in the sky; the USGS regional picture is draped on the globe.
  2. Library: the region, close; the Field Library panel with its shelves; the places and NASA views named on the
     globe; no Moon chips, no Hardware switch; the course's chips instead.
  3. A picture opens a card with the real photo (loaded) and its credit; a place marker opens its card.
  4. Watch: a course video opens the app's video player on /api/video/<id>/file.
  5. The site tour starts with the course's own title.
  6. Open data beyond NASA (docs/OPEN_DATA.md): ESA's Sentinel-2 near-infrared view opens with the Copernicus notice;
     the Climate record shelf (NOAA tree rings) shows its chart.
With --moon-base (a second run against a backend WITHOUT the flag): the Moon's Library is unchanged (no panel, no
markers, its Apollo chips, its Hardware switch), plus its Maps button: the USGS age and height maps swap onto the globe
with their legend and credit, and the photo comes back when the cadet leaves the Library.

Screenshots at 1440x900 and 1280x720 into --out.

    backend (port 8687): OUTPOST_DEV_COURSE=archaeology LUNA_DATA_DIR=<d> CACHE_DIR=<c> VIDEO_PREFETCH=false uv run uvicorn app.main:app --port 8687
    vite (port 5687): BACKEND_URL=http://127.0.0.1:8687 npx vite --port 5687
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/field_library_e2e.py --base http://localhost:5687 --out <shots>
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright
_d = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_d, os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[bool] = []


def check(ok, msg):
    results.append(bool(ok))
    print(("  ok  " if ok else "  FAIL ") + msg, flush=True)


def until(pg, js, ms=15000):
    try:
        pg.wait_for_function(js, timeout=ms)
        return True
    except Exception:  # noqa: BLE001
        return False


SEED = """try { if (!sessionStorage.getItem('fl-e2e')) { sessionStorage.setItem('fl-e2e', '1');
  localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('atm-mode', 'academy');
  localStorage.setItem('outpost-course:Nova', '%s'); localStorage.setItem('outpost-course', '%s'); } } catch (e) {}"""
IMG_OK = "(sel) => { const i = document.querySelector(sel); return !!i && i.complete && i.naturalWidth > 0; }"


def arch(b, base, out, vw, vh):
    tag = f"{vw}x{vh}"
    ctx = b.new_context(viewport={"width": vw, "height": vh}); silence(ctx)
    ctx.add_init_script(SEED % ("archaeology", "archaeology"))
    pg = ctx.new_page()
    errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    offsite: list[str] = []
    pg.on("request", lambda r: (r.resource_type in ("image", "media") and not r.url.startswith(base) and not r.url.startswith("data:")
                                and not r.url.startswith("blob:")) and offsite.append(r.url))
    pg.goto(base)
    check(until(pg, "() => window.__outpost && window.__outpost.fieldLibrary && window.__outpost.fieldLibrary.lib"), f"[{tag}] the course library loaded")
    pg.wait_for_selector(".apanel.is-map", timeout=30000)
    check(until(pg, "() => { const r = document.querySelector('.flib-ribbon'); return r && getComputedStyle(r).display !== 'none'; }"),
          f"[{tag}] Field School map: the Real views ribbon shows")
    pg.wait_for_timeout(2500)
    n_img = pg.evaluate("[...document.querySelectorAll('.flib-rb-item img')].filter(i => i.complete && i.naturalWidth > 0).length")
    check(n_img >= 3, f"[{tag}] ... with real pictures loaded ({n_img})")
    g = pg.evaluate("({o: window.__outpost.globe.overlayCount, m: window.__outpost.globe.markerCount, moon: window.__outpost.globe.hasContextMoon})")
    check(g["o"] == 1 and g["moon"], f"[{tag}] the USGS region is draped on Earth and the Moon is in the sky {g}")
    pg.screenshot(path=f"{out}/field_library-start-{tag}.png")

    pg.click("#libraryBtn"); pg.wait_for_timeout(2500)
    check(pg.locator(".flib").is_visible(), f"[{tag}] Library: the Field Library panel")
    tabs = pg.locator(".flib-tabs [data-shelf]").all_inner_texts()
    check(len(tabs) == 7 and "Watch" in tabs and "Sentinel-2" in tabs and "Climate record" in tabs, f"[{tag}] ... with its shelves {tabs}")
    check(g["m"] >= 8, f"[{tag}] places and NASA views named on the globe ({g['m']})")
    vis = pg.evaluate("[...document.querySelectorAll('.cmark')].filter(e => !e.classList.contains('is-hidden') && e.getBoundingClientRect().width > 0).length")
    check(vis >= 5, f"[{tag}] ... in view ({vis})")
    chips = pg.evaluate("[...document.querySelectorAll('#chips > button')].filter(b => getComputedStyle(b).display !== 'none' && !b.hidden).map(b => b.textContent)")
    check(not any("Apollo" in c for c in chips) and "Tour the sites" in chips, f"[{tag}] the course's chips, no Moon chips {chips}")
    check(not pg.locator("#hwBtn").is_visible() and pg.locator("#nearBtn").inner_text() == "The region", f"[{tag}] no Hardware switch on Earth")
    pg.screenshot(path=f"{out}/field_library-library-{tag}.png")

    pg.click('[data-item="mv_landsat"]')
    check(until(pg, f"() => ({IMG_OK})('#cardImg') && !document.getElementById('card').hidden"), f"[{tag}] a picture opens its card with the real photo")
    check("Public domain" in pg.locator("#card").inner_text(), f"[{tag}] ... and its credit")
    pg.wait_for_timeout(1200)
    pg.screenshot(path=f"{out}/field_library-photo-{tag}.png")

    # [open data] ESA's Sentinel-2 in near-infrared, with the Copernicus notice the EU licence asks for
    pg.click('[data-shelf="sentinel"]'); pg.wait_for_timeout(400)
    pg.click('[data-item="s2_nir"]')
    check(until(pg, f"() => ({IMG_OK})('#cardImg') && /s2_mesa_verde_nir/.test(document.getElementById('cardImg').src)"),
          f"[{tag}] Sentinel-2 near-infrared opens with its picture")
    check("Contains modified Copernicus Sentinel data 2024" in pg.locator("#card").inner_text(), f"[{tag}] ... and the Copernicus notice")
    pg.wait_for_timeout(800)
    pg.screenshot(path=f"{out}/field_library-sentinel-{tag}.png")
    pg.click('[data-shelf="climate"]'); pg.wait_for_timeout(400)
    pg.click('[data-item="rings_chart"]')
    check(until(pg, f"() => ({IMG_OK})('#cardImg') && /co652_chart/.test(document.getElementById('cardImg').src)"),
          f"[{tag}] Climate record: NOAA's tree-ring chart opens")
    check("NOAA" in pg.locator("#card").inner_text() and "Chart: " in pg.locator("#card").inner_text(), f"[{tag}] ... a chart, credited to NOAA NCEI")
    pg.wait_for_timeout(800)
    pg.screenshot(path=f"{out}/field_library-climate-{tag}.png")

    pg.evaluate("document.querySelector('.cmark[data-id=\"place:hovenweep\"]').click()")
    check(until(pg, "() => /Hovenweep/.test(document.getElementById('cardTitle').textContent)"), f"[{tag}] a place marker opens its card")

    pg.click('[data-shelf="watch"]'); pg.wait_for_timeout(500)
    n_post = pg.evaluate("[...document.querySelectorAll('.flib-grid img')].length")
    check(n_post == 4, f"[{tag}] Watch: four NASA videos with posters ({n_post})")
    pg.click('[data-item="v_lidar"]')
    check(until(pg, "() => { const v = document.querySelector('dialog[open] video'); return !!v && /\\/api\\/video\\/arch_lidar_space\\/file/.test(v.currentSrc || v.src); }", 20000),
          f"[{tag}] a course video plays in the app's player, from our own origin")
    pg.wait_for_timeout(2500)
    pg.screenshot(path=f"{out}/field_library-video-{tag}.png")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(800)

    pg.click("#tourBtn")
    check(until(pg, "() => /Site tour|Four Corners/.test(document.getElementById('card').textContent)"), f"[{tag}] the site tour starts")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{out}/field_library-tour-{tag}.png")
    check(not offsite, f"[{tag}] no picture or video hot-linked from another origin {offsite[:3]}")
    check(not errs, f"[{tag}] no page errors {errs[:2]}")
    ctx.close()


def moon(b, base, out):
    ctx = b.new_context(viewport={"width": 1440, "height": 900}); silence(ctx)
    ctx.add_init_script(SEED % ("moon", "moon"))
    pg = ctx.new_page(); errs: list[str] = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(base); pg.wait_for_selector(".apanel.is-map", timeout=30000); pg.wait_for_timeout(1500)
    pg.click("#libraryBtn"); pg.wait_for_timeout(2000)
    check(pg.locator(".flib").count() == 0 and pg.locator(".flib-ribbon").count() == 0, "[moon] no course library panel or ribbon")
    check(pg.evaluate("window.__outpost.globe.markerCount === 0 && window.__outpost.globe.overlayCount === 0 && !window.__outpost.globe.hasContextMoon"),
          "[moon] the Moon's globe has no Earth extras")
    chips = pg.locator("#chips > button:not(.nudge)").all_inner_texts()
    check("Where did Apollo 11 land?" in chips, f"[moon] its Apollo chips {chips}")
    check(pg.locator("#hwBtn").is_visible() and pg.locator("#nearBtn").inner_text() == "Near side", "[moon] its Hardware switch and Near side")
    pg.screenshot(path=f"{out}/field_library-moon-library-1440x900.png")
    # [open data] Maps: the USGS age and height maps (docs/OPEN_DATA.md)
    check(until(pg, "() => !!document.getElementById('mapsBtn')"), "[moon] a Maps button in the Library")
    pg.click("#mapsBtn")
    check(pg.locator(".mlayers").is_visible(), "[moon] ... opens the Maps panel")
    tabs = pg.locator(".ml-tabs [data-layer]").all_inner_texts()
    check(tabs == ["Photo", "Age", "Height"], f"[moon] ... Photo, Age, Height {tabs}")
    pg.click('.ml-tabs [data-layer="age"]')
    check(until(pg, "() => /moon_age\\.jpg$/.test(window.__outpost.globe.baseMap || '')"), "[moon] Age: the USGS geologic map is on the globe")
    txt = pg.locator(".mlayers").inner_text()
    check(pg.locator(".ml-legend li").count() == 5 and "Copernican" in txt and "CC0" in txt and "USGS" in txt,
          "[moon] ... with its five periods and the USGS CC0 credit")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{out}/field_library-moon-age-1440x900.png")
    pg.click('.ml-tabs [data-layer="height"]')
    check(until(pg, "() => /moon_height\\.jpg$/.test(window.__outpost.globe.baseMap || '')") and "Public domain" in pg.locator(".mlayers").inner_text(),
          "[moon] Height: the LOLA colour relief, public domain")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{out}/field_library-moon-height-1440x900.png")
    pg.click("#modeAcademy") if pg.locator("#modeAcademy").count() else pg.evaluate("document.body.dataset.mode = 'academy'")
    check(until(pg, "() => !window.__outpost.globe.baseMap && document.body.dataset.mode !== 'cadet'"), "[moon] leaving the Library brings the photo back")
    check(not errs, f"[moon] no page errors {errs[:2]}")
    ctx.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5687")
    ap.add_argument("--moon-base", default="", help="a second app URL whose backend plays the Moon (no dev flag)")
    ap.add_argument("--out", default=".")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=LAUNCH_ARGS)
        if a.moon_base:
            moon(b, a.moon_base, a.out)
        else:
            for vw, vh in ((1440, 900), (1280, 720)):
                arch(b, a.base, a.out, vw, vh)
        b.close()
    print(f"{sum(results)}/{len(results)} checks")
    sys.exit(0 if results and all(results) else 1)


if __name__ == "__main__":
    main()
