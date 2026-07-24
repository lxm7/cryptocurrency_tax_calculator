"""Application settings (pydantic-settings). Values come from the environment.

Env vars (populate in `.env` / compose): DATABASE_URL, DATABASE_URL_DIRECT,
REDIS_URL, ANTHROPIC_API_KEY, ANTHROPIC_MODEL.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # Non-pooled Neon endpoint for alembic (prepared statements need direct host).
    # Optional: falls back to DATABASE_URL when unset (e.g. local non-Neon Postgres).
    database_url_direct: str | None = None
    redis_url: str
    anthropic_api_key: str
    anthropic_model: str = "claude-haiku-4-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # fields are read from the environment
