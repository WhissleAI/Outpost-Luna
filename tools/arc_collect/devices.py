"""Audio devices, sample rates, the mic-permission probe, machine facts and disk estimates.

Nothing here identifies a person: device names are scrubbed of an owner's name ("Sam's AirPods" -> "Owner's
AirPods"), and the machine facts are the OS version and the model identifier only (no serial number, host or user name).
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

PREFERRED_RATES = (48000, 44100, 32000, 24000, 16000)
BLUETOOTH_HINTS = ("airpods", "bluetooth", "beats", "buds", "headphone", "headset", "hands-free", "handsfree", "bose",
                   "sony wh", "wh-1000", "jabra", "jbl", "powerbeats", "soundcore", " bt", "(bt", "hfp", "a2dp")
BUILTIN_SPEAKER_HINTS = ("macbook", "built-in", "builtin", "internal", "realtek", "speakers (", "speaker (",
                         "laptop", "conexant", "cirrus", "intel smart sound", "sst")


def scrub_name(name: str) -> str:
    """Drop a person's name from a device name: "Sam's AirPods Pro" / "Alex’s iPhone Microphone" -> "Owner's ..."."""
    s = str(name or "")
    s = re.sub(r"^[^'’()]{1,40}?['’]s\s+", "Owner's ", s)
    return s.strip()


def is_bluetooth(name: str) -> bool:
    n = " " + str(name or "").lower()
    return any(h in n for h in BLUETOOTH_HINTS)


def looks_builtin_speaker(name: str) -> bool:
    n = str(name or "").lower()
    return not is_bluetooth(n) and any(h in n for h in BUILTIN_SPEAKER_HINTS)


def default_devices(sd) -> tuple[dict, dict]:
    return sd.query_devices(kind="input"), sd.query_devices(kind="output")


def pick_device(sd, spec, kind: str) -> dict:
    """`spec`: None (the system default), an index, or a case-insensitive substring of the name."""
    if spec is None or spec == "":
        return sd.query_devices(kind=kind)
    try:
        return sd.query_devices(int(spec))
    except (TypeError, ValueError):
        pass
    want = str(spec).lower()
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    for d in sd.query_devices():
        if want in d["name"].lower() and d[key] > 0:
            return d
    raise SystemExit(f"No {kind} device matches {spec!r}. Run `check` to list them.")


def choose_rate(sd, din: dict, dout: dict, out_channels: int, want: int | None = None) -> tuple[int, list[str]]:
    """One sample rate both devices accept (a duplex stream needs one). Tries the asked rate, 48 kHz, the output's and
    the input's own rates, then the usual ones. Returns (rate, notes)."""
    notes = []
    cands = []
    for r in (want, 48000, int(dout["default_samplerate"]), int(din["default_samplerate"]), *PREFERRED_RATES):
        if r and r not in cands:
            cands.append(int(r))
    for r in cands:
        try:
            sd.check_output_settings(device=dout["index"], channels=out_channels, dtype="float32", samplerate=r)
            sd.check_input_settings(device=din["index"], channels=1, dtype="float32", samplerate=r)
        except Exception as e:  # noqa: BLE001 - PortAudioError, ValueError
            notes.append(f"{r} Hz refused ({str(e)[:60]})")
            continue
        if want and r != want:
            notes.append(f"asked for {want} Hz; the devices run at {r} Hz")
        if int(din["default_samplerate"]) != int(dout["default_samplerate"]):
            notes.append(f"mic default {int(din['default_samplerate'])} Hz, speakers {int(dout['default_samplerate'])} Hz:"
                         f" both opened at {r} Hz (the OS converts)")
        return r, notes
    raise SystemExit("The mic and the speakers share no sample rate. Pick other devices (`check` lists them).")


def device_entry(d: dict, role: str) -> dict:
    return {"role": role, "name": scrub_name(d["name"]), "index": d["index"],
            "default_samplerate": int(d["default_samplerate"]), "bluetooth_guess": is_bluetooth(d["name"]),
            "builtin_speaker_guess": looks_builtin_speaker(d["name"]) if role == "output" else None}


def list_devices(sd) -> list[dict]:
    out = []
    try:
        dflt = list(sd.default.device)
    except Exception:  # noqa: BLE001
        dflt = [None, None]
    for d in sd.query_devices():
        out.append({"index": d["index"], "name": d["name"], "in": d["max_input_channels"],
                    "out": d["max_output_channels"], "rate": int(d["default_samplerate"]),
                    "default_in": d["index"] == dflt[0], "default_out": d["index"] == dflt[1],
                    "bluetooth_guess": is_bluetooth(d["name"])})
    return out


# ---- mic permission ---------------------------------------------------------------------------------------------------
def mic_probe(sd, device=None, seconds: float = 0.25, rate: int | None = None) -> dict:
    """Open the mic for a fraction of a second and read it (discarded, never saved, nothing is played).

    On macOS this read is what makes the OS ask "<your terminal> would like to access the microphone" the first time.
    A denied mic does not raise there: it delivers pure digital zeros, so all-zero samples = permission missing."""
    d = pick_device(sd, device, "input")
    r = int(rate or d["default_samplerate"])
    try:
        with sd.InputStream(device=d["index"], channels=1, samplerate=r, dtype="float32") as s:
            x, _ = s.read(int(seconds * r))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "device": scrub_name(d["name"]), "error": str(e)[:200]}
    x = np.asarray(x, np.float32).ravel()
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    zeros = bool(peak == 0.0)
    rms = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
    return {"ok": not zeros, "device": scrub_name(d["name"]), "all_zero": zeros,
            "rms_dbfs": round(20 * np.log10(rms), 1) if rms > 0 else None}


def permission_help() -> str:
    if sys.platform == "darwin":
        return ("macOS: System Settings > Privacy & Security > Microphone > switch ON the app you run this from "
                "(Terminal, iTerm, or VS Code), then quit and reopen that app.")
    if sys.platform == "win32":
        return ("Windows: Settings > Privacy & security > Microphone > turn on 'Microphone access' and "
                "'Let desktop apps access your microphone'.")
    return "Check the OS's microphone privacy settings."


# ---- machine facts ----------------------------------------------------------------------------------------------------
def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def machine_info(dry_run: bool = False) -> dict:
    """OS + version + the hardware model identifier. Never the serial number, host name or user name."""
    info = {"os": platform.system(), "os_version": platform.release(), "arch": platform.machine(),
            "python": platform.python_version()}
    if sys.platform == "darwin":
        info["os_version"] = platform.mac_ver()[0] or info["os_version"]
        info["model"] = _run(["/usr/sbin/sysctl", "-n", "hw.model"]) or None
        chip = _run(["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"])
        info["chip"] = chip or None
    elif sys.platform == "win32":
        info["os_version"] = platform.version()
        ps = ("$c = Get-CimInstance Win32_ComputerSystem; $c.Manufacturer + ' | ' + $c.Model")
        info["model"] = _run(["powershell", "-NoProfile", "-Command", ps]) or None
    else:
        try:
            info["model"] = Path("/sys/devices/virtual/dmi/id/product_name").read_text().strip()
        except OSError:
            info["model"] = None
    if dry_run:
        info["dry_run"] = True
    return info


def output_volume() -> int | None:
    """The macOS output volume (0-100), read only; never changed. None elsewhere (the person types it)."""
    if sys.platform != "darwin":
        return None
    v = _run(["/usr/bin/osascript", "-e", "output volume of (get volume settings)"])
    try:
        return int(v)
    except ValueError:
        return None


# ---- disk -------------------------------------------------------------------------------------------------------------
def bytes_per_second(rate: int) -> float:
    """Per second of session: mic + reference float32 at `rate`, plus their 16 kHz 16-bit copies."""
    return 2 * rate * 4 + 2 * 16000 * 2


def free_bytes(path: Path) -> int | None:
    p = Path(path).expanduser()
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def human(n: float | None) -> str:
    if n is None:
        return "?"
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u in ("B", "KB") else f"{n:.1f} {u}"
        n /= 1024
    return str(n)


def default_root() -> Path:
    return Path.home() / "Outpost Luna recordings"


def app_user_dir() -> Path | None:
    """The desktop app's per-user folder (Electron userData): its first-run assets live in <it>/assets."""
    if sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / "Outpost Luna"
    elif sys.platform == "win32":
        p = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Outpost Luna"
    else:
        p = Path.home() / ".config" / "Outpost Luna"
    return p if p.exists() else None
