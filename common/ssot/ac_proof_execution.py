"""AC proof execution placement vocabulary.

This module keeps the runtime helper vocabulary aligned with the CI/CD SSOT:
the AC remains the only coverage key, while each proof edge may carry placement
metadata describing where it runs and which job family executes it.
"""

from __future__ import annotations

from typing import Any

PROOF_EXECUTION_STAGES = (
    "local.advisory",
    "github_ci.merge_authority",
    "preview.runtime",
    "staging.release_validation",
    "staging.provider_regression",
    "prod.release_integrity",
    "ops.scheduled_cleanup",
    "manual.adjudication",
)

PROOF_TASK_CATEGORIES = (
    "aggregate",
    "classify",
    "static_contract",
    "ac_traceability",
    "backend_unit",
    "backend_integration",
    "backend_api_e2e",
    "frontend_build",
    "frontend_unit",
    "frontend_browser_e2e",
    "image_build",
    "tooling_contract",
    "coverage_fan_in",
    "behavioral_ratchet",
    "deploy_smoke",
    "provider_gate",
    "release_integrity",
    "cleanup_retention",
    "critical_behavioral",
    "manual_evidence",
)

LEGACY_CI_TIER_TO_STAGE = {
    "pr_ci": "github_ci.merge_authority",
    "post_merge_environment": "staging.release_validation",
    "manual": "manual.adjudication",
}

SCOPE_TO_TASK_CATEGORY = {
    "behavioral": "critical_behavioral",
    "static_contract": "static_contract",
    "manual_gate": "manual_evidence",
}


def _validate_known(value: str, *, field: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        expected = ", ".join(allowed)
        raise ValueError(
            f"unknown AC proof {field} {value!r}; expected one of: {expected}"
        )
    return value


def stage_for_ci_tier(ci_tier: str) -> str:
    """Return the stage implied by a legacy critical-proof ``ci_tier`` value."""
    return LEGACY_CI_TIER_TO_STAGE.get(ci_tier, "")


def task_category_for_scope(scope: str) -> str:
    """Return the default task category implied by a proof scope."""
    return SCOPE_TO_TASK_CATEGORY.get(scope, "critical_behavioral")


def normalize_proof_execution(fields: dict[str, Any]) -> tuple[str, str]:
    """Return ``(stage, task_category)`` for a proof metadata mapping.

    Explicit ``stage`` / ``task_category`` values win. Legacy ``ci_tier`` and
    ``scope`` remain accepted compatibility inputs, so existing ``@ac_proof``
    declarations gain placement metadata without changing their validation
    semantics.
    """
    stage = str(
        fields.get("stage") or stage_for_ci_tier(str(fields.get("ci_tier", "")))
    )
    task_category = str(
        fields.get("task_category")
        or task_category_for_scope(str(fields.get("scope", "behavioral")))
    )
    return (
        _validate_known(stage, field="stage", allowed=PROOF_EXECUTION_STAGES),
        _validate_known(
            task_category, field="task_category", allowed=PROOF_TASK_CATEGORIES
        ),
    )
