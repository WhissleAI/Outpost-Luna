"""Gestures blended into answering, and the L1 far-side step by every input (docs/GESTURES.md §Answers).

Synthetic landmarks (tests/e2e/frames.mjs over tests/fixtures/gestures/synth.mjs) go through the real classifier,
bind.js and the intent bus (window.__outpost.gestures.inject); the camera stays off (fake device only, never used here).
Checks, on L1 "Know your Moon":
  step 2 "Standing there, could you see Earth in the sky?" (Yes / No / Sometimes):
    thumbs up answers "yes", thumbs down answers "no", three fingers answers "sometimes", each like a tap (the
    attempt the server grades carries that choice) and the picked button wears the ring first;
  step 4 "Turn the Moon to show the far side": click, Enter, the number key 2, voice "far side", a gesture
    point-and-hold on Far side, and a fist spin to the far side each turn the Moon to the far side and pass;
  the mission's "Steer left / Steer right" card: a thumbs up picks nothing and shows "Point at an answer, or hold up
  fingers".

    cd frontend && npm run build   (backend on :8201 serving frontend/dist)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/answers_e2e.py --base http://127.0.0.1:8201
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless)
import mission_ui as mu  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

HERE = Path(__file__).resolve().parent
FRONT = HERE.parents[1]
FIX = FRONT / "tests" / "fixtures" / "gestures"
results: list[tuple[bool, str]] = []

SEED = """try { if (!sessionStorage.getItem('ans')) { localStorage.clear(); sessionStorage.setItem('ans', '1');
  localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('outpost-tour-done:Nova', '1');
  localStorage.setItem('outpost-prep-seen', JSON.stringify(['moon'])); } } catch (e) {}
  window.__outpostTest = true;
  (() => { const F = window.fetch; window.__attempts = [];
    window.fetch = function (u, o) { try { if (String(u).includes('/api/academy/attempt')) window.__attempts.push(JSON.parse(o.body)); } catch (e) {} return F.apply(this, arguments); }; })();"""


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)


def frames(*args):
    return json.loads(subprocess.check_output(["node", str(HERE / "frames.mjs"), *map(str, args)], cwd=FRONT))


def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text())["frames"]


class T:
    def __init__(self, pg):
        self.pg, self.cursor = pg, 0

    def js(self, *a):
        return self.pg.evaluate(*a)

    def until(self, expr, timeout=8000, arg=None):
        end = time.time() + timeout / 1000
        while time.time() < end:
            try:
                if (self.pg.evaluate(expr, arg) if arg is not None else self.pg.evaluate(expr)):
                    return True
            except Exception:
                pass
            self.pg.wait_for_timeout(150)
        return False

    def inject(self, fs, gap=1500):
        """Inject frames right after the previous ones (time only goes forwards), in real time-ish chunks."""
        base = (self.cursor or 1_000_000) + gap
        shift = base - fs[0]["t"]
        self.cursor = fs[-1]["t"] + shift
        return self.js("([fs, dt]) => window.__outpost.gestures.inject(fs.map(f => ({...f, t: f.t + dt}))).map(e => e.type + (e.n ? e.n : ''))", [fs, shift])

    def lesson_step(self, n):
        self.js("() => window.__outpost.shellNav('lesson', 'moon', 'lesson moon')")
        if not self.until("() => window.__outpost.academyTest && window.__outpost.academyTest.where.view === 'lesson'", 10000):
            return False
        self.pg.wait_for_timeout(600)
        self.js("n => window.__outpost.academyTest.step(n)", n)
        self.js("() => { window.__attempts.length = 0; }")
        return self.until("() => document.querySelectorAll('#aPanel .a-choice').length > 0", 6000)

    def last_attempt(self, timeout=6000):
        self.until("() => window.__attempts.length > 0", timeout)
        a = self.js("() => window.__attempts.slice(-1)[0] || null")
        return a


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8201")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--enable-unsafe-swiftshader"])

        def fresh():
            ctx = b.new_context(viewport={"width": 1280, "height": 800})
            ctx.add_init_script(SEED)
            silence(ctx)
            pg = ctx.new_page()
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(base + "/")
            t = T(pg)
            t.until("() => window.__outpost && window.__outpost.gestures && window.__outpost.shellNav", 30000)
            pg.wait_for_timeout(1200)
            return ctx, pg, t, errs

        # ---------------- L1 step 2: thumbs up / down, three fingers ----------------
        for name, fs, want in (("thumbs up", fixture("thumbs_up"), "yes"), ("thumbs down", fixture("thumbs_down"), "no"),
                               ("three fingers", frames("hold", "three", 1300), "sometimes")):
            ctx, pg, t, errs = fresh()
            ok(t.lesson_step(1) and "see Earth" in t.js("() => document.getElementById('aPanel').innerText"), f"L1 step 2 is up for {name}")
            labels = t.js("() => [...document.querySelectorAll('#aPanel .a-choice')].map(b => b.innerText.trim())")
            ring = []
            pg.expose_function("__ringSeen", lambda c: ring.append(c))
            t.js("() => new MutationObserver(ms => ms.forEach(m => { if (m.target.classList && m.target.classList.contains('is-gesture-pick')) window.__ringSeen(m.target.dataset.c || ''); })).observe(document.getElementById('aPanel'), {subtree: true, attributes: true, attributeFilter: ['class']})")
            evs = t.inject(fs)
            at = t.last_attempt()
            got = ((at or {}).get("input") or {}).get("choice")
            ok(got == want, f"{name} on Yes / No / Sometimes answers {want!r} like a tap (events {evs}, options {labels}, attempt {got!r})")
            ok(want in ring, f"{name}: the picked button wore the ring before it was pressed ({ring})")
            ok(not errs, f"{name}: no page errors {errs[:2]}")
            ctx.close()

        # ---------------- L1 step 4: the far side, by every input ----------------
        side_far = "() => { const c = window.__outpost.globe && window.__outpost.globe.centerLatLon ? window.__outpost.globe.centerLatLon() : null; return c ? Math.abs((((c.lon + 180) % 360) + 360) % 360 - 180) : -1; }"

        def far_step(how, act):
            ctx, pg, t, errs = fresh()
            up = t.lesson_step(3) and t.until("() => !!document.querySelector('#aPanel .g-side[data-c=far]')", 5000)
            ok(up, f"far side ({how}): L1 step 4 is up")
            if not up:
                ctx.close()
                return
            pg.wait_for_timeout(1600)   # the step's own globe directive settles
            act(pg, t)
            at = t.last_attempt(9000)
            inp = (at or {}).get("input") or {}
            lon = t.js(side_far)
            passed = t.until("() => !!document.querySelector('#aPanel .a-choice.is-correct, #aPanel .is-correct, #aNext') || /far side/i.test((document.querySelector('#aPanel .a-feedback') || {}).textContent || '')", 6000)
            ok(inp.get("choice") == "far" or (inp.get("view") and abs(((inp["view"]["lon"] + 180) % 360) - 180) > 110),
               f"far side ({how}): graded as far ({inp})")
            ok(lon > 110, f"far side ({how}): the Moon shows the far side when it is graded (|lon| {lon:.0f})")
            ok(passed, f"far side ({how}): the step passes")
            ok(not errs, f"far side ({how}): no page errors {errs[:2]}")
            ctx.close()

        far_step("click", lambda pg, t: pg.click("#aPanel .g-side[data-c=far]", no_wait_after=True))
        far_step("Enter", lambda pg, t: (pg.focus("#aPanel .g-side[data-c=far]"), pg.keyboard.press("Enter")))
        far_step("number key 2", lambda pg, t: (t.js("() => document.activeElement && document.activeElement.blur()"), pg.keyboard.press("2")))
        far_step("voice 'far side'", lambda pg, t: t.js("() => window.__outpost.academyTest && window.__outpost.hear('far side')"))

        def point_hold(pg, t):
            r = t.js("() => { const q = document.querySelector('#aPanel .g-side[data-c=far]').getBoundingClientRect(); return [(q.x + q.width / 2) / innerWidth, (q.y + q.height / 2) / innerHeight]; }")
            t.inject(frames("point", r[0], r[1], 1600))
        far_step("gesture point and hold", point_hold)

        def fist_spin(pg, t):
            # the fist's own intents (gesture/bind.js: spin start / move / end, source gesture): lean right and hold
            t.js("() => window.__outpost.intents.emitIntent('spin', {phase: 'start', x: 0, y: 0, z: 0}, 'gesture')")
            end = time.time() + 6
            while time.time() < end and t.js(side_far) < 150:
                t.js("() => window.__outpost.intents.emitIntent('spin', {phase: 'move', x: 1, y: 0, z: 0}, 'gesture')")
                pg.wait_for_timeout(100)
            t.js("() => window.__outpost.intents.emitIntent('spin', {phase: 'end', x: 0, y: 0, z: 0, how: 'open'}, 'gesture')")
        far_step("fist spin", fist_spin)

        # ---------------- no yes / no option: "Steer left / Steer right" ----------------
        ctx = b.new_context(viewport={"width": 1440, "height": 879})
        ctx.add_init_script(mu.SEED)
        ctx.add_init_script("window.__outpostTest = true;")
        silence(ctx)
        pg = ctx.new_page()
        pg.goto(base + "/")
        t = T(pg)
        t.until("() => window.__outpost && window.__outpost.gestures", 30000)
        steer = mu.to_steer(pg)
        ok(steer, "the mission reaches 'Steer left or right?'")
        if steer:
            before = t.js("() => (window.__outpost.missionUI.card || {}).key || ''")
            t.inject(fixture("thumbs_up"))
            shown = t.until("() => { const h = document.getElementById('gxHint'); return !!(h && !h.hidden && /Point at an answer, or hold up fingers/.test(h.textContent)); }", 3000)
            ok(shown, "thumbs up on Steer left / Steer right shows 'Point at an answer, or hold up fingers'")
            pg.wait_for_timeout(800)
            ok(t.js("() => (window.__outpost.missionUI.card || {}).key || ''") == before, "… and picks nothing")
            # two fingers do pick: option 2 (Steer right)
            t.inject(frames("hold", "two", 1300))
            ok(t.until(f"() => ((window.__outpost.missionUI.card || {{}}).key || '') !== {json.dumps(before)}", 5000), "two fingers pick option 2 on the choice card")
        ctx.close()
        b.close()
    bad = [w for c, w in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
