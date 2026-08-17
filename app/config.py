from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CHECKIN_")

    database_url: str = "postgresql+asyncpg://checkin:checkin@localhost:5432/checkin_dev"

    no_checkin_streak_days: int = 3
    summary_prebuild_enabled: bool = True

    environment: str = "dev"


settings = Settings()
