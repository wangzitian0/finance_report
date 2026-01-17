"""Tests for configuration helpers."""

from src.config import parse_comma_list


def test_parse_comma_list_defaults() -> None:
    assert parse_comma_list(None, ["a"]) == ["a"]


def test_parse_comma_list_accepts_list() -> None:
    assert parse_comma_list(["x", "y"], ["a"]) == ["x", "y"]


def test_parse_comma_list_splits_string() -> None:
    assert parse_comma_list("x, y, ,z", ["a"]) == ["x", "y", "z"]
