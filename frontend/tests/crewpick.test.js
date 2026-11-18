// [0.4.1] Crew talk with an exact answer (src/crewpick.js): the gated turn comes back as one chip, "Heard “B” · Use it";
// a click (Enter / controller A on the focused chip) uses it once; chatter gets no chip; the chip times out.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createCrewPick, pickText, PICK_MS } from "../src/crewpick.js";

function fakeDoc() {
  const els = {};
  const mk = tag => ({ tag, hidden: false, attrs: {}, textContent: "", children: [], parentNode: null, isConnected: true,
    setAttribute(k, v) { this.attrs[k] = v; }, focus() { doc.activeElement = this; },
    append(c) { c.parentNode = this; this.children.push(c); }, insertBefore(c) { c.parentNode = this; this.children.push(c); } });
  const row = mk("div"), listen = mk("div"); row.append(listen); els.listen = listen;
  const doc = { activeElement: null, createElement: mk, getElementById: id => els[id] || null, querySelector: s => (s === "#askbar .dock-row" ? row : null), row };
  return doc;
}
const fakeTimers = () => { const T = { fns: [] }; T.setTimeout = (f, ms) => (T.fns.push({ f, ms }), T.fns.length); T.clearTimeout = () => {}; return T; };

test("the chip names what the kid said, short", () => {
  assert.equal(pickText({ heard: "B", label: "No, never from here" }), "Heard “B” · Use it");
  assert.equal(pickText({ heard: "yes earth is up over the rim right now", label: "x" }), "Heard “yes earth is up over th…” · Use it");
});

test("an exact quiet answer shows one focused chip; using it taps that option once; it hides", () => {
  const doc = fakeDoc(), T = fakeTimers(), used = [];
  const prev = { focus() { doc.activeElement = prev; }, isConnected: true }; doc.activeElement = prev;
  const cp = createCrewPick(doc, p => used.push(p), { timers: T });
  cp.show({ label: "No, never from here", choice: "no", heard: "no" });
  const b = cp.el;
  assert.equal(b.hidden, false); assert.equal(b.textContent, "Heard “no” · Use it");
  assert.equal(b.attrs["aria-label"], "Use your answer: No, never from here");
  assert.equal(doc.activeElement, b, "focused: Enter / controller A use it");
  assert.equal(b.parentNode, doc.row, "in the voice bar, beside the state word");
  b.onclick(); b.onclick();
  assert.deepEqual(used, [{ label: "No, never from here", choice: "no", heard: "no" }], "used once");
  assert.equal(b.hidden, true); assert.equal(doc.activeElement, prev, "focus goes back");
});

test("chatter (no pick) shows nothing; a chip times out after PICK_MS", () => {
  const doc = fakeDoc(), T = fakeTimers(), used = [];
  const cp = createCrewPick(doc, p => used.push(p), { timers: T });
  cp.show(null);
  assert.equal(cp.el, null);
  cp.show({ label: "Steer left", choice: null, heard: "left" });
  assert.equal(T.fns.at(-1).ms, PICK_MS);
  T.fns.at(-1).f();
  assert.equal(cp.el.hidden, true); assert.equal(cp.pick, null); assert.deepEqual(used, []);
});

test("main.js wires it: crew_talk with a pick shows the chip; a lesson option is tapped, a Now-card choice goes as its label", () => {
  const m = readFileSync(new URL("../src/main.js", import.meta.url), "utf8");
  assert.match(m, /if \(d\.reason === "crew_talk" && d\.pick\) crewPick\.show\(d\.pick\); else crewPick\.hide\(\);/);
  assert.match(m, /#aPanel \.a-choice\[data-c=/);
  assert.match(m, /emitIntent\("task_choice", \{ arg: p\.label, text: p\.label \}, "tap"\)/);
  assert.match(m, /onIntent\("select", \(\) => \(crewPick\.pick/);
});
