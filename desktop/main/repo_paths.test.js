"use strict";
// Every tracked file must check out on Windows: `git clone` there stops with "invalid path" on a name holding
// < > : " | ? * or a backslash, a reserved device name (CON, NUL, COM1, ...), or a trailing dot / space, and two paths
// that differ only in case overwrite each other. (Four screenshots named "...time-warp?.jpg" once broke the clone.)
const test = require("node:test");
const assert = require("node:assert");
const path = require("path");
const { execFileSync } = require("child_process");

function tracked() {
  try {
    return execFileSync("git", ["ls-files", "-z"], { cwd: path.join(__dirname, "..", ".."), encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] })
      .split("\0").filter(Boolean);
  } catch { return null; }   // not a git checkout (an unpacked source tarball): nothing to check
}

test("every tracked path is a valid Windows path, and no two differ only in case", (t) => {
  const files = tracked();
  if (!files) return t.skip("no git checkout");
  const bad = files.filter((f) => f.split("/").some((seg) =>
    /[<>:"|?*\\\x00-\x1f]/.test(seg) || /[. ]$/.test(seg) || /^(con|prn|aux|nul|com\d|lpt\d)(\.|$)/i.test(seg)));
  assert.deepStrictEqual(bad, [], "rename these: Windows can't check them out");
  const seen = new Map(), clash = [];
  for (const f of files) { const k = f.toLowerCase(); if (seen.has(k)) clash.push(`${seen.get(k)} / ${f}`); else seen.set(k, f); }
  assert.deepStrictEqual(clash, [], "paths that differ only in case collide on Windows");
});
