"""Settings → Reset, end to end (docs/RESET.md).

1. Make progress: a call sign, patches, prefs, a mission flown, the tour seen (localStorage, as the app keeps them),
   plus files in the backend's per-user cache (a spoken line, a turn log, a saved NASA video, a vector cache).
2. Finding it: "For grown-ups" is the last sidebar item, below Help, with a divider above it and no warning colour
   until it is hovered or selected; it is locked behind a 3-second hold (a click does nothing). Cadets links to it.
   The keyboard reaches it (Alt+A, arrows, Enter), and so does a controller (D-pad, A, B). Voice "reset" opens it.
   None of these erases anything.
3. Start over: the confirm says what goes; a click (not a hold) does nothing; Esc backs out; holding the button 3 s
   resets. [0.4.1] Progress stays: the call sign and Flight School progress (and missions flown) are still there, so
   the app comes back to the map, not the call-sign screen; every other app key is gone; the spoken-line cache and
   turn log are empty; the saved video, the vectors and the bundled media are still there (no re-download).
4. Start over with "Hold to erase progress too": every app key is gone; the app comes back at the call-sign screen.
5. Reset everything: the video and vector caches are empty too.

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


def stale(c: Path, sub: str, t0: float):
    """Files in a cache folder written BEFORE t0 (the reset). The app speaks again right after it comes back (the
    call-sign screen's line), which refills the spoken-line cache: only files from before the reset count."""
    d = c / sub
    return sorted(p.name for p in d.iterdir() if p.is_file() and p.stat().st_mtime < t0 - 0.5) if d.exists() else []


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


PAD = """(() => { const B = () => Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 }));
  const pad = { id: 'Synthetic (STANDARD GAMEPAD)', index: 0, connected: true, mapping: 'standard', buttons: B(), axes: [0, 0, 0, 0], timestamp: 0 };
  let plugged = false;
  Object.defineProperty(navigator, 'getGamepads', { value: () => (plugged ? [pad, null, null, null] : [null, null, null, null]), configurable: true });
  window.__plug = () => { plugged = true; const e = new Event('gamepadconnected'); Object.defineProperty(e, 'gamepad', { value: pad }); dispatchEvent(e); };
  window.__btn = (i, on) => { pad.buttons[i] = { pressed: on, touched: on, value: on ? 1 : 0 }; pad.timestamp++; }; })();"""


def pad(pg, i):
    pg.evaluate(f"() => window.__btn({i}, true)")
    pg.wait_for_timeout(180)
    pg.evaluate(f"() => window.__btn({i}, false)")
    pg.wait_for_timeout(220)


def open_grownups(pg):
    """For grown-ups is locked: hold its gate 3 s (only when it shows the gate)."""
    until(pg, "() => !!document.querySelector('[data-gu-open], [data-reset-open]')", 3000)
    if pg.evaluate("() => !!document.querySelector('[data-gu-open]')"):
        hold(pg, "[data-gu-open]", 3400)
    return until(pg, "() => document.querySelectorAll('[data-reset-open]').length === 2", 3000)


def open_reset(pg, level):
    pg.mouse.click(*pg.evaluate("() => { const q = document.getElementById('a11yBtn').getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }"))
    until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-sec=grownups]')", 5000)
    pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=grownups]').click()")
    open_grownups(pg)
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
        ctx.add_init_script(PAD)
        silence(ctx)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/")
        until(pg, "() => window.__outpost && window.__outpost.a11y", 30000)
        pg.wait_for_timeout(1500)
        before = pg.evaluate(APP_KEYS)
        ok(len(before) >= 6, f"progress made: {len(before)} app keys")

        # ---- the Reset item: last in the sidebar, below Help, after a divider ----
        pg.mouse.click(*pg.evaluate("() => { const q = document.getElementById('a11yBtn').getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }"))
        until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) .set-nav')", 5000)
        nav = pg.evaluate("() => [...document.querySelectorAll('.a11y-panel .set-nav [data-sec]')].map(b => b.textContent.trim())")
        ok(nav[-1] == "For grown-ups" and nav[-2] == "Help", f"the sidebar ends Help, For grown-ups ({nav})")
        ok(not {"Videos", "Help & diagnostics", "What the app has learned", "Reset"} & set(nav), "the grown-up items are not in the sidebar")
        vis = pg.evaluate("""() => { const b = document.querySelector('.a11y-panel .set-nav [data-sec=grownups]'), q = b.getBoundingClientRect(), n = b.closest('.set-nav').getBoundingClientRect();
          const cs = getComputedStyle(b), line = getComputedStyle(b, '::before');
          return {inView: q.bottom <= n.bottom + 1 && q.height > 0, divider: line.borderTopStyle === 'solid', color: cs.color,
                  help: getComputedStyle(document.querySelector('.a11y-panel .set-nav [data-sec=help]')).color}; }""")
        ok(vis["inView"] and vis["divider"], f"For grown-ups is in view with a divider above it ({vis})")
        ok(vis["color"] == vis["help"], "no warning colour until it is hovered or selected")
        # locked: a click on the gate does nothing; nothing grown-up is reachable
        pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=grownups]').click()")
        until(pg, "() => !!document.querySelector('[data-gu-open]')", 3000)
        pg.evaluate("() => document.querySelector('[data-gu-open]').click()")
        pg.wait_for_timeout(400)
        ok(pg.evaluate("() => !document.querySelector('[data-reset-open], [data-vid-clear], [data-dg-save], [data-lr-reset], [data-prof-reset]')"),
           "For grown-ups is locked: a click on the gate opens nothing")
        hold(pg, "[data-gu-open]", 3400)
        parts = pg.evaluate("() => [...document.querySelectorAll('.gu-part')].map(p => p.dataset.gu)")
        ok(until(pg, "() => document.querySelectorAll('[data-reset-open]').length === 2", 3000) and {"reset", "videos", "diagnostics", "learning", "patches"} <= set(parts),
           f"a 3-second hold opens it: Reset, Videos, diagnostics, learning, Reset my patches ({parts})")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        # Cadets links there (locked again: Settings was closed)
        pg.keyboard.press("Alt+a")
        until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden])')", 4000)
        pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=cadets]').click()")
        until(pg, "() => !!document.querySelector('[data-sec-go=grownups]')", 3000)
        pg.evaluate("() => document.querySelector('[data-sec-go=grownups]').click()")
        ok(until(pg, "() => !!document.querySelector('[data-gu-open]')", 3000), "Cadets → For grown-ups (locked again after Settings closed)")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)

        # ---- keyboard: Alt+A opens Settings, arrows reach Reset, Enter opens it, Enter opens Start over, Esc backs out ----
        pg.keyboard.press("Alt+a")
        until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden])')", 4000)
        for _ in range(16):
            if pg.evaluate("() => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.sec === 'reset'"):
                break
            pg.keyboard.press("ArrowDown")
            pg.wait_for_timeout(150)
        pg.keyboard.press("Enter")
        ok(until(pg, "() => !!document.querySelector('[data-gu-open]')", 3000), "keyboard: arrows reach For grown-ups, Enter opens it")
        pg.evaluate("() => document.querySelector('[data-gu-open]').focus()")
        pg.keyboard.down("Enter")
        pg.wait_for_timeout(3400)
        pg.keyboard.up("Enter")
        ok(until(pg, "() => document.querySelectorAll('[data-reset-open]').length === 2", 3000), "keyboard: Enter held 3 s opens the gate")
        pg.evaluate("() => document.querySelector('[data-reset-open=start]').focus()")
        pg.keyboard.press("Enter")
        ok(until(pg, "() => !!document.querySelector('.rs-confirm[data-level=start]')", 3000), "keyboard: Enter on Start over shows the hold-to-confirm")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        ok(not pg.evaluate("() => !!document.querySelector('.rs-confirm')") and set(before) <= set(pg.evaluate(APP_KEYS)), "Esc backs out, nothing erased")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)

        # ---- a controller: D-pad down to Reset, A opens it, B backs out ----
        pg.evaluate("() => window.__plug()")
        pg.keyboard.press("Alt+a")
        until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden])')", 4000)
        for _ in range(16):
            if pg.evaluate("() => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.sec === 'reset'"):
                break
            pad(pg, 13)
        pad(pg, 0)
        ok(until(pg, "() => !!document.querySelector('[data-gu-open]')", 3000), "controller: D-pad reaches For grown-ups, A opens it (locked)")
        pad(pg, 1)
        pad(pg, 1)
        pg.wait_for_timeout(300)

        # ---- voice "reset" opens For grown-ups (its gate); it never confirms or erases ----
        pg.evaluate("() => window.__outpost.a11y.handleText('reset')")
        ok(until(pg, "() => !!document.querySelector('[data-gu-open]') && !document.querySelector('.rs-confirm')", 4000), "voice 'reset' opens For grown-ups, at its gate")
        open_grownups(pg)
        ok(set(before) <= set(pg.evaluate(APP_KEYS)), "… and erases nothing by itself")
        pg.evaluate("() => document.querySelector('[data-reset-open=start]').click()")
        until(pg, "() => !!document.querySelector('.rs-confirm')", 3000)
        ok(pg.evaluate("() => document.activeElement && document.activeElement.matches('[data-reset-cancel]')"), "in the confirm, Cancel has focus first")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        pg.keyboard.press("Escape")

        # ---- Start over: a click is not a hold; a short hold is not enough; 3 s is ----
        ok(open_reset(pg, "start"), "Settings → Reset → Start over shows the confirm")
        what = pg.evaluate("() => document.querySelector('.rs-confirm').innerText")
        ok("Lessons, patches and call signs stay" in what and "Hold to erase progress too" in what, "it says exactly what goes and what stays")
        pg.evaluate("() => document.querySelector('[data-reset-hold]').click()")
        hold(pg, "[data-reset-hold]", 1200)
        pg.wait_for_timeout(500)
        ok(set(before) <= set(pg.evaluate(APP_KEYS)), "a click or a 1.2 s hold does nothing")
        t_reset = time.time()
        with pg.expect_navigation(timeout=15000):
            hold(pg, "[data-reset-hold]", 3400)
        until(pg, "() => window.__outpost && window.__outpost.a11y", 30000)
        pg.wait_for_timeout(1500)
        left = [k for k in pg.evaluate(APP_KEYS) if k not in ("outpost-prefs", "atm-theme")]   # silent.py re-seeds its Mute pref; the default (dark) theme is written at boot
        kept = {"outpost-callsign", "atm-academy", "outpost-missions-flown:Nova"}
        ok(kept <= set(left), f"progress stays: call sign, Flight School progress, missions flown ({left})")
        ok(not [k for k in left if k in before and k not in kept and k != "outpost-profiles"], f"every other app key from before is gone ({left})")
        ok(pg.evaluate("() => JSON.parse(localStorage.getItem('atm-academy')).badges.join(',')") == "scout,history", "the patches are the same")
        ok(until(pg, "() => !document.getElementById('aCsForm') && !!document.querySelector('.mp-top')", 15000), "the app comes back at the map (the call sign stayed)")
        ok(stale(cache, "tts", t_reset) == [] and stale(cache, "turnlog", t_reset) == [],
           f"the spoken-line cache and the turn log hold nothing from before the reset (after: {files(cache, 'tts')})")
        ok(files(cache, "video") and files(cache, "vectors"), f"the saved video and the vectors stay ({files(cache, 'video')}, {files(cache, 'vectors')})")
        ok(pg.evaluate("() => fetch('/api/video/catalog').then(r => r.ok)") and
           pg.evaluate("() => fetch('/media/img/moon4k.jpg', {method: 'HEAD'}).then(r => r.ok)"), "bundled assets still served (no re-download)")

        # ---- Start over with "Hold to erase progress too" ----
        ok(open_reset(pg, "start"), "Start over again")
        with pg.expect_navigation(timeout=15000):
            hold(pg, "[data-reset-erase]", 3400)
        until(pg, "() => window.__outpost && window.__outpost.a11y", 30000)
        pg.wait_for_timeout(1500)
        left = [k for k in pg.evaluate(APP_KEYS) if k not in ("outpost-prefs", "atm-theme")]
        ok(not [k for k in left if k in before], f"erase progress too: every app key from before is gone ({left})")
        ok(until(pg, "() => !!document.getElementById('aCsForm')", 15000), "the app comes back at first launch (the call-sign screen)")

        # ---- Reset everything ----
        seed_cache(cache)
        time.sleep(1.0)
        ok(open_reset(pg, "all"), "Reset everything shows its confirm")
        t_all = time.time()
        with pg.expect_navigation(timeout=15000):
            hold(pg, "[data-reset-hold]", 3400)
        until(pg, "() => window.__outpost && window.__outpost.a11y", 30000)
        ok(all(stale(cache, s, t_all) == [] for s in ("tts", "turnlog", "vectors")) and
           not [n for n in files(cache, "video") if n != "index.json"],
           f"every cache holds nothing from before the reset ({[stale(cache, s, t_all) for s in ('tts', 'turnlog', 'video', 'vectors')]})")
        ok(not errs, f"no page errors {errs[:2]}")
        b.close()
    bad = [w for c, w in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
