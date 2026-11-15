"""Structural checks of a Windows Outpost Luna bundle, without Windows. Stdlib only, so it runs anywhere (the Mac
cross-build, or the teammate's Windows build).

    python desktop/scripts/win_bundle_check.py dlls     <resources>              every .dll/.pyd's imports resolve
    python desktop/scripts/win_bundle_check.py manifest <resources> [--out f]   the bundle's manifest (JSON)
    python desktop/scripts/win_bundle_check.py compare  <mac Resources> <win resources>   parity report; exit 1 on a gap
    python desktop/scripts/win_bundle_check.py speech   <win resources>              the WinRT / SAPI speech packages

<resources> is `desktop/resources`, `desktop/dist/win-unpacked/resources`, or an unpacked installer's `resources`.

dlls: reads each PE's import and delay-import tables and resolves every DLL name the way Windows will at run time:
next to the importer, next to python.exe (the application folder, searched for every load), in the folders the
packages add themselves (torch/lib, <pkg>.libs, onnxruntime/capi, ...), or in Windows itself (the in-box list below).
Anything else would fail on a clean PC with "DLL load failed" / WinError 126, the classic case being MSVCP140.dll
on a machine without the Visual C++ Redistributable.

compare: the Mac .app's Contents/Resources against the Windows resources, by area: app code (byte-for-byte, except
the .pyc bytecode), models (sha256 vs desktop/models.lock.json), media, vision assets, the OS-voice engine (and on
Windows its WinRT / SAPI packages), Director weights, the native Arc Tagger library, and the top-level packages of both site folders (platform-specific
packages such as uvloop / colorama are listed, not failed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# In-box on Windows 10 / 11 x64 (System32). api-ms-win-* / ext-ms-* API sets resolve to these.
SYSTEM_DLLS = {d.lower() for d in """
kernel32 kernelbase ntdll user32 gdi32 gdi32full advapi32 shell32 shlwapi ole32 oleaut32 combase rpcrt4 ws2_32 mswsock
msvcrt ucrtbase bcrypt bcryptprimitives crypt32 ncrypt secur32 sspicli wintrust userenv netapi32 iphlpapi dnsapi
winhttp wininet urlmon normaliz psapi dbghelp dbgcore version winmm imm32 comctl32 comdlg32 setupapi cfgmgr32 powrprof
uxtheme dwmapi d3d9 d3d11 d3d12 dxgi dxcore d3dcompiler_47 opengl32 glu32 propsys shcore wldap32 mpr credui
oleacc hid winspool.drv mf mfplat mfreadwrite ksuser avrt msacm32 wtsapi32 authz netutils srvcli wkscli
cryptbase cryptsp mscoree msimg32 usp10 dwrite d2d1 windowscodecs pdh msi imagehlp cabinet
""".split()}


def pe_imports(path: Path) -> list[str]:
    """The DLL names a PE file imports (import table + delay-import table). [] for a file that is not a PE."""
    b = path.read_bytes()
    if b[:2] != b"MZ":
        return []
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    if b[pe:pe + 4] != b"PE\0\0":
        return []
    nsec, opt_size = struct.unpack_from("<H", b, pe + 6)[0], struct.unpack_from("<H", b, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", b, opt)[0]
    dd = opt + (112 if magic == 0x20B else 96)
    secs = []
    for i in range(nsec):
        s = opt + opt_size + 40 * i
        vsize, va, rsize, raw = struct.unpack_from("<IIII", b, s + 8)
        secs.append((va, max(vsize, rsize), raw))

    def off(rva):
        for va, size, raw in secs:
            if va <= rva < va + size:
                return raw + rva - va
        return None

    def cstr(rva):
        o = off(rva)
        return b[o:b.index(b"\0", o)].decode("ascii", "replace") if o is not None else ""

    names = []
    imp_rva = struct.unpack_from("<I", b, dd + 8 * 1)[0]
    if imp_rva and (o := off(imp_rva)) is not None:
        while True:
            oft, _, _, name, ft = struct.unpack_from("<IIIII", b, o)
            if not (oft or name or ft):
                break
            names.append(cstr(name))
            o += 20
    dly_rva = struct.unpack_from("<I", b, dd + 8 * 13)[0]
    if dly_rva and (o := off(dly_rva)) is not None:
        while True:
            attrs, name = struct.unpack_from("<II", b, o)
            if not name:
                break
            names.append(cstr(name))
            o += 32
    return names


def is_system(dll: str) -> bool:
    d = dll.lower()
    return d.startswith(("api-ms-win-", "ext-ms-")) or d.removesuffix(".dll") in SYSTEM_DLLS or d in SYSTEM_DLLS


def check_dlls(res: Path) -> list[tuple[str, str]]:
    """[(importer, missing dll)] for every import that resolves neither in the bundle nor in Windows."""
    pes = [p for p in res.rglob("*") if p.suffix.lower() in (".dll", ".pyd", ".exe") and p.is_file()]
    by_dir: dict[Path, set[str]] = {}
    for p in pes:
        by_dir.setdefault(p.parent, set()).add(p.name.lower())
    app_dir = {p.name.lower() for p in (res / "python").glob("*.dll")}
    # folders packages put on the DLL path themselves (os.add_dll_directory / preloading): torch/lib, *.libs, capi, ...
    pkg_dirs = set()
    for p in pes:
        parts = [x.lower() for x in p.relative_to(res).parts]
        if any(x.endswith(".libs") for x in parts) or "lib" in parts or "capi" in parts or "_soundfile_data" in parts:
            pkg_dirs |= by_dir[p.parent]
    missing = []
    for p in pes:
        for dll in pe_imports(p):
            d = dll.lower()
            if is_system(d) or d in by_dir[p.parent] or d in app_dir or d in pkg_dirs:
                continue
            missing.append((p.relative_to(res).as_posix(), dll))
    return missing


# ------------------------------------------------------------------------------------------------- manifest / compare
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


HASHED = re.compile(r"^(frontend/assets/.+)-[A-Za-z0-9_-]{8}(\.\w+)$")   # Vite's content-hashed bundle names


def files(base: Path, skip_suffix=(".pyc",)) -> dict[str, int]:
    return {p.relative_to(base).as_posix(): p.stat().st_size for p in sorted(base.rglob("*"))
            if p.is_file() and p.suffix not in skip_suffix and p.name != ".DS_Store" and "__pycache__" not in p.parts}


def unhashed(paths) -> dict[str, str]:
    """frontend/assets/index-BQn7G8N-.js -> frontend/assets/index-*.js (two builds of different commits differ there)."""
    return {HASHED.sub(r"\1-*\2", k): k for k in paths}


def top_packages(site: Path) -> set[str]:
    """{"name==version"} from the dist-info folders."""
    out = set()
    for p in site.glob("*.dist-info"):
        name, ver = p.name[: -len(".dist-info")].rsplit("-", 1)
        out.add(f"{name.lower().replace('_', '-')}=={ver}")
    return out


def manifest(res: Path) -> dict:
    app = res / "app"
    m = {
        "app": files(app / "backend") and {f"backend/{k}": v for k, v in files(app / "backend").items()},
        "packages": {s: sorted(top_packages(res / "site" / s)) for s in ("backend", "models") if (res / "site" / s).exists()},
        "models": {k: sha256(res / "models" / k) for k in files(res / "models")} if (res / "models").exists() else {},
        "native": sorted(p.name for p in (res / "native").glob("*")) if (res / "native").exists() else [],
        "python": sorted(p.name for p in (res / "python").iterdir()) if (res / "python").exists() else [],
    }
    m["app"].update({f"model_server/{k}": v for k, v in files(app / "model_server").items()})
    m["app"].update({f"frontend/{k}": v for k, v in files(app / "frontend").items()})
    m["app"]["launch.py"] = (app / "launch.py").stat().st_size if (app / "launch.py").exists() else -1
    return m


# What each area must contain (and so what a Windows build must not lose). Paths under resources/app.
MUST = {
    "Director weights": ["backend/app/director_model/weights.npz", "backend/app/director_model/weights.json"],
    "vision assets": ["frontend/vision/vision_wasm_module_internal.js", "frontend/vision/vision_wasm_module_internal.wasm",
                      "frontend/vision/hand_landmarker.task", "frontend/vision/blaze_face_short_range.tflite"],
    "story / places / clips data": ["backend/data/places.json", "backend/data/index/clips.json", "backend/data/clip_loudness.json"],
    "OS voice engine": ["model_server/app/tts_os.py", "model_server/app/os_voices.py"],
    "voice pack (Siri Voice 1 clips)": ["model_server/app/voice_pack.py", "backend/data/voice_pack/lines.json",
                                        "backend/data/voice_pack/index.json"],
    "NASA video catalog": ["backend/data/video/catalog.json"],
    "Settings reset (docs/RESET.md)": ["backend/app/reset.py"],
    "NASA media (Moon map)": ["backend/data/media/img/moon4k.jpg"],
    "crew clip time map": ["backend/data/media/trim.json"],
    "frontend": ["frontend/index.html"],
    "launcher": ["launch.py"],
}


def compare(mac: Path, win: Path) -> int:
    mm, wm = manifest(mac), manifest(win)
    bad = 0

    def row(area, ok, detail):
        nonlocal bad
        bad += not ok
        print(f"  {'OK  ' if ok else 'GAP '} {area:30s} {detail}")

    print(f"mac: {mac}\nwin: {win}")
    for area, must in MUST.items():
        miss = [m for m in must if m not in wm["app"]]
        row(area, not miss, "all present" if not miss else f"missing {miss}")
    speech = speech_packages(win / "site/models")
    row("Windows speech (WinRT + SAPI + Steer)", all(speech.values()), ", ".join(f"{k} {'ok' if v else 'MISSING'}" for k, v in speech.items()))
    st = steer_model(win)
    row("Steer TTS Edge model", all(st.values()), "all present" if all(st.values()) else f"missing {[k for k, v in st.items() if not v]}")
    media = [k for k in wm["app"] if k.startswith("backend/data/media/audio/")]
    row("NASA crew clips", len(media) == len([k for k in mm["app"] if k.startswith("backend/data/media/audio/")]),
        f"{len(media)} clips (mac {len([k for k in mm['app'] if k.startswith('backend/data/media/audio/')])})")
    mu, wu = unhashed(mm["app"]), unhashed(wm["app"])
    only_mac = sorted(set(mu) - set(wu))
    only_win = sorted(set(wu) - set(mu))
    # a different size is information, not a gap: the Mac app may be a build of another commit
    diff = sorted(k for k in set(mu) & set(wu) if mm["app"][mu[k]] != wm["app"][wu[k]])
    row("app files (vs mac)", not only_mac, f"{len(wm['app'])} files; only on mac {len(only_mac)} {only_mac[:6]}; "
        f"only on win {len(only_win)} {only_win[:6]}; same file, different size {len(diff)} {diff[:6]}")
    lock = json.loads((ROOT / "desktop/models.lock.json").read_text(encoding="utf-8"))
    lock_bad = sorted(k for k in set(lock) | set(wm["models"]) if lock.get(k, {}).get("sha256") != wm["models"].get(k))
    row("models vs models.lock.json", not lock_bad, f"{len(wm['models'])} files, sha256 " + ("all match" if not lock_bad else f"differ: {lock_bad[:6]}"))
    row("models vs mac", mm["models"] == wm["models"], "identical sha256 set" if mm["models"] == wm["models"] else "differ")
    row("native Arc Tagger", "arctag.dll" in wm["native"], f"win {wm['native']}, mac {mm['native']}")
    row("embedded python", "python.exe" in wm["python"] and "Lib" in wm["python"], f"win {len(wm['python'])} entries incl. python.exe, Lib, DLLs")
    for s in ("backend", "models"):
        av = dict(x.split("==") for x in mm["packages"].get(s, []))
        bv = dict(x.split("==") for x in wm["packages"].get(s, []))
        a, b = set(av), set(bv)
        ver = sorted(f"{k} {av[k]}/{bv[k]}" for k in a & b if av[k] != bv[k])
        row(f"site/{s} packages", bool(b) and not (a - b - PLATFORM_ONLY) and not ver,
            f"{len(b)} (mac {len(a)}), same versions{'' if not ver else ' EXCEPT ' + str(ver[:6])}; "
            f"mac-only {sorted(a - b)}; win-only {sorted(b - a)}")
    print(f"{'PARITY OK' if not bad else f'{bad} GAP(S)'}")
    return 1 if bad else 0


# Packages a lock pulls in on one OS only (environment markers): a difference here is expected, not a gap.
PLATFORM_ONLY = {"uvloop", "colorama", "pywin32", "win32-setctime", "comtypes", "winrt-runtime",
                 "winrt-windows-media-speechsynthesis", "winrt-windows-media-core", "winrt-windows-storage-streams",
                 "winrt-windows-foundation", "winrt-windows-foundation-collections"}
# The Windows OS-voice engine (model_server/app/tts_os.py): pywinrt's native modules + comtypes for the SAPI fallback.
SPEECH_MODULES = {"WinRT runtime": "winrt/_winrt.*.pyd",
                  "WinRT SpeechSynthesis": "winrt/_winrt_windows_media_speechsynthesis.*.pyd",
                  "WinRT Media.Core (word cues)": "winrt/_winrt_windows_media_core.*.pyd",
                  "WinRT Storage.Streams": "winrt/_winrt_windows_storage_streams.*.pyd",
                  "WinRT Foundation": "winrt/_winrt_windows_foundation.*.pyd",
                  "WinRT Foundation.Collections": "winrt/_winrt_windows_foundation_collections.*.pyd",
                  "comtypes (SAPI)": "comtypes/__init__.py",
                  "steertts_edge (Steer TTS, the optional engine)": "steertts_edge/__init__.py"}
# The bundled Steer TTS Edge model (desktop/scripts/gather_models.py STEER_FILES) + its licence files.
STEER_MODEL_FILES = ("config.json", "director.bin", "voices.json", "voices.safetensors", "onnx/enc.onnx", "onnx/dec.onnx",
                     "onnx/voc.onnx", "front/gru.npz", "LICENSE", "NOTICE")


def steer_model(res: Path) -> dict[str, bool]:
    d = res / "models/steer-tts-edge"
    return {f"Steer model {f}": (d / f).is_file() for f in STEER_MODEL_FILES}


def speech_packages(site: Path) -> dict[str, bool]:
    return {k: any(site.glob(g)) for k, g in SPEECH_MODULES.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("dlls", "manifest", "compare", "speech"))
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    if a.cmd == "dlls":
        res = a.paths[0]
        miss = check_dlls(res)
        n = sum(1 for p in res.rglob("*") if p.suffix.lower() in (".dll", ".pyd") and p.is_file())
        for importer, dll in miss:
            print(f"  MISSING {dll:28s} imported by {importer}")
        print(f"{n} DLL/PYD files; {'every import resolves' if not miss else f'{len(miss)} unresolved import(s)'}")
        sys.exit(1 if miss else 0)
    if a.cmd == "speech":
        got = {**speech_packages(a.paths[0] / "site/models"), **steer_model(a.paths[0])}
        for k, v in got.items():
            print(f"  {'OK  ' if v else 'MISS'} {k}")
        sys.exit(0 if all(got.values()) else 1)
    if a.cmd == "manifest":
        m = json.dumps(manifest(a.paths[0]), indent=1, sort_keys=True)
        a.out.write_text(m) if a.out else print(m)
        return
    sys.exit(compare(a.paths[0], a.paths[1]))


if __name__ == "__main__":
    main()
