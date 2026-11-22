// Settings → For grown-ups → "Help improve Outpost Luna" (docs/ADULT_SESSIONS.md; backend app/adult_collect.py).
//   * An ADULT tester's opt-in, off by default, drawn only inside For grown-ups (the 3-second hold / teacher PIN):
//     a kid can't reach it without the gate.
//   * Turning it on needs the consent screen: the adult ticks that they are an adult and agree. It is tied to the
//     cadet profile it was turned on from; other profiles on this computer are never collected.
//   * Audio is a separate switch, off by default. A turn counter, "Export to share" (one redacted zip, saved where the
//     adult chooses: the desktop shell's save dialog, or a download in the browser) and "Delete everything".
//   * Nothing is sent. No network.
import { turnProfileId } from "./prefs.js";
import { holdButtonHtml, bindHold } from "./reset.js";

const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  title: "Help improve Outpost Luna",
  off: "Off. Nothing extra is kept.",
  on: "On for this profile.",
  what: "Keeps the words it heard and what the app did, to improve it.",
  where: "Stays on this computer. Nothing is sent.",
  share: "You choose whether to export and share a file.",
  start: "Turn on",
  stop: "Turn off",
  consentTitle: "Before you turn it on",
  consent: ["Kept: the words the app heard, and what it decided and said.",
    "Audio clips only if you turn them on below.",
    "No names. It stays on this computer. Nothing is sent.",
    "You can export a file to share, or delete everything."],
  agree: "I'm an adult, and I agree.",
  go: "Turn on",
  cancel: "Cancel",
  audio: "Also keep audio clips",
  audioHelp: "Each turn's audio, on this computer only.",
  count: n => (n === 1 ? "1 turn kept." : `${n} turns kept.`),
  clips: n => (n === 1 ? "1 audio clip." : `${n} audio clips.`),
  export: "Export to share…",
  del: "Hold to delete everything",
  deleted: "Deleted.",
  tag: "Improving",
  tagTitle: "Help improve Outpost Luna is on: turns are kept on this computer",
  state: { saving: "Saving…", saved: "Saved.", cancelled: "", error: "Couldn't save it. Try again." },
  error: "Couldn't reach the app. Try again.",
};

export const isDesktop = (ua = typeof navigator !== "undefined" ? navigator.userAgent : "") => /Electron\//.test(ua);

/** Is it on for the profile playing now? (st = GET /api/collect) */
export const onHere = (st, pid) => !!(st && st.on && st.profile === pid);

/** The part's HTML (pure; tests/collect_ui.test.js). view = "main" | "consent". */
export function viewHtml({ st = null, pid = "p1", view = "main" } = {}) {
  if (view === "consent") {
    return `<div class="pt-consent" role="group" aria-labelledby="colConsentH">
      <p class="set-help" id="colConsentH"><b>${esc(COPY.consentTitle)}</b></p>
      <ul class="pt-list">${COPY.consent.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
      <label class="a11y-sw pt-agree"><input type="checkbox" data-col-agree><span><b>${esc(COPY.agree)}</b></span></label>
      <span class="pt-row"><button type="button" class="btn btn-primary" data-col-go disabled>${esc(COPY.go)}</button>
      <button type="button" class="btn" data-col-cancel>${esc(COPY.cancel)}</button></span></div>`;
  }
  const on = onHere(st, pid), turns = (st && st.turns) || 0, clips = (st && st.clips) || 0;
  const head = `<p class="set-help pt-status"><span class="pt-lamp${on ? " is-rec" : " is-off"}" aria-hidden="true"></span>${esc(on ? COPY.on : COPY.off)}${turns ? ` ${esc(COPY.count(turns))}` : ""}${clips ? ` ${esc(COPY.clips(clips))}` : ""}</p>
    <p class="set-help">${esc(COPY.what)} ${esc(COPY.where)} ${esc(COPY.share)}</p>`;
  const sw = on
    ? `<label class="a11y-sw"><input type="checkbox" data-col-audio ${st && st.audio ? "checked" : ""}><span><b>${esc(COPY.audio)}</b><small>${esc(COPY.audioHelp)}</small></span></label>
      <span class="pt-row"><button type="button" class="btn" data-col-stop>${esc(COPY.stop)}</button></span>`
    : `<span class="pt-row"><button type="button" class="btn" data-col-start>${esc(COPY.start)}</button></span>`;
  const files = turns
    ? `<span class="pt-row"><button type="button" class="btn" data-col-export>${esc(COPY.export)}</button>
      ${holdButtonHtml(COPY.del, "data-col-delete")}</span>`
    : "";
  return `${head}${sw}${files}<p class="set-help" data-col-state role="status" aria-live="polite"></p>`;
}

// ---- the top bar's tag, while it is on for this profile ----
export function setTag(on, doc = typeof document !== "undefined" ? document : null) {
  if (!doc) return;
  let t = doc.getElementById("colTag");
  if (on && !t) {
    t = doc.createElement("span");
    t.id = "colTag"; t.className = "pt-tag"; t.setAttribute("role", "status"); t.title = COPY.tagTitle;
    t.innerHTML = `<span class="pt-lamp is-rec" aria-hidden="true"></span>${esc(COPY.tag)}`;
    const nav = doc.querySelector(".topnav");
    if (nav) nav.prepend(t); else doc.body.append(t);
  } else if (!on && t) t.remove();
}

const pid = () => { try { return turnProfileId(); } catch (e) { return "p1"; } };
const get = (fetchFn = fetch) => fetchFn("/api/collect").then(r => (r.ok ? r.json() : null)).catch(() => null);
const post = (path, body, fetchFn = fetch) => fetchFn(path, { method: "POST",
  headers: { "Content-Type": "application/json", "X-Outpost-Reset": "1" }, body: JSON.stringify(body || {}) });
export async function refresh(fetchFn = typeof fetch === "function" ? fetch : null) {
  if (!fetchFn) return null;
  const st = await get(fetchFn);
  setTag(onHere(st, pid()));
  return st;
}

/** Desktop: hand over to the shell (a save dialog). Browser: fetch the zip and let the browser save it. */
export async function exportZip({ w = window, fetchFn = fetch, onState = () => {} } = {}) {
  if (isDesktop(w.navigator && w.navigator.userAgent)) {
    w.__lunaCollect = d => onState(d && d.state);
    w.location.href = "/__outpost/collect-export";
    return "desktop";
  }
  onState("saving");
  try {
    const r = await post("/api/collect/export", {}, fetchFn);
    if (!r.ok) throw new Error(String(r.status));
    const url = URL.createObjectURL(await r.blob());
    const a = w.document.createElement("a");
    a.href = url; a.download = `outpost-luna-help-${new Date().toISOString().slice(0, 10)}.zip`;
    w.document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    onState("saved");
    return "browser";
  } catch (e) { onState("error"); return "error"; }
}

let view = "main";
const section = {
  id: "collect", title: COPY.title, after: "playtest", grownup: true,   // only in Settings → For grown-ups
  html: () => `<div class="pt-zone" data-col-zone>${viewHtml({ st: null, pid: pid(), view })}</div>`,
  bind(el, { fetchFn = typeof fetch === "function" ? fetch : null } = {}) {
    const zone = el.querySelector("[data-col-zone]");
    if (!zone || !fetchFn) return;
    let st = null, hold = null;
    const draw = (focus) => {
      if (hold) { hold.destroy(); hold = null; }
      zone.innerHTML = viewHtml({ st, pid: pid(), view });
      wire();
      const f = focus && zone.querySelector(focus);
      if (f) f.focus({ preventScroll: true });
    };
    const say = t => { const s = zone.querySelector("[data-col-state]"); if (s) s.textContent = t; };
    const load = async (focus) => { st = await get(fetchFn); setTag(onHere(st, pid())); draw(focus); };
    const set = async (body, focus) => {
      const r = await post("/api/collect", body, fetchFn).catch(() => null);
      view = "main";
      if (!r || !r.ok) { draw(); say(COPY.error); return; }
      await load(focus);
    };
    function wire() {
      const q = s => zone.querySelector(s);
      if (q("[data-col-start]")) q("[data-col-start]").onclick = () => { view = "consent"; draw("[data-col-agree]"); };
      if (q("[data-col-cancel]")) q("[data-col-cancel]").onclick = () => { view = "main"; draw("[data-col-start]"); };
      if (q("[data-col-agree]")) q("[data-col-agree]").onchange = e => { q("[data-col-go]").disabled = !e.target.checked; };
      if (q("[data-col-go]")) q("[data-col-go]").onclick = () => {
        if (!q("[data-col-agree]").checked) return;
        set({ on: true, audio: false, consent: true, adult: true, profile: pid() }, "[data-col-stop]");
      };
      if (q("[data-col-stop]")) q("[data-col-stop]").onclick = () => set({ on: false }, "[data-col-start]");
      if (q("[data-col-audio]")) q("[data-col-audio]").onchange = e =>
        set({ on: true, audio: e.target.checked, consent: true, adult: true, profile: pid() }, "[data-col-audio]");
      if (q("[data-col-export]")) q("[data-col-export]").onclick = e => {
        const b = e.currentTarget; b.disabled = true;
        exportZip({ fetchFn, onState: s => { say(COPY.state[s] ?? ""); if (s !== "saving") b.disabled = false; } });
      };
      const del = q("[data-col-delete]");
      if (del) hold = bindHold(del, { onFire: async () => {
        const r = await post("/api/collect/delete", {}, fetchFn).catch(() => null);
        if (!r || !r.ok) { say(COPY.error); throw new Error("delete failed"); }
        await load(); say(COPY.deleted);
      } });
    }
    load();
    return { destroy() { if (hold) hold.destroy(); } };
  },
};
if (typeof window !== "undefined") {
  (O.settingsSections = O.settingsSections || []).push(section);
  if (typeof document !== "undefined" && typeof fetch === "function") refresh();
}
export default section;
