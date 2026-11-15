"""Every executed order gets its spoken readback, every end shift its report (owner's rc/2 play: "more power to the
heaters" and the first "end shift" were silent). First mission, Cadet, tour skipped; the floor's playback events are
recorded. The kid waits ~21 s between some orders so the first-shift nudge comes due right as a report starts (the
nudge used to cut it off). Asserts each readback / report starts AND plays to its end (never "interrupted").

  uv run --with playwright python frontend/tools/orders_spoken.py --base http://127.0.0.1:5398
"""
import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

SEED = """try{ localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-prefs', JSON.stringify({level:'cadet'})); }catch(e){}"""
HOOK = """() => { const O = window.__outpost; window.__pb = [];
  O.floor.on('playback', e => { if (e.kind === 'guide') window.__pb.push({ state: e.state, id: e.id, text: e.text || '' }); }); }"""
TYPED = "t => { const q = document.getElementById('q'); q.value = t; document.getElementById('askForm').requestSubmit(); }"
# (what the kid says, the start of the line CAPCOM must say for it, seconds of silence before the next order)
SCRIPT = [("more power to the heaters", "Copy. Heaters", 21), ("end shift", "Copy. Day 1, shift 2", 4),
          ("shields to 40", "Copy. Radiation shields", 21), ("end shift", "Copy. Day 1, shift 3", 4)]


def run(base):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    fails = []

    def check(cond, msg):
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.add_init_script(SEED)
        pg.goto(base)
        pg.wait_for_selector("#mStart", timeout=60000)
        pg.wait_for_timeout(1500)
        pg.evaluate(HOOK)
        pg.evaluate("document.getElementById('mStart').click()")
        pg.wait_for_selector(".m-tour:not([hidden])", timeout=60000)
        pg.evaluate("document.querySelector('.m-tour .t-skip').click()")
        pg.wait_for_timeout(3000)
        for text, want, gap in SCRIPT:
            pg.evaluate(TYPED, text)
            # wait (up to 40 s, the shared TTS can be slow) until the line has started and finished, or was cut off
            try:
                pg.wait_for_function("""w => { const s = window.__pb.find(e => e.state === 'start' && e.text.startsWith(w));
                    return s && window.__pb.some(e => e.id === s.id && e.state !== 'start'); }""", arg=want, timeout=40000)
            except Exception:
                pass   # reported below as not said / not finished
            ev = pg.evaluate("w => { const s = window.__pb.find(e => e.state === 'start' && e.text.startsWith(w)); return s ? window.__pb.filter(e => e.id === s.id) : []; }", want)
            started = any(e["state"] == "start" for e in ev)
            ended = [e["state"] for e in ev if e["state"] != "start"]
            check(started and ended == ["end"], f"'{text}': CAPCOM said \"{want}…\" to the end ({[e['state'] for e in ev]})")
            pg.evaluate("window.__pb = window.__pb.filter(e => false)")
            pg.wait_for_timeout(gap * 1000)
        b.close()
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 0 if not fails else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5398")
    sys.exit(run(ap.parse_args().base))
