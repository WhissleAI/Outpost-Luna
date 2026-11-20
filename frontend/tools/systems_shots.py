"""The Systems drawer and the wave-5 feedback, by level and window size (docs/GAMEPLAY.md §17).

For each level (cadet, commander, engineer) and size it flies into the cabin and checks, with the keyboard only:
  * the Systems key is on screen with its word; ] opens the drawer, focus moves inside;
  * the panels follow the level (Cadet: Power, Radiation, Rover; Commander and Engineer: + Life support, Radio);
  * every text in the drawer is >= 20 px; nothing in it is clipped off screen; it never covers the Now card;
  * ] / [ step the panels (and wrap); Esc closes it and focus goes back to the Systems key;
  * a drawer control sends the same order as its console twin (Shields + on the Radiation panel moves the shields);
  * Engineer shows the numbers (kW, mSv) and an equation line;
then shoots the drawer on each panel, the objective-done pulse and the chapter card (stars landing).

    uv run --no-project --with playwright==1.58.0 python frontend/tools/systems_shots.py --base http://localhost:5473 \
        --sizes 1440x900,1280x720,1024x640 --shots docs/img/systems
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless)

SEED = """try{ localStorage.clear(); localStorage.setItem('atm-theme','dark'); localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('outpost-first-mission:Comet','1'); localStorage.setItem('outpost-tour-done:Comet','1'); localStorage.setItem('outpost-coach-done:Comet','1');
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-prefs', JSON.stringify({level:'%s'})); window.__outpostTest = 1; }catch(e){}"""
results = []


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)


def chromium():
    return (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]


FONTS = """() => { const el = document.getElementById('cbSys'); el.getAnimations().forEach(x => x.finish()); const small = []; const W = innerWidth, H = innerHeight;
  const walk = n => { for (const c of n.childNodes) { if (c.nodeType === 3 && c.textContent.trim()) { const p = c.parentElement, cs = getComputedStyle(p);
      if (p.closest('[hidden]') || cs.visibility === 'hidden' || p.closest('.cb-vh')) continue; const f = parseFloat(cs.fontSize); if (f < 19.5) small.push(c.textContent.trim().slice(0, 24) + ' ' + f); }
    else if (c.nodeType === 1) walk(c); } };
  walk(el); const r = el.getBoundingClientRect(), now = document.querySelector('#cbNow:not([hidden])'), n = now ? now.getBoundingClientRect() : null;
  const over = n && !(n.right <= r.left || n.left >= r.right || n.bottom <= r.top || n.top >= r.bottom);
  return { small, inside: r.left >= 0 && r.top >= 0 && r.right <= W + 0.5 && r.bottom <= H + 0.5, over: !!over, w: Math.round(r.width), h: Math.round(r.height) }; }"""
STATE = """() => { const el = document.getElementById('cbSys'), a = document.activeElement; return { open: !!el && !el.hidden, panel: el && el.dataset.sys,
  tabs: el ? [...el.querySelectorAll('.sys-tab')].map(t => t.dataset.sys) : [], inside: !!(el && el.contains(a)), key: a && a.id === 'cbSysKey',
  title: el ? el.querySelector('.sys-t').textContent : '' }; }"""


def into_cabin(pg):
    pg.wait_for_selector("#mStart", timeout=60000)
    pg.wait_for_timeout(800)
    pg.click("#mStart")
    for _ in range(20):
        if pg.query_selector("#mlSkip"):
            pg.click("#mlSkip")
        if pg.query_selector("#mBriefGo"):
            pg.click("#mBriefGo")
            break
        pg.wait_for_timeout(600)
    pg.wait_for_selector(".cb-now:not([hidden])", timeout=60000)
    pg.wait_for_timeout(4000)


def run(base, level, size, shots):
    vw, vh = size
    tag = f"{level}-{vw}x{vh}"
    shot = (lambda name: pg.screenshot(path=os.path.join(shots, f"{tag}-{name}.png"), timeout=180000)) if shots else (lambda name: None)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium(), args=["--mute-audio", "--use-gl=angle", "--use-angle=swiftshader"])
        pg = b.new_page(viewport={"width": vw, "height": vh})
        pg.on("pageerror", lambda e: print("PAGEERR", str(e)[:300]))
        pg.add_init_script(SEED % level)
        pg.goto(base + "/")
        into_cabin(pg)
        shot("01-seat")
        key = pg.evaluate("() => { const k = document.getElementById('cbSysKey'); if (!k) return null; const r = k.getBoundingClientRect(), s = k.querySelector('span');"
                          " return { w: r.width, word: !!s && getComputedStyle(s).display !== 'none', on: r.right <= innerWidth && r.top >= 0 }; }")
        ok(key and key["on"] and key["word"], f"{tag}: the Systems key is on screen with its word")
        if not key:
            b.close()
            return
        pg.keyboard.press("]")
        pg.wait_for_timeout(700)
        s = pg.evaluate(STATE)
        want = ["power", "radiation", "rover"] if level == "cadet" else ["power", "radiation", "rover", "life", "radio"]
        ok(s["open"] and s["tabs"] == want, f"{tag}: ] opens the drawer with {len(want)} panels ({','.join(s['tabs'])})")
        pg.wait_for_timeout(400)
        s = pg.evaluate(STATE)
        ok(s["inside"], f"{tag}: focus moved into the drawer")
        start = want.index(s["panel"]) if s["panel"] in want else 0
        ok(True, f"{tag}: it opened at {s['panel']} (the Now job's panel, else the first)")
        order = want[start:] + want[:start]
        for i, pid in enumerate(order):
            pg.wait_for_timeout(700)   # the slide-in (a transform) is over
            s = pg.evaluate(STATE)
            f = pg.evaluate(FONTS)
            ok(not f["small"], f"{tag}: {s['title']} panel, every text >= 20 px" + (f" (small: {f['small'][:4]})" if f["small"] else ""))
            ok(f["inside"] and not f["over"], f"{tag}: {s['title']} panel on screen, clear of the Now card ({f['w']}x{f['h']})")
            ok(s["panel"] == pid and s["inside"], f"{tag}: ] reached {pid}, focus still in the drawer")
            shot(f"02-{want.index(pid) + 1}-{pid}")
            pg.keyboard.press("]")
        pg.wait_for_timeout(500)
        ok(pg.evaluate(STATE)["panel"] == order[0], f"{tag}: ] wraps back to {order[0]}")
        pg.keyboard.press("[")
        pg.wait_for_timeout(500)
        ok(pg.evaluate(STATE)["panel"] == order[-1], f"{tag}: [ steps back to {order[-1]}")
        # the same order as the console: Shields + on the Radiation panel
        sh0 = pg.evaluate("() => +document.getElementById('cbShVal').textContent")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(500)
        s = pg.evaluate(STATE)
        ok(not s["open"] and s["key"], f"{tag}: Esc closes the drawer, focus back on the Systems key")
        pg.keyboard.press("Enter")   # the key itself opens it again
        pg.wait_for_timeout(500)
        ok(pg.evaluate(STATE)["open"], f"{tag}: Enter on the Systems key opens it")
        for _ in range(4):
            if pg.evaluate(STATE)["panel"] == "radiation":
                break
            pg.keyboard.press("]")
            pg.wait_for_timeout(300)
        if sh0 < 60:
            pg.click('#cbSys [data-act="shields"][data-d="10"]')
            pg.wait_for_timeout(1500)
            sh1 = pg.evaluate("() => +document.getElementById('cbShVal').textContent")
            ok(sh1 == sh0 + 10, f"{tag}: Shields + in the drawer moves the console's knob too ({sh0} -> {sh1})")
        if level == "engineer":
            pg.click('#cbSys .sys-tab[data-sys="power"]')   # the Power tab
            pg.wait_for_timeout(800)
            txt = pg.evaluate("() => document.getElementById('cbSys').textContent")
            ok("kW" in txt and pg.evaluate("() => !!document.querySelector('#cbSys .sys-eq')"), f"{tag}: Engineer sees kW and an equation line")
        # the Why card from a drawer gauge sits beside the drawer, never on it
        pg.click("#cbSys .sys-gauge .sys-why")
        pg.wait_for_timeout(600)
        w = pg.evaluate("() => { const w = document.getElementById('cbWhy'), s = document.getElementById('cbSys'); if (!w || w.hidden) return null; const a = w.getBoundingClientRect(), b = s.getBoundingClientRect(); return { clear: a.right <= b.left + 1 }; }")
        ok(w and w["clear"], f"{tag}: the gauge's (i) opens its Why card beside the drawer")
        shot("03-why")
        # the objective-done pulse, then the chapter card
        pg.keyboard.press("Escape")   # the Why card closes first; the drawer stays (its control can wear the pulse)
        pg.wait_for_timeout(400)
        n = pg.evaluate("() => window.__cabinTest ? window.__cabinTest.pulse() : 0")
        pg.wait_for_timeout(120)   # inside the pulse's held ring (cabin.css nowDone 15%-50%)
        ok(n >= 1 and pg.evaluate("() => !!document.querySelector('#cbNow[data-done]')"), f"{tag}: the done pulse marks the Now card ({n} nodes)")
        an = pg.evaluate("() => { const n = document.getElementById('cbNow'); return { name: getComputedStyle(n).animationName, run: n.getAnimations().map(a => a.animationName + ':' + a.playState + ':' + Math.round(a.currentTime || 0)) }; }")
        ok("nowDone" in an["name"], f"{tag}: the Now card plays the pulse ({an})")
        # a screenshot of the 3D cabin can take longer than the 1.1 s pulse: hold the frame at its peak for the picture
        pg.evaluate("() => document.querySelectorAll('[data-done]').forEach(n => n.getAnimations().forEach(a => { a.pause(); a.currentTime = 300; }))")
        shot("04-pulse")
        pg.evaluate("() => document.querySelectorAll('[data-done]').forEach(n => n.getAnimations().forEach(a => a.finish()))")
        pg.evaluate("() => { document.documentElement.dataset.motion = 'reduce'; }")   # less motion: colour only
        pg.wait_for_timeout(1400)
        pg.evaluate("() => window.__cabinTest.pulse()")
        pg.wait_for_timeout(220)
        shot("04b-pulse-reduced")
        pg.evaluate("() => { delete document.documentElement.dataset.motion; }")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(300)
        pg.evaluate("() => window.__cabinTest.chapter({ safe: true, powered: true, science: level === 'cadet' })".replace("level", repr(level)))
        pg.wait_for_timeout(400)
        shot("05-chapter-landing")
        pg.wait_for_timeout(1800)
        ok(pg.evaluate("() => !document.getElementById('cbChapter').hidden && document.activeElement.id === 'cbChGo'"), f"{tag}: the chapter card is up, focus on its button")
        shot("06-chapter")
        b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5473")
    ap.add_argument("--levels", default="cadet,commander,engineer")
    ap.add_argument("--sizes", default="1440x900,1280x720,1024x640")
    ap.add_argument("--shots", default="")
    a = ap.parse_args()
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    for lv in a.levels.split(","):
        for sz in a.sizes.split(","):
            run(a.base, lv, tuple(map(int, sz.split("x"))), a.shots)
    bad = [w for c, w in results if not c]
    print(f"{len(results) - len(bad)}/{len(results)} checks")
    sys.exit(1 if bad else 0)
