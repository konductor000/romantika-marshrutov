"""Application settings, read from the environment only (never from code)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


class Settings(BaseSettings):
    """Runtime configuration. Secrets come from `.env` in deployment, never committed."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str = ""
    admin_ids: Annotated[tuple[int, ...], NoDecode] = ()
    database_url: str = "postgresql+asyncpg://romantika:romantika@127.0.0.1:5432/romantika"
    media_dir: Path = PROJECT_ROOT / "data" / "media"
    public_base_url: str = "http://127.0.0.1:8010"
    admin_chat_id: int | None = None
    log_level: str = "INFO"
    env: str = "dev"
    dev_auth_user_id: int | None = None

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: object) -> object:
        """`ADMIN_IDS` is a comma-separated list of Telegram ids."""
        if isinstance(value, str):
            return tuple(int(part) for part in value.replace(";", ",").split(",") if part.strip())
        return value

    @field_validator("admin_chat_id", "dev_auth_user_id", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings instance for entrypoints (tests build `Settings()` directly)."""
    return Settings()
