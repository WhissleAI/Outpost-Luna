"""The cockpit's patch key (mission/patches.js, cabin.js paintPatches), in the real app, headless and muted.

Seeds a cadet with Flight School and Field School patches, takes command, then checks:
  * the key sits on the Habitat console, inside its plate, on screen, and shows the count;
  * Enter on the key opens the card (focus on its close key), which names every patch with its school, every word
    at least 18 px, clear of the viewport edges; Esc closes it and focus goes back to the key;
  * a patch earned while the cabin is up (the Academy's "outpost:patches") repaints the key at once and is announced.

  uv run --with playwright python frontend/tests/e2e/cockpit_patches_e2e.py --base http://127.0.0.1:8147 --shots <dir>
"""
import argparse
import os
import sys

from playwright.sync_api import sync_playwright

_d = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [_d, os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: muted, headless)
from mission_ui import PAD, chromium  # noqa: E402

BADGES = ["scout", "watcher", "sun", "radio", "storm", "ice", "commander", "observer", "fieldkit"]
SEED = """try{ localStorage.clear(); localStorage.setItem('atm-theme','dark'); localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:%s, qualified:true}));
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-prefs', JSON.stringify({level:'cadet', graphics:'low'}));
  localStorage.setItem('outpost-tour-done:Comet','1'); localStorage.setItem('outpost-moonbase-seen:Comet','1'); window.__hourMs = 2000; window.__missionSeed = 2; }catch(e){}""" % (str(BADGES).replace("'", '"'))

STATE = """() => {
  const R = e => { const r = e.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom].map(Math.round); };
  const key = document.getElementById('cbPatchKey'), dsp = document.querySelector('.cb-hab'), deck = document.querySelector('.cb-deck');
  const pop = document.getElementById('cbPatchPop');
  const sizes = pop && !pop.hidden ? [...pop.querySelectorAll('b, small, p')].filter(e => e.textContent.trim()).map(e => parseFloat(getComputedStyle(e).fontSize)) : [];
  return { key: key && !key.hidden ? R(key) : null, dsp: dsp ? R(dsp) : null, deck: deck ? R(deck) : null, label: key && key.getAttribute('aria-label'),
    expanded: key && key.getAttribute('aria-expanded'), n: key && (key.querySelector('.cb-patchn') || {}).textContent,
    art: key ? key.querySelectorAll('svg').length : 0, keyFont: key ? parseFloat(getComputedStyle(key.querySelector('.cb-patchn')).fontSize) : 0,
    keyText: key ? key.textContent.trim() : '',
    pop: pop && !pop.hidden ? R(pop) : null, items: pop ? [...pop.querySelectorAll('.cb-patchli')].map(li => li.textContent.trim()) : [],
    sum: (document.getElementById('cbPatchSum') || {}).textContent, sizes, focus: document.activeElement && document.activeElement.id,
    news: (document.getElementById('cbPatchNews') || {}).textContent, vw: innerWidth, vh: innerHeight };
}"""


def inside(a, b, pad=1):
    return a and b and a[0] >= b[0] - pad and a[1] >= b[1] - pad and a[2] <= b[2] + pad and a[3] <= b[3] + pad


def run(base, shots, sizes):
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium(), args=["--mute-audio", "--use-gl=angle", "--use-angle=swiftshader"])
        for vw, vh in sizes:
            tag = f"{vw}x{vh}"
            pg = b.new_page(viewport={"width": vw, "height": vh}, device_scale_factor=1)
            pg.set_default_timeout(120000)
            pg.add_init_script(PAD)
            pg.add_init_script(SEED)
            pg.goto(base)
            pg.wait_for_selector("#mStart")
            pg.wait_for_timeout(1500)
            pg.evaluate("document.getElementById('mStart').click()")
            pg.wait_for_selector("#mBriefGo, .cb-now-btns .cb-now-b")
            pg.evaluate("() => { const b = document.getElementById('mBriefGo'); if (b) b.click(); }")
            pg.wait_for_selector("#cbPatchKey:not([hidden])")
            pg.wait_for_timeout(1500)
            s = pg.evaluate(STATE)
            f = []
            if not inside(s["key"], s["dsp"]):
                f.append(f"the key {s['key']} is not inside the Habitat console {s['dsp']}")
            if s["key"] and (s["key"][0] < 0 or s["key"][1] < 0 or s["key"][2] > vw or s["key"][3] > vh):
                f.append(f"the key is off-screen: {s['key']}")
            if s["n"] != str(len(BADGES)) or s["label"] != f"Patches: {len(BADGES)} earned. Show them":
                f.append(f"key count/label: {s['n']!r} {s['label']!r}")
            if s["art"] != 3 or s["keyFont"] < 18 or not s["keyText"].startswith("Patches"):
                f.append(f"key art {s['art']} / count font {s['keyFont']}px / text {s['keyText']!r}")
            if shots:
                pg.screenshot(path=os.path.join(shots, f"patchkey-{tag}.png"), timeout=300000)
            # keyboard: focus the key, Enter opens the card (focus lands on its close key)
            pg.evaluate("document.getElementById('cbPatchKey').focus()")
            pg.keyboard.press("Enter")
            pg.wait_for_timeout(400)
            s = pg.evaluate(STATE)
            if not s["pop"] or s["expanded"] != "true" or s["focus"] != "cbPatchPopX":
                f.append(f"Enter did not open the card: pop {s['pop']} expanded {s['expanded']} focus {s['focus']}")
            else:
                if len(s["items"]) != len(BADGES):
                    f.append(f"the card lists {len(s['items'])} patches")
                if not any("Field School" in t for t in s["items"]) or "Field School" not in (s["sum"] or ""):
                    f.append("no Field School patch on the card")
                if s["sizes"] and min(s["sizes"]) < 18:
                    f.append(f"card text below 18 px: {min(s['sizes'])}")
                if s["pop"][0] < 0 or s["pop"][1] < 0 or s["pop"][2] > vw or s["pop"][3] > vh:
                    f.append(f"the card is off-screen: {s['pop']}")
                if shots:
                    pg.screenshot(path=os.path.join(shots, f"patchcard-{tag}.png"), timeout=300000)
            pg.keyboard.press("Escape")
            pg.wait_for_timeout(300)
            s = pg.evaluate(STATE)
            if s["pop"] or s["focus"] != "cbPatchKey":
                f.append(f"Esc: pop {s['pop']} focus {s['focus']}")
            # live: a patch earned while the cabin is up
            pg.evaluate("""() => { const a = window.__outpost.academyUI; a.progress.badges.push('rockhound');
              dispatchEvent(new CustomEvent('outpost:patches', { detail: { id: 'rockhound' } })); }""")
            pg.wait_for_timeout(300)
            s = pg.evaluate(STATE)
            if s["n"] != str(len(BADGES) + 1) or s["news"] != "New patch: Rock Hound":
                f.append(f"live repaint: count {s['n']!r}, announced {s['news']!r}")
            if shots:
                pg.screenshot(path=os.path.join(shots, f"patchkey-new-{tag}.png"), timeout=300000)
            print(f"{'ok  ' if not f else 'FAIL'} {tag}")
            for x in f:
                print(f"       {x}")
            bad += [f"{tag}: {x}" for x in f]
            pg.close()
        b.close()
    print("PASS" if not bad else f"FAIL ({len(bad)} findings)")
    return 0 if not bad else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5199")
    ap.add_argument("--shots", default="")
    ap.add_argument("--sizes", default="1440x900,1280x720,1024x640")
    a = ap.parse_args()
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    sys.exit(run(a.base, a.shots, [tuple(map(int, s.split("x"))) for s in a.sizes.split(",")]))
