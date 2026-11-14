// Clip time <-> file time for crew audio. The desktop app ships trimmed crew audio (backend/pipeline/trim_media.py):
// only the stretches that can play, back to back. A clip's segs = [[clip_t0, file_t0, len], ...] (GET /api/clips/<id>)
// map the clip's time, which every timestamp in the data uses, to the file's. No segs (the dev app plays the original
// audio) means the two are the same. Only <audio>.currentTime is in file time.

/** Clip time -> file time. A time in a dropped gap (nothing plays there) maps to the start of the next stretch. */
export function toFileTime(segs, t) {
  if (!segs || !segs.length) return t;
  let k = 0; while (k + 1 < segs.length && segs[k + 1][0] <= t) k++;
  const [c0, f0, len] = segs[k];
  if (t < c0) return f0;                                     // before the first kept stretch
  if (t <= c0 + len || k + 1 === segs.length) return f0 + Math.min(t - c0, len);
  return segs[k + 1][1];
}

/** File time -> clip time. */
export function toClipTime(segs, ft) {
  if (!segs || !segs.length) return ft;
  let k = 0; while (k + 1 < segs.length && segs[k + 1][1] <= ft) k++;
  return segs[k][0] + Math.max(0, ft - segs[k][1]);
}
