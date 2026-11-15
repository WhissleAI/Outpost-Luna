"""The landing-site navigator, end to end (docs/SITE_NAVIGATOR.md). Needs the backend with sites_physics.json and the
map layers (`cd backend && uv run python -m pipeline.site_physics layers`), and the dev server.

Checks, every input:
  - the screen: "Choose your landing site", the map with 4 layer toggles, a legend with its unit and a credit line,
    5 site rows with a score and a NASA tag, NASA's 9 regions, numbers with a source link each;
  - layers by mouse (click Slope), by voice ("show sunlight"), the toggle state and the legend follow;
  - voice "which site has the most ice?" -> the ice layer, the Shackleton Crater Floor row selected, CAPCOM answers;
  - presets: "ice first" by voice and the Power first chip by mouse re-score the rows; a slider by keyboard;
  - the map: mouse wheel zoom, keyboard + / arrows, controller (right stick spin, triggers zoom_rate), gesture fist /
    pinch (the same bus intents) all move the map view and never the globe behind it;
  - thumbs up (yes) on a focused row picks it; voice "pick Malapert" picks Malapert; "pick Haworth" shows a region;
  - pick -> take command: the mission starts at that site and runs on its real numbers (the sim's rover_to_ice_h,
    window sun % = the navigator's site, Sun spans from GET /windows);
  - without the layers (a stubbed API): "Map layers downloading…" and the plain globe picker still works.

    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/site_navigator_e2e.py --base http://localhost:5207
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

SEED = """try{ localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-first-mission:Comet','1'); localStorage.removeItem('outpost-nav-weights'); localStorage.removeItem('outpost-nav-layer'); }catch(e){}"""
TYPED = "t => { const q = document.getElementById('q'); q.value = t; document.getElementById('askForm').requestSubmit(); }"
SEL = "() => (document.querySelector('.mx-site[aria-checked=\"true\"]') || {}).dataset?.site"
PRESSED = "() => (document.querySelector('.nv-layer[aria-pressed=\"true\"]') || {}).dataset?.layer || 'off'"
VIEW = "() => window.__outpost.navigator.view"
SCORES = "() => Object.fromEntries([...document.querySelectorAll('.mx-site')].map(b => [b.dataset.site, +b.querySelector('.nv-score').textContent]))"


def run(base: str) -> int:
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    fails: list[str] = []

    def ok(cond, msg):
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        pg = ctx.new_page()
        said, starts = [], []
        pg.on("request", lambda r: "/api/mission/start" in r.url and starts.append(r.post_data_json))
        pg.add_init_script(SEED)
        pg.goto(base)
        pg.wait_for_selector(".nv-map .nv-layer", timeout=60000)
        pg.wait_for_timeout(1500)
        pg.evaluate("() => { const f = window.speechSynthesis; window.__said = []; }")

        # ---- the screen
        ok(pg.inner_text(".mx-title").strip() == "Choose your landing site", "title: Choose your landing site")
        ok(pg.locator(".nv-layer").count() == 4, "4 layer toggles (Sunlight, Slope, Ice, Earth view)")
        ok(pg.locator(".mx-site").count() == 5 and pg.locator(".nv-region").count() == 9, "5 site rows + 9 NASA regions")
        tags = pg.eval_on_selector_all(".mx-site .nv-tag", "ns => ns.map(n => n.textContent)")
        ok(any("2024 Artemis III" in t for t in tags) and any("dropped" in t for t in tags), f"tags: on NASA's 2024 list / studied, dropped ({set(tags)})")
        n_src = pg.locator(".nv-detail .nv-src").count()
        ok(n_src >= 7, f"every number in the detail card links its source ({n_src})")
        ok("% of the time" in pg.inner_text(".nv-legend") and "LOLA" in pg.inner_text(".nv-credit"), "legend has the unit and a credit line")
        ok(pg.evaluate("() => [...document.querySelectorAll('.nv-pin')].length") == 14, "14 pins on the map")

        # ---- layers: mouse, voice
        pg.click('.nv-layer[data-layer="slope"]'); pg.wait_for_timeout(300)
        ok(pg.evaluate(PRESSED) == "slope" and "degrees" in pg.inner_text(".nv-legend"), "click Slope: toggled, legend in degrees")
        pg.evaluate(TYPED, "show sunlight"); pg.wait_for_timeout(2500)
        ok(pg.evaluate(PRESSED) == "sunlight", f"voice 'show sunlight' ({pg.evaluate(PRESSED)})")
        pg.evaluate(TYPED, "earth view"); pg.wait_for_timeout(2500)
        ok(pg.evaluate(PRESSED) == "earth", f"voice 'earth view' ({pg.evaluate(PRESSED)})")

        # ---- the question
        pg.evaluate(TYPED, "which site has the most ice?"); pg.wait_for_timeout(3000)
        ok(pg.evaluate(SEL) == "shackleton_floor", f"'which site has the most ice' selects Shackleton Crater Floor ({pg.evaluate(SEL)})")
        ok(pg.evaluate(PRESSED) == "ice", "...and turns the ice layer on")
        cap = pg.evaluate("() => document.body.innerText")
        ok("Ice can last right there" in cap, "CAPCOM answers with the number")

        # ---- presets and sliders
        s0 = pg.evaluate(SCORES)
        pg.evaluate(TYPED, "ice first"); pg.wait_for_timeout(2500)
        s1 = pg.evaluate(SCORES)
        ok(pg.get_attribute('[data-preset="ice_first"]', "aria-pressed") == "true" and s1 != s0, f"voice 'ice first' re-scores ({s0} -> {s1})")
        pg.click('[data-preset="power_first"]'); pg.wait_for_timeout(300)
        s2 = pg.evaluate(SCORES)
        ok(s2 != s1 and s2["shackleton_floor"] < s1["shackleton_floor"], "the Power first chip re-scores (the dark floor drops)")
        pg.evaluate("() => { const d = document.querySelector('.nv-sliders'); d.open = true; }")
        pg.focus('input[data-w="safety"]'); pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(300)
        ok(pg.input_value('input[data-w="safety"]') == "2" and pg.evaluate("() => document.querySelector('[aria-pressed=\"true\"][data-preset]')") is None,
           "a slider by keyboard: weight 2, no preset any more")

        # ---- the map: mouse, keyboard, controller, gestures move the map (not the globe)
        v0 = pg.evaluate(VIEW)
        box = pg.locator(".nv-hit").bounding_box()
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2); pg.mouse.wheel(0, -400); pg.wait_for_timeout(300)
        v1 = pg.evaluate(VIEW)
        ok(v1["z"] > v0["z"], f"mouse wheel zooms the map ({v0['z']:.2f} -> {v1['z']:.2f})")
        pg.focus(".nv-hit"); pg.keyboard.press("ArrowRight"); pg.keyboard.press("-"); pg.wait_for_timeout(900)
        v2 = pg.evaluate(VIEW)
        ok(v2["x"] > v1["x"] and v2["z"] < v1["z"], "keyboard: arrow pans, minus zooms out")
        pg.evaluate("() => window.__outpost.intents.emitIntent('spin', {phase: 'start', x: 1, y: 0}, 'gamepad')"); pg.wait_for_timeout(500)
        pg.evaluate("() => window.__outpost.intents.emitIntent('spin', {phase: 'end', x: 0, y: 0}, 'gamepad')"); pg.wait_for_timeout(600)
        v3 = pg.evaluate(VIEW)
        ok(abs(v3["x"] - v2["x"]) > 1000, f"controller right stick (spin) pans the map ({v2['x']:.0f} -> {v3['x']:.0f} m)")
        pg.evaluate("() => window.__outpost.intents.emitIntent('zoom_rate', {phase: 'start', rate: 1}, 'gamepad')"); pg.wait_for_timeout(500)
        pg.evaluate("() => window.__outpost.intents.emitIntent('zoom_rate', {phase: 'end', rate: 0}, 'gamepad')"); pg.wait_for_timeout(600)
        v4 = pg.evaluate(VIEW)
        ok(v4["z"] > v3["z"], "controller trigger / gesture pinch (zoom_rate) zooms the map")
        pg.evaluate("() => window.__outpost.intents.emitIntent('rotate', {phase: 'move', dx: 0.05, dy: 0}, 'gesture')"); pg.wait_for_timeout(200)
        ok(abs(pg.evaluate(VIEW)["x"] - v4["x"]) > 100, "gesture fist drag (rotate) moves the map")

        # ---- picks: thumbs up on a focused row, voice by name, a region
        pg.focus('.mx-site[data-site="connecting_ridge"]')
        pg.evaluate("() => window.__outpost.intents.emitIntent('yes', {}, 'gesture')"); pg.wait_for_timeout(800)
        ok(pg.evaluate(SEL) == "connecting_ridge" and not starts, "thumbs up on a focused row picks it (and does not fly yet)")
        pg.evaluate(TYPED, "pick malapert"); pg.wait_for_timeout(2500)
        ok(pg.evaluate(SEL) == "malapert_massif", f"voice 'pick Malapert' ({pg.evaluate(SEL)})")
        pg.evaluate(TYPED, "pick haworth"); pg.wait_for_timeout(2500)
        ok(pg.evaluate("() => window.__outpost.navigator.focus") == "a3_haworth" and pg.evaluate(SEL) == "malapert_massif",
           "voice 'pick Haworth' shows the region; the flyable pick stays Malapert")

        # ---- pick -> the mission uses its numbers
        pg.evaluate(TYPED, "which site has the most ice?"); pg.wait_for_timeout(2500)
        nav = pg.evaluate("() => fetch('/api/sites/navigator').then(r => r.json())")
        floor = next(x for x in nav["places"] if x["id"] == "shackleton_floor")
        pg.evaluate(TYPED, "take command")
        pg.wait_for_selector(".cb-glass", timeout=60000)
        ok(bool(starts) and starts[-1]["site"] == "shackleton_floor", f"take command flies the picked site ({starts[-1] if starts else None})")
        ok(pg.evaluate("() => !document.querySelector('.nv-map') || document.querySelector('.nv-map').hidden"), "the map leaves with the picker")
        sites = pg.evaluate("() => fetch('/api/mission/sites').then(r => r.json())")["sites"]
        rim = next(x for x in sites if x["id"] == "shackleton_rim")
        nrim = next(x for x in nav["places"] if x["id"] == "shackleton_rim")
        ok(rim["sunlight_pct"] == nrim["sunlight_pct"]["value"] and rim["rover_to_ice_h"] == nrim["rover_to_ice_h"],
           "the sim's sites carry the navigator's numbers (sunlight %, ice run hours)")
        ok(floor["ice_km"]["value"] < 0.15, "the floor's ice is right there (Diviner)")
        ctx.close()

        # ---- a second run: pick Malapert, fly, and read the mission's own windows
        ctx = b.new_context(viewport={"width": 1280, "height": 720}); pg = ctx.new_page(); pg.add_init_script(SEED)
        st = []
        pg.on("response", lambda r: "/api/mission/start" in r.url and st.append(r.json()))
        pg.goto(base); pg.wait_for_selector(".nv-map .nv-layer", timeout=60000); pg.wait_for_timeout(800)
        pg.click('.mx-site[data-site="malapert_massif"]'); pg.wait_for_timeout(400)
        pg.click("#mStart"); pg.wait_for_selector(".cb-glass", timeout=60000); pg.wait_for_timeout(500)
        m = st[-1] if st else {}
        win = pg.evaluate("id => fetch('/api/mission/' + id + '/windows').then(r => r.json())", m.get("id", ""))
        sun_h = sum(b_ - a for a, b_ in win.get("sun", []))
        mal = next(x for x in sites if x["id"] == "malapert_massif")
        ok(m.get("site", {}).get("id") == "malapert_massif" and abs(sun_h - mal["window_sunlit_pct"] * 2.4) <= 3,
           f"Malapert's mission runs on its real skyline: {sun_h} sunlit hours = {mal['window_sunlit_pct']}% of 240")
        ctx.close()

        # ---- without the layers: the plain picker + "Map layers downloading…"
        ctx = b.new_context(viewport={"width": 1440, "height": 900}); pg = ctx.new_page(); pg.add_init_script(SEED)

        def stub(route):
            resp = route.fetch(); d = resp.json(); d["layers"] = {"state": "downloading", "managed": True}
            route.fulfill(response=resp, body=json.dumps(d), headers={**resp.headers, "content-type": "application/json"})
        pg.route("**/api/sites/navigator", stub)
        pg.route("**/api/sites/layers/want", lambda r: r.fulfill(status=200, body='{"ok":true}', headers={"content-type": "application/json"}))
        pg.goto(base); pg.wait_for_selector("#mStart", timeout=60000); pg.wait_for_timeout(1500)
        ok("Map layers downloading" in pg.inner_text("body"), "no layers: 'Map layers downloading…'")
        ok(pg.locator(".mx-site").count() == 5 and pg.locator(".nv-detail .nv-src").count() >= 7, "...and the numbers with sources still show")
        pg.evaluate(TYPED, "show sunlight"); pg.wait_for_timeout(2000)
        ok("still downloading" in pg.inner_text("body"), "voice 'show sunlight' says the layers are downloading")
        ctx.close()
        b.close()
    print(f"\n{'FAILED' if fails else 'PASSED'}: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5207")
    sys.exit(run(ap.parse_args().base))
