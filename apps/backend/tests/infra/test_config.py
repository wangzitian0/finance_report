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
    monkeypatch.delenv("ZAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
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
    # 1. Process environment: ZAI_API_KEY="" does not mask GEMINI_API_KEY="real-gemini-key"
    for k in ("GLM_API_KEY", "AI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ZAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "real-gemini-key")
    monkeypatch.setenv("CORS_ORIGINS", "")
    monkeypatch.setenv("API_RATE_LIMIT_REQUESTS", "")

    settings = Settings(_env_file=None)
    assert settings.ai_api_key == "real-gemini-key"
    assert "http://localhost:3000" in settings.cors_origins
    assert settings.api_rate_limit_requests == 300

    # 2. Dotenv file source: ZAI_API_KEY= with fallback GEMINI_API_KEY=real-dotenv-key
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("API_RATE_LIMIT_REQUESTS", raising=False)

    env_file = tmp_path / "test.env"
    env_file.write_text(
        "ZAI_API_KEY=\nGEMINI_API_KEY=real-dotenv-key\nCORS_ORIGINS=\nAPI_RATE_LIMIT_REQUESTS=\n",
        encoding="utf-8",
    )

    settings_dotenv = Settings(_env_file=str(env_file))
    assert settings_dotenv.ai_api_key == "real-dotenv-key"
    assert "http://localhost:3000" in settings_dotenv.cors_origins
    assert settings_dotenv.api_rate_limit_requests == 300

    # 3. Fail-closed: DATABASE_URL="" does NOT silently revert to default localhost
    monkeypatch.setenv("DATABASE_URL", "")
    settings_db = Settings(_env_file=None)
    assert settings_db.database_url == ""

    # 4. Import-time resilience: module-level settings = Settings() succeeds on empty rate limits
    import importlib

    import src.config

    monkeypatch.setenv("API_RATE_LIMIT_REQUESTS", "")
    reloaded_module = importlib.reload(src.config)
    assert reloaded_module.settings.api_rate_limit_requests == 300


def test_explicit_empty_cors_and_rate_limits() -> None:
    settings = Settings(_env_file=None, cors_origins_str="   ", api_rate_limit_requests="  ")
    assert "http://localhost:3000" in settings.cors_origins
    assert settings.api_rate_limit_requests == 300
