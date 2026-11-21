// [0.5.6] Links, with no dead clicks (owner playtest 0.5.5: the Lesson 1 source card for the NPS rack card logged "link
// refused (not on the list)" four times and did nothing).
//
// Every link the app shows is one of two kinds, and says which:
//   a document the course keeps in its pack (course library `docs`, backend/app/course_library.py): the click opens its
//     pages in the app's picture viewer (media/lightbox.js), offline. Marked with a page icon, "Opens here".
//   any other web link: it opens in the system browser (the desktop shell's allow list, desktop/main/hardening.js
//     linkAllowed; hardening.test.js fails on a course link that is not listed). Marked with an arrow, "Opens in your
//     web browser".
// One capture-phase click handler and one MutationObserver, so every renderer's plain <a href target=_blank> is covered
// (lesson facts, source chips, the answer card, the Field Library) without each of them knowing.
import { openLightbox } from "./media/lightbox.js";

/** A link's address, compared without its #fragment (a PDF link may carry #page=2). Pure. */
export const linkKey = u => { try { const x = new URL(u, "http://local.invalid/"); x.hash = ""; return x.href; } catch (e) { return String(u || ""); } };

/** What a click on `href` does: {kind: "doc", doc} (opens here), "web" (the system browser), "ours" (the app). Pure. */
export function linkKind(href, docs, origin) {
  if (!href) return { kind: "none" };
  let u; try { u = new URL(href, origin || "http://local.invalid/"); } catch (e) { return { kind: "none" }; }
  const k = linkKey(u.href), d = (docs || []).find(x => linkKey(x.url) === k);
  if (d) return { kind: "doc", doc: d };
  if (origin && u.origin === origin) return { kind: "ours" };
  if (u.protocol === "https:" || u.protocol === "http:") return { kind: "web" };
  return { kind: "none" };
}

/** The viewer's items for a document: one per page. Pure. */
export const docItems = d => (d.pages || []).map((p, k) => ({ src: p.url, alt: p.alt || `Page ${k + 1}`,
  caption: `${d.title}${d.pages.length > 1 ? `, page ${k + 1} of ${d.pages.length}` : ""}`, credit: [d.credit || d.by, (d.licence || "").split(/[(.;]/)[0].trim()].filter(Boolean).join(" · ") }));

export const COPY = { here: "Opens here (saved with the course)", web: "Opens in your web browser" };

export function installLinks({ doc = document, win = window } = {}) {
  let docs = [];
  const origin = win.location.origin;
  const openDoc = d => openLightbox({ title: `${d.title}${d.by ? ` · ${d.by}` : ""}`, items: docItems(d) });
  const mark = a => {
    const href = a.getAttribute("href"); if (!href || href.startsWith("#")) return;
    const k = linkKind(href, docs, origin);
    a.classList.toggle("is-local-doc", k.kind === "doc");
    a.classList.toggle("is-web", k.kind === "web");
    // the link's own title (a source's full name) stays first; what a click does is added once
    if (a.dataset.linkTitle === undefined) a.dataset.linkTitle = a.getAttribute("title") || "";
    const own = a.dataset.linkTitle, say = k.kind === "doc" ? COPY.here : k.kind === "web" ? COPY.web : "";
    if (!say) return;
    a.title = own ? `${own} · ${say}` : say;
    if (k.kind === "web") { a.target = "_blank"; a.rel = "noopener"; }
  };
  const scan = root => { if (root.matches && root.matches("a[href]")) mark(root); if (root.querySelectorAll) root.querySelectorAll("a[href]").forEach(mark); };
  doc.addEventListener("click", e => {
    const a = e.target && e.target.closest && e.target.closest("a[href]"); if (!a) return;
    const k = linkKind(a.getAttribute("href"), docs, origin);
    if (k.kind !== "doc") return;
    e.preventDefault(); e.stopPropagation();
    openDoc(k.doc);
  }, true);
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1) scan(n); }))).observe(doc.body, { childList: true, subtree: true });
  scan(doc.body);
  const api = {
    /** The active course's documents (field_library.js, after its library loads). */
    setDocs(list) { docs = Array.isArray(list) ? list.filter(d => d && d.url && d.pages && d.pages.length) : []; scan(doc.body); },
    get docs() { return docs; },
    openDoc,
    kind: href => linkKind(href, docs, origin).kind,
  };
  try { (win.__outpost = win.__outpost || {}).links = api; } catch (e) { /* */ }
  return api;
}
