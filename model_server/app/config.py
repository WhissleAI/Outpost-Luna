import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

HEADSTART = Path.home() / "Desktop/work/whissle/headstart"
STEER_REPO = Path(__file__).resolve().parents[3] / "steer-tts"          # sibling checkout (live_assist/steer-tts)
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

    Every weight path can be set by env var (ARCTAG_LIB, ARCTAG_MODEL_DIR, STEER_TTS_MODEL, STEER_DIRECTOR; ARC_META_WEIGHTS
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

    # Steer TTS Edge (POST /v1/tts). on|off; fails open with the reason in /health.
    steer_tts: str = "on"
    # The edge package directory (config.json, voices.*, onnx/). Default: the Hugging Face cache snapshot.
    steer_tts_model: Path | None = None
    # Steer's performance director (director.bin, format 2 as steertts_edge reads). Default: next to the model, then
    # the steer-tts repo's c/models copy.
    steer_director: Path | None = None
    steer_threads: int = 2

    def steer_model_dir(self) -> Path | None:
        if self.steer_tts_model:
            return self.steer_tts_model if (self.steer_tts_model / "config.json").exists() else None
        return hf_snapshot("WhissleAI/steer-tts-edge", "config.json")

    def steer_director_path(self) -> Path | None:
        model = self.steer_model_dir()
        for p in (self.steer_director, model / "director.bin" if model else None,
                  STEER_REPO / "c/models/steer-tts-edge/director.bin"):
            if p and p.exists():
                return p
        return None


settings = Settings()
