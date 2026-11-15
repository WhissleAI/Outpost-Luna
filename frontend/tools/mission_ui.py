"""Mission cabin layout check: nothing overlaps, nothing is clipped, at every window size (docs/GAMEPLAY.md §9).

The owner's 1440x879 play (round 3): the Now card covered the clock strip, the windshield and the gauges, and its text
collided with the time controls. The round-2 novice run passed anyway, because it only checked that a button could be
clicked, not what it covered. This tool checks what a kid SEES:

  * the HUD elements that are visible (clock / time strip, Now card, view tabs, progress, sky readout, rover pill,
    alert strip, mission log) never intersect each other;
  * the Now card never covers the windshield's centre or the three gauges (POWER / LIFE SUPPORT / DOSE);
  * nothing visible is cut by the viewport, and no label is clipped by its own box (scrollWidth > clientWidth);
  * every control is shown once (one Pause/Play, one speed group, one Skip ahead).

It drives the real app to the owner's moment (Cadet, Shackleton Rim, ice run, the "Steer left / Steer right" choice),
shoots each size into --shots, and exits non-zero on any finding.

  uv run --with playwright python frontend/tools/mission_ui.py --base http://127.0.0.1:5199 --shots docs/img/mission-ui --tag after
"""
import argparse
import glob
import json
import os
import sys

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

SIZES = "1280x720,1440x879,1440x900,1920x1080,1024x640"
SEED = """try{ localStorage.clear(); localStorage.setItem('atm-theme','dark'); localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-prefs', JSON.stringify({level:'cadet', graphics:'low'}));
  localStorage.setItem('outpost-tour-done:Comet','1'); window.__hourMs = 700; }catch(e){}"""

# The HUD elements a kid reads in the seat view. Selectors that don't exist in a build are simply skipped.
HUD = {
    "clock": "#cbClock", "time": "#cbTime", "views": ".cb-views", "progress": "#cbProg", "now": "#cbNow",
    "sky": "#cbSky", "rover": "#cbRover", "alert": "#cbAlert", "log": "#cbMlog", "deck": ".cb-deck",
}
MEASURE = """(HUD) => {
  const vis = e => !!(e && !e.hidden && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && +getComputedStyle(e).opacity > 0.05);
  const R = e => { const r = e.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)]; };
  const out = { hud: {}, clipped: [], dupes: {}, vw: innerWidth, vh: innerHeight };
  for (const [k, s] of Object.entries(HUD)) { const e = document.querySelector(s); if (vis(e)) out.hud[k] = R(e); }
  // the deck contains the clock / time / progress: they are one element there, not three to compare
  const deck = document.querySelector('.cb-deck');
  if (deck && vis(deck)) for (const k of ['clock', 'time', 'progress', 'views']) { const e = document.querySelector(HUD[k]); if (e && deck.contains(e)) delete out.hud[k]; }
  // the top bar: the Mute button sits next to Settings; nothing in the bar overlaps (the brand, the sections, the icons)
  out.topbar = [...document.querySelectorAll('.topbar .brand, .topbar .modes, .topnav > button')].filter(vis).map(e => [e.id || e.className.split(' ')[0], ...R(e)]);
  out.mute = (() => { const m = document.getElementById('muteBtn'), g = document.getElementById('a11yBtn');
    return m && vis(m) ? { pressed: m.getAttribute('aria-pressed'), label: m.getAttribute('aria-label'), nextToSettings: !!(g && m.nextElementSibling === g) } : null; })();
  // the consoles (3D panels): the Now panel may not sit on them
  out.consoles = [...document.querySelectorAll('.c3-panel')].filter(vis).map(e => [e.dataset.panel, ...R(e)]);
  // inside the deck, its own groups must not collide either (the owner's "1x 13 h" over "1x")
  if (deck && vis(deck)) { const parts = [...deck.children].filter(vis).map(e => [e.className.split(' ')[0], ...R(e)]); out.deckParts = parts; }
  const hole = document.querySelector('.cb-hole') || document.querySelector('.cb-glass');
  if (hole) { const r = R(hole), w = r[2] - r[0], h = r[3] - r[1]; out.windshield = [r[0] + w * .25, r[1] + h * .3, r[2] - w * .25, r[3] - h * .15].map(Math.round); }
  const dus = [...document.querySelectorAll('[data-du]')].filter(vis).map(e => R(e.querySelector('.du-head') || e));
  out.gauges = dus;
  // labels clipped by their own box (text cut with no ellipsis by design), in the HUD only
  const scope = [...document.querySelectorAll('.cb-deck, .cb-hole, .cb-glass, #cbNow')];
  const seen = new Set();
  scope.forEach(root => root.querySelectorAll('b, span, small, em, button, p, h3').forEach(e => {
    if (seen.has(e) || !vis(e) || !e.textContent.trim()) return; seen.add(e);
    const cs = getComputedStyle(e);
    if (cs.overflow === 'visible' && cs.textOverflow !== 'ellipsis') {
      const r = e.getBoundingClientRect();
      if (r.left < -1 || r.top < -1 || r.right > innerWidth + 1 || r.bottom > innerHeight + 1) out.clipped.push(['viewport', e.className || e.tagName, e.textContent.trim().slice(0, 30)]);
    } else if (e.scrollWidth > e.clientWidth + 2 && cs.textOverflow !== 'ellipsis') out.clipped.push(['box', e.className || e.tagName, e.textContent.trim().slice(0, 30)]);
  }));
  // controls shown once
  const count = s => [...document.querySelectorAll(s)].filter(vis).length;
  out.dupes = { pause: count('#cbPlay'), speed: count('.cb-warps'), skip: [...document.querySelectorAll('button')].filter(b => vis(b) && /skip ahead/i.test(b.textContent)).length };
  out.now = (() => { const n = document.querySelector('#cbNow'); return n && vis(n) ? n.innerText.replace(/\\s+/g, ' ').trim().slice(0, 120) : null; })();
  return out;
}"""


def hits(a, b, pad=2):
    return a[0] < b[2] - pad and b[0] < a[2] - pad and a[1] < b[3] - pad and b[1] < a[3] - pad


def findings(m):
    out = []
    keys = list(m["hud"])
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if {a, b} <= {"log", "now"} or "log" in (a, b):
                continue   # the mission log is a popover the kid opened on purpose
            if hits(m["hud"][a], m["hud"][b]):
                out.append(f"overlap: {a} x {b}")
    parts = m.get("deckParts") or []
    for i, a in enumerate(parts):
        for b in parts[i + 1:]:
            if hits(a[1:], b[1:]):
                out.append(f"overlap inside the deck: {a[0]} x {b[0]}")
    tb = m.get("topbar") or []
    for i, a in enumerate(tb):
        for b in tb[i + 1:]:
            if hits(a[1:], b[1:], pad=0):
                out.append(f"top bar overlap: {a[0]} x {b[0]}")
    if not m.get("mute"):
        out.append("no Mute button in the top bar")
    elif not m["mute"]["nextToSettings"]:
        out.append("the Mute button is not next to Settings")
    deck = m["hud"].get("deck")
    if deck and m.get("windshield") and hits(deck, m["windshield"]):
        out.append("the deck covers the windshield centre")
    now = m["hud"].get("now")
    for c in m.get("consoles", []):
        r = c[1:]
        if now and hits(now, r):
            ix = max(0, min(now[2], r[2]) - max(now[0], r[0])) * max(0, min(now[3], r[3]) - max(now[1], r[1]))
            if ix > 0.08 * (now[2] - now[0]) * (now[3] - now[1]):
                out.append(f"the Now card covers the {c[0]} console")
    if now and m.get("windshield") and hits(now, m["windshield"]):
        out.append("the Now card covers the windshield centre")
    for g in m.get("gauges", []):
        if now and hits(now, g):
            out.append("the Now card covers a gauge")
    for k, r in m["hud"].items():
        if r[0] < 0 or r[1] < 0 or r[2] > m["vw"] or r[3] > m["vh"]:
            out.append(f"off-screen: {k} {r}")
    out += [f"clipped ({w}): {c} '{t}'" for w, c, t in m["clipped"]]
    if m["dupes"]["pause"] > 1 or m["dupes"]["speed"] > 1 or m["dupes"]["skip"] > 1:
        out.append(f"shown twice: {m['dupes']}")
    return out


def chromium():
    return (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]


def to_steer(pg):
    """Play like a kid to the owner's moment: raise the shields, start the clock, send the rover, wait for the boulders."""
    pg.wait_for_selector("#mStart")
    pg.wait_for_timeout(1500)
    pg.evaluate("document.getElementById('mStart').click()")
    pg.wait_for_selector(".cb-now-btns .cb-now-b")
    pg.wait_for_timeout(1200)
    for _ in range(40):
        c = pg.evaluate("() => window.__outpost.missionUI.card")
        if c and c.get("choice") and "teer" in (c.get("text") or ""):
            return True
        if c and c.get("buttons"):
            b = c["buttons"][0]
            if b.get("clock") == "skip" or "Time warp" in b.get("label", ""):
                pg.wait_for_timeout(700)   # let the drive run to the boulder field
            else:
                pg.evaluate("document.querySelector('.cb-now-btns .cb-now-b').click()")
        pg.wait_for_timeout(700)
    return False


def main(base, shots, tag, sizes):
    bad = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium(), args=["--mute-audio", "--use-gl=angle", "--use-angle=swiftshader"])
        for vw, vh in sizes:
            pg = b.new_page(viewport={"width": vw, "height": vh}, device_scale_factor=1)
            pg.set_default_timeout(180000)
            pg.add_init_script(SEED)
            pg.goto(base)
            got = to_steer(pg)
            pg.wait_for_timeout(1500)
            m = pg.evaluate(MEASURE, HUD)
            f = findings(m) + ([] if got else ["never reached the steer choice"])
            bad[f"{vw}x{vh}"] = f
            if shots:
                pg.screenshot(path=os.path.join(shots, f"{tag}-{vw}x{vh}.jpg"), type="jpeg", quality=70, timeout=300000)
            print(f"{'ok  ' if not f else 'FAIL'} {vw}x{vh}  now: {m['now']}")
            for x in f:
                print(f"       {x}")
            pg.close()
        b.close()
    if shots:
        with open(os.path.join(shots, f"{tag}-findings.json"), "w") as fh:
            json.dump(bad, fh, indent=1)
    n = sum(len(v) for v in bad.values())
    print("PASS" if not n else f"FAIL ({n} findings)")
    return 0 if not n else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5199")
    ap.add_argument("--shots", default="")
    ap.add_argument("--tag", default="after")
    ap.add_argument("--sizes", default=SIZES)
    a = ap.parse_args()
    if a.shots:
        os.makedirs(a.shots, exist_ok=True)
    sys.exit(main(a.base, a.shots, a.tag, [tuple(map(int, s.split("x"))) for s in a.sizes.split(",")]))
