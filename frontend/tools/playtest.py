"""Novice playtest driver (docs/PLAYTEST.md): walk every step of every lesson the way a 7-year-old who knows nothing
about the Moon would, and record what the screen offers at each rung of the hint ladder.

For each step it screenshots the step as it opens, then makes up to three wrong tries a novice would make (tap a dot
that isn't it, pick a wrong card, mumble), screenshotting after each, and logs: the prompt, the "do this" line,
the feedback and hint, whether each place the step names is on screen, facing the camera and labelled, and how many
unlabelled place dots are showing. Then it goes through the check ride, the site picker, the cabin's first shift, the
debrief, and mode switches in the middle of a step.

  uv run --with playwright python frontend/tools/playtest.py --base http://localhost:5299 --out /tmp/pt --tag before

Writes <out>/<tag>/*.jpg and <out>/<tag>/log.json. Exit code 1 on console errors.
"""
import argparse
import glob
import io
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
COURSE = json.load(open(os.path.join(ROOT, "backend", "data", "academy", "course.json")))
sys.path.insert(0, os.path.dirname(__file__))
from ux_shots import answer_for, _Vocab  # noqa: E402
IGNORE = ("favicon", "/api/voices", "404 (Not Found)", "WebSocket", "ws/")

# what the step names on the Moon (ids from places.json or mission sites)
def named_places(st):
    a = st["accept"]
    if a["type"] in ("intent", "tap", "earth_view"):
        return [a["place"]]
    if a["type"] == "route":
        return list(a["stops"])
    if a["type"] == "compare":
        return [o["id"] for o in a["options"]]
    return []


PROBE = """(ids) => {
  const O = window.__outpost, g = O.globe, P = document.getElementById('aPanel');
  const sites = O.__sites || [];
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.2 && !el.closest('[hidden]'); };
  const out = {};
  for (const id of ids) {
    const f = O.placeById(id) || sites.find(s => s.id === id);
    if (!f) { out[id] = {missing: true}; continue; }
    const p = g.project(f.lat, f.lon);
    const W = innerWidth, H = innerHeight, onScreen = p.facing && p.x > 0 && p.x < W && p.y > 0 && p.y < H;
    const top = onScreen ? document.elementFromPoint(p.x, p.y) : null;
    const covered = !!(top && P.contains(top));
    const short = (f.name || id).split(' (')[0].toLowerCase();
    const labels = [...document.querySelectorAll('#stage *')].filter(e => !P.contains(e) && e.children.length === 0 && vis(e)
      && (e.textContent || '').toLowerCase().includes(short));
    const near = labels.some(e => { const r = e.getBoundingClientRect(); return Math.hypot(r.x + r.width / 2 - p.x, r.y + r.height / 2 - p.y) < 160; });
    out[id] = {name: f.name, onScreen, facing: p.facing, covered, labelled: onScreen && near, x: Math.round(p.x), y: Math.round(p.y)};
  }
  const ghosts = document.querySelector('.ghosts');
  const dotsOn = !!(ghosts && ghosts.style.display !== 'none');
  const guides = [...document.querySelectorAll('.gd-mark')].filter(vis).map(e => e.textContent.trim());
  const text = sel => { const e = P.querySelector(sel); return e ? e.textContent.replace(/\\s+/g, ' ').trim() : ''; };
  return {places: out, decorDots: dotsOn, guides,
    prompt: text('.a-prompt'), how: [...P.querySelectorAll('.a-how')].map(e => e.textContent.trim()).join(' | '),
    intro: text('.a-intro'), feedback: text('#aFeedback'), hint: text('.a-hint'),
    buttons: [...P.querySelectorAll('button')].filter(vis).map(b => (b.textContent || b.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim()).filter(Boolean)};
}"""

# a spot on the visible Moon, away from the step's places (a novice's random tap on a dot that isn't it)
DECOY = """(ids) => {
  const O = window.__outpost, g = O.globe, P = document.getElementById('aPanel'), sites = O.__sites || [];
  const tg = ids.map(id => O.placeById(id) || sites.find(s => s.id === id)).filter(Boolean);
  const c = g.centerLatLon();
  const ang = (a, b) => { const r = Math.PI / 180; return Math.acos(Math.min(1, Math.sin(a.lat*r)*Math.sin(b.lat*r) + Math.cos(a.lat*r)*Math.cos(b.lat*r)*Math.cos((a.lon-b.lon)*r))) / r; };
  for (const [dl, dn] of [[20, -25], [-15, 30], [25, 25], [-25, -30], [5, -40], [10, 40], [0, 0]]) {
    const q = {lat: Math.max(-85, Math.min(85, c.lat + dl)), lon: c.lon + dn};
    if (tg.some(t => ang(q, t) < 18)) continue;
    const p = g.project(q.lat, q.lon); if (!p.facing) continue;
    const top = document.elementFromPoint(p.x, p.y);
    if (top && top.tagName === 'CANVAS') return {x: p.x, y: p.y};
  }
  return null;
}"""


def wrong_option(st, page):
    """A wrong button a novice might pick (the first option that isn't the answer)."""
    a = st["accept"]
    ans = a.get("answer")
    if a["type"].startswith("vocab_"):
        ans = None
    for b in page.query_selector_all("#aInput .a-choice, #aInput .v-opt, #aInput .a-order"):
        if not b.is_visible() or b.is_disabled():
            continue
        c = b.get_attribute("data-c") or b.get_attribute("data-say") or b.get_attribute("data-id") or ""
        lab = (b.text_content() or "").lower()
        if ans and c == ans:
            continue
        if a["type"] == "command":
            want = answer_for(st).split()[-1]
            if want in lab or want in c:
                continue
        if a["type"].startswith("vocab_"):
            right = answer_for(st, vocab=_Vocab()).lower()
            if a["term"] in lab or (right and right[:20] in lab):
                continue
        if a["type"] == "globe_side" and c == a["want"]:
            continue
        return b
    return None


def open_lesson(page, lid):
    page.wait_for_selector(f'.pin[data-l="{lid}"]', state="attached", timeout=15000)
    if not page.query_selector(f'#aStart[data-l="{lid}"]'):
        page.evaluate("id => document.querySelector('.pin[data-l=\"' + id + '\"]').click()", lid)
        page.wait_for_selector(f'#aStart[data-l="{lid}"]', timeout=15000)
    page.click("#aStart")


def shot(page, out, name):
    from PIL import Image
    png = page.screenshot()
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.save(os.path.join(out, name + ".jpg"), quality=55)


def run(base, out, only=None):
    os.makedirs(out, exist_ok=True)
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    log, errs = {"steps": [], "screens": []}, []
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                                          "--autoplay-policy=no-user-gesture-required", "--use-gl=angle", "--use-angle=swiftshader"])
        ctx = b.new_context(viewport={"width": 1280, "height": 720})
        ctx.add_init_script("""try{localStorage.setItem('outpost-callsign','Nova');localStorage.setItem('atm-theme','dark');
          localStorage.setItem('atm-academy', JSON.stringify({badges:[], qualified:false}));}catch(e){}""")
        page = ctx.new_page(); page.set_default_timeout(60000)
        page.on("console", lambda m: m.type == "error" and not any(x in m.text for x in IGNORE) and errs.append(m.text))
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(base)
        page.wait_for_selector(".mp-card", timeout=30000)
        page.evaluate("fetch('/api/mission/sites').then(r=>r.json()).then(d=>window.__outpost.__sites=d.sites)")
        page.wait_for_timeout(1500)
        shot(page, out, "00_map")
        log["screens"].append({"screen": "map", **page.evaluate(PROBE, [])})
        for L in COURSE["lessons"]:
            if only and L["id"] not in only:
                continue
            if L.get("ride"):
                continue
            open_lesson(page, L["id"])
            page.wait_for_selector("#aInput", state="attached", timeout=15000)
            for k, st in enumerate(L["steps"]):
                tag = f"{L['id']}_{k + 1}"
                page.wait_for_timeout(2600)
                ids = named_places(st)
                rec = {"lesson": L["id"], "step": k + 1, "type": st["accept"]["type"], "open": page.evaluate(PROBE, ids)}
                shot(page, out, tag + "_a_open")
                tries = []
                t_open = time.time() - 2.6
                for m in range(3):
                    if page.query_selector("#aNext"):
                        break
                    if m == 2:   # the reveal waits for 3 real misses and ~20 s on the step (grade.reveal_due)
                        page.wait_for_timeout(max(0, int((21 - (time.time() - t_open)) * 1000)))
                    t = st["accept"]["type"]
                    did = ""
                    if t in ("tap", "intent", "terminator", "route"):
                        n = len(st["accept"].get("stops", [])) if t == "route" else 1
                        for _ in range(n):
                            d = page.evaluate(DECOY, ids)
                            if not d:
                                break
                            page.mouse.click(d["x"], d["y"]); page.wait_for_timeout(350)
                        did = "tapped a dot that isn't it"
                    elif t == "predict":
                        did = "predict: any guess passes"
                        btn = page.query_selector("#aInput .a-choice")
                        btn.click()
                    else:
                        btn = wrong_option(st, page)
                        if btn:
                            did = "picked: " + (btn.text_content() or "").strip()
                            btn.click()
                        elif m >= 1 and st["accept"].get("all"):   # a half readback (a real try, wrong)
                            did = "typed: " + st["accept"]["all"][0][0]
                            page.fill("#q", st["accept"]["all"][0][0]); page.press("#q", "Enter")
                        else:   # a kid with no idea asks for help (routed to the step's hint, not a miss)
                            did = "typed: what do I do"
                            page.fill("#q", "what do I do"); page.press("#q", "Enter")
                    page.wait_for_timeout(1800)
                    pr = page.evaluate(PROBE, ids)
                    tries.append({"did": did, **pr})
                    shot(page, out, f"{tag}_b_miss{m + 1}")
                rec["tries"] = tries
                log["steps"].append(rec)
                if not page.query_selector("#aNext") and not page.query_selector(".a-badge"):   # still stuck after 3 (should never happen): answer it
                    page.fill("#q", answer_for(st, vocab=_Vocab())); page.press("#q", "Enter")
                    page.wait_for_timeout(2500)
                if k < len(L["steps"]) - 1:
                    page.wait_for_selector("#aNext", timeout=20000); page.click("#aNext")
                else:
                    page.wait_for_selector(".a-badge", timeout=20000); page.wait_for_timeout(1200)
                    shot(page, out, f"{L['id']}_z_patch")
                    log["screens"].append({"screen": f"patch {L['id']}", **page.evaluate(PROBE, [])})
                    page.click("#aMap"); page.wait_for_selector(".mp-card", timeout=15000)
        # ---- check ride ----
        if not only or "checkride" in only:
            L = next(l for l in COURSE["lessons"] if l.get("ride"))
            open_lesson(page, L["id"])
            page.wait_for_selector("#aInput", state="attached", timeout=15000)
            for k, st in enumerate(L["steps"]):
                page.wait_for_timeout(3000)
                rec = {"lesson": "checkride", "step": k + 1, "type": st["accept"]["type"], "open": page.evaluate(PROBE, [])}
                shot(page, out, f"checkride_{k + 1}_a_open")
                page.fill("#q", "um what"); page.press("#q", "Enter"); page.wait_for_timeout(1800)
                rec["tries"] = [{"did": "typed: um what", **page.evaluate(PROBE, [])}]
                shot(page, out, f"checkride_{k + 1}_b_miss1")
                log["steps"].append(rec)
                if not page.query_selector("#aNext"):
                    page.fill("#q", answer_for(st)); page.press("#q", "Enter"); page.wait_for_timeout(3000)
                if page.query_selector("#aNext"):
                    page.click("#aNext")
            page.wait_for_timeout(2500)
            shot(page, out, "checkride_z_end")
            log["screens"].append({"screen": "checkride end", **page.evaluate(PROBE, [])})
        page.goto(base); page.wait_for_selector(".mp-card", timeout=30000); page.wait_for_timeout(1500)
        # ---- mode switch in the middle of a step ----
        if True:
            open_lesson(page, "history"); page.wait_for_timeout(2500)
            for _ in range(3):   # the route step: the owner's stuck moment
                if page.query_selector("#aNext"): page.click("#aNext"); page.wait_for_timeout(500)
                page.fill("#q", answer_for(COURSE["lessons"][1]["steps"][len(page.query_selector_all(".a-steps i.is-done"))], vocab=_Vocab())); page.press("#q", "Enter"); page.wait_for_timeout(2500)
            if page.query_selector("#aNext"): page.click("#aNext"); page.wait_for_timeout(2500)
            shot(page, out, "switch_0_lesson_step")
            page.click("#modeMission"); page.wait_for_timeout(2500)
            shot(page, out, "switch_1_lesson_to_mission")
            log["screens"].append({"screen": "switch lesson -> mission", **page.evaluate(PROBE, [])})
            page.click("#libraryBtn"); page.wait_for_timeout(2500)
            shot(page, out, "switch_2_mission_to_library")
            page.click("#modeAcademy"); page.wait_for_timeout(2500)
            shot(page, out, "switch_3_library_to_school")
            log["screens"].append({"screen": "switch library -> school", **page.evaluate(PROBE, [])})
        # ---- site picker, first shift, debrief ----
        page.click("#modeMission"); page.wait_for_timeout(3000)
        shot(page, out, "mission_1_picker")
        log["screens"].append({"screen": "picker", "text": page.evaluate("document.getElementById('mPanel') ? document.getElementById('mPanel').innerText : ''")})
        if page.query_selector("#mStart"):
            page.click("#mStart"); page.wait_for_timeout(5000)
            shot(page, out, "mission_2_cabin_first")
            log["screens"].append({"screen": "cabin first shift", "text": page.evaluate("document.body.innerText.slice(0, 1500)")})
            page.wait_for_timeout(9000)
            shot(page, out, "mission_3_cabin_idle")
            page.evaluate("window.__cabinTest && window.__cabinTest.debrief('survived')"); page.wait_for_timeout(2500)
            shot(page, out, "mission_4_debrief")
            log["screens"].append({"screen": "debrief", "text": page.evaluate("document.body.innerText.slice(0, 1500)")})
        b.close()
    json.dump(log, open(os.path.join(out, "log.json"), "w"), indent=1)
    return errs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5299")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="run")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    errs = run(a.base, os.path.join(a.out, a.tag), set(filter(None, a.only.split(","))))
    for e in errs:
        print("ERR", e[:300])
    sys.exit(1 if errs else 0)
