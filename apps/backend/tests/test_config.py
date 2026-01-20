"""Tests for configuration helpers."""

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
