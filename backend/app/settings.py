from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    nfd_env: Literal["development", "test", "production"] = "development"
    nfd_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    nfd_data_root: Path = ROOT_ENV_FILE.parent / "data" / "local"
    database_url: str = "postgresql://nfd:nfd-local-only@localhost:5432/nfd"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            raise ValueError("DATABASE_URL must be a PostgreSQL URL with a host")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            raise ValueError("REDIS_URL must be a Redis URL with a host")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
