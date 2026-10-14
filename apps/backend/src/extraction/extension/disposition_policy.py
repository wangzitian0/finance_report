"""Runtime binding for the extraction-owned statement disposition policy."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.extraction.base.disposition import (
    DispositionMode,
    DispositionPolicy,
    StatementDispositionPolicySnapshot,
)
from src.extraction.extension.ai_settings import auto_accept_enabled

#: The version of the policy that accepts a suggestion at any score. The default policy keeps ``disposition-v1``.
AUTO_ACCEPT_POLICY_VERSION = "disposition-v1-accept-any-score"


def statement_disposition_policy(*, auto_accept: bool) -> DispositionPolicy:
    """The policy for one user. A user who lets the system accept the AI suggestions accepts them at any score (#2405).

    The classifier already refused a suggestion that cannot post, and it writes a general-account row for a
    row that it could not place. The score gate is therefore open. The snapshot records the threshold that ran.
    """
    if not auto_accept:
        return DispositionPolicy()
    # One version string names one threshold: the recorded version tells which gate ran.
    return DispositionPolicy(version=AUTO_ACCEPT_POLICY_VERSION, authoritative_threshold=Decimal("0"))


async def statement_disposition_policy_for_user(db: AsyncSession, user_id: UUID) -> DispositionPolicy:
    """The policy that posting uses for this user: the setting ``auto_accept_ai_suggestions`` decides the score gate."""
    return statement_disposition_policy(auto_accept=await auto_accept_enabled(db, user_id))


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
