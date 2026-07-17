"""AC-audit.trace-record.3: promotion shadow has explicit causal persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.audit import (
    InvariantResult,
    PromotionTraceAdapter,
    PromotionTraceContext,
    PromotionTracePolicy,
    TraceEmitter,
    TraceRecordType,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)


def test_promotion_shadow_emits_observations_and_a_causal_decision():
    context = PromotionTraceContext(
        scope=TraceScope.tenant(uuid4()),
        target=VersionedTraceRef(kind="financial_fact", id="fact-1", version="v1"),
        execution_id="promotion-run-1",
        evidence_manifest_digest="a" * 64,
        occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
    )
    invariants = [InvariantResult(name="balance_chain", passed=False)]
    policy = PromotionTracePolicy(
        policy_id="deterministic-promotion-gate",
        required_invariants=("balance_chain",),
        min_confidence=0,
    )

    records = PromotionTraceAdapter(policy).records(
        context,
        invariants,
        confidence_rank=100,
    )

    assert records[0].record_type is TraceRecordType.OBSERVATION
    assert records[0].result is TraceResult.FAIL
    assert records[-1].record_type is TraceRecordType.DECISION
    assert records[-1].target_class is TraceTargetClass.GENERAL
    assert records[-1].result is TraceResult.REJECTED
    assert set(records[-1].parent_ids) == {
        records[0].record_id,
        records[1].record_id,
    }


async def test_promotion_shadow_uses_explicit_emitter_and_fails_closed():
    context = PromotionTraceContext(
        scope=TraceScope.tenant(uuid4()),
        target=VersionedTraceRef(kind="promotion_candidate", id="candidate-1", version="v1"),
        execution_id="promotion-run-1",
        evidence_manifest_digest="a" * 64,
        occurred_at=datetime(2026, 7, 17, tzinfo=UTC),
    )
    adapter = PromotionTraceAdapter(
        PromotionTracePolicy(
            policy_id="deterministic-promotion-gate",
            required_invariants=("balance_chain",),
            min_confidence=80,
        )
    )
    repository = AsyncMock()
    repository.append.side_effect = [
        adapter.records(
            context,
            [InvariantResult(name="balance_chain", passed=True)],
            confidence_rank=90,
        )[0],
        RuntimeError("flush failed"),
    ]

    with pytest.raises(RuntimeError, match="flush failed"):
        await adapter.emit(
            context,
            [InvariantResult(name="balance_chain", passed=True)],
            confidence_rank=90,
            emitter=TraceEmitter(repository),
        )

    assert repository.append.await_count == 2
