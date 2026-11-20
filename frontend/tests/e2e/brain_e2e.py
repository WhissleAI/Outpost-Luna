"""My Brain (docs/BRAIN.md): the cadet's drawer and the grown-ups' Progress, in the real app.

Checks: the top bar's My Brain button and the Flight School call-sign chip open the drawer; it shows the star map,
Try next, the names the app learned and "How the outpost thinks"; "Change call sign" lands on the call-sign card;
a graded lesson step lands in the practice counts (ids and counts only); Esc closes and focus returns; the grown-ups'
Progress shows the Practice table with NGSS hooks and this computer's counts, never words. Screenshots (--out) of
both audiences at 1440x900 and 1280x720.

    (backend on --base's proxy; seed learned names / a turn log first for the full picture)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/brain_e2e.py --base http://localhost:5480 [--out DIR]
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

results: list[bool] = []
BRAIN = {"v": 1, "lessons": {"moon": {"steps": 5, "first": 4, "helped": 1, "shown": 0, "misses": 1, "pause": 0, "secs": 260},
                             "phases": {"steps": 4, "first": 1, "helped": 2, "shown": 1, "misses": 5, "pause": 2, "secs": 540},
                             "power": {"steps": 2, "first": 1, "helped": 1, "shown": 0, "misses": 1, "pause": 0, "secs": 150}},
         "days": []}
SEED = """(() => { try { if (sessionStorage.getItem('brain-e2e')) return; sessionStorage.setItem('brain-e2e', '1'); localStorage.clear();
  localStorage.setItem('outpost-callsign', 'Nova');
  localStorage.setItem('atm-academy', JSON.stringify({ badges: ['scout', 'watcher'], qualified: false, steps: { power: { i: 1, n: 3 } }, current: 'power' }));
  const d = new Date(), day = n => { const t = new Date(d); t.setDate(t.getDate() - n); return t.getFullYear() + '-' + String(t.getMonth() + 1).padStart(2, '0') + '-' + String(t.getDate()).padStart(2, '0'); };
  const b = %s; b.days = [day(2), day(1), day(0)]; localStorage.setItem('outpost-brain', JSON.stringify(b));
} catch (e) {} })();""" % json.dumps(BRAIN)


def check(ok, msg):
    results.append(bool(ok)); print(("  ok  " if ok else "  FAIL ") + msg)


def until(pg, js, ms=8000):
    for _ in range(ms // 100):
        try:
            if pg.evaluate(js):
                return True
        except Exception:
            pass
        pg.wait_for_timeout(100)
    return False


def hold(pg, sel, ms):
    box = pg.evaluate("s => { const q = document.querySelector(s).getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }", sel)
    pg.mouse.move(*box); pg.mouse.down(); pg.wait_for_timeout(ms); pg.mouse.up()


def open_progress(pg):
    pg.evaluate("() => document.getElementById('a11yBtn').click()")
    until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-sec=grownups]')", 5000)
    pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=grownups]').click()")
    until(pg, "() => !!document.querySelector('[data-gu-open], .gu-part')", 3000)
    if pg.evaluate("() => !!document.querySelector('[data-gu-open]')"):
        hold(pg, "[data-gu-open]", 3400)
    return until(pg, "() => !!document.querySelector('.pg-practice')", 8000)


def shot(pg, out, name):
    if out:
        for _ in range(2):   # a loaded machine: WebGL frames can stall one capture
            try:
                pg.screenshot(path=str(Path(out) / f"{name}.png"), timeout=60000)
                return
            except Exception as e:  # noqa: BLE001
                print("  (screenshot retry:", str(e)[:80], ")")


DRAWER_TEXT = "() => (document.getElementById('brain') || {}).innerText || ''"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5480")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    errs: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=[*LAUNCH_ARGS, "--enable-unsafe-swiftshader"])
        for w, h in ((1440, 900), (1280, 720)):
            print(f"-- {w}x{h}")
            ctx = b.new_context(viewport={"width": w, "height": h})
            ctx.add_init_script(SEED)
            silence(ctx)
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: m.type == "error" and "favicon" not in m.text and "WebSocket" not in m.text and errs.append(m.text))
            pg.goto(a.base + "/", wait_until="domcontentloaded")
            check(until(pg, "() => !!document.getElementById('brainBtn') && !!window.__outpost && !!window.__outpost.brain", 20000), "the top bar has My Brain")
            pg.wait_for_timeout(1500)
            pg.click("#brainBtn")
            check(until(pg, "() => document.getElementById('brain').open"), "My Brain opens from the top bar")
            check(until(pg, "() => !!document.querySelector('#brain .bm-map')", 8000), "the star map is drawn")
            txt = pg.evaluate(DRAWER_TEXT)
            for s in ("Nova", "Your star map", "Try next", "How the outpost knows your voice", "How the outpost thinks", "It keeps your words private", "Days in a row"):
                check(s.lower() in txt.lower(), f"cadet sees: {s}")
            check(pg.evaluate("() => document.querySelectorAll('#brain .bm-star.is-lit').length") == 2, "two stars lit (two patches)")
            check(pg.evaluate("() => document.querySelectorAll('#brain .bm-star.is-practising').length") >= 1, "a lesson in progress glows")
            if until(pg, "() => /The outpost knows you mean/.test(document.getElementById('brain').innerText)", 4000):
                check(True, "a learned name in kid words")
            else:
                print("  (no learned names on this backend: seed LEARN_DIR to see them)")
            # novice check: no engineering words on the cadet's page
            check(not any(x in txt.lower() for x in ("alias", "threshold", "device_directed", "profile", "token", "turn log", "redact")),
                  "novice: no engineering words on the cadet's page")
            check(pg.evaluate("() => { const d = document.querySelector('#brain'); return d.scrollWidth <= d.clientWidth + 1; }"), "no sideways scroll in the drawer")
            shot(pg, a.out, f"brain_cadet_{w}x{h}")
            pg.evaluate("() => { const b = document.querySelector('#brain .about-body'); b.scrollTop = b.scrollHeight; }")
            pg.wait_for_timeout(300)
            shot(pg, a.out, f"brain_cadet_bottom_{w}x{h}")
            pg.keyboard.press("Escape")
            # focus goes back to My Brain, or (in a lesson step, whose scope holds focus: input/spatial.js) to the lesson
            okc = until(pg, "() => { const a = document.activeElement; return !document.getElementById('brain').open && !!a && (a.id === 'brainBtn' || (document.body.dataset.aview === 'lesson' && !!a.closest('#aPanel'))); }", 3000)
            if not okc:
                print("   at:", pg.evaluate("() => [document.getElementById('brain').open, document.activeElement && (document.activeElement.id || document.activeElement.className)]"))
            check(okc, "Esc closes; focus back on My Brain (or the lesson underneath)")
            if w == 1440:
                # the practice counts take a graded step (ids and counts only)
                pg.evaluate("""() => dispatchEvent(new CustomEvent('outpost:lesson-result', { detail: { status: 'passed', step_type: 'choice', lesson: 'radiation',
                    shown: false, misses: 0, helped: false, step_s: 14, text: 'my name is Alex', callsign: 'Nova' } }))""")
                saved = pg.evaluate("() => localStorage.getItem('outpost-brain') || ''")
                check('"radiation":{"steps":1,"first":1' in saved, "a graded step lands in the practice counts")
                check("Alex" not in saved and "Nova" not in saved and "my name" not in saved, "no words or call sign in the practice counts")
                # the Flight School call-sign chip opens My Brain; Change call sign goes to the call-sign card
                pg.click("#modeAcademy")
                if until(pg, "() => !!document.getElementById('aCsEdit')", 15000):
                    pg.evaluate("() => document.getElementById('aCsEdit').click()")
                    check(until(pg, "() => document.getElementById('brain').open"), "the map's call-sign chip opens My Brain")
                    pg.click("#brain [data-bm-cs]")
                    check(until(pg, "() => !document.getElementById('brain').open && !!document.getElementById('aCsIn')", 6000), "Change call sign opens the call-sign card")
                    pg.click("#aCsGo")
                    until(pg, "() => !!document.getElementById('aCsEdit')", 6000)
                else:
                    check(False, "the Flight School map shows the call-sign chip")
            # grown-ups: Progress grows into the Brain view
            check(open_progress(pg), "Settings → For grown-ups → Progress shows Practice")
            until(pg, "() => !!document.querySelector('.pg-computer')", 6000)
            g = pg.evaluate("() => document.querySelector('.pg-sheet').innerText")
            for s in ("Practice", "first try", "NGSS", "Needed the most help", "Talking with the app", "Safety", "kept private", "Your controls"):
                check(s.lower() in g.lower(), f"grown-up sees: {s}")
            check(not any(x in g for x in ("ticko", "shackle ton", "<private>", "redacted")), "grown-up view: counts only, no words")
            pg.evaluate("() => document.querySelector('.pg-practice').scrollIntoView({ block: 'start' })")
            pg.wait_for_timeout(400)
            shot(pg, a.out, f"brain_grownup_{w}x{h}")
            pg.evaluate("() => document.querySelector('.pg-computer').scrollIntoView({ block: 'start' })")
            pg.wait_for_timeout(300)
            shot(pg, a.out, f"brain_grownup_computer_{w}x{h}")
            ctx.close()
        b.close()
    errs = [e for e in errs if "Failed to load resource" not in e]
    print(f"{sum(results)}/{len(results)} checks; page errors: {len(errs)}")
    for e in errs[:10]:
        print("  ERR", e[:300])
    sys.exit(0 if all(results) and not errs else 1)


if __name__ == "__main__":
    main()
