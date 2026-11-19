"""Entry point for the desktop app's two Python children (the Electron main process spawns these).

    python launch.py backend --port 47310
    python launch.py models  --port 47210

Puts the right dependency folder (resources/site/<backend|models>) and app folder on sys.path, then runs uvicorn on
127.0.0.1 only (HOST). A watchdog thread exits the process when the parent (Electron, MOON_PARENT_PID) is gone, so a crashed or
force-quit app never leaves a model server holding 1 GB of RAM. Electron also kills the tree on quit and reaps stale
pids on the next start; this is the third line of defence.
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent            # resources/app
RES = HERE.parent                                  # resources
LAYOUT = {"backend": ("site/backend", "backend"), "models": ("site/models", "model_server")}
HOST = "127.0.0.1"   # loopback only, never 0.0.0.0: nothing on the school / home network can reach the servers
OFFLINE_KEYS = ("DEEPGRAM_API_KEY", "NASA_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "HF_TOKEN")


def watch_parent(pid: int) -> None:
    def alive() -> bool:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not h:
                return False
            k.WaitForSingleObject(h, 0xFFFFFFFF)       # blocks until the parent exits
            k.CloseHandle(h)
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return os.getppid() == pid

    def loop():
        while alive():
            time.sleep(1.0)
        os._exit(0)

    threading.Thread(target=loop, name="parent-watchdog", daemon=True).start()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("which", choices=sorted(LAYOUT))
    ap.add_argument("--port", type=int, required=True)
    a = ap.parse_args()
    site, app_dir = LAYOUT[a.which]
    sys.path[:0] = [str(HERE / app_dir), str(RES / site)]
    os.chdir(HERE / app_dir)   # pydantic reads ../.env and .env from here: the bundle ships neither (build check)
    for k in OFFLINE_KEYS:     # offline app: no cloud keys, whatever the launching shell had
        os.environ.pop(k, None)
    # ONNX Runtime's official builds (1.32 on macOS) ship Microsoft's 1DS telemetry, ON by default: it phones Azure
    # (*.events.data.microsoft.com) within seconds of the first session, from native code. The app promises no network
    # after setup, so it is off before anything loads onnxruntime (the Python wheel and libarc's own copy both read it).
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"
    if os.environ.get("MOON_PARENT_PID"):
        watch_parent(int(os.environ["MOON_PARENT_PID"]))
    # School network mode (app/netgate.py, docs/SCHOOL_IT.md): the outbound gate goes in before anything can connect.
    # When it is on at launch the plain asyncio loop runs (not uvloop), so the socket-level backstop sees every connect.
    from app import netgate
    netgate.install()
    import uvicorn
    uvicorn.run("app.main:app", host=HOST, port=a.port, log_level=os.environ.get("MOON_LOG_LEVEL", "info"),
                access_log=False, loop="asyncio" if netgate.enforcing() else "auto")


if __name__ == "__main__":
    main()
