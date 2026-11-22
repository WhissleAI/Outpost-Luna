// "Your web browser didn't open. Copy the link:" (src/link_fallback_ui.js): the block, Copy, the corner notice.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const LF = await import("../src/link_fallback_ui.js");
const URL1 = "https://github.com/WhissleAI/Outpost-Luna/releases/tag/v0.3.9";

test("the block: the short line, the link read-only, a Copy button; only web links, escaped", () => {
  const h = LF.fallbackHtml(URL1);
  assert.match(h, /Your web browser didn't open\. Copy the link:/);
  assert.match(h, new RegExp(`<input class="lf-url" type="text" readonly value="${URL1.replace(/[.?/]/g, "\\$&")}"`));
  assert.match(h, /data-lf-copy>Copy</);
  assert.equal(LF.fallbackHtml("javascript:alert(1)"), "");
  assert.equal(LF.fallbackHtml("file:///etc/passwd"), "");
  assert.equal(LF.fallbackHtml('https://x.org/"><script>'), "");
  assert.equal(LF.fallbackHtml(null), "");
  assert.ok(LF.LINK_COPY.line.split(/\s+/).length <= 8);
  assert.equal(window.__lunaLink, LF.receiveLink);
});

test("copy: the clipboard API first; else select the text and the copy command; says Copied!", async () => {
  const wrote = [];
  assert.equal(await LF.copyText("x", null, { clipboard: { writeText: async (t) => wrote.push(t) } }, null), true);
  assert.deepEqual(wrote, ["x"]);
  let selected = false;
  const input = { value: URL1, select() { selected = true; }, focus() {} };
  const ok = await LF.copyText(URL1, input, { clipboard: { writeText: async () => { throw new Error("denied"); } } }, { execCommand: (c) => c === "copy" });
  assert.equal(ok, true);
  assert.equal(selected, true);
  assert.equal(await LF.copyText(URL1, input, null, null), false);
  const btn = { textContent: "Copy", closest: (sel) => (sel === "[data-lf-copy]" ? btn : sel === ".lf-box" ? box : null) };
  const box = { querySelector: () => input };
  const save = globalThis.navigator;
  Object.defineProperty(globalThis, "navigator", { value: { clipboard: { writeText: async () => {} } }, configurable: true });
  try { assert.equal(await LF.onCopyClick({ target: btn }), true); } finally { Object.defineProperty(globalThis, "navigator", { value: save, configurable: true }); }
  assert.equal(btn.textContent, "Copied!");
  assert.equal(await LF.onCopyClick({ target: { closest: () => null } }), false);
});

test("the corner notice for any other link: one at a time, dismissable; nothing for a non-web link", () => {
  const doc = { body: { appendChild(n) { doc.byId[n.id] = n; } }, byId: {}, getElementById(id) { return this.byId[id] || null; },
    createElement: () => ({ attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, remove() { this.removed = true; delete doc.byId[this.id]; } }) };
  const n = LF.showLinkNotice({ url: URL1 }, doc);
  assert.equal(n.attrs.role, "status");
  assert.match(n.innerHTML, /Copy the link/);
  assert.match(n.innerHTML, /data-lf-close/);
  assert.equal(LF.showLinkNotice({ url: "https://nasa.gov/x" }, doc), n);   // reused, not stacked
  assert.match(n.innerHTML, /nasa\.gov/);
  const close = { dataset: { lfClose: "" } };
  n.onclick({ target: { closest: () => close } });
  assert.equal(n.removed, true);
  assert.equal(LF.showLinkNotice({ url: "mailto:x@y" }, doc), null);
});
