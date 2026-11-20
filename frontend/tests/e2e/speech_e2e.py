"""Speech learning steps (docs/SPEECH_LEARNING.md): each Moon sample lesson plays to its patch in the real app, by taps,
typing (the card's box and the voice bar) and keys. Read: a choice, a typed short answer, a sentence found with the
keyboard, and Read it aloud (typed words stand in for the ear) with its counts. Vocab: a sound-alike trap is caught,
then each word. Summary: a typed summary gets key-point feedback, never a grade. Progress shows counts only.
Screenshots (--out) at 1440x900 and 1280x720.

    (backend on its port, Vite in front of it)
    uv run --no-project --with playwright==1.58.0 python frontend/tests/e2e/speech_e2e.py --base http://localhost:5484 [--out DIR]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright
sys.path.insert(0, str(Path(__file__).resolve().parent))
from silent import LAUNCH_ARGS, silence  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
COURSE = json.loads((ROOT / "backend" / "data" / "academy" / "course.json").read_text())
LES = {l["id"]: l for l in COURSE["lessons"]}
PASSAGE = next(s for s in LES["reading"]["steps"] if s["accept"]["type"] == "read")["accept"]["passage"]["text"]
results: list[bool] = []
GRADE_WORDS = ("wrong", "score", "grade", "incorrect", "fail")


def check(ok, msg):
    results.append(bool(ok)); print(("  ok  " if ok else "  FAIL ") + msg)


def until(pg, js, ms=8000):
    for _ in range(ms // 100):
        try:
            if pg.evaluate(js):
                return True
        except Exception:
            pass
        pg.wait_for_timeout(100)
    return False


def shot(pg, out, name):
    if out:
        pg.screenshot(path=str(Path(out) / f"{name}.png"))


def step_type(pg):
    return pg.evaluate("() => document.getElementById('aPanel').dataset.step")


def say(pg, text):
    """The voice bar: typed words take the same path as the ear's words."""
    pg.fill("#q", text); pg.press("#q", "Enter")


def answered(pg, ms=9000):
    return until(pg, "() => !!document.querySelector('#aNext')", ms)


def next_step(pg):
    pg.click("#aNext"); pg.wait_for_timeout(500)


def open_lesson(pg, lid):
    until(pg, f"""() => !!document.querySelector('.route .pin[data-l="{lid}"]')""", 20000)
    ok = pg.evaluate(f"""() => {{ const p = document.querySelector('.route .pin[data-l="{lid}"]'); if (p) {{ p.click(); return true; }} return false; }}""")
    if ok:
        until(pg, "() => !!document.querySelector('#aStart')", 4000)
        pg.click("#aStart")
    return until(pg, f"() => document.getElementById('aPanel').dataset.step && document.querySelector('#aPanel .m-title').textContent.includes({json.dumps(LES[lid]['title'])})", 8000)


def keys_reach(pg, sel):
    """Tab from the prompt until focus lands on the step's control (keyboard / controller reach)."""
    pg.evaluate("() => { const q = document.querySelector('.a-prompt'); if (q) q.focus(); }")
    for _ in range(40):
        pg.keyboard.press("Tab")
        if pg.evaluate(f"() => !!document.activeElement && document.activeElement.matches({json.dumps(sel)})"):
            return True
    return False


def skip_video(pg):
    if step_type(pg) == "video":
        say(pg, "skip")
        if not answered(pg):
            pg.evaluate("() => { const b = [...document.querySelectorAll('#aInput button')].find(x => /skip/i.test(x.textContent)); if (b) b.click(); }")
        check(answered(pg), "the video hook can be skipped (never blocks)")
        next_step(pg)


def play_reading(pg, out, tag):
    check(open_lesson(pg, "reading"), "Read like a scientist opens")
    skip_video(pg)
    say(pg, "yes in dark craters"); check(answered(pg), "predict step passes"); next_step(pg)
    check(step_type(pg) == "read", "the read step shows the passage")
    check(pg.evaluate("() => /Cabeus crater/.test(document.querySelector('.sp-passage').textContent)"), "passage text on the card")
    pg.wait_for_timeout(400); shot(pg, out, f"speech_read_{tag}")
    # Read it aloud: typed words stand in for the ear
    pg.click("[data-aloud]")
    check(until(pg, "() => !!document.querySelector('[data-aloud-done]')", 3000), "Read it aloud listens, with Done")
    say(pg, " ".join(PASSAGE.split()[:30]))
    check(until(pg, "() => /30 words heard/.test(document.querySelector('.sp-aloud').textContent)", 3000), "the heard words are counted live")
    pg.click("[data-aloud-done]")
    check(until(pg, "() => /You read \\d+ of \\d+ words/.test(document.querySelector('.sp-aloud').textContent)", 6000), "counts come back (words read, pace)")
    txt = pg.evaluate("() => document.querySelector('.sp-aloud').textContent")
    check(not any(w in txt.lower() for w in GRADE_WORDS), "no score or label on the reading")
    pg.wait_for_timeout(300); shot(pg, out, f"speech_aloud_{tag}")
    # q1 choice (tap), q2 short answer (typed in the card), q3 find the sentence (keys)
    pg.click(".sp-opt[data-c=a]")
    check(until(pg, "() => /LCROSS crash/.test(document.querySelector('.sp-qp').textContent)", 6000), "q1 by tap, q2 shows")
    pg.fill(".sp-type input", "cabeus crater"); pg.press(".sp-type input", "Enter")
    check(until(pg, "() => !!document.querySelector('.sp-sent')", 6000), "q2 typed, q3 turns the sentences into buttons")
    check(keys_reach(pg, ".sp-sent"), "Tab reaches the sentences")
    pg.focus(".sp-sent[data-c=s7]"); pg.keyboard.press("Enter")
    check(answered(pg), "q3 found with the keyboard: the read step passes")
    next_step(pg)
    say(pg, "frozen water"); check(answered(pg), "the word step passes")
    pg.click("#aNext")
    check(until(pg, "() => !!document.querySelector('.a-badge') && /Reader/.test(document.querySelector('.a-badge').textContent)", 8000), "Reader patch earned")
    shot(pg, out, f"speech_read_patch_{tag}")


def play_wordlab(pg, out, tag):
    pg.click("#aMap"); pg.wait_for_timeout(800)
    check(open_lesson(pg, "wordlab"), "Word lab opens")
    say(pg, "how bright a surface is"); check(answered(pg), "the meaning step passes"); next_step(pg)
    check(step_type(pg) == "vocab", "the word lab step")
    shot(pg, out, f"speech_vocab_{tag}")
    items = {i["id"]: i for i in next(s for s in LES["wordlab"]["steps"] if s["accept"]["type"] == "vocab")["accept"]["items"]}
    trapped = False
    for _ in range(6):
        if pg.evaluate("() => !!document.querySelector('#aNext')"):
            break
        defn = pg.evaluate("() => (document.querySelector('.sp-def') || {}).textContent || ''")
        it = next((i for i in items.values() if i.get("kind") == "sentence" and i["term"] in defn), None) or \
            next((i for i in items.values() if i.get("kind", "word") == "word" and _define(i) and _define(i)[:20] in defn), None)
        if not it:
            check(False, f"vocab item not recognised: {defn!r}"); break
        if it.get("kind") == "sentence":
            pg.fill(".sp-type input", f"our boots sank into the {it['term']} near the rover"); pg.press(".sp-type input", "Enter")
        else:
            if not trapped and it.get("traps"):
                say(pg, it["traps"][0]["word"])
                trapped = until(pg, f"() => /{it['traps'][0]['note'].split()[1]}/i.test(document.getElementById('aFeedback').textContent)", 5000)
                check(trapped, f"a sound-alike ({it['traps'][0]['word']}) is caught with its meaning")
                if trapped:
                    shot(pg, out, f"speech_vocab_trap_{tag}")
            b = pg.evaluate(f"() => {{ const b = [...document.querySelectorAll('.sp-words .sp-opt')].find(x => x.textContent.trim().endsWith({json.dumps(it['term'])})); if (b) {{ b.click(); return true; }} return false; }}")
            if not b:
                say(pg, it["term"])
        pg.wait_for_timeout(1200)
    check(answered(pg), "every word done: the word lab passes")
    next_step(pg)
    say(pg, "hummocky"); check(answered(pg), "say it step passes")
    pg.click("#aNext")
    check(until(pg, "() => !!document.querySelector('.a-badge') && /Word Smith/.test(document.querySelector('.a-badge').textContent)", 8000), "Word Smith patch earned")


def _define(it):
    g = json.loads((ROOT / "backend" / "data" / "glossary.json").read_text())["terms"]
    return it.get("define") or (g.get(it["term"]) or {}).get("explain", "")


def play_retell(pg, out, tag):
    pg.click("#aMap"); pg.wait_for_timeout(800)
    check(open_lesson(pg, "retell"), "Tell it back opens")
    skip_video(pg)
    check(step_type(pg) == "summary", "the summary step")
    check(keys_reach(pg, "[data-tell-done], .sp-type input, [data-watch]"), "Tab reaches the summary controls")
    shot(pg, out, f"speech_summary_{tag}")
    pg.fill(".sp-type input", "an astronaut dropped a hammer and a feather on the moon and they landed at the same time")
    pg.press(".sp-type input", "Enter")
    check(answered(pg), "the summary passes")
    fb = pg.evaluate("() => document.getElementById('aFeedback').textContent")
    check("hammer" in fb and "key point" in fb.lower(), f"feedback names points told and one more ({fb.strip()[:90]})")
    check(not any(w in fb.lower() for w in GRADE_WORDS), "never a grade or 'wrong'")
    shot(pg, out, f"speech_summary_feedback_{tag}")
    next_step(pg)
    pg.click(".a-choice[data-c=no]") if pg.evaluate("() => !!document.querySelector('.a-choice[data-c=no]')") else say(pg, "no the feather is slower")
    check(answered(pg), "the Earth predict passes"); next_step(pg)
    pg.click(".a-choice[data-c=a15]"); check(answered(pg), "the mission choice passes")
    pg.click("#aNext")
    check(until(pg, "() => !!document.querySelector('.a-badge') && /Storyteller/.test(document.querySelector('.a-badge').textContent)", 8000), "Storyteller patch earned")
    shot(pg, out, f"speech_retell_patch_{tag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5484")
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        Path(a.out).mkdir(parents=True, exist_ok=True)
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, headless=True, args=LAUNCH_ARGS)
        for vw, vh in ((1440, 900), (1280, 720)):
            tag = f"{vw}x{vh}"
            print(f"-- {tag}")
            ctx = b.new_context(viewport={"width": vw, "height": vh}); silence(ctx)
            badges = [l["badge"]["id"] for l in COURSE["lessons"] if l.get("track", "core") == "core"]
            ctx.add_init_script("""try { if (!sessionStorage.getItem('sp-e2e')) { sessionStorage.setItem('sp-e2e', '1');
              localStorage.setItem('outpost-callsign', 'Nova'); localStorage.setItem('atm-mode', 'academy');
              localStorage.setItem('atm-academy', JSON.stringify({badges: %s, qualified: true}));
              localStorage.removeItem('outpost-brain'); } } catch (e) {}""" % json.dumps(badges))
            pg = ctx.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(a.base, wait_until="domcontentloaded")
            until(pg, "() => !!document.getElementById('modeAcademy')", 20000)
            pg.evaluate("() => document.getElementById('modeAcademy').click()")   # a qualified cadet opens on Mission
            check(until(pg, "() => !!document.querySelector('#aPanel .mp-top')", 60000), "Flight School map up")
            for play in (play_reading, play_wordlab, play_retell):
                try:
                    play(pg, a.out, tag)
                except Exception as e:   # noqa: BLE001
                    check(False, f"{play.__name__}: {e}")
            brain = pg.evaluate("() => JSON.parse(localStorage.getItem('outpost-brain') || 'null')")
            sp = ((brain or {}).get("speech") or {}).get("c", {}).get("moon", {})
            check(sp.get("read") == 1 and sp.get("summaries") == 1 and len(sp.get("words", {})) >= 4,
                  f"the Brain keeps counts: read {sp.get('read')}, summaries {sp.get('summaries')}, words {len(sp.get('words', {}))}")
            check("hammer" not in json.dumps(brain) and "cabeus crater" not in json.dumps(brain), "and never the words said")
            check(not errors, f"no page errors {errors[:2]}")
            ctx.close()
        b.close()
    print(f"{sum(results)}/{len(results)} ok")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
