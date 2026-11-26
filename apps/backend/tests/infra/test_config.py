from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from infra2_sdk.llm import LlmSettings
from pydantic import ValidationError

from src.config import (
    ENV_SOURCE_CLASSES,
    Settings,
    _extract_env_candidate_names,
    parse_comma_list,
    parse_key_value_pairs,
    settings,
)


def test_parse_helpers_and_to_llm_settings() -> None:
    assert parse_comma_list(None, ["a"]) == ["a"]
    assert parse_comma_list(["x", "y"], ["a"]) == ["x", "y"]
    assert parse_comma_list("x, y, ,z", ["a"]) == ["x", "y", "z"]
    assert parse_key_value_pairs(None) == {}
    assert parse_key_value_pairs("a=1, ,invalid,b=two,=ignored,c=") == {"a": "1", "b": "two"}
    s = Settings(_env_file=None)
    llm = s.to_llm_settings()
    assert (
        llm.provider,
        llm.base_url,
        llm.role_model("small"),
        llm.role_model("large"),
        llm.role_model("multimodal"),
    ) == (
        s.ai_provider,
        s.ai_base_url,
        s.small_model,
        s.large_model,
        s.multimodal_model,
    )


def test_env_aliases_and_closed_modes(monkeypatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
    s = Settings(_env_file=None)
    assert (s.environment, s.ai_base_url, s.cors_origin_regex) == (
        "staging",
        "https://api.z.ai/api/coding/paas/v4",
        "^$",
    )
    assert "https://report.zitian.party" not in s.cors_origins

    monkeypatch.setenv("CORS_ORIGIN_REGEX", r"^https://.*\.example\.com$")
    assert Settings(_env_file=None).cors_origin_regex == r"^https://.*\.example\.com$"

    monkeypatch.setenv("STATEMENT_DISPOSITION_MODE", "observe")
    assert Settings(_env_file=None).statement_disposition_mode == "observe"
    monkeypatch.setenv("STATEMENT_DISPOSITION_MODE", "unsafe-default")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_AC_runtime_env_empty_values_2_settings_empty_env_resolution(monkeypatch, tmp_path) -> None:
    import src.config

    for k in ("LLM_API_KEY", "CORS_ORIGINS", "API_RATE_LIMIT_REQUESTS"):
        monkeypatch.setenv(k, "")
    s = Settings(_env_file=None)
    assert s.ai_api_key == "" and "http://localhost:3000" in s.cors_origins and s.api_rate_limit_requests == 300

    for k in ("LLM_API_KEY", "CORS_ORIGINS", "API_RATE_LIMIT_REQUESTS"):
        monkeypatch.delenv(k, raising=False)
    env_file = tmp_path / "test.env"
    env_file.write_text("LLM_API_KEY=\nCORS_ORIGINS=\nAPI_RATE_LIMIT_REQUESTS=\n", encoding="utf-8")
    dotenv_s = Settings(_env_file=str(env_file))
    assert (
        dotenv_s.ai_api_key == ""
        and "http://localhost:3000" in dotenv_s.cors_origins
        and dotenv_s.api_rate_limit_requests == 300
    )

    monkeypatch.setenv("DATABASE_URL", "")
    assert Settings(_env_file=None).database_url == ""

    orig = src.config.settings
    try:
        monkeypatch.setenv("API_RATE_LIMIT_REQUESTS", "")
        reloaded = importlib.reload(src.config)
        assert reloaded.settings.api_rate_limit_requests == 300
    finally:
        reloaded.settings = orig


def test_explicit_empty_cors_rate_limits_and_thresholds(monkeypatch) -> None:
    from pydantic.fields import FieldInfo

    assert _extract_env_candidate_names(FieldInfo(), "fallback_field") == ["fallback_field"]
    assert Settings._empty_cors_origins_is_none("   ") is None
    assert Settings._empty_cors_origins_is_none("http://localhost:3000") == "http://localhost:3000"
    assert (
        Settings._empty_rate_limits_use_default("", type("I", (), {"field_name": "api_rate_limit_requests"})()) == 300
    )

    s = Settings(_env_file=None, cors_origins_str="   ", api_rate_limit_requests="  ")
    assert "http://localhost:3000" in s.cors_origins and s.api_rate_limit_requests == 300

    for k, v in (
        ("TRUST_PROXY", "true"),
        ("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "92"),
        ("RECONCILIATION_REVIEW_THRESHOLD", "75"),
    ):
        monkeypatch.setenv(k, v)
    s2 = Settings(_env_file=None)
    assert (s2.trust_proxy, s2.reconciliation_auto_accept_threshold, s2.reconciliation_review_threshold) == (
        True,
        92,
        75,
    )

    monkeypatch.setenv("RECONCILIATION_AUTO_ACCEPT_THRESHOLD", "")
    monkeypatch.setenv("RECONCILIATION_REVIEW_THRESHOLD", "   ")
    s3 = Settings(_env_file=None)
    direct = Settings(_env_file=None, reconciliation_auto_accept_threshold="", reconciliation_review_threshold="  ")
    assert (s3.reconciliation_auto_accept_threshold, s3.reconciliation_review_threshold) == (None, None)
    assert (direct.reconciliation_auto_accept_threshold, direct.reconciliation_review_threshold) == (None, None)


def test_config_contracts_formats_pool_and_model_roles(monkeypatch) -> None:
    assert (
        settings.ai_provider == "zai"
        and settings.small_model.startswith("glm-")
        and re.match(r"^glm-[\d.a-z-]+", settings.small_model)
    )
    env_example = (Path(__file__).parents[4] / ".env.example").read_text()
    match = re.search(r"^LLM_SMALL_MODEL=(.+)$", env_example, re.MULTILINE)
    assert match and settings.small_model == match.group(1).strip()
    assert settings.base_currency.isalpha() and len(settings.base_currency) == 3 and settings.base_currency.isupper()
    assert 3 <= len(settings.s3_bucket) <= 63 and re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", settings.s3_bucket)
    assert settings.jwt_algorithm in {"HS256", "RS256"} and (
        "postgresql+asyncpg://" in settings.database_url or "sqlite" in settings.database_url
    )

    for k in ("DB_POOL_SIZE", "DB_POOL_MAX_OVERFLOW", "LLM_LARGE_MODEL", "LLM_SMALL_MODEL", "LLM_MULTIMODAL_MODEL"):
        monkeypatch.delenv(k, raising=False)
    for k in ("NEXT_PUBLIC_APP_URL", "OTEL_RESOURCE_ATTRIBUTES"):
        monkeypatch.setenv(k, "")
    s, sdk = Settings(_env_file=None), LlmSettings()
    assert (s.db_pool_size, s.db_pool_max_overflow) == (5, 10) and s.db_pool_size >= 1 and s.db_pool_max_overflow >= 0
    assert (s.large_model, s.small_model, s.multimodal_model) == (
        sdk.role_model("large"),
        sdk.role_model("small"),
        sdk.role_model("multimodal"),
    )
    assert all(field not in ENV_SOURCE_CLASSES for field in ("large_model", "small_model", "multimodal_model"))
    assert (s.next_public_app_url, s.otel_resource_attributes) == ("http://localhost:3000", None)

    monkeypatch.setenv("DB_POOL_SIZE", "20")
    monkeypatch.setenv("DB_POOL_MAX_OVERFLOW", "25")
    overridden = Settings()
    assert (overridden.db_pool_size, overridden.db_pool_max_overflow) == (20, 25)
