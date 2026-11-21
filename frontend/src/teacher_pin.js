// Teacher PIN (D7, docs/BRAIN.md §12): a real gate on top of the 3-second hold. The hold stops a young cadet, not an
// older one; safety counts and care notes need more in a school.
//
// Optional and per computer: a grown-up sets 4 to 8 digits in Settings → For grown-ups → Teacher PIN. From then on the
// hold asks for it before For grown-ups opens. Stored as a salted SHA-256 hash in localStorage "outpost-teacher-pin"
// ({v, salt, hash}), never the digits; never sent anywhere. Five wrong tries wait 30 seconds. Forgotten? Clearing the
// app's data on the computer removes it (docs/SCHOOL_IT.md); Start over (behind the PIN) removes it too.
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || {}) : {};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const KEY = "outpost-teacher-pin";
export const MAX_TRIES = 5;
export const LOCK_MS = 30000;
export const COPY = {
  title: "Teacher PIN",
  off: "No PIN yet. The 3-second hold is the only gate.",
  on: "A PIN is set. The hold asks for it before For grown-ups opens.",
  why: "Set one in a classroom: it keeps the safety counts and notes for grown-ups.",
  pin: "PIN (4 to 8 digits)",
  again: "PIN again",
  set: "Set PIN",
  change: "Change PIN",
  remove: "Remove PIN",
  saved: "PIN set.",
  removed: "PIN removed.",
  bad: "Use 4 to 8 digits.",
  mismatch: "The two PINs don't match.",
  forgot: "Forgot it? Clearing the app's data on this computer removes it. Start over removes it too.",
  ask: "Enter the teacher PIN",
  unlock: "Open",
  wrong: "That PIN isn't right.",
  wait: s => `Too many tries. Wait ${s} seconds.`,
};

const ls = () => { try { return typeof localStorage !== "undefined" ? localStorage : null; } catch (e) { return null; } };
export const validPin = p => typeof p === "string" && /^\d{4,8}$/.test(p);

function read(storage = ls()) {
  try { const r = JSON.parse((storage && storage.getItem(KEY)) || "null"); return r && r.v === 1 && /^[0-9a-f]{32}$/.test(r.salt) && /^[0-9a-f]{64}$/.test(r.hash) ? r : null; } catch (e) { return null; }
}
export const pinSet = (storage = ls()) => !!read(storage);

const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
async function digest(salt, pin) {
  const c = globalThis.crypto && globalThis.crypto.subtle;
  if (!c) throw new Error("no WebCrypto");
  return hex(await c.digest("SHA-256", new TextEncoder().encode(`${salt}:${pin}`)));
}
function newSalt() { const a = new Uint8Array(16); globalThis.crypto.getRandomValues(a); return hex(a.buffer); }

/** Set (or change) the PIN. false for an invalid PIN or no storage. */
export async function setPin(pin, storage = ls()) {
  if (!validPin(pin) || !storage) return false;
  const salt = newSalt();
  try { storage.setItem(KEY, JSON.stringify({ v: 1, salt, hash: await digest(salt, pin) })); return true; } catch (e) { return false; }
}
export function clearPin(storage = ls()) { try { if (storage) storage.removeItem(KEY); } catch (e) { /* */ } }

// wrong tries, in memory (a reload starts over: a slow-down, not a vault)
const tries = { n: 0, until: 0 };
export function lockedFor(now = Date.now()) { return tries.until > now ? Math.ceil((tries.until - now) / 1000) : 0; }
export function _resetTries() { tries.n = 0; tries.until = 0; }
/** Check a PIN: {ok} or {ok:false, wait?} (seconds to wait after MAX_TRIES wrong ones). No PIN set: always ok. */
export async function checkPin(pin, storage = ls(), now = Date.now()) {
  const r = read(storage);
  if (!r) return { ok: true };
  const w = lockedFor(now); if (w) return { ok: false, wait: w };
  const ok = validPin(pin) && (await digest(r.salt, pin)) === r.hash;
  if (ok) { _resetTries(); return { ok: true }; }
  tries.n++;
  if (tries.n >= MAX_TRIES) { tries.n = 0; tries.until = now + LOCK_MS; return { ok: false, wait: Math.ceil(LOCK_MS / 1000) }; }
  return { ok: false };
}

/** The gate's PIN step (pure): shown after the hold when a PIN is set. */
export function askHtml(msg = "") {
  return `<form class="gu-pin" data-gu-pin-form autocomplete="off"><label><b>${esc(COPY.ask)}</b>
      <input type="password" inputmode="numeric" pattern="[0-9]*" maxlength="8" autocomplete="off" data-gu-pin aria-describedby="guPinMsg"></label>
    <button type="submit" class="btn">${esc(COPY.unlock)}</button><p class="set-help" id="guPinMsg" role="status">${esc(msg)}</p></form>`;
}

/** The grown-up part: set, change or remove the PIN (pure). */
export function partHtml(set = pinSet()) {
  return `<div class="tp-zone"><p class="set-help">${esc(set ? COPY.on : COPY.off)} ${esc(set ? "" : COPY.why)}</p>
    <form class="tp-form" data-tp-form autocomplete="off">
      <label><span>${esc(COPY.pin)}</span><input type="password" inputmode="numeric" pattern="[0-9]*" maxlength="8" autocomplete="new-password" data-tp-pin></label>
      <label><span>${esc(COPY.again)}</span><input type="password" inputmode="numeric" pattern="[0-9]*" maxlength="8" autocomplete="new-password" data-tp-pin2></label>
      <button type="submit" class="btn">${esc(set ? COPY.change : COPY.set)}</button>
      ${set ? `<button type="button" class="btn-quiet" data-tp-remove>${esc(COPY.remove)}</button>` : ""}</form>
    <p class="set-help" data-tp-msg role="status"></p><p class="set-help">${esc(COPY.forgot)}</p></div>`;
}

const section = {
  id: "teacherpin", title: COPY.title, grownup: true,
  html: () => partHtml(),
  bind(el, { storage = ls() } = {}) {
    const form = el.querySelector("[data-tp-form]"), msg = el.querySelector("[data-tp-msg]");
    if (!form) return;
    const redraw = text => { el.innerHTML = partHtml(pinSet(storage)); section.bind(el, { storage }); const m = el.querySelector("[data-tp-msg]"); if (m) m.textContent = text; };
    form.onsubmit = async e => {
      e.preventDefault();
      const a = form.querySelector("[data-tp-pin]").value, b = form.querySelector("[data-tp-pin2]").value;
      if (!validPin(a)) { msg.textContent = COPY.bad; return; }
      if (a !== b) { msg.textContent = COPY.mismatch; return; }
      redraw((await setPin(a, storage)) ? COPY.saved : COPY.bad);
    };
    const rm = el.querySelector("[data-tp-remove]");
    if (rm) rm.onclick = () => { clearPin(storage); redraw(COPY.removed); };
    return { destroy() {} };
  },
};
if (typeof window !== "undefined") (O.settingsSections = O.settingsSections || []).push(section);
export default section;
