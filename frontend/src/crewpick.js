// [0.4.1] Crew talk with an exact answer (docs/GAMEPLAY.md §15.2). The router keeps a quiet spoken answer off a guess or
// a choice when Arc isn't sure it was for us (turn_router.crew_talk). If the words named one option exactly, the
// `heard` decision carries `pick` ({label, choice, heard}) and the voice bar offers it back as one chip:
// "Heard “B” · Use it". A click, Enter or controller A on the chip uses it (as a tap on that option); saying it again,
// clearly, still answers. Chatter that names no option gets no chip. The chip goes after PICK_MS or on the next turn.
export const PICK_MS = 8000;

/** The chip's words: the kid's own words, short. Pure (tested). */
export function pickText(pick) {
  const h = String((pick && (pick.heard || pick.label)) || "").trim();
  const w = h.length > 24 ? h.slice(0, 23).trimEnd() + "…" : h;
  return `Heard “${w}” · Use it`;
}

/** @param {Document} doc @param {(pick:object)=>boolean|void} use  run the pick (a tap on that option) */
export function createCrewPick(doc, use, { ms = PICK_MS, timers = globalThis } = {}) {
  let btn = null, cur = null, t = 0, before = null;
  function el() {
    if (btn) return btn;
    btn = doc.createElement("button");
    btn.type = "button"; btn.className = "crew-pick"; btn.id = "crewPick"; btn.hidden = true;
    btn.onclick = () => { const p = cur; hide(); if (p) use(p); };
    const row = doc.querySelector && doc.querySelector("#askbar .dock-row"), listen = doc.getElementById("listen");
    if (row && listen && listen.parentNode === row) row.insertBefore(btn, listen.nextSibling);
    else if (row) row.append(btn);
    return btn;
  }
  function show(pick) {
    if (!pick || !(pick.label || pick.heard)) return hide();
    const b = el();
    cur = pick;
    b.textContent = pickText(pick);
    b.setAttribute("aria-label", `Use your answer: ${pick.label || pick.heard}`);
    b.hidden = false;
    before = doc.activeElement && doc.activeElement !== b ? doc.activeElement : before;
    try { b.focus({ preventScroll: true }); } catch (e) { /* no focus in tests */ }   // Enter / controller A use it
    timers.clearTimeout(t); t = timers.setTimeout(hide, ms);
  }
  function hide() {
    timers.clearTimeout(t); t = 0;
    if (!btn || btn.hidden) { cur = null; return; }
    const had = doc.activeElement === btn;
    btn.hidden = true; cur = null;
    if (had && before && before.isConnected !== false) { try { before.focus({ preventScroll: true }); } catch (e) { /* */ } }
    before = null;
  }
  return { show, hide, get pick() { return cur; }, get el() { return btn; } };
}
