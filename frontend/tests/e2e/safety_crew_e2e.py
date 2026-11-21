"""Safety counts, care-flag ack and crew rotation in the real app (D1-D4, docs/BRAIN.md §7, §9). Silent.

Checks, on a fresh backend (its own BRAIN_DIR):
  - a typed rude word lands in the playing cadet's counts as profanity / typed, and never as words;
  - a care phrase raises a care flag that survives (persisted), the grown-ups' gate shows "1 safety note", Progress
    lists it by kind and day with "Mark as seen", and the ack clears it;
  - crew rotation (Settings → Cadets): the crew bar names both cadets, listening becomes hold-to-talk, a tap passes
    the turn ("Nova: hold Space to talk"), and the next typed rude word counts for Nova, not Comet;
  - Progress shows each cadet's own safety block with the open-mic caveat; the cadet's My Brain shows no counts.

    (backend + vite on their own ports, e.g. frontend/tests/e2e: BACKEND_URL=... npx vite --port 5480)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/safety_crew_e2e.py --base http://localhost:5480
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[bool] = []
SEED = """(() => { try { if (sessionStorage.getItem('sc-e2e')) return; sessionStorage.setItem('sc-e2e', '1'); localStorage.clear();
  localStorage.setItem('outpost-callsign', 'Comet');
  localStorage.setItem('atm-academy', JSON.stringify({ badges: ['scout'], qualified: false, steps: {}, current: null }));
  localStorage.setItem('outpost-profiles', JSON.stringify({ active: 'p1', list: [{ id: 'p1', data: null },
    { id: 'p2', data: { 'outpost-callsign': 'Nova', 'atm-academy': JSON.stringify({ badges: [], qualified: false }) } }] }));
} catch (e) {} })();"""


def no_hmr_socket(ctx):
    """A dev server run with server.ws:false (long browser tests) still injects Vite's HMR client, whose socket to "/"
    never opens; Chrome then queues the app's /ws/session behind it and the session times out. Answer the HMR socket
    here (mocked, silent) so the session socket connects."""
    ctx.route_web_socket(re.compile(r"^wss?://[^/]+/(\?.*)?$"), lambda ws: None)


def check(ok, msg):
    results.append(bool(ok)); print(("  ok  " if ok else "  FAIL ") + msg)


def until(pg, js, ms=8000, arg=None):
    for _ in range(ms // 100):
        try:
            if pg.evaluate(js) if arg is None else pg.evaluate(js, arg):
                return True
        except Exception:
            pass
        pg.wait_for_timeout(100)
    return False


def hold(pg, sel, ms):
    box = pg.evaluate("s => { const q = document.querySelector(s).getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }", sel)
    pg.mouse.move(*box); pg.mouse.down(); pg.wait_for_timeout(ms); pg.mouse.up()


def typed(pg, text):
    pg.evaluate("t => { const q = document.getElementById('q'); q.value = t; document.getElementById('askForm').requestSubmit(); }", text)


def summary(pg, pid):
    return pg.evaluate("p => fetch('/api/brain/summary?profile=' + p).then(r => r.json())", pid)


def flags(pg):
    return pg.evaluate("() => fetch('/api/safety/flags').then(r => r.json()).then(b => b.flags)")


def rude(pg, pid):
    s = summary(pg, pid)
    bk = (s.get("safety") or {}).get("by_kind") or {}
    return bk.get("profanity") or {}


def open_settings(pg, sec):
    if not pg.evaluate("() => !!document.querySelector('.a11y-panel:not([hidden])')"):
        pg.evaluate("() => document.getElementById('a11yBtn').click()")
    until(pg, "() => !!document.querySelector('.a11y-panel:not([hidden]) [data-sec]')", 5000)
    pg.evaluate("s => document.querySelector(`.a11y-panel [data-sec=${s}]`).click()", sec)
    pg.wait_for_timeout(300)


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
        check(until(pg, "() => !!window.__outpost && !!window.__outpost.prefsApi && !!window.__outpost.crew", 30000), "the app loads with crew rotation wired")
        check(until(pg, "() => !!(window.__atmSession && window.__atmSession.connected)", 30000), "the session socket is up")
        pg.wait_for_timeout(1000)   # its prefs (the profile) reach the server

        print("-- safety counting (playing cadet, typed)")
        c0 = rude(pg, "p1").get("typed", 0)   # a reused backend may hold earlier runs' counts
        typed(pg, "this is crap")
        check(until(pg, "n => fetch('/api/brain/summary?profile=p1').then(r => r.json()).then(s => s.safety && s.safety.by_kind && s.safety.by_kind.profanity.typed === n)", 10000, c0 + 1),
              "a typed rude word counts for Comet as profanity / typed")
        s1 = summary(pg, "p1")
        check(s1.get("scope") == "cadet" and s1["talk"]["turns"] >= 1, "talk counts come from the counts store (scope cadet)")
        check("crap" not in json.dumps(s1).lower(), "no words in the summary")

        print("-- a care flag, persisted, acknowledged")
        pg.evaluate("() => fetch('/api/safety/flags/ack?profile=p1', { method: 'POST' })")   # a reused backend: start clean
        typed(pg, "i want to kill myself")
        check(until(pg, "() => fetch('/api/safety/flags').then(r => r.json()).then(b => b.flags.length === 1)", 10000), "a care flag is kept for a grown-up")
        f = flags(pg)
        check(f and f[0]["kind"] == "self_harm" and f[0]["profile"] == "p1" and set(f[0]) == {"id", "kind", "day", "profile", "n"},
              "kind, day and profile only")
        open_settings(pg, "grownups")
        check(until(pg, "() => { const n = document.querySelector('[data-gu-notes]'); return n && !n.hidden && /1 safety note/.test(n.textContent); }", 6000),
              "the grown-ups' gate shows 1 safety note (no details before the hold)")
        hold(pg, "[data-gu-open]", 3400)
        check(until(pg, "() => !!document.querySelector('.pg-care [data-care-ack]')", 10000), "Progress lists the note with Mark as seen")
        txt = pg.evaluate("() => document.querySelector('.pg-sheet').innerText")
        check("Words about getting hurt came up" in txt and "kill" not in txt.lower(), "by kind and day, never the words")
        check("heard near the app" in txt and "Rude words filtered" in txt, "profanity split, with the open-mic caveat")
        check("not an assessment" in txt.lower(), "the sheet says it is not for grading")
        if a.out:
            pg.evaluate("() => document.querySelector('.pg-care').scrollIntoView({ block: 'start' })")
            pg.screenshot(path=str(Path(a.out) / "safety_notes_1280x800.png"))
        pg.click(".pg-care [data-care-ack]")
        check(until(pg, "() => !document.querySelector('.pg-care')", 8000), "Mark as seen clears it from Progress")
        check(flags(pg) == [], "and from the backend")
        close_settings(pg)

        print("-- crew rotation")
        open_settings(pg, "cadets")
        check(pg.evaluate("() => !!document.querySelector('[data-crew-sw]:not([disabled])')"), "Settings → Cadets offers Crew rotation (two cadets)")
        pg.evaluate("() => document.querySelector('[data-crew-sw]').click()")
        close_settings(pg)
        check(until(pg, "() => { const b = document.getElementById('crewBar'); return b && !b.hidden && /Comet/.test(b.innerText) && /Nova/.test(b.innerText); }", 4000),
              "the crew bar names both cadets")
        check(pg.evaluate("() => window.__outpost.prefsApi.value.listen") == "ptt", "listening is hold-to-talk while the crew rotates")
        pg.click("#crewBar [data-crew-turn=p2]")
        check(until(pg, "() => document.querySelector('#crewBar [data-crew-turn=p2]').getAttribute('aria-pressed') === 'true'", 3000), "a tap passes the turn to Nova")
        check("Nova: hold Space to talk" in pg.evaluate("() => document.getElementById('crewBar').innerText"), "push-to-talk is Nova's now")
        if a.out:
            pg.screenshot(path=str(Path(a.out) / "crew_bar_1280x800.png"))
        pg.wait_for_timeout(800)   # the prefs (profile p2) reach the session
        n0 = rude(pg, "p2").get("typed", 0)
        typed(pg, "crap")
        check(until(pg, "n => fetch('/api/brain/summary?profile=p2').then(r => r.json()).then(s => s.safety && s.safety.by_kind && s.safety.by_kind.profanity.typed === n)", 10000, n0 + 1),
              "the next typed rude word counts for Nova")
        check(rude(pg, "p1").get("typed") == c0 + 1, "Comet's count is unchanged")
        pg.click("#crewBar [data-crew-turn=p1]")
        check(until(pg, "() => window.__outpost.crew.state.turn === 'p1'", 3000), "and back to Comet")

        print("-- the grown-ups' sheet and the kid's page")
        open_settings(pg, "grownups")
        if pg.evaluate("() => !!document.querySelector('[data-gu-open]')"):
            hold(pg, "[data-gu-open]", 3400)
        check(until(pg, "() => document.querySelectorAll('.pg-sheet .pg-safety').length === 2", 10000), "Progress: each cadet has her own safety block")
        close_settings(pg)
        pg.click("#brainBtn")
        until(pg, "() => document.getElementById('brain').open && !!document.querySelector('#brain .bm-think')", 8000)
        kid = pg.evaluate("() => document.getElementById('brain').innerText")
        check(not any(w in kid.lower() for w in ("filtered", "safety note", "heard in the room", "push-to-talk")), "My Brain: no counts, nothing punitive")
        check("Grown-ups see how many, never the word." in kid, "the cadet is told grown-ups can see how many")
        pg.keyboard.press("Escape")
        # crew off: listening comes back
        open_settings(pg, "cadets")
        pg.evaluate("() => document.querySelector('[data-crew-sw]').click()")
        close_settings(pg)
        check(pg.evaluate("() => window.__outpost.prefsApi.value.listen") == "handsfree" and pg.evaluate("() => document.getElementById('crewBar').hidden"),
              "crew rotation off: the bar goes, hands-free comes back")
        ctx.close()
        b.close()
    errs = [e for e in errs if "Failed to load resource" not in e]
    print(f"{sum(results)}/{len(results)} checks; page errors: {len(errs)}")
    for e in errs[:10]:
        print("  ERR", e[:300])
    sys.exit(0 if all(results) and not errs else 1)


if __name__ == "__main__":
    main()
