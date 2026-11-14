"use strict";
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const net = require("net");
const path = require("path");
const { spawn } = require("child_process");
const S = require("./supervisor");

test("pickPort: preferred when free, another when taken", async () => {
  const free = await S.pickPort([]);
  assert.strictEqual(await S.pickPort([free]), free);
  const srv = net.createServer().listen(free, "127.0.0.1");
  await new Promise((r) => srv.once("listening", r));
  const other = await S.pickPort([free]);
  assert.notStrictEqual(other, free);
  srv.close();
});

test("pickPort: never returns an avoided port", async () => {
  const p = await S.pickPort([]);
  assert.notStrictEqual(await S.pickPort([p], new Set([p])), p);
});

test("childEnv: no inherited API keys, offline flags set", () => {
  const env = S.childEnv({ X: "1" }, { PATH: "/bin", DEEPGRAM_API_KEY: "secret", NASA_API_KEY: "k", OPENAI_API_KEY: "o" });
  assert.strictEqual(env.PATH, "/bin");
  assert.strictEqual(env.DEEPGRAM_API_KEY, "");
  assert.strictEqual(env.NASA_API_KEY, "");
  assert.strictEqual(env.OPENAI_API_KEY, undefined);
  assert.strictEqual(env.HF_HUB_OFFLINE, "1");
  assert.strictEqual(env.X, "1");
});

test("killTree kills a detached child and its grandchild; reap kills stale pids", { skip: S.IS_WIN }, async () => {
  const marker = `outpost-test-${process.pid}`;
  const p = spawn("/bin/sh", ["-c", `sleep 30 & sleep 31; : ${marker}`], { detached: true, stdio: "ignore" });
  await S.sleep(200);
  assert.ok(S.alive(p.pid));
  await S.killTree(p.pid, 1000);
  await S.sleep(100);
  assert.ok(!S.alive(p.pid) || S.commandOf(p.pid) === null);

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pidfile-"));
  const pf = new S.PidFile(path.join(dir, "children.json"));
  const q = spawn("/bin/sh", ["-c", `sleep 30; : ${marker}`], { detached: true, stdio: "ignore" });
  q.unref();
  pf.add({ name: "t", pid: q.pid });
  pf.add({ name: "gone", pid: 999999 });
  await S.sleep(200);
  const killed = await pf.reap(marker);
  assert.deepStrictEqual(killed, [q.pid]);
  assert.deepStrictEqual(pf.read(), []);
});
