from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

HEADSTART = Path.home() / "Desktop/work/whissle/headstart"
STEER_REPO = Path(__file__).resolve().parents[3] / "steer-tts"          # sibling checkout (live_assist/steer-tts)
HF_STEER = Path.home() / ".cache/huggingface/hub/models--WhissleAI--steer-tts-edge/snapshots"


class Settings(BaseSettings):
    """Model server settings. Read from the environment, then ../.env (shared with the backend)."""

    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    # Arc Tagger v0.3 native library (arc-tagger-c, int8, native backend) and its model folder.
    # Defaults point at the copies Head Start already ships, so the two apps run the same build.
    arctag_lib: Path = HEADSTART / "vendor/arctag/libarctag.dylib"
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
        snaps = sorted(HF_STEER.glob("*/config.json"), key=lambda p: p.stat().st_mtime) if HF_STEER.exists() else []
        return snaps[-1].parent if snaps else None

    def steer_director_path(self) -> Path | None:
        model = self.steer_model_dir()
        for p in (self.steer_director, model / "director.bin" if model else None,
                  STEER_REPO / "c/models/steer-tts-edge/director.bin"):
            if p and p.exists():
                return p
        return None


settings = Settings()
