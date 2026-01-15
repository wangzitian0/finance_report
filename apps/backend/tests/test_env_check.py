"""Tests for env_check module."""

import os
from unittest.mock import MagicMock, patch


from src.env_check import (
    check_env_on_startup,
    print_loaded_config,
)


class TestPrintLoadedConfig:
    """Tests for print_loaded_config function."""

    def test_not_debug_mode_returns_early(self, capsys):
        """Test that function returns early when not in DEBUG mode."""
        with patch.dict(os.environ, {"DEBUG": "false"}, clear=False):
            mock_settings = MagicMock()
            print_loaded_config(mock_settings)

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_debug_mode_prints_config(self, capsys):
        """Test that function prints config in DEBUG mode."""
        with patch.dict(os.environ, {"DEBUG": "true"}, clear=False):
            mock_settings = MagicMock()
            mock_settings.debug = True
            mock_settings.base_currency = "SGD"
            mock_settings.primary_model = "test-model"
            mock_settings.s3_endpoint = "http://localhost:9000"
            mock_settings.s3_bucket = "test-bucket"
            mock_settings.cors_origin_regex = ".*"
            mock_settings.database_url = "postgresql://..."
            mock_settings.redis_url = None
            mock_settings.openrouter_api_key = ""
            mock_settings.s3_access_key = "test"
            mock_settings.s3_secret_key = "test"

            print_loaded_config(mock_settings)

        captured = capsys.readouterr()
        assert "Config loaded" in captured.out
        assert "SGD" in captured.out


class TestCheckEnvOnStartup:
    """Tests for check_env_on_startup function."""

    def test_non_production_no_warning(self, capsys):
        """Test no warning in development environment."""
        with patch.dict(os.environ, {"ENV": "development"}, clear=False):
            check_env_on_startup()

        captured = capsys.readouterr()
        assert "Missing required variables" not in captured.out

    def test_production_with_all_vars(self, capsys):
        """Test production with all required vars set."""
        env_vars = {
            "ENV": "production",
            "DATABASE_URL": "postgresql://...",
            "S3_ENDPOINT": "http://localhost:9000",
            "S3_ACCESS_KEY": "test",
            "S3_SECRET_KEY": "test",
            "S3_BUCKET": "test",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            check_env_on_startup()

        captured = capsys.readouterr()
        assert "Missing required variables" not in captured.out

    def test_production_missing_vars_warns(self, capsys):
        """Test production with missing vars shows warning."""
        # Set ENV to production and ensure required vars are missing
        with patch.dict(
            os.environ,
            {
                "ENV": "production",
            },
            clear=True,
        ):
            
            check_env_on_startup()

        captured = capsys.readouterr()
        assert "Missing required variables" in captured.out
