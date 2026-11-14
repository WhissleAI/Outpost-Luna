"""UX audit 2 (docs/AUDIT_2.md): "act, then check the app noticed".

Drives the real app headless and, for every action a kid could take, records what the screen showed before, 1 s after
and once settled: the instruction lines (prompt, do-line, feedback, map beat, patch line, the cabin's Now strip), the
voice bar (state, words, caption), the cards, toasts and sheets. A moment is flagged when

  - nothing visible changed within 1 s of the action ("no reaction"),
  - an instruction line on screen is word-for-word the same after an action that did what it asked ("stale"),
  - the same line was spoken twice in a row ("said twice").

  uv run --with playwright --with pillow python frontend/tools/ux_audit2.py --base http://localhost:5311 --out /tmp/a2 [--only first,lessons,...]

Writes <out>/log.json, <out>/*.jpg (640 px wide) and prints the flagged moments. Exit 1 on console errors.
"""
import argparse
import glob
import io
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from ux_shots import COURSE, answer_for, _Vocab  # noqa: E402

IGNORE = ("favicon", "/api/voices", "404 (Not Found)", "WebSocket", "ws/", "ERR_ABORTED", "Failed to load resource", "net::ERR")

PROBE = r"""() => {
  const vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' && +getComputedStyle(e).opacity > 0.05 && !e.closest('[hidden]');
  const T = e => (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
  const all = s => [...document.querySelectorAll(s)].filter(vis).map(T).filter(Boolean);
  const one = s => { const e = document.querySelector(s); return e && vis(e) ? T(e) : ''; };
  const bar = document.getElementById('askbar'), cap = document.getElementById('captionBar');
  const O = window.__outpost || {}; let c = null; try { c = O.globe.centerLatLon(); } catch (e) {}
  const ab = document.getElementById('about');
  return {
    mode: document.body.dataset.mode || '', aview: document.body.dataset.aview || '', cabin: document.body.dataset.cabin || '', ride: document.body.dataset.ride || '',
    instr: all('#aPanel .a-prompt, #aPanel .a-how, #aPanel .a-intro, #aPanel .a-phrase, #aPanel #aFeedback, #aPanel .mp-beat, #aPanel .a-where, #aPanel .a-badge-sub, #aPanel .mp-card .eyebrow, #aPanel .mp-card h2, #aPanel .h-label, #mCabin .ob-text, #mCabin .m-now, #mCabin [class*="now"]'),
    panel: one('#aPanel'), mpanel: one('#mPanel').slice(0, 300), cabinTxt: one('#mCabin').slice(0, 300), debrief: one('#mDebrief').slice(0, 300),
    primary: all('.btn-primary').slice(0, 4),
    vstate: ((bar.className.match(/is-[a-z]+/g)) || []).join(' '), listen: one('#listenState'), words: one('#liveWords'), hint: one('#spaceHint'),
    caption: T(cap), capdup: cap.classList.contains('is-dup'),
    card: one('#card').slice(0, 300), mcard: one('#missionCard'), nudge: one('#nudge'), np: one('#nowPlaying'),
    settings: one('.a11y-panel').slice(0, 300), about: ab && ab.open ? T(ab).slice(0, 200) : '',
    toast: one('.keys-toast'), keyhelp: one('.keys-help').slice(0, 120), legend: one('.key-legend'), loading: one('#loading'), vbanner: one('.a11y-vbanner'),
    pressed: [...document.querySelectorAll('[aria-pressed]')].filter(vis).map(b => (b.id || b.dataset.l || b.dataset.c || b.dataset.cs || '') + ':' + b.getAttribute('aria-pressed')).join(','),
    center: c ? [Math.round(c.lat), Math.round(c.lon)] : null,
    focus: document.activeElement ? (document.activeElement.id || String(document.activeElement.className).slice(0, 30) || document.activeElement.tagName) : '',
    q: document.getElementById('q').placeholder, qv: document.getElementById('q').value,
    html: ['contrast', 'dyslexia', 'motion', 'captions', 'textScale', 'theme', 'input'].map(k => k + '=' + (document.documentElement.dataset[k] || '')).join(' '),
  };
}"""

VISUAL = ("mode", "aview", "cabin", "ride", "instr", "panel", "mpanel", "cabinTxt", "debrief", "primary", "vstate", "listen", "words", "caption", "card",
          "mcard", "nudge", "np", "settings", "about", "toast", "keyhelp", "loading", "pressed", "center", "html", "hint", "vbanner", "legend", "qv")


class Audit:
    def __init__(self, page, out):
        self.page, self.out, self.rows, self.n = page, out, [], 0
        self.spoken = []
        page.expose_binding("__a2said", lambda src, t: self.spoken.append((time.time(), t)))
        page.add_init_script("""(() => { const hook = () => { const O = window.__outpost; if (!O || !O.floor || O.floor.__a2) return setTimeout(hook, 300);
          O.floor.__a2 = 1; const s = O.floor.say.bind(O.floor); O.floor.say = (t, o) => { try { window.__a2said(Array.isArray(t) ? t.join(' / ') : String(t)); } catch (e) {} return s(t, o); }; };
          addEventListener('load', hook); })();""")

    def probe(self):
        return self.page.evaluate(PROBE)

    def shot(self, name):
        from PIL import Image
        try:   # the 3D cabin on a loaded machine can stall a capture: skip the picture, keep the row
            im = Image.open(io.BytesIO(self.page.screenshot(timeout=20000, animations="disabled"))).convert("RGB")
        except Exception:
            return ""
        im.thumbnail((640, 640))
        p = os.path.join(self.out, name + ".jpg"); im.save(p, quality=50)
        return os.path.basename(p)

    def act(self, screen, action, fn, settle=1500, expect_change=True, stale_ok=False, note=""):
        """Run fn; check the screen reacted within 1 s and the instruction lines moved on."""
        self.n += 1
        before = self.probe()
        k0 = len(self.spoken)
        t0 = time.time()
        err = ""
        try:
            fn()
        except Exception as e:   # the action itself failed: the control was missing, etc.
            err = str(e).split("\n")[0][:160]
        dt = time.time() - t0
        self.page.wait_for_timeout(max(0, int((1.0 - dt) * 1000)))
        at1 = self.probe()
        if settle > 1000:
            self.page.wait_for_timeout(settle - 1000)
        after = self.probe()
        changed1 = [k for k in VISUAL if before.get(k) != at1.get(k)]
        changed = [k for k in VISUAL if before.get(k) != after.get(k)]
        said = [t for _, t in self.spoken[k0:]]
        instr_same = bool(before["instr"]) and before["instr"] == after["instr"]
        flags = []
        if err:
            flags.append("action failed")
        if expect_change and not changed1:
            flags.append("no reaction in 1 s")
        if expect_change and instr_same and not stale_ok and after["mode"] == before["mode"]:
            flags.append("instruction unchanged")
        if len(said) >= 2 and said[-1] == said[-2]:
            flags.append("said twice")
        name = f"{self.n:03d}_{screen}_{action}".replace(" ", "_").replace("/", "-").replace('"', "")[:70]
        img = self.shot(name)
        row = {"n": self.n, "screen": screen, "action": action, "note": note, "err": err, "changed_1s": changed1, "changed": changed,
               "said": said, "before": {k: before[k] for k in ("instr", "listen", "caption", "card")}, "after": after, "flags": flags, "img": img}
        self.rows.append(row)
        mark = "FLAG " + ", ".join(flags) if flags else "ok"
        print(f"{self.n:03d} [{screen}] {action}: {mark}  instr={after['instr'][:3]} said={said[:2]}", flush=True)
        return row

    def say(self, text):
        self.page.fill("#q", text); self.page.press("#q", "Enter")


def launch(p, base, init="", block_mic=False):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    args = ["--autoplay-policy=no-user-gesture-required"]   # the real GPU (software GL made boot so slow the session timed out)
    if not block_mic:
        args += ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
    b = p.chromium.launch(executable_path=exe, args=args)
    ctx = b.new_context(viewport={"width": 1280, "height": 720})
    if init:
        ctx.add_init_script(init)
    if block_mic:
        ctx.add_init_script("navigator.mediaDevices.getUserMedia = () => Promise.reject(Object.assign(new Error('Permission denied'), {name: 'NotAllowedError'}));")
    return b, ctx


SEED = """try{if(!sessionStorage.getItem('a2')){sessionStorage.setItem('a2','1');localStorage.clear();%s}}catch(e){}"""


def scenario_first(p, base, out, errs):
    """First launch → call sign → map; the call-sign screen's wrong actions; the map's pins, call-sign edit, keys."""
    b, ctx = launch(p, base, SEED % "localStorage.setItem('atm-theme','dark');")
    pg = ctx.new_page(); A = Audit(pg, out); hook(pg, errs)
    pg.goto(base); pg.wait_for_selector("#aCsForm", timeout=30000); pg.wait_for_timeout(1500)
    A.act("home", "open (first launch)", lambda: None, expect_change=False)
    A.act("home", "tap a call-sign chip", lambda: pg.click(".a-csb >> nth=1"), stale_ok=True)
    A.act("home", "Pick for me (shuffle)", lambda: pg.click("#aCsRand"), stale_ok=True)
    A.act("home", "clear the field, press Start", lambda: (pg.fill("#aCsIn", ""), pg.click("#aCsGo")))
    A.act("home", "say 'hello there' (not a call sign)", lambda: A.say("hello there"), settle=3500)
    A.act("home", "press M (mic)", lambda: (pg.click("body", position={"x": 640, "y": 300}), pg.keyboard.press("m")), settle=1500)
    A.act("home", "say 'call me Nova'", lambda: A.say("call me Nova"), settle=4000)
    pg.wait_for_selector(".mp-card", timeout=20000)
    A.act("map", "wait (first map)", lambda: pg.wait_for_timeout(3000), expect_change=False)
    A.act("map", "say 'what do I do'", lambda: A.say("what do I do"), settle=4000, stale_ok=True)
    A.act("map", "tap pin 3 (not next)", lambda: pg.evaluate("document.querySelectorAll('.pin')[2].click()"), settle=2000)
    A.act("map", "tap the same pin again", lambda: pg.evaluate("document.querySelectorAll('.pin')[2].click()"), settle=3000)
    A.act("lesson", "Map (back)", lambda: pg.click("#aBack"), settle=2000)
    A.act("map", "call-sign chip", lambda: pg.click("#aCsEdit"), settle=1500)
    A.act("callsign-edit", "type 'Zed', Use it", lambda: (pg.fill("#aCsIn", "Zed"), pg.click("#aCsGo")), settle=3000)
    A.act("map", "press Tab (keyboard mode)", lambda: pg.keyboard.press("Tab"), settle=1200)
    A.act("map", "press ArrowDown", lambda: pg.keyboard.press("ArrowDown"), settle=1200)
    A.act("map", "press H (help sheet)", lambda: pg.keyboard.press("h"), settle=1200)
    A.act("map", "Esc (close help)", lambda: pg.keyboard.press("Escape"), settle=1200)
    # the key legend vs the NASA credit (owner's small item)
    ov = pg.evaluate("""() => { const a = document.querySelector('.key-legend'), b = document.querySelector('#aPanel .mp-credit');
      if (!a || !b) return null; const r = a.getBoundingClientRect(), s = b.getBoundingClientRect();
      return {legend: [r.left, r.top, r.right, r.bottom].map(Math.round), credit: [s.left, s.top, s.right, s.bottom].map(Math.round),
        overlap: r.width > 0 && s.width > 0 && !(r.right < s.left || s.right < r.left || r.bottom < s.top || s.bottom < r.top)}; }""")
    A.rows.append({"n": 0, "screen": "map", "action": "key legend vs NASA credit", "geom": ov, "flags": ["overlap"] if ov and ov["overlap"] else []})
    print("legend vs credit:", ov)
    A.act("map", "press N (next)", lambda: pg.keyboard.press("n"), settle=3000)
    A.act("lesson", "Esc (back to map)", lambda: pg.keyboard.press("Escape"), settle=2000)
    A.act("map", "press S (settings)", lambda: pg.keyboard.press("s"), settle=1200)
    A.act("settings", "Esc", lambda: pg.keyboard.press("Escape"), settle=1200)
    A.act("map", "press C (captions)", lambda: pg.keyboard.press("c"), settle=1200)
    A.act("map", "press C again", lambda: pg.keyboard.press("c"), settle=1200)
    b.close()
    return A.rows


def hook(pg, errs):
    pg.set_default_timeout(30000)
    pg.on("console", lambda m: m.type == "error" and not any(x in m.text for x in IGNORE) and errs.append(m.text))
    pg.on("pageerror", lambda e: errs.append(str(e)))


def wrong_for(st, pg):
    a = st["accept"]; t = a["type"]
    if t in ("choice", "predict", "earth_view"):
        for btn in pg.query_selector_all("#aInput .a-choice"):
            if btn.get_attribute("data-c") != a.get("answer") and btn.is_visible() and not btn.is_disabled():
                return lambda: btn.click(), "tap a wrong answer"
    if t == "command":
        want = answer_for(st)
        for btn in pg.query_selector_all("#aInput .a-order"):
            if btn.get_attribute("data-say") != want and btn.is_visible():
                return lambda: btn.click(), "tap a wrong order"
    if t.startswith("vocab_"):
        right = (answer_for(st, vocab=_Vocab()) or "").lower()
        for btn in pg.query_selector_all("#aInput .v-opt"):
            lab = (btn.text_content() or "").lower()
            if btn.is_visible() and not btn.is_disabled() and a.get("term", "~") not in lab and right[:12] not in lab:
                return lambda: btn.click(), "tap a wrong word"
    if t in ("tap", "intent", "terminator", "route", "compare", "globe_side"):
        return lambda: pg.mouse.click(300, 200), "tap empty Moon / sky"
    return lambda: (pg.fill("#q", "pancakes"), pg.press("#q", "Enter")), "say a wrong word"


def scenario_lessons(p, base, out, errs, only=None):
    """Every lesson and step: open, help, a wrong try, mic off/on, a mode switch mid-step, the answer, Next."""
    b, ctx = launch(p, base, SEED % "localStorage.setItem('outpost-callsign','Nova');localStorage.setItem('atm-theme','dark');localStorage.setItem('atm-academy', JSON.stringify({badges:[], qualified:false}));")
    pg = ctx.new_page(); A = Audit(pg, out); hook(pg, errs)
    pg.goto(base); pg.wait_for_selector(".mp-card", timeout=30000); pg.wait_for_timeout(2000)
    for li, L in enumerate(COURSE["lessons"]):
        if L.get("ride") or (only and L["id"] not in only):
            continue
        if not pg.query_selector(f'#aStart[data-l="{L["id"]}"]'):
            pg.evaluate("id => document.querySelector('.pin[data-l=\"' + id + '\"]').click()", L["id"]); pg.wait_for_timeout(800)
        A.act("map", f"Start lesson {L['id']}", lambda: pg.click("#aStart"), settle=3500)
        for k, st in enumerate(L["steps"]):
            scr = f"{L['id']}#{k + 1}:{st['accept']['type']}"
            pg.wait_for_timeout(1500)
            A.act(scr, "open", lambda: None, expect_change=False)
            if k == 0:
                A.act(scr, "Brief button", lambda: pg.click("#aBriefBtn"), settle=1200)
                A.act(scr, "Brief button again (close)", lambda: pg.click("#aBriefBtn"), settle=1000)
            A.act(scr, "say 'what do I do'", lambda: A.say("what do I do"), settle=3500)
            fn, label = wrong_for(st, pg)
            A.act(scr, label, fn, settle=3500)
            if k == 0 and li == 0:
                A.act(scr, "mic button (off)", lambda: pg.click("#mic"), settle=1200)
                A.act(scr, "mic button (on)", lambda: pg.click("#mic"), settle=1500)
            if k == 1 and li in (0, 3):
                A.act(scr, "Library tab mid-step", lambda: pg.click("#libraryBtn"), settle=2000)
                A.act("library", "Flight School tab (resume)", lambda: pg.click("#modeAcademy"), settle=2500)
            if k == 1 and li == 1:
                A.act(scr, "say 'library' mid-step", lambda: A.say("open the library"), settle=3000)
                A.act("library", "say 'go back'", lambda: A.say("go back"), settle=3000)
            if not pg.query_selector("#aNext") and not pg.query_selector(".a-badge"):
                ans = answer_for(st, vocab=_Vocab())
                a = st["accept"]
                if a["type"] in ("choice", "earth_view", "predict") and pg.query_selector(f'#aInput .a-choice[data-c="{a.get("answer")}"]'):
                    A.act(scr, "tap the right answer", lambda: pg.click(f'#aInput .a-choice[data-c="{a.get("answer")}"]'), settle=3500)
                else:
                    A.act(scr, f"say the answer ({ans[:30]})", lambda: A.say(ans), settle=4500)
            last = k == len(L["steps"]) - 1
            if last:
                try: pg.wait_for_selector(".a-badge", timeout=20000)
                except Exception: pass
                pg.wait_for_timeout(1500)
                A.act(f"patch {L['id']}", "open", lambda: None, expect_change=False)
                if li == 0:
                    A.act(f"patch {L['id']}", "say 'what do I do'", lambda: A.say("what do I do"), settle=3500, stale_ok=True)
                    A.act(f"patch {L['id']}", "Map", lambda: pg.click("#aMap"), settle=2500)
                elif li == 1:
                    A.act(f"patch {L['id']}", "say 'next'", lambda: A.say("next"), settle=3500)
                    A.act("lesson", "say 'map'", lambda: A.say("back to the map"), settle=3000)
                else:
                    A.act(f"patch {L['id']}", "Map", lambda: pg.click("#aMap"), settle=2500)
            else:
                try: pg.wait_for_selector("#aNext", timeout=20000)
                except Exception: pass
                A.act(scr, "say 'pancakes' (after answer)", lambda: A.say("pancakes"), settle=3000, stale_ok=True)
                if k % 2:
                    A.act(scr, "Next button", lambda: pg.click("#aNext"), settle=3000)
                else:
                    A.act(scr, "say 'next'", lambda: A.say("next"), settle=3500)
    b.close()
    return A.rows


def scenario_ride(p, base, out, errs):
    """Six patches → the check ride → qualified → Take command."""
    six = [l["badge"]["id"] for l in COURSE["lessons"] if not l.get("ride")]
    b, ctx = launch(p, base, SEED % f"localStorage.setItem('outpost-callsign','Nova');localStorage.setItem('atm-theme','dark');localStorage.setItem('atm-academy', JSON.stringify({{badges:{json.dumps(six)}, qualified:false}}));")
    pg = ctx.new_page(); A = Audit(pg, out); hook(pg, errs)
    pg.goto(base); pg.wait_for_selector(".mp-card", timeout=30000); pg.wait_for_timeout(2000)
    A.act("map (6 patches)", "open", lambda: None, expect_change=False)
    A.act("map (6 patches)", "say 'what do I do'", lambda: A.say("what do I do"), settle=3500, stale_ok=True)
    A.act("map (6 patches)", "Start check ride", lambda: pg.click("#aStart"), settle=6000)
    L = next(l for l in COURSE["lessons"] if l.get("ride"))
    for k, st in enumerate(L["steps"]):
        scr = f"ride#{k + 1}"
        pg.wait_for_timeout(1500)
        A.act(scr, "open", lambda: None, expect_change=False)
        A.act(scr, "say 'what do I do'", lambda: A.say("what do I do"), settle=3500)
        A.act(scr, "say 'um what'", lambda: A.say("um what"), settle=3000)
        A.act(scr, f"say the order ({answer_for(st)[:30]})", lambda: A.say(answer_for(st)), settle=4500)
        if pg.query_selector("#aNext"):
            A.act(scr, "Next", lambda: pg.click("#aNext"), settle=3000)
    pg.wait_for_timeout(3000)
    A.act("qualified", "open", lambda: None, expect_change=False)
    A.act("qualified", "say 'what do I do'", lambda: A.say("what do I do"), settle=3500, stale_ok=True)
    if pg.query_selector("#aMap"):
        A.act("qualified", "Map", lambda: pg.click("#aMap"), settle=2500)
        A.act("map (qualified)", "open", lambda: None, expect_change=False)
    if pg.query_selector("#aGoMission"):
        A.act("map (qualified)", "Take command", lambda: pg.click("#aGoMission"), settle=4000)
    b.close()
    return A.rows


def scenario_library(p, base, out, errs):
    b, ctx = launch(p, base, SEED % "localStorage.setItem('outpost-callsign','Nova');localStorage.setItem('atm-theme','dark');localStorage.setItem('atm-academy', JSON.stringify({badges:['scout'], qualified:false}));")
    pg = ctx.new_page(); A = Audit(pg, out); hook(pg, errs)
    pg.goto(base); pg.wait_for_selector(".mp-card", timeout=30000); pg.wait_for_timeout(1500)
    A.act("map", "Library tab", lambda: pg.click("#libraryBtn"), settle=2500)
    A.act("library", "say 'what do I do'", lambda: A.say("what do I do"), settle=3500, stale_ok=True)
    A.act("library", "Far side", lambda: pg.click("#farBtn"), settle=2000)
    A.act("library", "Near side", lambda: pg.click("#nearBtn"), settle=2000)
    A.act("library", "Places off", lambda: pg.click("#pinsBtn"), settle=1200)
    A.act("library", "Places on", lambda: pg.click("#pinsBtn"), settle=1200)
    A.act("library", "Hardware off", lambda: pg.click("#hwBtn"), settle=1200)
    A.act("library", "Hardware on", lambda: pg.click("#hwBtn"), settle=1200)
    A.act("library", "tap the Moon centre", lambda: pg.mouse.click(640, 330), settle=3000)
    A.act("library", "tap empty sky", lambda: pg.mouse.click(80, 600), settle=1500)
    A.act("library", "ask 'where did Apollo 11 land?'", lambda: A.say("where did Apollo 11 land?"), settle=6000)
    hear = pg.query_selector("#cardActions button")
    if hear:
        A.act("library card", "Hear the crew", lambda: hear.click(), settle=3000)
        A.act("library card", "stop crew audio", lambda: pg.click("#npStop") if pg.query_selector("#npStop:visible") else None, settle=1500)
    A.act("library card", "card ×", lambda: pg.click("#cardClose"), settle=1200)
    A.act("library", "ask a mumble 'uh'", lambda: A.say("uh"), settle=3000, expect_change=False)
    A.act("library", "ask an unknown 'what is the best pizza on the moon'", lambda: A.say("what is the best pizza on the moon"), settle=6000)
    A.act("library", "Tour", lambda: pg.click("#tourBtn"), settle=4000)
    A.act("library tour", "Next stop", lambda: pg.click("#cardActions button >> nth=0"), settle=3000)
    A.act("library tour", "say 'next'", lambda: A.say("next"), settle=3000)
    A.act("library tour", "Stop", lambda: pg.click("#cardActions button >> text=Stop"), settle=1500)
    A.act("library tour", "Tour again then card ×", lambda: (pg.click("#tourBtn"), pg.wait_for_timeout(2500), pg.click("#cardClose")), settle=2000)
    A.act("library", "Find it", lambda: pg.click("#missionsBtn"), settle=2500)
    A.act("find it", "tap the wrong place", lambda: pg.mouse.click(500, 250), settle=2500)
    A.act("find it", "Show me", lambda: pg.click("#mShow"), settle=2500)
    A.act("find it", "Next", lambda: pg.click("#mNext"), settle=2500)
    A.act("find it", "close ×", lambda: pg.click("#mClose"), settle=1500)
    A.act("library", "Library tab again (back)", lambda: pg.click("#libraryBtn"), settle=2500)
    A.act("map", "say 'library'", lambda: A.say("library"), settle=3000)
    A.act("library", "Esc (back)", lambda: (pg.mouse.click(80, 600), pg.keyboard.press("Escape")), settle=2500)
    A.act("map", "Mission tab", lambda: pg.click("#modeMission"), settle=3000)
    A.act("mission (not qualified)", "say 'what do I do'", lambda: A.say("what do I do"), settle=3500, stale_ok=True)
    A.act("mission", "say 'flight school'", lambda: A.say("flight school"), settle=3000)
    b.close()
    return A.rows


def scenario_settings(p, base, out, errs):
    b, ctx = launch(p, base, SEED % "localStorage.setItem('outpost-callsign','Nova');localStorage.setItem('atm-theme','dark');localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history'], qualified:false}));")
    pg = ctx.new_page(); A = Audit(pg, out); hook(pg, errs)
    pg.goto(base); pg.wait_for_selector(".mp-card", timeout=30000); pg.wait_for_timeout(1500)
    A.act("map", "gear (Settings)", lambda: pg.click("#a11yBtn"), settle=1500)
    secs = pg.eval_on_selector_all(".set-nav [data-sec]", "bs => bs.map(b => b.dataset.sec)")
    for s in secs:
        A.act("settings", f"section {s}", lambda s=s: pg.click(f'.set-nav [data-sec="{s}"]'), settle=1200)
        # every control in the section: flip / move it, check the app applied it
        n = pg.eval_on_selector_all(".set-sec input, .set-sec button, .set-sec select", "es => es.length")
        for i in range(min(n, 14)):
            d = pg.evaluate("""i => { const e = [...document.querySelectorAll('.set-sec input, .set-sec button, .set-sec select')][i]; if (!e) return null;
              return {tag: e.tagName, type: e.type || '', name: e.name || e.dataset.p || e.dataset.k || e.dataset.pb || '', val: e.value || '',
                label: ((e.closest('label') || e).innerText || e.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim().slice(0, 40),
                checked: !!e.checked, vis: e.getClientRects().length > 0, attrs: Object.keys(e.dataset).join(',')}; }""", i)
            if not d or not d["vis"]:
                continue
            if any(x in d["attrs"] for x in ("profSwitch", "profAdd", "close", "cabinTour", "preview")):
                continue   # done below on their own
            loc = pg.locator(".set-sec input, .set-sec button, .set-sec select").nth(i)
            if d["tag"] == "INPUT" and d["type"] == "range":
                fn = lambda loc=loc: (loc.focus(), pg.keyboard.press("ArrowRight"))
            elif d["tag"] == "SELECT":
                continue
            elif d["tag"] == "INPUT" and d["type"] == "radio" and d["checked"]:
                continue
            elif d["tag"] == "INPUT" and d["name"] == "p-voice" and i > 2:
                continue   # two voices are enough
            elif d["tag"] == "INPUT":   # styled switches / radios: the input is visually hidden, the label is the target
                fn = lambda loc=loc: loc.locator("xpath=ancestor::label[1]").click(timeout=4000, position={"x": 10, "y": 10})
            else:
                fn = lambda loc=loc: loc.click(timeout=4000)
            A.act(f"settings/{s}", f"{d['name'] or d['tag']} {d['val'] if d['type'] == 'radio' else ''} [{d['label']}]", fn, settle=1000, stale_ok=True)
    A.act("settings", "Esc", lambda: pg.keyboard.press("Escape"), settle=1000)
    # Cadets: add a cadet (reloads to home), then switch back
    A.act("map", "gear → Cadets → Add a cadet", lambda: (pg.click("#a11yBtn"), pg.click('.set-nav [data-sec="cadets"]'), pg.click("[data-prof-add]")), settle=4000)
    pg.wait_for_timeout(2000)
    A.act("home (new cadet)", "open", lambda: None, expect_change=False)
    A.act("home (new cadet)", "gear → Cadets → Switch to Nova", lambda: (pg.click("#a11yBtn"), pg.click('.set-nav [data-sec="cadets"]'), pg.click("[data-prof-switch] >> nth=0")), settle=4000)
    pg.wait_for_timeout(2000)
    A.act("map (back as Nova)", "open", lambda: None, expect_change=False)
    A.act("map", "gear → Help → Show me around", lambda: (pg.click("#a11yBtn"), pg.click('.set-nav [data-sec="help"]'), pg.click("[data-cabin-tour]")), settle=3000)
    A.act("mission", "Flight School tab", lambda: pg.click("#modeAcademy"), settle=2500)
    A.act("map", "gear → Help → Pick a place → Go there", lambda: (pg.click("#a11yBtn"), pg.click('.set-nav [data-sec="help"]'), pg.click(".a11y-place summary"), pg.click("#a11yPlaceGo")), settle=3000)
    A.act("map", "Esc", lambda: pg.keyboard.press("Escape"), settle=1000)
    A.act("map", "gear → Cadets → Reset my patches (once)", lambda: (pg.click("#a11yBtn"), pg.click('.set-nav [data-sec="cadets"]'), pg.click("[data-prof-reset]")), settle=1200)
    A.act("settings/cadets", "Reset my patches (twice)", lambda: pg.click("[data-prof-reset]"), settle=3000)
    A.act("after reset", "open", lambda: None, expect_change=False)
    A.act("map", "say 'open settings'", lambda: (pg.keyboard.press("Escape"), A.say("open settings")), settle=2500)
    A.act("settings", "say 'bigger text'", lambda: A.say("bigger text"), settle=2500)
    A.act("settings", "scrim click", lambda: pg.mouse.click(30, 690), settle=1200)
    A.act("map", "About", lambda: pg.click("#aboutBtn"), settle=1500)
    A.act("about", "Esc", lambda: pg.keyboard.press("Escape"), settle=1200)
    A.act("map", "About, then Settings via S", lambda: (pg.click("#aboutBtn"), pg.keyboard.press("s")), settle=1500)
    A.act("map", "theme button", lambda: (pg.keyboard.press("Escape"), pg.click("#themeBtn")), settle=1200)
    A.act("map", "theme button again", lambda: pg.click("#themeBtn"), settle=1200)
    b.close()
    return A.rows


def scenario_errors(p, base, out, errs):
    rows = []
    # offline: /api/places fails for the first 7 s
    b, ctx = launch(p, base, SEED % "localStorage.setItem('outpost-callsign','Nova');")
    pg = ctx.new_page(); A = Audit(pg, out); hook(pg, [])
    t0 = time.time()
    pg.route("**/api/places*", lambda r: r.abort() if time.time() - t0 < 7 else r.continue_())
    pg.goto(base); pg.wait_for_timeout(2500)
    A.act("offline", "open", lambda: None, expect_change=False)
    A.act("offline", "click Flight School tab", lambda: pg.click("#modeAcademy"), settle=1500)
    A.act("offline", "type a question", lambda: A.say("hello"), settle=2000)
    A.act("offline→back", "wait for the backend", lambda: pg.wait_for_selector(".mp-card", timeout=20000), settle=1500)
    rows += A.rows; b.close()
    # course fails (Flight School offline)
    b, ctx = launch(p, base, SEED % "localStorage.setItem('outpost-callsign','Nova');")
    pg = ctx.new_page(); A = Audit(pg, out); A.n = 100; hook(pg, [])
    t1 = time.time()
    pg.route("**/api/academy/course*", lambda r: r.abort() if time.time() - t1 < 9 else r.continue_())
    pg.goto(base); pg.wait_for_timeout(4000)
    A.act("school offline", "open", lambda: None, expect_change=False)
    A.act("school offline", "wait 8 s", lambda: pg.wait_for_timeout(8000), settle=1000)
    A.act("school offline", "Library then Flight School", lambda: (pg.click("#libraryBtn"), pg.wait_for_timeout(800), pg.click("#modeAcademy")), settle=3000)
    rows += A.rows; b.close()
    # warming
    b, ctx = launch(p, base, SEED % "localStorage.setItem('outpost-callsign','Nova');")
    pg = ctx.new_page(); A = Audit(pg, out); A.n = 200; hook(pg, [])
    pg.route("**/api/health*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "model_server": {"ok": False, "models": {}}})))
    pg.goto(base); pg.wait_for_selector(".mp-card", timeout=30000); pg.wait_for_timeout(3000)
    A.act("warming", "open", lambda: None, expect_change=False)
    A.act("warming", "mic button", lambda: pg.click("#mic") if pg.query_selector("#mic:visible") else None, settle=1500)
    A.act("warming", "type 'next'", lambda: A.say("next"), settle=3500)
    rows += A.rows; b.close()
    # mic blocked
    b, ctx = launch(p, base, SEED % "localStorage.setItem('outpost-callsign','Nova');", block_mic=True)
    pg = ctx.new_page(); A = Audit(pg, out); A.n = 300; hook(pg, [])
    pg.goto(base); pg.wait_for_selector(".mp-card", timeout=30000); pg.wait_for_timeout(2500)
    A.act("mic blocked", "open", lambda: None, expect_change=False)
    A.act("mic blocked", "mic button", lambda: pg.click("#mic") if pg.query_selector("#mic:visible") else pg.mouse.click(640, 300), settle=2000)
    A.act("mic blocked", "hold Space", lambda: (pg.mouse.click(640, 300), pg.keyboard.down("Space"), pg.wait_for_timeout(700), pg.keyboard.up("Space")), settle=1500)
    A.act("mic blocked", "type 'next'", lambda: A.say("next"), settle=3500)
    rows += A.rows; b.close()
    return rows


def scenario_returning(p, base, out, errs):
    b, ctx = launch(p, base, SEED % "localStorage.setItem('outpost-callsign','Nova');localStorage.setItem('atm-theme','light');localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio'], qualified:false}));localStorage.setItem('outpost-seen-steps', JSON.stringify(['intent','tap','route','choice','command','keywords','predict','compare','globe_side','terminator','earth_view']));")
    pg = ctx.new_page(); A = Audit(pg, out); A.n = 400; hook(pg, errs)
    pg.goto(base); pg.wait_for_selector(".mp-card", timeout=30000)
    A.act("map (returning)", "open (3 patches, light)", lambda: pg.wait_for_timeout(2500), expect_change=False)
    A.act("map (returning)", "say 'next'", lambda: A.say("next"), settle=4000)
    A.act("lesson", "Mission tab mid-lesson", lambda: pg.click("#modeMission"), settle=3000)
    A.act("mission (not qualified)", "Flight School tab", lambda: pg.click("#modeAcademy"), settle=3000)
    A.act("lesson (resumed)", "reload the app mid-lesson", lambda: pg.reload(), settle=5000)
    b.close()
    return A.rows


SCEN = {"first": scenario_first, "lessons": scenario_lessons, "ride": scenario_ride, "library": scenario_library,
        "settings": scenario_settings, "errors": scenario_errors, "returning": scenario_returning}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5311")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--lessons", default="")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    errs, rows = [], []
    want = [s for s in (a.only.split(",") if a.only else SCEN)]
    with sync_playwright() as p:
        for s in want:
            print(f"==== {s}", flush=True)
            try:
                rows += (SCEN[s](p, a.base, a.out, errs, set(filter(None, a.lessons.split(",")))) if s == "lessons" else SCEN[s](p, a.base, a.out, errs))
            except Exception as e:
                print("SCENARIO FAILED", s, str(e)[:300]); errs.append(f"{s}: {e}")
    tag = "_".join(want) if a.only else "all"
    json.dump(rows, open(os.path.join(a.out, f"log_{tag}.json"), "w"), indent=1)
    fl = [r for r in rows if r.get("flags")]
    print(f"\n{len(rows)} moments, {len(fl)} flagged; console errors: {len(errs)}")
    for e in errs: print("  ERR", e[:300])
    sys.exit(1 if errs else 0)
