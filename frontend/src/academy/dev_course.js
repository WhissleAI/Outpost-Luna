// [courses] Dev / test harness only (docs/COURSES.md P3), until the course platform lands (P1/P2): with the backend
// started as OUTPOST_DEV_COURSE=<id> and the page opened as /?course=<id> on the Vite dev server, the globe draws that
// course's body. A built app (import.meta.env.DEV false) never reads the URL: Moon players see nothing new.
const DEV_BODIES = Object.freeze({
  archaeology: Object.freeze({ name: "Earth", map: "/api/courses/archaeology/media/earth5400.jpg", km: 6371 }),
});
/** The globe body for ?course=<id> on the dev server, else undefined (the Moon). Pure (tested). */
export function devCourseBody(search, dev) {
  if (!dev) return undefined;
  let id = null;
  try { id = new URLSearchParams(search || "").get("course"); } catch (e) { id = null; }
  return (id && Object.prototype.hasOwnProperty.call(DEV_BODIES, id)) ? DEV_BODIES[id] : undefined;
}
