from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore", protected_namespaces=("settings_",))

    data_dir: Path = ROOT / "data"
    model_server_url: str = "http://127.0.0.1:8200"
    model_timeout_s: float = 2.0
    anthropic_api_key: str = ""
    ask_model: str = "claude-haiku-5-5"
    frontend_dist: Path = ROOT.parent / "frontend/dist"
    cors_origins: str = "http://localhost:5173"


settings = Settings()
