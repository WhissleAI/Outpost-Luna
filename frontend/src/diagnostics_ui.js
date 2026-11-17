// Settings → Help & diagnostics (issue #92, docs/DIAGNOSTICS.md): what a diagnostics file holds, listed before anything
// is saved, and "Save a diagnostics file…". In the desktop app the page navigates to /__outpost/diagnostics: the shell
// asks where to save (a save dialog), the backend builds the zip, the shell writes it, then calls window.__lunaDiag with
// the result. In a browser (make dev) the page fetches the zip and the browser saves it. Nothing is ever uploaded.
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  line: "For support. No audio, no words, no keys. Never uploaded.",
  save: "Save a diagnostics file…",
  names: "Include the names the app learned (how your child says them)",
  state: { saving: "Saving…", saved: "Saved.", cancelled: "", error: "Couldn't save it. Try again." },
};
export const FALLBACK = ["App, system and hardware details", "App and model versions", "Speed and error counts",
  "Recent technical logs"];

export const isDesktop = (ua = typeof navigator !== "undefined" ? navigator.userAgent : "") => /Electron\//.test(ua);

/** The list's lines from GET /api/diagnostics/contents ({items: [{name, what}]}). */
export const items = c => (c && Array.isArray(c.items) && c.items.length ? c.items.map(x => x.what) : FALLBACK);

let last = null;
const load = () => fetch("/api/diagnostics/contents").then(r => (r.ok ? r.json() : null)).then(c => (last = c)).catch(() => null);

/** Desktop: hand over to the shell. Browser: fetch the zip and let the browser save it. */
export async function save({ w = window, fetchFn = fetch, onState = () => {}, names = false } = {}) {
  if (isDesktop(w.navigator && w.navigator.userAgent)) {
    w.__lunaDiag = d => onState(d && d.state);
    w.location.href = "/__outpost/diagnostics" + (names ? "?names=1" : "");
    return "desktop";
  }
  onState("saving");
  try {
    const r = await fetchFn("/api/diagnostics/bundle", { method: "POST", headers: { "Content-Type": "application/json" }, body: names ? JSON.stringify({ learning_aliases: true }) : "{}" });
    if (!r.ok) throw new Error(String(r.status));
    const url = URL.createObjectURL(await r.blob());
    const a = w.document.createElement("a");
    a.href = url; a.download = `outpost-luna-diagnostics-${new Date().toISOString().slice(0, 10)}.zip`;
    w.document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    onState("saved");
    return "browser";
  } catch (e) { onState("error"); return "error"; }
}

const section = {
  id: "diagnostics", title: "Help & diagnostics", after: "storage",
  html: () => `<div class="dg-zone">
    <p class="set-help">${esc(COPY.line)}</p>
    <ul class="dg-list" data-dg-items>${items(last).map(t => `<li>${esc(t)}</li>`).join("")}</ul>
    <label class="set-help"><input type="checkbox" data-dg-names> ${esc(COPY.names)}</label>
    <button type="button" class="btn" data-dg-save>${esc(COPY.save)}</button>
    <p class="set-help" data-dg-state role="status" aria-live="polite"></p></div>`,
  bind(el) {
    const list = el.querySelector("[data-dg-items]"), btn = el.querySelector("[data-dg-save]"), st = el.querySelector("[data-dg-state]");
    if (!btn) return;
    load().then(c => { if (c && list) list.innerHTML = items(c).map(t => `<li>${esc(t)}</li>`).join(""); });
    const onState = s => {
      st.textContent = COPY.state[s] ?? "";
      btn.disabled = s === "saving";
    };
    const names = el.querySelector("[data-dg-names]");
    btn.onclick = () => save({ onState, names: !!(names && names.checked) });
  },
};
if (typeof window !== "undefined") {
  (O.settingsSections = O.settingsSections || []).push(section);
  if (typeof fetch === "function" && typeof document !== "undefined") load();
}
export default section;
