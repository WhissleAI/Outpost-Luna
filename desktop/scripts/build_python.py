"""Build the desktop app's Python: one relocatable CPython (python-build-standalone, via `uv python install`) plus the
backend's and the model server's locked dependencies, each in its own folder (their numpy pins differ: backend 2.x,
model server 1.26), and the app code itself.

    uv run --no-project python desktop/scripts/build_python.py      (or: make desktop-python)

Output (all under desktop/resources/, gitignored):
    python/                 the interpreter (bin/python3 on macOS / Linux, python.exe on Windows)
    site/backend/           backend deps (uv export --frozen of backend/uv.lock)
    site/models/            model-server deps (model_server/uv.lock, incl. the Windows-only WinRT speech + comtypes
                            packages on a Windows target) + the arc-transcriber wheel
    app/backend/            backend/app + backend/data (minus media and caches; media is added by electron-builder)
    app/model_server/       model_server/app
    app/frontend/           frontend/dist (npm run build)
    app/launch.py           the child-process entry point (desktop/runtime/launch.py)

The arc-transcriber wheel comes from desktop/vendor/wheels/ (see docs/DESKTOP.md); with --build-wheels it is built from
the local checkout first. Speech uses the OS's own voices (model_server/app/tts_os.py): nothing to bundle on macOS
(/usr/bin/say); on Windows the pinned pywinrt packages come from the lock like any other dependency. Caches stay in desktop/build/.

Cross-build (docs/BUILD_WINDOWS.md, "Cross-build on a Mac"): `--target win-x64` on macOS / Linux lays out the Windows
tree instead: python-build-standalone's x86_64-pc-windows-msvc build (sha256-checked against the release's SHA256SUMS),
win_amd64 wheels (`uv pip install --python-platform x86_64-pc-windows-msvc`), and bytecode compiled by this machine's
CPython of the same minor version (a .pyc depends on the Python version, not the OS).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESK = ROOT / "desktop"
RES = DESK / "resources"
BUILD = DESK / "build"
WHEELS = DESK / "vendor/wheels"
PY_VERSION = os.environ.get("DESKTOP_PYTHON", "3.11")
WIN = sys.platform == "win32"     # the TARGET is Windows (this machine, or --target win-x64)
# Cross-build targets: the uv platform for wheels and python-build-standalone's download for the interpreter.
TARGETS = {"win-x64": {"uv_platform": "x86_64-pc-windows-msvc", "os": "windows", "arch": "x86_64"}}
CROSS: dict | None = None         # set by --target
VENDORED = ("arc-transcriber",)
LOCAL_SRC = {  # dev-machine checkouts, for --build-wheels (the paths model_server/pyproject.toml uses)
    "arc-transcriber": ROOT / "../../../../dv3work/arc/arc_transcriber",
}
# The OS-voice engine's Windows packages (model_server/pyproject.toml): a Windows tree must hold every one of them.
WIN_SPEECH = ("winrt/_winrt", "winrt/_winrt_windows_media_speechsynthesis", "winrt/_winrt_windows_media_core",
              "winrt/_winrt_windows_storage_streams", "winrt/_winrt_windows_foundation",
              "winrt/_winrt_windows_foundation_collections", "comtypes/__init__.py")


def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def uv_env() -> dict:
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(BUILD / "uv-cache"))
    env["UV_PYTHON_INSTALL_DIR"] = str(BUILD / "uv-python")
    env["UV_PYTHON_INSTALL_BIN"] = "0"   # no python3.11 shim in ~/.local/bin: the build keeps to desktop/build
    return env


def python_exe(pydir: Path) -> Path:
    return pydir / "python.exe" if WIN else pydir / "bin/python3"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def install_python_cross() -> Path:
    """The target OS's python-build-standalone "install_only_stripped" build: the same release `uv python install`
    picks natively (uv's own download list), checked against that release's SHA256SUMS, unpacked into resources/python."""
    out = subprocess.run(["uv", "python", "list", "--all-platforms", "--only-downloads", "--output-format", "json"],
                         env=uv_env(), check=True, capture_output=True, text=True).stdout
    cands = [e for e in json.loads(out) if e["implementation"] == "cpython" and e["os"] == CROSS["os"]
             and e["arch"] == CROSS["arch"] and e.get("variant", "default") == "default"
             and f"{e['version_parts']['major']}.{e['version_parts']['minor']}" == PY_VERSION and e.get("url")]
    if not cands:
        sys.exit(f"uv knows no CPython {PY_VERSION} download for {CROSS['os']}-{CROSS['arch']}")
    e = max(cands, key=lambda e: e["version_parts"]["patch"])
    url = e["url"]
    name = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    tgz = BUILD / name
    if not tgz.exists():
        print(f"downloading {name}", flush=True)
        with urllib.request.urlopen(url, timeout=120) as r, open(tgz.with_suffix(".part"), "wb") as f:
            shutil.copyfileobj(r, f)
        tgz.with_suffix(".part").replace(tgz)
    sums = urllib.request.urlopen(url.rsplit("/", 1)[0] + "/SHA256SUMS", timeout=60).read().decode()
    want = {ln.split()[1]: ln.split()[0] for ln in sums.splitlines() if len(ln.split()) == 2}.get(name)
    got = _sha256(tgz)
    if want != got:
        tgz.unlink()
        sys.exit(f"{name}: sha256 {got} does not match the release's SHA256SUMS ({want})")
    print(f"{name}: sha256 ok", flush=True)
    dst = RES / "python"
    shutil.rmtree(dst, ignore_errors=True)
    tmp = BUILD / "py-unpack"
    shutil.rmtree(tmp, ignore_errors=True)
    with tarfile.open(tgz) as t:
        t.extractall(tmp, filter="data")
    shutil.move(str(tmp / "python"), str(dst))
    shutil.rmtree(tmp, ignore_errors=True)
    for p in dst.rglob("EXTERNALLY-MANAGED"):
        p.unlink()
    return dst


def host_python() -> Path:
    """This machine's managed CPython of PY_VERSION (bytecode for a cross-built tree; same minor version = same .pyc)."""
    env = uv_env()
    run("uv", "python", "install", PY_VERSION, env=env)
    return Path(subprocess.run(["uv", "python", "find", "--managed-python", PY_VERSION], env=env, check=True,
                               capture_output=True, text=True).stdout.strip())


def install_python() -> Path:
    """python-build-standalone via uv, copied (not linked) into resources/python so the app owns it."""
    if CROSS:
        return install_python_cross()
    env = uv_env()
    run("uv", "python", "install", PY_VERSION, env=env)
    found = subprocess.run(["uv", "python", "find", "--managed-python", PY_VERSION], env=env, check=True,
                           capture_output=True, text=True).stdout.strip()
    src = Path(found).resolve()
    src = src.parent if WIN else src.parents[1]           # .../cpython-3.11.x-<plat>/(bin/python3.11 | python.exe)
    dst = RES / "python"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst, symlinks=True)
    # The managed install is marked EXTERNALLY-MANAGED; we install with --target, so this only matters for pip users.
    for p in dst.rglob("EXTERNALLY-MANAGED"):
        p.unlink()
    return dst


def build_wheels():
    WHEELS.mkdir(parents=True, exist_ok=True)
    for name, src in LOCAL_SRC.items():
        src = src.resolve()
        if not src.exists():
            sys.exit(f"{name}: no local checkout at {src}; put its wheel in {WHEELS}")
        tmp = BUILD / "wheel-src" / name
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(src, tmp, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.egg-info", "build", "dist", "tests",
                                                                 ".pytest_cache", "c", "examples", "macos"))
        run("uv", "build", "--wheel", "--out-dir", WHEELS, tmp, env=uv_env())


def wheel_for(name: str) -> Path:
    stem = name.replace("-", "_")
    found = sorted(WHEELS.glob(f"{stem}-*.whl"))
    if not found:
        sys.exit(f"missing {stem}-*.whl in {WHEELS} (run with --build-wheels on a dev machine, or see docs/DESKTOP.md)")
    return found[-1]


def install_site(py: Path, project: str, target: Path, extra: list[Path]):
    req = BUILD / f"req-{project}.txt"
    args = ["uv", "export", "--project", ROOT / project, "--frozen", "--no-dev", "--no-hashes", "--no-emit-project",
            "--no-header", "-o", req]
    for name in VENDORED:
        args += ["--no-emit-package", name]
    run(*args, env=uv_env())
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    # --no-deps: the export is the whole locked set already (incl. the vendored packages' own deps).
    # Cross-build: resolve wheels for the target platform; uv evaluates the export's markers for it (colorama-style
    # Windows-only deps come in, uvloop stays out). Pure-Python sdists (docopt) still build here; check_cross_site()
    # then refuses anything native to this machine.
    who = ["--python-platform", CROSS["uv_platform"], "--python-version", PY_VERSION] if CROSS else ["--python", py]
    run("uv", "pip", "install", *who, "--target", target, "--no-deps", "--link-mode", "copy",
        "-r", req, *extra, env=uv_env())
    if CROSS:
        check_cross_site(target)


def check_win_speech(site: Path) -> None:
    """The Windows OS-voice engine's packages are in the tree (pywinrt's .pyd per namespace, comtypes for SAPI)."""
    missing = [m for m in WIN_SPEECH if not (list(site.glob(m + "*.pyd")) or (site / m).exists())]
    if missing:
        sys.exit(f"{site.name}: the Windows speech packages are missing {missing} (model_server/pyproject.toml)")
    print(f"{site.name}: Windows speech packages present (WinRT SpeechSynthesis + comtypes/SAPI)", flush=True)


def check_cross_site(site: Path) -> None:
    """A cross-built site folder must hold only Windows binaries: no .so / .dylib, and every wheel tag win_amd64 or
    pure (an sdist built on this Mac for a package with C code would otherwise slip in as a macOS binary)."""
    native = [p.relative_to(site).as_posix() for p in site.rglob("*") if p.suffix in (".so", ".dylib") and p.is_file()]
    tags = set()
    for w in site.glob("*.dist-info/WHEEL"):
        tags |= {ln.split(":", 1)[1].strip() for ln in w.read_text(encoding="utf-8").splitlines() if ln.startswith("Tag:")}
    foreign = sorted(t for t in tags if not (t.endswith("-any") or t.endswith("win_amd64")))
    if native or foreign:
        sys.exit(f"{site.name}: not a Windows tree: native files {native[:8]}, wheel tags {foreign[:8]}")
    print(f"{site.name}: Windows-only binaries ({len(tags)} wheel tags, all win_amd64 or pure)", flush=True)


# The Visual C++ runtime, next to python.exe (the application folder: Windows searches it for every DLL the process
# loads). torch (c10.dll, torch_cpu.dll), onnxruntime and rapidfuzz import MSVCP140.dll / MSVCP140_1.dll, which
# python-build-standalone does not ship (it has vcruntime140*.dll only) and a clean Windows does not have unless some
# other program installed the VC++ Redistributable: without these the model server dies on `import torch` with
# WinError 126. Microsoft's redistributable DLLs, from the pinned msvc-runtime wheel (PyPI), win_amd64.
MSVC_RUNTIME = "msvc-runtime==14.44.35112"
MSVC_DLLS = ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
             "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll", "vcomp140.dll")


def install_msvc_runtime(py_dir: Path, py: Path) -> None:
    tmp = BUILD / "msvc-runtime"
    shutil.rmtree(tmp, ignore_errors=True)
    who = ["--python-platform", TARGETS["win-x64"]["uv_platform"], "--python-version", PY_VERSION] if CROSS else ["--python", py]
    run("uv", "pip", "install", *who, "--target", tmp, "--no-deps", "--link-mode", "copy", MSVC_RUNTIME, env=uv_env())
    for name in MSVC_DLLS:
        src = tmp / name if (tmp / name).exists() else tmp / "Scripts" / name
        if not src.exists():
            sys.exit(f"{MSVC_RUNTIME} has no {name}")
        shutil.copy2(src, py_dir / name)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Visual C++ runtime ({MSVC_RUNTIME}): {len(MSVC_DLLS)} DLLs next to python.exe", flush=True)


# ------------------------------------------------------------------------------------------------- size trimming
STDLIB_DROP = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data", "unittest/test",
               "distutils/tests", "ctypes/test", "sqlite3/test", "config-3.11-darwin", "config-3.11-x86_64-linux-gnu"]
SITE_DROP_DIRS = {"tests", "__pycache__"}
SITE_DROP_PATHS = ["torch/include", "torch/share", "torch/_inductor/codegen/cuda", "torch/utils/benchmark",
                   "caffe2", "functorch/csrc", "torchgen/packaged", "scipy/datasets"]
SITE_DROP_GLOBS = ["**/*.pyi", "**/*.a", "**/*.lib", "**/*.pdb", "torch/lib/*.lib"]
# Installers and dev tools nothing imports at run time (checked with `python -X importtime` on both children through
# desktop/scripts/smoke.py, plus a grep of the app and arc_audio; docs/DESKTOP.md "What the build drops").
#   pip / setuptools / pkg_resources / _distutils_hack / wheel: install-time only (the bundle never installs anything);
#     the interpreter's own copies too, with distutils-precedence.pth, which imported _distutils_hack at every start.
#   pygments: optional for rich (pretty tracebacks of the CLIs typer and huggingface_hub ship; unused under uvicorn).
#   networkx: only torch._inductor / functorch partitioners (torch.compile), which the app never calls.
#   hf_xet: huggingface_hub's optional Xet download backend; the app runs with HF_HUB_OFFLINE=1 and local models.
#   torch/bin/protoc*: the protobuf compiler (8 MB, a build tool). torch/bin/torch_shm_manager stays: `import torch`
#     refuses to start without it on macOS / Linux (torch/__init__.py _manager_path), though the app never shares tensors.
#   numpy/f2py (Fortran wrapper generator) and each site folder's bin/ (console scripts with a build-machine shebang).
#   onnxruntime/{transformers,quantization,tools}: ONNX model optimizer / quantizer / converter CLIs; `import
#     onnxruntime` never loads them. onnxruntime/capi/libonnxruntime.*.dylib (34 MB, macOS): the C-API library for C
#     callers; the Python binding (onnxruntime_pybind11_state.so) is self-contained (`otool -L` lists no link to it)
#     and lsof shows it unmapped while a session runs. The Windows onnxruntime.dll is left alone.
UNUSED_PACKAGES = ["pip", "setuptools", "pkg_resources", "_distutils_hack", "wheel", "pygments", "networkx", "hf_xet"]
UNUSED_FILES = ["distutils-precedence.pth", "torch/bin/protoc*", "numpy/f2py", "bin", "onnxruntime/transformers",
                "onnxruntime/quantization", "onnxruntime/tools", "onnxruntime/capi/libonnxruntime.*.dylib"]
HEADERS = {".h", ".hpp", ".hxx", ".cuh", ".inl", ".tcc"}


def _unused(site: Path) -> list[Path]:
    """The UNUSED_PACKAGES (+ their dist-info), UNUSED_FILES and header-only include/ dirs in one site folder."""
    out = [p for f in UNUSED_FILES for p in site.glob(f)]
    for name in UNUSED_PACKAGES:
        out += [site / name, *site.glob(f"{name}-*.dist-info")]
    out += [d for d in site.rglob("include") if d.is_dir() and all(f.suffix in HEADERS for f in d.rglob("*") if f.is_file())]
    return out


def _rm(p: Path) -> int:
    if not p.exists():
        return 0
    n = sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size
    shutil.rmtree(p) if p.is_dir() else p.unlink()
    return n


def trim(py_dir: Path, sites: list[Path]) -> None:
    freed = 0
    lib = py_dir / ("Lib" if WIN else f"lib/python{PY_VERSION}")
    for d in STDLIB_DROP:
        freed += _rm(lib / d)
    for d in ("include", "share", "tcl", "lib/tcl8.6", "lib/tk8.6", "lib/itcl4.2.4", "lib/thread2.8.9"):
        freed += _rm(py_dir / d)
    # Windows layout: Tk lives in DLLs/, import libraries (.lib, for building C extensions) in libs/
    for d in ("libs", "DLLs/_tkinter.pyd", "DLLs/tcl86t.dll", "DLLs/tk86t.dll"):
        freed += _rm(py_dir / d)
    for f in list(py_dir.glob("lib/libtcl*")) + list(py_dir.glob("lib/libtk*")):
        freed += _rm(f)
    # The interpreter's own site-packages (pip, setuptools) and pip's launchers.
    for p in _unused(lib / "site-packages"):
        freed += _rm(p)
    for f in [*py_dir.glob("bin/pip*"), *py_dir.glob("Scripts/pip*")]:
        freed += _rm(f)
    for site in sites:
        for p in _unused(site):
            freed += _rm(p)
        for d in SITE_DROP_PATHS:
            freed += _rm(site / d)
        for pat in SITE_DROP_GLOBS:
            for f in site.glob(pat):
                freed += _rm(f)
    for base in [lib, *sites]:
        for d in sorted((p for p in base.rglob("*") if p.is_dir() and p.name in SITE_DROP_DIRS), key=lambda p: -len(p.parts)):
            freed += _rm(d)
        for f in base.rglob("*.pyc"):
            freed += _rm(f)
    print(f"trimmed {freed / 1e6:.0f} MB", flush=True)


# ------------------------------------------------------------------------------------------------- app code
APP_IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".DS_Store", ".env", ".env.*")


def stage_app(skip_frontend: bool):
    app = RES / "app"
    shutil.rmtree(app, ignore_errors=True)
    shutil.copytree(ROOT / "backend/app", app / "backend/app", ignore=APP_IGNORE)
    # data: read-only in the bundle. media is mapped by electron-builder (Moon map + the trimmed clips, trim_media.py);
    # cache/ and tts_cache/ are rebuilt in the per-user folder (CACHE_DIR).
    shutil.copytree(ROOT / "backend/data", app / "backend/data",
                    ignore=shutil.ignore_patterns("media", "cache", "tts_cache", "video_cache", ".DS_Store", ".env"))
    shutil.copytree(ROOT / "model_server/app", app / "model_server/app", ignore=APP_IGNORE)
    shutil.copy2(DESK / "runtime/launch.py", app / "launch.py")
    if not skip_frontend:
        run("npm", "run", "build", cwd=ROOT / "frontend", shell=sys.platform == "win32")   # npm.cmd: the HOST, not the target
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").exists():
        sys.exit("frontend/dist/index.html missing: run `npm run build` in frontend/")
    shutil.copytree(dist, app / "frontend")
    # Camera gestures: the vision runtime + models ship inside the app (frontend/tools/fetch_vision.mjs; docs/GESTURES.md)
    for must in ("backend/app/director_model/weights.json", "backend/app/director_model/weights.npz",
                 "backend/data/places.json", "backend/data/index/clips.json",
                 "backend/data/ear_vocab.json", "model_server/app/tts_os.py", "model_server/app/os_voices.py",
                 "model_server/app/voice_pack.py", "backend/data/voice_pack/lines.json",
                 "backend/data/video/catalog.json",
                 "frontend/vision/vision_wasm_module_internal.js", "frontend/vision/vision_wasm_module_internal.wasm",
                 "frontend/vision/hand_landmarker.task", "frontend/vision/blaze_face_short_range.tflite"):
        if not (app / must).exists():
            sys.exit(f"bundle is missing {must}")
    # Never ship a key: fail the build if any .env slipped in.
    leaked = [p for p in RES.rglob(".env*") if p.is_file()]
    if leaked:
        sys.exit(f"refusing to bundle env files: {leaked}")


def precompile(py: Path, dirs: list[Path]) -> None:
    """Bytecode in the bundle, never re-validated (unchecked-hash): the bundle is read-only and signed, so Python must
    neither check source mtimes nor write .pyc next to them at run time (the app sets PYTHONDONTWRITEBYTECODE=1).
    Cross-build: the target's python.exe cannot run here, so this machine's CPython of the same version compiles."""
    if CROSS:
        py = host_python()
    subprocess.run([str(py), "-m", "compileall", "-q", "-j0", "--invalidation-mode", "unchecked-hash",
                    *[str(d) for d in dirs if d.exists()]], check=False)


def du(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink()) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-wheels", action="store_true", help="build the vendored wheels from the local checkouts first")
    ap.add_argument("--app-only", action="store_true", help="only re-stage the app code (python/ and site/ unchanged)")
    ap.add_argument("--skip-frontend-build", action="store_true", help="use the existing frontend/dist")
    ap.add_argument("--target", choices=sorted(TARGETS), help="cross-build for another OS (docs/BUILD_WINDOWS.md)")
    a = ap.parse_args()
    global WIN, CROSS
    if a.target:
        CROSS, WIN = TARGETS[a.target], True
    RES.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    if not a.app_only:
        if a.build_wheels:
            build_wheels()
        extra = [wheel_for(n) for n in VENDORED]
        py_dir = install_python()
        py = python_exe(py_dir)
        install_site(py, "backend", RES / "site/backend", [])
        install_site(py, "model_server", RES / "site/models", extra)
        if WIN:
            check_win_speech(RES / "site/models")
        if WIN:
            install_msvc_runtime(py_dir, py)
        trim(py_dir, [RES / "site/backend", RES / "site/models"])
    stage_app(a.skip_frontend_build)
    py_dir = RES / "python"
    lib = py_dir / ("Lib" if WIN else f"lib/python{PY_VERSION}")
    precompile(python_exe(py_dir), [lib, RES / "site/backend", RES / "site/models", RES / "app"] if not a.app_only
               else [RES / "app"])
    for p in ("python", "site/backend", "site/models", "app"):
        if (RES / p).exists():
            print(f"  {p:14s} {du(RES / p):8.1f} MB")
    if WIN and not a.app_only:
        # every DLL / .pyd import must resolve in the bundle or in Windows itself (a clean PC: no VC++ Redistributable)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from win_bundle_check import check_dlls
        missing = check_dlls(RES)
        if missing:
            sys.exit("DLL imports that resolve nowhere on a clean Windows:\n" + "\n".join(f"  {d} <- {f}" for f, d in missing))
        print("Windows DLL imports: all resolve (bundle + in-box Windows)")
    print(f"platform {platform.system()} {platform.machine()}; resources in {RES}{' (target: Windows x64)' if CROSS else ''}")


if __name__ == "__main__":
    main()
