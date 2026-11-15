"""Windows branches of the model server, exercised on any OS with sys.platform mocked (docs/BUILD_WINDOWS.md)."""
import importlib
import sys
from pathlib import Path

import app.arctag as arctag
import app.config as config


def test_windows_loads_arctag_dll_with_its_folder_on_the_dll_path(monkeypatch, tmp_path):
    lib = tmp_path / "Outpost Luna" / "resources" / "native" / "arctag.dll"
    calls = {}
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(arctag.os, "add_dll_directory", lambda d: calls.setdefault("dll_dir", d), raising=False)
    monkeypatch.setattr(arctag.ctypes, "CDLL", lambda p, **kw: calls.setdefault("cdll", (p, kw)))
    arctag.load_library(lib)
    assert calls["dll_dir"] == str(lib.resolve().parent)
    assert calls["cdll"] == (str(lib), {"winmode": 0})


def test_posix_loads_without_dll_directory(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(arctag.ctypes, "CDLL", lambda p, **kw: calls.setdefault("cdll", (p, kw)))
    arctag.load_library(tmp_path / "libarctag.dylib")
    assert calls["cdll"] == (str(tmp_path / "libarctag.dylib"), {})


def test_library_name_per_os(monkeypatch):
    try:
        for plat, name in (("win32", "arctag.dll"), ("darwin", "libarctag.dylib"), ("linux", "libarctag.so")):
            monkeypatch.setattr(sys, "platform", plat)
            assert importlib.reload(config).ARCTAG_LIB_NAME == name
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_desktop_env_paths_win_over_dev_defaults(monkeypatch, tmp_path):
    """The desktop app sets every weight path by env var (main.js envFor); nothing falls back to a home-folder default."""
    models = tmp_path / "Outpost Luna" / "resources" / "models"
    monkeypatch.setenv("ARCTAG_LIB", str(tmp_path / "native" / "arctag.dll"))
    monkeypatch.setenv("ARCTAG_MODEL_DIR", str(models / "arctag"))
    monkeypatch.setenv("OS_TTS_ENGINE", "winrt")
    s = config.Settings(_env_file=None)
    assert s.arctag_lib == Path(tmp_path / "native" / "arctag.dll")
    assert s.arctag_model_dir == models / "arctag"
    assert s.os_tts == "on" and s.os_tts_engine == "winrt"     # speech needs no model path: the OS's own voices


def test_health_memory_probe_works_without_posix_resource_module(monkeypatch):
    """Windows has no `resource` module; /health (the desktop readiness probe) must still answer."""
    import builtins

    import psutil  # noqa: F401  (imported for real before sys.platform is faked)

    import app.main as main
    real_import = builtins.__import__

    def no_resource(name, *a, **kw):
        if name == "resource":
            raise ModuleNotFoundError("No module named 'resource'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_resource)
    monkeypatch.setattr(sys, "platform", "win32")
    out = main._rss_mb()
    assert out["now"] and out["now"] > 0 and out["peak"] and out["peak"] > 0

    monkeypatch.setattr(sys, "platform", "linux")   # any failure is swallowed, never raised
    assert main._rss_mb()["now"] > 0


def test_windows_ear_finds_the_onnxruntime_wheels_dll(monkeypatch, tmp_path):
    """libarc (the ear) loads ONNX Runtime by path: on Windows it is onnxruntime.dll in the wheel's capi folder."""
    import importlib.util
    import types

    import app.nft2 as nft2
    pkg = tmp_path / "C" / "Users" / "Zoë" / "Outpost Luna" / "resources" / "site" / "models" / "onnxruntime"
    (pkg / "capi").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "capi" / "onnxruntime.dll").write_bytes(b"MZ")
    (pkg / "capi" / "libonnxruntime.1.23.2.dylib").write_bytes(b"x")    # the other OS's name must not be picked
    monkeypatch.delenv("ARC_ORT_LIB", raising=False)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: types.SimpleNamespace(origin=str(pkg / "__init__.py")))
    monkeypatch.setattr(sys, "platform", "win32")
    got = nft2.ort_library()
    assert got == pkg / "capi" / "onnxruntime.dll"
    # the path crosses into C as UTF-8; libarc's Windows shim (compat/win/arc_u8io.h) and ort_loader.c widen it
    assert str(got).encode() == str(got).encode("utf-8") and "Zoë".encode() in str(got).encode()
