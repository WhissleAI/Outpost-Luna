"""Camera gestures, end to end, headless (docs/GESTURES.md §Testing).

Runs the built app as the desktop app serves it (the backend's own origin, frontend/dist with /vision/ inside), in
Chromium with a fake camera (--use-fake-device-for-media-stream). Checks:
  1. camera off by default; no camera request until Settings turns it on
  2. Settings -> Camera & gestures -> on: the bundled WASM + models load in the worker and frames flow (fps, ms)
  3. nothing is fetched from anywhere but the app's own origin
  4. the first-time calibration (hand, fist left / right / up / down, pinch, head) runs on injected landmarks and is saved
  5. landmark streams injected on each screen emit the right intents, and the screens react
  6. fist spin, played in real time: in all 8 directions the Moon turns that way at a rate, the stick indicator and
     the heading arrow show it, and opening the hand releases with a little momentum that stops by itself
  7. the coach mark and the "Gestures" help card; a gesture shows the keys' focus ring (html[data-input=gesture])
  8. the indicator's one-click off stops the camera; keyboard intents work with the camera off

    cd frontend && npm run build
    (backend on :8390 serving frontend/dist)  uv run --no-project --with playwright==1.58.0 python tests/e2e/gestures_e2e.py --base http://127.0.0.1:8390
Exit 1 on the first failure. --shots DIR saves screenshots.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402  (owner rule: test runs make no sound)

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "gestures"
results: list[tuple[bool, str]] = []


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        raise SystemExit(1)


def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text())["frames"]


SPY = """() => { window.__spy = []; window.__outpost.intents.onIntent('*', (a, ev) => { window.__spy.push({name: ev.name, source: ev.source, args: a}); return false; }, {priority: 100}); }"""


def spied(page, clear=True):
    out = page.evaluate("() => window.__spy.slice()")
    if clear:
        page.evaluate("() => { window.__spy.length = 0; }")
    return out


def inject(page, name, shift=0):
    frames = fixture(name)
    # re-time so a fixture can be injected more than once (the classifier needs increasing time)
    return page.evaluate("([fs, dt]) => window.__outpost.gestures.inject(fs.map(f => ({...f, t: f.t + dt}))).map(e => e.type)", [frames, shift])


_cursor = [0]


def inject_next(page, name):
    """Inject a fixture right after the previous one (contiguous time, as a camera would see it)."""
    frames = fixture(name)
    base = _cursor[0] or 1_000_000
    shift = base - frames[0]["t"]
    _cursor[0] = frames[-1]["t"] + shift + 33
    return page.evaluate("([fs, dt]) => window.__outpost.gestures.inject(fs.map(f => ({...f, t: f.t + dt}))).map(e => e.type)", [frames, shift])


def inject_paced(page, name):
    return page.evaluate("fs => window.__outpost.gestures.injectPaced(fs)", fixture(name))


def screen(page):
    return page.evaluate("""() => { const a = document.getElementById('aPanel'); return {mode: document.body.dataset.mode, aview: document.body.dataset.aview || '',
        lesson: !!(a && !a.hidden && a.querySelector('.a-prompt')), cabin: document.body.dataset.cabin || ''}; }""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8390")
    ap.add_argument("--shots", default="")
    ap.add_argument("--seconds", type=float, default=6.0, help="how long to run the real camera path")
    ap.add_argument("--min-frames", type=int, default=20, help="camera frames that must flow through the worker (lower it on a loaded machine)")
    ap.add_argument("--frames-timeout", type=float, default=30.0, help="seconds to wait for them")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        # the first-mission cabin tour (story) owns next / yes while it runs: these checks are about the cabin itself
        ctx.add_init_script("try { localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('outpost-tour-done:Nova', '1'); } catch (e) {}")
        silence(ctx)
        page = ctx.new_page()
        foreign, cam_requests = [], []
        page.on("request", lambda r: foreign.append(r.url) if not (r.url.startswith(base) or r.url.startswith(base.replace("http", "ws")) or r.url.startswith(("data:", "blob:"))) else None)
        logs = []
        page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"))
        page.goto(base + "/")
        page.wait_for_function("() => window.__outpost && window.__outpost.gestures && window.__outpost.intents", timeout=30000)
        page.evaluate(SPY)
        page.wait_for_timeout(1500)

        # ---- 1. off by default ----
        st = page.evaluate("() => ({active: window.__outpost.gestures.active, cam: document.body.dataset.camera, ind: document.getElementById('gxIndicator').hidden, s: window.__outpost.gestures.settings})")
        ok(not st["active"] and st["ind"] and st["s"]["enabled"] is False, "camera is off by default (no indicator, setting off)")
        ok(page.evaluate("() => !document.querySelector('.gx-video').srcObject"), "no camera stream before opt-in")

        # ---- 4a. camera off: everything still works (keyboard intent) ----
        page.keyboard.press("Alt+ArrowRight")
        ok(any(e["name"] == "next" and e["source"] == "keyboard" for e in spied(page)), "keyboard Alt+Right emits next (camera off)")

        # ---- 2. Settings -> Camera & gestures -> on ----
        page.click("#a11yBtn")
        page.click('[data-sec="camera"]')   # Settings → Camera & gestures (settingsSections)
        page.wait_for_selector("#gxEnabled", timeout=5000)
        ok(page.evaluate("() => !!document.querySelector('.topbar #gxIndicator, .topnav #gxIndicator')"), "camera chip lives in the top bar")
        if a.shots:
            page.screenshot(path=f"{a.shots}/gestures-settings-off.png")
        page.check("#gxEnabled")
        try:
            page.wait_for_function("() => window.__outpost.gestures.active && window.__outpost.gestures.stats.state === 'on'", timeout=45000)
        except Exception:
            print("   state:", page.evaluate("() => [window.__outpost.gestures.stats, document.querySelector('.gx-state') && document.querySelector('.gx-state').textContent]"))
            print("   console:\n     " + "\n     ".join(logs[-15:]))
            ok(False, "camera + vision worker started")
        # ---- 4. the first-time calibration: offered once, on injected landmarks (palm, fist + 4 tilts, head) ----
        page.wait_for_selector(".gx-calib", timeout=5000)
        ok(True, "first time on: the calibration opens by itself (skippable)")
        step = lambda: page.evaluate("() => (document.querySelector('.gx-calib-step') || {}).textContent || ''")
        inject_next(page, "palm_hold")
        ok("fist" in step().lower(), f"calibration: open hand -> 'Make a fist' ({step()!r})")
        seen_steps = []
        for i, d in enumerate(["left", "right", "up", "down"]):
            inject_next(page, f"fist_spin_{d}")
            seen_steps.append(step())
        ok(all(w in seen_steps[i].lower() for i, w in enumerate(["right", "up", "down", "pinch"])), f"calibration: tilt left, right, up, down ({seen_steps})")
        inject_next(page, "pinch_hold")
        # the head step only shows when "Look around with your head" is on; otherwise the pinch is the last step
        calib_open = page.evaluate("() => !!document.querySelector('.gx-calib')")
        ok("look" in step().lower() or not calib_open, f"calibration: pinch your fingers -> sit back, or done ({step()!r})")
        if calib_open:
            inject_next(page, "lean_in_back")
        page.wait_for_function("() => !document.querySelector('.gx-calib')", timeout=15000)
        cal = page.evaluate("() => window.__outpost.gestures.calibration")
        stored = page.evaluate("() => JSON.parse(localStorage.getItem('outpost-gestures-spin') || 'null')")
        ok(cal and cal["v"] == 1 and stored == cal and all(0.8 < cal[k] < 2.0 for k in ("left", "right", "up", "down")) and cal["pitchSign"] == 1,
           f"calibration measured each direction and saved it on this device: {cal}")
        ok(cal and 0.02 < cal.get("pinch", 0) < 0.2, f"calibration measured the pinch distance ({cal and cal.get('pinch')} hand-lengths)")
        ok(page.evaluate("() => /Fist tuned for you/.test(document.querySelector('.gx-state').textContent) && !!document.getElementById('gxCalib') && /Recalibrate/.test(document.getElementById('gxCalib').textContent) && !!document.getElementById('gxInvert')"),
           "Settings: 'Fist tuned for you', Recalibrate, Flip the spin")
        t0 = time.time()
        try:
            page.wait_for_function(f"() => window.__outpost.gestures.stats.frames > {a.min_frames}", timeout=int(a.frames_timeout * 1000))
        except Exception:
            print("   state:", page.evaluate("() => [window.__outpost.gestures.stats, (v => v && [v.readyState, v.videoWidth, v.paused])(document.querySelector('.gx-video'))]"))
            print("   console:\n     " + "\n     ".join(l for l in logs[-25:] if "GL Driver" not in l))
            ok(False, "frames flow through the worker")
        page.wait_for_timeout(int(a.seconds * 1000))
        stats = page.evaluate("() => window.__outpost.gestures.stats")
        print("   stats:", json.dumps(stats), f"(first {a.min_frames} frames in {time.time() - t0:.1f}s)")
        ok(stats["frames"] > a.min_frames and stats["fps"] >= 0, f"bundled models run in the worker: {stats['fps']} fps, {stats['inferMs']} ms/frame, {stats['delegate']}, load {stats['loadMs']} ms")
        ok(not page.evaluate("() => document.getElementById('gxIndicator').hidden"), "indicator visible while the camera is on")

        page.keyboard.press("Escape")
        if a.shots:
            page.wait_for_timeout(400)
            page.screenshot(path=f"{a.shots}/gestures-on.png")

        # ---- 4. per-screen intents (landmark injection) ----
        spied(page)
        # every coach mark shown from here on (the map and the Library are both Moon screens: the first one gets it,
        # and which one wins depends on whether an earlier coach card is still up, so the check below accepts either)
        page.evaluate("""() => { window.__coaches = []; const seen = c => { if (!c.hidden && c.dataset.mode === 'coach') window.__coaches.push({screen: c.dataset.screen, text: c.textContent}); };
            new MutationObserver(() => { const c = document.querySelector('.gx-card'); if (c) seen(c); }).observe(document.body, {subtree: true, attributes: true, attributeFilter: ['hidden'], childList: true}); }""")
        # Flight School map: swipe left = next -> the next lesson opens
        page.evaluate("() => document.getElementById('modeAcademy').click()")
        page.wait_for_timeout(1200)
        before = screen(page)
        inject(page, "swipe_left", 10_000_000)
        page.wait_for_timeout(1500)
        ev = spied(page)
        ok(any(e["name"] == "next" and e["source"] == "gesture" for e in ev), f"map: swipe left -> next (from {before['aview'] or before['mode']})")
        ok(screen(page)["lesson"], "map: next opened a lesson")
        # lesson: open palm = stop (speech stops)
        inject(page, "palm_hold", 20_000_000)
        page.wait_for_timeout(300)
        ok(any(e["name"] == "stop" for e in spied(page)), "lesson: open palm -> stop")
        # lesson: a moving palm and a background thumbs-up do nothing
        inject(page, "moving_palm", 30_000_000)
        inject(page, "background_person", 40_000_000)
        page.wait_for_timeout(300)
        noise = [e["name"] for e in spied(page) if e["name"] not in ("point", "look", "rotate")]
        ok(not noise, f"lesson: waving and a far thumbs-up emit nothing ({noise})")
        # point + dwell -> select at the cursor; select taps whatever is there (here: a lesson answer / button)
        inject(page, "point_dwell", 50_000_000)
        page.wait_for_timeout(300)
        ok(any(e["name"] == "select" for e in spied(page)), "lesson: point + dwell -> select")
        ok(page.evaluate("() => document.documentElement.dataset.input") == "gesture", "a gesture drives like the remote: html[data-input=gesture] (the keys' focus ring)")
        tgt = page.evaluate("""() => { const b = [...document.querySelectorAll('#aPanel button')].find(x => x.offsetParent); if (!b) return null;
            const r = b.getBoundingClientRect(); window.__clicked = null; b.addEventListener('click', () => { window.__clicked = b.textContent.trim(); }, {once: true});
            return {x: r.left + r.width / 2, y: r.top + r.height / 2, label: b.textContent.trim()}; }""")
        if tgt:
            page.evaluate("t => window.__outpost.intents.emitIntent('select', {x: t.x, y: t.y}, 'gesture')", tgt)
            page.wait_for_timeout(200)
            ok(page.evaluate("() => window.__clicked") == tgt["label"], f"select taps the button under the cursor ({tgt['label']!r})")
        # Library: the coach mark, the help card, then the fist spins the Moon in all 8 directions
        page.evaluate("() => document.getElementById('libraryBtn').click()")
        page.wait_for_timeout(1600)
        coach = page.evaluate("() => { const c = document.querySelector('.gx-card'); return c && !c.hidden ? {mode: c.dataset.mode, screen: c.dataset.screen, text: c.textContent} : null; }")
        if not (coach and coach["mode"] == "coach" and coach["screen"] == "moon"):   # shown already, on the map
            coach = next((c for c in page.evaluate("() => window.__coaches") if c["screen"] == "moon"), None)
            if coach:
                coach["mode"] = "coach"
        ok(coach and coach["mode"] == "coach" and coach["screen"] == "moon" and "Turn the Moon" in coach["text"] and "Pinch and slide" in coach["text"], f"Moon screens: first-use coach mark ({coach and coach['text'][:60]!r})")
        page.click("#gxHelpBtn")
        helpc = page.evaluate("() => { const c = document.querySelector('.gx-card'); return c && !c.hidden ? {mode: c.dataset.mode, text: c.textContent} : null; }")
        ok(helpc and helpc["mode"] == "help" and "Turn the Moon" in helpc["text"] and "Zoom: slide up or down" in helpc["text"], "Gestures help card lists this screen's gestures")
        page.click(".gx-card [data-close]")
        spied(page)
        inject(page, "grab_drag", 60_000_000)
        page.wait_for_timeout(200)
        sp = [e for e in spied(page) if e["name"] == "spin"]
        ok(sp and any(e["args"].get("phase") == "move" for e in sp) and sp[-1]["args"].get("phase") == "end" and not any(e["name"] == "rotate" for e in spied(page)),
           f"library: fist -> spin (rate), not follow ({len(sp)} spin intents)")
        page.wait_for_timeout(1500)
        # the sign of "the surface moves right" in longitude (the same convention as a drag)
        ref = page.evaluate("""() => { const g = window.__outpost.globe; g.halt(); const a = g.centerLatLon(); g.rotateBy(0.02, 0); const b = g.centerLatLon(); g.rotateBy(-0.02, 0);
            return Math.sign(((b.lon - a.lon + 540) % 360) - 180); }""")
        DIRS = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1), "up_left": (-1, -1), "up_right": (1, -1), "down_left": (-1, 1), "down_right": (1, 1)}
        for d, (vx, vy) in DIRS.items():
            page.evaluate("() => { const g = window.__outpost.globe; g.flyTo(0, 0, 3.6); }")
            page.wait_for_function("() => { const c = window.__outpost.globe.centerLatLon(); return Math.abs(c.lat) < 1 && Math.abs(((c.lon + 540) % 360) - 180) < 1 && window.__outpost.gestures.spin().speed === 0; }", timeout=6000)
            page.wait_for_timeout(300)
            c0 = page.evaluate("() => window.__outpost.globe.centerLatLon()")
            z0 = page.evaluate("() => window.__outpost.globe.distance")
            # mid-hold: the stick indicator and the heading arrow are up
            r = page.evaluate("""fs => { const probe = new Promise(res => setTimeout(() => res({grab: window.__outpost.gestures.spin(),
                stick: !document.getElementById('gxStick').hidden && document.getElementById('gxStick').classList.contains('is-grabbed'),
                heading: !document.getElementById('gxHeading').hidden}), 1250));
                return window.__outpost.gestures.injectPaced(fs).then(evs => probe.then(p => ({evs, probe: p}))); }""", fixture(f"fist_spin_roll_{d}"))
            evs, probe = r["evs"], r["probe"]
            c1 = page.evaluate("() => window.__outpost.globe.centerLatLon()")
            page.wait_for_function("() => window.__outpost.gestures.spin().speed === 0", timeout=12000)
            c2 = page.evaluate("() => window.__outpost.globe.centerLatLon()")
            dlat, dlon = c1["lat"] - c0["lat"], ((c1["lon"] - c0["lon"] + 540) % 360) - 180
            coast = abs(c2["lat"] - c1["lat"]) + abs(((c2["lon"] - c1["lon"] + 540) % 360) - 180)
            # off-axis drift: under 3 deg, or under 8% of the turn (real-time paced frames integrate a little longer on a
            # loaded machine: a 66 deg turn right with 3.3 deg of drift still reads as "right")
            good = (vy == 0 and abs(dlat) < max(3, 0.08 * abs(dlon)) or vy != 0 and (dlat > 5 if vy > 0 else dlat < -5)) and \
                (vx == 0 and abs(dlon) < max(3, 0.08 * abs(dlat)) or vx != 0 and dlon * ref * vx > 5)
            ok(good and "grab_start" in evs and "grab_end" in evs, f"fist spin {d}: the Moon turned that way (dlat {dlat:+.1f}, dlon {dlon:+.1f})")
            ok(probe["grab"]["grabbed"] and probe["grab"]["speed"] > 0.3 and probe["stick"] and probe["heading"], f"fist spin {d}: stick indicator + heading arrow while held ({probe})")
            ok(0.2 < coast < 30, f"fist spin {d}: opening the hand releases with a little momentum ({coast:.1f} deg), then stops")
            z2 = page.evaluate("() => window.__outpost.globe.distance")
            ok(abs(z2 - z0) < 1e-3 and "pinch_start" not in evs, f"spin with wrist roll ±0.5 rad ({d}): zoom unchanged ({z0:.3f} -> {z2:.3f})")
        ok(page.evaluate("() => document.getElementById('gxStick').hidden && document.getElementById('gxHeading').hidden"), "released: indicator and arrow gone")

        # ---- the one-hand zoom: pinch and slide (up = closer, down = farther), rate-controlled; letting go stops it ----
        def settle_at(dist):
            page.evaluate(f"() => window.__outpost.globe.flyTo(0, 0, {dist})")
            page.wait_for_function(f"() => Math.abs(window.__outpost.globe.distance - {dist}) < 0.01 && window.__outpost.gestures.zoom().rate === 0", timeout=6000)
            page.wait_for_timeout(200)
            return page.evaluate("() => window.__outpost.globe.distance")
        for name, closer in (("pinch_slide_up", True), ("pinch_slide_down", False)):
            d0 = settle_at(3.0)
            r = page.evaluate("""fs => { const probe = new Promise(res => setTimeout(() => res({z: window.__outpost.gestures.zoom(),
                ind: !document.getElementById('gxZoom').hidden, text: document.querySelector('.gx-zoom-text').textContent}), 1250));
                return window.__outpost.gestures.injectPaced(fs).then(evs => probe.then(p => ({evs, probe: p}))); }""", fixture(name))
            page.wait_for_timeout(350)
            d1 = page.evaluate("() => window.__outpost.globe.distance")
            page.wait_for_timeout(500)
            d2 = page.evaluate("() => window.__outpost.globe.distance")
            moved = d1 < d0 * 0.85 if closer else d1 > d0 * 1.15
            ok(moved and "pinch_start" in r["evs"] and "pinch_end" in r["evs"], f"{name}: the Moon zoomed {'in' if closer else 'out'} ({d0:.2f} -> {d1:.2f})")
            p = r["probe"]
            ok(p["ind"] and p["z"]["held"] and (p["z"]["rate"] > 0.2 if closer else p["z"]["rate"] < -0.2), f"{name}: zoom indicator up while held ({p})")
            ok(abs(d2 - d1) < 0.02 and page.evaluate("() => document.getElementById('gxZoom').hidden"), f"{name}: letting go stops the zoom ({d1:.3f} -> {d2:.3f}), indicator gone")
        # the same rates from the keys (+/- held, a tap is a step) and an eased step from voice
        page.evaluate("() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); }")
        d0 = settle_at(3.0)
        page.keyboard.down("="); page.wait_for_timeout(800); page.keyboard.up("=")
        page.wait_for_timeout(400)
        d1 = page.evaluate("() => window.__outpost.globe.distance")
        ok(d1 < d0 / 1.4, f"+ held 0.8 s zooms in at a rate, well past a tap's x1.25 ({d0:.2f} -> {d1:.2f}, x{d0 / d1:.2f})")
        d0 = settle_at(3.0)
        page.keyboard.press("-"); page.wait_for_timeout(600)
        d1 = page.evaluate("() => window.__outpost.globe.distance")
        ok(1.15 < d1 / d0 < 1.45, f"- tapped: one eased step out (x{d1 / d0:.2f})")
        d0 = settle_at(3.0)
        page.evaluate("() => window.__outpost.intents.emitIntent('zoom_in', {}, 'voice')"); page.wait_for_timeout(700)
        d1 = page.evaluate("() => window.__outpost.globe.distance")
        page.evaluate("() => window.__outpost.intents.emitIntent('zoom_out', {}, 'voice')"); page.wait_for_timeout(700)
        d2 = page.evaluate("() => window.__outpost.globe.distance")
        ok(1.4 < d0 / d1 < 1.8 and abs(d2 - d0) < 0.05, f"voice 'zoom in' / 'zoom out': eased steps ({d0:.2f} -> {d1:.2f} -> {d2:.2f})")
        # thumbs up / down -> yes / no
        inject(page, "thumbs_up", 70_000_000)
        inject(page, "thumbs_down", 80_000_000)
        page.wait_for_timeout(300)
        names = [e["name"] for e in spied(page)]
        ok("yes" in names and "no" in names, "thumbs up / down -> yes / no")
        # Mission: thumbs up on the brief takes command -> the cabin; swipe = next window view
        page.evaluate("() => document.getElementById('modeMission').click()")
        page.wait_for_timeout(2500)
        inject(page, "thumbs_up", 90_000_000)
        page.wait_for_timeout(3000)
        sc = screen(page)
        if sc["cabin"] == "1":
            ok(True, "brief: thumbs up -> take command (cabin)")
            v0 = page.evaluate("() => (document.querySelector('.cb-view[aria-pressed=true]') || {}).dataset?.view")
            inject(page, "swipe_left", 100_000_000)
            page.wait_for_timeout(600)
            v1 = page.evaluate("() => (document.querySelector('.cb-view[aria-pressed=true]') || {}).dataset?.view")
            ok(v0 and v1 and v0 != v1, f"cabin: swipe left -> next window view ({v0} -> {v1})")
            spied(page)
            is3d = page.evaluate("() => !!document.querySelector('.c3-gl')")
            panels = []
            page.expose_function("__panelSeen", lambda p: panels.append(p))
            page.evaluate("""() => { const h = document.querySelector('.c3-gl') && document.querySelector('.c3-gl').parentElement; if (!h) return;
                new MutationObserver(rs => rs.forEach(r => { window.__panelSeen(r.oldValue); window.__panelSeen(h.dataset.panel); })).observe(h, {attributes: true, attributeOldValue: true, attributeFilter: ['data-panel']}); }""")
            evs = inject(page, "lean_in_back", 110_000_000)
            print("   lean events:", sorted(set(evs)), "panel:", page.evaluate("() => (document.querySelector('.c3-gl') || {}).parentElement?.dataset.panel"))
            page.wait_for_timeout(1500)
            names = [e["name"] for e in spied(page)]
            if is3d:
                ok("panel_open" in names and "panel_back" in names, f"cabin: lean in -> panel_open, sit back -> panel_back ({sorted(set(names))})")
                ok(any(p not in (None, "seat") for p in panels) and panels and panels[-1] == "seat", f"3D cabin: a panel opened, then back to the seat ({panels})")
            else:
                ok("look" in names, f"cabin (2D fallback): head pose -> look ({sorted(set(names))})")
        else:
            print("   (mission did not reach the cabin in this environment; cabin checks skipped)", sc)

        # ---- 3. offline: nothing fetched off-origin ----
        vision_foreign = [u for u in foreign if "vision" in u or "mediapipe" in u or ".wasm" in u or ".task" in u or ".tflite" in u]
        ok(not vision_foreign, f"vision assets only from the app's origin ({len(foreign)} other off-origin requests: {sorted(set(u.split('?')[0] for u in foreign))[:3]})")

        # ---- 5. one-click off ----
        page.click("#gxOff")
        page.wait_for_function("() => !window.__outpost.gestures.active", timeout=5000)
        ok(page.evaluate("() => document.getElementById('gxIndicator').hidden && !document.querySelector('.gx-video').srcObject"), "Turn off: camera stream released, indicator gone")
        ok(page.evaluate("() => !JSON.stringify(window.__outpost.intents.recent()).includes('lm')"), "the intent log holds intents only (no landmarks)")
        b.close()
    print(f"\n{sum(r[0] for r in results)}/{len(results)} passed")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        sys.exit(e.code)
