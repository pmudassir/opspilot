from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, read from environment variables (and `.env` locally).

    Validated once at startup: a missing or malformed value stops the app
    from booting instead of failing on the first request.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn
    environment: Literal["local", "test", "production"] = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
