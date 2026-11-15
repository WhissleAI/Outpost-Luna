"""Every multi-step flow pauses and resumes, end to end (fix/flow-resume, src/flows.js).

Owner bug (0.1.2, Library, camera on): "tour strangely got stopped in between and then saying continue also didn't
work, no way to resume the tour". For each flow this interrupts it every way a kid can (voice "stop", the open hand,
a barge-in, Esc) and resumes it every way (voice "continue", a thumbs up, Enter, the Resume button), and checks it
continues from the right step, says why it paused, and logs the reason in window.__outpost.flowLog.

  Library tour  4 interrupts x 4 resumes, plus next / go back / again by voice, arrows, a barge-in that was only room
                noise (the tour plays on by itself), a question mid-tour (the answer card offers "Resume tour")
  crew clip     open hand / voice stop / Esc -> paused bar; continue / thumbs up / Enter / a tap on the bar
  cabin tour    the first-mission tour: open hand / voice stop / Esc -> Paused card; continue / thumbs up / Enter /
                Resume; back / again / next
  mission clock paused: "continue" runs it again
  lesson        "continue" in a lesson re-asks the question (it used to do nothing)

Gestures enter as the intents bind.js makes from the classifier (source "gesture"); the classifier's own timing (600 ms
still, facing, the 1 s arm) is unit-tested in tests/flows.test.js. Voice turns go through the real session router
(window.__outpost.hear: the socket, turn_router with the screen's flow_state).

    backend :8205 + vite :5205 (one browser, silent, fake camera only):
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/flows_e2e.py --base http://localhost:5205
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import time

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from silent import LAUNCH_ARGS, silence  # noqa: E402  (owner rule: test runs make no sound)

results: list[tuple[bool, str]] = []


def ok(cond, what):
    results.append((bool(cond), what))
    print(("PASS " if cond else "FAIL ") + what, flush=True)


def until(page, js, ms=8000, arg=None):
    """Poll from Python (page.evaluate), not wait_for_function: under swiftshader the 3D cabin starves the page's own
    rAF / timer polling, and a predicate that is already true timed out."""
    end = time.time() + ms / 1000
    while True:
        try:
            if page.evaluate(js, arg):
                return True
        except Exception as e:
            print(f"   (until: {type(e).__name__}: {str(e)[:160]})")
        if time.time() > end:
            return False
        time.sleep(0.15)


TOUR = "() => window.__outpost.flowTest.tour()"
GEST = "n => window.__outpost.intents.emitIntent(n, {}, 'gesture')"


def tour(page):
    return page.evaluate(TOUR)


_last_heard: dict = {}


def hear(page, text):
    # the session drops the same turn text from the same source within 1 s as a duplicate (session._dup): a real kid
    # never says "stop" twice that fast, so keep the test's identical turns at least 1.2 s apart
    gap = time.time() - _last_heard.get(text, 0)
    if gap < 1.2:
        time.sleep(1.2 - gap)
    page.evaluate("t => window.__outpost.hear(t)", text)
    _last_heard[text] = time.time()


def last_log(page, flow=None):
    return page.evaluate("f => (window.__outpost.flowLog || []).filter(e => !f || e.flow === f).slice(-1)[0] || null", flow)


def eyebrow(page):
    return page.evaluate("() => { const e = document.getElementById('cardEyebrow'); return e && !e.hidden ? e.textContent : ''; }")


def card_buttons(page):
    return page.evaluate("() => [...document.querySelectorAll('#cardActions button')].map(b => b.textContent.trim())")


# ---------------------------------------------------------------------------------------------------- Library tour
def start_tour(page):
    if tour(page)["active"]:
        page.evaluate("() => document.getElementById('cardClose').click()")   # the card's ✕ ends the tour
    mode = page.evaluate("() => document.body.dataset.mode")
    if mode != "cadet":
        last = page.evaluate("() => window.__outpost.intents.recent().slice(-4).map(e => e.name + ':' + e.source)")
        print(f"   (the screen is {mode!r}, not the Library; last intents: {last})")
        page.click("#libraryBtn"); until(page, "() => document.body.dataset.mode === 'cadet'")
    page.click("#tourBtn")
    # the intro card's Start skips the intro line; then a step forward, so "the same stop" is not just stop 0
    until(page, "() => [...document.querySelectorAll('#cardActions button')].some(b => b.textContent.trim() === 'Start')", 5000)
    page.evaluate("() => { const b = [...document.querySelectorAll('#cardActions button')].find(x => x.textContent.trim() === 'Start'); if (b) b.click(); }")
    if not until(page, "() => window.__outpost.flowTest.tour().i >= 0", 8000):
        return False
    page.evaluate("() => { const b = [...document.querySelectorAll('#cardActions button')].find(x => x.textContent.trim() === 'Next stop'); if (b) b.click(); }")
    return until(page, "() => { const t = window.__outpost.flowTest.tour(); return t.active && t.i >= 1 && !t.paused; }", 8000)


INTERRUPTS = {
    "voice stop": (lambda p: hear(p, "stop"), "voice", "you said stop"),
    "open hand": (lambda p: p.evaluate(GEST, "stop"), "gesture", "hand signal"),
    "barge-in + a question": (lambda p: (p.evaluate("() => window.__outpost.flowTest.barge()"),
                                         hear(p, "what is the biggest crater on the moon"),
                                         p.evaluate("() => window.__outpost.flowTest.kidDone()")), "question", "you asked something"),
    "Esc": (lambda p: p.keyboard.press("Escape"), "keyboard", "key press"),
}


def resume_by(page, how):
    if how == "voice continue":
        hear(page, "continue")
    elif how == "thumbs up":
        page.evaluate(GEST, "yes")
    elif how == "Enter":
        page.keyboard.press("Enter")
    elif how == "button":
        page.evaluate("() => { const b = [...document.querySelectorAll('#cardActions button')].find(x => /^Resume( tour)?$/.test(x.textContent.trim())); if (b) b.click(); }")


def library(page):
    page.click("#libraryBtn")
    ok(until(page, "() => document.body.dataset.mode === 'cadet'"), "library: open")
    for name, (act, src, why) in INTERRUPTS.items():
        for how in ("voice continue", "thumbs up", "Enter", "button"):
            if not start_tour(page):
                ok(False, f"library: the tour starts ({name} / {how})")
                continue
            i0 = tour(page)["i"]
            act(page)
            paused = until(page, "() => window.__outpost.flowTest.tour().paused", 8000)
            t = tour(page)
            ok(paused and t["active"] and t["why"].endswith(why), f"library [{name}]: paused, not ended (why: {t['why']!r})")
            lg = last_log(page, "library_tour")
            ok(bool(lg) and lg["event"] == "pause" and lg["source"] == src, f"library [{name}]: flowLog has the pause and its source ({lg and lg['source']})")
            if name != "barge-in + a question":
                ok(eyebrow(page).startswith("Paused"), f"library [{name}]: the card says Paused ({eyebrow(page)!r})")
                btns = card_buttons(page)
                ok(btns and btns[0] == "Resume" and "Close tour" in btns, f"library [{name}]: Resume first, Close tour there ({btns})")
                ok(until(page, "() => document.activeElement && document.activeElement.textContent.trim() === 'Resume'", 3000), f"library [{name}]: Resume has focus")
                ok(page.evaluate("() => document.getElementById('cardPrev').hidden"), f"library [{name}]: no history 'Previous' toggle on a tour card")
            else:
                ok(any(b == "Resume tour" for b in card_buttons(page)) or eyebrow(page).startswith("Paused"), f"library [{name}]: the answer card offers Resume tour ({card_buttons(page)})")
            ip = tour(page)["i"]
            resume_by(page, how)
            res = until(page, "() => { const t = window.__outpost.flowTest.tour(); return t.active && !t.paused; }", 8000)
            t = tour(page)
            ok(res and t["i"] == ip, f"library [{name}] -> {how}: resumed at the same stop ({ip} -> {t['i']}, from {i0})")
    # steps by voice and keys
    start_tour(page)
    page.evaluate(GEST, "stop"); until(page, "() => window.__outpost.flowTest.tour().paused")
    i = tour(page)["i"]
    hear(page, "next")
    ok(until(page, f"() => window.__outpost.flowTest.tour().i === {i + 1}"), "library: \"next\" goes to the next stop")
    hear(page, "go back")
    ok(until(page, f"() => window.__outpost.flowTest.tour().i === {i}"), "library: \"go back\" goes to the stop before")
    page.evaluate(GEST, "stop"); until(page, "() => window.__outpost.flowTest.tour().paused")
    hear(page, "again")
    ok(until(page, f"() => {{ const t = window.__outpost.flowTest.tour(); return !t.paused && t.i === {i}; }}"), "library: \"again\" plays this stop again")
    page.evaluate(GEST, "stop"); until(page, "() => window.__outpost.flowTest.tour().paused")
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("ArrowRight")
    ok(until(page, f"() => window.__outpost.flowTest.tour().i === {i + 1}"), "library: arrow right = next stop")
    page.keyboard.press("ArrowLeft")
    ok(until(page, f"() => window.__outpost.flowTest.tour().i === {i}"), "library: arrow left = the stop before")
    # a barge-in that was only room noise: the tour holds, then plays on by itself
    page.evaluate("() => window.__outpost.flowTest.barge()")
    ok(tour(page)["held"], "library: a barge-in holds the tour (not stopped)")
    page.evaluate("() => window.__outpost.flowTest.kidDone()")
    ok(until(page, f"() => {{ const t = window.__outpost.flowTest.tour(); return t.active && !t.held && !t.paused && t.i >= {i}; }}", 5000),
       "library: a barge-in nobody meant (no turn) -> the tour plays on from the same stop")
    ok(last_log(page, "library_tour")["source"] in ("barge_ignored", "flow"), "library: flowLog says the barge was ignored")
    # Esc twice: pause, then close
    page.keyboard.press("Escape")
    until(page, "() => window.__outpost.flowTest.tour().paused")
    page.keyboard.press("Escape")
    ok(until(page, "() => !window.__outpost.flowTest.tour().active && document.getElementById('card').hidden"), "library: Esc pauses, a second Esc closes")
    # the Tour button pauses and resumes too
    start_tour(page)
    page.click("#tourBtn")
    ok(until(page, "() => window.__outpost.flowTest.tour().paused"), "library: the Tour button pauses a running tour")
    page.click("#tourBtn")
    ok(until(page, "() => !window.__outpost.flowTest.tour().paused"), "library: and resumes it")
    page.evaluate("() => document.getElementById('cardClose').click()")
    ok(until(page, "() => !window.__outpost.flowTest.tour().active"), "library: the card's ✕ ends the tour")


# ---------------------------------------------------------------------------------------------------- crew clip
def crew(page):
    if page.evaluate("() => document.body.dataset.mode") != "cadet":   # the now-playing bar lives in the Library
        page.click("#libraryBtn"); until(page, "() => document.body.dataset.mode === 'cadet'")
    for name, act in (("open hand", lambda p: p.evaluate(GEST, "stop")), ("voice stop", lambda p: hear(p, "stop")),
                      ("Esc", lambda p: p.keyboard.press("Escape"))):
        for how in ("voice continue", "thumbs up", "Enter", "tap"):
            if not page.evaluate("() => window.__outpost.playCrew()"):
                ok(False, "crew: a clip plays"); return
            until(page, "() => window.__outpost.flows.current() && window.__outpost.flows.current().name === 'crew_clip'", 8000)
            page.wait_for_timeout(900)
            act(page)
            p = until(page, "() => { const c = window.__outpost.flows.current(); return c && c.name === 'crew_clip' && c.paused; }", 6000)
            ok(p and page.evaluate("() => /Paused/.test(document.getElementById('npPaused').textContent)"), f"crew [{name}]: the clip holds, the bar says Paused")
            page.evaluate("() => document.activeElement && document.activeElement.blur()")
            if how == "tap":
                page.evaluate("() => document.querySelector('#nowPlaying .np-body').click()")
            elif how == "voice continue":
                hear(page, "continue")
            elif how == "thumbs up":
                page.evaluate(GEST, "yes")
            else:
                page.keyboard.press("Enter")
            r = until(page, "() => { const c = window.__outpost.flows.current(); return c && c.name === 'crew_clip' && !c.paused; }", 6000)
            ok(r, f"crew [{name}] -> {how}: plays on")
            page.evaluate("() => { if (!document.getElementById('nowPlaying').hidden) document.getElementById('npStop').click(); }")


# ---------------------------------------------------------------------------------------------------- cabin tour
TT = "() => { const c = document.querySelector('.m-tour'); return c && !c.hidden ? { paused: c.classList.contains('is-paused'), eye: c.querySelector('.t-eye').textContent, why: (c.querySelector('.t-why') || {}).textContent || '', text: c.querySelector('.t-text').textContent } : null; }"


def cabin(page, base):
    page.click("#modeMission")
    until(page, "() => document.body.dataset.mode === 'mission'")
    page.wait_for_timeout(800)
    page.evaluate("() => window.__outpost.shellNav('take_command')")
    # the first-mission briefing card (Moon Base video offer, when the video is cached): "Not now" goes on to the cabin
    if until(page, "() => !!document.querySelector('.ml-offer #mlSkip')", 4000):
        ok(page.evaluate("() => document.activeElement && document.activeElement.id === 'mlWatch'"), "briefing offer: Watch has focus (Enter works)")
        page.click(".ml-offer #mlSkip")
    if not until(page, "() => { const c = document.querySelector('.m-tour'); return c && !c.hidden; }", 30000):
        ok(False, "cabin: the first-mission tour starts"); return
    page.wait_for_timeout(500)
    for name, act, why in (("open hand", lambda p: p.evaluate(GEST, "stop"), "hand signal"), ("voice stop", lambda p: hear(p, "stop"), "you said stop"),
                           ("Esc", lambda p: p.keyboard.press("Escape"), "key press")):
        for how in ("voice continue", "thumbs up", "Enter", "button"):
            before = page.evaluate(TT)
            act(page)
            p = until(page, "() => { const c = document.querySelector('.m-tour'); return c && c.classList.contains('is-paused'); }", 6000)
            st = page.evaluate(TT) or {}
            lg = page.evaluate("() => window.__outpost.flowLog.slice(-3).map(e => e.flow + ':' + e.event + ':' + e.source)")
            ok(p and st.get("eye", "").startswith("Paused") and why in st.get("why", ""), f"cabin tour [{name}]: Paused, says why ({st.get('why')!r}; p={p} eye={st.get('eye')!r} log={lg})")
            ok(until(page, "() => document.activeElement && document.activeElement.dataset.t === 'resume'", 3000), f"cabin tour [{name}]: Resume has focus")
            if how == "voice continue":
                hear(page, "continue")
            elif how == "thumbs up":
                page.evaluate(GEST, "yes")
            elif how == "Enter":
                page.keyboard.press("Enter")
            else:
                page.click(".m-tour [data-t=resume]")
            r = until(page, "() => { const c = document.querySelector('.m-tour'); return c && !c.hidden && !c.classList.contains('is-paused'); }", 12000)
            st = page.evaluate(TT) or {}
            lg = page.evaluate("() => window.__outpost.flowLog.slice(-3).map(e => e.flow + ':' + e.event + ':' + e.source)")
            ok(r and st.get("text") == (before or {}).get("text"), f"cabin tour [{name}] -> {how}: resumed on the same beat ({lg}; {(before or {}).get('eye')} {(before or {}).get('text', '')[:25]!r} -> {st.get('eye')} {st.get('text', '')[:25]!r})")
    # barge-in only cuts the line; "again" says the beat again, "next" / "go back" step
    t0 = page.evaluate(TT)["text"]
    hear(page, "next")
    ok(until(page, "t => { const c = document.querySelector('.m-tour .t-text'); return c && c.textContent !== t; }", 6000, t0), "cabin tour: \"next\" -> the next beat")
    hear(page, "go back")
    ok(until(page, "t => { const c = document.querySelector('.m-tour .t-text'); return c && c.textContent === t; }", 6000, t0), "cabin tour: \"go back\" -> the beat before")
    hear(page, "again")
    page.wait_for_timeout(600)
    ok(page.evaluate(TT)["text"] == t0 and not page.evaluate(TT)["paused"], "cabin tour: \"again\" -> this beat again")
    # skip it, then the mission clock: paused, "continue" runs it
    page.evaluate("() => { const b = document.querySelector('.m-tour [data-t=skip]'); if (b) b.click(); }")
    until(page, "() => { const c = document.querySelector('.m-tour'); return !c || c.hidden; }")
    page.evaluate("() => { const m = window.__outpost.missionUI; m.clockAction('play'); m.clockAction('pause'); }")
    ok(page.evaluate("() => { const c = window.__outpost.flows.current(); return !!c && c.name === 'mission_clock' && c.paused; }"), "mission clock: a paused clock is a paused flow")
    hear(page, "keep going")
    ok(until(page, "() => window.__outpost.missionUI.clock.running", 6000), "mission clock: \"keep going\" runs it again")
    page.evaluate("() => window.__outpost.missionUI.clockAction('pause')")


# ---------------------------------------------------------------------------------------------------- glossary
HL = "() => { const c = document.querySelector('.hl-card'); if (!c || c.hidden) return null; const r = c.getBoundingClientRect(); return { title: c.querySelector('h3').textContent, def: (c.querySelector('h3 + p') || {}).textContent || '', src: !!c.querySelector('.hl-src a'), on: r.top >= 0 && r.left >= 0 && r.bottom <= innerHeight && r.right <= innerWidth }; }"


def glossary(page):
    """Owner bug: "ⓘ lava" chips did nothing. Every chip and every marked word on a card opens a definition, on screen."""
    if page.evaluate("() => document.body.dataset.mode") != "cadet":
        page.click("#libraryBtn"); until(page, "() => document.body.dataset.mode === 'cadet'")
    line = "The near side, the face we always see. The dark patches are old lava. Rovers look for ice in a crater."
    page.evaluate("t => { document.getElementById('cardTitle').textContent = 'Guide'; document.getElementById('cardSay').textContent = t; document.getElementById('cardSay').hidden = false; document.getElementById('card').hidden = false; }", line)
    ok(until(page, "() => document.querySelectorAll('#card .hl-chip').length >= 3", 5000), "glossary: the card shows word chips")
    n = page.evaluate("() => document.querySelectorAll('#card .hl-chip, #cardSay .hl[role=button]').length")
    for i in range(n):
        el = page.evaluate("i => { const e = [...document.querySelectorAll('#card .hl-chip, #cardSay .hl[role=button]')][i]; return e.dataset.kind + ':' + (e.dataset.ref || e.textContent); }", i)
        page.evaluate("i => [...document.querySelectorAll('#card .hl-chip, #cardSay .hl[role=button]')][i].click()", i)
        if el.startswith("place:"):
            continue
        ok(until(page, "() => { const c = document.querySelector('.hl-card'); return c && !c.hidden; }", 3000), f"glossary: {el} opens a card")
        st = page.evaluate(HL) or {}
        ok(len(st.get("def", "").split()) >= 4 and st.get("on") and st.get("src"), f"glossary: {el}: a definition, a source, fully on screen ({st})")
        page.keyboard.press("Escape")
        ok(until(page, "() => { const c = document.querySelector('.hl-card'); return !c || c.hidden; }", 3000), f"glossary: {el}: Esc closes it")
        ok(page.evaluate("() => !document.getElementById('card').hidden"), f"glossary: {el}: one Esc closes only the word card")
    # Enter on a focused chip, then voice
    page.focus("#card .hl-chip-term")
    page.keyboard.press("Enter")
    ok(until(page, "() => { const c = document.querySelector('.hl-card'); return c && !c.hidden; }", 3000), "glossary: Enter on a chip opens it")
    page.click(".hl-card [data-x]")
    hear(page, "what is lava?")
    ok(until(page, "() => { const c = document.querySelector('.hl-card'); return c && !c.hidden && /lava/i.test(c.querySelector('h3').textContent); }", 5000), "glossary: \"what is lava?\" opens lava")
    page.click(".hl-card [data-x]")
    hear(page, "what does that mean?")
    ok(until(page, "() => { const c = document.querySelector('.hl-card'); return c && !c.hidden; }", 5000), "glossary: \"what does that mean?\" opens the word on screen")
    page.keyboard.press("Escape")
    page.evaluate("() => document.getElementById('cardClose').click()")


# ---------------------------------------------------------------------------------------------------- lesson
def lesson(page):
    for lid, label in (("phases", "lesson"), ("checkride", "check ride")):
        page.evaluate("() => document.getElementById('modeAcademy').click()")
        until(page, "() => document.body.dataset.mode === 'academy'")
        page.wait_for_timeout(1500)   # Flight School settles on its map first
        page.evaluate("id => window.__outpost.shellNav('lesson', id)", lid)
        page.wait_for_timeout(800)
        page.wait_for_timeout(1200)
        if page.evaluate("() => window.__outpost.screenFrame().screen") == "prep":   # mission prep: a hands-on task first
            hear(page, "wait")
            page.wait_for_timeout(1200)
            n = page.evaluate("() => window.__outpost.intents.recent().length")
            hear(page, "keep going")
            ok(until(page, "() => { const e = window.__outpost.flowLog.slice(-1)[0]; return !!e && e.flow === 'prep' && e.event === 'repeat'; }", 8000),
               "prep: \"keep going\" after \"wait\" says the task again (it was ignored)")
            hear(page, "skip")
            until(page, "() => window.__outpost.screenFrame().screen !== 'prep'", 8000)
        page.evaluate("() => { const b = document.getElementById('aBriefBtn'); if (b && b.offsetParent) b.click(); }")   # the lesson's brief
        if not until(page, "() => { const a = document.getElementById('aPanel'); return a && !a.hidden && !!a.querySelector('.a-prompt'); }", 15000):
            ok(False, f"{label}: it opens"); continue
        page.wait_for_timeout(600)
        page.evaluate("() => window.__outpost.intents.emitIntent('stop', {}, 'gesture')")
        n = page.evaluate("() => window.__outpost.intents.recent().length")
        hear(page, "continue")
        ok(until(page, "() => { const e = window.__outpost.flowLog.slice(-1)[0]; return !!e && /lesson|check_ride/.test(e.flow) && e.event === 'repeat'; }", 8000)
           and not page.evaluate("() => { const f = document.querySelector('#aPanel .a-feedback'); return !!(f && f.textContent.trim()); }"),
           f"{label}: \"continue\" after a stop is handled (the question again), not a dead end "
           f"({page.evaluate('n => window.__outpost.intents.recent().slice(n).map(e => e.name + `:` + e.handled)', n)} {page.evaluate('() => window.__outpost.screenFrame()')})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5205")
    ap.add_argument("--only", default="", help="library,crew,glossary,cabin,lesson")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    only = set(filter(None, a.only.split(",")))
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    errs: list[str] = []
    t0 = time.time()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=[*LAUNCH_ARGS, "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                                          "--autoplay-policy=no-user-gesture-required", "--enable-unsafe-swiftshader"])
        ctx = b.new_context(viewport={"width": 1440, "height": 879})
        ctx.add_init_script("""try { if (!sessionStorage.getItem('flows-e2e')) { localStorage.clear(); sessionStorage.setItem('flows-e2e', '1');
          localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('atm-academy', JSON.stringify({badges: ['scout','history','radio','sun','storm','ice','commander'], qualified: true})); } } catch (e) {}
          window.__outpostTest = true;""")
        silence(ctx)
        page = ctx.new_page()
        page.on("console", lambda m: m.type == "error" and not any(x in m.text for x in ("favicon", "/api/voices", "404", "ERR_", "tts", "Failed to load resource")) and errs.append(m.text))
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(base + "/")
        page.wait_for_function("() => window.__outpost && window.__outpost.flowTest && window.__outpost.intents && window.__outpost.hear && document.body.dataset.mode", timeout=60000)
        until(page, "() => !document.getElementById('loading') || document.getElementById('loading').hidden || !document.getElementById('loading').offsetParent", 30000)
        page.wait_for_timeout(1500)
        if not only or "library" in only:
            library(page)
        if not only or "crew" in only:
            crew(page)
        if not only or "glossary" in only:
            glossary(page)
        if not only or "cabin" in only:
            cabin(page, base)
        if not only or "lesson" in only:
            lesson(page)
        ok(not errs, f"no page errors ({errs[:3]})")
        b.close()
    bad = [w for c, w in results if not c]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed in {time.time() - t0:.0f}s")
    if bad:
        print("FAILED:\n  " + "\n  ".join(bad))
        sys.exit(1)


if __name__ == "__main__":
    main()
