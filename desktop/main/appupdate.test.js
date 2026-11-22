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

// ---- "Download" without a browser: the main process fetches the installer (downloadInstaller) ----------------------
const crypto = require("crypto");
const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");
const BYTES = Buffer.from("a dmg, pretend ".repeat(5000));   // 75 KB
const ASSET_HOST = "https://release-assets.githubusercontent.com/github-production-release-asset/1/abc?sig=x";
const withSizes = (rel, sizes, digests = {}) => {
  for (const a of rel.assets) { a.size = sizes[a.name] ?? 95; if (digests[a.name]) a.digest = `sha256:${digests[a.name]}`; }
  return rel;
};
/** A fake fetch: routes[url] -> {status, headers, body (Buffer) | chunks | hang}; records every request. */
function fakeNet(routes) {
  const seen = [];
  const f = async (url, opts = {}) => {
    seen.push(url);
    assert.equal(opts.redirect, "manual");   // every hop is checked before it is requested
    const r = routes[url];
    if (!r) throw Object.assign(new TypeError("fetch failed"), { cause: { code: "ENOTFOUND" } });
    if (r.throws) throw r.throws;
    const h = Object.fromEntries(Object.entries(r.headers || {}).map(([k, v]) => [k.toLowerCase(), String(v)]));
    const chunks = r.chunks || (r.body ? [r.body.subarray(0, 1000), r.body.subarray(1000)] : []);
    return {
      status: r.status || 200,
      headers: { get: (k) => h[k.toLowerCase()] ?? null },
      text: async () => Buffer.concat(chunks).toString(),
      body: { cancel: async () => {}, async *[Symbol.asyncIterator]() {
        for (const c of chunks) yield c;
        if (r.hang) await new Promise((res) => opts.signal.addEventListener("abort", res));
        if (opts.signal && opts.signal.aborted) throw Object.assign(new Error("aborted"), { name: "AbortError" });
      } },
    };
  };
  f.seen = seen;
  return f;
}
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "luna-dl-"));
const parts = (dir) => fs.readdirSync(dir).filter((n) => n.endsWith(".part"));
async function available(platform = "darwin", { digests = {}, names = BOTH } = {}) {
  const rel = withSizes(release("0.3.9", names), { "Outpost-Luna-0.3.9-arm64.dmg": BYTES.length, "Outpost-Luna-mac-arm64.dmg": BYTES.length,
    "Outpost-Luna-win-x64.exe": BYTES.length }, digests);
  return AU.check({ appVersion: "0.3.8", platform, fetchImpl: respond(200, rel) });
}
const macRoutes = (body = BYTES, shaText = `${sha(BYTES)}  Outpost-Luna-0.3.9-arm64.dmg\n`) => ({
  [`${DL}/v0.3.9/Outpost-Luna-mac-arm64.dmg`]: { status: 302, headers: { Location: ASSET_HOST } },
  [ASSET_HOST]: { body, headers: { "Content-Length": body.length } },
  [`${DL}/v0.3.9/Outpost-Luna-0.3.9-arm64.dmg.sha256`]: { status: 302, headers: { Location: ASSET_HOST + "&sha" } },
  [ASSET_HOST + "&sha"]: { body: Buffer.from(shaText) },
});

test("check: the installer's size, GitHub's digest and the matching .sha256 (the versioned file for the stable copy)", async () => {
  const r = await available("darwin", { digests: { "Outpost-Luna-mac-arm64.dmg": sha(BYTES), "Outpost-Luna-0.3.9-arm64.dmg": sha(BYTES) } });
  assert.equal(r.asset, "Outpost-Luna-mac-arm64.dmg");
  assert.equal(r.size, BYTES.length);
  assert.equal(r.digest, sha(BYTES));
  assert.equal(r.sha_url, `${DL}/v0.3.9/Outpost-Luna-0.3.9-arm64.dmg.sha256`);
  const w = await available("win32");
  assert.equal(w.sha_url, null);   // no .sha256 for the exe: never borrow the dmg's
  assert.equal(w.digest, null);
  const rel = AU.parseRelease(withSizes(release("0.3.9", ["Outpost-Luna-0.3.9-arm64.dmg", "Outpost-Luna-0.3.9-arm64.dmg.sha256", "Outpost-Luna-mac-arm64.dmg"]),
    { "Outpost-Luna-0.3.9-arm64.dmg": 10, "Outpost-Luna-mac-arm64.dmg": 11 }));
  assert.equal(AU.pickSha(rel, AU.pickAsset(rel, "darwin"), "darwin"), null);   // a different size: not the same file
});

test("sha256 file parsing and the release-asset redirect hosts", () => {
  const h = "ab".repeat(32);
  assert.equal(AU.parseShaFile(`${h}  Outpost-Luna-0.3.9-arm64.dmg\n`), h);
  assert.equal(AU.parseShaFile(`SHA256 (x.dmg) = ${h.toUpperCase()}`), h);
  assert.equal(AU.parseShaFile("no hash"), null);
  assert.equal(AU.parseShaFile("a".repeat(65)), null);
  assert.equal(AU.assetHostAllowed(ASSET_HOST), true);
  assert.equal(AU.assetHostAllowed("https://objects.githubusercontent.com/x"), true);
  for (const bad of ["http://objects.githubusercontent.com/x", "https://evil.githubusercontent.com/x", "https://u:p@objects.githubusercontent.com/x",
    "https://objects.githubusercontent.com:444/x", "nope"]) assert.equal(AU.assetHostAllowed(bad), false, bad);
  assert.equal(AU.openAllowed(ASSET_HOST), false);   // fetched for the download, never handed to a browser
});

test("download: follows GitHub's redirect, checks size and sha256, lands in the folder; progress reported", async () => {
  const dir = tmp();
  const last = await available("darwin");
  const net = fakeNet(macRoutes());
  const prog = [];
  const r = await AU.downloadInstaller({ last, dir, fetchImpl: net, onProgress: (g, t) => prog.push([g, t]), appVersion: "0.3.8" });
  assert.equal(r.file, path.join(dir, "Outpost-Luna-mac-arm64.dmg"));
  assert.equal(r.verified, "sha256");
  assert.equal(r.bytes, BYTES.length);
  assert.ok(fs.readFileSync(r.file).equals(BYTES));
  assert.deepEqual(prog.at(-1), [BYTES.length, BYTES.length]);
  assert.ok(prog.length >= 2);
  assert.deepEqual(parts(dir), []);
  assert.equal(net.seen[0], `${DL}/v0.3.9/Outpost-Luna-0.3.9-arm64.dmg.sha256`);   // the checksum first
  fs.rmSync(dir, { recursive: true, force: true });
});

test("download: never overwrites: a file with that name already there -> 'name (1).dmg', the old one untouched", async () => {
  const dir = tmp();
  fs.writeFileSync(path.join(dir, "Outpost-Luna-mac-arm64.dmg"), "old");
  fs.writeFileSync(path.join(dir, "Outpost-Luna-mac-arm64 (1).dmg"), "older");
  const last = await available("darwin");
  const r = await AU.downloadInstaller({ last, dir, fetchImpl: fakeNet(macRoutes()) });
  assert.equal(path.basename(r.file), "Outpost-Luna-mac-arm64 (2).dmg");
  assert.equal(fs.readFileSync(path.join(dir, "Outpost-Luna-mac-arm64.dmg"), "utf8"), "old");
  assert.equal(AU.uniquePath("/d", "a.exe", (p) => p === path.join("/d", "a.exe")), path.join("/d", "a (1).exe"));
  fs.rmSync(dir, { recursive: true, force: true });
});

test("download: a wrong sha256, a short file, a too-long file or a Content-Length that disagrees -> 'check', nothing left", async () => {
  const last = await available("darwin");
  const cases = [
    macRoutes(BYTES, `${"0".repeat(64)}  x.dmg\n`),
    macRoutes(BYTES.subarray(0, 1000)),
    { ...macRoutes(), [ASSET_HOST]: { chunks: [BYTES, Buffer.from("extra")] } },
    { ...macRoutes(), [ASSET_HOST]: { body: BYTES, headers: { "Content-Length": 5 } } },
    macRoutes(BYTES, "not a checksum"),
  ];
  for (const routes of cases) {
    const dir = tmp();
    await assert.rejects(AU.downloadInstaller({ last, dir, fetchImpl: fakeNet(routes) }), (e) => e.kind === "check");
    assert.deepEqual(fs.readdirSync(dir), []);
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("download: verified by GitHub's digest when there is no .sha256 file; by size when there is neither (Windows .exe)", async () => {
  const exe = `${DL}/v0.3.9/Outpost-Luna-win-x64.exe`;
  const routes = { [exe]: { status: 302, headers: { Location: ASSET_HOST } }, [ASSET_HOST]: { body: BYTES } };
  let dir = tmp();
  const d = await AU.downloadInstaller({ last: await available("win32", { digests: { "Outpost-Luna-win-x64.exe": sha(BYTES) } }), dir, fetchImpl: fakeNet(routes) });
  assert.equal(d.verified, "sha256");
  assert.equal(path.basename(d.file), "Outpost-Luna-win-x64.exe");
  await assert.rejects(AU.downloadInstaller({ last: await available("win32", { digests: { "Outpost-Luna-win-x64.exe": "1".repeat(64) } }), dir, fetchImpl: fakeNet(routes) }),
    (e) => e.kind === "check");
  fs.rmSync(dir, { recursive: true, force: true });
  dir = tmp();
  assert.equal((await AU.downloadInstaller({ last: await available("win32"), dir, fetchImpl: fakeNet(routes) })).verified, "size");
  fs.rmSync(dir, { recursive: true, force: true });
});

test("download: only our repo, then GitHub's asset hosts; a redirect anywhere else is refused before it is requested", async () => {
  const dir = tmp();
  const last = await available("darwin");
  const routes = { ...macRoutes(), [ASSET_HOST]: { status: 302, headers: { Location: "https://evil.example/x.dmg" } } };
  const net = fakeNet(routes);
  await assert.rejects(AU.downloadInstaller({ last, dir, fetchImpl: net }), (e) => e.kind === "error");
  assert.ok(!net.seen.includes("https://evil.example/x.dmg"));
  await assert.rejects(AU.downloadInstaller({ last: { ...last, download: "https://evil.example/x.dmg" }, dir, fetchImpl: net }), (e) => e.kind === "error");
  const up = await AU.downloadInstaller({ last: { ...last, asset: "../../x.dmg" }, dir, fetchImpl: fakeNet(macRoutes()) });
  assert.equal(up.file, path.join(dir, "x.dmg"));   // a name with a path is reduced to its base name: never outside the folder
  await assert.rejects(AU.downloadInstaller({ last: { ...last, asset: "notes.txt" }, dir, fetchImpl: net }), (e) => e.kind === "error");
  fs.rmSync(dir, { recursive: true, force: true });
});

test("download under School network mode: github.com not allowed -> 'school', no request; allowed -> its asset host too", async () => {
  const dir = tmp();
  const last = await available("darwin");
  const net = fakeNet(macRoutes());
  await assert.rejects(AU.downloadInstaller({ last, dir, fetchImpl: net, hostOk: () => false }), (e) => e.kind === "school");
  assert.deepEqual(net.seen, []);
  const r = await AU.downloadInstaller({ last, dir, fetchImpl: fakeNet(macRoutes()), hostOk: (h) => h === "github.com" });
  assert.equal(r.verified, "sha256");
  fs.rmSync(dir, { recursive: true, force: true });
});

test("download: offline, a stalled transfer, an HTTP error and an unwritable folder each fail cleanly", async () => {
  const last = await available("darwin");
  let dir = tmp();
  await assert.rejects(AU.downloadInstaller({ last, dir, fetchImpl: fakeNet({}) }), (e) => e.kind === "offline");
  await assert.rejects(AU.downloadInstaller({ last, dir, stallMs: 50, fetchImpl: fakeNet({ ...macRoutes(), [ASSET_HOST]: { chunks: [BYTES.subarray(0, 10)], hang: true } }) }),
    (e) => e.kind === "offline" && /stalled/.test(e.message));
  await assert.rejects(AU.downloadInstaller({ last, dir, fetchImpl: fakeNet({ ...macRoutes(), [ASSET_HOST]: { status: 500 } }) }), (e) => e.kind === "error");
  assert.deepEqual(fs.readdirSync(dir), []);
  const file = path.join(dir, "a-file");
  fs.writeFileSync(file, "x");
  await assert.rejects(AU.downloadInstaller({ last, dir: path.join(file, "sub"), fetchImpl: fakeNet(macRoutes()) }), (e) => e.kind === "disk");
  fs.rmSync(dir, { recursive: true, force: true });
  await assert.rejects(AU.downloadInstaller({ last: null, dir }), (e) => e.kind === "error");
});

test("the page may ask to show the downloaded file in its folder", () => {
  const o = "http://127.0.0.1:47999";
  assert.deepEqual(AU.parseUpdateUrl(`${o}/__outpost/update?do=open&what=folder`, o), { do: "open", what: "folder" });
  assert.equal(AU.targetUrl({}, "folder"), null);   // never a URL
});

test("openWithFallback: awaited; a browser that does not open is logged and the page is told the link", async () => {
  const told = [], logs = [];
  assert.equal(await AU.openWithFallback("https://x.org/", { open: async () => {}, onFail: (u) => told.push(u) }), true);
  assert.deepEqual(told, []);
  const nope = async () => { throw new Error("Failed to open URL (-10810)"); };
  assert.equal(await AU.openWithFallback("https://x.org/a", { open: nope, log: (...a) => logs.push(a.join(" ")), onFail: (u) => told.push(u) }), false);
  assert.deepEqual(told, ["https://x.org/a"]);
  assert.match(logs[0], /web browser did not open: Failed to open URL \(-10810\)/);
  assert.equal(await AU.openWithFallback("https://x.org/b", { open: nope, onFail: () => { throw new Error("page gone"); } }), false);   // never throws
});
