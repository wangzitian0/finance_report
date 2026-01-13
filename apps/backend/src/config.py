"""Application configuration using Pydantic Settings."""

from pydantic import Field, field_validator
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
    base_currency: str = "SGD"

    # CORS origins - explicit list for known origins
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
        # Explicit production origin(s) as fallback in addition to regex
        "https://report.zitian.party",
    ]

    # CORS origin regex - for dynamic subdomains (PR deployments)
    cors_origin_regex: str = r"https://.*\.zitian\.party"

    # OpenRouter API (for AI models)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    primary_model: str = "nvidia/nemotron-3-nano-30b-a3b:free"
    fallback_models: list[str] = [
        "google/gemini-2.0-flash-exp:free",
        "google/gemini-2.0-flash-thinking-exp:free",
    ]
    openrouter_daily_limit_usd: int | None = None

    # S3 / MinIO storage
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = Field(default="minioadmin", validation_alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minioadmin", validation_alias="S3_SECRET_KEY")
    s3_bucket: str = "statements"
    s3_region: str = "us-east-1"
    s3_presign_expiry_seconds: int = 900

    @field_validator("fallback_models", mode="before")
    @classmethod
    def parse_fallback_models(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


settings = Settings()
