from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore", protected_namespaces=("settings_",))

    data_dir: Path = ROOT / "data"
    # Writable caches (embedding vectors, server TTS audio). Default: inside data_dir, as in the dev checkout. The desktop
    # app keeps data_dir read-only inside the bundle and points this at the per-user app data folder (docs/DESKTOP.md).
    cache_dir: Path | None = None
    model_server_url: str = "http://127.0.0.1:8200"
    model_timeout_s: float = 2.0
    deepgram_api_key: str = ""
    # Guide-channel TTS: steer (Steer TTS Edge on the model server, falls back to deepgram) | deepgram
    tts_engine: str = "steer"
    tts_timeout_s: float = 8.0
    flux_url: str = "wss://api.deepgram.com/v2/listen"
    model_stream_url: str = ""  # default: model_server_url as ws:// + /v1/stream
    brain: str = "local"   # knowledge cards + the model server embedder (docs/LOCAL_BRAIN.md); no cloud LLM
    frontend_dist: Path = ROOT.parent / "frontend/dist"
    cors_origins: str = "http://localhost:5173"


    def vector_cache(self) -> Path:
        return self.cache_dir / "vectors" if self.cache_dir else self.data_dir / "cache"

    def tts_cache(self) -> Path:
        return self.cache_dir / "tts" if self.cache_dir else self.data_dir / "tts_cache"


settings = Settings()
