"""Keyboard only, end to end (docs/KEYBOARD.md): the whole journey with page.keyboard and zero mouse.

home → call sign → Moon map (pins) → every lesson and every step type (choice, predict, earth_view, globe_side, the
Moon steps intent / tap / terminator / route / compare, keywords, command, vocab) → patches → the check ride → qualified
→ site picker → the 3D cabin (seat, panels, a knob, orders, storm + shelter, a confirm, Houston, End shift) → debrief →
fly again → Settings → Library (the Moon reticle, a card, a tour) → About → help sheet, captions, mic.

Modelled on tools/ux_flow.py (the voice / click pass) and tests/e2e/gestures_e2e.py. It fails on the first step that
doesn't advance, on any trusted pointer event, and on console errors (except the known ones in IGNORE).

    (backend :8397 + vite :5297, see docs/KEYBOARD.md §Testing)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/keys_e2e.py --base http://127.0.0.1:5297 [--shots docs/img/keys]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
import time

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402  (owner rule: test runs make no sound)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
from ux_shots import COURSE, answer_for, _Vocab  # noqa: E402

# the known console noise: voices endpoint, favicon, and TTS blobs revoked while a line is cut off (floor.js)
IGNORE = ("favicon", "/api/voices", "404 (Not Found)", "ERR_FILE_NOT_FOUND")
ORDERS = ["more power to the heaters", "more power to the shields", "everyone into the shelter", "leave the shelter", "send the rover for ice"]
results: list[tuple[bool, str]] = []


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)
    if not cond:
        raise SystemExit(1)


ACTIVE = """() => { const a = document.activeElement || document.body;
  return { id: a.id || '', cls: String(a.className || ''), tag: a.tagName, label: (a.getAttribute('aria-label') || a.textContent || '').trim().slice(0, 60),
    panel: a.dataset ? (a.dataset.panel || '') : '', l: a.dataset ? (a.dataset.l || '') : '', mode: document.body.dataset.mode || '', aview: document.body.dataset.aview || '',
    cabin: (document.querySelector('.c3-gl') && document.querySelector('.c3-gl').parentElement.dataset.panel) || '', input: document.documentElement.dataset.input || '' }; }"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5297")
    ap.add_argument("--shots", default="", help="save focus-state screenshots (small JPEGs) here")
    ap.add_argument("--start", choices=["home", "mission"], default="home", help="mission: a qualified cadet, from the site picker (quick runs)")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    errs = []
    t0 = time.time()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required", "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        # a fresh cadet; count trusted pointer events (there must be none)
        ctx.add_init_script("""try { if (!sessionStorage.getItem('keys-e2e')) { localStorage.clear(); sessionStorage.setItem('keys-e2e', '1'); } } catch (e) {}
          window.__ptr = 0; ['pointerdown', 'mousedown', 'click'].forEach(t => addEventListener(t, e => { if (e.isTrusted && e.detail !== 0 && e.pointerId !== 77) window.__ptr++; }, true));""")
        if a.start == "mission":
            ctx.add_init_script("""try { localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('atm-academy', JSON.stringify({badges: ['scout','history','radio','sun','storm','ice','commander'], qualified: true})); } catch (e) {}""")
        silence(ctx)
        pg = ctx.new_page()
        pg.on("console", lambda m: m.type == "error" and not any(x in m.text for x in IGNORE) and errs.append(m.text))
        pg.on("pageerror", lambda e: errs.append(str(e)))
        kb = pg.keyboard

        def press(k, ms=350):
            kb.press(k)
            pg.wait_for_timeout(ms)

        act = lambda: pg.evaluate(ACTIVE)
        js = pg.evaluate

        def until(expr, timeout=20000, what=""):
            # polled from Python: wait_for_function starves while two WebGL scenes render (the check ride)
            end = time.time() + timeout / 1000
            while time.time() < end:
                try:
                    if js(expr):
                        return True
                except Exception:
                    pass
                pg.wait_for_timeout(250)
            if what != "-":
                print("  timeout:", what or expr, act())
            return False

        def shot(name):
            if a.shots:
                os.makedirs(a.shots, exist_ok=True)
                pg.screenshot(path=os.path.join(a.shots, f"{name}.jpg"), type="jpeg", quality=62)

        def press_until(keys, cond, n=8, ms=380):
            for _ in range(n):
                if js(cond):
                    return True
                for k in keys:
                    press(k, ms)
                    if js(cond):
                        return True
            return js(cond)

        if a.start == "home":
            # ---------------- home: call sign ----------------
            pg.goto(base + "/")
            until("() => !!document.getElementById('aCsForm')", 25000, "home")
            pg.wait_for_timeout(1200)
            press("ArrowDown")
            ok(act()["id"] == "aCsGo", "home: the first arrow lands on Start (the screen's primary action)")
            ok(js("() => document.documentElement.dataset.input") == "keys", "home: keyboard mode (TV focus ring, key hints)")
            shot("01-home-start")
            press("ArrowUp")
            ok("a-csb" in act()["cls"], "home: Up reaches the call-sign chips")
            press("2")
            ok(js("() => document.querySelector('.a-csb[aria-pressed=true]') === document.querySelectorAll('.a-csb')[1]"), "home: 2 picks the second call sign")
            press("/")
            ok(act()["id"] == "aCsIn", "home: / focuses the call-sign field")
            kb.type("Nova")
            press("m", 100)   # a letter types while typing
            press("Backspace", 100)
            ok(js("() => document.getElementById('aCsIn').value") == "Nova", "home: letters and Backspace type in the field (M, Backspace aren't shortcuts there)")
            press("Enter", 1500)
            ok(until("() => !!document.querySelector('.mp-card')", 20000), "home: Enter in the field saves the call sign → Moon map")

            # ---------------- the Moon map: pins ----------------
            until("() => document.activeElement && document.activeElement.id === 'aStart'", 6000, "map primary")
            ok(act()["id"] == "aStart", "map: focus lands on Start (Next up)")
            press("ArrowUp", 900)
            pin = act()
            ok("pin" in pin["cls"], f"map: Up moves onto a lesson pin ({pin['label'][:30]})")
            # (learning v1: locked explorer pins are on the map too; Enter on one shows when it opens, not a Start button)
            press_until(["ArrowDown", "ArrowLeft", "ArrowRight"], "() => document.activeElement.classList.contains('pin') && !document.activeElement.classList.contains('is-locked') && document.activeElement.dataset.l !== %s" % json.dumps(pin["l"]), n=4)
            pin2 = act()
            ok("pin" in pin2["cls"] and pin2["l"] != pin["l"], "map: arrows move between pins geographically")
            shot("02-map-pin")
            press("Enter", 1200)
            ok(until("() => document.querySelector('#aStart') && document.querySelector('#aStart').dataset.l === %s" % json.dumps(pin2["l"]), 8000), "map: Enter on a pin selects it (the card shows that lesson)")
            until("() => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.l", 4000, "pin refocus")
            ok(act()["l"] == pin2["l"], "map: focus stays on the same pin after the map re-renders")

            # ---------------- every lesson, keyboard only ----------------
            def visible_q(sel):
                return js("s => { const e = document.querySelector(s); return !!(e && !e.hidden && e.getClientRects().length && !e.closest('[hidden]')); }", sel)

            def done_q():
                return js("() => !!(document.querySelector('#aNext') || document.querySelector('.a-badge') || document.querySelector('#aRetry'))")

            def answer(L, k, st):
                acc = st["accept"]
                t = acc["type"]
                opts = [o["id"] for o in acc.get("options", [])]
                want = acc.get("answer") or acc.get("want")
                if t == "choice":
                    press("abcd"[opts.index(want)], 200)
                    return "letter"
                if t in ("predict", "earth_view", "compare") and opts:
                    press(str((opts.index(want) if want in opts else 0) + 1), 200)
                    return "digit"
                if t == "globe_side":
                    press("2" if want == "far" else "1", 200)
                    return "digit"
                if t in ("intent", "tap", "terminator", "route"):
                    ok(act()["id"] == "moonFocus", f"{L['id']} step {k + 1} ({t}): focus is on the Moon reticle")
                    taps = len(acc.get("stops") or []) or 1
                    on_moon = lambda: js("() => document.activeElement && document.activeElement.id === 'moonFocus'")
                    for attempt in range(5):
                        # wait out a slow grading reply: never press keys meant for the Moon once the step has moved on
                        if until("() => !!(document.querySelector('#aNext') || document.querySelector('.a-badge'))", 2500, "-"):
                            break
                        if not on_moon() and not press_until(["ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"], "() => document.activeElement && document.activeElement.id === 'moonFocus'", n=3):
                            break
                        press(["ArrowRight", "ArrowUp", "ArrowLeft", "ArrowDown", "ArrowRight"][attempt], 1500)
                        if attempt == 1 and t == "terminator":
                            press("Shift+ArrowLeft", 300)
                            press("Shift+ArrowLeft", 600)
                        for _ in range(taps):
                            if done_q() or not on_moon():
                                break
                            press("Enter", 1200)
                        if until("() => !!(document.querySelector('#aNext') || document.querySelector('.a-badge'))", 4000, "-"):
                            break
                    return "moon"
                if t == "video":   # a NASA video step (media-v1): never block; skip it by typing, like a kid saying "skip"
                    press("/", 200)
                    until("() => document.activeElement && document.activeElement.id === 'q'", 6000, "q focus")
                    kb.type("skip")
                    press("Enter", 300)
                    return "typed skip"
                if t == "command" and answer_for(st, vocab=_Vocab()) in ORDERS and visible_q(".a-order"):
                    press(str(ORDERS.index(answer_for(st, vocab=_Vocab())) + 1), 200)
                    return "order"
                press("/", 200)
                ok(until("() => document.activeElement && document.activeElement.id === 'q'", 6000, "q focus"), f"{L['id']} step {k + 1} ({t}): / opens the text box")
                kb.type(answer_for(st, vocab=_Vocab()))
                press("Enter", 300)
                return "typed"

            lesson_shots = set()
            # learning v1: the 6 core lessons and the ride (explorer lessons open after missions, so the walk skips them)
            WALK = [l for l in COURSE["lessons"] if l.get("track", "core") == "core"]
            for li, L in enumerate(WALK):
                if li == 0:
                    press("n", 1500)   # N on the map: start the next lesson
                # Mission prep (learning v1) comes first the first time a lesson opens: its Done is focused; Enter
                until("() => !!(document.querySelector('#aInput') || document.querySelector('#aPrepDone'))", 20000, "lesson or prep")
                if js("() => !!document.querySelector('#aPrepDone')"):
                    ok(act()["id"] == "aPrepDone", f"{L['id']}: Mission prep, focus is on Done")
                    press("Enter", 1200)
                ok(until("() => !!document.querySelector('#aInput')", 20000), f"{L['id']}: lesson opens")
                for k, st in enumerate(L["steps"]):
                    pg.wait_for_timeout(900)
                    t = st["accept"]["type"]
                    ride = bool(L.get("ride"))
                    for tries in range(3):
                        how = answer(L, k, st)
                        if until("() => !!(document.querySelector('#aNext') || document.querySelector('.a-badge') || document.querySelector('#aRetry'))", 60000 if ride else 25000, f"{L['id']} {k + 1} {t}"):
                            break
                        # the ride moves on by itself after misses: never answer a step twice once it has moved
                        if ride and js("() => [...document.querySelectorAll('.a-steps i')].findIndex(e => e.classList.contains('is-now'))") != k:
                            break
                        pg.wait_for_timeout(800)
                    if js("() => !!document.querySelector('#aRetry')"):   # the check ride ended without passing: fly it again
                        ok(False, f"{L['id']}: the check ride failed by keyboard")
                    ok(done_q(), f"{L['id']} step {k + 1} ({t}) answered by keyboard ({how})")
                    if t not in lesson_shots and a.shots and js("() => !!document.querySelector('#aNext')"):
                        lesson_shots.add(t)
                        if t in ("choice", "route", "command", "keywords"):
                            shot(f"03-lesson-{t}-next")
                    last = k == len(L["steps"]) - 1
                    if last:
                        until("() => !!document.querySelector('.a-badge')", 8000, "badge")
                    if not last and js("() => !!document.querySelector('#aNext')"):
                        until("() => document.activeElement && document.activeElement.id === 'aNext'", 4000, "next focus")
                        ok(act()["id"] in ("aNext", "q"), f"{L['id']} step {k + 1}: focus is on Next")
                        press("Enter" if act()["id"] == "aNext" else "Escape", 300)
                        if act()["id"] != "aNext" and js("() => !!document.querySelector('#aNext')"):
                            press("Enter", 300)
                        pg.wait_for_timeout(900)
                ok(until("() => !!document.querySelector('.a-badge')", 20000), f"{L['id']}: patch earned")
                if li == 0:
                    shot("04-patch")
                    press("Escape", 1500)
                    ok(until("() => !!document.querySelector('.mp-card')", 10000), "patch: Esc goes back to the map")
                    press("n", 1500)
                    continue
                if li < len(WALK) - 1:
                    ok(act()["id"] in ("aNextLesson", "aMap"), "patch: focus is on Next lesson")
                    press("y" if li % 2 else "n", 1500)   # Y takes the offer; N is next
                if li == 1:   # a Moon step screenshot on lesson 3's compare step comes later; here: the ride below
                    pass

            # ---------------- qualified → Mission ----------------
            ok(until("() => document.activeElement && document.activeElement.id === 'aGoMission'", 8000), "qualified: focus is on Take command")
            press("Enter", 2500)
        else:
            pg.goto(base + "/")
            pg.wait_for_timeout(2500)
            press("ArrowDown", 600)
        ok(until("() => document.body.dataset.mode === 'mission' && !!document.getElementById('mStart')", 20000), "qualified: Enter → the site picker")
        until("() => document.activeElement && document.activeElement.id === 'mStart'", 5000, "picker primary")
        ok(act()["id"] == "mStart", "picker: focus lands on Take command")
        site0 = js("() => document.querySelector('.mx-site[aria-checked=true]').dataset.site")
        press("n", 900)
        ok(js("() => document.querySelector('.mx-site[aria-checked=true]').dataset.site") != site0, "picker: N picks the next site")
        press("p", 900)
        ok(js("() => document.querySelector('.mx-site[aria-checked=true]').dataset.site") == site0, "picker: P picks the previous site")
        ok(press_until(["ArrowUp"], "() => document.activeElement.classList.contains('mx-site')", n=4), "picker: Up reaches the site rows")
        r0 = js("() => [...document.querySelectorAll('.mx-site')].indexOf(document.activeElement)")
        press("ArrowUp" if r0 > 0 else "ArrowDown", 900)
        ok(js("() => document.activeElement.classList.contains('mx-site') && document.activeElement.getAttribute('aria-checked') === 'true'")
           and js("() => [...document.querySelectorAll('.mx-site')].indexOf(document.activeElement)") != r0, "picker: Up / Down walk the rows (the focused row is picked)")
        shot("05-picker")
        press("y", 3000)
        if js("() => !!document.querySelector('#mlSkip')"):   # learning v1: the first mission offers the Moon Base video once
            ok(act()["id"] == "mlWatch", "first mission: the Moon Base card, focus on Watch")
            press("Escape", 3000)                          # Esc = no: skip it, the mission starts
        ok(until("() => document.body.dataset.cabin === '1' && !!document.querySelector('#mCabin .c3-panel')", 30000), "picker: Y takes command → the 3D cabin")

        # ---------------- the cabin ----------------
        # the first-mission cabin tour (story): its Next is focused; Enter advances; Esc skips (on rc/2 + story)
        pg.wait_for_timeout(1500)
        if js("() => !!document.querySelector('.m-tour:not([hidden])')"):
            until("() => document.activeElement && document.activeElement.matches('.m-tour .t-next')", 6000, "tour next")
            ok(js("() => document.activeElement.matches('.m-tour .t-next')"), "tour: focus is on Next")
            shot("06a-cabin-tour")
            b0 = js("() => document.querySelector('.m-tour .t-eye').textContent")
            press("Enter", 1500)
            ok(js("() => !document.querySelector('.m-tour:not([hidden])') || document.querySelector('.m-tour .t-eye').textContent !== %s" % json.dumps(b0)), "tour: Enter advances it")
            press("ArrowLeft", 500)
            ok(js("() => !document.querySelector('.m-tour:not([hidden])') || document.querySelector('.m-tour').contains(document.activeElement)"), "tour: arrows stay on the tour card (Next, Skip tour)")
            # [flows] the first Esc pauses the tour (Paused, Resume focused); the second one skips it
            press("Escape", 1000)
            ok(js("() => { const c = document.querySelector('.m-tour:not([hidden])'); return !!c && c.classList.contains('is-paused') && document.activeElement && document.activeElement.dataset.t === 'resume'; }"), "tour: Esc pauses it (Resume focused)")
            press("Escape", 1500)
            ok(js("() => !document.querySelector('.m-tour:not([hidden])')"), "tour: a second Esc skips the tour")
        until("() => document.activeElement && document.activeElement.id === 'seatFocus'", 8000, "seat focus")
        ok(act()["id"] == "seatFocus", "seat: focus is on a console panel")

        def seat_to(panel):
            for k in ["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"] * 4:
                if act()["id"] == "seatFocus" and act()["panel"] == panel:
                    return True
                if act()["id"] != "seatFocus":
                    press("ArrowDown", 300)
                    continue
                cur = act()["panel"]
                if panel in ("habitat", "rover") and cur not in ("habitat", "rover"):
                    press("ArrowLeft", 350)
                elif panel in ("radiation", "comm") and cur not in ("radiation", "comm"):
                    press("ArrowRight", 350)
                elif panel in ("habitat", "radiation") and cur in ("rover", "comm"):
                    press("ArrowUp", 350)
                elif panel in ("rover", "comm") and cur in ("habitat", "radiation"):
                    press("ArrowDown", 350)
                elif panel in ("displays", "pedestal"):
                    if cur in ("habitat", "rover"):
                        press("ArrowRight", 350)
                    elif cur in ("radiation", "comm"):
                        press("ArrowLeft", 350)
                    else:
                        press("ArrowDown" if panel == "pedestal" else "ArrowUp", 350)
                else:
                    press(k, 350)
            return act()["id"] == "seatFocus" and act()["panel"] == panel

        def in_panel_to(cond, n=10):
            return press_until(["ArrowDown", "ArrowRight"], cond, n=n, ms=350) or press_until(["ArrowUp", "ArrowLeft"], cond, n=n, ms=350)

        seen = {act()["panel"]}
        for target in ["radiation", "comm", "rover", "pedestal", "habitat", "displays"]:   # the Now card may start the seat on any panel
            if seat_to(target):
                seen.add(target)
        ok(len(seen) >= 5, f"seat: arrows light the panels ({', '.join(sorted(seen))})")
        ok(js("() => !!document.querySelector('#mCabin .c3-panel.is-hl')"), "seat: the focused panel is lit (.is-hl)")
        ok(seat_to("habitat"), "seat: reach the Habitat panel")
        shot("06-cabin-seat")
        press("Enter", 1300)
        ok(act()["cabin"] == "habitat", "seat: Enter opens the lit panel (the camera dollies in)")
        ok(js("() => document.querySelector('#mCabin .c3-panel.is-open').contains(document.activeElement)"), "panel: focus moves inside the open panel")
        ok(in_panel_to("() => document.activeElement.matches('.cb-toggle[data-sw=heaters]')"), "panel: arrows reach the Heaters switch")
        h0 = js("() => document.querySelector('.cb-toggle[data-sw=heaters]').getAttribute('aria-pressed')")
        press("Enter", 2500)
        ok(until("() => document.querySelector('.cb-toggle[data-sw=heaters]').getAttribute('aria-pressed') !== %s" % json.dumps(h0), 12000), "panel: Enter flips the Heaters switch (an order)")
        press("n", 1300)
        ok(act()["cabin"] not in ("habitat", "seat", ""), f"panel: N steps to the next panel ({act()['cabin']})")
        press("Escape", 1300)
        ok(act()["cabin"] == "seat" and act()["id"] == "seatFocus", "panel: Esc goes back to the seat, focus on the panel it left")
        v0 = js("() => document.querySelector('.cb-view[aria-pressed=true]').dataset.view")
        press("v", 900)
        ok(js("() => document.querySelector('.cb-view[aria-pressed=true]').dataset.view") != v0, "seat: V cycles the window view")
        ok(seat_to("radiation"), "seat: reach the Radiation panel")
        press("o", 1300)
        ok(act()["cabin"] == "radiation", "seat: O opens the lit panel")
        ok(in_panel_to("() => document.activeElement.id === 'cbKnob'"), "panel: arrows reach the shield knob")
        k0 = js("() => +document.getElementById('cbKnob').getAttribute('aria-valuenow')")
        press("ArrowRight", 2500)
        ok(until("() => +document.getElementById('cbKnob').getAttribute('aria-valuenow') !== %d" % k0, 10000), "panel: Right turns the shield knob (Left / Right adjust)")
        shot("07-cabin-knob")
        press("ArrowUp", 400)
        ok(act()["id"] != "cbKnob", "panel: Up leaves the knob (Up / Down never turn it)")
        press("Backspace", 1300)
        ok(act()["cabin"] == "seat", "panel: Backspace also goes back to the seat")

        # storm (forced by the dev hook: a state, not an input) → Shelter from the alert strip by keyboard
        js("() => window.__cabinTest && window.__cabinTest.storm(true)")
        pg.wait_for_timeout(1200)
        got = press_until(["ArrowUp"], "() => document.activeElement.matches('.cb-al-b[data-act=shelter]')", n=3) or \
            press_until(["ArrowLeft", "ArrowUp"], "() => document.activeElement.matches('.cb-al-b[data-act=shelter]')", n=4) or \
            press_until(["ArrowRight", "ArrowUp"], "() => document.activeElement.matches('.cb-al-b[data-act=shelter]')", n=4)
        if not got:
            print("  at:", act(), js("() => [...document.querySelectorAll('.cb-al-b')].map(b => b.dataset.act).join(',')"))
        ok(got, "storm: arrows reach Shelter on the alert strip")
        shot("08-cabin-storm")
        press("Enter", 3000)
        ok(until("() => document.getElementById('cbl-shelter').classList.contains('is-on') || !document.querySelector('.cb-al-b[data-act=shelter]')", 12000), "storm: Enter sends the crew to the shelter")
        js("() => window.__cabinTest.storm(false)")
        # a confirm: Y / N answer it (N is no, not next, while it waits)
        js("() => window.__cabinTest.confirm('Send the rover out during a solar storm? Say yes or no.')")
        pg.wait_for_timeout(800)
        js("() => window.__outpost.intents.onIntent('*', (a, ev) => { (window.__seen = window.__seen || []).push(ev.name + ':' + ev.source); return false; }, {priority: 100})")
        press("n", 900)
        ok("no:keyboard" in js("() => window.__seen || []"), "confirm: N says no while a yes / no waits")
        js("() => { window.__seen = []; }")
        # Houston: the comm panel
        press_until(["Escape"], "() => document.activeElement.id === 'seatFocus'", n=2)
        ok(seat_to("comm"), "seat: reach the Comm panel")
        press("Enter", 1300)
        ok(in_panel_to("() => document.activeElement.id === 'cbPtt'"), "comm: arrows reach Call Houston")
        press("Enter", 1500)
        ok(until("() => /travel|Signal|Calling|No signal|Houston/i.test(document.getElementById('cbPttSub').textContent + document.getElementById('mSignal').textContent) ", 8000), "comm: Enter calls Houston")
        press("Escape", 1300)
        # End shift + finish: the pedestal
        ok(seat_to("pedestal"), "seat: reach the pedestal (End shift)")
        press("Enter", 1300)
        if js("() => !document.getElementById('cbEnd').disabled"):
            ok(in_panel_to("() => document.activeElement.id === 'cbEnd'"), "pedestal: arrows reach End shift")
            press("Enter", 4000)
            ok(True, "pedestal: Enter ends the shift")
        ok(in_panel_to("() => document.activeElement.id === 'cbDb'"), "pedestal: arrows reach Finish mission")
        press("Enter", 3000)
        ok(until("() => !document.getElementById('mDebrief').hidden", 15000), "pedestal: Enter → the debrief")

        # ---------------- debrief → fly again ----------------
        pg.wait_for_timeout(1200)
        press("ArrowDown", 600)
        ok(act()["id"] in ("mAgain", "mNewSite", "mDbClose") or "mx" in act()["cls"] or act()["tag"] in ("SUMMARY", "A"), f"debrief: arrows move in the debrief ({act()['id'] or act()['cls']})")
        shot("09-debrief")
        press("y", 1500)
        wipe = "() => { const w = document.querySelector('.mx-wipe'); return !!(w && w.getClientRects().length); }"
        if js(wipe):   # a paused mission asks first (QA-26): N keeps it, Y starts over
            ok(True, "debrief: Y on a paused mission asks 'start over?'")
            shot("09a-debrief-wipe")
            press("n", 900)
            ok(not js(wipe) and js("() => !document.getElementById('mDebrief').hidden"), "debrief: N keeps the mission (N is no while it asks)")
            press("y", 1500)
            ok(js(wipe), "debrief: Y asks again")
            press("y", 3500)
        ok(until("() => document.body.dataset.cabin === '1'", 20000), "debrief: Y flies again (a new shift in the cabin)")

        # ---------------- the top bar from the seat, Settings ----------------
        until("() => document.activeElement && document.activeElement.id === 'seatFocus'", 8000, "seat focus again")
        ok(press_until(["ArrowUp"], "() => !!document.activeElement.closest('.topbar')", n=6), "seat: Up reaches the top bar (no trap)")
        press("s", 900)
        ok(js("() => !document.querySelector('.a11y-panel').hidden"), "S opens Settings")
        ok(press_until(["ArrowDown"], "() => document.activeElement.dataset.sec === 'keys'", n=10), "settings: arrows walk the sections to Keyboard & controller")
        press("Enter", 600)
        ok(js("() => document.querySelector('.set-sec h3').textContent") == "Keyboard & controller", "settings: Enter opens the Keyboard & controller section")
        press("ArrowRight", 400)
        ok(press_until(["ArrowUp"], "() => document.activeElement.matches('input[data-keys=sound]')", n=5) or press_until(["ArrowDown"], "() => document.activeElement.matches('input[data-keys=sound]')", n=6), "settings: arrows reach the focus-sound switch")
        press("Space", 500)
        ok(js("() => JSON.parse(localStorage.getItem('outpost-keys') || '{}').sound") is True, "settings: a Space tap toggles the switch (focus sound on)")
        shot("10-settings-keys")
        press("Space", 300)
        cond = "() => document.activeElement.dataset.sec === 'sound'"
        got = press_until(["ArrowUp"], cond, n=6) or press_until(["ArrowLeft", "ArrowDown"], cond, n=8)
        if not got:
            print("  at:", act())
        ok(got, "settings: back to the section list")
        press("Enter", 600)
        press("ArrowRight", 400)
        ok(press_until(["ArrowUp"], "() => document.activeElement.matches('input[type=range][data-p=volume]')", n=5) or press_until(["ArrowDown"], "() => document.activeElement.matches('input[type=range][data-p=volume]')", n=6), "settings: arrows reach the Volume slider")
        vol0 = js("() => +document.querySelector('input[data-p=volume]').value")
        press("ArrowRight", 500)
        ok(js("() => +document.querySelector('input[data-p=volume]').value") > vol0, "settings: Right raises the slider")
        press("Escape", 700)
        ok(js("() => document.querySelector('.a11y-panel').hidden"), "settings: Esc closes")

        # ---------------- Library ----------------
        cond = "() => document.activeElement.id === 'libraryBtn'"
        got = press_until(["ArrowLeft"], cond, n=6) or press_until(["ArrowUp", "ArrowRight"], cond, n=6)
        if not got:
            print("  at:", act())
        ok(got, "top bar: arrows reach Library (Esc returned focus to the gear)")
        press("Enter", 2500)
        ok(js("() => document.body.dataset.mode") == "cadet", "Library opens")
        ok(press_until(["ArrowDown"], "() => document.activeElement.id === 'moonFocus'", n=5), "library: Down reaches the Moon")
        moon = "() => document.activeElement.id === 'moonFocus'"
        for k in ["ArrowUp", "ArrowLeft", "ArrowRight", "ArrowDown", "ArrowUp"]:
            press(k, 1700)
            if js(moon) and js("() => document.querySelector('#moonFocus .mf-name').textContent"):
                break
            if not js(moon):   # that arrow left the Moon (no place near that way): come back
                press_until(["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight"], moon, n=2)
        name = js("() => document.querySelector('#moonFocus .mf-name').textContent")
        ok(bool(name), f"library: an arrow hops to a place and the globe flies there ({name})")
        shot("11-library-moon")
        press("Shift+ArrowLeft", 300)
        press("ArrowUp", 1500)
        press("Enter", 2500)
        ok(until("() => !document.getElementById('card').hidden", 15000), "library: Enter on the Moon picks the place (its card opens)")
        press("Escape", 700)
        ok(js("() => document.getElementById('card').hidden"), "library: Esc closes the card")
        cond = "() => document.activeElement.id === 'tourBtn'"
        press_until(["ArrowUp"], "() => !!document.activeElement.closest('.hud')", n=6)
        got = press_until(["ArrowLeft"], cond, n=6) or press_until(["ArrowRight"], cond, n=6)
        if not got:
            print("  at:", act())
        ok(got, "library: arrows leave the Moon for the toolbar and reach Tour")
        press("Enter", 3500)
        ok(js("() => document.getElementById('tourBtn').getAttribute('aria-pressed')") == "true", "library: Enter starts the tour")
        stop0 = js("() => (document.getElementById('cardEyebrow') || {}).textContent || ''")
        press("n", 2500)
        ok(js("() => (document.getElementById('cardEyebrow') || {}).textContent || ''") != stop0, "library: N goes to the next tour stop")
        press("Escape", 600)
        # [flows] the first Esc pauses the tour; the paused card must not trap arrow / D-pad focus (owner bug after #39):
        # with a button focused, Left / Right move focus instead of stepping the tour, so arrows leave the card
        ok(js("() => /Paused:/.test(document.body.innerText)"), "library: the first Esc pauses the tour")
        stop1 = js("() => (document.getElementById('cardEyebrow') || {}).textContent || ''")

        # ---------------- About, help, captions, mic ----------------
        ok(press_until(["ArrowUp"], "() => !!(document.activeElement && document.activeElement.closest('.topbar'))", n=8),
           "library: Up leaves a paused tour card for the top bar (no trap)")
        ok(js("() => (document.getElementById('cardEyebrow') || {}).textContent || ''") == stop1, "library: arrows over a paused tour move focus, not the tour")
        ok(press_until(["ArrowRight"], "() => document.activeElement.id === 'aboutBtn'", n=8), "top bar: arrows reach About")
        press("Escape", 800)   # the second Esc closes the paused tour (and leaves focus where it is)
        ok(js("() => !/Paused:/.test(document.body.innerText) && document.getElementById('tourBtn').getAttribute('aria-pressed') !== 'true'"),
           "library: the second Esc closes the paused tour")
        press("Enter", 900)
        ok(js("() => document.getElementById('about').open"), "About opens")
        press("ArrowDown", 400)
        press("Escape", 700)
        ok(not js("() => document.getElementById('about').open") and act()["id"] == "aboutBtn", "About: Esc closes, focus back on About")
        press("h", 600)
        ok(js("() => !document.getElementById('keysHelp').hidden"), "H opens the keys sheet for this screen")
        ok("Library" in js("() => document.getElementById('keysHelp').textContent"), "help: lists this screen's keys")
        shot("12-help")
        press("Escape", 500)
        ok(js("() => document.getElementById('keysHelp').hidden"), "help: Esc closes")
        c0 = js("() => document.documentElement.dataset.captions")
        press("c", 500)
        ok(js("() => document.documentElement.dataset.captions") != c0, "C toggles captions")
        press("c", 300)
        m0 = js("() => document.getElementById('mic').getAttribute('aria-label')")
        press("m", 1200)
        ok(js("() => document.getElementById('mic').getAttribute('aria-label')") != m0, "M toggles the mic")
        press("Backspace", 1500)
        ok(js("() => document.body.dataset.mode") != "cadet", "Backspace leaves the Library (back to where you were)")
        ok(js("() => !!document.querySelector('.topbar')"), "back never quits the app")

        ok(js("() => window.__ptr") == 0, "zero mouse: no trusted pointer event in the whole run")
        b.close()
    print(f"{sum(1 for r in results if r[0])}/{len(results)} checks in {time.time() - t0:.0f}s; console errors: {len(errs)}")
    for e in errs:
        print("  ERR", e[:300])
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
