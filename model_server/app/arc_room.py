"""Arc Transcriber Space v2 room read-outs (nft2/room.onnx) on ONNX Runtime, next to the ear (docs/ARC_V2.md).

libarc does not run room.onnx (arc_transcriber f8bb78d): the ear asks libarc for the encoder's Arc tap of the turn it
just decoded (arc_nft2_tap: the clip decode's memo, no second encoder pass) and this module runs the small room network
on it, the turn's microphone audio and, when the app played something during the turn, the playback reference on the
same clock. A port of arc_audio/room.py (Room.run / Room.summary) at arc_transcriber f8bb78d, frames left out.

Per turn: act (question / command / confirmation / chatter / statement), end_of_turn, playback (share of 80 ms frames
that are the app's own audio), media (other loudspeaker speech), and two BETA read-outs: addressee (device /
other_person / reading_aloud) and safety (15 classes, Arc's thresholds). The BETA ones carry "beta": true and are never
used for an automatic action (docs/ARC_V2.md): kids safety stays with Arc Tagger's kids domain and the phrase
backstops.

Bounded: one intra-op thread, one call at a time (a lock), turns past ROOM_MAX_S are cut to their last ROOM_MAX_S, and
EAR_ROOM=off skips it. Runs on the pip onnxruntime wheel (pinned to the same version as the runtime next to libarc).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import numpy as np

SR = 16000
ROOM_MAX_S = 20.0
STATE: dict = {"room": None, "error": None, "load_s": None, "calls": 0, "ms_total": 0.0}
_lock = threading.Lock()


class Room:
    """One room.onnx session and its config.json `room` section."""

    def __init__(self, path: Path, cfg: dict, threads: int = 1):
        import onnxruntime as ort
        try:   # same as app/nft2.py and libarc: no ONNX Runtime telemetry
            ort.disable_telemetry_events()
        except Exception:  # noqa: BLE001
            pass
        self.cfg = cfg
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, int(threads))
        so.inter_op_num_threads = 1
        so.log_severity_level = 3
        self.sess = ort.InferenceSession(str(Path(path) / cfg.get("file", "room.onnx")), so,
                                         providers=["CPUExecutionProvider"])
        self.frame_s = float(cfg.get("frame_s", 0.08))
        self.frames = list(cfg["frames"])
        self.addr = list(cfg["addressee"]["labels"])
        self.act = list(cfg["act"]["labels"])
        self.safety = list(cfg["safety"]["labels"])
        self.thr = {k: float(v) for k, v in (cfg["safety"].get("thresholds") or {}).items()}
        self.beta = sorted(k for k, v in cfg.items() if isinstance(v, dict) and v.get("beta"))
        self.lock = threading.Lock()

    def run(self, tap: np.ndarray, mic: np.ndarray, ref: np.ndarray | None = None) -> dict:
        """tap (T, d): the Arc tap of `mic` (drop0, 80 ms); mic / ref: float32 16 kHz, ref aligned sample for sample
        (None: nothing played). -> the raw arrays (Room.run)."""
        tap = np.ascontiguousarray(tap, np.float32)
        mic = np.asarray(mic, np.float32).reshape(-1)
        n = max(len(mic), 401)
        m = np.zeros(n, np.float32)
        m[:len(mic)] = mic
        r = np.zeros(n, np.float32)
        on = 0.0
        if ref is not None:
            ref = np.asarray(ref, np.float32).reshape(-1)[:n]
            r[:len(ref)] = ref
            on = 1.0 if np.any(ref) else 0.0
        with self.lock:
            o = self.sess.run(None, {"tap": tap[None], "mic": m[None], "ref": r[None],
                                     "ref_on": np.array([on], np.float32)})
        return {"frames": o[0][0], "addressee": o[1][0], "act": o[2][0], "safety": o[3][0], "ref_on": bool(on)}

    def summary(self, raw: dict) -> dict:
        """The utterance read-out (Room.summary without the frame tracks)."""
        F = raw["frames"]
        T = len(F)
        live = F[:, self.frames.index("live_speech")] >= 0.5 if T else np.zeros(0, bool)
        A = raw["addressee"][live] if live.any() else raw["addressee"]
        la = np.log(np.clip(A, 1e-9, 1.0)).mean(0) if len(A) else np.log(np.full(len(self.addr), 1.0 / len(self.addr)))
        pa = np.exp(la - la.max())
        pa = pa / pa.sum()
        act, su = raw["act"], raw["safety"]
        k = self.frames.index("end_of_turn")
        r4 = lambda v: round(float(v), 4)  # noqa: E731
        return {
            "act": {"label": self.act[int(act.argmax())], "p": r4(act.max()),
                    "probs": {a: r4(p) for a, p in zip(self.act, act)}},
            "addressee": {"label": self.addr[int(pa.argmax())], "p": r4(pa.max()),
                          "probs": {a: r4(p) for a, p in zip(self.addr, pa)}, "beta": True},
            "safety": {"above_threshold": [s for s, p in zip(self.safety, su) if p >= self.thr.get(s, 0.5)],
                       "max_p": r4(su.max()) if len(su) else None, "beta": True},
            "end_of_turn": r4(F[-6:, k].max()) if T else None,
            "playback": r4((F[:, self.frames.index("app_playback")] >= 0.5).mean()) if T else None,
            "playback_max": r4(F[:, self.frames.index("app_playback")].max()) if T else None,
            "media": r4((F[:, self.frames.index("media_playback")] >= 0.5).mean()) if T else None,
            "live_speech": r4(live.mean()) if T else None,
            "reference": raw.get("ref_on", False),
        }


def load(model_dir: Path | str | None, threads: int = 1) -> Room | None:
    """The nft2/ folder's room read-outs, or None (no room section / no room.onnx: an Arc Transcriber Space v1 model).
    Never raises: the reason goes to /health (models.arc_room.error)."""
    t = time.perf_counter()
    STATE.update(room=None, error=None, load_s=None)
    if model_dir is None:
        STATE["error"] = "no model folder"
        return None
    try:
        d = Path(model_dir)
        cfg = json.loads((d / "config.json").read_text(encoding="utf-8")).get("room")
        if not cfg:
            STATE["error"] = "this model has no room read-outs (Arc Transcriber Space v1)"
            return None
        if not (d / cfg.get("file", "room.onnx")).exists():
            STATE["error"] = f"{cfg.get('file', 'room.onnx')} missing"
            return None
        STATE["room"] = Room(d, cfg, threads)
    except Exception as e:  # noqa: BLE001
        STATE["error"] = f"{type(e).__name__}: {e}"[:300]
    STATE["load_s"] = round(time.perf_counter() - t, 3)
    return STATE["room"]


def readout(tap: np.ndarray | None, mic: np.ndarray, ref: np.ndarray | None = None) -> dict | None:
    """One turn's room read-out, or None (no room model, no tap, a failure: never raises)."""
    room = STATE["room"]
    if room is None or tap is None or not len(tap):
        return None
    t = time.perf_counter()
    try:
        mic = np.asarray(mic, np.float32).reshape(-1)
        cut = len(mic) - int(ROOM_MAX_S * SR)
        if cut > 0:   # bounded: the turn's last ROOM_MAX_S (the tap is on the same 80 ms grid)
            k = cut // 1280
            mic, tap = mic[k * 1280:], tap[k:]
            ref = None if ref is None else np.asarray(ref, np.float32).reshape(-1)[k * 1280:]
        out = room.summary(room.run(tap, mic, ref))
    except Exception as e:  # noqa: BLE001
        STATE["error"] = f"{type(e).__name__}: {e}"[:300]
        return None
    ms = (time.perf_counter() - t) * 1000
    with _lock:
        STATE["calls"] += 1
        STATE["ms_total"] += ms
    out["ms"] = round(ms, 1)
    return out


def health() -> dict:
    r = STATE["room"]
    return {"loaded": r is not None, "error": STATE["error"], "load_s": STATE["load_s"],
            "beta": r.beta if r is not None else [], "calls": STATE["calls"],
            "mean_ms": round(STATE["ms_total"] / STATE["calls"], 1) if STATE["calls"] else None,
            "enabled": os.environ.get("EAR_ROOM", "shadow").strip().lower() not in ("off", "0", "false", "no")}
