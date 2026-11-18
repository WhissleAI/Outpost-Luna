// Haptics (docs/ACCESSIBILITY.md §Haptics): four mission moments, felt as well as seen and heard.
//
//   storm_warning   short    a storm is forecast (the alert strip shows it; CAPCOM says it)
//   storm_hit       long     the storm is here (the alarm, the flash, the takeover card)
//   boulder         bump     the rover reaches the boulder field (the Now card asks: steer left or right?)
//   rover_home      two taps the rover is back at the outpost (CAPCOM's line, the rover pill)
//
// Never alone: every call site already plays a sound or shows something; a haptic is the third channel, never the only
// one. Where it lands: a game controller's rumble (Chromium: gamepad.vibrationActuator.playEffect("dual-rumble"),
// Firefox: hapticActuators[0].pulse) and navigator.vibrate on phones and tablets (laptops have neither: nothing
// happens). Settings: Sound -> "Vibrate for alerts" (a11y.js S.vibrate) turns all of it off; "Less motion" (or the OS
// reduced-motion setting) keeps only the two storm alerts, softer.
// The pure part (plan, vibratePattern, momentOf) is unit-tested (tests/haptics.test.js).
import { loadSettings } from "./a11y.js";

// [ms on, strong motor 0..1, weak motor 0..1, ms off before the next pulse]
export const PATTERNS = Object.freeze({
  storm_warning: [[160, 0.45, 0.35, 0]],
  storm_hit: [[900, 1, 0.8, 0]],
  boulder: [[90, 0.7, 0.25, 70], [60, 0.4, 0.15, 0]],
  rover_home: [[70, 0, 0.55, 90], [70, 0, 0.55, 0]],
});
export const ALERTS = new Set(["storm_warning", "storm_hit"]);
const SOFT = 0.6;          // reduced motion: alerts only, at this share of the magnitude
const AGAIN_MS = 1500;     // the same moment from two paths (the clock step and the session's state) buzzes once

/** The pulses to play for `kind` under the settings, or null (off, unknown kind, decorative under reduced motion). */
export function plan(kind, { vibrate = true, reduced = false } = {}) {
  const p = PATTERNS[kind];
  if (!p || !vibrate) return null;
  if (reduced && !ALERTS.has(kind)) return null;
  return p.map(([ms, s, w, gap]) => ({ ms, strong: reduced ? s * SOFT : s, weak: reduced ? w * SOFT : w, gap }));
}

/** Pulses -> a navigator.vibrate pattern: [on, off, on, ...]. */
export function vibratePattern(pulses) {
  const out = [];
  (pulses || []).forEach((p, i) => { out.push(p.ms); if (p.gap && i < pulses.length - 1) out.push(p.gap); });
  return out;
}

/** Sim events (one clock step or order) -> the one moment to feel, strongest first, or null. A near-miss storm (few
 *  particles reach the Moon, e.sep === false) is felt like a warning, not a hit. */
export function momentOf(evs) {
  const es = evs || [];
  const hit = es.find(e => e && e.kind === "solar_storm");
  if (hit) return hit.sep === false ? "storm_warning" : "storm_hit";
  if (es.some(e => e && e.kind === "storm_warning")) return "storm_warning";
  if (es.some(e => e && e.kind === "task" && e.phase === "ready" && e.step === "steer")) return "boulder";
  if (es.some(e => e && e.kind === "rover_back")) return "rover_home";
  return null;
}

const reducedNow = s => !!(s.reducedMotion || (typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches));

let last = { kind: "", at: -1e9 };

/**
 * Play one moment on every controller that can rumble and on navigator.vibrate. deps are for tests:
 * {settings, reduced, pads, vibrate, now, later}. Returns {pads, vibrate} (what was asked to play), or null.
 */
export function buzz(kind, deps = {}) {
  const st = deps.settings ? deps.settings() : (() => { try { return loadSettings(localStorage); } catch (e) { return { vibrate: true }; } })();
  const reduced = deps.reduced ? deps.reduced() : reducedNow(st);
  const pulses = plan(kind, { vibrate: st.vibrate !== false, reduced });
  if (!pulses) return null;
  const now = deps.now ? deps.now() : Date.now();
  if (last.kind === kind && now - last.at < AGAIN_MS) return null;
  last = { kind, at: now };
  const later = deps.later || ((fn, ms) => setTimeout(fn, ms));
  let pads = [];
  try { pads = [...((deps.pads ? deps.pads() : (typeof navigator !== "undefined" && navigator.getGamepads ? navigator.getGamepads() : [])) || [])].filter(Boolean); } catch (e) { pads = []; }
  let n = 0;
  pads.forEach(pad => {
    const act = pad.vibrationActuator, hap = pad.hapticActuators && pad.hapticActuators[0];
    const one = p => {
      try {
        if (act && typeof act.playEffect === "function") act.playEffect("dual-rumble", { startDelay: 0, duration: p.ms, strongMagnitude: p.strong, weakMagnitude: p.weak }).catch(() => {});
        else if (hap && typeof hap.pulse === "function") hap.pulse(Math.max(p.strong, p.weak), p.ms);
      } catch (e) { /* the controller went away */ }
    };
    if (!(act && typeof act.playEffect === "function") && !(hap && typeof hap.pulse === "function")) return;
    n++;
    // one pulse at a time: a second playEffect preempts the first, so the next starts when this one ends
    let t = 0;
    pulses.forEach(p => { if (t) later(() => one(p), t); else one(p); t += p.ms + (p.gap || 0); });
  });
  const vib = deps.vibrate || (typeof navigator !== "undefined" && typeof navigator.vibrate === "function" ? navigator.vibrate.bind(navigator) : null);
  let v = false;
  if (vib) { try { v = vib(vibratePattern(pulses)) !== false; } catch (e) { v = false; } }
  return { pads: n, vibrate: v };
}

/** Tests: forget the last moment (the de-duplication window). */
export function _reset() { last = { kind: "", at: -1e9 }; }
