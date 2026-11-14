"""Build the desktop app's Python: one relocatable CPython (python-build-standalone, via `uv python install`) plus the
backend's and the model server's locked dependencies, each in its own folder (their numpy pins differ: backend 2.x,
model server 1.26), and the app code itself.

    uv run --no-project python desktop/scripts/build_python.py      (or: make desktop-python)

Output (all under desktop/resources/, gitignored):
    python/                 the interpreter (bin/python3 on macOS / Linux, python.exe on Windows)
    site/backend/           backend deps (uv export --frozen of backend/uv.lock)
    site/models/            model-server deps (model_server/uv.lock) + arc-transcriber and steertts-edge wheels
    app/backend/            backend/app + backend/data (minus media and caches; media is added by electron-builder)
    app/model_server/       model_server/app
    app/frontend/           frontend/dist (npm run build)
    app/launch.py           the child-process entry point (desktop/runtime/launch.py)

The wheels for arc-transcriber and steertts-edge come from desktop/vendor/wheels/ (see docs/DESKTOP.md); with --build-wheels
they are built from the local checkouts first. Caches stay in desktop/build/.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESK = ROOT / "desktop"
RES = DESK / "resources"
BUILD = DESK / "build"
WHEELS = DESK / "vendor/wheels"
PY_VERSION = os.environ.get("DESKTOP_PYTHON", "3.11")
WIN = sys.platform == "win32"
VENDORED = ("arc-transcriber", "steertts-edge")
LOCAL_SRC = {  # dev-machine checkouts, for --build-wheels (the paths model_server/pyproject.toml uses)
    "arc-transcriber": ROOT / "../../../../dv3work/arc/arc_transcriber",
    "steertts-edge": ROOT / "../steer-tts/edge",
}


def run(*cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def uv_env() -> dict:
    env = dict(os.environ)
    env.setdefault("UV_CACHE_DIR", str(BUILD / "uv-cache"))
    env["UV_PYTHON_INSTALL_DIR"] = str(BUILD / "uv-python")
    return env


def python_exe(pydir: Path) -> Path:
    return pydir / "python.exe" if WIN else pydir / "bin/python3"


def install_python() -> Path:
    """python-build-standalone via uv, copied (not linked) into resources/python so the app owns it."""
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
    run("uv", "pip", "install", "--python", py, "--target", target, "--no-deps", "--link-mode", "copy",
        "-r", req, *extra, env=uv_env())


# ------------------------------------------------------------------------------------------------- size trimming
STDLIB_DROP = ["test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3", "pydoc_data", "unittest/test",
               "distutils/tests", "ctypes/test", "sqlite3/test", "config-3.11-darwin", "config-3.11-x86_64-linux-gnu"]
SITE_DROP_DIRS = {"tests", "__pycache__"}
SITE_DROP_PATHS = ["torch/include", "torch/share", "torch/_inductor/codegen/cuda", "torch/utils/benchmark",
                   "caffe2", "functorch/csrc", "torchgen/packaged", "scipy/datasets"]
SITE_DROP_GLOBS = ["**/*.pyi", "**/*.a", "**/*.lib", "**/*.pdb", "torch/lib/*.lib"]


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
    for f in list(py_dir.glob("lib/libtcl*")) + list(py_dir.glob("lib/libtk*")):
        freed += _rm(f)
    for site in sites:
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
    # data: read-only in the bundle. media (~0.5 GB) is mapped by electron-builder straight from backend/data/media;
    # cache/ and tts_cache/ are rebuilt in the per-user folder (CACHE_DIR).
    shutil.copytree(ROOT / "backend/data", app / "backend/data",
                    ignore=shutil.ignore_patterns("media", "cache", "tts_cache", ".DS_Store", ".env"))
    shutil.copytree(ROOT / "model_server/app", app / "model_server/app", ignore=APP_IGNORE)
    shutil.copy2(DESK / "runtime/launch.py", app / "launch.py")
    if not skip_frontend:
        run("npm", "run", "build", cwd=ROOT / "frontend", shell=WIN)
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").exists():
        sys.exit("frontend/dist/index.html missing: run `npm run build` in frontend/")
    shutil.copytree(dist, app / "frontend")
    # Camera gestures: the vision runtime + models ship inside the app (frontend/tools/fetch_vision.mjs; docs/GESTURES.md)
    for must in ("backend/app/director_model/weights.json", "backend/app/director_model/weights.npz",
                 "backend/data/places.json", "backend/data/index/clips.json",
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
    neither check source mtimes nor write .pyc next to them at run time (the app sets PYTHONDONTWRITEBYTECODE=1)."""
    subprocess.run([str(py), "-m", "compileall", "-q", "-j0", "--invalidation-mode", "unchecked-hash",
                    *[str(d) for d in dirs if d.exists()]], check=False)


def du(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink()) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-wheels", action="store_true", help="build the vendored wheels from the local checkouts first")
    ap.add_argument("--app-only", action="store_true", help="only re-stage the app code (python/ and site/ unchanged)")
    ap.add_argument("--skip-frontend-build", action="store_true", help="use the existing frontend/dist")
    a = ap.parse_args()
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
        trim(py_dir, [RES / "site/backend", RES / "site/models"])
    stage_app(a.skip_frontend_build)
    py_dir = RES / "python"
    lib = py_dir / ("Lib" if WIN else f"lib/python{PY_VERSION}")
    precompile(python_exe(py_dir), [lib, RES / "site/backend", RES / "site/models", RES / "app"] if not a.app_only
               else [RES / "app"])
    for p in ("python", "site/backend", "site/models", "app"):
        if (RES / p).exists():
            print(f"  {p:14s} {du(RES / p):8.1f} MB")
    print(f"platform {platform.system()} {platform.machine()}; resources in {RES}")


if __name__ == "__main__":
    main()
