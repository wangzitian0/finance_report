"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database - use env var in production, local dev default for convenience
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report"

    # App settings
    debug: bool = False

    # CORS origins - configure via CORS_ORIGINS env var in production
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


settings = Settings()
