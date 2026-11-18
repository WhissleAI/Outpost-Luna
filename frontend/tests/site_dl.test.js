// The site's download buttons (site/dl.js): releases go Mac first and Windows follows, so each button links the newest
// release that really has its file and shows that version; it never 404s. Runs the real file in a bare context.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(new URL("../../site/dl.js", import.meta.url), "utf8");
const ctx = { module: { exports: {} } };
vm.runInNewContext(src, ctx);
const { pick, plan, fetchReleases } = ctx.module.exports;

const DMG = "Outpost-Luna-mac-arm64.dmg", EXE = "Outpost-Luna-win-x64.exe";
const rel = (v, files, extra = {}) => ({ tag_name: `v${v}`, draft: false, prerelease: false,
  assets: files.map((n) => ({ name: n, browser_download_url: `https://github.com/WhissleAI/Outpost-Luna/releases/download/v${v}/${n}` })), ...extra });
// today: 0.3.9-0.3.11 are Mac-only; 0.3.8 has both
const TODAY = [rel("0.3.11", [DMG]), rel("0.3.10", [DMG]), rel("0.3.9", [DMG]), rel("0.3.8", [DMG, EXE]), rel("0.3.7", [DMG, EXE])];

test("Windows: the newest release with the .exe (0.3.8 while 0.3.9-0.3.11 are Mac-only), with its version", () => {
  const w = plan(TODAY, "win");
  assert.equal(w.state, "release");
  assert.equal(w.version, "0.3.8");
  assert.match(w.href, /\/download\/v0\.3\.8\/Outpost-Luna-win-x64\.exe$/);
  const m = plan(TODAY, "mac");
  assert.equal(m.state, "latest");
  assert.equal(m.version, "0.3.11");
});

test("after the 0.3.11 exe is uploaded, Windows links 0.3.11 (latest)", () => {
  const after = [rel("0.3.11", [DMG, EXE]), ...TODAY.slice(1)];
  const w = plan(after, "win");
  assert.equal(w.state, "latest");
  assert.equal(w.version, "0.3.11");
});

test("drafts never count; a pre-release only when no published release has the file", () => {
  const rels = [rel("0.4.0", [EXE], { draft: true }), rel("0.3.12-rc1", [EXE], { prerelease: true }), rel("0.3.11", [DMG]), rel("0.3.8", [EXE])];
  assert.equal(pick(rels, EXE).version, "0.3.8");
  assert.equal(pick([rel("0.3.12-rc1", [EXE], { prerelease: true }), rel("0.3.11", [DMG])], EXE).version, "0.3.12-rc1");
});

test("no release has the file: the build guide / the Releases page; the API failed: keep the stable link", () => {
  const w = plan([rel("0.3.11", [DMG])], "win");
  assert.equal(w.state, "fallback");
  assert.match(w.href, /BUILD_WINDOWS\.md$/);
  assert.equal(plan([rel("0.3.11", [EXE])], "mac").state, "fallback");
  assert.deepEqual({ ...plan(null, "win") }, { state: "assumed" });
});

test("looks past the first page (older code looked at 5 releases only); stops once both files are found", async () => {
  const page1 = [...Array.from({ length: 100 }, (_, i) => rel(`0.9.${100 - i}`, [DMG]))];
  const page2 = [rel("0.3.8", [DMG, EXE])];
  const urls = [];
  const fetchFn = async (u) => { urls.push(u); const p = /[?&]page=(\d)/.exec(u)[1]; return { ok: true, json: async () => (p === "1" ? page1 : p === "2" ? page2 : []) }; };
  const all = await fetchReleases(fetchFn);
  assert.equal(urls.length, 2);
  assert.equal(plan(all, "win").version, "0.3.8");
  const one = [];
  await fetchReleases(async (u) => { one.push(u); return { ok: true, json: async () => TODAY }; });
  assert.equal(one.length, 1);   // a short page is the last one
  await assert.rejects(fetchReleases(async () => ({ ok: false, status: 403 })), /403/);
});
