"use strict";
// Settings -> "Check for updates" (appupdate.js): version compare, the installer per platform, the open allow-list,
// GitHub response parsing (draft / prerelease ignored, missing assets, rate limit, offline), the once-a-day opt-in.
// No network: fetch is a fake.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const AU = require("./appupdate");

const DL = "https://github.com/WhissleAI/Outpost-Luna/releases/download";
const asset = (v, name) => ({ name, state: "uploaded", browser_download_url: `${DL}/v${v}/${name}` });
const release = (v, names, extra = {}) => ({
  tag_name: `v${v}`, draft: false, prerelease: false, html_url: `https://github.com/WhissleAI/Outpost-Luna/releases/tag/v${v}`,
  body: `## Outpost Luna ${v}\n\n**Mac:** download it.\n\n### What's new\n- **Check for updates** in Settings.\n- Faster [first launch](https://x.y).\n- Fixes.\n- A fourth line.\n\n### Checks\n- passed`,
  assets: names.map((n) => asset(v, n)), ...extra });
const BOTH = ["Outpost-Luna-0.3.9-arm64.dmg", "Outpost-Luna-0.3.9-arm64.dmg.sha256", "Outpost-Luna-mac-arm64.dmg", "Outpost-Luna-win-x64.exe"];
const respond = (status, body) => async (url, opts) => {
  respond.last = { url, opts };
  return { status, text: async () => (typeof body === "string" ? body : JSON.stringify(body)) };
};

test("version compare: numeric, a leading v and pre-release suffixes ignored", () => {
  assert.equal(AU.cmpVersion("0.3.9", "0.3.8"), 1);
  assert.equal(AU.cmpVersion("v0.3.8", "0.3.8"), 0);
  assert.equal(AU.cmpVersion("0.3.10", "0.3.9"), 1);
  assert.equal(AU.cmpVersion("0.4", "0.3.99"), 1);
  assert.equal(AU.cmpVersion("0.3.7", "0.3.8"), -1);
});

test("asset per platform: the stable name first, a versioned one as fallback, never the .sha256", () => {
  const rel = AU.parseRelease(release("0.3.9", BOTH));
  assert.equal(AU.pickAsset(rel, "darwin").name, "Outpost-Luna-mac-arm64.dmg");
  assert.equal(AU.pickAsset(rel, "win32").name, "Outpost-Luna-win-x64.exe");
  assert.equal(AU.pickAsset(rel, "linux"), null);
  const versioned = AU.parseRelease(release("0.3.9", ["Outpost-Luna-0.3.9-arm64.dmg.sha256", "Outpost-Luna-0.3.9-arm64.dmg", "Outpost.Luna.Setup.0.3.9.exe"]));
  assert.equal(AU.pickAsset(versioned, "darwin").name, "Outpost-Luna-0.3.9-arm64.dmg");
  assert.equal(AU.pickAsset(versioned, "win32").name, "Outpost.Luna.Setup.0.3.9.exe");
  const macOnly = AU.parseRelease(release("0.3.9", BOTH.slice(0, 3)));
  assert.equal(AU.pickAsset(macOnly, "win32"), null);
  assert.deepEqual(AU.otherPlatforms(macOnly, "win32"), ["Mac"]);
});

test("open allow-list: https on our repo at github.com or our site, nothing else", () => {
  for (const ok of [`${DL}/v0.3.9/Outpost-Luna-mac-arm64.dmg`, "https://github.com/WhissleAI/Outpost-Luna/releases/tag/v0.3.9",
    "https://github.com/whissleai/outpost-luna/releases/latest", "https://whissleai.github.io/Outpost-Luna/", "https://whissleai.github.io/Outpost-Luna"])
    assert.equal(AU.openAllowed(ok), true, ok);
  for (const bad of ["http://github.com/WhissleAI/Outpost-Luna/releases", "https://github.com/evil/Outpost-Luna/releases",
    "https://github.com.evil.io/WhissleAI/Outpost-Luna/", "https://evil.github.io/Outpost-Luna/", "https://whissleai.github.io/other/",
    "https://user:pw@github.com/WhissleAI/Outpost-Luna/", "https://github.com:8443/WhissleAI/Outpost-Luna/", "file:///etc/passwd",
    "javascript:alert(1)", "https://objects.githubusercontent.com/x", "", null, "not a url"])
    assert.equal(AU.openAllowed(bad), false, String(bad));
});

test("release notes: the What's new bullets as plain text, three lines at most", () => {
  const rel = AU.parseRelease(release("0.3.9", BOTH));
  assert.equal(rel.notes, "Check for updates in Settings.\nFaster first launch.\nFixes.");
  assert.equal(AU.summarize("## Title\n\nJust a **line**.\n\nAnother."), "Just a line.\nAnother.");
  assert.equal(AU.summarize(""), "");
  assert.ok(AU.summarize("x ".repeat(400)).length <= 320);
});

test("parse: drafts, prereleases, odd tags and off-list asset URLs are ignored", () => {
  assert.equal(AU.parseRelease(release("0.3.9", BOTH, { draft: true })), null);
  assert.equal(AU.parseRelease(release("0.3.9", BOTH, { prerelease: true })), null);
  assert.equal(AU.parseRelease({ ...release("0.3.9", BOTH), tag_name: "nightly" }), null);
  assert.equal(AU.parseRelease(null), null);
  const r = release("0.3.9", BOTH);
  r.assets[2].browser_download_url = "https://evil.example/Outpost-Luna-mac-arm64.dmg";
  assert.equal(AU.pickAsset(AU.parseRelease(r), "darwin").name, "Outpost-Luna-0.3.9-arm64.dmg");
});

test("check: newer release -> available, with the platform's installer; the request is identified, unauthenticated", async () => {
  const r = await AU.check({ appVersion: "0.3.8", platform: "darwin", fetchImpl: respond(200, release("0.3.9", BOTH)) });
  assert.equal(r.state, "available");
  assert.equal(r.latest, "0.3.9");
  assert.equal(r.current, "0.3.8");
  assert.equal(r.download, `${DL}/v0.3.9/Outpost-Luna-mac-arm64.dmg`);
  assert.equal(respond.last.url, AU.LATEST_URL);
  assert.equal(respond.last.opts.headers["User-Agent"], "Outpost-Luna/0.3.8");
  assert.equal(respond.last.opts.headers.Authorization, undefined);
  const w = await AU.check({ appVersion: "0.3.8", platform: "win32", fetchImpl: respond(200, release("0.3.9", BOTH)) });
  assert.equal(w.download, `${DL}/v0.3.9/Outpost-Luna-win-x64.exe`);
  assert.equal(w.platform, "Windows");
});

test("check: same or older release -> up to date; a prerelease 'latest' never offers itself", async () => {
  assert.equal((await AU.check({ appVersion: "0.3.8", platform: "darwin", fetchImpl: respond(200, release("0.3.8", BOTH)) })).state, "up_to_date");
  assert.equal((await AU.check({ appVersion: "0.4.0", platform: "darwin", fetchImpl: respond(200, release("0.3.9", BOTH)) })).state, "up_to_date");
  const pre = await AU.check({ appVersion: "0.3.8", platform: "darwin", fetchImpl: respond(200, release("0.4.0", BOTH, { prerelease: true })) });
  assert.equal(pre.state, "up_to_date");
  assert.equal(pre.latest, null);
});

test("check: this platform's installer missing -> available, no download, the platforms it is out for", async () => {
  const r = await AU.check({ appVersion: "0.3.8", platform: "win32", fetchImpl: respond(200, release("0.3.9", BOTH.slice(0, 3))) });
  assert.equal(r.state, "available");
  assert.equal(r.download, null);
  assert.deepEqual(r.others, ["Mac"]);
  assert.equal(r.release, "https://github.com/WhissleAI/Outpost-Luna/releases/tag/v0.3.9");
});

test("check: rate limit (403 / 429), offline, timeout, 5xx and junk JSON all come back as an error, never a throw", async () => {
  const kind = async (fetchImpl, timeoutMs) => (await AU.check({ appVersion: "0.3.8", platform: "darwin", fetchImpl, timeoutMs })).reason;
  assert.equal(await kind(respond(403, { message: "API rate limit exceeded" })), "rate_limited");
  assert.equal(await kind(respond(429, "")), "rate_limited");
  assert.equal(await kind(async () => { throw Object.assign(new TypeError("fetch failed"), { cause: { code: "ENOTFOUND" } }); }), "offline");
  assert.equal(await kind((u, o) => new Promise((_, rej) => o.signal.addEventListener("abort", () => rej(Object.assign(new Error("aborted"), { name: "AbortError" })))), 20), "offline");
  assert.equal(await kind(respond(502, "")), "error");
  assert.equal(await kind(respond(200, "<html>")), "error");
  const r = await AU.check({ appVersion: "0.3.8", platform: "darwin", fetchImpl: respond(403, {}) });
  assert.equal(r.state, "error");
  assert.equal(r.site, "https://whissleai.github.io/Outpost-Luna/");
});

test("open targets come from the last result, allow-listed; the page never names a URL", () => {
  const last = { download: `${DL}/v0.3.9/Outpost-Luna-mac-arm64.dmg`, release: "https://github.com/WhissleAI/Outpost-Luna/releases/tag/v0.3.9" };
  assert.equal(AU.targetUrl(last, "download"), last.download);
  assert.equal(AU.targetUrl(last, "release"), last.release);
  assert.equal(AU.targetUrl(null, "release"), AU.RELEASES_URL);
  assert.equal(AU.targetUrl(null, "site"), AU.SITE_URL);
  assert.equal(AU.targetUrl(null, "download"), null);
  assert.equal(AU.targetUrl({ download: "https://evil.example/x.dmg" }, "download"), null);
  assert.equal(AU.targetUrl(last, "anything"), null);
});

test("the page's request URL: only /__outpost/update on our origin, known actions only", () => {
  const o = "http://127.0.0.1:47999";
  assert.deepEqual(AU.parseUpdateUrl(`${o}/__outpost/update?do=check`, o), { do: "check" });
  assert.deepEqual(AU.parseUpdateUrl(`${o}/__outpost/update?do=open&what=download`, o), { do: "open", what: "download" });
  assert.equal(AU.parseUpdateUrl(`${o}/__outpost/update?do=open&what=https://evil.example`, o), null);
  assert.equal(AU.parseUpdateUrl(`${o}/__outpost/update?do=install`, o), null);
  assert.equal(AU.parseUpdateUrl(`http://127.0.0.1:1/__outpost/update?do=check`, o), null);
  assert.equal(AU.parseUpdateUrl(`${o}/api/update?do=check`, o), null);
});

test("opt-in launch check: at most once a day, the attempt counts, survives restarts", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "luna-au-"));
  const file = path.join(dir, "update-check.json");
  let t = Date.parse("2026-11-16T09:00:00Z");
  const g = AU.createAutoGate({ file, now: () => t });
  assert.equal(g.due(), true);          // never checked
  g.mark();
  assert.equal(g.due(), false);         // same launch / a reload
  t += 23 * 3600e3;
  assert.equal(AU.createAutoGate({ file, now: () => t }).due(), false);   // next launch, same day
  t += 3600e3;
  assert.equal(AU.createAutoGate({ file, now: () => t }).due(), true);    // 24 h later
  fs.writeFileSync(file, "{junk");
  assert.equal(g.due(), true);          // a damaged file never blocks it forever
  g.mark();
  t -= 10 * AU.DAY_MS;                  // the clock moved back a lot: allowed again
  assert.equal(g.due(), true);
  fs.rmSync(dir, { recursive: true, force: true });
});
