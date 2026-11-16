"""A first-time player flies the first mission, start to finish, and logs every moment (docs/GAMEPLAY.md §Verify).

The novice knows nothing about the sim. It only reads the screen like a kid would:
  * a tour card -> press its Next;
  * the Now card -> read it, then press the card's hot (first) button; a choice -> press the first option;
  * the glowing control (.is-point) -> note it (is the thing to do lit up and on screen?);
  * a CAPCOM yes/no -> press Yes.
For each moment it logs what the kid should do (the card), whether that is OBVIOUS (a hot button or a glowing control
is visible, on screen and not covered: elementFromPoint at its centre is the control) and whether the app REACTED (the
card moved on, an acknowledgement showed, or the clock moved). Screenshots of each new task, beat and the debrief go to
--shots. The clock runs on the real HOUR_MS for the first shift (to time it), then faster (dev hook window.__hourMs)
with the in-game time warp.

  uv run --with playwright python frontend/tools/play_mission.py --base http://127.0.0.1:5310 --level cadet \
      --sizes 1280x720,1440x900 --shots docs/img/gameplay --log docs/img/gameplay
"""
import argparse
import glob
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

SEED = """try{ localStorage.clear(); localStorage.setItem('atm-theme','dark'); localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('atm-mode','mission'); localStorage.setItem('outpost-prefs', JSON.stringify({level:'%s', graphics:'%s'}));
  window.__hourMs = %s; }catch(e){}"""

# What a kid sees: the Now card, its buttons, the glow, the clock, any tour / confirm, the progress strip.
LOOK = """() => {
  const vis = e => !!(e && !e.hidden && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const clear = e => { if (!vis(e)) return false; const r = e.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2;
    if (x < 0 || y < 0 || x > innerWidth || y > innerHeight) return false; const h = document.elementFromPoint(x, y); return !!(h && (h === e || e.contains(h))); };
  const now = document.querySelector('#cbNow'), ui = window.__outpost && window.__outpost.missionUI;
  const btns = [...document.querySelectorAll('.cb-now-btns .cb-now-b')].filter(vis);
  const glow = [...document.querySelectorAll('.is-point')].filter(vis);
  const tour = document.querySelector('.m-tour:not([hidden])');
  const card = document.querySelector('#card:not([hidden])');
  const cardBtns = card ? [...card.querySelectorAll('button.pill:not([disabled])')].filter(vis).map(b => b.textContent.trim()) : [];
  const debrief = document.querySelector('#mDebrief:not([hidden]) .mx-title');
  const offer = [...document.querySelectorAll('.cb-offer-b')].filter(vis).map(b => b.textContent.trim());
  return { tour: tour ? (tour.querySelector('.t-text') || {}).textContent : null,
    now: vis(now) ? { title: (now.querySelector('.cb-now-title') || {}).textContent || '', text: (now.querySelector('#cbNowT') || {}).textContent || '',
      ack: ((now.querySelector('.cb-now-ack') || {}).textContent || '').trim(), meta: ((now.querySelector('.cb-now-meta') || {}).textContent || '').trim(),
      buttons: btns.map(b => b.childNodes[0].textContent.trim()), hotClear: btns.length ? clear(btns[0]) : null } : null,
    glow: glow.map(g => g.id || g.className.split(' ')[0]), glowClear: glow.some(clear),
    clock: (document.querySelector('#cbClock') || {}).textContent || '', held: (document.querySelector('#cbHeld') || {}).textContent || '',
    prog: ((document.querySelector('#cbProg') || {}).textContent || '').replace(/\\s+/g, ' ').trim(),
    capcom: cardBtns, offer, debrief: debrief ? debrief.textContent : null,
    moment: (() => { const m = document.querySelector('.cb-moment:not([hidden]) b'); return m ? m.textContent : null; })() };
}"""


def chromium():
    return (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]


def click(pg, sel, idx=0):
    """A real mouse click at the control's centre, after a hit test: what a kid's mouse would land on. (The cabin's
    window HUD follows the 3D camera, so Playwright's "stable" check can stall; the hit test is the honest check.)
    Falls back to a DOM click, and says so, only when something else is on top."""
    hit = pg.evaluate("""([s, i]) => { const e = document.querySelectorAll(s)[i]; if (!e) return null; e.scrollIntoView({block: 'nearest'});
      const r = e.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2, h = document.elementFromPoint(x, y);
      return { x, y, ok: !!(h && (h === e || e.contains(h))), on: h ? h.tagName + '.' + String(h.className).split(' ')[0] : null }; }""", [sel, idx])
    if hit and hit["ok"]:
        pg.mouse.click(hit["x"], hit["y"])
        return "click"
    pg.evaluate("([s, i]) => { const e = document.querySelectorAll(s)[i]; if (e) e.click(); }", [sel, idx])
    return f"dom-click (covered by {hit and hit['on']})"


def play(base, level, size, shots, fast_ms, real_first_shift, max_s, graphics="high"):
    vw, vh = size
    log, seen_keys, shots_taken = [], set(), 0
    t0 = time.time()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chromium(), args=["--mute-audio", "--autoplay-policy=no-user-gesture-required", "--use-gl=angle", "--use-angle=swiftshader"])
        pg = b.new_page(viewport={"width": vw, "height": vh})
        pg.set_default_timeout(120000)
        pg.add_init_script(SEED % (level, graphics, "0" if real_first_shift else fast_ms))
        pg.goto(base)
        pg.wait_for_selector("#mStart")
        pg.wait_for_timeout(1500)
        tag = f"{level}-{vw}x{vh}"

        def shot(name):
            nonlocal shots_taken
            if shots and shots_taken < 40:
                shots_taken += 1
                safe = re.sub(r'[<>:"/\\|?*]', "", name)   # a valid file name on Windows too (git can't check out "?")
                pg.screenshot(path=os.path.join(shots, f"{tag}-{shots_taken:02d}-{safe}.jpg"), type="jpeg", quality=60, timeout=300000)

        # the first-mission briefing may offer NASA's Moon Base video over the site picker (it appears a few seconds in):
        # a novice skips it, then presses the big Take command at the suggested site
        t_pick, steps = time.time(), []
        VIS = "(s) => { const e = document.querySelector(s); return !!(e && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden'); }"
        while time.time() - t_pick < 90:
            if pg.evaluate(VIS, ".cb-now") or pg.evaluate(VIS, ".m-tour:not([hidden])"):
                break
            if pg.evaluate(VIS, "#mlSkip, [data-skip]"):
                steps.append("skip video: " + click(pg, "#mlSkip, [data-skip]"))
            elif pg.evaluate(VIS, "#mStart"):
                steps.append("take command: " + click(pg, "#mStart"))
            pg.wait_for_timeout(1500)
        pg.wait_for_selector(".cb-now:not([hidden]), .m-tour:not([hidden])", timeout=60000)
        log.append({"t": round(time.time() - t0), "moment": "picker", "should": "Take command at the suggested site",
                    "obvious": True, "reacted": True, "seen": f"cabin after {time.time() - t_pick:.1f}s; " + "; ".join(steps)})
        pg.wait_for_timeout(1200)
        shot("arrival")
        first_shift_t, sped = None, not real_first_shift
        last_key, idle = None, 0
        while time.time() - t0 < max_s:
            v = pg.evaluate(LOOK)
            if v["debrief"]:
                log.append({"t": round(time.time() - t0), "moment": "debrief", "should": "Read the debrief; Fly again", "obvious": True,
                            "reacted": True, "seen": v["debrief"]})
                pg.wait_for_timeout(2500)
                shot("debrief")
                break
            if v["tour"]:
                log.append({"t": round(time.time() - t0), "moment": "tour", "should": v["tour"], "obvious": bool(v["glow"]),
                            "action": click(pg, ".m-tour .t-next"), "reacted": True})
                pg.wait_for_timeout(700)
                if not pg.evaluate(LOOK)["tour"]:
                    shot("after-tour")
                continue
            if v["capcom"] and any(x in ("Yes",) for x in v["capcom"]):
                log.append({"t": round(time.time() - t0), "moment": "confirm", "should": "Answer CAPCOM: Yes", "obvious": True,
                            "action": click(pg, "#card button.pill", 0), "reacted": True})
                pg.wait_for_timeout(600)
                continue
            if v["offer"]:   # Cadet: CAPCOM's offer opened its panel with two big buttons; take the lit one
                log.append({"t": round(time.time() - t0), "clock": v["clock"], "task": "CAPCOM offer", "should": " / ".join(v["offer"]),
                            "buttons": v["offer"], "obvious": True, "action": f"{click(pg, '.cb-offer-b', 0)}: {v['offer'][0]}"})
                pg.wait_for_timeout(900)
                a2 = pg.evaluate(LOOK)
                log[-1]["reacted"] = not a2["offer"] or a2["clock"] != v["clock"]
                log[-1]["next"] = (a2["now"] or {}).get("text", "")
                continue
            n = v["now"]
            hour = v["clock"]
            if not sped and "Shift 2" in hour:
                first_shift_t = round(time.time() - t0)
                pg.evaluate(f"window.__hourMs = {fast_ms}")   # the clock reads it every tick (dev builds only)
                sped = True
            if not n:
                idle += 1
                pg.wait_for_timeout(500)
                continue
            key = (n["title"], n["text"], tuple(n["buttons"]))
            if key == last_key and not n["buttons"]:
                pg.wait_for_timeout(400)
                continue
            if not n["buttons"]:
                # the Now panel points at a deck control (Skip ahead / Play / the speed): a kid presses the glowing one
                lit = pg.evaluate("() => { const e = document.querySelector('.cb-deck .is-point'); if (!e) return null; const b = e.matches('button') ? e : e.querySelector('button:not([aria-pressed=\"true\"])') || e.querySelector('button'); if (!b) return null; b.dataset.lit = '1'; return b.textContent.trim(); }")
                if lit:
                    before = pg.evaluate(LOOK)
                    act = click(pg, "[data-lit='1']", 0)
                    pg.evaluate("() => document.querySelectorAll('[data-lit]').forEach(e => delete e.dataset.lit)")
                    pg.wait_for_timeout(900)
                    after = pg.evaluate(LOOK)
                    na = after["now"] or {}
                    log.append({"t": round(time.time() - t0), "clock": hour, "task": n["title"] or "Now", "should": n["text"], "meta": n["meta"],
                                "buttons": [lit], "glow": v["glow"], "obvious": bool(v["glowClear"]), "glow_on_screen": v["glowClear"],
                                "action": f"{act}: {lit} (deck)", "reacted": after["clock"] != before["clock"] or (na.get("text") != n["text"]),
                                "ack": na.get("ack") or "", "next": na.get("text") or "", "progress": after["prog"], "moment_shown": after["moment"]})
                    continue
                pg.wait_for_timeout(400)
                last_key = key
                continue
            before = pg.evaluate(LOOK)
            act = click(pg, ".cb-now-btns .cb-now-b", 0)
            pg.wait_for_timeout(900)
            after = pg.evaluate(LOOK)
            na = after["now"] or {}
            reacted = (after["debrief"] is not None or (na.get("text"), tuple(na.get("buttons", []))) != (n["text"], tuple(n["buttons"]))
                       or bool(na.get("ack")) or after["clock"] != before["clock"] or bool(after["capcom"]))
            entry = {"t": round(time.time() - t0), "clock": hour, "task": n["title"] or "Now", "should": n["text"], "meta": n["meta"],
                     "buttons": n["buttons"], "glow": v["glow"], "obvious": bool(n["hotClear"]) and bool(v["glow"]) or bool(n["hotClear"]),
                     "glow_on_screen": v["glowClear"], "action": f"{act}: {n['buttons'][0]}", "reacted": reacted,
                     "ack": na.get("ack") or "", "next": na.get("text") or "", "progress": after["prog"], "moment_shown": after["moment"]}
            log.append(entry)
            k2 = (n["title"] or n["text"])
            if k2 not in seen_keys:
                seen_keys.add(k2)
                shot((n["title"] or n["text"]).lower().replace(" ", "-").replace(":", "")[:28])
            if after["moment"]:
                shot("moment-" + after["moment"].lower().replace(" ", "-"))
            last_key = key
            same = [e for e in log[-10:] if e.get("action") == entry["action"] and e.get("should") == entry["should"]
                    and e.get("progress") == entry["progress"]]
            if len(same) >= 10:   # the same press ten times and the mission didn't move (days, science, ice): stuck
                log.append({"t": round(time.time() - t0), "moment": "STUCK", "obvious": False, "reacted": False,
                            "should": entry["should"], "action": "gave up", "clock": hour})
                shot("stuck")
                break
        else:
            log.append({"moment": "timeout", "obvious": False, "reacted": False, "should": f"mission not finished in {max_s}s"})
        b.close()
    return log, first_shift_t


def summary(log):
    acts = [e for e in log if "action" in e and e.get("moment") != "tour"]
    return {"moments": len(log), "actions": len(acts), "obvious": sum(1 for e in acts if e.get("obvious")),
            "reacted": sum(1 for e in acts if e.get("reacted")), "finished": any(e.get("moment") == "debrief" for e in log),
            "unclear": [e for e in acts if not e.get("obvious") or not e.get("reacted")][:12]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5310")
    ap.add_argument("--level", default="cadet")
    ap.add_argument("--sizes", default="1280x720,1440x900")
    ap.add_argument("--shots", default="")
    ap.add_argument("--log", default="")
    ap.add_argument("--fast-ms", type=int, default=900, help="ms per sim hour after the first shift (dev hook)")
    ap.add_argument("--real-first-shift", action="store_true", help="time the first shift on the shipped clock")
    ap.add_argument("--max-s", type=int, default=900)
    ap.add_argument("--graphics", default="high", choices=["high", "low"], help="Settings -> graphics (low: a slow PC)")
    a = ap.parse_args()
    for d in (a.shots, a.log):
        if d:
            os.makedirs(d, exist_ok=True)
    ok = True
    for sz in a.sizes.split(","):
        size = tuple(map(int, sz.split("x")))
        log, fst = play(a.base, a.level, size, a.shots, a.fast_ms, a.real_first_shift, a.max_s, a.graphics)
        s = summary(log)
        print(f"== {a.level} {sz}: {s['actions']} actions, {s['obvious']} obvious, {s['reacted']} reacted, finished={s['finished']}"
              + (f", first shift took {fst}s of real time" if fst else ""))
        for e in log:
            if "action" in e and e.get("moment") != "tour":
                print(f"  [{'clear' if e['obvious'] and e['reacted'] else 'CONFUSING'}] {e.get('clock', '')[:22]:22} {e.get('task', '')}: "
                      f"{e['should']} -> {e['action']} -> {e.get('ack') or e.get('next', '')}")
        if a.log:
            with open(os.path.join(a.log, f"playthrough-{a.level}-{sz}.json"), "w") as f:
                json.dump({"level": a.level, "size": sz, "first_shift_s": fst, "summary": {k: v for k, v in s.items() if k != "unclear"},
                           "log": log}, f, indent=1)
        ok = ok and s["finished"] and s["obvious"] == s["actions"] and s["reacted"] == s["actions"]
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)
