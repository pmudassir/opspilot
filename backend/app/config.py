from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Depends
from pydantic import PostgresDsn, SecretStr, field_validator
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

    # AI request drafts (optional). Without a key the feature is off; the app works as before.
    # SecretStr: the key never appears in logs, reprs or error messages.
    groq_api_key: SecretStr | None = None
    ai_model: str = "openai/gpt-oss-120b"
    ai_timeout_seconds: float = 20.0
    ai_drafts_per_hour: int = 20
    ai_assistant_runs_per_hour: int = 10

    @field_validator("groq_api_key", mode="before")
    @classmethod
    def _empty_key_means_off(cls, value: object) -> object:
        # GROQ_API_KEY="" (e.g. e2e runs overriding a real key in .env) switches AI off.
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def session_cookie_secure(self) -> bool:
        # Secure cookies are only sent over HTTPS; local dev and tests use plain HTTP.
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
