"""Pure unit tests for AI settings evaluation without DB or global settings mutation."""

from __future__ import annotations

import pytest

from src.extraction.base.ai_settings import (
    AiSettingsDefaults,
    evaluate_auto_accept_preference,
    evaluate_classification_enabled,
    evaluate_effective_auto_accept,
    evaluate_reconciliation_enabled,
)

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("overrides", "default", "expected"),
    [
        (None, False, False),
        ({}, True, True),
        ({"enable_ai_reconciliation": "yes"}, False, False),
        ({"enable_ai_reconciliation": True}, False, True),
        ({"enable_ai_reconciliation": False}, True, False),
    ],
)
def test_evaluate_reconciliation_enabled_honors_boolean_override(
    overrides: dict[str, object] | None, default: bool, expected: bool
) -> None:
    assert evaluate_reconciliation_enabled(overrides, default=default) is expected


@pytest.mark.parametrize(
    ("overrides", "defaults", "expected_preference", "expected_effective"),
    [
        ({}, AiSettingsDefaults(True, True, True), True, True),
        ({}, AiSettingsDefaults(True, True, False), True, False),
        ({"enable_ai_classification": False}, AiSettingsDefaults(True, True, True), True, False),
        ({"auto_accept_ai_suggestions": False}, AiSettingsDefaults(True, True, True), False, False),
        (
            {"enable_ai_classification": True, "auto_accept_ai_suggestions": True},
            AiSettingsDefaults(True, False, True),
            True,
            True,
        ),
    ],
)
def test_evaluate_effective_auto_accept_truth_table(
    overrides: dict[str, object],
    defaults: AiSettingsDefaults,
    expected_preference: bool,
    expected_effective: bool,
) -> None:
    assert evaluate_auto_accept_preference(overrides) is expected_preference
    assert evaluate_effective_auto_accept(overrides, defaults=defaults) is expected_effective
    assert evaluate_classification_enabled(overrides, default=defaults.enable_ai_classification) is bool(
        overrides.get("enable_ai_classification", defaults.enable_ai_classification)
    )
