"""The engine's C boundary (issues #85, #86): bindings generated from the headers, ABI checks, the pinned ONNX Runtime
and the model files' sha256. Network-free; the compiler / built-library tests skip when those are not on the machine."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "model_server/tools"))
import gen_bindings  # noqa: E402

from app import _cdefs, model_verify, nft2  # noqa: E402
from app._arc_ffi import ffi as arc_ffi  # noqa: E402
from app._arctag_ffi import ffi as tag_ffi  # noqa: E402

LOCK = json.loads((ROOT / "desktop/vendor/libarc/onnxruntime.lock.json").read_text())
SNAPSHOT = Path(__file__).with_name("abi_snapshot.json")
LIBARC = next((p for p in (ROOT / "desktop/build/libarc").glob("*arc.*") if p.suffix in (".dylib", ".so", ".dll")), None) \
    if (ROOT / "desktop/build/libarc").exists() else None


# ------------------------------------------------------------------------------------------------ generated == header
def test_generated_bindings_match_the_headers():
    """app/_arc_ffi.py, _arctag_ffi.py and _cdefs.py are exactly what gen_bindings.py makes from arc.h / arctag.h now:
    a header edit without regenerating fails here (and in the build scripts' --check step)."""
    assert gen_bindings.stale() == [], "run: uv run --project model_server python model_server/tools/gen_bindings.py"


@pytest.mark.parametrize("mod,src", [("_arc_ffi", "app/nft2.py"), ("_arctag_ffi", "app/arctag.py")])
def test_every_function_python_calls_is_declared_in_the_header(mod, src):
    declared = set(re.findall(r"\b(\w+)\s*\(", _cdefs.CDEF[mod]))
    used = set(re.findall(r"\bL\.(arc\w+)\(", (ROOT / "model_server" / src).read_text()))
    assert used and used <= declared, f"called but not in the header: {sorted(used - declared)}"


def test_preprocessor_keeps_integer_defines_and_drops_the_rest():
    cdef, defines = gen_bindings.preprocess(
        '#ifndef X_H\n#define X_H\n#include <stddef.h>\n#ifdef __cplusplus\nextern "C" {\n#endif\n'
        "#if defined(_WIN32) && defined(B)\n#define API __declspec(dllexport)\n#else\n#define API\n#endif\n"
        '#define V 3\n#define NEG (-1)\n#define S "1.0"\n/* a comment */ API int f(void); // more\n'
        "#ifdef __cplusplus\n}\n#endif\n#endif\n")
    assert [x.strip() for x in cdef.split("\n")] == ["#define V 3", "#define NEG -1", "int f(void);", ""]
    assert defines["S"] == '"1.0"'
    with pytest.raises(ValueError):
        gen_bindings.preprocess("#define F(x) (x)\n")


# ------------------------------------------------------------------------------------------------ layouts vs a compiler
def _structs(ffi) -> list[str]:
    typedefs, _, _ = ffi.list_types()
    return [t for t in typedefs if ffi.typeof(t).kind == "struct" and ffi.typeof(t).fields]


@pytest.mark.parametrize("mod,ffi,header", [("_arc_ffi", arc_ffi, "desktop/vendor/libarc/include/arc.h"),
                                             ("_arctag_ffi", tag_ffi, "desktop/vendor/arctag/include/arctag.h")])
def test_struct_layouts_and_constants_match_a_c_compiler(mod, ffi, header, tmp_path):
    """cffi lays the structs out from the declarations; a real compiler reading the real header must agree on every
    sizeof / offsetof and on every integer constant / enum value the binding knows (what ctypes never checked)."""
    cc = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
    if not cc:
        pytest.skip("no C compiler on this machine")
    lines, expect = [], []
    for t in _structs(ffi):
        lines.append(f'printf("{t} %zu\\n", sizeof({t}));')
        expect.append(f"{t} {ffi.sizeof(t)}")
        for f, _ in ffi.typeof(t).fields:
            lines.append(f'printf("{t}.{f} %zu\\n", offsetof({t}, {f}));')
            expect.append(f"{t}.{f} {ffi.offsetof(t, f)}")
    consts = re.findall(r"#define (\w+) (-?\d+)", _cdefs.CDEF[mod])
    enums = [(n, v) for t in ffi.list_types()[0] if ffi.typeof(t).kind == "enum"
             for v, n in ffi.typeof(t).elements.items()]
    for name, val in consts + enums:
        lines.append(f'printf("{name} %lld\\n", (long long)({name}));')
        expect.append(f"{name} {val}")
    src = tmp_path / "layout.c"
    src.write_text(f'#include <stddef.h>\n#include <stdio.h>\n#include "{ROOT / header}"\n'
                   "int main(void) {\n" + "\n".join(lines) + "\nreturn 0;\n}\n")
    exe = tmp_path / "layout"
    subprocess.run([cc, "-std=c11", str(src), "-o", str(exe)], check=True)
    got = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout.split("\n")[:-1]
    assert got == expect


# ------------------------------------------------------------------------------------------------ ABI bump rule
def _decls(cdef: str) -> list[str]:
    """Top-level declarations, whitespace-normalised (a struct with its fields is one)."""
    out, cur, depth = [], "", 0
    for ch in cdef:
        cur += ch
        depth += ch == "{"
        depth -= ch == "}"
        if (ch == ";" and depth == 0) or (ch == "\n" and depth == 0 and cur.strip().startswith("#")):
            if cur.strip():
                out.append(" ".join(cur.split()))
            cur = ""
    return out


def test_abi_version_is_bumped_when_an_existing_declaration_changes():
    """arc.h's bump rules, enforced: against the snapshot of the last ABI, any declaration removed or changed (a struct
    field, a signature, a constant) needs ARC_ABI_VERSION (arctag.h: its MAJOR.MINOR) to move; additions alone do
    not. After a deliberate bump, refresh the snapshot: python model_server/tests/test_bindings.py --snapshot."""
    snap = json.loads(SNAPSHOT.read_text())
    for mod, ver in (("_arc_ffi", _abi("_arc_ffi")), ("_arctag_ffi", _abi("_arctag_ffi"))):
        old, new = snap[mod], _decls(_cdefs.CDEF[mod])
        if ver != old["abi"]:
            continue   # bumped: anything may change (refresh the snapshot)
        gone = [d for d in old["decls"] if d not in new]
        assert not gone, (f"{_cdefs.HEADER[mod]} changed existing declarations without an ABI bump "
                          f"({'ARC_ABI_VERSION' if mod == '_arc_ffi' else 'ARCTAG_VERSION_MAJOR/MINOR'} still "
                          f"{ver}): {gone[:3]}")


def _abi(mod: str) -> str:
    d = _cdefs.DEFINES[mod]
    return d["ARC_ABI_VERSION"] if mod == "_arc_ffi" else f"{d['ARCTAG_VERSION_MAJOR']}.{d['ARCTAG_VERSION_MINOR']}"


# ------------------------------------------------------------------------------------------------ the built library
@pytest.mark.skipif(LIBARC is None, reason="libarc not built (make desktop-libarc)")
def test_built_libarc_reports_the_headers_abi():
    L = nft2.open_library(LIBARC)
    assert L.arc_abi_version() == nft2.ABI_VERSION == int(_cdefs.DEFINES["_arc_ffi"]["ARC_ABI_VERSION"])
    assert arc_ffi.string(L.arc_version()).decode() == json.loads(_cdefs.DEFINES["_arc_ffi"]["ARC_VERSION"])


@pytest.mark.skipif(LIBARC is None, reason="libarc not built (make desktop-libarc)")
def test_a_library_of_another_abi_is_refused_with_a_message(monkeypatch):
    monkeypatch.setattr(nft2, "ABI_VERSION", nft2.ABI_VERSION + 1)
    with pytest.raises(nft2.AbiMismatch, match=r"libarc ABI \d+ .*rebuild libarc"):
        nft2.open_library(LIBARC)


def test_a_library_without_the_abi_call_is_refused():
    """A libarc built before the ABI check (or any other library) has no arc_abi_version(): refused, not crashed."""
    import ctypes.util
    libc = ctypes.util.find_library("c")
    if not libc or sys.platform == "win32":
        pytest.skip("no libc to stand in for an old libarc")
    with pytest.raises(nft2.AbiMismatch, match="no arc_abi_version"):
        nft2.open_library(Path(libc))


# ------------------------------------------------------------------------------------------------ ONNX Runtime pin
def test_onnxruntime_is_pinned_once_and_the_wheel_matches():
    """One version: onnxruntime.lock.json. The Python wheel (embedder, Steer TTS) is pinned to the same in
    pyproject.toml and uv.lock, and libarc's C API headers serve the lock's API version."""
    v = LOCK["version"]
    deps = tomllib.loads((ROOT / "model_server/pyproject.toml").read_text())["project"]["dependencies"]
    assert f"onnxruntime=={v}" in deps
    lock = (ROOT / "model_server/uv.lock").read_text()
    assert re.search(r'name = "onnxruntime"\nversion = "([^"]+)"', lock).group(1) == v
    hdr = (ROOT / "desktop/vendor/libarc/third_party/onnxruntime/include/onnxruntime_c_api.h").read_text()
    assert int(re.search(r"#define ORT_API_VERSION (\d+)", hdr).group(1)) == LOCK["c_api_version"]
    for key, p in LOCK["platforms"].items():
        assert v in p["url"] and p["url"].startswith("https://github.com/microsoft/onnxruntime/releases/download/")
        assert re.fullmatch(r"[0-9a-f]{64}", p["sha256"]) and re.fullmatch(r"[0-9a-f]{64}", p["lib_sha256"]), key
    assert {"darwin-arm64", "windows-x64"} <= set(LOCK["platforms"])          # the two installers


def _pinned_dir(tmp_path: Path, name: str, data: bytes = b"ort") -> Path:
    d = tmp_path / "native" / "onnxruntime"
    d.mkdir(parents=True)
    (d / name).write_bytes(data)
    import hashlib
    (d / "onnxruntime.json").write_text(json.dumps({"version": LOCK["version"], "lib": name,
                                                    "sha256": hashlib.sha256(data).hexdigest()}))
    return d


def test_the_pinned_runtime_next_to_libarc_is_used(monkeypatch, tmp_path):
    monkeypatch.delenv("ARC_ORT_LIB", raising=False)
    monkeypatch.delenv("ARC_ORT_FROM_WHEEL", raising=False)
    d = _pinned_dir(tmp_path, "libonnxruntime.1.32.0.dylib")
    path, info = nft2.resolve_ort(tmp_path / "native" / "libarc.dylib")
    assert path == d / "libonnxruntime.1.32.0.dylib" and info["source"] == "pinned" and info["version"] == LOCK["version"]


def test_windows_multi_config_build_finds_the_runtime_one_folder_up(monkeypatch, tmp_path):
    """Visual Studio puts arc.dll in build\\libarc\\Release\\; the runtime is in build\\libarc\\onnxruntime\\."""
    monkeypatch.delenv("ARC_ORT_LIB", raising=False)
    monkeypatch.delenv("ARC_ORT_FROM_WHEEL", raising=False)
    d = _pinned_dir(tmp_path, "onnxruntime.dll")
    path, _ = nft2.resolve_ort(tmp_path / "native" / "Release" / "arc.dll")
    assert path == d / "onnxruntime.dll"


def test_a_damaged_pinned_runtime_is_refused(monkeypatch, tmp_path):
    monkeypatch.delenv("ARC_ORT_LIB", raising=False)
    monkeypatch.delenv("ARC_ORT_FROM_WHEEL", raising=False)
    d = _pinned_dir(tmp_path, "onnxruntime.dll")
    (d / "onnxruntime.dll").write_bytes(b"something else")
    with pytest.raises(RuntimeError, match="damaged or not the pinned build"):
        nft2.resolve_ort(tmp_path / "native" / "arc.dll")


def test_no_pinned_runtime_and_no_dev_flag_fails_loudly(monkeypatch, tmp_path):
    """The wheel is NOT a silent fallback any more: only ARC_ORT_FROM_WHEEL=1 (dev) uses it."""
    monkeypatch.delenv("ARC_ORT_LIB", raising=False)
    monkeypatch.delenv("ARC_ORT_FROM_WHEEL", raising=False)
    with pytest.raises(RuntimeError, match="ARC_ORT_FROM_WHEEL=1"):
        nft2.resolve_ort(tmp_path / "libarc.dylib")
    monkeypatch.setenv("ARC_ORT_FROM_WHEEL", "1")
    monkeypatch.setattr(nft2, "wheel_ort_library", lambda: tmp_path / "wheel.dylib")
    assert nft2.resolve_ort(tmp_path / "libarc.dylib") == (tmp_path / "wheel.dylib", {"source": "wheel"})


# ------------------------------------------------------------------------------------------------ model sha256 at load
def _asset(tmp_path: Path, managed: bool, state_files_sha: bool = True):
    """An installed asset 'ear' (nft2/a.bin, nft2/b.bin) + a manifest; managed: <assets>/state.json lists it."""
    import hashlib
    assets = tmp_path / "assets"
    home = assets / "ear" if managed else tmp_path / "arc-space"
    (home / "nft2").mkdir(parents=True)
    files = []
    for n, data in (("nft2/a.bin", b"aaaa"), ("nft2/b.bin", b"bbbbbb")):
        (home / n).write_bytes(data)
        files.append({"path": n, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    m = tmp_path / "manifest.json"
    m.write_text(json.dumps({"assets": [{"id": "ear", "sha256": "t" * 64, "version": "3", "files": files}]}))
    if managed:
        rec = {"version": "3", "sha256": "t" * 64,
               "files": files if state_files_sha else [{"path": f["path"], "size": f["size"]} for f in files]}
        (assets / "state.json").write_text(json.dumps({"ear": rec}))
    return home, m


@pytest.fixture
def verify_env(monkeypatch):
    monkeypatch.delenv("ARC_VERIFY", raising=False)
    return monkeypatch


@pytest.mark.parametrize("state_sha", [True, False])
def test_intact_files_verify_from_the_install_record_or_the_manifest(verify_env, tmp_path, state_sha):
    home, m = _asset(tmp_path, managed=True, state_files_sha=state_sha)
    verify_env.setenv("ARC_ASSETS_MANIFEST", str(m))
    r = model_verify.verify_asset("ear", home)
    assert r["verified"] and r["files"] == 2
    assert ("state.json" in r["source"]) == state_sha


def test_a_damaged_app_asset_is_refused_moved_aside_and_asked_for_again(verify_env, tmp_path):
    home, m = _asset(tmp_path, managed=True)
    verify_env.setenv("ARC_ASSETS_MANIFEST", str(m))
    (home / "nft2/b.bin").write_bytes(b"bbbbbX")              # same size: only the sha256 catches it
    with pytest.raises(model_verify.ModelIntegrityError, match=r"damaged: nft2/b\.bin: sha256 .*downloading it again"):
        model_verify.verify_asset("ear", home, "The speech model")
    assert not (home / "nft2/b.bin").exists() and (home / "nft2/b.bin.damaged").exists()   # the app's size check: corrupt
    assert (home / "nft2/a.bin").exists()
    assert (tmp_path / "assets/.want/ear").exists()                                        # main.js watchWanted


def test_a_damaged_dev_folder_is_refused_and_left_alone(verify_env, tmp_path):
    home, m = _asset(tmp_path, managed=False)
    verify_env.setenv("ARC_ASSETS_MANIFEST", str(m))
    (home / "nft2/a.bin").unlink()
    with pytest.raises(model_verify.ModelIntegrityError, match=r"nft2/a\.bin: missing.*make ear-model"):
        model_verify.verify_asset("ear", home)
    assert (home / "nft2/b.bin").exists() and not (tmp_path / "assets/.want").exists()


def test_unknown_versions_load_unverified_and_the_check_can_be_skipped(verify_env, tmp_path):
    home, m = _asset(tmp_path, managed=True, state_files_sha=False)
    j = json.loads(m.read_text())
    j["assets"][0]["sha256"] = "u" * 64                       # the manifest describes another version than installed
    m.write_text(json.dumps(j))
    verify_env.setenv("ARC_ASSETS_MANIFEST", str(m))
    r = model_verify.verify_asset("ear", home)
    assert r["verified"] is False and "not the version" in r["reason"]
    verify_env.setenv("ARC_VERIFY", "off")
    assert model_verify.verify_asset("ear", home) == {"verified": False, "reason": "ARC_VERIFY=off"}


@pytest.mark.parametrize("path", ["desktop/assets.manifest.json", "site/assets/manifest.json"])
def test_the_manifest_has_a_sha256_for_every_model_file(path):
    m = json.loads((ROOT / path).read_text())
    for a in m["assets"]:
        if a["id"] in ("ear", "tagger", "embedder"):
            assert all(re.fullmatch(r"[0-9a-f]{64}", f.get("sha256", "")) for f in a["files"]), a["id"]
            want = model_verify._files_with_sha(a["files"])
            assert want and len(want) == a["n_files"], a["id"]


if __name__ == "__main__" and "--snapshot" in sys.argv:   # refresh after a deliberate ABI bump
    SNAPSHOT.write_text(json.dumps({mod: {"abi": _abi(mod), "decls": _decls(_cdefs.CDEF[mod])}
                                    for mod in ("_arc_ffi", "_arctag_ffi")}, indent=1) + "\n")
    print(f"wrote {SNAPSHOT}")


def test_generated_bindings_are_lf_only(tmp_path):
    """The Windows build runs --check: generation must write LF there too (text mode would write CRLF)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_bindings", Path(__file__).resolve().parents[1] / "tools" / "gen_bindings.py")
    gb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gb)
    for p in gb.generate(tmp_path).values():
        assert b"\r\n" not in p.read_bytes(), p.name
