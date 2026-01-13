"""Tests for core config module."""

import pytest
import os
from unittest.mock import patch

from src.core.config import Settings, settings


def test_settings_default_values():
    """Test that Settings has required configuration fields."""
    test_settings = Settings(
        database_url="sqlite:///test.db", s3_access_key="test_key", s3_secret_key="test_secret"
    )

    assert test_settings.database_url == "sqlite:///test.db"
    assert test_settings.s3_access_key == "test_key"
    assert test_settings.s3_secret_key == "test_secret"


def test_settings_environment_variables():
    """Test that settings can be loaded from environment."""
    with patch.dict(
        os.environ,
        {
            "DATABASE_URL": "postgresql://test",
            "S3_ACCESS_KEY": "env_key",
            "S3_SECRET_KEY": "env_secret",
        },
    ):
        test_settings = Settings()

        assert test_settings.database_url == "postgresql://test"
        assert test_settings.s3_access_key == "env_key"
        assert test_settings.s3_secret_key == "env_secret"


def test_settings_instance_exists():
    """Test that global settings instance is available."""
    assert settings is not None
    assert hasattr(settings, "database_url")
    assert hasattr(settings, "s3_access_key")
    assert hasattr(settings, "s3_secret_key")
