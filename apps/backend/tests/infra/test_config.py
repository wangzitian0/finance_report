"""Tests for configuration helpers."""

import pytest
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


_EMPTY_SAFETY_KEYS = (
    "ZAI_API_KEY",
    "GLM_API_KEY",
    "AI_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "CORS_ORIGINS",
    "API_RATE_LIMIT_REQUESTS",
)


def test_AC_runtime_18_7_empty_env_values_fall_through_to_defaults(monkeypatch, tmp_path) -> None:
    """AC-runtime.18.7: ``env_ignore_empty=True`` — an empty value is "unset", never a blank setting.

    Before this, a compose ``${VAR:-}`` line or a blank ``.env`` entry could
    (a) win the ``ai_api_key`` alias race with ``""`` even though ``GEMINI_API_KEY``
    carried a real key, (b) turn ``CORS_ORIGINS=""`` into an *empty* origin list
    instead of the default list, and (c) crash import on
    ``API_RATE_LIMIT_REQUESTS=""`` (not an int). In the installed pydantic-settings
    (2.12) ``env_ignore_empty`` applies to the dotenv source as well as
    ``os.environ`` — ``DotEnvSettingsSource`` hands it to ``parse_env_vars`` for
    the file's values — so the same three cases are exercised through a ``.env``
    file below, after being proven against monkeypatched ``os.environ`` with
    ``_env_file=None``.
    """
    for key in _EMPTY_SAFETY_KEYS:
        monkeypatch.delenv(key, raising=False)
    baseline = Settings(_env_file=None)
    assert baseline.cors_origins, "default origin list must be non-empty for this proof to bite"

    monkeypatch.setenv("ZAI_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("CORS_ORIGINS", "")
    monkeypatch.setenv("API_RATE_LIMIT_REQUESTS", "")
    from_environ = Settings(_env_file=None)

    assert from_environ.ai_api_key == "gemini-key"
    assert from_environ.cors_origins_str is None
    assert from_environ.cors_origins == baseline.cors_origins
    assert from_environ.api_rate_limit_requests == baseline.api_rate_limit_requests == 300

    for key in _EMPTY_SAFETY_KEYS:
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        'ZAI_API_KEY=\nGEMINI_API_KEY=gemini-key\nCORS_ORIGINS=""\nAPI_RATE_LIMIT_REQUESTS=\n',
        encoding="utf-8",
    )
    from_dotenv = Settings(_env_file=env_file)

    assert from_dotenv.ai_api_key == "gemini-key"
    assert from_dotenv.cors_origins == baseline.cors_origins
    assert from_dotenv.api_rate_limit_requests == 300


def test_statement_disposition_mode_is_closed_configuration(monkeypatch) -> None:
    monkeypatch.setenv("STATEMENT_DISPOSITION_MODE", "observe")
    assert Settings(_env_file=None).statement_disposition_mode == "observe"

    monkeypatch.setenv("STATEMENT_DISPOSITION_MODE", "unsafe-default")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
