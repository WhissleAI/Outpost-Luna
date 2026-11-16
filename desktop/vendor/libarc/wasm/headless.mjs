// Run the libarc WebAssembly page in a headless Chromium (silent: --headless, --mute-audio, no window) and print
// window.arcResult as JSON. Node 22+ (global WebSocket). Used for docs/EMBEDDING.md's measurements.
//   node desktop/vendor/libarc/wasm/headless.mjs "http://127.0.0.1:47931/?clip=c11_0" [chrome binary] [timeout s]
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync, readdirSync, existsSync } from "node:fs";
import { tmpdir, homedir } from "node:os";
import { join } from "node:path";

const url = process.argv[2];
const timeoutS = Number(process.argv[4] || 600);
function findChrome() {
  if (process.argv[3]) return process.argv[3];
  const pw = join(homedir(), "Library/Caches/ms-playwright");
  for (const d of existsSync(pw) ? readdirSync(pw).sort().reverse() : []) {
    const p = join(pw, d, "chrome-headless-shell-mac-arm64/chrome-headless-shell");
    if (d.startsWith("chromium_headless_shell") && existsSync(p)) return p;
  }
  return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
}
const port = 47932;
const profile = mkdtempSync(join(tmpdir(), "arc-wasm-"));
const chrome = spawn(findChrome(), ["--headless", "--mute-audio", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0;
const pending = new Map();
const send = (method, params = {}) => new Promise((res) => {
  const i = ++id;
  pending.set(i, res);
  ws.send(JSON.stringify({ id: i, method, params }));
});
try {
  let target;
  for (let i = 0; i < 100 && !target; ++i) {
    await sleep(100);
    try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch {}
  }
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id && pending.has(d.id)) { pending.get(d.id)(d.result); pending.delete(d.id); }
    else if (d.method === "Runtime.consoleAPICalled")
      console.error("[page]", d.params.args.map((a) => a.value ?? a.description).join(" "));
    else if (d.method === "Runtime.exceptionThrown") console.error("[page exception]", JSON.stringify(d.params.exceptionDetails).slice(0, 500));
  };
  await send("Runtime.enable");
  await send("Page.navigate", { url });
  const t0 = Date.now();
  let r = null;
  while (!r && Date.now() - t0 < timeoutS * 1000) {
    await sleep(500);
    const v = await send("Runtime.evaluate", { expression: "window.arcResult ? JSON.stringify(window.arcResult) : ''" });
    if (v && v.result && v.result.value) r = v.result.value;
  }
  console.log(r || JSON.stringify({ error: "timeout", reason: `no result in ${timeoutS} s` }));
} finally {
  chrome.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
