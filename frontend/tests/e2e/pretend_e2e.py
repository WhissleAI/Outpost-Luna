"""The "pretend tech" mark stays inside what it labels (owner: "what's that pretend tech box bulging out?").

At 1024x640, 1280x800 and 1920x1080:
  * the radiation lesson's order buttons ("Shields up" is pretend tech; the same buttons as the check ride's
    "Solar particle storm! … Your order?"): every mark sits inside its button, on the label's line (never on a line of
    its own), not over the number badge; every button in a row of the grid has the same height;
  * the mission cabin: the Shields control, the Radiation panel rows, an alert's actions: every mark inside its row or
    button;
  * the first pick of "Shields up" marks the explanation as given (once).

    (backend on :8203 serving frontend/dist)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/pretend_e2e.py --base http://127.0.0.1:8203
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
import mission_ui as mu  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

results: list[tuple[bool, str]] = []
SEED = """try { if (!sessionStorage.getItem('pt')) { localStorage.clear(); sessionStorage.setItem('pt', '1');
  localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('outpost-tour-done:Nova', '1');
  localStorage.setItem('outpost-prep-seen', JSON.stringify(['radiation'])); } } catch (e) {}
  window.__outpostTest = true;"""

# every pretend mark: inside the box it labels (its button / option / row), not over a number badge
CHECK = r"""() => {
  const vis = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && !e.closest('[hidden]'));
  const inside = (r, B) => r.left >= B.left - 1 && r.right <= B.right + 1 && r.top >= B.top - 1 && r.bottom <= B.bottom + 1;
  const hit = (a, b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
  const out = { marks: 0, bad: [], dashed: 0 };
  for (const m of document.querySelectorAll('.pt-mark')) {
    if (!vis(m)) continue; out.marks++;
    const box = m.closest('button, [role=option], .du-row, .cb-row, li, small, .cb-shl') || m.parentElement;
    const r = m.getBoundingClientRect(), B = box.getBoundingClientRect();
    if (!inside(r, B)) out.bad.push(`outside ${box.className || box.tagName}: ${box.textContent.trim().slice(0, 30)}`);
    const badge = box.querySelector('kbd, .a-key');
    if (badge && vis(badge) && hit(r, badge.getBoundingClientRect())) out.bad.push(`over the badge: ${box.textContent.trim().slice(0, 30)}`);
    // glued to the last word: the glue never breaks, so the mark is on the same line as that word
    const g = m.closest('.pt-glue'); if (g) { const gr = g.getClientRects(); if (gr.length > 1) out.bad.push(`the mark wrapped off its word: ${g.textContent}`); }
  }
  out.dashed = [...document.querySelectorAll('button *, [role=option] *')].filter(e => vis(e) && getComputedStyle(e).borderStyle.includes('dashed') && /pretend/i.test(e.textContent)).length;
  return out;
}"""
ROWS = r"""() => { const bs = [...document.querySelectorAll('#aPanel .a-order')].filter(b => b.getClientRects().length);
  const rows = {}; for (const b of bs) { const q = b.getBoundingClientRect(); (rows[Math.round(q.top)] = rows[Math.round(q.top)] || []).push(Math.round(q.height)); }
  return { n: bs.length, rows: Object.values(rows) }; }"""


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8203")
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--enable-unsafe-swiftshader"])
        # ---------------- the order buttons (lesson / check ride) ----------------
        ctx = b.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_init_script(SEED)
        silence(ctx)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(base + "/")
        until(pg, "() => window.__outpost && window.__outpost.shellNav", 30000)
        pg.wait_for_timeout(1200)
        pg.evaluate("() => window.__outpost.shellNav('lesson', 'radiation', 'lesson radiation')")
        until(pg, "() => window.__outpost.academyTest && window.__outpost.academyTest.where.view === 'lesson'", 10000)
        pg.wait_for_timeout(500)
        step = pg.evaluate("() => { const L = window.__outpost.academyTest; for (let i = 0; i < 6; i++) { L.step(i); if (document.querySelector('#aPanel .a-order')) return i; } return -1; }")
        ok(step >= 0, f"the radiation lesson's order step is up (step {step + 1})")
        for w, h in ((1024, 640), (1280, 800), (1920, 1080)):
            pg.set_viewport_size({"width": w, "height": h})
            pg.wait_for_timeout(600)
            c = pg.evaluate(CHECK)
            ok(c["marks"] >= 1 and not c["bad"] and not c["dashed"], f"{w}x{h} orders: {c['marks']} mark(s), all inside, no dashed box ({c['bad']})")
            rows = pg.evaluate(ROWS)
            ok(all(len(set(r)) == 1 for r in rows["rows"]), f"{w}x{h} orders: every button in a row has the same height ({rows['rows']})")
            if a.shots:
                os.makedirs(a.shots, exist_ok=True)
                pg.screenshot(path=os.path.join(a.shots, f"orders-{w}.png"))
        pg.set_viewport_size({"width": 1280, "height": 800})
        pg.wait_for_timeout(400)
        ok(not pg.evaluate("() => localStorage.getItem('outpost-pretend-explained')"), "not explained before it is picked")
        pg.evaluate("() => [...document.querySelectorAll('#aPanel .a-order')].find(b => b.querySelector('.pt-mark')).click()")
        pg.wait_for_timeout(300)
        ok(pg.evaluate("() => localStorage.getItem('outpost-pretend-explained')") == "1", "picking Shields up gives the explanation (once per cadet)")
        ok(not errs, f"no page errors {errs[:2]}")
        ctx.close()

        # ---------------- the cabin: Shields, the Radiation panel, an alert ----------------
        ctx = b.new_context(viewport={"width": 1440, "height": 879})
        ctx.add_init_script(mu.SEED)
        ctx.add_init_script("window.__outpostTest = true;")
        silence(ctx)
        pg = ctx.new_page()
        pg.goto(base + "/")
        until(pg, "() => window.__outpost && window.__outpost.missionUI", 30000)
        ok(mu.to_steer(pg) or until(pg, "() => !!document.querySelector('.cb-now-btns')", 5000), "the mission is running")
        pg.evaluate("() => window.__cabinTest && window.__cabinTest.storm(true)")
        pg.wait_for_timeout(1200)
        for w, h in ((1024, 640), (1440, 879), (1920, 1080)):
            pg.set_viewport_size({"width": w, "height": h})
            pg.wait_for_timeout(900)
            c = pg.evaluate(CHECK)
            ok(c["marks"] >= 1 and not c["bad"] and not c["dashed"], f"{w}x{h} cabin (seat, storm alert): {c['marks']} mark(s) inside ({c['bad']})")
        pg.evaluate("() => window.__cabinTest && window.__cabinTest.panel('radiation')")
        pg.wait_for_timeout(1500)
        c = pg.evaluate(CHECK)
        ok(c["marks"] >= 1 and not c["bad"], f"Radiation panel: the Shields row's mark inside its row ({c['marks']}, {c['bad']})")
        if a.shots:
            pg.screenshot(path=os.path.join(a.shots, "cabin-radiation.png"))
        m = pg.evaluate(mu.MEASURE, mu.HUD)
        ok(not m.get("crossing"), f"mission_ui's check: nothing crosses a button border ({m.get('crossing', [])[:3]})")
        ctx.close()
        b.close()
    bad = [w for c, w in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
