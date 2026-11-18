"""Pure AI preference evaluation over per-user override mappings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AiSettingsDefaults:
    """Process-level ceilings and defaults supplied by the extension/app layer."""

    enable_ai_reconciliation: bool = True
    enable_ai_classification: bool = True
    auto_accept_ai_suggestions: bool = True


def evaluate_reconciliation_enabled(
    overrides: Mapping[str, object] | None,
    *,
    default: bool,
) -> bool:
    """Evaluate the reconciliation flag with the per-user boolean override on top."""
    raw = (overrides or {}).get("enable_ai_reconciliation")
    if isinstance(raw, bool):
        return raw
    return default


def evaluate_classification_enabled(
    overrides: Mapping[str, object] | None,
    *,
    default: bool,
) -> bool:
    """Evaluate the AI classification flag with the per-user override on top."""
    return bool((overrides or {}).get("enable_ai_classification", default))


def evaluate_auto_accept_preference(overrides: Mapping[str, object] | None) -> bool:
    """Evaluate what the user chose for ``auto_accept_ai_suggestions``."""
    return bool((overrides or {}).get("auto_accept_ai_suggestions", True))


def evaluate_effective_auto_accept(
    overrides: Mapping[str, object] | None,
    *,
    defaults: AiSettingsDefaults,
) -> bool:
    """Evaluate whether automatic acceptance is active under process ceiling and classification."""
    return (
        defaults.auto_accept_ai_suggestions
        and evaluate_auto_accept_preference(overrides)
        and evaluate_classification_enabled(overrides, default=defaults.enable_ai_classification)
    )
