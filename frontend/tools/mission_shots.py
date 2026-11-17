"""Mission screens at three sizes, for review by eye (Mission polish 4): the hub, the briefing, a normal step, a storm
takeover and the debrief. Headless and muted (frontend/tools/silent.py). Also checks the debrief's primary button and
the hub / briefing primary are inside the viewport without scrolling.

  uv run --no-project --with playwright==1.58.0 python frontend/tools/mission_shots.py --base http://127.0.0.1:5314 \
      --out docs/img/mission-polish --tag p4 [--sizes 1440x900,1280x720,1024x640]
"""
import argparse
import glob
import json
import os
import sys

from playwright.sync_api import sync_playwright
_d = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_d]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless)

SEED = """try{ if (!sessionStorage.getItem('shots')) { localStorage.clear(); sessionStorage.setItem('shots','1'); }
  localStorage.setItem('atm-theme','dark'); localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-prefs', JSON.stringify({level:'commander'})); window.__outpostTest = 1; }catch(e){}"""

# is the element's whole box inside the viewport (no scrolling needed) and the top thing at its centre?
IN_VIEW = """(s) => { const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null;
  const r = e.getBoundingClientRect(), h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return { top: Math.round(r.top), bottom: Math.round(r.bottom), vh: innerHeight, inside: r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth,
    hit: !!(h && (h === e || e.contains(h))) }; }"""


def chromium():
    return (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]


def run(base, out, tag, size):
    w, h = size
    res = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium(), args=["--use-gl=angle", "--use-angle=swiftshader"])
        ctx = b.new_context(viewport={"width": w, "height": h})
        ctx.add_init_script(SEED)
        pg = ctx.new_page()
        js = pg.evaluate

        def shot(name):
            pg.screenshot(path=os.path.join(out, f"{tag}-{name}-{w}x{h}.jpg"), type="jpeg", quality=70, timeout=180000)

        def tap(sel):
            # a real click when the control is on top at its centre (what a mouse would hit), else a DOM click
            r = js(IN_VIEW, sel)
            if r and r["hit"]:
                pg.click(sel, timeout=10000, force=True)
            else:
                js("(s) => document.querySelector(s).click()", sel)

        def vis(sel):
            return js("(s) => { const e = document.querySelector(s); return !!(e && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden'); }", sel)

        def wait(sel, ms=30000):
            pg.wait_for_function("(s) => { const e = document.querySelector(s); return !!(e && e.getClientRects().length); }", arg=sel, timeout=ms)

        pg.goto(base)
        wait("#mStart", 60000)
        pg.wait_for_timeout(2500)
        if vis(".mx-hub"):
            res["hub"] = js(IN_VIEW, "#mStart")
            shot("1-hub")
            tap("#mStart")
            wait("#mBriefGo")
            pg.wait_for_timeout(1500)
            res["briefing"] = js(IN_VIEW, "#mBriefGo")
            shot("2-briefing")
            tap("#mBriefGo")
        else:
            res["picker"] = js(IN_VIEW, "#mStart")
            shot("1-picker")
            tap("#mStart")
            pg.wait_for_timeout(2500)
            if vis("#mlSkip"):
                tap("#mlSkip")
        wait(".cb-now:not([hidden]), .m-tour:not([hidden])", 60000)
        pg.wait_for_timeout(3000)
        if vis(".m-tour:not([hidden])"):
            shot("3a-tour")
            while vis(".m-tour:not([hidden])"):
                tap(".m-tour .t-next")
                pg.wait_for_timeout(500)
            pg.wait_for_timeout(1500)
        res["coach"] = js("() => { const c = document.querySelector('.cb-coach:not([hidden])'); return c ? c.textContent : null; }")
        shot("3-first-step")
        # a normal step: do the first job (an order), then the next card
        if vis(".cb-now-btns .cb-now-b"):
            tap(".cb-now-btns .cb-now-b")
            pg.wait_for_timeout(600)
            shot("3b-ack")
            pg.wait_for_timeout(2500)
        shot("4-normal-step")
        js("() => window.__outpost.missionUI.clockAction('pause')")
        js("() => window.__cabinTest.storm(true)")
        pg.wait_for_timeout(1500)
        res["storm"] = js(IN_VIEW, ".cb-now.is-takeover .cb-now-b")
        shot("5-storm-takeover")
        js("() => window.__cabinTest.storm(false)")
        js("() => window.__cabinTest.moment('On our own')")
        pg.wait_for_timeout(1800)
        res["moment_overlap"] = js("""() => { const m = document.querySelector('.cb-moment:not([hidden])'); if (!m) return null; const r = m.getBoundingClientRect();
          return [...document.querySelectorAll('.tv-mark')].filter(k => k.getClientRects().length && getComputedStyle(k).opacity > 0.05 && getComputedStyle(k).visibility !== 'hidden').map(k => ({ t: k.textContent, b: k.getBoundingClientRect() }))
            .filter(o => !(o.b.right < r.left || o.b.left > r.right || o.b.bottom < r.top || o.b.top > r.bottom)).map(o => o.t); }""")
        shot("6-moment")
        js("() => window.__cabinTest.debrief('survived', {stars: 3})")
        wait("#mAgain")
        pg.wait_for_timeout(2500)
        res["debrief"] = js(IN_VIEW, "#mAgain")
        res["debrief_scroll"] = js("() => { const d = document.getElementById('mDebrief'); return d.scrollTop; }")
        shot("7-debrief")
        b.close()
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5314")
    ap.add_argument("--out", default="docs/img/mission-polish")
    ap.add_argument("--tag", default="p4")
    ap.add_argument("--sizes", default="1440x900,1280x720,1024x640")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    bad = False
    for sz in a.sizes.split(","):
        r = run(a.base, a.out, a.tag, tuple(map(int, sz.split("x"))))
        print(sz, json.dumps(r))
        for k in ("hub", "briefing", "debrief", "storm"):
            if k in r and not (r[k] and r[k]["inside"] and r[k]["hit"]):
                bad = True
        if r.get("moment_overlap"):
            bad = True
    print("FAIL" if bad else "PASS")
    sys.exit(1 if bad else 0)
