from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

HEADSTART = Path.home() / "Desktop/work/whissle/headstart"


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


settings = Settings()
