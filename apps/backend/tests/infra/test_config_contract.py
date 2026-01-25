"""Contract tests for configuration consistency.

These tests validate that configuration defaults match documentation
and follow expected patterns, preventing silent breakage on config changes.
"""

import re
from pathlib import Path


class TestConfigContract:
    """Test configuration contracts and synchronization."""

    def test_primary_model_format(self):
        """Ensure PRIMARY_MODEL follows expected pattern."""
        from src.config import settings

        # Test contract: model should follow google/gemini-* pattern
        assert settings.primary_model.startswith("google/"), (
            f"Invalid model provider: {settings.primary_model}. Expected pattern: google/gemini-*"
        )
        assert "gemini" in settings.primary_model.lower(), (
            f"Invalid model family: {settings.primary_model}. Expected 'gemini' in model name"
        )
        # Flexible check - allow various version formats
        assert re.match(r"^google/gemini-[\d.a-z-]+", settings.primary_model), (
            f"Invalid model format: {settings.primary_model}. Expected pattern: google/gemini-<version>"
        )

    def test_config_sync_with_env_example(self):
        """Ensure config.py default matches .env.example documentation."""
        from src.config import settings

        env_example_path = Path(__file__).parent.parent.parent.parent / ".env.example"
        env_example = env_example_path.read_text()

        # Parse PRIMARY_MODEL from .env.example
        match = re.search(r"^PRIMARY_MODEL=(.+)$", env_example, re.MULTILINE)
        assert match, ".env.example missing PRIMARY_MODEL definition"

        expected = match.group(1).strip()
        assert settings.primary_model == expected, (
            f"Config default mismatch:\n"
            f"  config.py:        {settings.primary_model}\n"
            f"  .env.example:     {expected}\n"
            f"Please update config.py default to match .env.example"
        )

    def test_base_currency_format(self):
        """Ensure BASE_CURRENCY is a valid ISO 4217 currency code."""
        from src.config import settings

        assert settings.base_currency.isalpha(), (
            f"Invalid currency code: {settings.base_currency}. Must be alphabetic (ISO 4217)"
        )
        assert len(settings.base_currency) == 3, (
            f"Invalid currency code: {settings.base_currency}. Must be 3 characters (ISO 4217)"
        )
        assert settings.base_currency.isupper(), (
            f"Invalid currency code: {settings.base_currency}. Must be uppercase (ISO 4217)"
        )

    def test_s3_bucket_format(self):
        """Ensure S3_BUCKET follows naming conventions."""
        from src.config import settings

        # S3 bucket naming rules: lowercase, no underscores, 3-63 chars
        assert settings.s3_bucket.islower() or settings.s3_bucket.replace("-", "").islower(), (
            f"Invalid S3 bucket name: {settings.s3_bucket}. Must be lowercase"
        )
        assert 3 <= len(settings.s3_bucket) <= 63, (
            f"Invalid S3 bucket name: {settings.s3_bucket}. Must be 3-63 characters"
        )
        assert re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", settings.s3_bucket), (
            f"Invalid S3 bucket name: {settings.s3_bucket}. Must contain only lowercase letters, numbers, and hyphens"
        )

    def test_jwt_algorithm_allowed(self):
        """Ensure JWT_ALGORITHM is a secure algorithm."""
        from src.config import settings

        # Allow only HS256 and RS256 (secure algorithms)
        allowed_algorithms = {"HS256", "RS256"}
        assert settings.jwt_algorithm in allowed_algorithms, (
            f"Insecure JWT algorithm: {settings.jwt_algorithm}. Allowed: {allowed_algorithms}"
        )

    def test_database_url_format(self):
        """Ensure DATABASE_URL follows expected format."""
        from src.config import settings

        # Should use asyncpg driver for async FastAPI compatibility
        assert (
            "postgresql+asyncpg://" in settings.database_url
            or "sqlite" in settings.database_url  # Allow sqlite for testing
        ), f"Invalid database URL: {settings.database_url}. Expected postgresql+asyncpg:// or sqlite://"
