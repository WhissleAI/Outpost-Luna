"""Teacher PIN and the class summary in the real app (D7, docs/BRAIN.md §12). Silent.

Checks:
  - For grown-ups → Teacher PIN sets a PIN (4-8 digits, typed twice); it is stored hashed, never as digits;
  - with a PIN, the 3-second hold leads to the PIN step: a wrong PIN stays locked, the right one opens For grown-ups;
  - Class summary lists every cadet on this computer in call-sign order (not by any count), with counts only and the
    "not a ranking, not for grading" line, and a Print button;
  - removing the PIN brings back the hold alone.

    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/teacher_summary_e2e.py --base http://localhost:5480
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[bool] = []
SEED = """(() => { try { if (sessionStorage.getItem('ts-e2e')) return; sessionStorage.setItem('ts-e2e', '1'); localStorage.clear();
  localStorage.setItem('outpost-callsign', 'Zephyr');
  localStorage.setItem('atm-academy', JSON.stringify({ badges: ['scout', 'watcher'], qualified: false, steps: {}, current: null }));
  localStorage.setItem('outpost-brain', JSON.stringify({ v: 1, lessons: { moon: { steps: 4, first: 3, helped: 1, shown: 0, misses: 1, pause: 0, secs: 200 } }, days: ['2026-11-19'] }));
  localStorage.setItem('outpost-profiles', JSON.stringify({ active: 'p1', list: [{ id: 'p1', data: null },
    { id: 'p2', data: { 'outpost-callsign': 'Astra', 'atm-academy': JSON.stringify({ badges: [], qualified: false }) } },
    { id: 'p3', data: { 'outpost-callsign': 'Nova', 'atm-academy': JSON.stringify({ badges: ['scout'], qualified: false }) } }] }));
} catch (e) {} })();"""
PIN = "4821"


def no_hmr_socket(ctx):
    """server.ws:false still injects Vite's HMR client; its socket never opens and Chrome queues the app's own behind it."""
    ctx.route_web_socket(re.compile(r"^wss?://[^/]+/(\?.*)?$"), lambda ws: None)


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


def open_grownups(pg):
    if not pg.evaluate("() => !!document.querySelector('.a11y-panel:not([hidden])')"):
        pg.evaluate("() => document.getElementById('a11yBtn').click()")
    until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-sec=grownups]')", 5000)
    pg.evaluate("() => document.querySelector('.a11y-panel [data-sec=grownups]').click()")
    until(pg, "() => !!document.querySelector('[data-gu-open]')", 3000)
    hold(pg, "[data-gu-open]", 3400)


def close_settings(pg):
    pg.evaluate("() => { const x = document.querySelector('.a11y-panel [data-close]'); if (x) x.click(); }")
    pg.wait_for_timeout(300)


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
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(SEED)
        silence(ctx)
        no_hmr_socket(ctx)
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "favicon" not in m.text and "WebSocket" not in m.text and errs.append(m.text))
        pg.goto(a.base + "/", wait_until="domcontentloaded")
        check(until(pg, "() => !!window.__outpost && !!window.__outpost.prefsApi", 30000), "the app loads")
        pg.wait_for_timeout(1500)

        print("-- set a teacher PIN (no PIN yet: the hold alone opens)")
        open_grownups(pg)
        check(until(pg, "() => !!document.querySelector('.gu-part[data-gu=teacherpin] [data-tp-form]')", 6000), "For grown-ups opens and has Teacher PIN")
        pg.fill(".gu-part[data-gu=teacherpin] [data-tp-pin]", "12")
        pg.fill(".gu-part[data-gu=teacherpin] [data-tp-pin2]", "12")
        pg.click(".gu-part[data-gu=teacherpin] [data-tp-form] button[type=submit]")
        check(until(pg, "() => /Use 4 to 8 digits/.test(document.querySelector('[data-gu=teacherpin] [data-tp-msg]').textContent)", 3000), "a too-short PIN is refused")
        pg.fill(".gu-part[data-gu=teacherpin] [data-tp-pin]", PIN)
        pg.fill(".gu-part[data-gu=teacherpin] [data-tp-pin2]", PIN)
        pg.click(".gu-part[data-gu=teacherpin] [data-tp-form] button[type=submit]")
        check(until(pg, "() => /PIN set/.test(document.querySelector('[data-gu=teacherpin] [data-tp-msg]').textContent)", 3000), "PIN set")
        stored = pg.evaluate("() => localStorage.getItem('outpost-teacher-pin') || ''")
        check(stored and PIN not in stored and '"hash"' in stored, "stored as a salted hash, never the digits")
        close_settings(pg)

        print("-- the hold now asks for the PIN")
        open_grownups(pg)
        check(until(pg, "() => !!document.querySelector('[data-gu-pin]') && !document.querySelector('.gu-part')", 4000), "after the hold: the PIN step, nothing open yet")
        if a.out:
            pg.screenshot(path=str(Path(a.out) / "teacher_pin_1280x800.png"))
        pg.fill("[data-gu-pin]", "0000")
        pg.press("[data-gu-pin]", "Enter")
        check(until(pg, "() => /isn't right/.test((document.getElementById('guPinMsg') || {}).textContent || '')", 4000), "a wrong PIN stays locked")
        check(pg.evaluate("() => !document.querySelector('.gu-part')"), "nothing for grown-ups shows")
        pg.fill("[data-gu-pin]", PIN)
        pg.press("[data-gu-pin]", "Enter")
        check(until(pg, "() => !!document.querySelector('.gu-part[data-gu=classsummary]')", 6000), "the right PIN opens For grown-ups")

        print("-- the class summary")
        check(until(pg, "() => document.querySelectorAll('.cs-table tbody tr').length === 3", 10000), "one row per cadet on this computer")
        names = pg.evaluate("() => [...document.querySelectorAll('.cs-table tbody th')].map(t => t.textContent)")
        check(names == ["Astra", "Nova", "Zephyr"], f"call-sign order, not a ranking: {names}")
        txt = pg.evaluate("() => document.querySelector('.gu-part[data-gu=classsummary]').innerText")
        check("Not a ranking, and not for grading." in txt and "Counts only, never words." in txt, "says what it is and isn't")
        zr = pg.evaluate("() => [...document.querySelector('.cs-table tr[data-cs=p1]').children].map(c => c.textContent)")
        check(zr[0] == "Zephyr" and zr[1].startswith("2 of") and zr[2] == "4" and zr[3] == "75%", f"Zephyr's counts: {zr}")
        check(pg.evaluate("() => !!document.querySelector('[data-gu=classsummary] [data-cs-print]')"), "a Print button")
        check(pg.evaluate("() => { const g = document.querySelector('.gu-part[data-gu=progress]'), c = document.querySelector('.gu-part[data-gu=classsummary]'); return !!g && !!c && (g.compareDocumentPosition(c) & Node.DOCUMENT_POSITION_FOLLOWING) > 0; }"),
              "it sits right after Progress")
        if a.out:
            pg.evaluate("() => document.querySelector('.gu-part[data-gu=classsummary]').scrollIntoView({ block: 'start' })")
            pg.screenshot(path=str(Path(a.out) / "class_summary_1280x800.png"))

        print("-- remove the PIN: the hold alone again")
        pg.click(".gu-part[data-gu=teacherpin] [data-tp-remove]")
        check(until(pg, "() => !localStorage.getItem('outpost-teacher-pin')", 3000), "PIN removed")
        close_settings(pg)
        open_grownups(pg)
        check(until(pg, "() => !!document.querySelector('.gu-part') && !document.querySelector('[data-gu-pin]')", 6000), "the hold opens For grown-ups again")
        ctx.close()
        b.close()
    errs = [e for e in errs if "Failed to load resource" not in e]
    print(f"{sum(results)}/{len(results)} checks; page errors: {len(errs)}")
    for e in errs[:10]:
        print("  ERR", e[:300])
    sys.exit(0 if all(results) and not errs else 1)


if __name__ == "__main__":
    main()
