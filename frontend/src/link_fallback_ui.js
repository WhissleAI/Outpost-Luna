// "Your web browser didn't open" (desktop/main/main.js openOutside, docs/DESKTOP.md "App updates"). A web link the
// page asks for opens in the system browser; on a computer where that fails (a Mac whose default browser app is gone
// says "The application can't be opened" and nothing else happens) the shell calls window.__lunaLink({url}) and the
// page shows the link with a Copy button, so it can be pasted into any browser. The update row uses the same block.
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const LINK_COPY = { line: "Your web browser didn't open. Copy the link:", copy: "Copy", copied: "Copied!" };

/** Only a web address is ever shown (the shell sends allow-listed https links; anything else shows nothing). */
const webUrl = u => (typeof u === "string" && /^https?:\/\/[^\s"<>]+$/i.test(u) ? u : "");

/** The block: the line, the link (read-only, selectable) and Copy. */
export function fallbackHtml(url) {
  const u = webUrl(url);
  if (!u) return "";
  return `<div class="lf-box"><p class="au-line">${esc(LINK_COPY.line)}</p><div class="lf-row">`
    + `<input class="lf-url" type="text" readonly value="${esc(u)}" aria-label="Link" spellcheck="false">`
    + `<button type="button" class="btn" data-lf-copy>${esc(LINK_COPY.copy)}</button></div></div>`;
}

/** Copy text: the clipboard API (allowed for our own origin), else select it and the old copy command. -> true | false */
export async function copyText(text, input = null, nav = typeof navigator !== "undefined" ? navigator : null, doc = typeof document !== "undefined" ? document : null) {
  try { if (nav && nav.clipboard && nav.clipboard.writeText) { await nav.clipboard.writeText(text); return true; } } catch (e) { /* fall through */ }
  try {
    if (input && input.select) { input.focus && input.focus(); input.select(); }
    return !!(doc && doc.execCommand && doc.execCommand("copy"));
  } catch (e) { return false; }
}

/** A click on Copy inside `root`: copy the link next to it and say so on the button. */
export async function onCopyClick(e) {
  const btn = e && e.target && e.target.closest ? e.target.closest("[data-lf-copy]") : null;
  if (!btn) return false;
  const box = btn.closest(".lf-box");
  const input = box && box.querySelector(".lf-url");
  if (!input) return false;
  const ok = await copyText(input.value, input);
  if (ok) btn.textContent = LINK_COPY.copied;
  else if (input.select) input.select();   // at least selected: Cmd/Ctrl+C works
  return ok;
}

/** The corner notice for any other link (a cited source, a NASA video page). */
export function showLinkNotice(s, doc = typeof document !== "undefined" ? document : null) {
  if (!doc || !doc.body) return null;
  const html = fallbackHtml(s && s.url);
  if (!html) return null;
  let n = doc.getElementById("lfNotice");
  if (!n) { n = doc.createElement("div"); n.id = "lfNotice"; n.className = "au-notice lf-notice"; n.setAttribute("role", "status"); doc.body.appendChild(n); }
  n.innerHTML = `${html}<button type="button" class="btn-icon" data-lf-close aria-label="Dismiss">&times;</button>`;
  n.onclick = e => {
    const t = e.target.closest ? e.target.closest("button") : null;
    if (t && t.dataset && "lfClose" in t.dataset) n.remove();
    else onCopyClick(e);
  };
  return n;
}

export function receiveLink(s) { showLinkNotice(s); return true; }

if (typeof window !== "undefined") window.__lunaLink = receiveLink;
