"""Migration shadow adapter from PromotionVerdict to causal TraceRecords."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from src.audit.base.promotion import InvariantResult, PromotionDecision
from src.audit.base.trace import (
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceRecord,
    TraceRecordType,
    TraceRecordValidationError,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.audit.ratio import Ratio

from .promotion import evaluate_promotion
from .trace_emitter import TraceEmitter


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionTraceContext:
    scope: TraceScope
    target: VersionedTraceRef
    execution_id: str
    evidence_manifest_digest: str
    occurred_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class PromotionTracePolicy:
    """Registered, replayable promotion policy and authority resolver."""

    policy_id: str
    required_invariants: tuple[str, ...]
    min_confidence: int
    confidence_label: str = "confidence"
    execution_stage: str = "github_ci.merge_authority"

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise TraceRecordValidationError("promotion policy_id is required")
        if not self.required_invariants or len(set(self.required_invariants)) != len(self.required_invariants):
            raise TraceRecordValidationError("promotion required_invariants must be non-empty and unique")
        if not 0 <= self.min_confidence <= 100:
            raise TraceRecordValidationError("promotion min_confidence must be within [0, 100]")

    @property
    def policy_digest(self) -> str:
        payload = {
            "confidence_label": self.confidence_label,
            "execution_stage": self.execution_stage,
            "min_confidence": self.min_confidence,
            "policy_id": self.policy_id,
            "required_invariants": list(self.required_invariants),
            "schema_version": "1",
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef(
            kind="promotion",
            id=self.policy_id,
            version=self.policy_digest,
        )

    @property
    def authority(self) -> TraceAuthorityProfile:
        return TraceAuthorityProfile(
            package="audit",
            tier="CODE-ONLY",
            proof_kind="exact",
            provenance="deterministic",
            execution_stage=self.execution_stage,
            assertion_owner_digest=self.policy_digest,
            producer_version=f"promotion-policy@{self.policy_digest[:16]}",
        )

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        # This policy proves the deterministic gate verdict. A consuming package
        # owns the separate policy that promotes an actual financial fact.
        return TraceTargetClass.GENERAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        expected = {("invariant", name, self.policy_digest) for name in self.required_invariants}
        expected.add(("confidence", self.confidence_label, self.policy_digest))
        actual = {(parent.assertion.kind, parent.assertion.id, parent.assertion.version) for parent in parents}
        if actual != expected or len(parents) != len(expected):
            raise TraceRecordValidationError("promotion parents do not match the registered required assertions")
        if any(
            parent.record_type is not TraceRecordType.OBSERVATION or parent.authority != self.authority
            for parent in parents
        ):
            raise TraceRecordValidationError("promotion parents must be observations from the registered authority")
        by_assertion = {parent.assertion: parent for parent in parents}
        invariants = [
            InvariantResult(
                name=name,
                passed=by_assertion[VersionedTraceRef("invariant", name, self.policy_digest)].result
                is TraceResult.PASS,
            )
            for name in self.required_invariants
        ]
        if any(
            by_assertion[VersionedTraceRef("invariant", name, self.policy_digest)].result
            not in {TraceResult.PASS, TraceResult.FAIL}
            for name in self.required_invariants
        ):
            raise TraceRecordValidationError("promotion invariant observations must pass or fail")
        confidence = by_assertion[VersionedTraceRef("confidence", self.confidence_label, self.policy_digest)]
        if confidence.result is not TraceResult.PASS or confidence.score is None:
            raise TraceRecordValidationError("promotion confidence observation must be a scored pass")
        confidence_rank = int(confidence.score.value * 100)
        verdict = evaluate_promotion(
            invariants,
            confidence_rank=confidence_rank,
            min_confidence=self.min_confidence,
            confidence_label=self.confidence_label,
        )
        result = {
            PromotionDecision.AUTHORITATIVE: TraceResult.AUTHORITATIVE,
            PromotionDecision.REVIEW: TraceResult.REVIEW,
            PromotionDecision.REJECTED: TraceResult.REJECTED,
        }[verdict.decision]
        return TraceDecisionOutcome(
            result=result,
            reason_code=f"promotion_{verdict.decision.value}",
            score=confidence.score,
        )


@dataclass(frozen=True, slots=True)
class PromotionTraceAdapter:
    """Build shadow records without changing the legacy verdict consumer."""

    policy: PromotionTracePolicy

    def records(
        self,
        context: PromotionTraceContext,
        invariants: list[InvariantResult],
        *,
        confidence_rank: int,
    ) -> list[TraceRecord]:
        if [invariant.name for invariant in invariants] != list(self.policy.required_invariants):
            raise TraceRecordValidationError("promotion inputs do not match the registered invariant order")
        if not 0 <= confidence_rank <= 100:
            raise TraceRecordValidationError("confidence_rank must be within [0, 100]")
        profile = self.policy.authority
        observations = [
            TraceRecord.observation(
                scope=context.scope,
                target=context.target,
                target_class=self.policy.target_class,
                assertion=VersionedTraceRef(
                    kind="invariant",
                    id=invariant.name,
                    version=self.policy.policy_digest,
                ),
                authority=profile,
                result=TraceResult.PASS if invariant.passed else TraceResult.FAIL,
                execution_id=context.execution_id,
                evidence_manifest_digest=context.evidence_manifest_digest,
                occurred_at=context.occurred_at,
                score=Ratio(Decimal("1" if invariant.passed else "0")),
                reason_code="invariant_passed" if invariant.passed else "invariant_failed",
            )
            for invariant in invariants
        ]
        observations.append(
            TraceRecord.observation(
                scope=context.scope,
                target=context.target,
                target_class=self.policy.target_class,
                assertion=VersionedTraceRef(
                    kind="confidence",
                    id=self.policy.confidence_label,
                    version=self.policy.policy_digest,
                ),
                authority=profile,
                result=TraceResult.PASS,
                execution_id=context.execution_id,
                evidence_manifest_digest=context.evidence_manifest_digest,
                occurred_at=context.occurred_at,
                score=Ratio(Decimal(confidence_rank) / Decimal("100")),
                reason_code="confidence_measured",
            )
        )
        decision = TraceRecord.decision(
            scope=context.scope,
            target=context.target,
            policy=self.policy,
            execution_id=context.execution_id,
            occurred_at=context.occurred_at,
            parents=observations,
        )
        return [*observations, decision]

    async def emit(
        self,
        context: PromotionTraceContext,
        invariants: list[InvariantResult],
        *,
        confidence_rank: int,
        emitter: TraceEmitter,
    ) -> tuple[TraceRecord, ...]:
        """Flush the complete shadow graph through an explicitly composed port."""
        records = self.records(
            context,
            invariants,
            confidence_rank=confidence_rank,
        )
        return await emitter.emit_many(records)
