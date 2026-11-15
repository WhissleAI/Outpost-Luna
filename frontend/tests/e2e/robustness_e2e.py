"""Robustness matrix: SURFACE x CHANGE (docs/ROBUSTNESS.md).

The owner's bug (v1, 2026-11-15): a NASA video, then Settings -> Camera & gestures -> on, and the whole window became one
unstyled line, "Needs internet. Ask a grown-up to connect.", with nothing to press. The class: a mode or setting
changes while something modal or active is on screen, and the app ends up stuck, blank, unstyled or uncloseable.

For every SURFACE (something open or active) this applies every CHANGE (a mode / setting / environment change) and then
asserts the app is still healthy:
  * no unstyled or blank full window (the app chrome is there and styled, the body was not overwritten);
  * every open modal still has a visible Close and focus sits inside the top one (or on <body>);
  * no uncaught page errors;
  * the Mute button and prefs.muted agree;
  * at the end of each surface: Esc closes every modal, the three tabs work, and the voice bar is not stuck in
    "Speaking" / "Thinking".

Silent (frontend/tools/silent.py; headless, --mute-audio --disable-audio-output) with Chromium's FAKE camera only.

    cd frontend && npm run build
    (backend on :8201 serving frontend/dist, VIDEO_PREFETCH=0; models not needed)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/robustness_e2e.py --base http://127.0.0.1:8201 \
        [--restart-cmd "<kills and restarts the backend>"] [--only video_yt,settings] [--json out.json]
Exit 1 when any cell fails. Without --restart-cmd the "backend_restart" change is skipped.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright
import os as _os, sys as _sys  # noqa: E401
_d = _os.path.dirname(_os.path.abspath(__file__))
_sys.path[:0] = [_d, _os.path.join(_d, "..", "..", "tools")]
import silent  # noqa: E402,F401  (owner rule: every browser run is muted and headless; frontend/tools/silent.py)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "gestures"
# YouTube's own player script (inside the cross-origin embed) throws this now and then; not our code
IGNORE_PAGEERR = ("isExternalMethodAvailable",)
IGNORE = ("favicon", "/api/voices", "404 (Not Found)", "ERR_FILE_NOT_FOUND", "ERR_INTERNET_DISCONNECTED", "ERR_NETWORK_CHANGED",
          "ERR_CONNECTION_REFUSED", "WebSocket", "GL Driver", "GPU stall", "net::", "Failed to load resource")

SEED_KID = """try { if (!sessionStorage.getItem('rb')) { localStorage.clear(); sessionStorage.setItem('rb', '1');
  localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('outpost-tour-done:Nova', '1');
  localStorage.setItem('outpost-prep-seen', JSON.stringify(['comms', 'radiation', 'moon'])); } } catch (e) {}
  window.__outpostTest = true;"""
SEED_QUALIFIED = """try { if (!sessionStorage.getItem('rbq')) { sessionStorage.setItem('rbq', '1');
  localStorage.setItem('atm-academy', JSON.stringify({badges: ['scout','history','radio','sun','storm','ice','commander'], qualified: true}));
  localStorage.setItem('atm-mode', 'mission'); localStorage.setItem('outpost-tour-done:Nova', '1'); } } catch (e) {}
  window.__hourMs = 2000; window.__missionSeed = 2;"""

# ---------------------------------------------------------------- the health check ----------------------------------
HEALTH = r"""() => {
  const vis = e => !!(e && e.isConnected && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' && !e.closest('[hidden]'));
  const need = ['modeAcademy', 'modeMission', 'libraryBtn', 'a11yBtn', 'stage', 'askbar'];
  const missing = need.filter(id => !document.getElementById(id));
  const gear = document.getElementById('a11yBtn'), cs = gear && getComputedStyle(gear);
  const styled = !!(cs && document.styleSheets.length > 0 && getComputedStyle(document.body).fontFamily.indexOf('Times') < 0 && cs.display !== 'inline');
  const modals = [...document.querySelectorAll('dialog[open], [role=dialog][aria-modal=true]:not([hidden]), .gx-calib')].filter(vis);
  const closer = m => [...m.querySelectorAll('button, [role=button]')].some(b => vis(b) &&
    /close|done|skip|cancel|not now|back|no thanks|×|^x$/i.test(((b.getAttribute('aria-label') || '') + ' ' + b.textContent).trim()));
  const noClose = modals.filter(m => !closer(m)).map(m => m.id || String(m.className).slice(0, 30));
  // a native modal <dialog> is in the top layer: it is on top of every plain-element modal, whatever the DOM order,
  // and those underneath are inert (the kid can't touch them)
  const native = modals.filter(m => m.tagName === 'DIALOG');
  const under = native.length ? modals.filter(m => m.tagName !== 'DIALOG').map(m => m.id || String(m.className).slice(0, 30)) : [];
  const a = document.activeElement, top = native.length ? native[native.length - 1] : modals[modals.length - 1];
  const focusOk = !a || a === document.body || (a.isConnected && (!top || top.contains(a) || (a.tagName === 'IFRAME' && top.contains(a))));
  const bodyText = (document.body.innerText || '').trim();
  const wiped = document.body.children.length < 5;
  const P = (window.__outpost && window.__outpost.prefs) || {}, mb = document.getElementById('muteBtn');
  const muteOk = !mb || (mb.getAttribute('aria-pressed') === String(!!P.muted));
  const ab = document.getElementById('askbar');
  return { missing, styled, wiped, modals: modals.map(m => m.id || String(m.className).slice(0, 30)), under, noClose, focusOk,
    focus: a ? (a.id || a.tagName + '.' + String(a.className).slice(0, 20)) : '', muteOk, muted: !!P.muted,
    askbar: ab ? ab.className : '', text: bodyText.slice(0, 80), mode: document.body.dataset.mode || '' };
}"""


def problems(h, errs):
    out = []
    if h["missing"]:
        out.append(f"app chrome missing {h['missing']}")
    if h["wiped"]:
        out.append(f"body overwritten: {h['text']!r}")
    if not h["styled"]:
        out.append("unstyled")
    if h["under"]:
        out.append(f"inert under the video <dialog>: {h['under']}")
    if h["noClose"]:
        out.append(f"modal without a Close {h['noClose']}")
    if not h["focusOk"]:
        out.append(f"focus outside the top modal ({h['focus']} vs {h['modals']})")
    if not h["muteOk"]:
        out.append("Mute button and prefs.muted disagree")
    if errs:
        out.append("page errors: " + " | ".join(e[:120] for e in errs[:3]))
    return out


# ---------------------------------------------------------------- helpers ---------------------------------------------
def fixture(name):
    return json.loads((FIX / f"{name}.json").read_text())["frames"]


class Run:
    def __init__(self, pg, ctx, args, errs):
        self.pg, self.ctx, self.a, self.errs = pg, ctx, args, errs
        self.cursor = 0
        self.offline_route = False

    js = property(lambda self: self.pg.evaluate)

    def wait(self, ms):
        self.pg.wait_for_timeout(ms)

    def until(self, expr, timeout=8000):
        end = time.time() + timeout / 1000
        while time.time() < end:
            try:
                if self.pg.evaluate(expr):
                    return True
            except Exception:
                pass
            self.wait(200)
        return False

    def click(self, sel, double=False):
        """A real (trusted) mouse click at the control's centre. Playwright's own click waits for the element to be
        "stable" over animation frames, which the 3D cabin starves under SwiftShader; this is the same input."""
        self.pg.wait_for_selector(sel, state="visible", timeout=8000)
        box = self.js("s => { const q = document.querySelector(s).getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }", sel)
        (self.pg.mouse.dblclick if double else self.pg.mouse.click)(box[0], box[1])

    def modal_open(self):
        return self.js("() => !!document.querySelector('dialog[open]') || !!document.querySelector('.a11y-panel:not([hidden])') || !!document.querySelector('.gx-calib')")

    def inject(self, name):
        fs = fixture(name)
        base = self.cursor or 1_000_000
        shift = base - fs[0]["t"]
        self.cursor = fs[-1]["t"] + shift + 1500
        return self.js("([fs, dt]) => window.__outpost.gestures.inject(fs.map(f => ({...f, t: f.t + dt}))).map(e => e.type)", [fs, shift])

    def open_settings(self):
        if self.js("() => !!document.querySelector('.a11y-panel:not([hidden])')"):
            return True
        if self.modal_open():
            # a modal is up: the gear is inert / covered behind it, so the kid would say "settings"
            self.js("() => window.__outpost.shellNav('settings', null, 'settings')")
        else:
            self.click("#a11yBtn")
        return self.until("() => !!document.querySelector('.a11y-panel:not([hidden])')", 3000)

    def close_settings(self):
        if self.js("() => !!document.querySelector('.a11y-panel:not([hidden])')"):
            self.pg.keyboard.press("Escape")
            self.wait(300)

    def nav_tab(self, tab):
        ids = {"academy": "modeAcademy", "mission": "modeMission", "library": "libraryBtn"}
        if self.modal_open():
            self.js("t => window.__outpost.shellNav(t === 'mission' ? 'go_mission' : t, null, t)", tab)   # by voice
        else:
            self.click("#" + ids[tab])
        self.wait(700)


# ---------------------------------------------------------------- SURFACES ---------------------------------------------
# each: (name, needs_qualified, setup(r) -> bool, active(r) -> bool)
def video_open(vid):
    def setup(r):
        r.js(f"() => {{ window.__vres = null; window.__outpost.video.openVideo('{vid}', {{context: 'robustness'}}).then(x => window.__vres = x); }}")
        return r.until("() => !!(document.getElementById('vidDlg') && document.getElementById('vidDlg').open && document.querySelector('#vidDlg .vid-bar button'))", 10000)
    return setup


def l1_step(n):
    # L1 "Know your Moon": step 2 (Yes / No / Sometimes) or step 4 (the far side)
    def setup(r):
        r.js("() => window.__outpost.shellNav('lesson', 'moon', 'lesson moon')")
        if not r.until("() => window.__outpost.academyTest && window.__outpost.academyTest.where.view === 'lesson'", 10000):
            return False
        r.wait(500)
        r.js(f"() => window.__outpost.academyTest.step({n})")
        return r.until("() => document.querySelectorAll('#aPanel .a-choice').length > 0", 6000)
    return setup


def video_offline(r):
    r.pg.route("**/api/video/*/available", lambda route: route.fulfill(status=200, content_type="application/json", body='{"status":"offline"}'))
    try:
        return video_open("far_side_view")(r)
    finally:
        r.wait(300)
        r.pg.unroute("**/api/video/*/available")


VIDEO_ACTIVE = "() => !!(document.getElementById('vidDlg') && document.getElementById('vidDlg').open)"


def lesson(r):
    r.js("() => window.__outpost.shellNav('lesson', 'comms', 'lesson comms')")
    return r.until("() => !!document.querySelector('#aPanel:not([hidden]) .a-prompt')", 8000)


def prep(r):
    r.js("() => { try { localStorage.setItem('outpost-prep-seen', JSON.stringify(['comms','radiation'])); } catch (e) {} window.__outpost.shellNav('lesson', 'power', 'lesson power'); }")
    return r.until("() => document.getElementById('aPanel') && document.getElementById('aPanel').dataset.step === 'prep'", 8000)


def crew(r):
    r.js("() => window.__outpost.playCrew()")
    return r.until("() => !document.getElementById('nowPlaying').hidden", 8000)


def mission_choice(r):
    r.nav_tab("mission") if r.js("() => document.body.dataset.mode !== 'mission'") else None
    # a fresh mission shows Start; one already running (back from another tab) shows its Now card
    if not r.until("() => !!document.getElementById('mStart') || !!document.querySelector('.cb-now-btns .cb-now-b')", 25000):
        return False
    if not r.js("() => !!document.getElementById('mStart')"):
        return True
    r.wait(1200)
    r.js("() => document.getElementById('mStart').click()")
    if not r.until("() => !!document.querySelector('.cb-now-btns .cb-now-b')", 15000):
        return False
    r.js("() => { const p = document.getElementById('cbPlay'); if (p) p.click(); }")   # the clock running
    r.wait(800)
    return True


def storm(r):
    if not r.js("() => !!document.querySelector('.cb-now-btns .cb-now-b')") and not mission_choice(r):
        return False
    r.js("() => window.__cabinTest && window.__cabinTest.storm(true)")
    return r.until("() => !document.getElementById('mBanner').hidden || /storm/i.test(document.body.innerText)", 5000)


def debrief(r):
    if not r.js("() => !!window.__cabinTest") and not mission_choice(r):
        return False
    if not r.js("() => !!window.__cabinTest"):
        mission_choice(r)
    r.js("() => window.__cabinTest && window.__cabinTest.debrief('survived')")
    return r.until("() => !document.getElementById('mDebrief').hidden", 6000)


def settings(r):
    return r.open_settings()


def calibration(r):
    if not r.open_settings():
        return False
    r.click('[data-sec="camera"]')
    r.pg.wait_for_selector("#gxEnabled", timeout=4000)
    if not r.js("() => document.getElementById('gxEnabled').checked"):
        r.click("#gxEnabled")
    r.until("() => window.__outpost.gestures.active", 30000)
    if not r.until("() => !!document.querySelector('.gx-calib')", 4000):
        r.js("() => window.__outpost.gestures.calibrate && window.__outpost.gestures.calibrate()")
    return r.until("() => !!document.querySelector('.gx-calib')", 4000)


def gate(r):
    # the in-app half of the grown-up gate: a link out of the YouTube player is a window.open the shell turns into the
    # gate; in a browser it is a popup. The app itself must stay put and usable.
    if not video_open("far_side_view")(r):
        return False
    with r.ctx.expect_page(timeout=5000) as pop:
        r.js("() => window.open('https://www.youtube.com/watch?v=jdkMHkF7BaA', '_blank')")
    try:
        pop.value.close()
    except Exception:
        pass
    return r.js(VIDEO_ACTIVE)


def help_card(r):
    r.js("() => window.__outpost.gestures.showHelp()")
    return r.until("() => !!document.querySelector('.gx-help:not([hidden]), .gx-card:not([hidden])')", 4000)


def voicebar_listening(r):
    r.js("() => { const m = document.getElementById('mic'); if (m && !m.hidden) m.click(); }")
    return r.until("() => /is-listening|is-hearing/.test(document.getElementById('askbar').className)", 6000)


def after_video(r):
    # the owner's exact path: a video played and was closed, then the kid goes to Settings
    if not video_open("far_side_view")(r):
        return False
    r.wait(1500)
    r.pg.keyboard.press("Escape")
    ok = r.until("() => !document.getElementById('vidDlg').open", 3000)
    r.js("() => { window.__rbAfter = true; }")
    return ok


SURFACES = [
    ("after_video", False, after_video, lambda r: r.js("() => !!window.__rbAfter")),
    ("video_yt", False, video_open("far_side_view"), lambda r: r.js(VIDEO_ACTIVE)),
    ("video_file", False, video_open("psr"), lambda r: r.js(VIDEO_ACTIVE)),
    ("video_offline", False, video_offline, lambda r: r.js(VIDEO_ACTIVE)),
    ("l1_yes_no", False, l1_step(1), lambda r: r.js("() => !!document.querySelector('#aPanel .a-choice[data-c=sometimes]')")),
    ("l1_far_side", False, l1_step(3), lambda r: r.js("() => !!document.querySelector('#aPanel .g-side')")),
    ("lesson_step", False, lesson, lambda r: r.js("() => !!document.querySelector('#aPanel:not([hidden]) .a-prompt')")),
    ("prep_card", False, prep, lambda r: r.js("() => document.getElementById('aPanel').dataset.step === 'prep' && !document.getElementById('aPanel').hidden")),
    ("crew_clip", False, crew, lambda r: r.js("() => !document.getElementById('nowPlaying').hidden")),
    ("mission_choice", True, mission_choice, lambda r: r.js("() => !!document.querySelector('.cb-now-btns .cb-now-b')")),
    ("storm_alert", True, storm, lambda r: r.js("() => document.body.dataset.mode === 'mission' && /storm/i.test(document.body.innerText)")),
    ("debrief", True, debrief, lambda r: r.js("() => !document.getElementById('mDebrief').hidden")),
    ("settings", False, settings, lambda r: r.js("() => !!document.querySelector('.a11y-panel:not([hidden])')")),
    ("calibration", False, calibration, lambda r: r.js("() => !!document.querySelector('.gx-calib')")),
    ("grownup_gate", False, gate, lambda r: r.js(VIDEO_ACTIVE)),
    ("help_card", False, help_card, lambda r: r.js("() => !!document.querySelector('.gx-help:not([hidden]), .gx-card:not([hidden])')")),
    ("voicebar_listening", False, voicebar_listening, lambda r: r.js("() => /is-listening|is-hearing/.test(document.getElementById('askbar').className)")),
]


# ---------------------------------------------------------------- CHANGES ----------------------------------------------
def ch_camera_on(r):
    if r.modal_open():
        r.js("() => window.__outpost.gestures.enable()")   # behind a modal: the shortest real path (Settings is covered)
    else:
        r.open_settings()
        r.click('[data-sec="camera"]')
        r.pg.wait_for_selector("#gxEnabled", timeout=4000)
        if not r.js("() => document.getElementById('gxEnabled').checked"):
            r.click("#gxEnabled")
    r.until("() => window.__outpost.gestures.active", 30000)
    r.until("() => !!document.querySelector('.gx-calib')", 2500)
    # the first-time calibration may open by itself: it is a modal too (checked by the health check), then skipped
    r.js("() => { const s = [...document.querySelectorAll('.gx-calib button')].find(b => /skip|not now|later/i.test(b.textContent)); if (s) s.click(); }")
    r.close_settings()


def ch_camera_off(r):
    r.js("() => window.__outpost.gestures.disable()")
    r.wait(500)


def ch_settings(r):
    if not r.open_settings():
        raise RuntimeError("Settings did not open")
    secs = r.js("() => [...document.querySelectorAll('.a11y-panel .set-nav [data-sec]')].map(b => b.dataset.sec)")
    for s in secs:
        r.click(f'.a11y-panel [data-sec="{s}"]')
        r.wait(150)
        # every switch, choice and slider in the section (never a button: no resets, no profile changes)
        r.js("""() => { const p = document.querySelector('.a11y-panel');
          for (const i of [...p.querySelectorAll('input[type=checkbox]')].filter(i => i.id !== 'gxEnabled' && !i.disabled)) { i.click(); i.click(); }
          const radios = {}; for (const i of p.querySelectorAll('input[type=radio]:not(:disabled)')) (radios[i.name] = radios[i.name] || []).push(i);
          for (const g of Object.values(radios)) { const was = g.find(i => i.checked), other = g.find(i => !i.checked); if (other) { other.click(); if (was) was.click(); } }
          for (const i of p.querySelectorAll('input[type=range]:not(:disabled)')) { const v = i.value; i.value = i.max; i.dispatchEvent(new Event('input', {bubbles: true})); i.dispatchEvent(new Event('change', {bubbles: true}));
            const again = p.querySelector(`input[type=range][data-p="${i.dataset.p}"], input[type=range][data-k="${i.dataset.k}"]`) || i; again.value = v; again.dispatchEvent(new Event('change', {bubbles: true})); }
          for (const sl of p.querySelectorAll('select:not(:disabled)')) { const v = sl.value; if (sl.options.length > 1) { sl.selectedIndex = (sl.selectedIndex + 1) % sl.options.length; sl.dispatchEvent(new Event('change', {bubbles: true})); sl.value = v; sl.dispatchEvent(new Event('change', {bubbles: true})); } } }""")
        r.wait(150)
    r.close_settings()


def ch_mute_key(r):
    for _ in range(2):
        r.pg.keyboard.press("Shift+M")
        r.wait(300)


def ch_mute_btn(r):
    for _ in range(2):
        if r.modal_open():
            r.js("() => document.getElementById('muteBtn').click()")   # inert behind a modal: the shortcut's path
        else:
            r.click("#muteBtn")
        r.wait(300)


def ch_theme(r):
    for _ in range(2):
        if r.modal_open():
            r.js("() => document.getElementById('themeBtn').click()")
        else:
            r.click("#themeBtn")
        r.wait(300)


def ch_offline(r):
    r.ctx.set_offline(True)
    r.js("() => dispatchEvent(new Event('offline'))")
    r.wait(1500)
    r.ctx.set_offline(False)
    r.js("() => dispatchEvent(new Event('online'))")
    r.wait(1500)


def ch_resize(r):
    r.pg.set_viewport_size({"width": 1024, "height": 640})
    r.wait(700)
    r.pg.set_viewport_size({"width": 1280, "height": 800})
    r.wait(500)


def ch_tabs(r):
    for t in ("academy", "mission", "library", "academy"):
        r.nav_tab(t)


def ch_esc(r):
    r.pg.keyboard.press("Escape")
    r.wait(500)


def ch_voice(text):
    def f(r):
        r.js("t => window.__outpost.hear(t)", text)
        r.wait(1500)
        if text == "mute":
            r.js("() => window.__outpost.hear('unmute')")
            r.wait(400)
    return f


def ch_gestures(r):
    for g in ("palm_hold", "thumbs_down", "swipe_left"):
        r.inject(g)
        r.wait(400)


def ch_thumbs(r):
    for g in ("thumbs_up", "thumbs_down"):
        r.inject(g)
        r.wait(700)


def ch_fingers(r):
    fs = json.loads(subprocess.check_output(["node", str(Path(__file__).resolve().parent / "frames.mjs"), "hold", "three", "1300"],
                                            cwd=Path(__file__).resolve().parents[2]))
    base = (r.cursor or 1_000_000) + 1500
    shift = base - fs[0]["t"]
    r.cursor = fs[-1]["t"] + shift + 1500
    r.js("([fs, dt]) => window.__outpost.gestures.inject(fs.map(f => ({...f, t: f.t + dt}))).length", [fs, shift])
    r.wait(900)


def ch_backend_restart(r):
    subprocess.run(r.a.restart_cmd, shell=True, check=True, timeout=120)
    r.until("() => fetch('/api/video/catalog').then(x => x.ok).catch(() => false)", 60000)
    r.wait(4000)


def ch_visibility(r):
    for state in ("hidden", "visible"):
        r.js("s => { Object.defineProperty(document, 'visibilityState', {value: s, configurable: true}); Object.defineProperty(document, 'hidden', {value: s === 'hidden', configurable: true}); document.dispatchEvent(new Event('visibilitychange')); }", state)
        r.wait(800)


def ch_reset(r):
    # Settings -> Reset -> Start over, held 3 s, while the surface is open (docs/RESET.md): the app must come back fresh
    # at first launch with its chrome, never half-reset. Voice opens the confirm (a modal may cover the gear).
    r.js("() => window.__outpost.a11y.handleText('reset')")
    if not r.until("() => !!document.querySelector('.rs-confirm [data-reset-hold]')", 6000):
        raise RuntimeError("the reset confirm did not open")
    box = r.js("() => { const q = document.querySelector('[data-reset-hold]').getBoundingClientRect(); return [q.x + q.width / 2, q.y + q.height / 2]; }")
    r.pg.mouse.move(*box)
    r.pg.mouse.down()
    r.wait(3400)
    r.pg.mouse.up()
    r.until("() => document.readyState === 'complete' && window.__outpost && window.__outpost.shellNav && !!document.getElementById('aCsForm')", 30000)
    r.wait(1000)
    if r.js("() => Object.keys(localStorage).some(k => /^(outpost-callsign|atm-academy)$/.test(k))"):
        raise RuntimeError("progress survived the reset")


def ch_double(r):
    # a double press of whatever is focused, and of the tab buttons
    r.pg.keyboard.press("Enter")
    r.pg.keyboard.press("Enter")
    r.wait(1200)   # a double Enter can open something (the next step's video): let it land before looking
    if not r.modal_open():
        r.click("#modeAcademy", double=True)
    else:
        r.js("() => document.getElementById('modeAcademy').dispatchEvent(new MouseEvent('dblclick', {bubbles: true}))")
        r.wait(600)


CHANGES = [
    ("camera_on", ch_camera_on), ("camera_off", ch_camera_off), ("settings_change", ch_settings), ("mute_key", ch_mute_key),
    ("mute_btn", ch_mute_btn), ("theme", ch_theme), ("offline_online", ch_offline), ("resize", ch_resize), ("tabs", ch_tabs),
    ("esc", ch_esc), ("voice_stop", ch_voice("stop")), ("voice_map", ch_voice("go to the map")), ("voice_mute", ch_voice("mute")),
    ("gestures", ch_gestures), ("thumbs", ch_thumbs), ("fingers", ch_fingers), ("backend_restart", ch_backend_restart), ("visibility", ch_visibility), ("double_press", ch_double),
    ("reset", ch_reset),   # last: it erases the row's seeded state
]


# ---------------------------------------------------------------- the end of a surface ----------------------------------
FINAL_ESC = """() => [...document.querySelectorAll('dialog[open], [role=dialog][aria-modal=true]:not([hidden]), .gx-calib')]
  .filter(e => e.getClientRects().length).map(e => e.id || String(e.className).slice(0, 30))"""


def final_checks(r):
    out = []
    for _ in range(4):
        if not r.js(FINAL_ESC):
            break
        r.pg.keyboard.press("Escape")
        r.wait(400)
    left = r.js(FINAL_ESC)
    if left:
        out.append(f"Esc does not close {left}")
    for t, want in (("academy", "academy"), ("library", "cadet"), ("mission", "mission")):
        try:
            r.nav_tab(t)
        except Exception as e:  # noqa: BLE001
            out.append(f"tab {t} not reachable: {str(e)[:80]}")
            continue
        if not r.until(f"() => document.body.dataset.mode === '{want}'", 4000):
            out.append(f"tab {t} did not switch (mode {r.js('() => document.body.dataset.mode')})")
    if not r.until("() => !/is-speaking|is-thinking/.test(document.getElementById('askbar').className)", 40000):   # a long debrief line is legit (floor.js: 2.5 s + 0.5 s a word)
        out.append("voice bar stuck: " + r.js("() => document.getElementById('askbar').className"))
    return out


# ---------------------------------------------------------------- main -------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8201")
    ap.add_argument("--restart-cmd", default="", help="a shell command that kills and restarts the backend (else that change is skipped)")
    ap.add_argument("--only", default="", help="comma-separated surfaces")
    ap.add_argument("--changes", default="", help="comma-separated changes")
    ap.add_argument("--json", default="", help="write the matrix here")
    ap.add_argument("--shots", default="", help="screenshot each failing cell here")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    only = set(filter(None, a.only.split(",")))
    want_ch = set(filter(None, a.changes.split(",")))
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    matrix: dict[str, dict[str, str]] = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                                                         "--enable-unsafe-swiftshader", "--autoplay-policy=no-user-gesture-required"])
        for name, qual, setup, active in SURFACES:
            if only and name not in only:
                continue
            row = matrix.setdefault(name, {})
            ctx = b.new_context(viewport={"width": 1280, "height": 800})
            ctx.add_init_script(SEED_KID)
            if qual:
                ctx.add_init_script(SEED_QUALIFIED)
            silence(ctx)
            pg = ctx.new_page()
            errs: list[str] = []
            pg.on("pageerror", lambda e, errs=errs: None if any(x in str(e) for x in IGNORE_PAGEERR) else errs.append(str(e)))
            pg.on("console", lambda m, errs=errs: m.type == "error" and not any(x in m.text for x in IGNORE) and errs.append("console: " + m.text))
            r = Run(pg, ctx, a, errs)
            try:
                pg.goto(base + "/")
                r.until("() => window.__outpost && window.__outpost.video && window.__outpost.gestures && window.__outpost.shellNav", 30000)
                r.wait(1500)
                if qual:
                    r.nav_tab("mission")
                for cname, change in CHANGES:
                    if want_ch and cname not in want_ch:
                        continue
                    if cname == "backend_restart" and not a.restart_cmd:
                        row[cname] = "skip"
                        continue
                    errs.clear()
                    try:
                        if not active(r) and not setup(r):
                            row[cname] = "skip: surface did not open"
                            print(f"SKIP {name} x {cname}: surface did not open", flush=True)
                            continue
                        change(r)
                        r.wait(600)
                        h = pg.evaluate(HEALTH)
                        bad = problems(h, errs)
                    except Exception as e:  # noqa: BLE001
                        lines = str(e).splitlines()
                        why = [x.strip() for x in lines if any(k in x for k in ("intercepts pointer", "not stable", "not visible", "not enabled", "outside of the viewport"))]
                        bad = [f"exception: {lines[0][:160]}" + (f" ({why[-1][:160]})" if why else "")]
                        try:
                            bad += problems(pg.evaluate(HEALTH), errs)
                        except Exception:
                            pass
                    row[cname] = "pass" if not bad else "FAIL: " + "; ".join(bad)
                    print(("PASS " if not bad else "FAIL ") + f"{name} x {cname}" + ("" if not bad else "  -> " + "; ".join(bad)), flush=True)
                    if bad and a.shots:
                        os.makedirs(a.shots, exist_ok=True)
                        pg.screenshot(path=os.path.join(a.shots, f"{name}__{cname}.png"))
                    if bad and h_wiped(pg):
                        # the app is gone: reload so the rest of the row still means something
                        pg.reload()
                        r.until("() => window.__outpost && window.__outpost.shellNav", 30000)
                        r.wait(1200)
                        if qual:
                            r.nav_tab("mission")
                errs.clear()
                fin = final_checks(r) + problems(pg.evaluate(HEALTH), errs)
                row["final"] = "pass" if not fin else "FAIL: " + "; ".join(fin)
                print(("PASS " if not fin else "FAIL ") + f"{name} x final (Esc closes all, tabs, voice bar)" + ("" if not fin else "  -> " + "; ".join(fin)), flush=True)
            except Exception:  # noqa: BLE001
                row["setup"] = "FAIL: " + traceback.format_exc().splitlines()[-1][:200]
                print(f"FAIL {name}: {row['setup']}", flush=True)
            finally:
                ctx.close()
        b.close()
    cells = [(s, c, v) for s, row in matrix.items() for c, v in row.items()]
    n_pass = sum(v == "pass" for _, _, v in cells)
    n_fail = sum(v.startswith("FAIL") for _, _, v in cells)
    n_skip = len(cells) - n_pass - n_fail
    print(f"\nmatrix: {n_pass} pass, {n_fail} fail, {n_skip} skipped of {len(cells)} cells")
    if a.json:
        Path(a.json).write_text(json.dumps(matrix, indent=1))
    sys.exit(1 if n_fail else 0)


def h_wiped(pg):
    try:
        return pg.evaluate("() => document.body.children.length < 5 || !document.getElementById('a11yBtn')")
    except Exception:
        return True


if __name__ == "__main__":
    main()
