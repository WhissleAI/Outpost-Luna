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
    # Guide-channel TTS: os (the OS's own offline voice on the model server, falls back to deepgram) | deepgram
    tts_engine: str = "os"
    tts_timeout_s: float = 8.0
    flux_url: str = "wss://api.deepgram.com/v2/listen"
    model_stream_url: str = ""  # default: model_server_url as ws:// + /v1/stream
    brain: str = "local"   # knowledge cards + the model server embedder (docs/LOCAL_BRAIN.md); no cloud LLM
    frontend_dist: Path = ROOT.parent / "frontend/dist"
    cors_origins: str = "http://localhost:5173"
    # NASA video (app/video.py, docs/MEDIA.md): the offline cache's cap, the background prefetch of the pinned files on
    # first online launch, and a switch that makes the backend act offline (tests; trying the offline cards).
    video_cache_mb: int = 1024
    video_prefetch: bool = True
    video_offline: bool = False
    # First-run assets (desktop/main/assets.js, docs/DESKTOP.md "First run: assets"): the desktop app installs these into
    # the per-user folder after the app is built, so they are not under data_dir. None (dev): data_dir's own copies.
    media_audio_dir: Path | None = None    # crew audio: audio/*.mp3 + trim.json (served as /media/audio/*)
    video_pack_dir: Path | None = None     # the pinned NASA videos: <id>.mp4 / .vtt / .jpg, copied into the video cache
    voice_pack_dir: Path | None = None     # the recorded voice pack (index.json, clips/): default data_dir/voice_pack
    # Asset updates (desktop/main/updates.js, docs/DESKTOP.md "Asset updates"): the desktop writes its summary here and
    # watches the check-request file; GET /api/assets / POST /api/assets/check (app/assets_api.py). Unset in a dev checkout.
    assets_state_file: Path | None = None
    assets_check_file: Path | None = None


    def media_dirs(self) -> list[Path]:
        """Where /media/* is looked up, in order: the installed crew-audio asset (desktop), then data_dir/media."""
        return ([self.media_audio_dir] if self.media_audio_dir else []) + [self.data_dir / "media"]

    def voice_pack(self) -> Path:
        return self.voice_pack_dir or self.data_dir / "voice_pack"

    def vector_cache(self) -> Path:
        return self.cache_dir / "vectors" if self.cache_dir else self.data_dir / "cache"

    def tts_cache(self) -> Path:
        return self.cache_dir / "tts" if self.cache_dir else self.data_dir / "tts_cache"

    def video_cache(self) -> Path:
        return self.cache_dir / "video" if self.cache_dir else self.data_dir / "video_cache"


settings = Settings()
