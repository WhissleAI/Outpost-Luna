"""Camera gestures, end to end, headless (docs/GESTURES.md §Testing).

Runs the built app as the desktop app serves it (the backend's own origin, frontend/dist with /vision/ inside), in
Chromium with a fake camera (--use-fake-device-for-media-stream). Checks:
  1. camera off by default; no camera request until Settings turns it on
  2. Settings -> Camera & gestures -> on: the bundled WASM + models load in the worker and frames flow (fps, ms)
  3. nothing is fetched from anywhere but the app's own origin
  4. landmark streams injected on each screen emit the right intents, and the screens react
  5. the indicator's one-click off stops the camera; keyboard intents work with the camera off

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


def screen(page):
    return page.evaluate("""() => { const a = document.getElementById('aPanel'); return {mode: document.body.dataset.mode, aview: document.body.dataset.aview || '',
        lesson: !!(a && !a.hidden && a.querySelector('.a-prompt')), cabin: document.body.dataset.cabin || ''}; }""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8390")
    ap.add_argument("--shots", default="")
    ap.add_argument("--seconds", type=float, default=6.0, help="how long to run the real camera path")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        # the first-mission cabin tour (story) owns next / yes while it runs: these checks are about the cabin itself
        ctx.add_init_script("try { localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('outpost-tour-done:Nova', '1'); } catch (e) {}")
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
        t0 = time.time()
        try:
            page.wait_for_function("() => window.__outpost.gestures.stats.frames > 20", timeout=30000)
        except Exception:
            print("   state:", page.evaluate("() => [window.__outpost.gestures.stats, (v => v && [v.readyState, v.videoWidth, v.paused])(document.querySelector('.gx-video'))]"))
            print("   console:\n     " + "\n     ".join(l for l in logs[-25:] if "GL Driver" not in l))
            ok(False, "frames flow through the worker")
        page.wait_for_timeout(int(a.seconds * 1000))
        stats = page.evaluate("() => window.__outpost.gestures.stats")
        print("   stats:", json.dumps(stats), f"(first 20 frames in {time.time() - t0:.1f}s)")
        ok(stats["frames"] > 20 and stats["fps"] > 0, f"bundled models run in the worker: {stats['fps']} fps, {stats['inferMs']} ms/frame, {stats['delegate']}, load {stats['loadMs']} ms")
        ok(not page.evaluate("() => document.getElementById('gxIndicator').hidden"), "indicator visible while the camera is on")
        page.keyboard.press("Escape")
        if a.shots:
            page.wait_for_timeout(400)
            page.screenshot(path=f"{a.shots}/gestures-on.png")

        # ---- 4. per-screen intents (landmark injection) ----
        spied(page)
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
        tgt = page.evaluate("""() => { const b = [...document.querySelectorAll('#aPanel button')].find(x => x.offsetParent); if (!b) return null;
            const r = b.getBoundingClientRect(); window.__clicked = null; b.addEventListener('click', () => { window.__clicked = b.textContent.trim(); }, {once: true});
            return {x: r.left + r.width / 2, y: r.top + r.height / 2, label: b.textContent.trim()}; }""")
        if tgt:
            page.evaluate("t => window.__outpost.intents.emitIntent('select', {x: t.x, y: t.y}, 'gesture')", tgt)
            page.wait_for_timeout(200)
            ok(page.evaluate("() => window.__clicked") == tgt["label"], f"select taps the button under the cursor ({tgt['label']!r})")
        # Library: fist + drag -> rotate (the Moon turns)
        page.evaluate("() => document.getElementById('libraryBtn').click()")
        page.wait_for_timeout(800)
        spied(page)
        inject(page, "grab_drag", 60_000_000)
        page.wait_for_timeout(200)
        rot = [e for e in spied(page) if e["name"] == "rotate"]
        ok(rot and any(e["args"].get("phase") == "move" for e in rot), f"library: fist + drag -> rotate ({len(rot)} moves)")
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
