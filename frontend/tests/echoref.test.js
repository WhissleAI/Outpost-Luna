// echoref.js: what the app plays goes to the ear as 16 kHz PCM16, stamped on the mic stream's clock (libarc ABI 2).
import test from "node:test";
import assert from "node:assert/strict";
import * as echoref from "../src/echoref.js";

function fakeListener(clock = 2.5) {
  const sent = [];
  return { sent, live: true, clock: () => clock, send: o => { sent.push(o); return true; } };
}
const decode = m => { const b = Buffer.from(m.pcm, "base64"); return new Int16Array(b.buffer, b.byteOffset, b.length / 2); };

test("nothing is sent without a live mic", () => {
  echoref.bind(null);
  assert.equal(echoref.sendSamples(new Float32Array(1600), 1), 0);
  const l = fakeListener(); l.live = false; echoref.bind(l);
  assert.equal(echoref.sendSamples(new Float32Array(1600), 1), 0);
  assert.equal(l.sent.length, 0);
});

test("samples are stamped once and split into <= 10 s messages", () => {
  const l = fakeListener(); echoref.bind(l);
  const x = new Float32Array(16000 * 23).fill(0.5);
  assert.equal(echoref.sendSamples(x, 1.23456), x.length);
  assert.equal(l.sent.length, 3);
  assert.deepEqual(l.sent.map(m => m.t), ["ref", "ref", "ref"]);
  assert.equal(l.sent[0].at, 1.235);
  assert.equal(l.sent[1].at, null);          // right after the previous part
  assert.equal(decode(l.sent[0]).length, 160000);
  assert.equal(decode(l.sent[2]).length, 48000);
  assert.ok(Math.abs(decode(l.sent[0])[0] - 16383) <= 1);
  echoref.bind(null);
});

test("PCM16 conversion clips", () => {
  assert.deepEqual([...echoref.toPcm16(new Float32Array([-2, -1, 0, 1, 2]))], [-32768, -32768, 0, 32767, 32767]);
});

test("a muted or blob-less sentence sends nothing", async () => {
  const l = fakeListener(); echoref.bind(l);
  assert.equal(await echoref.fromBlob(null, 0), 0);
  assert.equal(await echoref.fromBlob({ arrayBuffer: async () => new ArrayBuffer(8) }, 0, true), 0);
  assert.equal(l.sent.length, 0);
  echoref.bind(null);
});
