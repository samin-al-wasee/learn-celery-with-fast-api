from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Cardicheck"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://cardicheck:cardicheck@localhost:5432/cardicheck"

    # M2: cache / result backend. Sync redis client (used off the event loop).
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 60

    # DEV-ONLY fallback; never ship a real secret as a default.
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60


@lru_cache
def get_settings() -> Settings:
    return Settings()