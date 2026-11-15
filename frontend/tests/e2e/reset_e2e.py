"""Settings → Reset Outpost Luna, end to end (docs/RESET.md).

1. Make progress: a call sign, patches, prefs, a mission flown, the tour seen (localStorage, as the app keeps them),
   plus files in the backend's per-user cache (a spoken line, a turn log, a saved NASA video, a vector cache).
2. Settings → Reset Outpost Luna → Start over: the confirm says what goes; a click (not a hold) does nothing; Esc backs
   out; holding the button 3 s resets. The app comes back at first launch (the call-sign screen), every app key is
   gone, the spoken-line cache and turn log are empty, and the saved video, the vectors and the bundled media are
   still there (no re-download).
3. Reset everything: the video and vector caches are empty too.
4. Voice "reset" only opens the confirm view.

    (backend on :8203 with CACHE_DIR=<dir> serving frontend/dist)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/reset_e2e.py --base http://127.0.0.1:8203 --cache <dir>
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401

sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[tuple[bool, str]] = []
PROGRESS = """try { if (!sessionStorage.getItem('rs-e2e')) { sessionStorage.setItem('rs-e2e', '1');
  localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('outpost-tour-done:Nova', '1');
  localStorage.setItem('atm-academy', JSON.stringify({badges: ['scout', 'history'], qualified: false}));
  localStorage.setItem('outpost-missions-flown:Nova', '2'); localStorage.setItem('outpost-first-mission:Nova', '1');
  localStorage.setItem('atm-theme', 'dark'); localStorage.setItem('outpost-gestures-spin', '{"v":1}'); } } catch (e) {}"""
APP_KEYS = "() => Object.keys(localStorage).filter(k => /^(outpost|atm[-:])/.test(k))"


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)


def seed_cache(c: Path):
    for sub, name in (("tts", "line.mp3"), ("turnlog", "2026-11-15.jsonl"), ("video", "psr.mp4"), ("vectors", "card_vectors_x.npy")):
        (c / sub).mkdir(parents=True, exist_ok=True)
        (c / sub / name).write_text("x")


def files(c: Path, sub: str):
    d = c / sub
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


def until(pg, expr, timeout=10000):
    end = time.time() + timeout / 1000
    while time.time() < end:
        try:
            if pg.evaluate(expr):
                return True
        except Exception:
            pass
        pg.wait_for_timeout(200)
    return False


def hold(pg, sel, ms):
    box = pg.evaluate("s => { const q = document.querySelector(s).getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }", sel)
    pg.mouse.move(*box)
    pg.mouse.down()
    pg.wait_for_timeout(ms)
    pg.mouse.up()


def open_reset(pg, level):
    pg.mouse.click(*pg.evaluate("() => { const q = document.getElementById('a11yBtn').getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }"))
    until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-sec=reset]')", 5000)
    pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=reset]').click()")
    until(pg, "() => !!document.querySelector('[data-reset-open]')", 3000)
    pg.evaluate(f"() => document.querySelector('[data-reset-open={level}]').click()")
    return until(pg, "() => !!document.querySelector('.rs-confirm [data-reset-hold]')", 3000)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8203")
    ap.add_argument("--cache", required=True, help="the backend's CACHE_DIR")
    a = ap.parse_args()
    base, cache = a.base.rstrip("/"), Path(a.cache)
    seed_cache(cache)
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(PROGRESS)
        silence(ctx)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/")
        until(pg, "() => window.__outpost && window.__outpost.a11y", 30000)
        pg.wait_for_timeout(1500)
        before = pg.evaluate(APP_KEYS)
        ok(len(before) >= 6, f"progress made: {len(before)} app keys")

        # ---- voice "reset" only opens the confirm view ----
        pg.evaluate("() => window.__outpost.a11y.handleText('reset')")
        ok(until(pg, "() => !!document.querySelector('.rs-confirm[data-level=start]')", 4000), "voice 'reset' opens the Start over confirm")
        ok(set(before) <= set(pg.evaluate(APP_KEYS)), "… and erases nothing by itself")
        ok(pg.evaluate("() => document.activeElement && document.activeElement.matches('[data-reset-cancel]')"), "Cancel has focus first")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        ok(not pg.evaluate("() => !!document.querySelector('.rs-confirm')") and set(before) <= set(pg.evaluate(APP_KEYS)), "Esc backs out")
        pg.keyboard.press("Escape")

        # ---- Start over: a click is not a hold; a short hold is not enough; 3 s is ----
        ok(open_reset(pg, "start"), "Settings → Reset Outpost Luna → Start over shows the confirm")
        what = pg.evaluate("() => document.querySelector('.rs-confirm').innerText")
        ok("Downloaded voices, crew audio, videos and models stay" in what and "Missions flown" in what, "it says exactly what goes and what stays")
        pg.evaluate("() => document.querySelector('[data-reset-hold]').click()")
        hold(pg, "[data-reset-hold]", 1200)
        pg.wait_for_timeout(500)
        ok(set(before) <= set(pg.evaluate(APP_KEYS)), "a click or a 1.2 s hold does nothing")
        with pg.expect_navigation(timeout=15000):
            hold(pg, "[data-reset-hold]", 3400)
        until(pg, "() => window.__outpost && window.__outpost.a11y", 30000)
        pg.wait_for_timeout(1500)
        left = [k for k in pg.evaluate(APP_KEYS) if k not in ("outpost-prefs",)]   # silent.py re-seeds its Mute pref
        ok(not [k for k in left if k in before], f"every app key from before is gone ({left})")
        ok(until(pg, "() => !!document.getElementById('aCsForm')", 15000), "the app comes back at first launch (the call-sign screen)")
        ok(files(cache, "tts") == [] and files(cache, "turnlog") == [], "the spoken-line cache and the turn log are empty")
        ok(files(cache, "video") and files(cache, "vectors"), f"the saved video and the vectors stay ({files(cache, 'video')}, {files(cache, 'vectors')})")
        ok(pg.evaluate("() => fetch('/api/video/catalog').then(r => r.ok)") and
           pg.evaluate("() => fetch('/media/img/moon4k.jpg', {method: 'HEAD'}).then(r => r.ok)"), "bundled assets still served (no re-download)")

        # ---- Reset everything ----
        seed_cache(cache)
        ok(open_reset(pg, "all"), "Reset everything shows its confirm")
        with pg.expect_navigation(timeout=15000):
            hold(pg, "[data-reset-hold]", 3400)
        until(pg, "() => window.__outpost && window.__outpost.a11y", 30000)
        ok(all(files(cache, s) in ([], ["index.json"]) for s in ("tts", "turnlog", "video", "vectors")),
           f"every cache is empty ({[files(cache, s) for s in ('tts', 'turnlog', 'video', 'vectors')]})")
        ok(not errs, f"no page errors {errs[:2]}")
        b.close()
    bad = [w for c, w in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
