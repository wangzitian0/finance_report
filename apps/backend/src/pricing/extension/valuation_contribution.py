"""Decision-backed valuation inputs published to report-package consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import (
    DeclarativeTracePolicy,
    SqlTraceRecordRepository,
    TraceAuthorityProfile,
    TraceDecisionPolicyRegistry,
    TraceDecisionRef,
    TraceEmitter,
    TraceLineage,
    TraceRecord,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
    canonical_json_digest,
)
from src.pricing.base.contribution import (
    MarketValuationSelection,
    ResolvedValuationContribution,
    resolution_policy_identity,
)
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


def _pricing_auth(tier: str, proof: str, prov: str, stage: str, policy_name: str) -> TraceAuthorityProfile:
    return TraceAuthorityProfile(
        package="pricing",
        tier=tier,
        proof_kind=proof,
        provenance=prov,
        execution_stage=stage,
        assertion_owner_digest=canonical_json_digest(
            {"package": "pricing", "policy": policy_name, "producer_version": "1"}, default=str
        ),
        producer_version="1",
    )


@dataclass(frozen=True, slots=True)
class ManualValuationAttestationPolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("pricing_valuation_attestation", "manual-or-override", "1")
    )
    authority: TraceAuthorityProfile = field(
        default_factory=lambda: _pricing_auth(
            "CODE-LED", "property", "manual", "manual.adjudication", "valuation-attestation"
        )
    )
    pass_reason: str = "manual_valuation_attested"
    fail_reason: str = "manual_valuation_attestation_invalid"


@dataclass(frozen=True, slots=True)
class ResolvedMarketValuationPolicy(DeclarativeTracePolicy):
    assertion: VersionedTraceRef = field(
        default_factory=lambda: VersionedTraceRef("pricing_valuation_selection", "resolved-market-observation", "1")
    )
    authority: TraceAuthorityProfile = field(
        default_factory=lambda: _pricing_auth(
            "CODE-ONLY", "exact", "deterministic", "product.runtime", "resolved-market-valuation"
        )
    )
    pass_reason: str = "resolved_market_valuation_selected"
    fail_reason: str = "resolved_market_valuation_invalid"


def pricing_trace_policy_registry() -> TraceDecisionPolicyRegistry:
    return TraceDecisionPolicyRegistry((ManualValuationAttestationPolicy(), ResolvedMarketValuationPolicy()))


def valuation_observation_version(observation: PriceObservation) -> str:
    return canonical_json_digest(
        {
            "as_of": observation.as_of.isoformat(),
            "currency": observation.currency,
            "id": str(observation.id),
            "observed_at": observation.observed_at.astimezone(UTC).isoformat(),
            "source": observation.source.value,
            "subject_key": observation.subject.key,
            "subject_kind": observation.subject.kind.value,
            "value": format(observation.value, "f"),
        },
        default=str,
    )


def manual_valuation_target(observation: PriceObservation) -> VersionedTraceRef:
    if observation.lineage_id is None:
        raise ValueError("manual valuation observation is missing its stable pricing lineage")
    return VersionedTraceRef("pricing_valuation", observation.lineage_id, valuation_observation_version(observation))


def resolved_market_valuation_target(
    *, subject: PriceableSubject, requested_as_of: date, policy: ResolutionPolicy, observation: PriceObservation
) -> VersionedTraceRef:
    policy_id = resolution_policy_identity(policy)
    return VersionedTraceRef(
        kind="pricing_resolved_valuation",
        id="pricing-resolution:"
        + canonical_json_digest(
            {
                "policy": policy_id,
                "requested_as_of": requested_as_of.isoformat(),
                "subject_key": subject.key,
                "subject_kind": subject.kind.value,
            },
            default=str,
        ),
        version=canonical_json_digest(
            {"observation_version": valuation_observation_version(observation), "policy": policy_id}, default=str
        ),
    )


def _build_contribution(
    *,
    subject: PriceableSubject,
    as_of: date,
    policy: ResolutionPolicy,
    state: str,
    reason_code: str | None = None,
    observation: PriceObservation | None = None,
    observation_version: str | None = None,
    decision: TraceRecord | None = None,
    component_type: str | None = None,
    valuation_basis: str | None = None,
    liquidity_class: str | None = None,
) -> ResolvedValuationContribution:
    obs_ver = observation_version or (valuation_observation_version(observation) if observation else None)
    return ResolvedValuationContribution(
        subject=subject,
        requested_as_of=as_of,
        resolution_policy=resolution_policy_identity(policy),
        state=state,  # type: ignore[arg-type]
        reason_code=reason_code,
        lineage_id=observation.lineage_id if observation else None,
        observation_id=observation.id if observation else None,
        observation_version=obs_ver,
        observation_as_of=observation.as_of if observation else None,
        value=observation.value if observation else None,
        currency=observation.currency if observation else None,
        source=observation.source if observation else None,
        decision=TraceDecisionRef(decision.record_id, decision.target, decision.assertion) if decision else None,
        component_type=component_type,
        valuation_basis=valuation_basis,
        liquidity_class=liquidity_class,
    )


def _unproven(
    *,
    subject: PriceableSubject,
    as_of: date,
    policy: ResolutionPolicy,
    reason_code: str,
    observation: PriceObservation | None = None,
    component_type: str | None = None,
    valuation_basis: str | None = None,
    liquidity_class: str | None = None,
) -> ResolvedValuationContribution:
    return _build_contribution(
        subject=subject,
        as_of=as_of,
        policy=policy,
        state="unproven",
        reason_code=reason_code,
        observation=observation,
        component_type=component_type,
        valuation_basis=valuation_basis,
        liquidity_class=liquidity_class,
    )


async def _emit_single_input_decision(
    repository: SqlTraceRecordRepository,
    *,
    scope: TraceScope,
    target: VersionedTraceRef,
    policy: DeclarativeTracePolicy,
    execution_id: str,
    evidence_digest: str,
    obs_reason: str,
    supersedes_id: UUID | None,
) -> TraceRecord:
    occurred_at = datetime.now(UTC)
    obs = TraceRecord.observation(
        scope=scope,
        target=target,
        target_class=TraceTargetClass.FINANCIAL,
        assertion=_OBSERVATION_ASSERTION,
        authority=policy.authority,
        result=TraceResult.PASS,
        execution_id=execution_id,
        evidence_manifest_digest=evidence_digest,
        occurred_at=occurred_at,
        score=None,
        reason_code=obs_reason,
        supersedes_id=None,
    )
    dec = TraceRecord.decision(
        scope=scope,
        target=target,
        policy=policy,
        execution_id=execution_id,
        occurred_at=occurred_at,
        parents=(obs,),
        supersedes_id=supersedes_id,
    )
    return (await TraceEmitter(repository).emit_many((obs, dec)))[-1]


async def emit_manual_valuation_decision(
    db: AsyncSession, *, user_id: UUID, observation: PriceObservation
) -> UUID:
    target = manual_valuation_target(observation)
    policy = ManualValuationAttestationPolicy()
    repository = SqlTraceRecordRepository(db, pricing_trace_policy_registry())
    scope = TraceScope.tenant(user_id)
    head = await repository.decision_head(scope, TraceLineage.from_refs(target, policy.assertion))
    current = head.record if head is not None and head.ancestry_current else None
    if current is not None and current.target.version == target.version and current.result is TraceResult.AUTHORITATIVE:
        return current.record_id
    if head is not None and len(head.record.parent_ids) != 1:
        raise ValueError("manual valuation decision must have exactly one input observation")
    decision = await _emit_single_input_decision(
        repository,
        scope=scope,
        target=target,
        policy=policy,
        execution_id=f"pricing-valuation:{target.id}:{target.version}",
        evidence_digest=target.version,
        obs_reason="manual_valuation_recorded",
        supersedes_id=head.record.record_id if head is not None else None,
    )
    return decision.record_id


async def _resolved_market_contribution(
    db: AsyncSession,
    *,
    user_id: UUID,
    subject: PriceableSubject,
    requested_as_of: date,
    policy: ResolutionPolicy,
    observation: PriceObservation,
) -> ResolvedValuationContribution:
    target = resolved_market_valuation_target(
        subject=subject, requested_as_of=requested_as_of, policy=policy, observation=observation
    )
    decision_policy = ResolvedMarketValuationPolicy()
    scope = TraceScope.tenant(user_id)
    repository = SqlTraceRecordRepository(db, pricing_trace_policy_registry())
    head = await repository.decision_head(scope, TraceLineage.from_refs(target, decision_policy.assertion))
    if head is not None and not head.ancestry_current:
        return _unproven(
            subject=subject,
            as_of=requested_as_of,
            policy=policy,
            reason_code="stale_observation_decision",
            observation=observation,
        )
    current = head.record if head is not None else None
    obs_ver = valuation_observation_version(observation)
    if current is not None and current.target == target and current.result is TraceResult.AUTHORITATIVE:
        decision = current
    else:
        decision = await _emit_single_input_decision(
            repository,
            scope=scope,
            target=target,
            policy=decision_policy,
            execution_id=f"pricing-resolution:{target.id}:{target.version}",
            evidence_digest=obs_ver,
            obs_reason="pricing_observation_selected",
            supersedes_id=current.record_id if current is not None else None,
        )
    return _build_contribution(
        subject=subject,
        as_of=requested_as_of,
        policy=policy,
        state="authoritative",
        observation=observation,
        observation_version=obs_ver,
        decision=decision,
    )


async def resolve_valuation_contribution(
    db: AsyncSession, *, user_id: UUID, subject: PriceableSubject, as_of: date, policy: ResolutionPolicy
) -> ResolvedValuationContribution:
    candidates = await SqlObservationRepository(db).candidates(subject, as_of, user_id=user_id)
    try:
        observation = resolve(subject, as_of, policy, candidates)
    except NoObservationError:
        return _unproven(subject=subject, as_of=as_of, policy=policy, reason_code="no_eligible_observation")
    if observation.source not in {ObservationSource.MANUAL, ObservationSource.OVERRIDE}:
        return await _resolved_market_contribution(
            db, user_id=user_id, subject=observation.subject, requested_as_of=as_of, policy=policy, observation=observation
        )
    return await _manual_observation_contribution(
        db, user_id=user_id, observation=observation, as_of=as_of, policy=policy
    )


async def resolve_selected_market_valuation_contribution(
    db: AsyncSession, *, user_id: UUID, selection: MarketValuationSelection, policy: ResolutionPolicy
) -> ResolvedValuationContribution:
    contribution = await resolve_valuation_contribution(
        db, user_id=user_id, subject=selection.subject, as_of=selection.requested_as_of, policy=policy
    )
    if not contribution.is_authoritative or contribution.observation_id == selection.observation_id:
        return contribution
    return _unproven(
        subject=selection.subject,
        as_of=selection.requested_as_of,
        policy=policy,
        reason_code="selected_observation_mismatch",
    )


async def _manual_observation_contribution(
    db: AsyncSession,
    *,
    user_id: UUID,
    observation: PriceObservation,
    as_of: date,
    policy: ResolutionPolicy,
    component_type: str | None = None,
    valuation_basis: str | None = None,
    liquidity_class: str | None = None,
) -> ResolvedValuationContribution:
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
            component_type=component_type,
            valuation_basis=valuation_basis,
            liquidity_class=liquidity_class,
        )
    policy_record = ManualValuationAttestationPolicy()
    repository = SqlTraceRecordRepository(db, pricing_trace_policy_registry())
    decision = await repository.current_decision(
        TraceScope.tenant(user_id), TraceLineage.from_refs(target, policy_record.assertion)
    )
    if decision is None or decision.result is not TraceResult.AUTHORITATIVE or decision.target != target:
        return _unproven(
            subject=observation.subject,
            as_of=as_of,
            policy=policy,
            reason_code="missing_observation_decision",
            observation=observation,
            component_type=component_type,
            valuation_basis=valuation_basis,
            liquidity_class=liquidity_class,
        )
    return _build_contribution(
        subject=observation.subject,
        as_of=as_of,
        policy=policy,
        state="authoritative",
        observation=observation,
        observation_version=target.version,
        decision=decision,
        component_type=component_type,
        valuation_basis=valuation_basis,
        liquidity_class=liquidity_class,
    )


async def resolve_manual_valuation_contributions(
    db: AsyncSession, *, user_id: UUID, as_of: date, policy: ResolutionPolicy
) -> tuple[ResolvedValuationContribution, ...]:
    from src.pricing.orm.manual_valuation import ManualValuationSnapshot

    rows = (
        (
            await db.execute(
                select(ManualValuationSnapshot)
                .where(
                    ManualValuationSnapshot.user_id == user_id,
                    ManualValuationSnapshot.as_of_date <= as_of,
                    ManualValuationSnapshot.superseded_by_id.is_(None),
                )
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
            lineage_id=pricing_valuation_lineage_id(subject=subject, source=row.source, as_of=row.as_of_date),
        )
        contributions.append(
            await _manual_observation_contribution(
                db,
                user_id=user_id,
                observation=observation,
                as_of=as_of,
                policy=policy,
                component_type=row.component_type.value,
                valuation_basis=row.valuation_basis.value if row.valuation_basis else None,
                liquidity_class=row.liquidity_class.value,
            )
        )
    return tuple(contributions)
