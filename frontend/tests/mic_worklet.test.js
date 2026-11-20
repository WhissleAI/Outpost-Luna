// The mic's AudioWorklet loads from a same-origin file, because the desktop CSP (script-src 'self') blocks blob:
// worklets; that made a working mic say "Another app is using the mic" (AbortError from addModule).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { WORKLET, WORKLET_PATH, loadPcmWorklet } from "../src/listen.js";
import { micErrorText } from "../src/floor.js";

test("the worklet file holds the same processor as WORKLET", () => {
  const file = readFileSync(new URL("../public/pcm16_worklet.js", import.meta.url), "utf8");
  const body = s => s.replace(/^\/\/.*$/gm, "").replace(/\s+/g, " ").trim();
  assert.equal(body(file), body(WORKLET));
  assert.equal(WORKLET_PATH, "/pcm16_worklet.js");
});

test("loadPcmWorklet: the file first, a blob only if the file fails, a clear error if both fail", async () => {
  const seen = [];
  const ok = { audioWorklet: { addModule: async u => { seen.push(u); } } };
  assert.equal(await loadPcmWorklet(ok), "file"); assert.equal(seen[0], WORKLET_PATH);
  globalThis.URL.createObjectURL = () => "blob:x"; globalThis.URL.revokeObjectURL = () => {};
  const fileFails = { audioWorklet: { addModule: async u => { if (!u.startsWith("blob:")) throw Object.assign(new Error("no"), { name: "AbortError" }); } } };
  assert.equal(await loadPcmWorklet(fileFails), "blob");
  const allFail = { audioWorklet: { addModule: async () => { throw Object.assign(new Error("csp"), { name: "AbortError" }); } } };
  await assert.rejects(loadPcmWorklet(allFail), e => e.name === "WorkletError");
});

test("only NotReadable says another app holds the mic", () => {
  assert.match(micErrorText({ name: "NotReadableError" }), /Another app/);
  assert.doesNotMatch(micErrorText({ name: "AbortError" }), /Another app/);
  assert.doesNotMatch(micErrorText({ name: "WorkletError" }), /Another app/);
  assert.match(micErrorText({ name: "NotAllowedError" }), /blocked/);
});
