"use strict";
// Settings → Reset Outpost Luna (reset.js, docs/RESET.md): which folders each level deletes on macOS and Windows,
// that logs / ports / the pid file are never touched, the order (stop children → clear storage → delete → relaunch),
// that nothing happens without the backend's confirmation, and that a Windows file lock is retried, not fatal.
const test = require("node:test");
const assert = require("node:assert");
const R = require("./reset");

const MAC = "/Users/kid/Library/Application Support/Outpost Luna";
const WIN = "C:\\Users\\kid\\AppData\\Roaming\\Outpost Luna";

test("plan: Start over deletes the spoken-line cache and the turn log only; Reset everything the whole cache and hf", () => {
  assert.deepStrictEqual(R.plan("start", MAC, "darwin").delete, [`${MAC}/cache/tts`, `${MAC}/cache/turnlog`]);
  assert.deepStrictEqual(R.plan("all", MAC, "darwin").delete, [`${MAC}/cache`, `${MAC}/hf`]);
  assert.deepStrictEqual(R.plan("start", WIN, "win32").delete, [`${WIN}\\cache\\tts`, `${WIN}\\cache\\turnlog`]);
  assert.deepStrictEqual(R.plan("all", WIN, "win32").delete, [`${WIN}\\cache`, `${WIN}\\hf`]);
  for (const [u, p] of [[MAC, "darwin"], [WIN, "win32"]]) for (const lv of R.LEVELS) {
    const pl = R.plan(lv, u, p);
    assert.ok(pl.delete.every((d) => !/logs|ports\.json|children\.json/.test(d)), "never the logs, ports or pid file");
    assert.ok(pl.storages.includes("localstorage") && pl.storages.includes("indexdb"), "the page's storage on both levels");
  }
  assert.throws(() => R.plan("bogus", MAC, "darwin"));
});

test("parseResetUrl: only our own origin's reset path with a level and a token", () => {
  const o = "http://127.0.0.1:47310";
  assert.deepStrictEqual(R.parseResetUrl(`${o}/__outpost/reset?level=all&token=abc`, o), { level: "all", token: "abc" });
  assert.strictEqual(R.parseResetUrl(`${o}/__outpost/reset?level=all`, o), null);
  assert.strictEqual(R.parseResetUrl(`${o}/__outpost/reset?level=wipe&token=a`, o), null);
  assert.strictEqual(R.parseResetUrl(`http://127.0.0.1:9999/__outpost/reset?level=all&token=a`, o), null);
  assert.strictEqual(R.parseResetUrl(`${o}/`, o), null);
});

function fakes(platform, { confirmLevel = "start", lock = 0 } = {}) {
  const calls = [];
  const locked = new Map();
  return {
    calls,
    deps: {
      platform, userData: platform === "win32" ? WIN : MAC, log: (m) => calls.push(`log ${m}`),
      confirm: async (t) => { calls.push(`confirm ${t}`); return confirmLevel; },
      stopChildren: async () => { calls.push("stop"); locked.clear(); },
      session: { clearStorageData: async (o) => calls.push(`storage ${o.storages.length}`), clearCache: async () => calls.push("cache") },
      fs: { rmSync: (p, o) => {
        // a Windows file lock: rmSync's own retries (maxRetries) ride it out; a lock that never clears is reported
        if (lock && p.endsWith("cache")) { if (!(o && o.maxRetries >= 3)) { const e = new Error("busy"); e.code = "EBUSY"; throw e; } if (lock > 1) { const e = new Error("busy"); e.code = "EBUSY"; throw e; } }
        calls.push(`rm ${p}`);
      } },
      relaunch: () => calls.push("relaunch"), exit: (c) => calls.push(`exit ${c}`),
    },
  };
}

for (const platform of ["darwin", "win32"]) {
  test(`performReset (${platform}): stop children, clear storage, delete, log, relaunch; in that order`, async () => {
    const f = fakes(platform);
    const out = await R.performReset({ level: "start", token: "t1" }, f.deps);
    assert.ok(out.done);
    const order = f.calls.filter((c) => !c.startsWith("log")).map((c) => c.split(" ")[0]);
    assert.deepStrictEqual(order, ["confirm", "stop", "storage", "cache", "rm", "rm", "relaunch", "exit"]);
    assert.ok(f.calls.some((c) => c.startsWith("log reset start: cleared")), "the reset is logged");
  });

  test(`performReset (${platform}): nothing happens unless the backend confirms the same level`, async () => {
    for (const confirmLevel of [null, "start"]) {
      const f = fakes(platform, { confirmLevel });
      const out = await R.performReset({ level: "all", token: "t2" }, f.deps);
      assert.strictEqual(out.done, false);
      assert.deepStrictEqual(f.calls.filter((c) => !c.startsWith("log") && !c.startsWith("confirm")), []);
    }
  });

  test(`performReset (${platform}): Reset everything; a file still locked is reported, and the app still relaunches`, async () => {
    const f = fakes(platform, { confirmLevel: "all", lock: 1 });
    const ok = await R.performReset({ level: "all", token: "t3" }, f.deps);
    assert.ok(ok.done && ok.failed.length === 0, "rmSync is called with retries (Windows EBUSY)");
    const g = fakes(platform, { confirmLevel: "all", lock: 2 });
    const bad = await R.performReset({ level: "all", token: "t4" }, g.deps);
    assert.ok(bad.done && bad.failed.length === 1 && /EBUSY/.test(bad.failed[0]));
    assert.ok(g.calls.includes("relaunch") && g.calls.includes("exit 0"));
  });
}
