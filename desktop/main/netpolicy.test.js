// School network mode in the shell (netpolicy.js, docs/SCHOOL_IT.md): the machine policy, the user switch, the gated fetch.
"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs");
const os = require("os");
const path = require("path");
const NP = require("./netpolicy");

const files = (map) => (f) => { if (f in map) { if (map[f] instanceof Error) throw map[f]; return map[f]; } throw Object.assign(new Error("no"), { code: "ENOENT" }); };

test("machine policy: where it is looked for on each OS", () => {
  assert.deepEqual(NP.machinePaths({ platform: "darwin", env: {}, execPath: "/Applications/Outpost Luna.app/Contents/MacOS/Outpost Luna" }),
    ["/Library/Application Support/Outpost Luna/policy.json"]);
  assert.deepEqual(NP.machinePaths({ platform: "win32", env: { ProgramData: "C:\\ProgramData" }, execPath: "C:\\Program Files\\Outpost Luna\\Outpost Luna.exe" }),
    ["C:\\Program Files\\Outpost Luna\\policy.json", "C:\\ProgramData\\Outpost Luna\\policy.json"]);
  assert.deepEqual(NP.machinePaths({ platform: "darwin", env: { OUTPOST_POLICY_FILE: "/x/p.json", OUTPOST_POLICY_SEARCH: "0" } }), ["/x/p.json"]);
});

test("machine policy: the file, the variables, and a broken file fails closed", () => {
  const P = "/Library/Application Support/Outpost Luna/policy.json";
  const read = (map, env = {}) => NP.readMachine({ platform: "darwin", env, readFile: files(map) });
  assert.deepEqual(read({}), { school_network: false, allow_hosts: [], open_links: true, source: "" });
  let p = read({ [P]: "\uFEFF" + JSON.stringify({ allow_hosts: ["*.NASA.gov", "nope host", "GitHub.io."] }) });
  assert.equal(p.school_network, true, "a policy file with no school_network key means on");
  assert.deepEqual(p.allow_hosts, ["nasa.gov", "github.io"]);
  p = read({ [P]: JSON.stringify({ school_network: false }) });
  assert.equal(p.school_network, false);
  p = read({ [P]: "{oops" });
  assert.equal(p.school_network, true); assert.deepEqual(p.allow_hosts, []); assert.equal(p.open_links, false);
  p = read({ [P]: Object.assign(new Error("denied"), { code: "EACCES" }) });
  assert.equal(p.school_network, true, "a file we may not read: on");
  p = read({}, { OUTPOST_SCHOOL_NETWORK: "1", OUTPOST_ALLOW_HOSTS: "example.org, nasa.gov" });
  assert.equal(p.school_network, true); assert.deepEqual(p.allow_hosts, ["example.org", "nasa.gov"]); assert.equal(p.source, "OUTPOST_SCHOOL_NETWORK");
});

test("effective: a machine policy locks it on; the user can only turn it on", () => {
  assert.equal(NP.effective({ school_network: true, allow_hosts: ["a.org"] }, false).locked, true);
  assert.deepEqual(NP.effective({ school_network: true, allow_hosts: ["a.org"] }, false).allow_hosts, ["a.org"]);
  const u = NP.effective({ school_network: false, allow_hosts: [] }, true);
  assert.equal(u.school_network, true); assert.equal(u.locked, false); assert.equal(u.source, "user");
  assert.equal(NP.effective({ school_network: false }, false).school_network, false);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "np-"));
  const f = path.join(dir, "network.json");
  assert.equal(NP.readUser(f), false);
  fs.writeFileSync(f, JSON.stringify({ school_network: true }));
  assert.equal(NP.readUser(f), true);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("hosts: loopback always, an allowed domain and its subdomains, nothing that only looks like one", () => {
  const pol = { school_network: true, allow_hosts: ["nasa.gov"] };
  for (const h of ["127.0.0.1", "localhost", "[::1]", "::1"]) assert.equal(NP.hostAllowed(h, pol), true, h);
  assert.equal(NP.hostAllowed("images-api.nasa.gov", pol), true);
  assert.equal(NP.hostAllowed("evilnasa.gov", pol), false);
  assert.equal(NP.hostAllowed("nasa.gov.evil.example", pol), false);
  assert.equal(NP.urlAllowed("data:text/plain,hi", pol), true);
  assert.equal(NP.urlAllowed("wss://api.deepgram.com/x", pol), false);
  assert.equal(NP.urlAllowed("https://example.org/", { school_network: false }), true);
});

test("gated fetch: a blocked host never reaches the real fetch; off, nothing changes", async () => {
  const calls = [];
  const real = async (url, opts) => { calls.push([url, opts && opts.redirect]); return { status: 200, headers: new Map() }; };
  let pol = { school_network: true, allow_hosts: [] };
  const f = NP.gateFetch(real, () => pol);
  await assert.rejects(f("https://api.github.com/repos/WhissleAI/Outpost-Luna/releases/latest"), (e) => e.kind === "school" && e.offline === true);
  await assert.rejects(f("https://www.dropbox.com/s/x/model.zip?dl=1"), (e) => e.school);
  assert.deepEqual(calls, [], "nothing left the shell");
  await f("http://127.0.0.1:47310/health");
  assert.equal(calls.length, 1, "loopback still works");
  pol = { school_network: false };
  calls.length = 0;
  await f("https://www.dropbox.com/s/x", { redirect: "follow" });
  assert.deepEqual(calls, [["https://www.dropbox.com/s/x", "follow"]], "off: the real fetch, options untouched");
});

test("gated fetch: every redirect hop is checked (an allowed host cannot bounce a download somewhere else)", async () => {
  const hops = { "https://dl.example.org/a": "https://cdn.example.org/a", "https://cdn.example.org/a": "https://elsewhere.example/a" };
  const calls = [];
  const real = async (url, opts) => {
    calls.push(url);
    assert.equal(opts.redirect, "manual");
    const to = hops[url];
    return { status: to ? 302 : 200, headers: { get: (k) => (k === "location" ? to : null) } };
  };
  const f = NP.gateFetch(real, () => ({ school_network: true, allow_hosts: ["example.org"] }));
  await assert.rejects(f("https://dl.example.org/a"), (e) => e.host === "elsewhere.example");
  assert.deepEqual(calls, ["https://dl.example.org/a", "https://cdn.example.org/a"], "the third hop was never requested");
  hops["https://cdn.example.org/a"] = null;
  const r = await f("https://dl.example.org/a");
  assert.equal(r.status, 200);
});

test("the app update check reports school network mode, not 'offline'", async () => {
  const AU = require("./appupdate");
  const f = NP.gateFetch(async () => { throw new Error("must not be called"); }, () => ({ school_network: true, allow_hosts: [] }));
  const r = await AU.check({ appVersion: "0.4.2", platform: "darwin", fetchImpl: f });
  assert.equal(r.state, "error"); assert.equal(r.reason, "school");
});
