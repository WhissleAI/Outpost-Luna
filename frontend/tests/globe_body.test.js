// [courses] createGlobe's optional `body` (docs/COURSES.md §4.3, §6 spike): left out, the globe is the Moon exactly as
// before; a course names another map and radius (Earth for Archaeology).
import test from "node:test";
import assert from "node:assert/strict";
import { MOON_BODY, globeBody } from "../src/globe.js";

test("no body is the Moon, unchanged", () => {
  assert.deepEqual(MOON_BODY, { name: "Moon", map: "/media/img/moon4k.jpg", km: 1737.4 });
  assert.equal(globeBody(undefined), MOON_BODY);
  assert.equal(globeBody(null), MOON_BODY);
  assert.equal(globeBody("earth"), MOON_BODY);
  assert.ok(Object.isFrozen(MOON_BODY));
});

test("a course's body: Earth's map and radius", () => {
  assert.deepEqual(globeBody({ name: "Earth", km: 6371, map: "/course/archaeology/earth5400.jpg" }),
    { name: "Earth", km: 6371, map: "/course/archaeology/earth5400.jpg" });
});

test("missing or bad fields fall back to the Moon's", () => {
  assert.deepEqual(globeBody({}), MOON_BODY);
  assert.deepEqual(globeBody({ km: -3, map: "" }), MOON_BODY);
  assert.deepEqual(globeBody({ km: 6371 }), { name: "Globe", map: MOON_BODY.map, km: 6371 });
});
