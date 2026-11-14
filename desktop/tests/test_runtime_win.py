"""Windows branches of the desktop's Python side, on any OS with sys.platform mocked:

    uv run --no-project --with pytest python -m pytest -q desktop/tests

launch.py (the children's entry point) and build_python.py (the embedded Python + the cross-build's Windows layout).
"""
import importlib.util
import sys
import threading
import types
from pathlib import Path

DESK = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


launch = load("desktop_launch", DESK / "runtime/launch.py")
build_python = load("desktop_build_python", DESK / "scripts/build_python.py")


class FakeKernel32:
    def __init__(self, handle):
        self.handle, self.calls = handle, []

    def OpenProcess(self, access, inherit, pid):
        self.calls.append(("OpenProcess", access, pid))
        return self.handle

    def WaitForSingleObject(self, h, ms):
        self.calls.append(("Wait", h, ms))

    def CloseHandle(self, h):
        self.calls.append(("Close", h))


def run_watchdog(monkeypatch, handle):
    import ctypes
    k = FakeKernel32(handle)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", types.SimpleNamespace(kernel32=k), raising=False)
    exited = threading.Event()
    monkeypatch.setattr(launch.os, "_exit", lambda code: exited.set())
    launch.watch_parent(4242)
    assert exited.wait(3), "the watchdog never exited"
    return k.calls


def test_windows_watchdog_waits_on_the_parent_handle_then_exits(monkeypatch):
    calls = run_watchdog(monkeypatch, handle=77)
    assert calls[0] == ("OpenProcess", 0x00100000, 4242)          # SYNCHRONIZE only
    assert ("Wait", 77, 0xFFFFFFFF) in calls and ("Close", 77) in calls


def test_windows_watchdog_exits_when_the_parent_is_already_gone(monkeypatch):
    calls = run_watchdog(monkeypatch, handle=0)
    assert calls == [("OpenProcess", 0x00100000, 4242)]


def test_children_listen_on_loopback_only(monkeypatch, tmp_path):
    """127.0.0.1, never 0.0.0.0: Windows Defender Firewall prompts for a program that listens on a network interface,
    and stays silent for loopback."""
    got = {}
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda app, **kw: got.update(app=app, **kw)))
    monkeypatch.setattr(launch, "HERE", tmp_path)
    (tmp_path / "backend").mkdir()
    monkeypatch.setattr(sys, "argv", ["launch.py", "backend", "--port", "47310"])
    monkeypatch.delenv("MOON_PARENT_PID", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    path0 = list(sys.path)
    try:
        launch.main()
    finally:
        sys.path[:] = path0
    assert got["host"] == "127.0.0.1" and got["port"] == 47310
    assert "GEMINI_API_KEY" not in launch.os.environ


def test_windows_python_layout(monkeypatch, tmp_path):
    monkeypatch.setattr(build_python, "WIN", True)
    assert build_python.python_exe(tmp_path) == tmp_path / "python.exe"
    monkeypatch.setattr(build_python, "WIN", False)
    assert build_python.python_exe(tmp_path) == tmp_path / "bin/python3"


def test_trim_on_a_windows_tree(monkeypatch, tmp_path):
    """python-build-standalone's Windows layout: Lib/, DLLs/, libs/, tcl/ next to python.exe."""
    monkeypatch.setattr(build_python, "WIN", True)
    py, site = tmp_path / "python", tmp_path / "site"
    keep = ["python.exe", "python311.dll", "vcruntime140.dll", "Lib/os.py", "DLLs/_ssl.pyd", "DLLs/sqlite3.dll"]
    drop = ["Lib/test/test_os.py", "Lib/tkinter/__init__.py", "Lib/idlelib/idle.py", "tcl/tcl8.6/init.tcl",
            "libs/python311.lib", "DLLs/_tkinter.pyd", "DLLs/tcl86t.dll", "DLLs/tk86t.dll", "include/Python.h"]
    site_keep = ["torch/lib/c10.dll", "numpy/__init__.py"]
    site_drop = ["torch/lib/c10.lib", "torch/include/x.h", "numpy/tests/test_a.py", "torch/lib/x.pdb", "pkg/m.pyi"]
    for f in keep + drop:
        (py / f).parent.mkdir(parents=True, exist_ok=True)
        (py / f).write_bytes(b"x")
    for f in site_keep + site_drop:
        (site / f).parent.mkdir(parents=True, exist_ok=True)
        (site / f).write_bytes(b"x")
    build_python.trim(py, [site])
    assert [f for f in keep if not (py / f).exists()] == []
    assert [f for f in drop if (py / f).exists()] == []
    assert [f for f in site_keep if not (site / f).exists()] == []
    assert [f for f in site_drop if (site / f).exists()] == []


def test_cross_target_is_windows_x64():
    t = build_python.TARGETS["win-x64"]
    assert t["uv_platform"] == "x86_64-pc-windows-msvc" and t["os"] == "windows" and t["arch"] == "x86_64"
