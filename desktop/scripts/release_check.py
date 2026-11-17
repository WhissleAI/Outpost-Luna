"""Local release gates (issue #91; docs/RELEASING.md). There is no paid CI: a person runs this before every release, on
the Mac (`make release-check DMG=...`) and on the Windows build machine (desktop/scripts/release-check.ps1).

    python3 desktop/scripts/release_check.py [--dmg X.dmg | --exe X-Setup.exe | --app "Outpost Luna.app"|<dir>]
                                             [--gates unit,smoke,golden,fuzz,soak] [--skip ...] [--keep]

Gates (one line each, a JSON report in desktop/dist/release-check.json, exit 1 if any FAILs):
  unit     backend + model_server (pytest), frontend + desktop (node --test)
  smoke    the INSTALLED app: copied out of the dmg into a temp folder (never /Applications) or unpacked from the
           installer (never the registry), signature checked, launched headless and muted on its own data folder and
           ports; engine.json + the model server's ear loaded on the PINNED ONNX Runtime; desktop/scripts/smoke.py;
           a real voice turn (crew clip -> /ws/listen -> "Orientale" heard and linked); clean quit (engine.json gone)
  video    the installed app plays a NASA file (hammer_feather) in its own player and a YouTube video (far_side_view)
           muted, read from the page over DevTools; a YouTube refusal must fall back to the NASA file cleanly (warn),
           never hang; YouTube is skipped offline. VIDEO_SWEEP=1: every catalog entry
  golden   40 fixed clips (desktop/tests/golden) through the installed app's ear: WER / name / link / number rates
           within tolerance of baseline.json, p50 / p95 latency within budget (a different machine: warn only)
  fuzz     (a) libarc's C API under ASan + UBSan (desktop/tests/fuzz/fuzz_libarc.c, debug build), (b) random and
           malformed WebSocket frames at /ws/listen and /v1/stream: no crash, health stays ok, no leaked ear slots
  soak     only with SOAK=1 (or --gates soak): looped clips through the ear for SOAK_MINUTES (10); fails on an RSS leak
           trend, latency drift, a child restart or a watchdog reset

Env: FUZZ_SECONDS (120 each), VIDEO_SWEEP=1, SOAK=1, SOAK_MINUTES (10), RC_ASSETS_SEED (the folder the test app's models come from).
Stdlib only, Python 3.9+: on Windows it runs under the installed app's own Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import shutil
import signal
import socket
import statistics
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rc_ws import OP_BIN, OP_CLOSE, OP_CONT, OP_PING, OP_TEXT, WS, Closed, HandshakeError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "desktop/tests/golden"
FIX = ROOT / "backend/tests/fixtures"
IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
FRAME = 2560                     # 80 ms of PCM16 at 16 kHz
OWNER_PORTS = {47310, 47311, 47312, 47210, 47211, 47212}   # the installed app's defaults: never used by a test run
ALL_GATES = ["unit", "smoke", "video", "golden", "fuzz", "soak"]


# ----------------------------------------------------------------------------------------------------------- report
class Report:
    def __init__(self, path: Path):
        self.path, self.gates, self.t0 = path, [], time.time()
        self.meta = {}

    def add(self, name, status, summary, seconds=None, **details):
        g = {"gate": name, "status": status, "summary": summary, "seconds": round(seconds or 0, 1), **details}
        self.gates.append(g)
        print(f"{status.upper():4} {name:<16} {summary}" + (f"  ({g['seconds']:.0f} s)" if seconds else ""), flush=True)
        self.write()
        return g

    def failed(self):
        return [g for g in self.gates if g["status"] == "fail"]

    def write(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        out = {**self.meta, "result": "fail" if self.failed() else "pass",
               "seconds": round(time.time() - self.t0, 1), "gates": self.gates}
        self.path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def log(*a):
    print("  -   ", *a, flush=True)


def run(cmd, cwd=None, env=None, timeout=None, capture=True):
    p = subprocess.run(cmd, cwd=cwd, env=env, timeout=timeout, text=True, encoding="utf-8", errors="replace",
                       stdout=subprocess.PIPE if capture else None, stderr=subprocess.STDOUT if capture else None)
    return p.returncode, (p.stdout or "")


def machine() -> dict:
    """A stable, non-identifying id for this machine (hash of the hardware UUID / MachineGuid) + a description."""
    raw, desc = "", platform.machine()
    try:
        if IS_MAC:
            out = run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])[1]
            m = re.search(r'"IOPlatformUUID" = "([^"]+)"', out)
            raw = m.group(1) if m else ""
            desc = f"{run(['sysctl', '-n', 'hw.model'])[1].strip()} {run(['sysctl', '-n', 'machdep.cpu.brand_string'])[1].strip()}"
        elif IS_WIN:
            out = run(["reg", "query", r"HKLM\SOFTWARE\Microsoft\Cryptography", "/v", "MachineGuid"])[1]
            m = re.search(r"MachineGuid\s+REG_SZ\s+(\S+)", out)
            raw = m.group(1) if m else ""
            desc = f"{platform.processor()} {os.cpu_count()} threads"
        else:
            raw = Path("/etc/machine-id").read_text().strip()
            desc = platform.processor() or platform.machine()
    except (OSError, IndexError):
        pass
    return {"id": hashlib.sha256((raw or socket.gethostname()).encode()).hexdigest()[:12], "desc": desc.strip(),
            "os": f"{platform.system()} {platform.release()}", "cpus": os.cpu_count()}


def http_json(url, timeout=5.0, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def free_port(avoid=()) -> int:
    for _ in range(50):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]
        s.close()
        if p not in OWNER_PORTS and p not in avoid:
            return p
    raise RuntimeError("no free port")


def pctl(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


# ------------------------------------------------------------------------------------------------------------ unit
def gate_unit(rep: Report):
    uv = shutil.which("uv")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    suites = [
        ("unit:backend", [uv, "run", "pytest", "-q", "-p", "no:cacheprovider"], ROOT / "backend", uv),
        ("unit:model_server", [uv, "run", "pytest", "-q", "-p", "no:cacheprovider"], ROOT / "model_server", uv),
        ("unit:frontend", [npm, "test"], ROOT / "frontend", npm),
        ("unit:desktop", [npm, "test"], ROOT / "desktop", npm),
    ]
    for name, cmd, cwd, tool in suites:
        t = time.time()
        if not tool:
            rep.add(name, "fail", f"{cmd[0] or 'uv/npm'} not found on PATH")
            continue
        if name == "unit:frontend" and not (cwd / "node_modules").exists():
            log("frontend/node_modules missing: npm ci --ignore-scripts")
            run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=cwd, timeout=900)
        try:
            rc, out = run(cmd, cwd=cwd, timeout=1800)
        except subprocess.TimeoutExpired:
            rep.add(name, "fail", "timed out after 30 min", time.time() - t)
            continue
        if "pytest" in cmd:
            m = re.findall(r"^=*\s*(\d+ (?:passed|failed).*?)(?: in [\d.]+s.*)?=*$", out, re.M)
            summ = m[-1].strip() if m else out.strip().splitlines()[-1:] or ["?"]
        else:
            cnt = dict(re.findall(r"^\S+ (tests|pass|fail|skipped) (\d+)$", out, re.M))
            summ = f"{cnt.get('pass', '?')}/{cnt.get('tests', '?')} pass, {cnt.get('fail', '?')} fail"
        summ = summ if isinstance(summ, str) else summ[0]
        fails = re.findall(r"^(FAILED \S+|ERROR \S+|✖ \S+.*)$", out, re.M)[:8]
        rep.add(name, "pass" if rc == 0 else "fail", summ, time.time() - t, failures=fails,
                **({"tail": out.strip().splitlines()[-25:]} if rc else {}))


# ---------------------------------------------------------------------------------------------- the installed app
class App:
    """One installed copy of the app in a temp folder, launched headless on its own data folder and ports."""

    def __init__(self, work: Path, artifact: Path | None, app: Path | None, seed: Path | None):
        self.work, self.artifact, self.app_arg, self.seed = work, artifact, app, seed
        self.ud = work / "userdata"
        self.proc = None
        self.engine = {}
        self.exe = self.res = None
        self.log_path = work / "app.log"
        self.health = {}

    # ---- install ----
    def install(self) -> dict:
        info = {}
        if self.app_arg:
            target = self.app_arg
            info["installed_from"] = str(target)
        elif IS_MAC:
            mnt = self.work / "mnt"
            mnt.mkdir()
            rc, out = run(["hdiutil", "attach", "-nobrowse", "-readonly", "-noautoopen", "-mountpoint", str(mnt),
                           str(self.artifact)], timeout=300)
            if rc:
                raise GateError(f"hdiutil attach failed: {out.strip()[-200:]}")
            try:
                apps = list(mnt.glob("*.app"))
                if not apps:
                    raise GateError("no .app in the dmg")
                target = self.work / "install" / apps[0].name
                target.parent.mkdir()
                rc, out = run(["ditto", str(apps[0]), str(target)], timeout=600)
                if rc:
                    raise GateError(f"ditto failed: {out[-200:]}")
            finally:
                run(["hdiutil", "detach", str(mnt), "-force"], timeout=120)
            info["installed_from"] = f"{self.artifact.name} -> {target}"
        elif IS_WIN:
            target = self._win_unpack()
            info["installed_from"] = f"{self.artifact.name} -> {target}"
        else:
            raise GateError("installed-app gates run on macOS and Windows")
        if IS_MAC:
            if target.suffix != ".app":
                raise GateError(f"not a .app: {target}")
            self.exe = next((target / "Contents/MacOS").iterdir())
            self.res = target / "Contents/Resources"
            rc, out = run(["codesign", "--verify", "--strict", "--deep", str(target)], timeout=600)
            info["codesign"] = "ok" if rc == 0 else out.strip()[-300:]
            rc2, out2 = run(["spctl", "-a", "-vv", "-t", "exec", str(target)], timeout=300)
            info["spctl"] = out2.strip().replace(str(target) + ": ", "")
            info["signed_ok"] = rc == 0 and rc2 == 0
        else:
            self.exe = target / "Outpost Luna.exe"
            self.res = target / "resources"
            ps = ["powershell", "-NoProfile", "-Command",
                  f"(Get-AuthenticodeSignature -LiteralPath '{self.exe}').Status"]
            info["authenticode"] = run(ps, timeout=120)[1].strip() if shutil.which("powershell") else "unknown"
            info["signed_ok"] = None    # unsigned by design (electron-builder.yml); reported, not gated
        if not self.exe.exists():
            raise GateError(f"app executable missing: {self.exe}")
        self.version = "?"
        if IS_MAC:
            import plistlib
            with open(target / "Contents/Info.plist", "rb") as f:
                self.version = plistlib.load(f).get("CFBundleShortVersionString", "?")
        return info

    def _win_unpack(self) -> Path:
        """NSIS installer -> its app-64.7z -> a folder. Never runs the installer (no registry, no Start menu, the
        owner's installed copy and its uninstall entry stay as they are)."""
        z = os.environ.get("SEVEN_ZIP") or shutil.which("7z") or shutil.which("7za")
        for c in [r"C:\Program Files\7-Zip\7z.exe", str(ROOT / "desktop/node_modules/7zip-bin/win/x64/7za.exe")]:
            if not z and Path(c).exists():
                z = c
        if not z:
            raise GateError("7-Zip not found (install 7-Zip or set SEVEN_ZIP): needed to unpack the installer "
                            "without running it")
        nsis = self.work / "nsis"
        rc, out = run([z, "x", "-y", f"-o{nsis}", str(self.artifact)], timeout=900)
        pk = next(iter(nsis.rglob("app-64.7z")), None)
        if rc or not pk:
            raise GateError(f"could not unpack the installer: {out.strip()[-200:]}")
        target = self.work / "install"
        rc, out = run([z, "x", "-y", f"-o{target}", str(pk)], timeout=900)
        shutil.rmtree(nsis, ignore_errors=True)
        if rc:
            raise GateError(f"could not unpack app-64.7z: {out.strip()[-200:]}")
        return target

    # ---- data folder: models from the seed, as copy-on-write clones (macOS) or hard links (Windows) ----
    def seed_assets(self) -> str:
        dst = self.ud / "assets"
        dst.mkdir(parents=True)
        if not self.seed or not (self.seed / "state.json").exists():
            return "none (the app downloads its models on first run)"
        man = json.loads((self.res / "assets.manifest.json").read_text(encoding="utf-8"))
        ids = [a["id"] for a in man["assets"] if (self.seed / a["id"]).is_dir()]
        for i in ids:
            if IS_MAC:
                rc, out = run(["cp", "-c", "-R", str(self.seed / i), str(dst / i)], timeout=600)
                if rc:   # another volume: plain copy
                    shutil.copytree(self.seed / i, dst / i)
            else:
                shutil.copytree(self.seed / i, dst / i, copy_function=_link_or_copy)
        shutil.copy2(self.seed / "state.json", dst / "state.json")
        return f"{', '.join(ids)} from {self.seed} ({'clones' if IS_MAC else 'hard links'}; the seed is never written)"

    # ---- run ----
    def supports_headless(self) -> bool:
        """OUTPOST_HEADLESS (no window, no Dock icon) and engine.json came in 0.3.6. An older build would open a window
        and take focus, so it is never launched: legacy_ear() runs its model server alone instead."""
        try:
            return b"OUTPOST_HEADLESS" in (self.res / "app.asar").read_bytes()
        except OSError:
            return False

    def legacy_ear(self, timeout=120.0) -> dict:
        """The installed bundle's own model server (its Python, launch.py, libarc + pinned ONNX Runtime), started the
        way main.js starts it, with no Electron and no window. -> the ear's /health block."""
        man = json.loads((self.res / "assets.manifest.json").read_text(encoding="utf-8"))
        a = self.ud / "assets"
        env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR", "SYSTEMROOT", "TEMP", "USERPROFILE", "APPDATA")
               if k in os.environ}
        for x in man["assets"]:
            if x.get("env"):
                env[x["env"]] = str(a / x["id"] / x["subdir"]) if x.get("subdir") else str(a / x["id"])
        nat = self.res / "native"
        lib = {"darwin": ("libarctag.dylib", "libarc.dylib"), "win32": ("arctag.dll", "arc.dll")}.get(
            sys.platform, ("libarctag.so", "libarc.so"))
        env.update({"ARCTAG_LIB": str(nat / lib[0]), "ARC_LIB": str(nat / lib[1]), "HF_HOME": str(self.ud / "hf"),
                    "MOON_PARENT_PID": str(os.getpid()), "PYTHONNOUSERSITE": "1", "PYTHONUNBUFFERED": "1",
                    "PYTHONUTF8": "1", "HF_HUB_OFFLINE": "1", "OS_TTS": "off"})
        port = free_port()
        py = self.res / ("python/python.exe" if IS_WIN else "python/bin/python3")
        out = open(self.work / "legacy_models.log", "ab")
        kw = {"creationflags": 0x08000000} if IS_WIN else {"start_new_session": True}
        self.proc = subprocess.Popen([str(py), str(self.res / "app/launch.py"), "models", "--port", str(port)],
                                     cwd=str(self.res / "app"), env=env, stdout=out, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, **kw)
        out.close()
        deadline, h = time.time() + timeout, {}
        try:
            while time.time() < deadline and self.proc.poll() is None:
                try:
                    h = http_json(f"http://127.0.0.1:{port}/health")
                    if h.get("ok"):
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(1)
        finally:
            self.kill()
            self.proc = None
        m = h.get("models", {})
        return {"ear": m.get("arc_ear"), "error": (m.get("arc_meta") or {}).get("error"), "up": bool(h)}

    def launch(self):
        self.ports = {"backend": free_port(), "models": 0}
        self.ports["models"] = free_port({self.ports["backend"]})
        self.ports["devtools"] = free_port({self.ports["backend"], self.ports["models"]})   # the video gate drives the page
        env = {**os.environ, "OUTPOST_HEADLESS": "1", "OUTPOST_MUTE_AUDIO": "1", "OUTPOST_USER_DATA": str(self.ud),
               "OUTPOST_BACKEND_PORT": str(self.ports["backend"]), "OUTPOST_MODELS_PORT": str(self.ports["models"]),
               # no asset update checks or downloads from a test run
               "OUTPOST_ASSETS_MANIFEST_URL": "http://127.0.0.1:9/release-check-no-updates.json"}
        for k in ("LUNA_TOKEN", "DEEPGRAM_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "ELECTRON_RUN_AS_NODE"):
            env.pop(k, None)
        out = open(self.log_path, "ab")
        kw = {"creationflags": 0x08000000} if IS_WIN else {"start_new_session": True}   # CREATE_NO_WINDOW
        self.t_launch = time.time()
        self.proc = subprocess.Popen([str(self.exe), "--mute-audio", f"--remote-debugging-port={self.ports['devtools']}"], cwd=str(self.work), env=env, stdout=out,
                                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        out.close()

    @property
    def engine_file(self) -> Path:
        return self.ud / "engine.json"

    def wait_ready(self, timeout=300.0) -> dict:
        """engine.json, then the model server's /health with the ear loaded (or a reason it is not)."""
        deadline = self.t_launch + timeout
        while not self.engine_file.exists():
            if self.proc.poll() is not None:
                raise GateError(f"the app exited (code {self.proc.returncode}) before writing engine.json; "
                                f"{self.tail_log()}")
            if time.time() > deadline:
                raise GateError(f"no engine.json after {timeout:.0f} s; {self.tail_log()}")
            time.sleep(0.5)
        self.engine = json.loads(self.engine_file.read_text(encoding="utf-8"))
        if self.version == "?":
            self.version = self.engine.get("version", "?")
        self.t_engine = time.time() - self.t_launch
        t_tagger = None
        while time.time() < deadline:
            try:
                h = http_json(self.engine["model_server"] + "/health")
            except (OSError, ValueError):
                h = {}
            self.health = h
            ear = h.get("models", {}).get("arc_ear", {})
            if ear.get("available"):
                self.t_ready = time.time() - self.t_launch
                return h
            if h.get("ok"):                       # the model server is up; the ear has 30 s more to come up
                t_tagger = t_tagger or time.time()
                if time.time() - t_tagger > 30:
                    break
            time.sleep(1)
        meta = self.health.get("models", {}).get("arc_meta", {})
        raise GateError(f"the ear never loaded: {meta.get('error') or 'model server not healthy'}")

    def headers(self):
        return {"X-Luna-Token": self.engine.get("token", "")}

    def model_health(self, timeout=5.0):
        return http_json(self.engine["model_server"] + "/health", timeout)

    def backend_health(self, timeout=5.0):
        return http_json(self.engine["backend"] + "/api/health", timeout, self.headers())

    def children(self):
        try:
            return json.loads((self.ud / "children.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def main_log(self) -> str:
        try:
            return (self.ud / "logs/main.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

    def child_exits(self) -> list[str]:
        return [ln for ln in self.main_log().splitlines() if " exited code=" in ln and "SIGTERM" not in ln]

    def tail_log(self, n=6) -> str:
        lines = self.main_log().strip().splitlines()[-n:]
        return "main.log: " + " | ".join(ln[27:] for ln in lines) if lines else "(no main.log)"

    def quit(self, timeout=30.0) -> dict:
        """Ask the app to quit the way the OS does (SIGTERM / WM_CLOSE), then check it cleaned up."""
        if not self.proc or self.proc.poll() is not None:
            return {"clean": False, "why": "not running"}
        kids = [c.get("pid") if isinstance(c, dict) else c for c in self.children()]
        t = time.time()
        if IS_WIN:
            run(["taskkill", "/PID", str(self.proc.pid)], timeout=30)
        else:
            self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout)
            forced = False
        except subprocess.TimeoutExpired:
            forced = True
            self.kill()
        time.sleep(0.5)
        alive = [p for p in kids if p and _pid_alive(p)]
        for p in alive:
            _kill_pid(p)
        res = {"seconds": round(time.time() - t, 1), "forced": forced, "engine_json_removed": not self.engine_file.exists(),
               "children_left": alive, "children_json": self.children()}
        res["clean"] = not forced and res["engine_json_removed"] and not alive and not res["children_json"]
        return res

    def kill(self):
        if self.proc and self.proc.poll() is None:
            if IS_WIN:
                run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], timeout=30)
            else:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except OSError:
                    self.proc.kill()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                pass
        for c in self.children():
            p = c.get("pid") if isinstance(c, dict) else c
            if p and _pid_alive(p):
                _kill_pid(p)


class GateError(Exception):
    pass


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _pid_alive(pid: int) -> bool:
    if IS_WIN:
        out = run(["tasklist", "/FI", f"PID eq {pid}", "/NH"])[1]
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill_pid(pid: int):
    if IS_WIN:
        run(["taskkill", "/PID", str(pid), "/T", "/F"])
    else:
        for f in (lambda: os.killpg(pid, signal.SIGKILL), lambda: os.kill(pid, signal.SIGKILL)):
            try:
                f()
                return
            except OSError:
                pass


def rss_mb(pid: int) -> float | None:
    try:
        if IS_WIN:
            out = run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])[1]
            m = re.search(r'"([\d.,\s]+) K"', out)
            return round(int(re.sub(r"\D", "", m.group(1))) / 1024, 1) if m else None
        out = run(["ps", "-o", "rss=", "-p", str(pid)])[1].strip()
        return round(int(out) / 1024, 1) if out else None
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------ a voice session
def read_wav(p: Path) -> bytes:
    with wave.open(str(p)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2, p
        return w.readframes(w.getnframes())


def voice_turn(app: App, pcm: bytes, speech_end_s: float | None = None, names=None, tail_s=1.5, pace=1.0,
               ws_path="/ws/listen") -> dict:
    """Stream one clip at real-time pace through /ws/listen (the page's path) and collect what comes back.
    latency_ms: from the moment the audio at speech end was sent to the first final words after it."""
    url = app.engine["backend"].replace("http", "ws", 1) + ws_path
    ws = WS.connect(url, headers=app.headers(), timeout=15)
    msgs, finals = [], []
    t_end = t_final = t_turn_end = None
    end_at = int((speech_end_s if speech_end_s is not None else len(pcm) / 32000) * 32000)
    audio = pcm + bytes(int(tail_s * 32000))
    try:
        if names:
            ws.send_text(json.dumps({"t": "context", "names": names}))
        t0 = time.perf_counter()
        for k, i in enumerate(range(0, len(audio), FRAME)):
            ws.send_binary(audio[i:i + FRAME])
            if t_end is None and i + FRAME >= end_at:
                t_end = time.perf_counter()
            # drain what has arrived, then wait for this frame's slot (real-time pace)
            while True:
                left = t0 + (k + 1) * 0.08 / pace - time.perf_counter()
                try:
                    m = ws.recv(timeout=max(left, 0.0005))
                except TimeoutError:
                    break
                _take(m, msgs, finals)
                if finals and t_end and t_final is None and finals[-1][1] >= t_end:
                    t_final = finals[-1][1]
                if msgs and msgs[-1].get("t") == "turn" and msgs[-1].get("state") == "end" and t_turn_end is None:
                    t_turn_end = time.perf_counter()
                if left <= 0:
                    break
        ws.send_text(json.dumps({"t": "stop"}))
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                m = ws.recv(timeout=deadline - time.time())
            except (TimeoutError, Closed):
                break
            _take(m, msgs, finals)
            if finals and t_end and t_final is None:
                t_final = finals[-1][1]
    finally:
        ws.close()
    texts = [f[0]["text"] for f in finals]
    names_out = [n for f in finals for n in (f[0].get("names") or [])]
    return {"text": " ".join(texts).strip(), "finals": texts, "names": names_out,
            "latency_ms": round((t_final - t_end) * 1000) if t_final and t_end else None,
            "turn_end_ms": round((t_turn_end - t_end) * 1000) if t_turn_end and t_end else None,
            "ear": next((m for m in msgs if m.get("t") == "ear"), {}),
            "errors": [m for m in msgs if m.get("t") == "error"]}


def _take(m, msgs, finals):
    if isinstance(m, bytes):
        return
    try:
        d = json.loads(m)
    except ValueError:
        return
    msgs.append(d)
    if d.get("t") == "words" and d.get("final"):
        finals.append((d, time.perf_counter()))


ORIENTALE = [{"name": "Orientale Basin", "kind": "lunar_feature", "aliases": ["Orientale", "Mare Orientale"]}]


def orientale_turn(app: App) -> tuple[bool, str, dict]:
    """The dead-ear check: Reid Wiseman (Artemis II) "...take out Orientale..." -> heard, and linked to the list."""
    pcm = (FIX / "crew_orientale_16k.s16le").read_bytes()
    r = voice_turn(app, pcm, names=ORIENTALE, tail_s=2.0)
    linked = [n for n in r["names"] if n.get("state") == "linked" and "Orientale" in (n.get("entity") or "")]
    ok = r["ear"].get("ear") == "arc" and "orientale" in r["text"].lower() and bool(linked) and not r["errors"]
    why = (f"ear {r['ear'].get('ear') or r['ear']}; heard {r['text']!r}; linked "
           f"{[n.get('entity') for n in linked] or 'nothing'}; latency {r['latency_ms']} ms")
    return ok, why, r


# ----------------------------------------------------------------------------------------------------------- smoke
def gate_smoke(rep: Report, app: App, info: dict, t0: float):
    h = app.health.get("models", {}).get("arc_ear", {})
    eng = h.get("engine") or {}
    checks = {
        "signature": info.get("signed_ok") is not False,
        "engine.json": bool(app.engine.get("token")) and app.engine.get("version") == app.version,
        "ear available": bool(h.get("available")),
        "ort pinned": eng.get("ort_source") == "pinned",
        "model sha256 verified": (eng.get("verify") or {}).get("verified") is True,
    }
    py = app.res / ("python/python.exe" if IS_WIN else "python/bin/python3")
    env = {**os.environ, "PYTHONPATH": str(app.res / "site/backend"), "PYTHONUTF8": "1"}
    env.pop("LUNA_TOKEN", None)
    rc, out = run([str(py), "-u", str(ROOT / "desktop/scripts/smoke.py"), "--engine",
                   str(app.engine_file)], env=env, timeout=600)
    checks["smoke.py"] = rc == 0 and "FAIL" not in out
    ok, why, _ = orientale_turn(app)
    checks["voice turn (Orientale linked)"] = ok
    status = "pass" if all(checks.values()) else "fail"
    bad = [k for k, v in checks.items() if not v]
    summ = (f"{app.version}: ear on {eng.get('backend')} ({eng.get('ort_source')}), ready in {app.t_ready:.1f} s; "
            f"smoke.py {'ok' if checks['smoke.py'] else 'FAILED'}; {why}" if status == "pass"
            else f"{app.version}: FAILED {', '.join(bad)}; {why}")
    return rep.add("smoke", status, summ, time.time() - t0, checks=checks, install=info, engine=eng,
                   ready_s=round(app.t_ready, 1), smoke_py=out.strip().splitlines()[-40:])


# ----------------------------------------------------------------------------------------------------------- video
class CDP:
    """The installed app's page over the DevTools protocol (--remote-debugging-port on the TEST app only)."""

    def __init__(self, port: int, origin: str, timeout=60.0):
        deadline, page = time.time() + timeout, None
        while time.time() < deadline and not page:
            try:
                ts = http_json(f"http://127.0.0.1:{port}/json", timeout=3)
                page = next((t for t in ts if t.get("type") == "page" and t.get("url", "").startswith(origin)), None)
            except (OSError, ValueError):
                pass
            if not page:
                time.sleep(1)
        if not page:
            raise GateError(f"no app page on the DevTools port {port}")
        self.ws, self.n = WS.connect(page["webSocketDebuggerUrl"], timeout=10), 0

    def eval(self, expr: str, timeout=90.0):
        self.n += 1
        self.ws.send_text(json.dumps({"id": self.n, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "awaitPromise": True, "returnByValue": True}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            m = json.loads(self.ws.recv(timeout=max(1.0, deadline - time.time())))
            if m.get("id") == self.n:
                r = m.get("result", {})
                if r.get("exceptionDetails"):
                    raise GateError("page error: " + json.dumps(r["exceptionDetails"])[:300])
                return r.get("result", {}).get("value")
        raise GateError(f"page did not answer in {timeout:.0f} s")

    def close(self):
        try:
            self.ws.close()
        except OSError:
            pass


# One video in the installed app's own overlay, muted: did it really play (time moving), or show which card?
# -> {id, kind, result: played|fell_back|card|stuck|unavailable, ...}. A YouTube video that shows "won't play here"
# also has its NASA fallback button pressed, and that file must play.
VIDEO_JS = r"""(async (id, waitS) => {
  const O = window.__outpost; O.muteVideos = true;
  const V = O.video, sleep = ms => new Promise(r => setTimeout(r, ms));
  const v = (await V.catalog()).find(x => x.id === id);
  if (!v) return { id, result: "missing" };
  const avail = await V.isAvailable(id);
  if (avail === "offline") return { id, kind: v.source, result: "unavailable", avail };
  if (V.isOpen()) V.command("stop");
  const done = V.openVideo(id, { context: "release-check" });
  const t0 = Date.now(); let out = null, fbT0 = 0;
  while (!out && Date.now() - t0 < waitS * 1000) {
    await sleep(500);
    const d = document.getElementById("vidDlg"); if (!d) continue;
    const el = d.querySelector("video");
    if (el && el.currentTime > 1.5 && !el.paused) out = { result: fbT0 ? "fell_back" : "played", t: +el.currentTime.toFixed(1), file: el.currentSrc.replace(location.origin, "") };
    else if (d.dataset.ytstate === "1") out = { result: "played", ytstate: 1 };
    else if (d.dataset.card && !fbT0) {
      const b = d.querySelector("[data-fb]");
      if (b && v.source === "youtube") { fbT0 = Date.now(); b.click(); }
      else out = { result: "card", card: d.dataset.card, yterror: d.dataset.yterror || null };
    }
  }
  const d = document.getElementById("vidDlg");
  if (!out) out = { result: "stuck", ytstate: d && d.dataset.ytstate, card: d && d.dataset.card };
  out.yterror = out.yterror || (d && d.dataset.yterror) || null;
  out.seconds_to_result = +((Date.now() - t0) / 1000).toFixed(1);
  V.command("stop"); const r = await done;
  return { id, kind: v.source, avail, ...out, closed: !V.isOpen(), how: r && (r.fallback ? "fallback:" + r.fallback : r.failed ? "failed" : "ok") };
})"""


# The phases lesson opens with its Try-at-home "Watch how" videos (the Oreo one) on its first step, while online.
WATCH_HOW_JS = r"""(async () => {
  const O = window.__outpost, sleep = ms => new Promise(r => setTimeout(r, ms));
  if ((await O.video.isAvailable("diy_oreo_phases")) === "offline") return { result: "unavailable" };
  document.getElementById("modeAcademy").click();
  for (let i = 0; i < 20 && document.body.dataset.mode !== "academy"; i++) await sleep(250);
  await sleep(1500);
  O.shellNav("lesson", "phases");
  for (let i = 0; i < 30; i++) {
    await sleep(500);
    const b = document.getElementById("aPrepVideos");
    if (b && !b.hidden && b.querySelector("[data-v]")) return { result: "shown", ids: [...b.querySelectorAll("[data-v]")].map(x => x.dataset.v) };
  }
  return { result: "missing", panel: !!document.querySelector("#aPanel .a-prompt") };
})()"""


def play_video(cdp: CDP, vid: str, wait_s=45) -> dict:
    return cdp.eval(f"{VIDEO_JS}({json.dumps(vid)}, {wait_s})", timeout=wait_s + 60) or {"id": vid, "result": "?"}


def gate_video(rep: Report, app: App, sweep=False):
    """The installed app plays a NASA file in its own player, and a YouTube video (or, when YouTube refuses, falls back
    to the NASA file cleanly, never stuck). Offline-safe: YouTube is skipped when the app says it is offline.
    VIDEO_SWEEP=1: every catalog entry."""
    t0 = time.time()
    cdp = None
    try:
        cdp = CDP(app.ports["devtools"], f"http://127.0.0.1:{app.ports['backend']}")
        ok = cdp.eval("(async () => { for (let i = 0; i < 120; i++) { if (window.__outpost && window.__outpost.video) "
                      "return true; await new Promise(r => setTimeout(r, 500)); } return false; })()")
        if not ok:
            raise GateError("the page never set up its video player (window.__outpost.video)")
        ids = ["hammer_feather", "far_side_view"]
        if sweep:
            ids = [v["id"] for v in cdp.eval("(async () => (await window.__outpost.video.catalog()).map(v => ({id: v.id})))()")]
        res = [play_video(cdp, i) for i in ids]
        how = cdp.eval(WATCH_HOW_JS, timeout=60) or {"result": "?"}
    except (GateError, OSError, Closed, TimeoutError) as e:
        return rep.add("video", "fail", f"could not drive the page: {e}", time.time() - t0)
    finally:
        if cdp:
            cdp.close()
    bad, warn, lines = [], [], []
    for r in res:
        k, out = r.get("kind"), r.get("result")
        lines.append(f"{r['id']}={out}" + (f"({r.get('yterror')})" if r.get("yterror") else ""))
        if k == "nasa_file" and out != "played":
            bad.append(r["id"])
        elif k == "youtube" and (out == "fell_back" or (out == "card" and r.get("card") == "error")):
            warn.append(r["id"])   # YouTube refused; the kid got "won't play here" (+ the NASA file when there is one)
        elif k == "youtube" and out not in ("played", "unavailable"):
            bad.append(r["id"])
        elif not k:
            bad.append(r["id"])
    lines.append(f"phases lesson Watch how={how.get('result')}" + (f"({','.join(how['ids'])})" if how.get("ids") else ""))
    if how.get("result") not in ("shown", "unavailable") or (how.get("ids") and "diy_oreo_phases" not in how["ids"]):
        bad.append("watch-how")
    status = "fail" if bad else "warn" if warn else "pass"
    summ = ("; ".join(lines) + (f"; FAILED {', '.join(bad)}" if bad else "")
            + (f"; YouTube refused {', '.join(warn)} (clean 'won't play here' card / NASA fallback)" if warn else ""))
    return rep.add("video", status, summ, time.time() - t0, results=res, watch_how=how)


# ---------------------------------------------------------------------------------------------------------- golden
def golden_run(app: App) -> dict:
    sys.path.insert(0, str(FIX / "ear_eval"))
    from score import edits, has, norm  # noqa: E402
    spec = json.loads((GOLDEN / "set.json").read_text(encoding="utf-8"))
    names_ctx = json.loads((FIX / "ear_eval/tier_a.json").read_text(encoding="utf-8"))   # what the backend sends
    rows = []
    for c in spec["clips"]:
        pcm = read_wav(GOLDEN / "audio" / f"{c['clip']}.wav")
        r = voice_turn(app, pcm, c["speech_end_s"], names=[{"name": n} for n in names_ctx], tail_s=1.0)
        hyp, ref = norm(r["text"]), norm(c["text"])
        linked = {(n.get("entity") or "").lower() for n in r["names"] if n.get("state") == "linked"}
        rows.append({"clip": c["clip"], "ref": c["text"], "hyp": r["text"], "err": edits(ref, hyp), "n": len(ref),
                     "names": [has(hyp, n) for n in c["names"]],
                     "linked": [any(n.lower() in e or e in n.lower() for e in linked if e) for n in c["names"]],
                     "numbers": [str(x) in hyp for x in c["numbers"]], "noisy": c["noisy"],
                     "latency_ms": r["latency_ms"], "turn_end_ms": r["turn_end_ms"], "errors": r["errors"]})

    def rate(key):
        xs = [x for r in rows for x in r[key]]
        return round(sum(xs) / max(len(xs), 1), 3), f"{sum(xs)}/{len(xs)}"
    lat = [r["latency_ms"] for r in rows]
    return {"clips": len(rows), "wer": round(sum(r["err"] for r in rows) / max(sum(r["n"] for r in rows), 1), 3),
            "wer_clean": round(sum(r["err"] for r in rows if not r["noisy"]) /
                               max(sum(r["n"] for r in rows if not r["noisy"]), 1), 3),
            "name_acc": rate("names")[0], "names": rate("names")[1], "link_rate": rate("linked")[0],
            "linked": rate("linked")[1], "number_acc": rate("numbers")[0], "numbers": rate("numbers")[1],
            "latency_ms": {"p50": pctl(lat, 0.5), "p95": pctl(lat, 0.95), "missing": sum(x is None for x in lat)},
            "errors": sum(len(r["errors"]) for r in rows), "rows": rows}


def gate_golden(rep: Report, app: App, mach: dict, update: bool):
    t = time.time()
    res = golden_run(app)
    bpath = GOLDEN / "baseline.json"
    if update or not bpath.exists():
        base = {"_note": "Golden ear baseline (docs/RELEASING.md). Re-record on purpose only: "
                "make release-check ARGS='--gates golden --update-baseline'.",
                "app_version": app.version, "recorded": time.strftime("%Y-%m-%d"), "machine": mach,
                "tolerance": {"wer_abs": 0.03, "name_acc_abs": 0.09, "link_rate_abs": 0.09, "number_acc_abs": 0.1,
                              "latency_ratio": 1.5, "latency_slack_ms": 150},
                **{k: res[k] for k in ("clips", "wer", "wer_clean", "name_acc", "link_rate", "number_acc", "latency_ms")},
                "hyps": {r["clip"]: r["hyp"] for r in res["rows"]}}
        bpath.write_text(json.dumps(base, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        return rep.add("golden", "pass", f"baseline recorded ({bpath.relative_to(ROOT)}): WER {res['wer']}, names "
                       f"{res['names']}, linked {res['linked']}, p50/p95 {res['latency_ms']['p50']}/"
                       f"{res['latency_ms']['p95']} ms", time.time() - t, result=_slim(res))
    base = json.loads(bpath.read_text(encoding="utf-8"))
    tol = base["tolerance"]
    fails, warns = [], []
    if res["wer"] > base["wer"] + tol["wer_abs"]:
        fails.append(f"WER {res['wer']} > {base['wer']} + {tol['wer_abs']}")
    for k in ("name_acc", "link_rate", "number_acc"):
        if res[k] < base[k] - tol[f"{k}_abs"]:
            fails.append(f"{k} {res[k]} < {base[k]} - {tol[f'{k}_abs']}")
    if res["errors"] or res["latency_ms"]["missing"] > 2:
        fails.append(f"{res['errors']} error messages, {res['latency_ms']['missing']} clips without a final")
    same = base["machine"]["id"] == mach["id"]
    for q in ("p50", "p95"):
        budget = base["latency_ms"][q] * tol["latency_ratio"] + tol["latency_slack_ms"]
        got = res["latency_ms"][q]
        if got is None or got > budget:
            (fails if same else warns).append(f"latency {q} {got} ms > budget {budget:.0f} ms"
                                              + ("" if same else " (other machine: warn only)"))
    changed = [{"clip": r["clip"], "baseline": base.get("hyps", {}).get(r["clip"]), "now": r["hyp"]}
               for r in res["rows"] if base.get("hyps", {}).get(r["clip"]) not in (None, r["hyp"])]
    status = "fail" if fails else ("warn" if warns else "pass")
    summ = (f"WER {res['wer']} (base {base['wer']}), names {res['names']}, linked {res['linked']}, numbers "
            f"{res['numbers']}, latency p50/p95 {res['latency_ms']['p50']}/{res['latency_ms']['p95']} ms "
            f"(base {base['latency_ms']['p50']}/{base['latency_ms']['p95']}, "
            f"{'same machine' if same else 'other machine'}); {len(changed)} transcripts changed")
    if fails or warns:
        summ += "; " + "; ".join(fails + warns)
    return rep.add("golden", status, summ, time.time() - t, result=_slim(res), changed=changed[:20])


def _slim(res):
    return {**{k: v for k, v in res.items() if k != "rows"},
            "rows": [{k: r[k] for k in ("clip", "hyp", "err", "names", "linked", "latency_ms")} for r in res["rows"]]}


# ------------------------------------------------------------------------------------------------------- ws fuzzer
def _rand_json(rnd: random.Random, depth=0):
    k = rnd.randrange(9 if depth < 4 else 5)
    if k == 0:
        return None
    if k == 1:
        return rnd.choice([True, False])
    if k == 2:
        return rnd.choice([0, -1, 2**63, 1e308, -1e308, 3.5])
    if k in (3, 4):
        return _rand_str(rnd)
    if k in (5, 6):
        return [_rand_json(rnd, depth + 1) for _ in range(rnd.randrange(6))]
    return {_rand_str(rnd): _rand_json(rnd, depth + 1) for _ in range(rnd.randrange(6))}


def _rand_str(rnd: random.Random) -> str:
    pick = rnd.randrange(6)
    if pick == 0:
        return rnd.choice(["t", "context", "stop", "end_turn", "names", "terms", "mission", "session", "hot", ""])
    if pick == 1:
        return "".join(chr(rnd.choice([rnd.randrange(32, 127), rnd.randrange(0x80, 0x800), rnd.randrange(0x4E00, 0x9FFF),
                                       rnd.randrange(0x1F300, 0x1FAFF)])) for _ in range(rnd.randrange(40)))
    if pick == 2:
        return "Orientale " * rnd.randrange(1, 3000)
    if pick == 3:
        return "\u0000\u202e\ufeff" + "x" * rnd.randrange(5)
    return "".join(rnd.choice("abc {}[]\":,\\") for _ in range(rnd.randrange(30)))


def _context_frame(rnd: random.Random) -> str:
    c = {"t": "context"}
    if rnd.random() < 0.8:
        n = rnd.choice([0, 1, 5, 200, 5000])
        c["names"] = [rnd.choice([_rand_str(rnd), {"name": _rand_str(rnd), "kind": _rand_str(rnd),
                                                   "aliases": [_rand_str(rnd) for _ in range(rnd.randrange(4))]},
                                  _rand_json(rnd), None, 7]) for _ in range(n)]
    if rnd.random() < 0.5:
        c["terms"] = [_rand_str(rnd) for _ in range(rnd.randrange(50))]
    if rnd.random() < 0.3:
        c["mission"] = _rand_json(rnd)
    if rnd.random() < 0.3:
        c["session"] = _rand_str(rnd)
    if rnd.random() < 0.3:
        c["hot"] = _rand_json(rnd)
    if rnd.random() < 0.2:
        c[_rand_str(rnd)] = _rand_json(rnd)
    return json.dumps(c, ensure_ascii=rnd.random() < 0.5)


def _fuzz_case(app: App, rnd: random.Random, pcm_bank: list[bytes]) -> str:
    """One random connection. Returns a short label of what was done (for the report)."""
    base = app.engine["backend"].replace("http", "ws", 1)
    ms = app.engine["model_server"].replace("http", "ws", 1)
    target = rnd.choice([base + "/ws/listen", base + "/ws/listen?session=" + str(rnd.randrange(1 << 30)),
                         ms + "/v1/stream?ear=arc", ms + "/v1/stream", ms + "/v1/stream?ear=arc&domain=" + quote(_rand_str(rnd)[:20])])
    kind = rnd.randrange(20)
    hdr = app.headers()
    if kind == 0:   # no token / a wrong one / a foreign Origin: must be refused, not crash
        bad = rnd.choice([{}, {"X-Luna-Token": "x" * rnd.randrange(80)}, {**hdr, "Origin": "https://evil.example"},
                          {"Authorization": "Bearer " + _rand_str(rnd)}])
        try:
            WS.connect(target, headers=bad, timeout=5).close()
            return "auth:ACCEPTED"     # flagged by the caller
        except HandshakeError as e:
            return f"auth:{e.status}"
    if kind == 1:   # garbage HTTP
        u = target.split("/", 3)
        hostport = u[2].split(":")
        s = socket.create_connection((hostport[0], int(hostport[1])), timeout=5)
        try:
            s.sendall(bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 4096))))
            s.settimeout(2)
            try:
                s.recv(1024)
            except OSError:
                pass
        finally:
            s.close()
        return "garbage-http"
    ws = WS.connect(target, headers=hdr, timeout=10)
    label = []
    try:
        for _ in range(rnd.randrange(1, 40)):
            op = rnd.randrange(16)
            if op <= 4:     # audio: real speech, noise, odd lengths
                b = rnd.choice(pcm_bank)
                off = rnd.randrange(max(1, len(b) - 1))
                n = rnd.choice([0, 1, 3, 159, FRAME - 1, FRAME, FRAME + 1, 32000, 200000])
                payload = (b[off:off + n] if rnd.random() < 0.6 else bytes(rnd.randrange(256) for _ in range(min(n, 4096))))
                ws.send_binary(payload)
                label.append("pcm")
            elif op <= 6:
                ws.send_text(_context_frame(rnd))
                label.append("ctx")
            elif op == 7:
                ws.send_text(rnd.choice(['{"t":"end_turn"}', '{"t":"stop"}', '{"t":', "[]", "null", "{}", '"stop"',
                                         json.dumps(_rand_json(rnd)), _rand_str(rnd)]))
                label.append("txt")
            elif op == 8:   # invalid UTF-8 in a text frame
                ws.send_frame(OP_TEXT, b'{"t":"context","names":["\xff\xfe\xc3"]}')
                label.append("bad-utf8")
            elif op == 9:   # reserved opcode / RSV bits
                ws.send_frame(rnd.choice([3, 4, 5, 6, 7, 11, 12, 13, 14, 15]), b"abc", rsv=rnd.randrange(8))
                label.append("bad-op")
            elif op == 10:  # fragments: an unfinished one, a stray continuation
                ws.send_frame(OP_BIN, b"\x00" * 100, fin=False)
                if rnd.random() < 0.5:
                    ws.send_frame(OP_CONT, b"\x00" * 100, fin=rnd.random() < 0.5)
                else:
                    ws.send_frame(OP_TEXT, b"{}")
                label.append("frag")
            elif op == 11:  # unmasked client frame (a protocol error)
                ws.send_frame(OP_BIN, b"\x01\x02" * 50, mask=False)
                label.append("unmasked")
            elif op == 12:  # ping, oversized control frame, close with odd codes
                ws.send_frame(OP_PING, os.urandom(rnd.choice([0, 10, 125, 126, 300])))
                label.append("ping")
            elif op == 13:  # a length field that lies (then the socket goes away)
                ws.send_frame(OP_BIN, b"\x00" * 10, length=rnd.choice([1 << 20, 1 << 31, (1 << 63) - 1]))
                label.append("lie")
                break
            elif op == 14:
                ws.send_frame(OP_CLOSE, rnd.choice([b"", b"\x03", struct.pack("!H", rnd.randrange(65536)) + os.urandom(3)]))
                label.append("close")
                break
            else:
                time.sleep(rnd.random() * 0.2)
            try:            # read whatever came back without blocking long
                while True:
                    ws.recv(timeout=0.01)
            except (TimeoutError, OSError):
                pass
    except (Closed, OSError, HandshakeError):
        label.append("closed-by-server")
    finally:
        if rnd.random() < 0.5:
            ws.close(rnd.choice([1000, 1001, 1011, 4000, 999]))
        else:
            try:
                ws.sock.close()    # just drop it
            except OSError:
                pass
    return ",".join(label[:6])


def gate_fuzz_ws(rep: Report, app: App, seconds: float, seed: int):
    t = time.time()
    rnd = random.Random(seed)
    bank = [(FIX / "crew_orientale_16k.s16le").read_bytes(), (FIX / "bullseye_16k.s16le").read_bytes()]
    exits0 = len(app.child_exits())
    resets0 = app.model_health().get("models", {}).get("watchdog", {}).get("resets", 0)
    cases, problems, kinds = 0, [], {}
    while time.time() - t < seconds:
        try:
            lab = _fuzz_case(app, rnd, bank)
        except HandshakeError as e:
            lab = f"handshake:{e.status}"
            if e.status not in (403, 1013, 0):
                problems.append(f"case {cases}: unexpected HTTP {e.status} on a valid handshake")
        except (OSError, Closed) as e:
            lab = f"io:{type(e).__name__}"
        kinds[lab.split(":")[0].split(",")[0]] = kinds.get(lab.split(":")[0].split(",")[0], 0) + 1
        if lab == "auth:ACCEPTED":
            problems.append(f"case {cases}: a connection without the right token / with a foreign Origin was accepted")
        cases += 1
        if cases % 10 == 0:
            ok, why = _healthy(app)
            if not ok:
                problems.append(f"after case {cases}: {why}")
                break
    # settle: every ear slot back, both healthy, the same children, a real turn still works
    deadline, sessions = time.time() + 20, None
    while time.time() < deadline:
        sessions = app.model_health().get("models", {}).get("arc_meta", {}).get("sessions")
        if sessions == 0:
            break
        time.sleep(1)
    if sessions:
        problems.append(f"{sessions} ear sessions still held 20 s after the fuzzer stopped (leaked slots)")
    ok, why = _healthy(app)
    if not ok:
        problems.append(why)
    exits = app.child_exits()[exits0:]
    if exits:
        problems.append(f"child process exits: {exits[:3]}")
    resets = app.model_health().get("models", {}).get("watchdog", {}).get("resets", 0)
    if resets != resets0:
        problems.append(f"decode watchdog resets {resets0} -> {resets}")
    ok2, why2, _ = orientale_turn(app)
    if not ok2:
        problems.append(f"voice turn after the fuzzer: {why2}")
    status = "fail" if problems else "pass"
    summ = (f"{cases} random connections in {seconds:.0f} s (seed {seed}); "
            + ("servers healthy, no restarts, ear slots released, voice turn ok" if not problems else "; ".join(problems[:4])))
    return rep.add("fuzz:ws", status, summ, time.time() - t, cases=cases, seed=seed, kinds=kinds, problems=problems)


def _healthy(app: App) -> tuple[bool, str]:
    try:
        h = app.model_health()
        b = app.backend_health()
    except (OSError, ValueError) as e:
        return False, f"health check failed: {e}"
    if not h.get("ok") or not h.get("models", {}).get("arc_ear", {}).get("available"):
        return False, f"model server unhealthy: {h.get('models', {}).get('arc_meta', {}).get('error')}"
    if not b.get("ok", True):
        return False, "backend unhealthy"
    return True, "ok"


# ------------------------------------------------------------------------------------------------------- C fuzzer
def gate_fuzz_c(rep: Report, app: App | None, seconds: float, seed: int, work: Path):
    t = time.time()
    if IS_WIN:
        return rep.add("fuzz:libarc", "skip", "ASan build of libarc runs on the Mac (docs/RELEASING.md); Windows runs "
                       "the protocol fuzzer only")
    cmake, cc = shutil.which("cmake"), shutil.which("clang") or shutil.which("cc")
    if not cmake or not cc:
        return rep.add("fuzz:libarc", "fail", "cmake and clang are needed for the ASan build")
    nft2 = app.ud / "assets/ear/nft2" if app else None
    if not nft2 or not (nft2 / "config.json").exists():
        seed_dir = Path(os.environ.get("RC_ASSETS_SEED", "")) / "ear/nft2"
        nft2 = seed_dir if (seed_dir / "config.json").exists() else None
    ort = next(iter(sorted((app.res / "native/onnxruntime").glob("libonnxruntime*.dylib"
                                                                  if IS_MAC else "libonnxruntime.so*"))), None) if app else None
    ort = ort or next(iter(sorted((ROOT / "desktop/build/libarc/onnxruntime").glob("libonnxruntime*"))), None)
    if not nft2 or not ort:
        return rep.add("fuzz:libarc", "fail", f"needs the ear model (nft2: {nft2}) and the pinned ONNX Runtime ({ort})")
    b = ROOT / "desktop/build/libarc-asan"
    flags = "-O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=undefined"
    steps = [[cmake, "-S", str(ROOT / "desktop/vendor/libarc"), "-B", str(b), "-DCMAKE_BUILD_TYPE=Debug",
              "-DARC_ORT_VENDOR=OFF", f"-DCMAKE_C_FLAGS={flags}", "-DCMAKE_SHARED_LINKER_FLAGS=-fsanitize=address,undefined"],
             [cmake, "--build", str(b), "-j", str(os.cpu_count() or 4)],
             [cc, *flags.split(), "-I", str(ROOT / "desktop/vendor/libarc/include"),
              str(ROOT / "desktop/tests/fuzz/fuzz_libarc.c"), "-L", str(b), "-larc", f"-Wl,-rpath,{b}", "-lm",
              "-o", str(b / "fuzz_libarc")]]
    for s in steps:
        rc, out = run(s, timeout=1200)
        if rc:
            return rep.add("fuzz:libarc", "fail", f"ASan build failed: {out.strip()[-300:]}", time.time() - t)
    env = {**os.environ, "ASAN_OPTIONS": "halt_on_error=1:abort_on_error=0:detect_leaks=0:symbolize=1",
           "UBSAN_OPTIONS": "print_stacktrace=1:halt_on_error=1"}
    errf = work / "fuzz_libarc.stderr"
    with open(errf, "w") as ef:
        p = subprocess.run([str(b / "fuzz_libarc"), str(nft2), str(ort), str(seconds), str(seed)], env=env,
                           stdout=subprocess.PIPE, stderr=ef, text=True, timeout=seconds + 600)
    err = errf.read_text(errors="replace")
    stats = {}
    try:
        stats = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        pass
    if p.returncode == 0 and stats:
        return rep.add("fuzz:libarc", "pass", f"{stats['cases']} cases, {stats['calls']} API calls in "
                       f"{stats['seconds']:.0f} s under ASan+UBSan (seed {seed}): no memory errors", time.time() - t,
                       fuzzer=stats)
    last_case = re.findall(r"^case \d+ seed (\d+)$", err, re.M)
    finding = next((ln for ln in err.splitlines() if "ERROR: AddressSanitizer" in ln or "runtime error" in ln), "")
    keep = ROOT / "desktop/dist/fuzz_libarc.crash.txt"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text(err[-60000:])
    return rep.add("fuzz:libarc", "fail", f"exit {p.returncode}: {finding.strip()[:200] or err.strip()[-200:]}; replay: "
                   f"fuzz_libarc <nft2> <ort> 1 {last_case[-1] if last_case else seed} (log {keep.relative_to(ROOT)})",
                   time.time() - t, fuzzer=stats)


# ---------------------------------------------------------------------------------------------------------- soak
def gate_soak(rep: Report, app: App, minutes: float):
    t = time.time()
    spec = json.loads((GOLDEN / "set.json").read_text(encoding="utf-8"))["clips"]
    clips = [(read_wav(GOLDEN / "audio" / f"{c['clip']}.wav"), c["speech_end_s"]) for c in spec]
    exits0, kids0 = len(app.child_exits()), app.children()
    resets0 = app.model_health().get("models", {}).get("watchdog", {}).get("resets", 0)
    samples, lats, turns, errors, i = [], [], 0, [], 0
    next_sample = 0.0
    end = t + minutes * 60
    pids = {"electron": app.proc.pid, **{(c.get("name") if isinstance(c, dict) else None) or f"child{k}":
                                          (c.get("pid") if isinstance(c, dict) else c) for k, c in enumerate(kids0)}}
    while time.time() < end:
        pcm, se = clips[i % len(clips)]
        i += 1
        try:
            r = voice_turn(app, pcm, se, tail_s=0.8)
            turns += 1
            lats.append((time.time() - t, r["latency_ms"]))
            if r["errors"]:
                errors.append(r["errors"][0])
        except (OSError, Closed, HandshakeError) as e:
            errors.append(f"{type(e).__name__}: {e}")
        if time.time() - t >= next_sample:
            next_sample += 15
            try:
                h = app.model_health()
            except (OSError, ValueError):
                h = {}
            samples.append({"t": round(time.time() - t), "ms_rss": (h.get("rss_mb") or {}).get("now"),
                            **{k: rss_mb(p) for k, p in pids.items() if p}})
    problems = []
    exits = app.child_exits()[exits0:]
    if exits or app.children() != kids0:
        problems.append(f"restarts: {exits[:3] or 'children.json changed'}")
    resets = app.model_health().get("models", {}).get("watchdog", {}).get("resets", 0)
    if resets != resets0:
        problems.append(f"decode watchdog resets {resets0} -> {resets}")
    if len(errors) > max(2, turns // 100):
        problems.append(f"{len(errors)} errors in {turns} turns: {errors[:2]}")
    # leak trend after a warm-up (first quarter): least-squares slope of each process's RSS
    leak_limit = float(os.environ.get("SOAK_LEAK_MB_PER_H", "60"))
    trend = {}
    warm = [s for s in samples if s["t"] >= minutes * 60 * 0.25]
    for key in [k for k in (samples[0] if samples else {}) if k != "t"]:
        pts = [(s["t"] / 3600, s[key]) for s in warm if s.get(key) is not None]
        if len(pts) >= 4:
            mx, my = statistics.mean(p[0] for p in pts), statistics.mean(p[1] for p in pts)
            den = sum((p[0] - mx) ** 2 for p in pts) or 1e-9
            slope = sum((p[0] - mx) * (p[1] - my) for p in pts) / den
            growth = pts[-1][1] - pts[0][1]
            trend[key] = {"mb_per_h": round(slope, 1), "growth_mb": round(growth, 1), "start": pts[0][1], "end": pts[-1][1]}
            if slope > leak_limit and growth > 30:
                problems.append(f"{key} RSS grows {slope:.0f} MB/h (+{growth:.0f} MB) > {leak_limit:.0f} MB/h")
    q = max(1, len(lats) // 4)
    first = [x for _, x in lats[q:2 * q] if x is not None]
    last = [x for _, x in lats[-q:] if x is not None]
    drift = None
    if first and last:
        a, b = statistics.median(first), statistics.median(last)
        drift = {"early_p50": a, "late_p50": b}
        if b > a * 1.5 + 100:
            problems.append(f"latency drift: p50 {a:.0f} -> {b:.0f} ms")
    status = "fail" if problems else "pass"
    summ = (f"{minutes:g} min, {turns} turns; model server RSS "
            f"{trend.get('ms_rss', {}).get('start')} -> {trend.get('ms_rss', {}).get('end')} MB "
            f"({trend.get('ms_rss', {}).get('mb_per_h')} MB/h); latency p50 {drift and drift['early_p50']} -> "
            f"{drift and drift['late_p50']} ms; restarts 0" if not problems else "; ".join(problems))
    return rep.add("soak", status, summ, time.time() - t, turns=turns, trend=trend, drift=drift, samples=samples,
                   problems=problems)


# ------------------------------------------------------------------------------------------------------------ main
def find_artifact() -> Path | None:
    d = ROOT / "desktop/dist"
    pats = ["*.dmg"] if IS_MAC else (["*Setup*.exe", "*.exe"] if IS_WIN else [])
    for p in pats:
        xs = sorted(d.glob(p), key=lambda x: x.stat().st_mtime)
        if xs:
            return xs[-1]
    return None


def default_seed() -> Path | None:
    s = os.environ.get("RC_ASSETS_SEED")
    if s:
        return Path(s)
    if IS_MAC:
        p = Path.home() / "Library/Application Support/Outpost Luna/assets"
    elif IS_WIN:
        p = Path(os.environ.get("APPDATA", "")) / "Outpost Luna/assets"
    else:
        p = Path.home() / ".config/Outpost Luna/assets"
    return p if (p / "state.json").exists() else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dmg", type=Path)
    ap.add_argument("--exe", type=Path, help="the Windows installer (unpacked with 7-Zip, never run)")
    ap.add_argument("--app", type=Path, help="an already-unpacked app: 'Outpost Luna.app' or a win-unpacked folder")
    ap.add_argument("--gates", default=None, help=f"comma list of {ALL_GATES} (default: all but soak; soak with SOAK=1)")
    ap.add_argument("--skip", default="", help="gates to leave out")
    ap.add_argument("--assets-seed", type=Path, default=None, help="where the test app's models come from (cloned)")
    ap.add_argument("--report", type=Path, default=ROOT / "desktop/dist/release-check.json")
    ap.add_argument("--update-baseline", action="store_true", help="re-record desktop/tests/golden/baseline.json")
    ap.add_argument("--keep", action="store_true", help="keep the temp install + data folder")
    ap.add_argument("--allow-unsigned", action="store_true", help="a dev build: signature check warns only")
    a = ap.parse_args()
    gates = a.gates.split(",") if a.gates else [g for g in ALL_GATES if g != "soak" or os.environ.get("SOAK") == "1"]
    gates = [g for g in gates if g not in a.skip.split(",")]
    fuzz_s = float(os.environ.get("FUZZ_SECONDS", "120"))
    soak_min = float(os.environ.get("SOAK_MINUTES", "10"))
    seed = int(os.environ.get("FUZZ_SEED", str(int(time.time()))))
    rep = Report(a.report)
    mach = machine()
    artifact = a.dmg or a.exe or (None if a.app else find_artifact())
    rep.meta = {"tool": "release_check.py", "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "platform": sys.platform,
                "machine": mach, "gates_run": gates, "artifact": str(artifact or a.app or ""),
                "artifact_sha256": _sha256(artifact) if artifact and artifact.is_file() else None,
                "git": run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"])[1].strip()}
    print(f"release-check: {', '.join(gates)} on {mach['desc']} ({mach['id']}); artifact {artifact or a.app or '-'}",
          flush=True)
    if "unit" in gates:
        gate_unit(rep)
    app_gates = [g for g in gates if g in ("smoke", "video", "golden", "fuzz", "soak")]
    work = Path(tempfile.mkdtemp(prefix="outpost-rc-"))
    app = None
    try:
        if app_gates:
            t0 = time.time()
            if not artifact and not a.app:
                rep.add("smoke", "fail", f"no installer: pass --dmg / --exe / --app (none in {ROOT / 'desktop/dist'})")
            else:
                app = App(work, artifact, a.app, a.assets_seed or default_seed())
                try:
                    info = app.install()
                    rep.meta["app_version"] = app.version
                    if info.get("signed_ok") is False and a.allow_unsigned:
                        info["signed_ok"] = None
                    info["assets"] = app.seed_assets()
                    log(f"installed {app.version}: {info['installed_from']}; models {info['assets']}")
                    log(f"signature: codesign {info.get('codesign', '-')}; spctl {info.get('spctl', info.get('authenticode', '-'))}")
                    if not app.supports_headless():
                        le = app.legacy_ear()
                        ear = le["ear"] or {}
                        raise GateError(
                            "this build cannot run silently (no OUTPOST_HEADLESS / engine.json: older than 0.3.6), so "
                            "the app was not launched; its own model server, run from the installed bundle: "
                            + ("ear loaded" if ear.get("available") else
                               f"the ear never loaded: {le['error'] or 'model server did not start'}"))
                    app.launch()
                    app.wait_ready()
                    log(f"engine.json after {app.t_engine:.1f} s, ear ready after {app.t_ready:.1f} s on ports "
                        f"{app.ports}")
                    gate_smoke(rep, app, info, t0)
                except GateError as e:
                    rep.add("smoke", "fail", f"{getattr(app, 'version', '?')}: {e}", time.time() - t0,
                            health=app.health.get("models", {}).get("arc_ear"))
                    app_gates = []   # nothing more to run against this app (the libarc fuzzer still runs below)
                if app.proc and app.proc.poll() is None and app.engine.get("model_server"):
                    if "video" in app_gates:
                        gate_video(rep, app, sweep=os.environ.get("VIDEO_SWEEP") == "1")
                    if "golden" in app_gates:
                        gate_golden(rep, app, mach, a.update_baseline)
                    if "fuzz" in app_gates:
                        gate_fuzz_ws(rep, app, fuzz_s, seed)
                    if "soak" in app_gates:
                        gate_soak(rep, app, soak_min)
                    q = app.quit()
                    rep.add("quit", "pass" if q["clean"] else "fail",
                            f"quit in {q['seconds']} s; engine.json {'removed' if q['engine_json_removed'] else 'LEFT'}; "
                            f"children {'all gone' if not q['children_left'] else 'LEFT ' + str(q['children_left'])}"
                            + ("; had to force-kill" if q["forced"] else ""), **q)
        if "fuzz" in gates:
            gate_fuzz_c(rep, app, fuzz_s, seed, work)
    except KeyboardInterrupt:
        rep.add("interrupted", "fail", "stopped by Ctrl-C")
    finally:
        if app:
            app.kill()
        if a.keep:
            log(f"kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    rep.write()
    bad = rep.failed()
    total = time.time() - rep.t0
    print(f"{'FAIL' if bad else 'PASS'} release-check: {len(rep.gates) - len(bad)}/{len(rep.gates)} gates ok in "
          f"{total / 60:.1f} min; report {a.report}", flush=True)
    sys.exit(1 if bad else 0)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


if __name__ == "__main__":
    main()
