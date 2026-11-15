import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

HEADSTART = Path.home() / "Desktop/work/whissle/headstart"
# The native Arc Tagger library's file name on this OS (desktop/vendor/arctag builds all three).
ARCTAG_LIB_NAME = {"darwin": "libarctag.dylib", "win32": "arctag.dll"}.get(sys.platform, "libarctag.so")


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

    Every weight path can be set by env var (ARCTAG_LIB, ARCTAG_MODEL_DIR; ARC_META_WEIGHTS
    in arcmeta.py; EMBED_MODEL_DIR in embed.py). The desktop app sets all of them to its bundled copies (docs/DESKTOP.md);
    the defaults below are the developer checkout's (`make dev`)."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # Arc Tagger v0.3 native library (arc-tagger-c, int8, native backend) and its model folder.
    # Defaults point at the copies Head Start already ships, so the two apps run the same build.
    arctag_lib: Path = HEADSTART / "vendor/arctag" / ARCTAG_LIB_NAME
    arctag_model_dir: Path = HEADSTART / "models/arctag"
    # Handles per domain kept warm. A handle is not thread-safe, so each request borrows one.
    arctag_pool_size: int = 2
    arctag_domains: str = "assistant,news,talk"
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


settings = Settings()
