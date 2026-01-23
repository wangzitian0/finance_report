"""Tests for env_check module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.env_check import (
    check_env_on_startup,
    get_vault_managed_keys_from_env_example,
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
            mock_settings.deployment_environment = "development"

            print_loaded_config(mock_settings)

        captured = capsys.readouterr()
        assert "Config loaded" in captured.out
        assert "SGD" in captured.out

    def test_debug_mode_no_defaults_prints_none(self, capsys):
        """Test that function prints '(none)' when all env vars are provided (no defaults)."""
        env_vars = {
            "ENV": "development",
            "DEBUG": "true",
            "BASE_CURRENCY": "USD",
            "PRIMARY_MODEL": "test",
            "S3_ENDPOINT": "http://minio:9000",
            "S3_BUCKET": "test",
            "CORS_ORIGIN_REGEX": ".*",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            "OTEL_SERVICE_NAME": "finance-report-backend",
            "OTEL_RESOURCE_ATTRIBUTES": "deployment.environment=development",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            mock_settings = MagicMock()
            mock_settings.debug = True
            mock_settings.deployment_environment = env_vars["ENV"]
            for k, v in env_vars.items():
                setattr(mock_settings, k.lower(), v)

            print_loaded_config(mock_settings)

        captured = capsys.readouterr()
        assert "(none)" in captured.out


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
        with patch("src.env_check.get_vault_managed_keys_from_env_example") as mock_parser:
            mock_parser.return_value = [
                "DATABASE_URL",
                "S3_ENDPOINT",
                "S3_ACCESS_KEY",
                "S3_SECRET_KEY",
                "S3_BUCKET",
                "REDIS_URL",
            ]
            env_vars = {
                "ENV": "production",
                "DATABASE_URL": "postgresql://...",
                "S3_ENDPOINT": "http://localhost:9000",
                "S3_ACCESS_KEY": "test",
                "S3_SECRET_KEY": "test",
                "S3_BUCKET": "test",
                "REDIS_URL": "redis://localhost:6379/0",
            }
            with patch.dict(os.environ, env_vars, clear=False):
                check_env_on_startup()

        captured = capsys.readouterr()
        assert "Missing required variables" not in captured.out

    def test_production_missing_vars_warns_with_override(self, capsys):
        """Test production with missing vars shows warning when STRICT_ENV_CHECK=false."""
        with patch.dict(
            os.environ,
            {
                "ENV": "production",
                "STRICT_ENV_CHECK": "false",
            },
            clear=True,
        ):
            check_env_on_startup()

        captured = capsys.readouterr()
        assert "Missing required variables" in captured.out

    def test_production_strict_mode_exits_by_default(self, capsys):
        """Test that sys.exit(1) is called by default when vars are missing in production."""
        env_vars = {
            "ENV": "production",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(SystemExit) as exc:
                check_env_on_startup()
            assert exc.value.code == 1

        captured = capsys.readouterr()
        assert "Missing required variables" in captured.out
        assert "Refusing to start" in captured.out


class TestGetVaultManagedKeysParser:
    """Tests for get_vault_managed_keys_from_env_example parser."""

    def test_parser_finds_keys_from_real_env_example(self):
        """Test parser correctly identifies keys from actual .env.example file."""
        keys = get_vault_managed_keys_from_env_example()

        expected_minimum = [
            "DATABASE_URL",
            "ENVIRONMENT",
            "OPENROUTER_API_KEY",
            "S3_ENDPOINT",
            "S3_ACCESS_KEY",
            "S3_SECRET_KEY",
            "S3_BUCKET",
            "S3_REGION",
            "S3_PRESIGN_EXPIRY_SECONDS",
        ]

        for expected_key in expected_minimum:
            assert expected_key in keys, f"Missing expected key: {expected_key}"

    def test_parser_respects_10_line_window(self):
        """Test that keys beyond 10 lines after [VAULT] marker are excluded."""
        content = """# [VAULT]
KEY1=val
KEY2=val

KEY4=val

KEY6=val

KEY8=val

KEY10=val
# Comment line 11
KEY11=val
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env.example", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with patch.object(Path, "__truediv__", return_value=Path(temp_path)):
                keys = get_vault_managed_keys_from_env_example()

            assert "KEY1" in keys
            assert "KEY10" in keys
            assert "KEY11" not in keys
        finally:
            os.unlink(temp_path)

    def test_parser_extracts_prefix_pattern(self):
        """Test parser correctly extracts and applies prefix patterns like 'S3_*'."""
        content = """# [VAULT] All S3_* variables
S3_ENDPOINT=x
S3_BUCKET=y
DEBUG=z
REDIS_URL=a
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env.example", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with patch.object(Path, "__truediv__", return_value=Path(temp_path)):
                keys = get_vault_managed_keys_from_env_example()

            assert "S3_ENDPOINT" in keys
            assert "S3_BUCKET" in keys
            assert "DEBUG" not in keys
            assert "REDIS_URL" not in keys
        finally:
            os.unlink(temp_path)

    def test_missing_env_example_returns_empty_list(self):
        """Test that missing .env.example file returns empty list without crashing."""
        with patch.object(Path, "exists", return_value=False):
            keys = get_vault_managed_keys_from_env_example()

        assert keys == []

    def test_malformed_env_example_handled_gracefully(self):
        """Test that malformed .env.example (invalid UTF-8) is handled gracefully."""
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".env.example", delete=False) as f:
            f.write(b"\xff\xfe\x00\x00")
            temp_path = f.name

        try:
            with patch.object(Path, "__truediv__", return_value=Path(temp_path)):
                keys = get_vault_managed_keys_from_env_example()

            assert isinstance(keys, list)
            assert keys == []
        finally:
            os.unlink(temp_path)

    def test_parser_handles_multiple_vault_markers(self):
        """Test parser correctly handles multiple [VAULT] markers with different patterns."""
        content = """# [VAULT] All S3_* variables
S3_ENDPOINT=x
S3_BUCKET=y

# [VAULT]
DATABASE_URL=postgres://...
REDIS_URL=redis://...

# [VAULT] All OTEL_* variables
OTEL_ENDPOINT=http://...
OTEL_SERVICE_NAME=test
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env.example", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with patch.object(Path, "__truediv__", return_value=Path(temp_path)):
                keys = get_vault_managed_keys_from_env_example()

            assert "S3_ENDPOINT" in keys
            assert "S3_BUCKET" in keys
            assert "DATABASE_URL" in keys
            assert "REDIS_URL" in keys
            assert "OTEL_ENDPOINT" in keys
            assert "OTEL_SERVICE_NAME" in keys
        finally:
            os.unlink(temp_path)

    def test_parser_resets_state_after_window_expires(self):
        """Test that parser correctly resets state when 10-line window expires with comments."""
        content = """# [VAULT] All S3_* variables
S3_ENDPOINT=x
# Comment 1
# Comment 2
# Comment 3
# Comment 4
# Comment 5
# Comment 6
# Comment 7
# Comment 8
# Comment 9
# Comment 10
# Comment 11 (line 13, window expired)
UNRELATED_VAR=should_not_match
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env.example", delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with patch.object(Path, "__truediv__", return_value=Path(temp_path)):
                keys = get_vault_managed_keys_from_env_example()

            assert "S3_ENDPOINT" in keys
            assert "UNRELATED_VAR" not in keys
        finally:
            os.unlink(temp_path)
