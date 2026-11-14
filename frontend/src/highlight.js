// Key-span highlighting + enrichment (docs/ACCESSIBILITY.md, docs/VOCABULARY.md).
// In cards, captions, lesson text and the radio log we mark four kinds of span, each with a shape as well as a colour
// (never colour alone):
//   place     places and hardware (/api/places)            solid underline + ⌖ glyph; tap/Enter → the globe flies there
//   number    numbers with units ("40 percent", "6 days")   boxed, tabular figures
//   term      space words (/api/glossary)                   dotted underline + "?" badge; tap/Enter → mini glossary card
//                                                           (kid meaning, NASA crew-audio source, "Hear it", "Hear the crew")
//   resource  mission resources (power, life support, dose, shields, …)   double underline
// Sources: the glossary and places from the backend, plus the Arc Tagger read-out spans (`readout.mentions`,
// `readout.numbers`) of the latest answer.

// ---------- pure helpers (tests/a11y.test.js) ----------

export const RESOURCES = ["life support", "solar panels", "power", "shields", "dose", "battery", "oxygen", "water", "ice",
  "rover", "shelter", "greenhouse", "radiation"];
const UNITS = "%|percent|km|kilometers?|kilometres?|meters?|metres?|mSv|millisieverts?|hours?|days?|minutes?|seconds?|degrees|°|kg|years?|miles?";
export const NUM_RE = new RegExp(`\\b\\d[\\d,]*(?:\\.\\d+)?\\s?(?:${UNITS})(?![\\w])|\\b\\d[\\d,]*(?:\\.\\d+)?(?:\\s?(?:–|-|to)\\s?\\d+)?\\b`, "gi");

const esc = s => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** A lexicon: {terms: {form: term}, places: {name: id}, resources: [...], extra: [mentions]} → one matcher. */
export function buildMatcher({ terms = {}, places = {}, resources = RESOURCES, extra = [] } = {}) {
  const items = [];
  Object.entries(terms).forEach(([form, term]) => items.push({ s: form, kind: "term", ref: term }));
  Object.entries(places).forEach(([name, id]) => items.push({ s: name, kind: "place", ref: id }));
  resources.forEach(r => items.push({ s: r, kind: "resource", ref: r }));
  extra.forEach(m => { if (m && !items.some(x => x.s.toLowerCase() === m.toLowerCase())) items.push({ s: m, kind: "place", ref: places[m] || "" }); });
  items.sort((a, b) => b.s.length - a.s.length);
  const by = new Map(items.map(x => [x.s.toLowerCase(), x]));
  const alt = items.filter(x => x.s.length >= 3).map(x => esc(x.s)).join("|");
  const re = alt ? new RegExp(`(?<![\\p{L}\\p{N}])(?:${alt})(?![\\p{L}\\p{N}])`, "giu") : null;
  return { re, by };
}

/** text → [{text, kind?, ref?}]: words/phrases from the lexicon plus numbers (with units when present). */
export function tokenize(text, m) {
  const t = String(text || ""), hits = [];
  if (m && m.re) for (const x of t.matchAll(m.re)) { const it = m.by.get(x[0].toLowerCase()); if (it) hits.push({ a: x.index, b: x.index + x[0].length, kind: it.kind, ref: it.ref }); }
  for (const x of t.matchAll(NUM_RE)) {
    const a = x.index, b = a + x[0].length;
    if (/^\d{4}$/.test(x[0])) continue;                       // a bare year reads as a date, not a quantity
    if (!hits.some(h => a < h.b && b > h.a)) hits.push({ a, b, kind: "number", ref: x[0] });
  }
  hits.sort((p, q) => p.a - q.a || q.b - p.b);
  const out = []; let pos = 0;
  for (const h of hits) {
    if (h.a < pos) continue;
    if (h.a > pos) out.push({ text: t.slice(pos, h.a) });
    out.push({ text: t.slice(h.a, h.b), kind: h.kind, ref: h.ref }); pos = h.b;
  }
  if (pos < t.length) out.push({ text: t.slice(pos) });
  return out;
}

// ---------- DOM ----------

const LABEL = { place: "Place", number: "Number", term: "Space word", resource: "Mission resource" };
const SELECTORS = "#cardSay, #cardStory, .a-prompt, .a-brief p, .a-feedback, .a-hint, .m-log li, .m-radio p, .m-event, [data-hl]";

export function initHighlight({ api, say, playCrew, flyTo } = {}) {
  if (typeof document === "undefined") return null;
  const O = (window.__outpost = window.__outpost || { stepRenderers: {} });
  const lex = { terms: {}, places: {}, extra: [] }, glossary = {};
  let m = buildMatcher(lex);

  async function load() {
    try {
      const g = await (await fetch("/api/glossary")).json();
      g.terms.forEach(t => { glossary[t.term] = t; (t.forms || [t.term]).forEach(f => { lex.terms[f] = t.term; }); });
    } catch (e) { /* glossary offline: no term marks */ }
    try {
      const ps = api && api.places ? await api.places() : [];
      ps.forEach(p => { if (p.name && p.name.length >= 4 && !/^(the )?moon$/i.test(p.name)) lex.places[p.name] = p.id; });
    } catch (e) { /* no places */ }
    m = buildMatcher(lex); scan(document.body);
  }
  /** The Arc Tagger read-out of the latest answer: its mentions become place marks (when not already known). */
  function noteReadout(r) {
    const x = r && r.readout; if (!x || !x.available) return;
    lex.extra = (x.mentions || []).filter(s => s && s.length > 2).slice(0, 8);
    m = buildMatcher(lex);
  }
  if (api && api.ask && !api.ask.__hl) {         // wrap once: every answer's read-out feeds the marks
    const orig = api.ask.bind(api);
    api.ask = async (...a) => { const r = await orig(...a); try { noteReadout(r); } catch (e) { /* ignore */ } return r; };
    api.ask.__hl = true;
  }

  function markEl(el) {
    const text = el.textContent;
    if (!text || el.dataset.hlText === text) return;
    const parts = tokenize(text, m);
    if (!parts.some(p => p.kind)) { el.dataset.hlText = text; return; }
    if (el.children.length && !el.querySelector(".hl")) {       // has structure (links, buttons): only mark text nodes
      markTextNodes(el); el.dataset.hlText = el.textContent; return;
    }
    el.textContent = "";
    parts.forEach(p => el.append(p.kind ? node(p) : document.createTextNode(p.text)));
    el.dataset.hlText = el.textContent;
    if (el.id === "cardSay") chips(el, parts);
  }
  function markTextNodes(el) {
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: n => n.parentElement.closest("a, button, .hl") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    const nodes = []; while (walk.nextNode()) nodes.push(walk.currentNode);
    nodes.forEach(n => {
      const parts = tokenize(n.nodeValue, m); if (!parts.some(p => p.kind)) return;
      const f = document.createDocumentFragment(); parts.forEach(p => f.append(p.kind ? node(p) : document.createTextNode(p.text)));
      n.replaceWith(f);
    });
  }
  function node(p) {
    const e = document.createElement("mark");
    e.className = `hl hl-${p.kind}`; e.textContent = p.text; e.dataset.kind = p.kind; e.dataset.ref = p.ref || "";
    const live = (p.kind === "term" && glossary[p.ref]) || (p.kind === "place" && p.ref);
    if (live) {
      e.tabIndex = 0; e.setAttribute("role", "button");
      e.setAttribute("aria-label", p.kind === "term" ? `Space word: ${p.text}. Press for its meaning` : `Place: ${p.text}. Press to fly there`);
    } else e.title = LABEL[p.kind];
    return e;
  }
  /** Enrichment chips under the card: the space words and places in this answer, one tap away. */
  function chips(el, parts) {
    let box = el.parentElement.querySelector(".hl-chips");
    if (!box) { box = document.createElement("div"); box.className = "hl-chips"; box.setAttribute("aria-label", "In this answer"); el.after(box); }
    const seen = new Set(), items = parts.filter(p => (p.kind === "term" && glossary[p.ref]) || (p.kind === "place" && p.ref))
      .filter(p => { const k = p.kind + p.ref; if (seen.has(k)) return false; seen.add(k); return true; }).slice(0, 5);
    box.innerHTML = ""; box.hidden = !items.length;
    items.forEach(p => {
      const b = document.createElement("button"); b.type = "button"; b.className = `hl-chip hl-chip-${p.kind}`;
      b.textContent = p.kind === "term" ? `? ${p.ref}` : `⌖ ${p.text}`; b.dataset.kind = p.kind; b.dataset.ref = p.ref;
      b.setAttribute("aria-label", p.kind === "term" ? `What does ${p.ref} mean?` : `Fly to ${p.text}`);
      box.append(b);
    });
  }
  /** Caption words (caption.js): add the mark classes to the word spans themselves (timing spans stay intact). */
  function markCaption(spans, words) {
    const text = words.join(" "), parts = tokenize(text, m);
    let pos = 0; const starts = words.map(w => { const a = pos; pos += w.length + 1; return a; });
    let c = 0;
    parts.forEach(p => {
      const a = c, b = c + p.text.length; c = b;
      if (!p.kind) return;
      starts.forEach((s, i) => {
        if (s < b && s + words[i].length > a && spans[i]) {
          spans[i].classList.add("hl", "hl-" + p.kind); spans[i].dataset.kind = p.kind; spans[i].dataset.ref = p.ref || "";
          if ((p.kind === "term" && glossary[p.ref]) || (p.kind === "place" && p.ref)) { spans[i].tabIndex = 0; spans[i].setAttribute("role", "button"); }
        }
      });
    });
  }

  // ---- the mini glossary card ----
  let cardEl = null, returnTo = null;
  function termCard(term, from) {
    const t = glossary[term]; if (!t) return;
    returnTo = from || document.activeElement;
    if (!cardEl) {
      cardEl = document.createElement("div"); cardEl.className = "hl-card"; cardEl.setAttribute("role", "dialog");
      cardEl.setAttribute("aria-modal", "false"); cardEl.setAttribute("aria-labelledby", "hlCardTitle"); document.body.append(cardEl);
      cardEl.addEventListener("keydown", e => { if (e.key === "Escape") closeCard(); });
    }
    const src = t.source || {};
    cardEl.innerHTML = `<header><span class="eyebrow">Space word</span><button type="button" class="x" data-x aria-label="Close">&times;</button></header>
      <h3 id="hlCardTitle">${escH(t.term)}</h3><p>${escH(t.explain)}</p>
      ${src.url ? `<p class="hl-src">Heard in: <a href="${escH(src.url)}" target="_blank" rel="noopener">${escH(src.title)}</a></p>` : ""}
      <div class="hl-acts"><button type="button" class="pill hot" data-hear>Hear it</button>
      ${src.clip_id ? `<button type="button" class="pill" data-crew>▶ Hear the crew say it</button>` : ""}</div>`;
    cardEl.hidden = false;
    cardEl.querySelector("[data-x]").onclick = closeCard;
    cardEl.querySelector("[data-hear]").onclick = () => say && say(`${t.term}. ${t.explain}`, { situation: "vocab", vocab: [t.term] });
    const cb = cardEl.querySelector("[data-crew]");
    if (cb) cb.onclick = () => playCrew && playCrew({ clip_id: src.clip_id, t0: Math.max(0, src.t - 2), t1: src.t + 4, speaker: "crew", places: [], jargon: [] });
    cardEl.querySelector("[data-hear]").focus({ preventScroll: true });
    if (O.a11y && O.a11y.describe) O.a11y.describe(`Space word card: ${t.term}. ${t.explain}`, { quiet: true });
  }
  function closeCard() { if (cardEl) cardEl.hidden = true; if (returnTo && returnTo.focus) returnTo.focus({ preventScroll: true }); }
  const escH = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function activate(e) {
    const t = e.target.closest && e.target.closest(".hl[data-kind], .hl-chip");
    if (!t) return;
    const kind = t.dataset.kind, ref = t.dataset.ref;
    if (kind === "term" && glossary[ref]) { e.preventDefault(); termCard(ref, t); }
    else if (kind === "place" && ref && flyTo) { e.preventDefault(); flyTo(ref); }
  }
  document.addEventListener("click", activate);
  document.addEventListener("keydown", e => { if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches(".hl[role=button]")) activate(e); });

  // ---- watch the app's text containers ----
  let pend = 0;
  function scan(root) { (root.matches && root.matches(SELECTORS) ? [root] : []).concat([...root.querySelectorAll(SELECTORS)]).forEach(markEl); }
  if (typeof MutationObserver !== "undefined") {
    new MutationObserver(() => { if (pend) return; pend = requestAnimationFrame(() => { pend = 0; scan(document.body); }); })
      .observe(document.body, { childList: true, subtree: true, characterData: true });
  }
  load();
  O.highlight = { markCaption, termCard, noteReadout, tokenize: t => tokenize(t, m), get glossary() { return glossary; }, rescan: () => scan(document.body) };
  return O.highlight;
}
