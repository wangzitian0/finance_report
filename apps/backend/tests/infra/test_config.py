"""Tests for configuration helpers."""

import pytest
from common.testing.ac_proof import ac_proof
from pydantic import ValidationError

from src.config import Settings, parse_comma_list, parse_key_value_pairs


def test_parse_comma_list_defaults() -> None:
    assert parse_comma_list(None, ["a"]) == ["a"]


def test_parse_comma_list_accepts_list() -> None:
    assert parse_comma_list(["x", "y"], ["a"]) == ["x", "y"]


def test_parse_comma_list_splits_string() -> None:
    assert parse_comma_list("x, y, ,z", ["a"]) == ["x", "y", "z"]


def test_parse_key_value_pairs_empty() -> None:
    assert parse_key_value_pairs(None) == {}


def test_parse_key_value_pairs_ignores_invalid_items() -> None:
    value = "a=1, ,invalid,b=two,=ignored,c="
    assert parse_key_value_pairs(value) == {"a": "1", "b": "two"}


def test_environment_alias_reads_deployment_environment(monkeypatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("ENV", "staging")
    settings = Settings(_env_file=None)
    assert settings.environment == "staging"


def test_ai_base_url_defaults_to_zai_coding_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    settings = Settings(_env_file=None)
    assert settings.ai_base_url == "https://api.z.ai/api/coding/paas/v4"


def test_statement_disposition_mode_is_closed_configuration(monkeypatch) -> None:
    monkeypatch.setenv("STATEMENT_DISPOSITION_MODE", "observe")
    assert Settings(_env_file=None).statement_disposition_mode == "observe"

    monkeypatch.setenv("STATEMENT_DISPOSITION_MODE", "unsafe-default")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_cors_origin_regex_defaults_to_match_nothing(monkeypatch) -> None:
    monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
    settings_default = Settings(_env_file=None)
    assert settings_default.cors_origin_regex == r"^$"
    assert "https://report.zitian.party" not in settings_default.cors_origins

    monkeypatch.setenv("CORS_ORIGIN_REGEX", r"^https://.*\.example\.com$")
    settings_valid = Settings(_env_file=None)
    assert settings_valid.cors_origin_regex == r"^https://.*\.example\.com$"


@ac_proof(
    proof_id="test_AC_runtime_env_empty_values_2_settings_empty_env_resolution",
    ac_ids=["AC-runtime.env-empty-values.2"],
    ci_tier="pr_ci",
)
def test_AC_runtime_env_empty_values_2_settings_empty_env_resolution(monkeypatch, tmp_path) -> None:
    """AC-runtime.env-empty-values.2: Settings resolves empty environment strings safely across alias chains."""
    # 1. Process environment: empty values fall back safely to defaults
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("CORS_ORIGINS", "")
    monkeypatch.setenv("API_RATE_LIMIT_REQUESTS", "")

    settings = Settings(_env_file=None)
    assert settings.ai_api_key == ""
    assert "http://localhost:3000" in settings.cors_origins
    assert settings.api_rate_limit_requests == 300

    # 2. Dotenv file source: empty values fall back safely to defaults
    monkeypatch.delenv("AI_API_KEY", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("API_RATE_LIMIT_REQUESTS", raising=False)

    env_file = tmp_path / "test.env"
    env_file.write_text(
        "AI_API_KEY=\nCORS_ORIGINS=\nAPI_RATE_LIMIT_REQUESTS=\n",
        encoding="utf-8",
    )

    settings_dotenv = Settings(_env_file=str(env_file))
    assert settings_dotenv.ai_api_key == ""
    assert "http://localhost:3000" in settings_dotenv.cors_origins
    assert settings_dotenv.api_rate_limit_requests == 300

    # 3. Fail-closed: DATABASE_URL="" does NOT silently revert to default localhost
    monkeypatch.setenv("DATABASE_URL", "")
    settings_db = Settings(_env_file=None)
    assert settings_db.database_url == ""

    # 4. Import-time resilience: module-level settings = Settings() succeeds on empty rate limits
    import importlib

    import src.config

    orig_settings = src.config.settings
    try:
        monkeypatch.setenv("API_RATE_LIMIT_REQUESTS", "")
        reloaded_module = importlib.reload(src.config)
        assert reloaded_module.settings.api_rate_limit_requests == 300
    finally:
        reloaded_module.settings = orig_settings


def test_explicit_empty_cors_and_rate_limits() -> None:
    from pydantic.fields import FieldInfo

    from src.config import _extract_env_candidate_names

    # Test line 50: candidate extraction fallback for field without validation_alias
    assert _extract_env_candidate_names(FieldInfo(), "fallback_field") == ["fallback_field"]

    # Test line 552: validator directly handles empty string
    assert Settings._empty_cors_origins_is_none("   ") is None
    assert Settings._empty_cors_origins_is_none("http://localhost:3000") == "http://localhost:3000"

    # Test line 565: rate limit validator directly returns field default
    class _DummyInfo:
        field_name = "api_rate_limit_requests"

    assert Settings._empty_rate_limits_use_default("", _DummyInfo()) == 300

    settings = Settings(_env_file=None, cors_origins_str="   ", api_rate_limit_requests="  ")
    assert "http://localhost:3000" in settings.cors_origins
    assert settings.api_rate_limit_requests == 300


def test_runtime_declared_env_variables(monkeypatch) -> None:
    """Category 2 environment variables are declared as typed Settings fields."""
    monkeypatch.setenv("TRUST_PROXY", "true")
    monkeypatch.setenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "92")
    monkeypatch.setenv("RECONCILIATION_REVIEW_THRESHOLD", "75")

    settings = Settings(_env_file=None)
    assert settings.trust_proxy is True
    assert settings.reconciliation_auto_accept_threshold == 92
    assert settings.reconciliation_review_threshold == 75


def test_empty_reconciliation_thresholds_resolve_to_none(monkeypatch) -> None:
    """Empty reconciliation threshold environment variables resolve safely to None."""
    monkeypatch.setenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "")
    monkeypatch.setenv("RECONCILIATION_REVIEW_THRESHOLD", "   ")

    settings = Settings(_env_file=None)
    assert settings.reconciliation_auto_accept_threshold is None
    assert settings.reconciliation_review_threshold is None

    direct = Settings(
        _env_file=None,
        reconciliation_auto_accept_threshold="",  # type: ignore[arg-type]
        reconciliation_review_threshold="  ",  # type: ignore[arg-type]
    )
    assert direct.reconciliation_auto_accept_threshold is None
    assert direct.reconciliation_review_threshold is None


def test_settings_infra2_builders() -> None:
    """Settings exports builders for LlmSettings, S3Settings, and PostgresSettings."""
    settings = Settings(_env_file=None)

    llm = settings.to_llm_settings()
    assert llm.provider == settings.ai_provider
    assert llm.base_url == settings.ai_base_url
    assert llm.primary_model == settings.primary_model

    s3 = settings.to_s3_settings()
    assert s3.bucket == settings.s3_bucket
    assert s3.endpoint_url == settings.s3_endpoint
    assert s3.presign_expiry_seconds == settings.s3_presign_expiry_seconds

    pg = settings.to_postgres_settings()
    assert pg.pool_size == settings.db_pool_size
    assert pg.pool_max_overflow == settings.db_pool_max_overflow
