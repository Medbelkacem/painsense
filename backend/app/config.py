import base64
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Both are read so one .env at the repository root serves the container stack and a
    # backend run directly from its own directory. The nearer file wins.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "sqlite+pysqlite:///./painscore.db"

    master_key: str = ""
    jwt_secret: str = ""
    jwt_refresh_secret: str = ""

    access_token_ttl_minutes: int = 20
    refresh_token_ttl_days: int = 14

    key_store_path: Path = Path("./keystore")
    model_store_path: Path = Path("./models")
    dataset_path: Path = Path("./datasets")
    document_store_path: Path = Path("./storage/documents")

    cors_origins: str = "http://localhost:5173,http://localhost:4173"
    max_document_bytes: int = 15 * 1024 * 1024

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def master_key_bytes(self) -> bytes:
        raw = base64.b64decode(self.master_key)
        if len(raw) != 32:
            raise ValueError("MASTER_KEY must decode to exactly 32 bytes")
        return raw


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # A dev machine should not need a .env just to start the app, but we never
    # want a generated key to silently become the production one.
    for field in ("master_key", "jwt_secret", "jwt_refresh_secret"):
        if not getattr(settings, field):
            if os.getenv("PAINSCORE_ENV") == "production":
                raise RuntimeError(f"{field.upper()} is required in production")
            setattr(settings, field, base64.b64encode(os.urandom(32)).decode())
    for directory in (
        settings.key_store_path,
        settings.model_store_path,
        settings.dataset_path,
        settings.document_store_path,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return settings
