"""Structural checks of a Windows Outpost Luna bundle, without Windows. Stdlib only, so it runs anywhere (the Mac
cross-build, or the teammate's Windows build).

    python desktop/scripts/win_bundle_check.py dlls     <resources>              every .dll/.pyd's imports resolve
    python desktop/scripts/win_bundle_check.py manifest <resources> [--out f]   the bundle's manifest (JSON)
    python desktop/scripts/win_bundle_check.py compare  <mac Resources> <win resources>   parity report; exit 1 on a gap
    python desktop/scripts/win_bundle_check.py speech   <win resources>              the WinRT / SAPI speech packages
    python desktop/scripts/win_bundle_check.py runtime  <win resources>              every runtime file the app needs

<resources> is `desktop/resources`, `desktop/dist/win-unpacked/resources`, or an unpacked installer's `resources`.

dlls: reads each PE's import and delay-import tables and resolves every DLL name the way Windows will at run time:
next to the importer, next to python.exe (the application folder, searched for every load), in the folders the
packages add themselves (torch/lib, <pkg>.libs, onnxruntime/capi, ...), or in Windows itself (the in-box list below).
Anything else would fail on a clean PC with "DLL load failed" / WinError 126, the classic case being MSVCP140.dll
on a machine without the Visual C++ Redistributable.

runtime: one Windows tree on its own (no Mac app needed): every MUST file below, the embedded python.exe + Visual C++
runtime, arctag.dll and arc.dll (libarc, the ear) + the pinned onnxruntime.dll it loads by path
(native/onnxruntime/, at its sha256), no bundled models (0.3: they
are first-run assets) and a usable resources/assets.manifest.json (https download + sha256 + file list for every
asset), a valid NASA video catalog, the speech packages (WinRT, SAPI, the Steer runtime), and the Electron shell inside
app.asar (main, supervisor, reset, keys, permissions, the grown-up gate, the splash, the first-run screen, assets and
updates). The build scripts run it in step 8.

compare: the Mac .app's Contents/Resources against the Windows resources, by area: app code (byte-for-byte, except
the .pyc bytecode), the first-run asset manifest (no models / crew audio / voice clips bundled: they download on first
launch, desktop/assets.manifest.json), media, vision assets, the OS-voice engine (and on
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


VC_RUNTIME = {"msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll"}


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
    # the pinned onnxruntime.dll (native/onnxruntime/) takes the Visual C++ runtime from python.exe's folder (the
    # application folder, searched for every load); checking a native/ folder on its own, assume it is there
    native_only = not (res / "python").exists()
    missing = []
    for p in pes:
        for dll in pe_imports(p):
            d = dll.lower()
            if is_system(d) or d in by_dir[p.parent] or d in app_dir or d in pkg_dirs:
                continue
            if native_only and p.parent.name.lower() == "onnxruntime" and d in VC_RUNTIME:
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
    "Director weights": ["backend/app/director_model/weights.npz", "backend/app/director_model/weights.json",
                         "backend/app/director_model/weights_r10.npz", "backend/app/director_model/weights_r10.json"],
    "vision assets": ["frontend/vision/vision_wasm_module_internal.js", "frontend/vision/vision_wasm_module_internal.wasm",
                      "frontend/vision/hand_landmarker.task", "frontend/vision/blaze_face_short_range.tflite"],
    "story / places / clips data": ["backend/data/places.json", "backend/data/index/clips.json", "backend/data/clip_loudness.json"],
    "OS voice engine": ["model_server/app/tts_os.py", "model_server/app/os_voices.py"],
    "voice pack (manifest; clips are a first-run asset)": ["model_server/app/voice_pack.py",
                                                           "backend/data/voice_pack/lines.json"],
    "NASA video catalog + downloader": ["backend/data/video/catalog.json", "backend/app/video.py"],
    "ear (libarc binding) + Steer engine": ["model_server/app/nft2.py", "model_server/app/arc_ear.py",
                                            "model_server/app/tts_steer.py", "model_server/app/_arc_ffi.py",
                                            "model_server/app/_arctag_ffi.py", "model_server/app/_cdefs.py",
                                            "model_server/app/model_verify.py"],
    "first-run assets API": ["backend/app/assets_api.py"],
    "NASA physics tables (docs/PHYSICS.md)": ["backend/data/physics/physics.json", "backend/app/mission/physics.py"],
    "Settings reset (docs/RESET.md)": ["backend/app/reset.py"],
    "NASA media (Moon map)": ["backend/data/media/img/moon4k.jpg"],
    "Moon map layers (docs/OPEN_DATA.md)": ["backend/data/courses/moon/library.json", "backend/data/courses/moon/media/moon_age.jpg",
                                            "backend/data/courses/moon/media/moon_height.jpg"],
    "frontend": ["frontend/index.html"],
    "launcher": ["launch.py"],
}


# The Electron shell's files, inside resources/app.asar (electron-builder.yml `files: main/**/*`).
SHELL_FILES = ("package.json", "main/main.js", "main/supervisor.js", "main/permissions.js", "main/keys.js", "main/reset.js",
               "main/gate.js", "main/gate.html", "main/splash.html", "main/assets.js", "main/updates.js",
               "main/firstrun.html", "main/firstrun-preload.js",
               "main/firstrun_progress.js", "main/fonts/inter-latin-wght-normal.woff2")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
PY_FILES = ("python.exe", "python311.dll", "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "Lib", "DLLs")


def asar_files(asar: Path) -> set[str]:
    """The file paths inside an Electron asar archive (its JSON header; stdlib only)."""
    with open(asar, "rb") as f:
        head = f.read(16)
        if len(head) < 16:
            return set()
        n = struct.unpack_from("<I", head, 12)[0]          # pickle: [4][header size][payload size][json length] json
        tree = json.loads(f.read(n).decode("utf-8"))
    out: set[str] = set()

    def walk(node, pre):
        for name, sub in node.get("files", {}).items():
            walk(sub, pre + name + "/") if "files" in sub else out.add(pre + name)
    walk(tree, "")
    return out


def pinned_ort(d: Path) -> tuple[bool, str]:
    """The pinned onnxruntime.dll next to arc.dll (desktop/vendor/libarc/onnxruntime.lock.json): present, and at the
    sha256 its onnxruntime.json gives (the model server refuses it otherwise)."""
    try:
        meta = json.loads((d / "onnxruntime.json").read_text(encoding="utf-8"))
        dll = d / meta["lib"]
        ok = dll.is_file() and sha256(dll) == meta["sha256"]
        return ok, f"{dll.name} {meta['version']} " + ("sha256 ok" if ok else "MISSING or sha256 mismatch")
    except (OSError, ValueError, KeyError) as e:
        return False, f"native/onnxruntime/onnxruntime.json unreadable: {e}"


def runtime(res: Path) -> dict[str, tuple[bool, str]]:
    """{check: (ok, detail)} for one Windows resources tree."""
    app = res / "app"
    out: dict[str, tuple[bool, str]] = {}
    for area, must in MUST.items():
        miss = [m for m in must if not (app / m).is_file()]
        out[area] = (not miss, "all present" if not miss else f"missing {miss}")
    miss = [f for f in PY_FILES if not (res / "python" / f).exists()]
    out["embedded python + VC++ runtime"] = (not miss, "python.exe, python311.dll, VC++ DLLs" if not miss else f"missing {miss}")
    nat = {n: (res / "native" / n).is_file() for n in ("arctag.dll", "arc.dll")}
    out["native Arc Tagger + libarc (the ear)"] = (all(nat.values()), ", ".join(f"{n} {'ok' if v else 'MISSING'}" for n, v in nat.items()))
    out["ONNX Runtime DLL (libarc loads it by path)"] = pinned_ort(res / "native/onnxruntime")
    models = res / "models"
    out["no bundled models (0.3: first-run assets)"] = (not models.exists(), "none" if not models.exists() else "resources/models still there")
    try:
        m = json.loads((res / "assets.manifest.json").read_text(encoding="utf-8"))
        bad, req, opt = [], 0, 0
        for x in m["assets"]:
            if not SHA_RE.match(str(x.get("sha256", ""))) or not x.get("files"):
                bad.append(f"{x.get('id')}: sha256/files")
            src = x.get("url") or (x.get("fallback") or {}).get("url") or (x.get("fallback") or {}).get("base")
            if not (src and str(src).startswith("https://")):
                bad.append(f"{x.get('id')}: no https download")
            if x.get("required"):
                req += int(x.get("size", 0))
            else:
                opt += int(x.get("size", 0))
        ids = [x["id"] for x in m["assets"]]
        out["first-run asset manifest"] = (not bad and bool(req), f"{len(ids)} assets {ids}; required {req / 1e6:.0f} MB, "
                                           f"optional {opt / 1e6:.0f} MB" + (f"; problems {bad}" if bad else ""))
    except (OSError, ValueError, KeyError, TypeError) as e:
        out["first-run asset manifest"] = (False, f"resources/assets.manifest.json unreadable: {e}")
    try:
        cat = json.loads((app / "backend/data/video/catalog.json").read_text(encoding="utf-8"))
        items = cat if isinstance(cat, list) else cat.get("videos", cat.get("items", []))
        srcs = sorted({v.get("source") for v in items})
        out["NASA video catalog parses"] = (bool(items), f"{len(items)} videos, sources {srcs}")
    except (OSError, ValueError, AttributeError) as e:
        out["NASA video catalog parses"] = (False, f"catalog.json unreadable: {e}")
    asar = res / "app.asar"
    have = asar_files(asar) if asar.is_file() else None
    if have is None:
        out["Electron shell (app.asar)"] = (False, "no app.asar (point at dist/win-unpacked/resources)")
    else:
        miss = [f for f in SHELL_FILES if f not in have]
        out["Electron shell (app.asar)"] = (not miss, f"{len(have)} files" + (f"; missing {miss}" if miss else
                                            ": main, supervisor, permissions, keys, reset, grown-up gate, splash, first run, assets, updates"))
        tests = sorted(f for f in have if f.endswith(".test.js"))
        out["no test files in the shell"] = (not tests, "none" if not tests else str(tests[:4]))
    for k, v in speech_packages(res / "site/models").items():
        out[f"speech: {k}"] = (v, "present" if v else "MISSING")
    return out


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
    row("Windows speech (WinRT + SAPI + Steer runtime)", all(speech.values()), ", ".join(f"{k} {'ok' if v else 'MISSING'}" for k, v in speech.items()))
    row("first-run asset manifest", (win / "assets.manifest.json").exists(),
        "resources/assets.manifest.json " + ("present" if (win / "assets.manifest.json").exists() else "MISSING"))
    mu, wu = unhashed(mm["app"]), unhashed(wm["app"])
    only_mac = sorted(set(mu) - set(wu))
    only_win = sorted(set(wu) - set(mu))
    # a different size is information, not a gap: the Mac app may be a build of another commit
    diff = sorted(k for k in set(mu) & set(wu) if mm["app"][mu[k]] != wm["app"][wu[k]])
    row("app files (vs mac)", not only_mac, f"{len(wm['app'])} files; only on mac {len(only_mac)} {only_mac[:6]}; "
        f"only on win {len(only_win)} {only_win[:6]}; same file, different size {len(diff)} {diff[:6]}")
    row("no bundled models", not wm["models"], "none (first-run assets)" if not wm["models"] else f"{len(wm['models'])} files still bundled")
    row("native Arc Tagger + libarc", {"arctag.dll", "arc.dll"} <= set(wm["native"]), f"win {wm['native']}, mac {mm['native']}")
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
def speech_packages(site: Path) -> dict[str, bool]:
    return {k: any(site.glob(g)) for k, g in SPEECH_MODULES.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("dlls", "manifest", "compare", "speech", "runtime"))
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
        got = speech_packages(a.paths[0] / "site/models")   # the Steer MODEL is an on-demand asset on 0.3, not bundled
        for k, v in got.items():
            print(f"  {'OK  ' if v else 'MISS'} {k}")
        sys.exit(0 if all(got.values()) else 1)
    if a.cmd == "runtime":
        got = runtime(a.paths[0])
        for k, (ok, detail) in got.items():
            print(f"  {'OK  ' if ok else 'MISS'} {k:36s} {detail}")
        bad = sum(not ok for ok, _ in got.values())
        print("RUNTIME OK" if not bad else f"{bad} runtime check(s) failed")
        sys.exit(1 if bad else 0)
    if a.cmd == "manifest":
        m = json.dumps(manifest(a.paths[0]), indent=1, sort_keys=True)
        a.out.write_text(m) if a.out else print(m)
        return
    sys.exit(compare(a.paths[0], a.paths[1]))


if __name__ == "__main__":
    main()
