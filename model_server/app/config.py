import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

HEADSTART = Path.home() / "Desktop/work/whissle/headstart"
STEER_REPO = Path(__file__).resolve().parents[3] / "steer-tts"          # sibling checkout (live_assist/steer-tts)
# The native Arc Tagger library's file name on this OS (desktop/vendor/arctag builds all three).
ARCTAG_LIB_NAME = {"darwin": "libarctag.dylib", "win32": "arctag.dll"}.get(sys.platform, "libarctag.so")
REPO_ARCTAG = Path(__file__).resolve().parents[2] / "desktop/resources/native" / ARCTAG_LIB_NAME   # `make desktop-arctag`


def hf_hub_cache() -> Path:
    """The Hugging Face hub cache, as huggingface_hub resolves it (HF_HUB_CACHE, then HF_HOME/hub, then ~/.cache)."""
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    if os.environ.get("HF_HOME"):
        return Path(os.environ["HF_HOME"]) / "hub"
    return Path.home() / ".cache/huggingface/hub"


def hf_snapshot(repo: str, has: str, prefer: str | None = None) -> Path | None:
    """A snapshot folder of `repo` (e.g. "WhissleAI/arc-v1.1") in the local HF cache that contains `has`: the `prefer`
    revision when it is there, else the newest. None when the repo is not cached. Never downloads."""
    snaps = hf_hub_cache() / f"models--{repo.replace('/', '--')}" / "snapshots"
    if prefer and (snaps / prefer / has).exists():
        return snaps / prefer
    found = sorted(snaps.glob(f"*/{has}"), key=lambda p: p.stat().st_mtime) if snaps.exists() else []
    return found[-1].parents[len(Path(has).parts) - 1] if found else None


class Settings(BaseSettings):
    """Model server settings. Read from the environment, then ../.env (shared with the backend).

    Every weight path can be set by env var (ARCTAG_LIB, ARCTAG_MODEL_DIR; ARC_SPACE_DIR and ARC_LIB
    in arcmeta.py; EMBED_MODEL_DIR in embed.py; STEER_TTS_MODEL, STEER_DIRECTOR for the optional Steer engine). The desktop app sets all of them to its bundled copies (docs/DESKTOP.md);
    the defaults below are the developer checkout's (`make dev`)."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # Arc Tagger 0.5 native library (arc-tagger-c, int8, native backend) and its model folder. The library defaults to
    # this checkout's build (`make desktop-arctag`): the binding checks its version against desktop/vendor/arctag's
    # header, so Head Start's older copy no longer loads. The model folder defaults to the copy Head Start ships.
    arctag_lib: Path = REPO_ARCTAG if REPO_ARCTAG.exists() else HEADSTART / "vendor/arctag" / ARCTAG_LIB_NAME
    arctag_model_dir: Path = HEADSTART / "models/arctag"
    # Handles per domain kept warm. A handle is not thread-safe, so each request borrows one.
    arctag_pool_size: int = 2
    # kids: safety on kid turns (backend/app/safety.py); assistant: the Director's read-out and /api/ask (unchanged)
    arctag_domains: str = "assistant,news,talk,kids"
    # Live dedicated handles for WS /v1/tag/stream (one per connection). Over the cap, new connections close with 1013.
    tag_stream_max: int = 16

    # Speech (POST /v1/tts): the operating system's own offline voices (app/tts_os.py). on|off; fails open with the
    # reason in /health. Engine: auto (macOS say; Windows WinRT, then SAPI) | say | winrt | sapi.
    os_tts: str = "on"
    os_tts_engine: str = "auto"
    # The kid's locale for ranking voices (e.g. en-GB). Default: the OS's own.
    os_tts_locale: str | None = None
    # Words per minute at 1x before the style's rate (macOS `say -r`); WinRT speaking-rate multiplier at 1x.
    os_tts_wpm: int = 165
    os_tts_winrt_rate: float = 1.0
    # The recorded voice pack (app/voice_pack.py, docs/VOICE_PACK.md): fixed lines pre-recorded with Siri Voice 1. on|off.
    # The folder defaults to the backend's data/voice_pack (dev checkout and the desktop bundle alike).
    voice_pack: str = "on"
    voice_pack_dir: Path = Path(__file__).resolve().parents[2] / "backend" / "data" / "voice_pack"

    # Steer TTS Edge, the optional second engine (POST /v1/tts/steer, app/tts_steer.py). on|off; fails open with the
    # reason in /health. The desktop app points STEER_TTS_MODEL at its downloaded `steer` asset (steer-tts-edge/).
    steer_tts: str = "on"
    # The edge package directory (config.json, voices.*, onnx/, front/). Default: model_server/models/steer-tts-edge,
    # then the Hugging Face cache snapshot.
    steer_tts_model: Path | None = None
    # Steer's performance director (director.bin). Default: next to the model, then the steer-tts repo's c/models copy.
    steer_director: Path | None = None
    steer_threads: int = 2

    def steer_model_dir(self) -> Path | None:
        if self.steer_tts_model:
            return self.steer_tts_model if (self.steer_tts_model / "config.json").exists() else None
        local = Path(__file__).resolve().parents[1] / "models" / "steer-tts-edge"
        if (local / "config.json").exists():
            return local
        return hf_snapshot("WhissleAI/steer-tts-edge", "config.json")

    def steer_director_path(self) -> Path | None:
        model = self.steer_model_dir()
        for p in (self.steer_director, model / "director.bin" if model else None,
                  STEER_REPO / "c/models/steer-tts-edge/director.bin"):
            if p and p.exists():
                return p
        return None


settings = Settings()
