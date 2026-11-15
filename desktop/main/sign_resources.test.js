"use strict";
// scripts/sign-resources.js (electron-builder afterPack, docs/DESKTOP.md "Signing"): macOS only. On a Windows build
// (native, or cross-built on a Mac) it must do nothing: no codesign call, no file touched, no error.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const cp = require("child_process");

function withFakeExec(fn) {
  const calls = [];
  const real = cp.execFileSync;
  cp.execFileSync = (...a) => { calls.push(a); return Buffer.alloc(0); };
  delete require.cache[require.resolve("../scripts/sign-resources.js")];
  const mod = require("../scripts/sign-resources.js");
  return Promise.resolve(fn(mod, calls)).finally(() => { cp.execFileSync = real; });
}

function tree() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "outpost-sign-"));
  const res = path.join(d, "win-unpacked", "resources");
  fs.mkdirSync(path.join(res, "python"), { recursive: true });
  fs.writeFileSync(path.join(res, "python", "python.exe"), Buffer.from("MZ\x90\x00 a PE file, not Mach-O"));
  fs.mkdirSync(path.join(res, "native"), { recursive: true });
  fs.writeFileSync(path.join(res, "native", "arctag.dll"), Buffer.from("MZ\x90\x00"));
  return { d, res };
}

test("afterPack on a Windows build: returns at once, never runs codesign", async () => {
  const { d } = tree();
  await withFakeExec(async (mod, calls) => {
    const ctx = { electronPlatformName: "win32", appOutDir: path.join(d, "win-unpacked"),
      packager: { appInfo: { productFilename: "Outpost Luna" } } };
    assert.strictEqual(await mod.default(ctx), undefined);
    assert.deepStrictEqual(calls, [], "no codesign (or any) call on win32");
  });
  fs.rmSync(d, { recursive: true, force: true });
});

test("findMachO: PE files (.exe / .dll / .pyd) are never picked for signing", () => {
  const { d, res } = tree();
  const { findMachO } = require("../scripts/sign-resources.js");
  assert.deepStrictEqual(findMachO(res), []);
  fs.rmSync(d, { recursive: true, force: true });
});
