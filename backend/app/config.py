from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends
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

    session_ttl_hours: int = 24 * 7
    # Origins allowed to make state-changing (POST/PUT/PATCH/DELETE) browser requests.
    allowed_origins: list[str] = ["http://localhost:3000"]

    @property
    def session_cookie_secure(self) -> bool:
        # Secure cookies are only sent over HTTPS; local dev and tests use plain HTTP.
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
