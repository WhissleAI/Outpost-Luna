"""The site picker flies the site the kid sees selected (owner's rc/2 play: "take command" started Malapert while
Shackleton Rim was the preselected "Best first pick"). On a fresh profile:
  - Shackleton Rim is preselected and tagged "Best first pick";
  - hovering another row (or its pin) highlights it but never selects it;
  - "take command" by voice starts the selected row;
  - a tapped row, or one moved to with the arrow keys, is what "take command" starts;
  - the ICE column never spills past the card (1440x900 and 1280x720).

  uv run --with playwright python frontend/tools/picker_select.py --base http://127.0.0.1:5398
"""
import argparse
import glob
import os
import sys

from playwright.sync_api import sync_playwright

SEED = """try{ localStorage.setItem('outpost-callsign','Comet');
  localStorage.setItem('atm-academy', JSON.stringify({badges:['scout','history','radio','sun','storm','ice','commander'], qualified:true}));
  localStorage.setItem('atm-mode','mission'); }catch(e){}"""
TYPED = "t => { const q = document.getElementById('q'); q.value = t; document.getElementById('askForm').requestSubmit(); }"


def run(base):
    exe = (sorted(glob.glob(os.path.expanduser("~/Library/Caches/ms-playwright/chromium_headless_shell-*/*/chrome-headless-shell"))) or [None])[-1]
    fails = []

    def check(cond, msg):
        print(("  ok   " if cond else "  FAIL ") + msg)
        if not cond:
            fails.append(msg)

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=exe, args=["--autoplay-policy=no-user-gesture-required"])

        def fresh(vw=1440, vh=900):
            ctx = b.new_context(viewport={"width": vw, "height": vh})
            pg = ctx.new_page()
            starts = []
            pg.on("request", lambda r: "/api/mission/start" in r.url and starts.append(r.post_data_json))
            pg.add_init_script(SEED)
            pg.goto(base)
            pg.wait_for_selector("#mStart", timeout=60000)
            pg.wait_for_timeout(1500)
            return ctx, pg, starts

        selected = lambda pg: pg.evaluate("document.querySelector('.mx-site[aria-checked=\"true\"]').dataset.site")

        # 1. preselected + hover + voice
        ctx, pg, starts = fresh()
        check(selected(pg) == "shackleton_rim", f"fresh profile preselects Shackleton Rim ({selected(pg)})")
        check(pg.evaluate("!!document.querySelector('.mx-site[data-site=\"shackleton_rim\"] .mx-rectag')"), "it carries the Best first pick tag")
        pg.hover('.mx-site[data-site="malapert_massif"]'); pg.wait_for_timeout(250)
        pg.hover('.mx-pin[data-site="de_gerlache_rim"]', force=True); pg.wait_for_timeout(250)
        pg.mouse.move(4, 400); pg.wait_for_timeout(200)
        check(selected(pg) == "shackleton_rim", f"hovering rows and pins never selects ({selected(pg)})")
        pg.evaluate(TYPED, "take command")
        pg.wait_for_selector(".cb-glass", timeout=60000)
        check(bool(starts) and starts[-1]["site"] == "shackleton_rim", f"voice 'take command' flies the selected row ({starts[-1] if starts else None})")
        ctx.close()

        # 2. a tapped row is what flies
        ctx, pg, starts = fresh()
        pg.click('.mx-site[data-site="connecting_ridge"]'); pg.wait_for_timeout(400)
        check(selected(pg) == "connecting_ridge", "a tap selects the row")
        pg.evaluate(TYPED, "take command")
        pg.wait_for_selector(".cb-glass", timeout=60000)
        check(bool(starts) and starts[-1]["site"] == "connecting_ridge", f"voice 'take command' flies the tapped row ({starts[-1] if starts else None})")
        ctx.close()

        # 3. arrow keys move the selection, and that row flies
        ctx, pg, starts = fresh()
        pg.focus('.mx-site[aria-checked="true"]'); pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(400)
        want = selected(pg)
        check(want != "shackleton_rim", f"ArrowDown moves the selection ({want})")
        pg.evaluate(TYPED, "start the mission")
        pg.wait_for_selector(".cb-glass", timeout=60000)
        check(bool(starts) and starts[-1]["site"] == want, f"'start the mission' flies the row the keys chose ({starts[-1] if starts else None})")
        ctx.close()

        # 4. the ICE column stays inside the card
        for vw, vh in ((1440, 900), (1280, 720)):
            ctx, pg, _ = fresh(vw, vh)
            spill = pg.evaluate("""() => { const card = document.getElementById('mPanel').getBoundingClientRect();
              return [...document.querySelectorAll('.mx-site .mx-v, .mx-cols span')].map(e => e.getBoundingClientRect().right - card.right).filter(d => d > 0.5); }""")
            check(not spill, f"{vw}x{vh}: the Sun / Earth / Ice columns stay inside the card {spill}")
            ctx.close()
        b.close()
    print("PASS" if not fails else f"FAIL ({len(fails)})")
    return 0 if not fails else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5398")
    sys.exit(run(ap.parse_args().base))
