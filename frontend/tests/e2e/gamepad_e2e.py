"""Game controller, end to end, with a synthetic navigator.getGamepads (docs/KEYBOARD.md §Gamepad).

A stub pad (standard mapping) replaces navigator.getGamepads; a `gamepadconnected` event turns the controller layer on.
Checks: off until connected (no poll, no toast); "Controller connected"; the D-pad / left stick move focus; A selects,
B goes back, X toggles the mic, Y opens the help sheet with the controller's buttons, RB / LB are next / prev, the right
stick spins the Moon (spin) and looks around the cabin (look); the cabin seat by D-pad; zero keyboard, zero mouse.

    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/gamepad_e2e.py --base http://127.0.0.1:5297
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402  (owner rule: test runs make no sound)

STUB = """
(() => {
  const B = () => Array.from({ length: 17 }, () => ({ pressed: false, touched: false, value: 0 }));
  const pad = { id: 'Synthetic Xbox Controller (STANDARD GAMEPAD)', index: 0, connected: true, mapping: 'standard', buttons: B(), axes: [0, 0, 0, 0], timestamp: 0 };
  let plugged = false;
  window.__pad = pad;
  Object.defineProperty(navigator, 'getGamepads', { value: () => (plugged ? [pad, null, null, null] : [null, null, null, null]), configurable: true });
  window.__plug = () => { plugged = true; const e = new Event('gamepadconnected'); Object.defineProperty(e, 'gamepad', { value: pad }); dispatchEvent(e); };
  window.__unplug = () => { plugged = false; const e = new Event('gamepaddisconnected'); Object.defineProperty(e, 'gamepad', { value: pad }); dispatchEvent(e); };
  window.__btn = (i, on) => { pad.buttons[i] = { pressed: on, touched: on, value: on ? 1 : 0 }; pad.timestamp++; };
  window.__axes = (a) => { pad.axes = a; pad.timestamp++; };
  window.__ptr = 0; window.__keys = 0;
  ['pointerdown', 'mousedown'].forEach(t => addEventListener(t, e => { if (e.isTrusted) window.__ptr++; }, true));
  addEventListener('keydown', e => { if (e.isTrusted) window.__keys++; }, true);
  try { localStorage.setItem('outpost-callsign', 'Nova'); } catch (e) {}
})();
"""
A, B, X, Y, LB, RB, UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3, 4, 5, 12, 13, 14, 15
results = []


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        raise SystemExit(1)


ACTIVE = "() => { const a = document.activeElement || document.body; return { id: a.id || '', cls: String(a.className || ''), l: (a.dataset && a.dataset.l) || '', panel: (a.dataset && a.dataset.panel) || '' }; }"
SPY = "() => { window.__seen = []; window.__outpost.intents.onIntent('*', (a, ev) => { window.__seen.push(ev.name + ':' + ev.source); return false; }, { priority: 100 }); }"


def wait_js(pg, expr, timeout=20000):
    """Polled from Python (wait_for_function starves while the WebGL scenes render)."""
    import time
    end = time.time() + timeout / 1000
    while time.time() < end:
        try:
            if pg.evaluate(expr):
                return True
        except Exception:
            pass
        pg.wait_for_timeout(250)
    raise SystemExit("FAIL timeout: " + expr + " active=" + str(pg.evaluate(ACTIVE)) + " input=" + str(pg.evaluate("() => document.documentElement.dataset.input + ' ' + document.body.dataset.cabin + ' ' + (document.querySelector('.c3-gl') && document.querySelector('.c3-gl').parentElement.dataset.panel)")))


def run_page(b, base, seed):
    ctx = b.new_context(viewport={"width": 1280, "height": 800})
    ctx.add_init_script(STUB + seed)
    silence(ctx)
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: print("PAGEERR", str(e)[:300]))
    pg.goto(base + "/")
    pg.wait_for_timeout(3500)
    pg.evaluate(SPY)
    return pg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5297")
    base = ap.parse_args().base.rstrip("/")
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--enable-unsafe-swiftshader"])

        # ---------------- Flight School map + a lesson ----------------
        pg = run_page(b, base, "")
        js, act = pg.evaluate, lambda: pg.evaluate(ACTIVE)

        def tap(i, ms=500):
            js(f"() => window.__btn({i}, true)"); pg.wait_for_timeout(90); js(f"() => window.__btn({i}, false)"); pg.wait_for_timeout(ms)

        def seen(clear=True):
            s = js("() => window.__seen.slice()")
            if clear:
                js("() => { window.__seen.length = 0; }")
            return s

        pg.wait_for_selector(".mp-card", timeout=20000)
        tap(A, 400)
        ok(not seen(), "off until a controller connects: a button press before connecting does nothing")
        ok(js("() => document.documentElement.dataset.input || ''") != "pad", "no pad mode before connecting")
        js("() => window.__plug()")
        pg.wait_for_timeout(400)
        ok("Controller connected" in js("() => (document.querySelector('.keys-toast') || {}).textContent || ''"), "connect: the 'Controller connected' toast")
        tap(DOWN, 600)
        ok(js("() => document.documentElement.dataset.input") == "pad", "the D-pad switches to pad mode (A / B hints)")
        ok(act()["id"] == "aStart", "D-pad: focus lands on Start")
        ok("move:gamepad" in seen(), "D-pad emits move on the bus (source gamepad)")
        tap(UP, 900)
        ok("pin" in act()["cls"], "D-pad up: a lesson pin")
        l0 = act()["l"]
        js("() => window.__axes([0, 0.95, 0, 0])"); pg.wait_for_timeout(120); js("() => window.__axes([0, 0, 0, 0])"); pg.wait_for_timeout(900)
        # learning v1 put two explorer pins and a Mission prep button on the map, so "the next thing down" from a pin
        # can be the next pin or the lesson card's button: the stick must move focus to one of them
        nx = act()
        ok(("pin" in nx["cls"] and nx["l"] != l0) or nx["id"] in ("aPrepMap", "aStart"), "left stick: moves focus down (the next pin or the card)")
        seen()
        js("() => window.__axes([0, 0, 0.8, 0])"); pg.wait_for_timeout(500); js("() => window.__axes([0, 0, 0, 0])"); pg.wait_for_timeout(300)
        ok(any(s == "spin:gamepad" for s in seen()), "right stick: spins the Moon (spin, the fist's rate control)")
        tap(Y, 600)
        ok(js("() => !document.getElementById('keysHelp').hidden"), "Y: the help sheet")
        ok("Controller" in js("() => document.getElementById('keysHelp').textContent"), "help lists the controller's buttons")
        tap(B, 600)
        ok(js("() => document.getElementById('keysHelp').hidden"), "B: closes the help sheet (back)")
        m0 = js("() => document.getElementById('mic').getAttribute('aria-label')")
        tap(X, 1200)
        ok(js("() => document.getElementById('mic').getAttribute('aria-label')") != m0, "X: mic on / off")
        tap(RB, 2500)
        if pg.query_selector("#aPrepDone") is not None:   # learning v1: Mission prep first; A takes Done
            ok(act()["id"] == "aPrepDone", "RB (next): Mission prep first, focus on Done")
            tap(A, 2500)
        ok(pg.query_selector("#aInput") is not None, "RB (next) on the map: the next lesson opens")
        ok(js("() => !!document.activeElement && document.activeElement.id === 'moonFocus'"), "a Moon step: focus on the Moon reticle")
        tap(RIGHT, 1600)
        ok(bool(js("() => document.querySelector('#moonFocus .mf-name').textContent")), "D-pad on the Moon: hops to a place")
        tap(A, 1500)
        ok("select:gamepad" in seen(), "A: select (taps the Moon)")
        tap(B, 1500)
        ok(pg.query_selector(".mp-card") is not None, "B in a lesson: back to the map")
        ok(js("() => window.__ptr + window.__keys") == 0, "zero mouse, zero keyboard")
        pg.context.close()

        # ---------------- Mission: picker + cabin ----------------
        pg = run_page(b, base, "try { localStorage.setItem('atm-academy', JSON.stringify({badges: ['scout','radio','sun','shield','air','history','commander'], qualified: true})); } catch (e) {}")
        js, act = pg.evaluate, lambda: pg.evaluate(ACTIVE)
        js("() => window.__plug()")
        pg.wait_for_selector("#mStart", timeout=20000)
        tap(DOWN, 600)
        ok(act()["id"] == "mStart", "picker: D-pad lands on Take command")
        s0 = js("() => document.querySelector('.mx-site[aria-checked=true]').dataset.site")
        tap(RB, 900)
        ok(js("() => document.querySelector('.mx-site[aria-checked=true]').dataset.site") != s0, "picker: RB picks the next site")
        tap(LB, 900)
        tap(A, 4000)
        if pg.query_selector("#mlSkip") is not None:   # learning v1: the first mission offers NASA's Moon Base video once
            ok(act()["id"] == "mlWatch", "first mission: the Moon Base card, focus on Watch")
            tap(B, 4000)                                # B = no: skip it, the mission starts
        wait_js(pg, "() => document.body.dataset.cabin === '1' && !!document.querySelector('#mCabin .c3-panel')", 30000)
        pg.wait_for_timeout(1500)
        if js("() => !!document.querySelector('.m-tour:not([hidden])')"):   # the first-mission cabin tour (story)
            wait_js(pg, "() => document.activeElement && document.activeElement.matches('.m-tour .t-next')", 8000)
            ok(True, "tour: focus on Next")
            e0 = js("() => document.querySelector('.m-tour .t-eye').textContent")
            tap(A, 1500)
            ok(js("() => !document.querySelector('.m-tour:not([hidden])') || document.querySelector('.m-tour .t-eye').textContent !== %r" % e0), "tour: A advances it")
            tap(B, 1500)
            ok(js("() => !document.querySelector('.m-tour:not([hidden])')"), "tour: B skips it")
        wait_js(pg, "() => document.activeElement && document.activeElement.id === 'seatFocus'", 8000)
        ok(act()["id"] == "seatFocus", "cabin: A took command; focus on a console panel")
        p0 = act()["panel"]
        tap(LEFT, 600)
        ok(act()["panel"] != p0, "cabin: D-pad lights another panel")
        tap(A, 1400)
        ok(js("() => document.querySelector('.c3-gl').parentElement.dataset.panel") not in ("seat", ""), "cabin: A opens it")
        tap(B, 1400)
        ok(js("() => document.querySelector('.c3-gl').parentElement.dataset.panel") == "seat", "cabin: B back to the seat")
        js("() => { window.__seen.length = 0; }")
        js("() => window.__axes([0, 0, -0.9, 0])"); pg.wait_for_timeout(400); js("() => window.__axes([0, 0, 0, 0])"); pg.wait_for_timeout(300)
        s = js("() => window.__seen.slice()")
        ok("look:gamepad" in s, "cabin: right stick looks around (look)")
        js("() => window.__unplug()"); pg.wait_for_timeout(400)
        ok("disconnected" in js("() => (document.querySelector('.keys-toast') || {}).textContent || ''"), "unplug: 'Controller disconnected'")
        ok(js("() => window.__ptr + window.__keys") == 0, "zero mouse, zero keyboard")
        b.close()
    print(f"{sum(1 for r in results if r[0])}/{len(results)} checks")


if __name__ == "__main__":
    main()
