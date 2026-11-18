// Settings → "What the app has learned" (docs/ON_DEVICE_LEARNING.md): what on-device learning holds for this cadet and
// this computer, in plain words; each learned name can be removed; "Reset learning" forgets all of it (two taps:
// "Reset learning", then "Yes, forget it"). Nothing here is ever uploaded, and no recordings are kept.
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  title: "What the app has learned",
  line: "The app learns how you talk, on this computer only. No recordings are kept.",
  empty: "Nothing learned yet.",
  remove: "Remove",
  reset: "Reset learning",
  confirm: "Yes, forget it",
  cancel: "Cancel",
  done: "Forgotten. The app starts learning again from now.",
  error: "Couldn't reach the app. Try again.",
};

/** The active cadet profile id ("p1".."p6"), as prefs.js stores it. */
export function activeProfile(storage = typeof localStorage !== "undefined" ? localStorage : null) {
  try { const s = JSON.parse(storage.getItem("outpost-profiles") || "null"); return (s && /^p\d{1,2}$/.test(s.active)) ? s.active : "p1"; }
  catch (e) { return "p1"; }
}

/** The view's HTML from GET /api/learn ({lines, learned: {aliases: [{heard, name}]}}). Pure. */
export function viewHtml(v) {
  if (!v) return `<p class="set-help">${esc(COPY.empty)}</p>`;
  const lines = (v.lines || []).map(t => `<li>${esc(t)}</li>`).join("");
  const al = ((v.learned || {}).aliases || []).filter(a => a && a.heard);
  const names = al.length ? `<ul class="lr-names">${al.map(a =>
    `<li><span>“${esc(a.heard)}” → ${esc(a.name)}</span> <button type="button" class="btn btn-quiet" data-lr-forget="${esc(a.heard)}" aria-label="${esc(COPY.remove)} ${esc(a.heard)}">${esc(COPY.remove)}</button></li>`).join("")}</ul>` : "";
  return `<ul class="lr-lines">${lines}</ul>${names}`;
}

const section = {
  id: "learning", title: COPY.title, after: "diagnostics", grownup: true,   // [0.4.1] in Settings → For grown-ups
  html: () => `<div class="lr-zone">
    <p class="set-help">${esc(COPY.line)}</p>
    <div data-lr-view aria-live="polite"></div>
    <button type="button" class="btn" data-lr-reset>${esc(COPY.reset)}</button>
    <span data-lr-confirm hidden><button type="button" class="btn btn-primary" data-lr-yes>${esc(COPY.confirm)}</button>
    <button type="button" class="btn" data-lr-no>${esc(COPY.cancel)}</button></span>
    <p class="set-help" data-lr-state role="status" aria-live="polite"></p></div>`,
  bind(el, { fetchFn = typeof fetch === "function" ? fetch : null } = {}) {
    const view = el.querySelector("[data-lr-view]"), st = el.querySelector("[data-lr-state]");
    const reset = el.querySelector("[data-lr-reset]"), conf = el.querySelector("[data-lr-confirm]");
    if (!view || !fetchFn) return;
    const pid = activeProfile();
    const load = () => fetchFn(`/api/learn?profile=${pid}`).then(r => (r.ok ? r.json() : null)).catch(() => null)
      .then(v => { view.innerHTML = viewHtml(v); wireForget(); });
    const post = (path, body) => fetchFn(path, { method: "POST", headers: { "Content-Type": "application/json", "X-Outpost-Reset": "1" },
      body: JSON.stringify(body || {}) }).then(r => r.ok).catch(() => false);
    function wireForget() {
      view.querySelectorAll("[data-lr-forget]").forEach(b => {
        b.onclick = async () => { if (await post(`/api/learn/forget?profile=${pid}`, { heard: b.dataset.lrForget })) load(); else st.textContent = COPY.error; };
      });
    }
    reset.onclick = () => { reset.hidden = true; conf.hidden = false; const y = conf.querySelector("[data-lr-no]"); if (y) y.focus(); };
    conf.querySelector("[data-lr-no]").onclick = () => { conf.hidden = true; reset.hidden = false; };
    conf.querySelector("[data-lr-yes]").onclick = async () => {
      const ok = await post(`/api/learn/reset?profile=${pid}`);
      st.textContent = ok ? COPY.done : COPY.error;
      conf.hidden = true; reset.hidden = false;
      if (ok) load();
    };
    load();
  },
};
if (typeof window !== "undefined") (O.settingsSections = O.settingsSections || []).push(section);
export default section;
