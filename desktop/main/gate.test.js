// gate.js with a fake window: links out of a video go behind the grown-up gate; only a 3-second hold ("go") opens.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { classifyOpen, createGate } = require("./gate");

const ORIGIN = "http://127.0.0.1:47310";

test("which links need the gate", () => {
  assert.equal(classifyOpen("https://www.youtube.com/watch?v=jdkMHkF7BaA", ORIGIN), "youtube");
  assert.equal(classifyOpen("https://youtu.be/jdkMHkF7BaA", ORIGIN), "youtube");
  assert.equal(classifyOpen("https://m.youtube.com/channel/x", ORIGIN), "youtube");
  assert.equal(classifyOpen("https://www.youtube-nocookie.com/embed/x", ORIGIN), "youtube");
  assert.equal(classifyOpen("https://accounts.google.com/x", ORIGIN), "youtube");
  assert.equal(classifyOpen("https://svs.gsfc.nasa.gov/14992", ORIGIN), "external");
  assert.equal(classifyOpen("https://www.youtube.com.evil.example/", ORIGIN), "external");
  assert.equal(classifyOpen(ORIGIN + "/x", ORIGIN), "ours");
  assert.equal(classifyOpen("file:///etc/passwd", ORIGIN), null);
  assert.equal(classifyOpen("not a url", ORIGIN), null);
});

function fakeWindow(made) {
  return (opts) => {
    const ev = {}, wcev = {};
    const w = { opts, closed: false, loaded: null,
      loadFile(f) { this.loaded = f; }, on(e, f) { ev[e] = f; }, once(e, f) { ev[e] = f; }, show() {},
      close() { this.closed = true; if (ev.closed) ev.closed(); }, isDestroyed() { return this.closed; },
      webContents: { on(e, f) { wcev[e] = f; }, setWindowOpenHandler() {} },
      title(t) { wcev["page-title-updated"]({}, t); } };
    made.push(w);
    return w;
  };
}

test("the gate opens only on the hold; Not now, closing it, or a second link while it is up do not", async () => {
  const made = [], gate = createGate({ makeWindow: fakeWindow(made), file: "/x/gate.html" });
  const parent = {};
  let p = gate(parent, "https://www.youtube.com/watch?v=a");
  assert.equal(made[0].opts.modal, true); assert.equal(made[0].opts.parent, parent); assert.equal(made[0].loaded, "/x/gate.html");
  assert.equal(await gate(parent, "https://www.youtube.com/watch?v=b"), false, "one gate at a time");
  made[0].title("go");
  assert.equal(await p, true); assert.equal(made[0].closed, true);
  p = gate(parent, "https://www.youtube.com/watch?v=c"); made[1].title("no"); assert.equal(await p, false);
  p = gate(parent, "https://www.youtube.com/watch?v=d"); made[2].close(); assert.equal(await p, false);
  p = gate(parent, "https://www.youtube.com/watch?v=e"); made[3].title("Ask a grown-up"); made[3].title("go"); assert.equal(await p, true);
});
