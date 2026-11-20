"""The bundle's bytecode (build_python.precompile / bytecode_problems) and the children's no-write rule:

    uv run --no-project --with pytest python -m pytest -q desktop/tests

0.4.x wrote .pyc into the signed app at first launch (python/lib/python3.11/re/__pycache__/...): the compiler's own
start-up imports had left TIMESTAMP .pyc that compileall then skipped, and they went stale once installed.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

DESK = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bp = load("desktop_build_python_bundle", DESK / "scripts/build_python.py")
TAG = sys.implementation.cache_tag


def _tree(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/__init__.py").write_text("X = 1\n")
    (tmp_path / "pkg/mod.py").write_text("import re\nY = re.compile('a')\n")
    (tmp_path / "pkg/py2_only.py").write_text("print 'old'\n")    # not valid Python 3: never imported, no .pyc
    return tmp_path


def test_missing_and_timestamp_pyc_are_problems(tmp_path):
    root = _tree(tmp_path)
    assert sorted(p.name for p in bp.bytecode_problems([root], TAG)) == ["__init__.py", "mod.py"]
    subprocess.run([sys.executable, "-m", "compileall", "-q", str(root)], check=False)    # timestamp .pyc
    assert bp.pyc_flags(root / "pkg/__pycache__" / f"mod.{TAG}.pyc") == 0
    assert sorted(p.name for p in bp.bytecode_problems([root], TAG)) == ["__init__.py", "mod.py"]


def test_precompile_forces_unchecked_hash_over_stale_timestamp_pyc(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    subprocess.run([sys.executable, "-m", "compileall", "-q", str(root)], check=False)    # what the old build left
    monkeypatch.setattr(bp, "PYC_TAG", TAG)
    bp.precompile(Path(sys.executable), [root])                                            # exits on any problem
    assert bp.pyc_flags(root / "pkg/__pycache__" / f"mod.{TAG}.pyc") == 1
    assert bp.bytecode_problems([root], TAG) == []


def test_unchecked_hash_bytecode_survives_a_source_mtime_change(tmp_path, monkeypatch):
    """An install that resets mtimes must not make the bundle's bytecode stale (nothing to rewrite)."""
    root = _tree(tmp_path)
    monkeypatch.setattr(bp, "PYC_TAG", TAG)
    bp.precompile(Path(sys.executable), [root])
    pyc = root / "pkg/__pycache__" / f"mod.{TAG}.pyc"
    before = pyc.read_bytes()
    os.utime(root / "pkg/mod.py", (1, 1))
    env = {**os.environ, "PYTHONPATH": str(root)}
    env.pop("PYTHONDONTWRITEBYTECODE", None)        # even a run that MAY write bytecode finds nothing stale
    env.pop("PYTHONPYCACHEPREFIX", None)
    out = subprocess.run([sys.executable, "-v", "-c", "import pkg.mod"], env=env, capture_output=True, text=True)
    assert out.returncode == 0
    assert "bytecode is stale for 'pkg.mod'" not in out.stderr
    assert pyc.read_bytes() == before


def test_launch_never_writes_bytecode():
    src = (DESK / "runtime/launch.py").read_text()
    assert "sys.dont_write_bytecode = True" in src
    assert "PYTHONDONTWRITEBYTECODE: \"1\"" in (DESK / "main/supervisor.js").read_text()


def test_release_check_runs_the_bundle_python_without_writing_bytecode():
    src = (DESK / "scripts/release_check.py").read_text()
    assert src.count('"PYTHONDONTWRITEBYTECODE": "1"') >= 2      # the smoke.py run and the legacy model server
    assert "codesign_after_run" in src


def test_trim_drops_the_model_servers_unused_packages_only(tmp_path, monkeypatch):
    monkeypatch.setattr(bp, "WIN", False)
    py = tmp_path / "python"
    (py / f"lib/python{bp.PY_VERSION}").mkdir(parents=True)
    models, backend = tmp_path / "site/models", tmp_path / "site/backend"
    keep = ["onnxruntime/capi/onnxruntime_pybind11_state.so", "onnxruntime/capi/onnxruntime.dll", "scipy/signal/x.py",
            "scipy/stats/x.py", "scipy/optimize/x.py", "steertts_edge/ort.py", "tokenizers/__init__.py"]
    drop = ["onnxruntime/capi/libonnxruntime.1.32.0.dylib", "huggingface_hub/__init__.py",
            "huggingface_hub-2.4.0.dist-info/METADATA", "fsspec/core.py", "filelock/__init__.py", "tqdm/std.py",
            "google/protobuf/x.py", "protobuf-7.36.2.dist-info/METADATA", "scipy/io/x.py", "scipy/odr/x.py",
            "scipy/fftpack/x.py", "scipy/cluster/x.py", "scipy/misc/x.py", "scipy/differentiate/x.py"]
    for f in keep + drop:
        (models / f).parent.mkdir(parents=True, exist_ok=True)
        (models / f).write_bytes(b"x")
    (backend / "tqdm").mkdir(parents=True)            # another site keeps what it has
    (backend / "tqdm/std.py").write_bytes(b"x")
    bp.trim(py, [backend, models])
    assert [f for f in keep if not (models / f).exists()] == []
    assert [f for f in drop if (models / f).exists()] == []
    assert (backend / "tqdm/std.py").exists()


def test_stage_app_leaves_the_video_work_folder_out(tmp_path):
    data = tmp_path / "backend/data"
    for f in ("video/catalog.json", "video/local/pack/ltv.mp4", "video/local/diy_crater_nasa.mp4", "voice_pack/lines.json",
              "voice_pack/clips/a.mp3", "media/audio/x.mp3", "places.json", "mission/local/keep.json"):
        (data / f).parent.mkdir(parents=True, exist_ok=True)
        (data / f).write_bytes(b"x")
    out = tmp_path / "out"
    shutil.copytree(data, out, ignore=bp.data_ignore)
    got = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    assert got == ["mission/local/keep.json", "places.json", "video/catalog.json", "voice_pack/lines.json"]
