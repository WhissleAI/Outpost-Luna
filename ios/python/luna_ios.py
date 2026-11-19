"""The iPad app's backend, run inside the app's own process (embedded CPython, docs/IPAD.md).

The Swift shell (ios/OutpostLuna/PythonHost.m) starts the interpreter on a background thread and calls `main()` with
the app's folders in the environment. This is the iOS twin of desktop/runtime/launch.py: the same backend, the same
built frontend at /, the same local guard, bound to 127.0.0.1 only (never the LAN).

What differs from the desktop:
  * one process: no model server child. The ear and the OS voice live in the shell (the voice is the page's
    speechSynthesis, which WKWebView runs on AVSpeechSynthesizer); TTS_ENGINE=deepgram with no key makes /api/tts
    answer 503 {"fallback": "browser"} at once, so the page uses that voice from the first line.
  * the port is picked here (a free loopback port), then written to $LUNA_PORT_FILE for the shell to read.
  * no network after install: video prefetch off, every cloud key dropped.
"""
from __future__ import annotations

import os
import socket
import sys
import traceback
from pathlib import Path

OFFLINE_KEYS = ("DEEPGRAM_API_KEY", "NASA_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "HF_TOKEN")


def ios_env(resources: Path, support: Path) -> dict[str, str]:
    """The backend's environment on iPad: read-only data in the app bundle, everything writable under `support`."""
    return {
        "DATA_DIR": str(resources / "app" / "backend" / "data"),
        "FRONTEND_DIST": str(resources / "app" / "frontend"),
        "CACHE_DIR": str(support / "cache"),
        "MISSION_SAVE_DIR": str(support / "cache" / "saves"),
        "TURNLOG_DIR": str(support / "cache" / "turnlog"),
        "LUNA_DATA_DIR": str(support),
        "LUNA_LOG_DIR": str(support / "logs"),
        "HF_HOME": str(support / "hf"),
        "MODEL_SERVER_URL": "http://127.0.0.1:9",   # discard port: no model server on iPad, fails fast
        "TTS_ENGINE": "deepgram",                   # + no key -> 503 -> the page's OS voice (module docstring)
        "VIDEO_PREFETCH": "0",
        "ORT_DISABLE_TELEMETRY": "1",
    }


def pick_port() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", int(os.environ.get("LUNA_PORT", "0"))))
    return s


def main() -> int:
    try:
        resources = Path(os.environ["LUNA_RESOURCES"])
        support = Path(os.environ["LUNA_SUPPORT"])
        for k in OFFLINE_KEYS:
            os.environ.pop(k, None)
        for k, v in ios_env(resources, support).items():
            os.environ.setdefault(k, v)
        for d in ("cache", "cache/saves", "cache/turnlog", "logs"):
            (support / d).mkdir(parents=True, exist_ok=True)
        backend = resources / "app" / "backend"
        sys.path.insert(0, str(backend))
        os.chdir(backend)                          # pydantic reads ../.env and .env from here: the bundle ships neither
        sock = pick_port()
        port = sock.getsockname()[1]
        os.environ["CORS_ORIGINS"] = f"http://127.0.0.1:{port}"
        import uvicorn
        config = uvicorn.Config("app.main:app", log_level=os.environ.get("MOON_LOG_LEVEL", "warning"), access_log=False,
                                loop="asyncio", http="h11", ws="websockets", lifespan="on")
        server = uvicorn.Server(config)
        port_file = os.environ.get("LUNA_PORT_FILE")
        if port_file:
            # written before serve(): the shell polls /health on this port until the app is ready
            Path(port_file).write_text(str(port))
        print(f"luna_ios: serving on 127.0.0.1:{port}", flush=True)
        server.run(sockets=[sock])
        return 0
    except BaseException:  # noqa: BLE001 - the shell shows a plain error; the trace goes to the log
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
