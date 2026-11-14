"""UX round screenshots: drive the app into each workflow state and save small JPEGs.

  uv run --with playwright python frontend/tools/ux_shots.py --base http://localhost:5240 \
      --states home,map,lesson --sizes 1440x900,1280x720 --themes dark,light --out docs/img/ux --tag r1

Each state starts from a fresh page with seeded localStorage (call sign, patches). Clicks only; the voice path is
covered by ux_flow.py. Console errors are printed and make the exit code 1.
"""
import argparse
import io
import json
import sys
import glob
import os
import time

from playwright.sync_api import sync_playwright

ALL = ["home", "map", "map_mid", "lesson_choice", "lesson_tap", "lesson_keywords", "lesson_command", "lesson_feedback",
       "vocab_listen", "vocab_match", "vocab_say", "vocab_fill", "patch", "ride", "brief", "cabin", "storm", "cabin_orbit",
       "houston", "debrief", "library", "access", "mic_denied"]
ALL_BADGES = ["scout", "radio", "sun", "storm", "ice", "history", "words"]


def seed(page, cs="Nova", badges=(), qualified=False, theme="dark"):
    page.add_init_script(f"""try{{
      localStorage.setItem('atm-theme', {json.dumps(theme)});
      {'localStorage.setItem("outpost-callsign", %s);' % json.dumps(cs) if cs else 'localStorage.removeItem("outpost-callsign");'}
      localStorage.setItem('atm-academy', JSON.stringify({{badges:{json.dumps(list(badges))}, qualified:{str(qualified).lower()}}}));
      localStorage.setItem('atm-mode', 'mission');
    }}catch(e){{}}""")


def settle(page, ms=900):
    page.wait_for_timeout(ms)


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend", "tools"))
from handsfree_run import answer_for  # noqa: E402  (the scripted kid's answers; one source of truth)

COURSE = json.load(open(os.path.join(ROOT, "backend", "data", "academy", "course.json")))
GLOSS = json.load(open(os.path.join(ROOT, "backend", "data", "glossary.json")))


class _Vocab:
    def term(self, t):
        items = GLOSS.get("terms", GLOSS) if isinstance(GLOSS, dict) else GLOSS
        if isinstance(items, dict):
            v = items.get(t)
            return v if isinstance(v, dict) else None
        return next((x for x in items if x.get("term") == t), None)


def open_lesson(page, lid, step=0):
    """Open lesson `lid` and advance to step `step` by answering each step correctly (typed = the voice path)."""
    page.wait_for_selector(f'[data-l="{lid}"]', state="attached", timeout=15000)
    page.wait_for_timeout(300)
    # the Moon map: a pin selects its lesson, the card's Start opens it (pins round the back can't be clicked)
    if not page.query_selector(f'#aStart[data-l="{lid}"]'):
        page.evaluate("id => document.querySelector('.pin[data-l=\"' + id + '\"]').click()", lid)
        page.wait_for_selector(f'#aStart[data-l="{lid}"]', timeout=15000)
    page.click("#aStart")
    page.wait_for_selector("#aInput", state="attached", timeout=15000)
    L = next(l for l in COURSE["lessons"] if l["id"] == lid)
    for k in range(step):
        answer_step(page, L["steps"][k])
        page.wait_for_selector("#aNext", timeout=25000)
        page.click("#aNext")
        page.wait_for_timeout(400)
    settle(page, 700)
    return L


def answer_step(page, st):
    page.wait_for_timeout(600)
    page.evaluate("t => window.__ux_answer(t)", answer_for(st, vocab=_Vocab()))


def to_cabin(page):
    page.wait_for_selector("#mStart", timeout=20000)
    page.click("#mStart")
    page.wait_for_selector(".cb-glass", timeout=20000)
    settle(page, 2600)


STATES = {}


def state(fn):
    STATES[fn.__name__[2:]] = fn
    return fn


@state
def s_home(page, base, theme):
    seed(page, cs="", theme=theme)
    page.goto(base)
    settle(page, 2500)


@state
def s_map(page, base, theme):
    seed(page, badges=[], theme=theme)
    page.goto(base)
    settle(page, 2500)


@state
def s_map_mid(page, base, theme):
    seed(page, badges=["scout", "radio", "sun"], theme=theme)
    page.goto(base)
    settle(page, 2500)


@state
def s_vbar_moved(page, base, theme):
    """The voice bar moved by the typed command (same path as speech) to the top right."""
    seed(page, badges=["scout", "radio", "sun"], theme=theme)
    page.add_init_script("try{localStorage.removeItem('outpost-voicebar')}catch(e){}")
    page.goto(base)
    settle(page, 2000)
    page.evaluate("t => window.__ux_answer(t)", "move the voice bar to the top right")
    settle(page, 1200)


@state
def s_vbar_dragged(page, base, theme):
    """The voice bar dragged by its grip (pointer) to the top right, in a lesson: it must avoid the lesson card."""
    seed(page, badges=["scout", "radio", "sun"], theme=theme)
    page.add_init_script("try{localStorage.removeItem('outpost-voicebar')}catch(e){}")
    page.goto(base)
    settle(page, 1500)
    open_lesson(page, "moon", 2)
    g = page.query_selector("#vsGrip").bounding_box()
    vw = page.viewport_size
    page.mouse.move(g["x"] + 8, g["y"] + 20)
    page.mouse.down()
    page.mouse.move(vw["width"] - 200, 140, steps=12)
    page.mouse.up()
    settle(page, 900)
    a = page.evaluate("document.getElementById('askbar').dataset.anchor")
    print(f"  vbar anchor after drag: {a}")


@state
def s_pin_selected(page, base, theme):
    """A done pin tapped on the Moon map: the globe flies there and the card offers Replay."""
    seed(page, badges=["scout", "radio", "sun"], theme=theme)
    page.goto(base)
    settle(page, 2000)
    page.evaluate("() => document.querySelector('.pin[data-l=\"comms\"]').click()")
    settle(page, 2200)


def lesson_state(lid, step, theme, page, base, feedback=False):
    seed(page, badges=["scout", "radio", "sun", "storm", "ice", "history", "words"], theme=theme)
    page.goto(base)
    settle(page, 1500)
    L = open_lesson(page, lid, step)
    if feedback:
        answer_step(page, L["steps"][step])
        page.wait_for_selector("#aNext", timeout=25000)
        settle(page, 600)


@state
def s_lesson_choice(page, base, theme): lesson_state("moon", 2, theme, page, base)
@state
def s_lesson_tap(page, base, theme): lesson_state("moon", 1, theme, page, base)
@state
def s_lesson_keywords(page, base, theme): lesson_state("comms", 1, theme, page, base)
@state
def s_lesson_command(page, base, theme): lesson_state("power", 2, theme, page, base)
@state
def s_lesson_feedback(page, base, theme): lesson_state("moon", 2, theme, page, base, feedback=True)
@state
def s_vocab_listen(page, base, theme): lesson_state("words", 0, theme, page, base)
@state
def s_vocab_match(page, base, theme): lesson_state("words", 1, theme, page, base)
@state
def s_vocab_say(page, base, theme): lesson_state("words", 2, theme, page, base)
@state
def s_vocab_fill(page, base, theme): lesson_state("words", 3, theme, page, base)


@state
def s_patch(page, base, theme):
    seed(page, badges=["scout", "radio", "sun", "storm", "ice", "history"], theme=theme)
    page.goto(base)
    settle(page, 1500)
    L = open_lesson(page, "words", 4)
    answer_step(page, L["steps"][4])
    page.wait_for_selector(".a-badge, .p-earned", timeout=15000)
    settle(page, 1400)


@state
def s_ride(page, base, theme):
    seed(page, badges=ALL_BADGES, theme=theme)
    page.goto(base)
    settle(page, 1500)
    open_lesson(page, "checkride", 0)
    settle(page, 2000)


def mission_page(page, base, theme):
    seed(page, badges=ALL_BADGES + ["commander"], qualified=True, theme=theme)
    page.goto(base)
    page.wait_for_selector("#mStart", timeout=20000)
    settle(page, 2500)


@state
def s_brief(page, base, theme): mission_page(page, base, theme)


@state
def s_cabin(page, base, theme):
    mission_page(page, base, theme)
    to_cabin(page)


@state
def s_storm(page, base, theme):
    mission_page(page, base, theme)
    to_cabin(page)
    page.evaluate("window.__cabinTest && window.__cabinTest.storm(true)")
    settle(page, 1500)


@state
def s_cabin_orbit(page, base, theme):
    mission_page(page, base, theme)
    to_cabin(page)
    page.click('.cb-view[data-view="orbit"]')
    settle(page, 2500)


@state
def s_houston(page, base, theme):
    mission_page(page, base, theme)
    to_cabin(page)
    page.click("#cbPtt")
    settle(page, 900)


@state
def s_debrief(page, base, theme):
    mission_page(page, base, theme)
    to_cabin(page)
    for _ in range(3):
        page.click("#cbEnd")
        settle(page, 1500)
    page.click("#cbDb")
    page.wait_for_selector("#mDebrief:not([hidden])", timeout=15000)
    settle(page, 1500)


@state
def s_library(page, base, theme):
    mission_page(page, base, theme)
    page.click("#libraryBtn")
    settle(page, 3000)


@state
def s_access(page, base, theme):
    mission_page(page, base, theme)
    page.click("#a11yBtn")
    settle(page, 900)


@state
def s_mic_denied(page, base, theme):
    """The browser refuses the mic: the strip says so, typing still works."""
    page.add_init_script("""navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('denied', 'NotAllowedError'));
      try { delete window.SpeechRecognition; delete window.webkitSpeechRecognition; } catch (e) {}""")
    seed(page, badges=["scout"], theme=theme)
    page.goto(base)
    settle(page, 1800)
    page.mouse.click(700, 400)
    settle(page, 1800)


def settings_section(page, base, theme, sec):
    seed(page, badges=["scout", "radio", "sun"], theme=theme)
    page.goto(base)
    settle(page, 1800)
    page.click("#a11yBtn")
    settle(page, 400)
    page.click(f'.set-nav [data-sec="{sec}"]')
    settle(page, 700)


@state
def s_settings_listen(page, base, theme): settings_section(page, base, theme, "listen")
@state
def s_settings_cadets(page, base, theme): settings_section(page, base, theme, "cadets")
@state
def s_settings_display(page, base, theme): settings_section(page, base, theme, "display")


@state
def s_warming(page, base, theme):
    """The model server is still loading: the voice bar says so; typing works."""
    seed(page, badges=["scout", "radio", "sun"], theme=theme)
    page.route("**/api/health", lambda r: r.fulfill(status=200, content_type="application/json",
               body='{"ok":true,"model_server":{"ok":false,"models":{}}}'))
    page.goto(base)
    settle(page, 2500)


@state
def s_offline(page, base, theme):
    """The backend is down: the Moon still loads, the app says what's wrong."""
    seed(page, badges=["scout"], theme=theme)
    page.route("**/api/**", lambda r: r.abort())
    page.goto(base)
    settle(page, 2500)


@state
def s_loading(page, base, theme):
    """First paint, before the Moon map and the course arrive."""
    seed(page, badges=["scout"], theme=theme)
    page.route("**/api/academy/course", lambda r: None)   # never answers
    page.goto(base)
    settle(page, 1500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5240")
    ap.add_argument("--states", default=",".join(ALL))
    ap.add_argument("--sizes", default="1440x900,1280x720")
    ap.add_argument("--themes", default="dark,light")
    ap.add_argument("--out", default="docs/img/ux")
    ap.add_argument("--tag", default="r1")
    ap.add_argument("--quality", type=int, default=72)
    a = ap.parse_args()
    errors = []
    with sync_playwright() as p:
        exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
        b = p.chromium.launch(executable_path=exe, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                    "--autoplay-policy=no-user-gesture-required", "--use-gl=angle", "--use-angle=swiftshader"])
        for st in a.states.split(","):
            for size in a.sizes.split(","):
                w, h = map(int, size.split("x"))
                for theme in a.themes.split(","):
                    ctx = b.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
                    page = ctx.new_page()
                    page.add_init_script("""window.__ux_answer = t => { const q = document.getElementById('q');
                      q.value = t; document.getElementById('askForm').requestSubmit(); };""")
                    errs = []
                    page.on("console", lambda m, errs=errs: m.type == "error" and errs.append(m.text))
                    page.on("pageerror", lambda e, errs=errs: errs.append(str(e)))
                    t0 = time.time()
                    try:
                        STATES[st](page, a.base, theme)
                        png = page.screenshot(type="jpeg", quality=a.quality)
                        name = f"{a.out}/{a.tag}-{st}-{w}-{theme}.jpg"
                        open(name, "wb").write(png)
                        print(f"{name} {len(png)//1024}KB {time.time()-t0:.1f}s")
                    except Exception as e:
                        errs.append(f"STATE FAILED: {e}")
                        try:
                            page.screenshot(path=f"{a.out}/{a.tag}-{st}-{w}-{theme}-FAIL.jpg", type="jpeg", quality=50)
                        except Exception:
                            pass
                    real = [e for e in errs if "favicon" not in e]
                    for e in real:
                        print(f"  ERR [{st} {size} {theme}] {e[:300]}")
                    errors += real
                    ctx.close()
        b.close()
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
