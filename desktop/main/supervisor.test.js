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

test("Windows: commandOf reads the CIM command line, falls back to tasklist, null when gone", () => {
  const calls = [];
  const exec = (impl) => (cmd, args) => { calls.push(cmd); return impl(cmd, args); };
  const LAUNCH = "C:\\Users\\kid\\AppData\\Local\\Programs\\Outpost Luna\\resources\\app\\launch.py";
  const cl = `"C:\\Users\\kid\\AppData\\Local\\Programs\\Outpost Luna\\resources\\python\\python.exe" "${LAUNCH}" models --port 47210`;
  assert.strictEqual(S.commandOf(42, { platform: "win32", exec: exec((c) => (c === "powershell.exe" ? cl + "\r\n" : "")) }), cl);
  assert.deepStrictEqual(calls, ["powershell.exe"]);
  calls.length = 0;
  const tl = '"python.exe","42","Console","1","120,000 K"';
  assert.strictEqual(S.commandOf(42, { platform: "win32", exec: exec((c) => { if (c === "powershell.exe") throw new Error("ENOENT"); return tl + "\r\n"; }) }), tl);
  assert.deepStrictEqual(calls, ["powershell.exe", "tasklist"]);
  const gone = (c) => (c === "powershell.exe" ? "\r\n" : "INFO: No tasks are running which match the specified criteria.\r\n");
  assert.strictEqual(S.commandOf(42, { platform: "win32", exec: gone }), null);
});

test("Windows: isOurChild matches our launcher (any case), a bare python.exe only from tasklist, never someone else's", () => {
  const LAUNCH = "C:\\Program Files\\Outpost Luna\\resources\\app\\launch.py";
  assert.ok(S.isOurChild(`"C:\\PROGRAM FILES\\Outpost Luna\\resources\\python\\python.exe" "${LAUNCH.toUpperCase()}" backend`, LAUNCH, "win32"));
  assert.ok(S.isOurChild('"python.exe","42","Console","1","120,000 K"', LAUNCH, "win32"), "tasklist fallback");
  assert.ok(!S.isOurChild('"C:\\Python311\\python.exe" C:\\work\\train.py', LAUNCH, "win32"), "a reused pid running the user's own python");
  assert.ok(!S.isOurChild(null, LAUNCH, "win32"));
  assert.ok(!S.isOurChild('"python.exe","42","Console","1","120,000 K"', "/app/launch.py", "darwin"), "POSIX needs the launcher path");
  assert.ok(S.isOurChild("/x/python3 /x/app/launch.py models", "/x/app/launch.py", "darwin"));
});

test("Windows: children are not detached (no console), hidden, and killed as a tree", () => {
  const w = S.childSpawnOptions({ cwd: "C:\\app", env: {}, out: 3, platform: "win32" });
  assert.strictEqual(w.detached, false);
  assert.strictEqual(w.windowsHide, true);
  assert.deepStrictEqual(w.stdio, ["ignore", 3, 3]);
  assert.strictEqual(S.childSpawnOptions({ cwd: "/app", env: {}, out: 3, platform: "darwin" }).detached, true);
  assert.deepStrictEqual(S.taskkillArgs(1234), ["/PID", "1234", "/T", "/F"]);
});

test("childEnv keeps the Windows variables Python and its DLL loading need", () => {
  const parent = { SystemRoot: "C:\\Windows", APPDATA: "C:\\Users\\kid\\AppData\\Roaming", LOCALAPPDATA: "C:\\Users\\kid\\AppData\\Local",
    TEMP: "C:\\Users\\kid\\AppData\\Local\\Temp", USERPROFILE: "C:\\Users\\kid", PATHEXT: ".EXE", GEMINI_API_KEY: "x" };
  const env = S.childEnv({}, parent);
  for (const k of ["SystemRoot", "APPDATA", "LOCALAPPDATA", "TEMP", "USERPROFILE", "PATHEXT"]) assert.strictEqual(env[k], parent[k], k);
  assert.strictEqual(env.GEMINI_API_KEY, undefined);
  assert.strictEqual(env.PYTHONUTF8, "1", "UTF-8 file I/O whatever the Windows code page");
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
