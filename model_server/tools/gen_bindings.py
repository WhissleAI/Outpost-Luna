"""Generate the model server's C bindings from the C headers (issue #86): cffi, out-of-line ABI mode.

    python model_server/tools/gen_bindings.py            # rewrite model_server/app/_arc_ffi.py, _arctag_ffi.py, _cdefs.py
    python model_server/tools/gen_bindings.py --check    # exit 1 when they differ from what the headers give (build step)
    python model_server/tools/gen_bindings.py --check --lib desktop/resources/native/libarc.dylib   # + the built ABI

Each header is preprocessed here (comments, include guards, `extern "C"`, export macros and `#ifdef __cplusplus` go;
integer #defines stay) and fed to `ffi.cdef()`; `ffi.set_source(name, None)` + `emit_python_code()` writes a pure
Python module holding the parsed declarations. At run time `app/nft2.py` / `app/arctag.py` import it and `ffi.dlopen()`
the shipped library: no compiler, no header and no pycparser on the user's machine, only `_cffi_backend` (cffi's wheel,
already in the app for soundfile). Struct layouts are computed by cffi from the declarations exactly as a C compiler
lays them out for the platform; model_server/tests/test_bindings.py checks that against a real compiler when there is
one, and that the generated files match the headers byte for byte.

Why cffi out-of-line ABI mode (not API mode / nanobind): API mode and nanobind compile a CPython extension per
platform and Python version, i.e. a second native build on the Windows collaborator's machine (MSVC + Python headers)
next to the CMake one, for no gain here: the libraries already have a plain C ABI and the calls are coarse (one per
utterance). ABI mode keeps the build exactly as it is, and still makes the header the single source of truth.
stdlib + cffi (== the version pinned in model_server/pyproject.toml; the generated code depends on it).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "model_server/app"
HEADERS = {   # module -> header
    "_arc_ffi": ROOT / "desktop/vendor/libarc/include/arc.h",
    "_arctag_ffi": ROOT / "desktop/vendor/arctag/include/arctag.h",
}
CDEFS = APP / "_cdefs.py"


def preprocess(text: str) -> tuple[str, dict[str, str]]:
    """The declarations of a public C header as cffi's cdef takes them, plus its #define values (raw text).

    A deliberately small preprocessor for these two headers: conditionals are evaluated with nothing predefined
    (no __cplusplus, no _WIN32: the export macros then expand to nothing), object-like macros with an empty body are
    substituted, `#define NAME <integer>` is kept as a cffi constant, any other #define is reported in the dict only.
    Anything it does not understand raises, so a header change that needs more fails loudly here."""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    defined: dict[str, str] = {}
    empty: set[str] = set()
    out: list[str] = []
    stack: list[tuple[bool, bool]] = []   # (this branch active, some branch of this #if taken)

    def active() -> bool:
        return all(a for a, _ in stack)

    def cond(expr: str) -> bool:
        e = re.sub(r"defined\s*\(\s*(\w+)\s*\)|defined\s+(\w+)",
                   lambda m: "1" if (m.group(1) or m.group(2)) in defined else "0", expr)
        e = e.replace("&&", " and ").replace("||", " or ")
        e = re.sub(r"!(?!=)", " not ", e)
        if not re.fullmatch(r"[\s01()andortn]*", e):
            raise ValueError(f"#if expression not understood: {expr!r}")
        return bool(eval(e, {"__builtins__": {}}))   # noqa: S307 (0/1/and/or/not/parens only, checked above)

    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            d = re.match(r"#\s*(\w+)\s*(.*)", s)
            kw, rest = d.group(1), d.group(2).strip()
            if kw in ("ifdef", "ifndef"):
                on = (rest in defined) == (kw == "ifdef")
                stack.append((on, on))
            elif kw == "if":
                on = cond(rest)
                stack.append((on, on))
            elif kw == "elif":
                _, taken = stack.pop()
                on = not taken and cond(rest)
                stack.append((on, taken or on))
            elif kw == "else":
                _, taken = stack.pop()
                stack.append((not taken, True))
            elif kw == "endif":
                stack.pop()
            elif not active():
                continue
            elif kw == "include":
                if rest not in ("<stddef.h>", "<stdint.h>"):
                    raise ValueError(f"#include {rest} not supported in a public header")
            elif kw == "define":
                m = re.match(r"(\w+)(\(.*?\))?\s*(.*)", rest)
                name, args, body = m.group(1), m.group(2), m.group(3).strip()
                if args:
                    raise ValueError(f"function-like macro {name} not supported in a public header")
                defined[name] = body
                if not body:
                    empty.add(name)
                elif re.fullmatch(r"\(?\s*-?\s*\d+\s*\)?", body):
                    out.append(f"#define {name} {int(body.strip('() ').replace(' ', ''))}")
            else:
                raise ValueError(f"#{kw} not supported in a public header")
            continue
        if not active():
            continue
        if re.fullmatch(r'\s*extern\s+"C"\s*\{\s*|\s*\}\s*', line):
            continue
        for name in empty:
            line = re.sub(rf"\b{name}\b\s*", "", line)
        if line.strip():
            out.append(line.rstrip())
    if stack:
        raise ValueError("unbalanced #if / #endif")
    return "\n".join(out) + "\n", {k: v for k, v in defined.items() if v}


def generate(out_dir: Path) -> dict[str, Path]:
    """Write <module>.py for every header and _cdefs.py into out_dir; returns {name: path}."""
    import cffi

    files: dict[str, Path] = {}
    meta = ['"""Generated by model_server/tools/gen_bindings.py from the C headers: do not edit (regenerate instead).',
            "",
            "CDEF: what each binding module was generated from (the preprocessed header). HEADER_SHA256: the header's",
            'bytes. DEFINES: every #define with a value, as text (ARC_VERSION, ARCTAG_VERSION_MAJOR, ...)."""', "",
            f"CFFI_VERSION = {cffi.__version__!r}", "CDEF = {}", "HEADER = {}", "HEADER_SHA256 = {}", "DEFINES = {}"]
    for mod, hdr in HEADERS.items():
        raw = hdr.read_bytes()
        cdef, defines = preprocess(raw.decode("utf-8"))
        ffi = cffi.FFI()
        ffi.cdef(cdef)
        ffi.set_source(f"app.{mod}", None)
        p = out_dir / f"{mod}.py"
        with contextlib.redirect_stdout(io.StringIO()):   # cffi prints "generating <path>"
            ffi.emit_python_code(str(p))
        p.write_text(f"# Generated by model_server/tools/gen_bindings.py from {hdr.relative_to(ROOT).as_posix()}: do not edit.\n"
                     + p.read_text())
        files[mod] = p
        meta += [f"CDEF[{mod!r}] = {cdef!r}", f"HEADER[{mod!r}] = {hdr.relative_to(ROOT).as_posix()!r}",
                 f"HEADER_SHA256[{mod!r}] = {hashlib.sha256(raw).hexdigest()!r}", f"DEFINES[{mod!r}] = {defines!r}"]
    (out_dir / CDEFS.name).write_text("\n".join(meta) + "\n")
    files["_cdefs"] = out_dir / CDEFS.name
    return files


def stale() -> list[str]:
    """The generated files that differ from what the headers give now ([] when up to date)."""
    with tempfile.TemporaryDirectory() as t:
        got = generate(Path(t))
        return [f"model_server/app/{p.name}" for p in got.values()
                if not (APP / p.name).exists() or (APP / p.name).read_bytes() != p.read_bytes()]


def check_lib(lib: Path) -> str | None:
    """None when the built libarc reports the header's ARC_ABI_VERSION, else the problem (ctypes only: the build
    machine's own library, before packaging)."""
    import ctypes
    import os

    want = int(preprocess(HEADERS["_arc_ffi"].read_text(encoding="utf-8"))[1]["ARC_ABI_VERSION"])
    if sys.platform == "win32":
        os.add_dll_directory(str(lib.resolve().parent))
        L = ctypes.CDLL(str(lib), winmode=0)
    else:
        L = ctypes.CDLL(str(lib))
    try:
        got = L.arc_abi_version()
    except AttributeError:
        return f"{lib}: no arc_abi_version() (built from an older arc.h)"
    if got != want:
        return f"{lib}: ABI {got}, arc.h says {want}"
    print(f"{lib}: ABI {got} (matches arc.h)")
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail (exit 1) when the generated bindings are stale")
    ap.add_argument("--lib", type=Path, action="append", default=[],
                    help="also check a built libarc's arc_abi_version() against arc.h (repeatable)")
    a = ap.parse_args()
    for lib in a.lib:
        bad = check_lib(lib)
        if bad:
            print(bad, file=sys.stderr)
            return 1
    if a.check:
        bad = stale()
        if bad:
            print(f"C bindings out of date with the headers: {bad}\n  regenerate: uv run --project model_server "
                  "python model_server/tools/gen_bindings.py (and bump ARC_ABI_VERSION in arc.h if a struct or "
                  "signature changed)", file=sys.stderr)
            return 1
        print("C bindings match arc.h and arctag.h")
        return 0
    for p in generate(APP).values():
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
