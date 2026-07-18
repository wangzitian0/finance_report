"""Decision-backed valuation inputs published to report-package consumers.

Pricing owns the storage transition and selection policy for valuations.  A
consumer receives this DTO rather than a raw manual-valuation, override, or
market-price row, so source labels and freshness metadata cannot be mistaken
for authority outside this package.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    TraceAuthorityProfile,
    TraceCausality,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceEmitter,
    TraceLineage,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.audit.extension.trace_repository import SqlTraceRecordRepository
from src.pricing.base.contribution import ResolvedValuationContribution, resolution_policy_identity
from src.pricing.base.errors import NoObservationError
from src.pricing.base.observation import (
    Authority,
    ObservationSource,
    PriceObservation,
    pricing_valuation_lineage_id,
)
from src.pricing.base.policy import ResolutionPolicy
from src.pricing.base.subject import PriceableSubject
from src.pricing.extension.repository import SqlObservationRepository
from src.pricing.extension.resolve import resolve

_OBSERVATION_ASSERTION = VersionedTraceRef("pricing_valuation_input", "selected-observation", "1")


def _digest(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _authority(*, provenance: str, stage: str, producer_version: str) -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package="pricing",
        tier="CODE-LED",
        proof_kind="property",
        provenance=provenance,
        execution_stage=stage,
        assertion_owner_digest=_digest(
            {
                "package": "pricing",
                "policy": "valuation-attestation",
                "producer_version": producer_version,
            }
        ),
        producer_version=producer_version,
    )


def _system_authority() -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package="pricing",
        tier="CODE-ONLY",
        proof_kind="exact",
        provenance="deterministic",
        execution_stage="product.runtime",
        assertion_owner_digest=_digest(
            {
                "package": "pricing",
                "policy": "resolved-market-valuation",
                "producer_version": "1",
            }
        ),
        producer_version="1",
    )


@dataclass(frozen=True, slots=True)
class ManualValuationAttestationPolicy:
    """A human-entered valuation is usable only after its exact fact is attested."""

    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef("pricing_valuation_attestation", "manual-or-override", "1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return _authority(provenance="manual", stage="manual.adjudication", producer_version="1")

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        valid = len(parents) == 1 and parents[0].result is TraceResult.PASS
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            "manual_valuation_attested" if valid else "manual_valuation_attestation_invalid",
        )


@dataclass(frozen=True, slots=True)
class ResolvedMarketValuationPolicy:
    """Authorizes the exact pricing-policy selection, not a provider label."""

    @property
    def assertion(self) -> VersionedTraceRef:
        return VersionedTraceRef("pricing_valuation_selection", "resolved-market-observation", "1")

    @property
    def authority(self) -> TraceAuthorityProfile:
        return _system_authority()

    @property
    def causality(self) -> TraceCausality:
        return TraceCausality.DIRECT

    @property
    def target_class(self) -> TraceTargetClass:
        return TraceTargetClass.FINANCIAL

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        valid = len(parents) == 1 and parents[0].result is TraceResult.PASS
        return TraceDecisionOutcome(
            TraceResult.AUTHORITATIVE if valid else TraceResult.REJECTED,
            "resolved_market_valuation_selected" if valid else "resolved_market_valuation_invalid",
        )


def pricing_trace_policy_registry() -> TraceDecisionPolicyRegistry:
    """The registry required to restore pricing-owned valuation decisions."""
    return TraceDecisionPolicyRegistry((ManualValuationAttestationPolicy(), ResolvedMarketValuationPolicy()))


def valuation_observation_version(observation: PriceObservation) -> str:
    """Digest the exact observation version selected for package use."""
    return _digest(
        {
            "as_of": observation.as_of.isoformat(),
            "currency": observation.currency,
            "id": str(observation.id),
            "observed_at": observation.observed_at.astimezone(UTC).isoformat(),
            "source": observation.source.value,
            "subject_key": observation.subject.key,
            "subject_kind": observation.subject.kind.value,
            "value": format(observation.value, "f"),
        }
    )


def manual_valuation_target(observation: PriceObservation) -> VersionedTraceRef:
    """Pin a manual/override decision to one immutable valuation observation."""
    if observation.lineage_id is None:
        raise ValueError("manual valuation observation is missing its stable pricing lineage")
    return VersionedTraceRef(
        kind="pricing_valuation",
        id=observation.lineage_id,
        version=valuation_observation_version(observation),
    )


def resolved_market_valuation_target(
    *,
    subject: PriceableSubject,
    requested_as_of: date,
    policy: ResolutionPolicy,
    observation: PriceObservation,
) -> VersionedTraceRef:
    """Pin a deterministic market selection to its subject/date/policy and value."""
    policy_id = resolution_policy_identity(policy)
    return VersionedTraceRef(
        kind="pricing_resolved_valuation",
        id="pricing-resolution:"
        + _digest(
            {
                "policy": policy_id,
                "requested_as_of": requested_as_of.isoformat(),
                "subject_key": subject.key,
                "subject_kind": subject.kind.value,
            }
        ),
        version=_digest(
            {
                "observation_version": valuation_observation_version(observation),
                "policy": policy_id,
            }
        ),
    )


def _unproven(
    *,
    subject: PriceableSubject,
    as_of: date,
    policy: ResolutionPolicy,
    reason_code: str,
    observation: PriceObservation | None = None,
) -> ResolvedValuationContribution:
    return ResolvedValuationContribution(
        subject=subject,
        requested_as_of=as_of,
        resolution_policy=resolution_policy_identity(policy),
        state="unproven",
        reason_code=reason_code,
        lineage_id=observation.lineage_id if observation else None,
        observation_id=observation.id if observation else None,
        observation_version=valuation_observation_version(observation) if observation else None,
        observation_as_of=observation.as_of if observation else None,
        value=observation.value if observation else None,
        currency=observation.currency if observation else None,
        source=observation.source if observation else None,
        decision_id=None,
    )


async def emit_manual_valuation_decision(
    db: AsyncSession,
    *,
    user_id: UUID,
    observation: PriceObservation,
) -> UUID:
    """Append the observation and its replacement decision in the caller UoW."""
    target = manual_valuation_target(observation)
    policy = ManualValuationAttestationPolicy()
    repository = SqlTraceRecordRepository(db, pricing_trace_policy_registry())
    scope = TraceScope.tenant(user_id)
    current = await repository.current_decision(scope, TraceLineage.from_refs(target, policy.assertion))
    if current is not None and current.target.version == target.version and current.result is TraceResult.AUTHORITATIVE:
        return current.record_id

    previous_decision_id = None
    if current is not None:
        if len(current.parent_ids) != 1:
            raise ValueError("manual valuation decision must have exactly one input observation")
        previous_decision_id = current.record_id

    occurred_at = datetime.now(UTC)
    execution_id = f"pricing-valuation:{target.id}:{target.version}"
    observation_record = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=_OBSERVATION_ASSERTION,
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=target.version,
        occurred_at=occurred_at,
        score=None,
        reason_code="manual_valuation_recorded",
        # A replacement decision supersedes the prior decision. The old
        # observation remains immutable historical evidence; superseding it
        # first would briefly leave the old decision without a current parent
        # and violates the database's causal-graph invariant.
        supersedes_id=None,
    )
    decision = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=policy,
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(observation_record,),
        supersedes_id=previous_decision_id,
    )
    return (await TraceEmitter(repository).emit_many((observation_record, decision)))[-1].record_id


async def _resolved_market_contribution(
    db: AsyncSession,
    *,
    user_id: UUID,
    subject: PriceableSubject,
    requested_as_of: date,
    policy: ResolutionPolicy,
    observation: PriceObservation,
) -> ResolvedValuationContribution:
    """Append or read the decision for one exact non-manual price selection."""
    target = resolved_market_valuation_target(
        subject=subject,
        requested_as_of=requested_as_of,
        policy=policy,
        observation=observation,
    )
    decision_policy = ResolvedMarketValuationPolicy()
    scope = TraceScope.tenant(user_id)
    repository = SqlTraceRecordRepository(db, pricing_trace_policy_registry())
    current = await repository.current_decision(scope, TraceLineage.from_refs(target, decision_policy.assertion))
    if current is not None and current.target == target and current.result is TraceResult.AUTHORITATIVE:
        decision = current
    else:
        occurred_at = datetime.now(UTC)
        execution_id = f"pricing-resolution:{target.id}:{target.version}"
        selection = TraceRecord.observation(
            scope=scope,
            target=target,
            target_class=TraceTargetClass.FINANCIAL,
            assertion=_OBSERVATION_ASSERTION,
            authority=decision_policy.authority,
            result=TraceResult.PASS,
            execution_id=execution_id,
            evidence_manifest_digest=valuation_observation_version(observation),
            occurred_at=occurred_at,
            score=None,
            reason_code="pricing_observation_selected",
        )
        decision = TraceRecord.decision(
            scope=scope,
            target=target,
            policy=decision_policy,
            execution_id=execution_id,
            occurred_at=occurred_at,
            parents=(selection,),
            supersedes_id=current.record_id if current is not None else None,
        )
        decision = (await TraceEmitter(repository).emit_many((selection, decision)))[-1]
    return ResolvedValuationContribution(
        subject=subject,
        requested_as_of=requested_as_of,
        resolution_policy=resolution_policy_identity(policy),
        state="authoritative",
        reason_code=None,
        lineage_id=observation.lineage_id,
        observation_id=observation.id,
        observation_version=valuation_observation_version(observation),
        observation_as_of=observation.as_of,
        value=observation.value,
        currency=observation.currency,
        source=observation.source,
        decision_id=decision.record_id,
    )


async def resolve_valuation_contribution(
    db: AsyncSession,
    *,
    user_id: UUID,
    subject: PriceableSubject,
    as_of: date,
    policy: ResolutionPolicy,
) -> ResolvedValuationContribution:
    """Resolve one valuation and expose only an exact current authority decision.

    Manual and override candidates must already carry the decision emitted by
    their write path. This deliberately rejects legacy rows: a source/basis
    label cannot recover trust. For provider and statement observations, this
    boundary emits the deterministic selection decision that pins the exact
    candidate and requested policy.
    """
    candidates = await SqlObservationRepository(db).candidates(subject, as_of, user_id=user_id)
    try:
        observation = resolve(subject, as_of, policy, candidates)
    except NoObservationError:
        return _unproven(subject=subject, as_of=as_of, policy=policy, reason_code="no_eligible_observation")

    if observation.source not in {ObservationSource.MANUAL, ObservationSource.OVERRIDE}:
        return await _resolved_market_contribution(
            db,
            user_id=user_id,
            subject=observation.subject,
            requested_as_of=as_of,
            policy=policy,
            observation=observation,
        )

    return await _manual_observation_contribution(
        db,
        user_id=user_id,
        observation=observation,
        as_of=as_of,
        policy=policy,
    )


async def _manual_observation_contribution(
    db: AsyncSession,
    *,
    user_id: UUID,
    observation: PriceObservation,
    as_of: date,
    policy: ResolutionPolicy,
) -> ResolvedValuationContribution:
    """Validate one exact manual lineage head independently of sibling assets."""
    try:
        resolve(observation.subject, as_of, policy, [observation])
        target = manual_valuation_target(observation)
    except (NoObservationError, ValueError):
        return _unproven(
            subject=observation.subject,
            as_of=as_of,
            policy=policy,
            reason_code="missing_or_ineligible_observation_decision",
            observation=observation,
        )
    policy_record = ManualValuationAttestationPolicy()
    repository = SqlTraceRecordRepository(db, pricing_trace_policy_registry())
    decision = await repository.current_decision(
        TraceScope.tenant(user_id),
        TraceLineage.from_refs(target, policy_record.assertion),
    )
    if decision is None or decision.result is not TraceResult.AUTHORITATIVE or decision.target != target:
        return _unproven(
            subject=observation.subject,
            as_of=as_of,
            policy=policy,
            reason_code="missing_observation_decision",
            observation=observation,
        )
    return ResolvedValuationContribution(
        subject=observation.subject,
        requested_as_of=as_of,
        resolution_policy=resolution_policy_identity(policy),
        state="authoritative",
        reason_code=None,
        lineage_id=observation.lineage_id,
        observation_id=observation.id,
        observation_version=target.version,
        observation_as_of=observation.as_of,
        value=observation.value,
        currency=observation.currency,
        source=observation.source,
        decision_id=decision.record_id,
    )


async def resolve_manual_valuation_contributions(
    db: AsyncSession,
    *,
    user_id: UUID,
    as_of: date,
    policy: ResolutionPolicy,
) -> tuple[ResolvedValuationContribution, ...]:
    """Resolve each current component/source lineage selected for package use."""
    from src.extraction.orm.layer3 import ManualValuationSnapshot

    rows = (
        (
            await db.execute(
                select(ManualValuationSnapshot)
                .where(ManualValuationSnapshot.user_id == user_id)
                .where(ManualValuationSnapshot.as_of_date <= as_of)
                .where(ManualValuationSnapshot.superseded_by_id.is_(None))
                .order_by(
                    ManualValuationSnapshot.component_type,
                    ManualValuationSnapshot.source,
                    ManualValuationSnapshot.as_of_date.desc(),
                    ManualValuationSnapshot.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    selected: dict[tuple[str, str], ManualValuationSnapshot] = {}
    for row in rows:
        selected.setdefault((row.component_type.value, row.source), row)

    contributions = []
    for row in selected.values():
        subject = PriceableSubject.component(row.component_type.value)
        observation = PriceObservation(
            id=row.id,
            subject=subject,
            value=row.value,
            as_of=row.as_of_date,
            observed_at=row.created_at,
            source=ObservationSource.MANUAL,
            authority=Authority.MANUAL,
            currency=row.currency,
            lineage_id=pricing_valuation_lineage_id(
                subject=subject,
                source=row.source,
                as_of=row.as_of_date,
            ),
        )
        contributions.append(
            await _manual_observation_contribution(
                db,
                user_id=user_id,
                observation=observation,
                as_of=as_of,
                policy=policy,
            )
        )
    return tuple(contributions)
