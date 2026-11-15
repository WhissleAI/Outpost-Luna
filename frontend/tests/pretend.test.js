// "Pretend tech" (src/pretend.js): a small mark glued to the label's last word, no dashed box; explained once.
import test from "node:test";
import assert from "node:assert/strict";

globalThis.window = globalThis.window || {};
const P = await import("../src/pretend.js");
const S = await import("../src/story.js");

test("the mark: an icon with the words for screen readers and a tooltip; no box, no visible text", () => {
  const m = P.pretendMark();
  assert.match(m, /class="pt-mark"/);
  assert.match(m, /role="img" aria-label="Pretend tech: Made up for the game\./);
  assert.match(m, /<svg[^>]*class="ic ic-sparkle/);
  assert.doesNotMatch(m.replace(/<[^>]+>/g, ""), /Pretend tech/, "no visible text that could wrap or crowd the label");
});

test("glued to the label's last word, so it never wraps onto a line of its own", () => {
  const h = P.pretendLabel("Shields up");
  assert.match(h, /^Shields <span class="pt-glue">up<span class="pt-mark"/);
  assert.match(P.pretendLabel("Greenhouse"), /^<span class="pt-glue">Greenhouse<span class="pt-mark"/);
  assert.match(P.pretendLabel("A & B"), /A &amp; <span class="pt-glue">B/);
});

test("the explanation: said once, the first time something marked is picked; ≤ 20 words", () => {
  assert.ok(S.PRETEND_EXPLAIN.split(/\s+/).length <= 20);
  assert.match(S.PRETEND_EXPLAIN, /thick walls and water/);
  const said = [], store = new Map(), listeners = [];
  const doc = { addEventListener: (t, f) => listeners.push(f) };
  const realST = globalThis.setTimeout; globalThis.setTimeout = f => f();
  try {
    P.installPretendExplain({ speak: t => said.push(t), store: { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }, doc });
    const btn = marked => ({ querySelector: () => (marked ? {} : null) });
    const click = marked => listeners.forEach(f => f({ target: { closest: () => btn(marked) } }));
    click(false); assert.equal(said.length, 0);
    click(true); click(true);
    assert.deepEqual(said, [S.PRETEND_EXPLAIN]);
    assert.equal(store.get(P.SEEN_KEY), "1");
  } finally { globalThis.setTimeout = realST; }
});
