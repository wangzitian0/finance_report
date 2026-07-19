"""Runtime binding for the extraction-owned statement disposition policy."""

from __future__ import annotations

from src.config import settings
from src.extraction.base.disposition import (
    DispositionMode,
    DispositionPolicy,
    StatementDispositionPolicySnapshot,
)


def current_statement_disposition_policy_snapshot(
    *,
    mode: DispositionMode | None = None,
    policy: DispositionPolicy | None = None,
) -> StatementDispositionPolicySnapshot:
    """Capture the runtime facts that govern one disposition decision or package assembly."""
    effective_policy = policy or DispositionPolicy()
    effective_mode = mode if mode is not None else DispositionMode(settings.statement_disposition_mode)
    return StatementDispositionPolicySnapshot(
        schema_version="1",
        policy_version=effective_policy.version,
        mode=effective_mode,
        machine_confidence_threshold=effective_policy.authoritative_threshold,
        # P&L uses the same authoritative gate as all commands. Recording it
        # separately makes a future policy split observable rather than implicit.
        pnl_effect_confidence_threshold=effective_policy.authoritative_threshold,
        unknown_intent_outcome="review",
        ambiguous_intent_outcome="review",
        live_llm_proposals_enabled=settings.enable_ai_classification,
        deployment_git_sha=settings.git_commit_sha,
    )
