// Settings → For grown-ups → Class lessons (docs/CURRICULUM.md): write lessons for your class, in the app's own console
// look. A lesson is a few steps (say it, find a place on the Moon, multiple choice, predict), a place for its pin and a
// patch. Check runs the same rules the loader does (docs/COPY.md word budgets, real places, a source link on every
// fact); Preview plays the lesson in Flight School as the cadet will see it (nothing saved, no patch); Save puts it on
// the map. A pack (all of one class's lessons) moves between computers as one JSON file: Export / Import.
//
// Every control is a button, a choice or a field in the Settings sheet, so Tab, arrows, a controller (buttons and
// choices; typing needs a keyboard) and "press <label>" reach it like any other setting. The sheet redraws itself
// (a11y.js renderPanel): everything typed lives in `S`, never only in the DOM.
import { courseLabel, courseState } from "./courses.js";
const moonCourse = () => !courseState.active || courseState.active === "moon";
const O = typeof window !== "undefined" ? (window.__outpost = window.__outpost || { stepRenderers: {} }) : { stepRenderers: {} };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const COPY = {
  title: "Class lessons",
  // [courses] the course's own school ("Field School") and lessons; the Moon's say Flight School and NASA, as before
  get line() { return moonCourse() ? "Write lessons for your class. They show up in Flight School next to NASA's."
    : `Write lessons for your class. They show up in ${courseLabel("school", "Field School")} next to the course's own.`; },
  empty: "No class lessons yet.",
  newLesson: "New lesson",
  importPack: "Import a pack…",
  exportPack: "Export",
  removePack: "Remove pack",
  removeLesson: "Remove lesson",
  confirmRemove: "Yes, remove it",
  cancel: "Cancel",
  edit: "Edit",
  up: "Move up",
  down: "Move down",
  back: "All lessons",
  check: "Check",
  preview: "Preview",
  save: "Save",
  addStep: "Add a step",
  addFact: "Add a fact",
  addAnswer: "Add an answer",
  remove: "Remove",
  right: "Right answer",
  lines: "What CAPCOM says",
  saved: "Saved. It's in Flight School now.",
  checked: "Looks good.",
  imported: (t, n) => `Imported ${t}: ${n} ${n === 1 ? "lesson" : "lessons"}.`,
  notPack: "That file isn't a lesson pack.",
  fix: n => `Fix ${n} ${n === 1 ? "thing" : "things"} first.`,
  offline: "Couldn't reach the app. Try again.",
  removed: "Removed.",
  steps: n => `${n} ${n === 1 ? "step" : "steps"}`,
  skipped: "Couldn't load",
  where: "Saved on this computer only.",
};
export const KINDS = [["say", "Say it"], ["place", "Find a place"], ["choice", "Multiple choice"], ["predict", "Predict"]];
/** [words, characters] per field (docs/COPY.md §3; classpacks.py enforces the same). */
export const BUDGET = { title: [6, 24], brief: [20], prompt: [20, 90], success: [8], fail: [6], hint: [10], option: [6, 40],
  reveal: [20], patch: [2, 20], packTitle: [6, 32], fact: [30] };
const DEFAULTS = { success: "Roger. That's it.", fail: "Not quite.",
  hint: { say: "Listen to the question again.", place: "Look for the glow.", choice: "Read each answer again.", predict: "Make your best guess." } };

// ---------------------------------------------------------------- pure helpers (tests/class_editor.test.js) ---------
export const slug = (s, fallback = "lesson") => (String(s || "").toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 24).replace(/-+$/, "") || fallback);
export const blankPack = () => ({ format: "outpost-luna-class-pack", version: 1, id: "my-class", title: "My class", lessons: [] });
export function blankStep(kind = "choice") {
  const s = { kind, prompt: "" };
  if (kind === "say") s.words = [];
  if (kind === "place") s.place = "";
  if (kind === "choice" || kind === "predict") { s.options = ["", ""]; s.answer = 0; }
  if (kind === "predict") s.reveal = "";
  return s;
}
export function blankLesson(pack) {
  const ids = new Set((pack.lessons || []).map(l => l.id));
  let n = (pack.lessons || []).length + 1, id = `lesson-${n}`;
  while (ids.has(id)) id = `lesson-${++n}`;
  return { id, title: "", brief: "", place: "", patch: { name: "", glyph: "" }, facts: [], steps: [blankStep("choice")] };
}
/** Change a step's kind, keeping what still fits (the question and CAPCOM's lines). */
export function rekind(step, kind) {
  const s = { ...blankStep(kind), prompt: step.prompt || "" };
  ["success", "fail", "hint"].forEach(k => { if (step[k]) s[k] = step[k]; });
  if (step.options && s.options) { s.options = step.options.slice(0, 4); s.answer = Math.min(step.answer || 0, s.options.length - 1); }
  return s;
}
const PATH = /[^.[\]]+/g;
/** "lessons[0].steps[1].prompt" → the value there. */
export const getAt = (o, path) => (String(path).match(PATH) || []).reduce((x, k) => (x == null ? undefined : x[/^\d+$/.test(k) ? +k : k]), o);
/** Set the value at a path (objects / arrays on the way must exist). */
export function setAt(o, path, v) {
  const ks = String(path).match(PATH) || [];
  let x = o;
  ks.slice(0, -1).forEach(k => { x = x[/^\d+$/.test(k) ? +k : k]; });
  const last = ks[ks.length - 1];
  x[/^\d+$/.test(last) ? +last : last] = v;
  return o;
}
/** Move item i of a by d (−1 up, +1 down); a new array. */
export function moveItem(a, i, d) {
  const j = i + d, b = a.slice();
  if (i < 0 || j < 0 || i >= b.length || j >= b.length) return b;
  [b[i], b[j]] = [b[j], b[i]];
  return b;
}
const words = s => String(s || "").trim().split(/\s+/).filter(Boolean).length;
/** The live budget line under a field: "4 / 20 words", over = past the budget. */
export function budgetNote(v, [w, c] = []) {
  const n = words(v), len = String(v || "").length;
  const over = (w && n > w) || (c && len > c);
  return { text: c && len > c * 0.75 ? `${len} / ${c} characters` : w ? `${n} / ${w} words` : "", over: !!over };
}
/** Errors keyed by their field path. */
export const errorsByAt = errs => (errs || []).reduce((m, e) => { (m[e.at] = m[e.at] || []).push(e.msg); return m; }, {});
export const packFileName = p => `outpost-luna-lessons-${slug(p && p.id, "class")}.json`;
/** A pack as it goes into the file / the API: answer words split, empty answers and facts dropped. */
export function cleanPack(p) {
  const out = JSON.parse(JSON.stringify(p));
  delete out.saved_at;
  (out.lessons || []).forEach(L => {
    L.facts = (L.facts || []).filter(f => (f.text || "").trim() || ((f.source || {}).url || "").trim());
    if (L.patch && !L.patch.glyph) delete L.patch.glyph;
    (L.steps || []).forEach(s => {
      if (s.kind === "say" && typeof s.words === "string") s.words = s.words.split(",").map(w => w.trim()).filter(Boolean);
      ["success", "fail", "hint"].forEach(k => { if (!String(s[k] || "").trim()) delete s[k]; });
    });
  });
  return out;
}

// ---------------------------------------------------------------- views (pure) --------------------------------------
function field({ at, label, value, budget, errs, multiline = false, placeholder = "", maxlength = 0 }) {
  const b = budget ? budgetNote(value, budget) : null, bad = (errs[at] || []);
  const ctl = multiline
    ? `<textarea rows="2" data-at="${esc(at)}" ${bad.length ? 'aria-invalid="true"' : ""} placeholder="${esc(placeholder)}">${esc(value || "")}</textarea>`
    : `<input type="text" data-at="${esc(at)}" value="${esc(value || "")}" ${maxlength ? `maxlength="${maxlength}"` : ""} ${bad.length ? 'aria-invalid="true"' : ""} placeholder="${esc(placeholder)}" spellcheck="true">`;
  return `<label class="ce-field${bad.length ? " is-bad" : ""}"><span class="ce-lab">${esc(label)}${b ? `<small class="ce-count${b.over ? " is-over" : ""}" data-count="${esc(at)}" data-budget="${(budget || []).join(",")}">${esc(b.text)}</small>` : ""}</span>
    ${ctl}${bad.map(m => `<small class="ce-err">${esc(m)}</small>`).join("")}</label>`;
}
function placeSelect({ at, label, value, places, errs }) {
  const bad = errs[at] || [];
  return `<label class="ce-field${bad.length ? " is-bad" : ""}"><span class="ce-lab">${esc(label)}</span>
    <select data-at="${esc(at)}" ${bad.length ? 'aria-invalid="true"' : ""}><option value="">Pick a place…</option>${places.map(p => `<option value="${esc(p.id)}" ${p.id === value ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>
    ${bad.map(m => `<small class="ce-err">${esc(m)}</small>`).join("")}</label>`;
}
const btn = (label, attrs, cls = "btn") => `<button type="button" class="${cls}" ${attrs}>${esc(label)}</button>`;

/** The list: every pack, its lessons (edit, reorder), export / remove; import; problems the loader found. */
export function listHtml(S) {
  const probs = (S.problems || []).length ? `<div class="ce-probs" role="note"><b>${esc(COPY.skipped)}</b><ul>${S.problems.map(p => `<li>${esc(p.msg)}</li>`).join("")}</ul></div>` : "";
  const packs = (S.packs || []).map((P, pi) => {
    const p = P.pack, cf = S.confirm && S.confirm.kind === "pack" && S.confirm.pi === pi;
    return `<div class="ce-pack" data-pi="${pi}">
      <div class="ce-packhead"><b>${esc(p.title)}</b><small>${esc(`${p.lessons.length} ${p.lessons.length === 1 ? "lesson" : "lessons"}`)}</small>
        <span class="ce-actions">${btn(COPY.newLesson, `data-ce="new" data-pi="${pi}"`)}${btn(COPY.exportPack, `data-ce="export" data-pi="${pi}"`, "btn-quiet")}
        ${cf ? `${btn(COPY.confirmRemove, `data-ce="remove-pack-yes" data-pi="${pi}"`, "btn btn-danger")}${btn(COPY.cancel, `data-ce="cancel"`, "btn-quiet")}`
          : btn(COPY.removePack, `data-ce="remove-pack" data-pi="${pi}"`, "btn-quiet")}</span></div>
      <ol class="ce-lessons">${p.lessons.map((L, li) => `<li><span class="ce-lpatch" aria-hidden="true">${esc(((L.patch && L.patch.glyph) || L.title || "?").slice(0, 1).toUpperCase())}</span>
        <span class="ce-lname"><b>${esc(L.title || "Untitled")}</b><small>${esc(COPY.steps((L.steps || []).length))}</small></span>
        ${btn(COPY.edit, `data-ce="edit" data-pi="${pi}" data-li="${li}" aria-label="${esc(`${COPY.edit} ${L.title || "lesson"}`)}"`)}
        ${btn("↑", `data-ce="lup" data-pi="${pi}" data-li="${li}" aria-label="${esc(`${COPY.up}: ${L.title}`)}" ${li === 0 ? "disabled" : ""}`, "btn-icon")}
        ${btn("↓", `data-ce="ldown" data-pi="${pi}" data-li="${li}" aria-label="${esc(`${COPY.down}: ${L.title}`)}" ${li === p.lessons.length - 1 ? "disabled" : ""}`, "btn-icon")}</li>`).join("")}</ol></div>`;
  }).join("");
  return `<div class="ce-zone" data-ce-view="list">
    <p class="set-help">${esc(COPY.line)}</p>
    ${probs}
    ${packs || `<p class="ce-empty">${esc(COPY.empty)}</p>`}
    <div class="ce-row">${(S.packs || []).length ? "" : btn(COPY.newLesson, `data-ce="new" data-pi="-1"`, "btn btn-primary")}${btn(COPY.importPack, `data-ce="import"`)}
      <input type="file" accept=".json,application/json" data-ce-file hidden tabindex="-1"></div>
    <p class="set-help ce-status" role="status" aria-live="polite">${esc(S.status || "")}</p>
    <small class="rs-note">${esc(COPY.where)}</small></div>`;
}

function stepHtml(s, si, n, at, errs, places) {
  const kindSeg = `<fieldset class="set-seg ce-kind"><legend>Step ${si + 1}</legend><div class="a11y-speed">${KINDS.map(([k, t]) =>
    `<label><input type="radio" name="ce-kind-${si}" data-ce-kind="${si}" value="${k}" ${s.kind === k ? "checked" : ""}><span>${esc(t)}</span></label>`).join("")}</div></fieldset>`;
  let body = field({ at: `${at}.prompt`, label: "Question", value: s.prompt, budget: BUDGET.prompt, errs, placeholder: s.kind === "place" ? "Find the Sea of Tranquility." : "What do craters tell us?" });
  if (s.kind === "say") body += field({ at: `${at}.words`, label: "Right answers (comma between them)", value: Array.isArray(s.words) ? s.words.join(", ") : s.words, errs, placeholder: "ejecta, splash" });
  if (s.kind === "place") body += placeSelect({ at: `${at}.place`, label: "The place to find", value: s.place, places, errs });
  if (s.kind === "choice" || s.kind === "predict") {
    body += `<fieldset class="ce-opts"><legend>Answers</legend>${(s.options || []).map((o, oi) => `<div class="ce-opt">
      <label class="ce-right"><input type="radio" name="ce-right-${si}" data-ce-right="${si}" value="${oi}" ${s.answer === oi ? "checked" : ""}><span>${esc(COPY.right)}</span></label>
      ${field({ at: `${at}.options[${oi}]`, label: `Answer ${"ABCD"[oi]}`, value: o, budget: BUDGET.option, errs })}
      ${(s.options || []).length > 2 ? btn(COPY.remove, `data-ce="opt-del" data-si="${si}" data-oi="${oi}" aria-label="${esc(`${COPY.remove} answer ${"ABCD"[oi]}`)}"`, "btn-quiet") : ""}</div>`).join("")}
      ${(errs[`${at}.answer`] || []).concat(errs[`${at}.options`] || []).map(m => `<small class="ce-err">${esc(m)}</small>`).join("")}
      ${(s.options || []).length < 4 ? btn(COPY.addAnswer, `data-ce="opt-add" data-si="${si}"`, "btn-quiet") : ""}</fieldset>`;
  }
  if (s.kind === "predict") body += field({ at: `${at}.reveal`, label: "The answer, said after the guess", value: s.reveal, budget: BUDGET.reveal, errs });
  const linesBad = ["success", "fail", "hint"].some(k => errs[`${at}.${k}`]);
  body += `<details class="ce-lines" ${linesBad ? "open" : ""}><summary>${esc(COPY.lines)}</summary>
    ${field({ at: `${at}.success`, label: "When it's right", value: s.success, budget: BUDGET.success, errs, placeholder: DEFAULTS.success })}
    ${field({ at: `${at}.fail`, label: "When it's not", value: s.fail, budget: BUDGET.fail, errs, placeholder: DEFAULTS.fail })}
    ${field({ at: `${at}.hint`, label: "Hint after two tries", value: s.hint, budget: BUDGET.hint, errs, placeholder: DEFAULTS.hint[s.kind] || "" })}</details>`;
  return `<div class="ce-step" data-si="${si}">${kindSeg}
    ${(errs[`${at}.kind`] || []).map(m => `<small class="ce-err">${esc(m)}</small>`).join("")}${body}
    <div class="ce-row ce-steptools">${btn(COPY.up, `data-ce="sup" data-si="${si}" ${si === 0 ? "disabled" : ""}`, "btn-quiet")}${btn(COPY.down, `data-ce="sdown" data-si="${si}" ${si === n - 1 ? "disabled" : ""}`, "btn-quiet")}
      ${n > 1 ? btn(COPY.remove, `data-ce="sdel" data-si="${si}" aria-label="${esc(`${COPY.remove} step ${si + 1}`)}"`, "btn-quiet") : ""}</div></div>`;
}

/** The lesson editor: the pack's name, the lesson (title, brief, place, patch, facts) and its steps; Check / Preview / Save. */
export function editorHtml(S) {
  const E = S.edit, p = E.pack, li = E.li, L = p.lessons[li], at = `lessons[${li}]`, errs = errorsByAt(S.errors), places = S.places || [];
  const all = (S.errors || []), here = all.filter(e => !document_has(e.at, li)), warn = S.warnings || [];
  const cf = S.confirm && S.confirm.kind === "lesson";
  return `<div class="ce-zone" data-ce-view="lesson">
    <div class="ce-row ce-top">${btn(`‹ ${COPY.back}`, `data-ce="back"`, "btn-quiet")}<span class="ce-crumb">${esc(p.title || "")}</span></div>
    ${field({ at: "title", label: "Pack name (your class)", value: p.title, budget: BUDGET.packTitle, errs })}
    <div class="ce-grid">
      ${field({ at: `${at}.title`, label: "Lesson title", value: L.title, budget: BUDGET.title, errs, placeholder: "Craters up close" })}
      ${placeSelect({ at: `${at}.place`, label: "Its pin on the Moon", value: L.place, places, errs })}
    </div>
    ${field({ at: `${at}.brief`, label: "Brief: why it matters, spoken first", value: L.brief, budget: BUDGET.brief, errs, multiline: true, placeholder: "Big craters tell the Moon's story." })}
    <div class="ce-grid">
      ${field({ at: `${at}.patch.name`, label: "Patch name", value: (L.patch || {}).name, budget: BUDGET.patch, errs, placeholder: "Crater Spotter" })}
      ${field({ at: `${at}.patch.glyph`, label: "Patch letter", value: (L.patch || {}).glyph, errs, maxlength: 1, placeholder: "C" })}
    </div>
    <fieldset class="ce-facts"><legend>Facts (each with its source)</legend>
      ${(L.facts || []).map((f, fi) => `<div class="ce-fact">${field({ at: `${at}.facts[${fi}].text`, label: `Fact ${fi + 1}`, value: f.text, budget: BUDGET.fact, errs })}
        <div class="ce-grid">${field({ at: `${at}.facts[${fi}].source.title`, label: "Source", value: (f.source || {}).title, errs, placeholder: "NASA Science: Moon facts" })}
        ${field({ at: `${at}.facts[${fi}].source.url`, label: "Link (https://…)", value: (f.source || {}).url, errs, placeholder: "https://science.nasa.gov/moon/" })}</div>
        ${(errs[`${at}.facts[${fi}].source`] || []).map(m => `<small class="ce-err">${esc(m)}</small>`).join("")}
        ${btn(COPY.remove, `data-ce="fact-del" data-fi="${fi}" aria-label="${esc(`${COPY.remove} fact ${fi + 1}`)}"`, "btn-quiet")}</div>`).join("")}
      ${(L.facts || []).length < 5 ? btn(COPY.addFact, `data-ce="fact-add"`, "btn-quiet") : ""}</fieldset>
    <div class="ce-steps">${L.steps.map((s, si) => stepHtml(s, si, L.steps.length, `${at}.steps[${si}]`, errs, places)).join("")}</div>
    ${L.steps.length < 8 ? `<div class="ce-row ce-add" role="group" aria-label="${esc(COPY.addStep)}"><span class="ce-lab">${esc(COPY.addStep)}:</span>${KINDS.map(([k, t]) => btn(t, `data-ce="sadd" data-kind="${k}"`, "btn-quiet")).join("")}</div>` : ""}
    ${here.length ? `<div class="ce-probs" role="alert"><b>${esc(COPY.fix(all.length))}</b><ul>${here.slice(0, 8).map(e => `<li>${esc(e.msg)}</li>`).join("")}</ul></div>` : ""}
    ${warn.length ? `<ul class="ce-warn">${warn.map(w => `<li>${esc(w.msg)}</li>`).join("")}</ul>` : ""}
    <div class="ce-row ce-bottom">${btn(COPY.check, `data-ce="check"`)}${btn(COPY.preview, `data-ce="preview"`)}${btn(COPY.save, `data-ce="save"`, "btn btn-primary")}
      <span class="ce-spacer"></span>${cf ? `${btn(COPY.confirmRemove, `data-ce="remove-lesson-yes"`, "btn btn-danger")}${btn(COPY.cancel, `data-ce="cancel"`, "btn-quiet")}` : btn(COPY.removeLesson, `data-ce="remove-lesson"`, "btn-quiet")}</div>
    <p class="set-help ce-status" role="status" aria-live="polite">${esc(S.status || "")}</p></div>`;
}
/** Is this error drawn next to a field of the open lesson (so the summary needn't repeat it)? */
function document_has(at, li) {
  if (!at) return false;
  if (at === "title") return true;
  const m = /^lessons\[(\d+)\]\.(title|brief|place|patch\.name|patch\.glyph|facts\[\d+\]\.(text|source(\.title|\.url)?)|steps\[\d+\]\.(prompt|words|place|options(\[\d+\])?|answer|reveal|success|fail|hint|kind))$/.exec(at);
  return !!m && +m[1] === li;
}

// ---------------------------------------------------------------- the live part ---------------------------------------
export const S = { packs: [], problems: [], places: [], edit: null, errors: [], warnings: [], status: "", confirm: null, loaded: false };
const HDR = { "Content-Type": "application/json", "X-Outpost-Class": "1" };

const section = {
  id: "class", title: COPY.title, after: "progress", grownup: true, first: true,   // in Settings → For grown-ups, after Progress
  html: () => (S.edit ? editorHtml(S) : listHtml(S)),
  bind(el, { fetchFn = typeof fetch === "function" ? fetch : null } = {}) {
    if (!el || !fetchFn) return;
    const redraw = (focusSel) => {
      const z = el.querySelector(".ce-zone");
      if (z) z.outerHTML = section.html(); else el.insertAdjacentHTML("beforeend", section.html());
      const f = focusSel && el.querySelector(focusSel);
      if (f) f.focus({ preventScroll: false });
      wire();
    };
    const say = (t, focusSel) => { S.status = t; redraw(focusSel); };
    const j = (url, o = {}) => fetchFn(url, o).then(async r => ({ ok: r.ok, status: r.status, body: await r.json().catch(() => null) }));
    const changed = () => { try { dispatchEvent(new CustomEvent("outpost:class-changed")); } catch (e) { /* tests */ } };
    async function load() {
      const [a, b] = await Promise.all([j("/api/class/packs").catch(() => null), S.places.length ? null : j("/api/class/places").catch(() => null)]);
      if (a && a.ok && a.body) { S.packs = a.body.packs || []; S.problems = a.body.problems || []; }
      if (b && b.ok && Array.isArray(b.body)) S.places = b.body;
      S.loaded = true;
    }
    async function put(pack) {
      const r = await j(`/api/class/packs/${encodeURIComponent(pack.id)}`, { method: "PUT", headers: HDR, body: JSON.stringify(cleanPack(pack)) }).catch(() => null);
      if (!r) return { ok: false, errors: [{ at: "", msg: COPY.offline }] };
      return { ok: r.ok, ...(r.body || {}) };
    }
    const lessonOf = () => S.edit.pack.lessons[S.edit.li];
    function wire() {
      // typing: the draft follows every key; only the budget line updates (no redraw: the caret stays put)
      el.querySelectorAll("[data-at]").forEach(inp => {
        const sync = () => {
          if (!S.edit) return;
          const at = inp.dataset.at, v = inp.value;
          setAt(S.edit.pack, at, v);   // answer words stay as typed ("ejecta, splash"); cleanPack splits them
          const c = el.querySelector(`[data-count="${CSS.escape(at)}"]`);
          if (c) { const b = budgetNote(v, c.dataset.budget.split(",").map(Number)); c.textContent = b.text; c.classList.toggle("is-over", b.over); }
          S.edit.dirty = true;
        };
        inp.addEventListener(inp.tagName === "SELECT" ? "change" : "input", sync);
      });
      el.querySelectorAll("[data-ce-kind]").forEach(r => r.onchange = () => { const L = lessonOf(), si = +r.dataset.ceKind; L.steps[si] = rekind(L.steps[si], r.value); S.edit.dirty = true; redraw(`[data-ce-kind="${si}"][value="${r.value}"]`); });
      el.querySelectorAll("[data-ce-right]").forEach(r => r.onchange = () => { lessonOf().steps[+r.dataset.ceRight].answer = +r.value; S.edit.dirty = true; });
      const file = el.querySelector("[data-ce-file]");
      if (file) file.onchange = async () => {
        const f = file.files && file.files[0]; file.value = "";
        if (!f) return;
        let pack = null; try { pack = JSON.parse(await f.text()); } catch (e) { pack = null; }
        if (!pack || typeof pack !== "object" || !Array.isArray(pack.lessons)) return say(COPY.notPack, '[data-ce="import"]');
        const r = await put(pack);
        if (!r.ok) return say(`${COPY.notPack} ${(r.errors || []).slice(0, 2).map(e => e.msg).join(" ")}`.trim(), '[data-ce="import"]');
        await load(); changed();
        say(COPY.imported(pack.title || pack.id, pack.lessons.length), '[data-ce="import"]');
      };
      el.querySelectorAll("[data-ce]").forEach(b => b.onclick = () => act(b.dataset.ce, b.dataset).catch(() => say(COPY.offline)));
    }
    async function act(what, d) {
      const pi = d.pi != null ? +d.pi : -1;
      if (what === "import") { const f = el.querySelector("[data-ce-file]"); if (f) f.click(); return; }
      if (what === "cancel") { S.confirm = null; return redraw('[data-ce^="remove"]'); }
      if (what === "new" || what === "edit") {
        const pack = pi >= 0 ? JSON.parse(JSON.stringify(S.packs[pi].pack)) : blankPack();
        let li = +d.li;
        if (what === "new") { pack.lessons.push(blankLesson(pack)); li = pack.lessons.length - 1; }
        S.edit = { pack, li, isNew: what === "new", known: pi >= 0 }; S.errors = []; S.warnings = []; S.status = ""; S.confirm = null;
        return redraw(`[data-at="lessons[${li}].title"]`);
      }
      if (what === "lup" || what === "ldown") {
        const pack = JSON.parse(JSON.stringify(S.packs[pi].pack)), li = +d.li;
        pack.lessons = moveItem(pack.lessons, li, what === "lup" ? -1 : 1);
        const r = await put(pack);
        if (r.ok) { await load(); changed(); }
        return say(r.ok ? COPY.saved : (r.errors || [])[0] ? r.errors[0].msg : COPY.offline, `[data-ce="${what}"][data-li="${Math.max(0, li + (what === "lup" ? -1 : 1))}"]`);
      }
      if (what === "export") {
        const p = cleanPack(S.packs[pi].pack), url = URL.createObjectURL(new Blob([JSON.stringify(p, null, 1)], { type: "application/json" }));
        const a = document.createElement("a"); a.href = url; a.download = packFileName(p); document.body.append(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
        return;
      }
      if (what === "remove-pack") { S.confirm = { kind: "pack", pi }; return redraw('[data-ce="cancel"]'); }
      if (what === "remove-pack-yes") {
        const id = S.packs[pi].pack.id;
        const r = await j(`/api/class/packs/${encodeURIComponent(id)}`, { method: "DELETE", headers: HDR }).catch(() => null);
        S.confirm = null;
        if (r && r.ok) { await load(); changed(); }
        return say(r && r.ok ? COPY.removed : COPY.offline, '[data-ce="import"]');
      }
      // ---- in the lesson editor ----
      if (!S.edit) return;
      const L = lessonOf();
      const steps = (f, focus) => { f(); S.edit.dirty = true; redraw(focus); };
      if (what === "back") { S.edit = null; S.errors = []; S.warnings = []; S.status = ""; S.confirm = null; return redraw('[data-ce="edit"], [data-ce="new"]'); }
      if (what === "sadd") return steps(() => L.steps.push(blankStep(d.kind)), `[data-at="lessons[${S.edit.li}].steps[${L.steps.length}].prompt"]`);
      if (what === "sup" || what === "sdown") { const si = +d.si, to = si + (what === "sup" ? -1 : 1); return steps(() => { L.steps = moveItem(L.steps, si, what === "sup" ? -1 : 1); }, `[data-ce="${what}"][data-si="${to}"]`); }
      if (what === "sdel") return steps(() => L.steps.splice(+d.si, 1), '[data-ce="sadd"]');
      if (what === "opt-add") return steps(() => L.steps[+d.si].options.push(""), `[data-at="lessons[${S.edit.li}].steps[${d.si}].options[${L.steps[+d.si].options.length}]"]`);
      if (what === "opt-del") return steps(() => { const s = L.steps[+d.si]; s.options.splice(+d.oi, 1); s.answer = Math.min(s.answer, s.options.length - 1); }, `[data-ce="opt-add"][data-si="${d.si}"]`);
      if (what === "fact-add") return steps(() => { L.facts = L.facts || []; L.facts.push({ text: "", source: { title: "", url: "" } }); }, `[data-at="lessons[${S.edit.li}].facts[${L.facts.length}].text"]`);
      if (what === "fact-del") return steps(() => L.facts.splice(+d.fi, 1), '[data-ce="fact-add"]');
      if (what === "remove-lesson") { S.confirm = { kind: "lesson" }; return redraw('[data-ce="cancel"]'); }
      if (what === "remove-lesson-yes") {
        const pack = S.edit.pack; pack.lessons.splice(S.edit.li, 1); S.confirm = null;
        let ok = true;
        if (S.edit.known) {
          const r = pack.lessons.length ? await put(pack) : await j(`/api/class/packs/${encodeURIComponent(pack.id)}`, { method: "DELETE", headers: HDR }).catch(() => null);
          ok = !!(r && r.ok);
          if (ok) { await load(); changed(); }
        }
        S.edit = null; S.errors = []; S.warnings = [];
        return say(ok ? COPY.removed : COPY.offline, '[data-ce="import"]');
      }
      if (what === "check") {
        const r = await j("/api/class/validate", { method: "POST", headers: HDR, body: JSON.stringify(cleanPack(S.edit.pack)) });
        S.errors = (r.body && r.body.errors) || []; S.warnings = (r.body && r.body.warnings) || [];
        return say(S.errors.length ? COPY.fix(S.errors.length) : COPY.checked, S.errors.length ? '[aria-invalid="true"]' : '[data-ce="check"]');
      }
      if (what === "save") {
        if (!S.edit.known && S.packs.some(P => P.pack.id === S.edit.pack.id)) {   // a first lesson never overwrites another pack
          let n = 2; while (S.packs.some(P => P.pack.id === `my-class-${n}`)) n++; S.edit.pack.id = `my-class-${n}`;
        }
        const r = await put(S.edit.pack);
        S.errors = r.errors || []; S.warnings = r.warnings || [];
        if (r.ok) { S.edit.known = true; S.edit.dirty = false; await load(); changed(); }
        return say(r.ok ? COPY.saved : COPY.fix(S.errors.length), r.ok ? '[data-ce="save"]' : '[aria-invalid="true"]');
      }
      if (what === "preview") {
        const r = await j("/api/class/preview", { method: "POST", headers: HDR, body: JSON.stringify({ pack: cleanPack(S.edit.pack), lesson: S.edit.li }) });
        if (!r.ok || !r.body || !r.body.lesson_id) { S.errors = (r.body && r.body.errors) || []; return say(COPY.fix(S.errors.length || 1), '[aria-invalid="true"]'); }
        S.errors = []; S.status = "";
        try { if (O.a11y && O.a11y.open) O.a11y.open(false); } catch (e) { /* */ }
        try { dispatchEvent(new CustomEvent("outpost:class-open", { detail: { id: r.body.lesson_id } })); } catch (e) { /* tests */ }
      }
    }
    if (!S.loaded) load().then(() => { if (el.isConnected) redraw(); });
    else { wire(); load().then(() => { if (el.isConnected && !S.edit) redraw(); }); }
    return { destroy() {} };
  },
};
if (typeof window !== "undefined") (O.settingsSections = O.settingsSections || []).push(section);
export default section;
