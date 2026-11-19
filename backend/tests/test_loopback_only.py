"""The backend, started exactly as the desktop app starts it (desktop/runtime/launch.py), answers on 127.0.0.1 and is
not reachable on this computer's network address (docs/SCHOOL_IT.md: nothing on the school network can reach it)."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]


def lan_ip() -> str | None:
    """This computer's address on its network (a UDP 'connect' only picks the route; nothing is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()
    return None if ip.startswith("127.") or ip == "0.0.0.0" else ip


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_launch_binds_loopback_only():
    src = (ROOT / "desktop/runtime/launch.py").read_text()
    assert 'HOST = "127.0.0.1"' in src and "host=HOST" in src


def test_backend_not_reachable_off_loopback(tmp_path):
    ip = lan_ip()
    if not ip:
        pytest.skip("no network address on this computer")
    # the desktop layout: resources/app/launch.py + resources/app/backend, resources/site/backend (deps: here, the venv)
    res = tmp_path / "res"
    (res / "app").mkdir(parents=True)
    (res / "site" / "backend").mkdir(parents=True)
    shutil.copy(ROOT / "desktop/runtime/launch.py", res / "app" / "launch.py")
    (res / "app" / "backend").symlink_to(ROOT / "backend", target_is_directory=True)
    port = free_port()
    env = {**os.environ, "VIDEO_PREFETCH": "0", "MOON_LOG_LEVEL": "warning", "LUNA_ALLOWED_HOSTS": "",
           "MISSION_SAVE_DIR": str(tmp_path / "saves"), "TURNLOG_DIR": str(tmp_path / "turnlog")}
    p = subprocess.Popen([sys.executable, str(res / "app" / "launch.py"), "backend", "--port", str(port)], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        t0 = time.time()
        while True:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/api/network", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if p.poll() is not None or time.time() - t0 > 90:
                pytest.fail(f"backend did not start: {p.stderr.read().decode()[-800:] if p.poll() is not None else 'timeout'}")
            time.sleep(0.5)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        try:
            with pytest.raises(OSError):   # refused (nothing listens on that address) or no answer at all
                s.connect((ip, port))
        finally:
            s.close()
        if shutil.which("lsof"):
            out = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-a", "-p", str(p.pid)],
                                 capture_output=True, text=True).stdout
            listening = [ln.split()[8] for ln in out.splitlines()[1:] if len(ln.split()) > 8]
            assert listening and all(a.startswith("127.0.0.1:") for a in listening), out
    finally:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
