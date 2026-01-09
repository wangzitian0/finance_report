"""Application configuration using Pydantic Settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
    
    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report"
    
    # App settings
    debug: bool = False
    api_prefix: str = "/api/v1"
    
    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
