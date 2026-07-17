"""Immutable TraceRecord assurance model."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid5

from src.audit.ratio import Ratio

TRACE_SCHEMA_VERSION = "1"
_TRACE_NAMESPACE = UUID("f40ff877-e949-4f4c-bffc-92b17ac89019")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Dependency-safe mirrors. Tooling parity-locks both to their owning vocabularies.
_VALID_PROOF_KINDS: dict[str, frozenset[str]] = {
    "CODE-ONLY": frozenset({"exact", "property"}),
    "CODE-LED": frozenset({"exact", "property"}),
    "LLM-LED": frozenset({"property", "invariant", "eval"}),
    "LLM-ONLY": frozenset({"eval", "smoke"}),
}
_VALID_STAGES = frozenset(
    {
        "local.advisory",
        "github_ci.merge_authority",
        "preview.runtime",
        "staging.release_validation",
        "staging.provider_regression",
        "prod.release_integrity",
        "ops.scheduled_cleanup",
        "manual.adjudication",
        "product.runtime",
    }
)


class TraceRecordValidationError(ValueError):
    """A TraceRecord is malformed or violates the assurance boundary."""


class TraceRecordType(StrEnum):
    OBSERVATION = "observation"
    DECISION = "decision"


class TraceResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    SKIPPED = "skipped"
    UNPROVEN = "unproven"
    AUTHORITATIVE = "authoritative"
    REVIEW = "review"
    REJECTED = "rejected"


class TraceScopeKind(StrEnum):
    TENANT = "tenant"
    REPOSITORY = "repository"
    ENVIRONMENT = "environment"


class TraceTargetClass(StrEnum):
    GENERAL = "general"
    FINANCIAL = "financial"


class TraceCausality(StrEnum):
    DIRECT = "direct"
    MANIFEST = "manifest"


@dataclass(frozen=True, slots=True)
class TraceScope:
    """Opaque isolation boundary shared by product, CI, and runtime records."""

    kind: TraceScopeKind
    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, TraceScopeKind):
            raise TraceRecordValidationError("scope kind must be a TraceScopeKind")
        _validate_text(self.id, name="scope id")

    @classmethod
    def tenant(cls, tenant_id: UUID) -> TraceScope:
        if not isinstance(tenant_id, UUID):
            raise TraceRecordValidationError("tenant scope id must be a UUID")
        return cls(kind=TraceScopeKind.TENANT, id=str(tenant_id))


@dataclass(frozen=True, slots=True)
class VersionedTraceRef:
    """Immutable identity of a target or assertion version."""

    kind: str
    id: str
    version: str

    def __post_init__(self) -> None:
        for name in ("kind", "id", "version"):
            _validate_text(getattr(self, name), name=name)


@dataclass(frozen=True, slots=True)
class TraceLineage:
    """Stable target/assertion identity; versions remain exact record pins."""

    target_kind: str
    target_id: str
    assertion_kind: str
    assertion_id: str

    def __post_init__(self) -> None:
        for name in (
            "target_kind",
            "target_id",
            "assertion_kind",
            "assertion_id",
        ):
            _validate_text(getattr(self, name), name=name)

    @classmethod
    def from_refs(
        cls,
        target: VersionedTraceRef,
        assertion: VersionedTraceRef,
    ) -> TraceLineage:
        return cls(
            target_kind=target.kind,
            target_id=target.id,
            assertion_kind=assertion.kind,
            assertion_id=assertion.id,
        )


@dataclass(frozen=True, slots=True)
class TraceAuthorityProfile:
    """Version-pinned snapshot of the existing authority vocabulary."""

    package: str
    tier: str
    proof_kind: str
    provenance: str
    execution_stage: str
    assertion_owner_digest: str
    producer_version: str

    def __post_init__(self) -> None:
        _validate_text(self.package, name="package", maximum=100)
        _validate_text(self.producer_version, name="producer_version")
        if not _SHA256_RE.fullmatch(self.assertion_owner_digest):
            raise TraceRecordValidationError("assertion_owner_digest must be a lowercase sha256")
        if self.execution_stage not in _VALID_STAGES:
            raise TraceRecordValidationError(f"execution_stage {self.execution_stage!r} is not registered")
        valid = _VALID_PROOF_KINDS.get(self.tier)
        if valid is None:
            raise TraceRecordValidationError(f"unknown authority tier {self.tier!r}")
        if self.proof_kind not in valid:
            raise TraceRecordValidationError(
                f"proof_kind {self.proof_kind!r} is invalid for {self.tier}; valid kinds: {sorted(valid)}"
            )
        if self.provenance not in {"deterministic", "live_llm", "manual"} and not (
            self.provenance.startswith("golden_fixture@") and len(self.provenance) > len("golden_fixture@")
        ):
            raise TraceRecordValidationError(
                "provenance must be deterministic, manual, live_llm, or golden_fixture@<ref>"
            )
        if self.provenance == "manual" and self.execution_stage != "manual.adjudication":
            raise TraceRecordValidationError("manual provenance requires manual.adjudication")
        if self.tier in {"LLM-LED", "LLM-ONLY"} and self.provenance == "deterministic":
            raise TraceRecordValidationError("LLM-led authority cannot claim deterministic provenance")
        if self.tier == "CODE-ONLY" and self.provenance == "live_llm":
            raise TraceRecordValidationError("CODE-ONLY authority cannot claim live_llm provenance")
        if self.provenance != "manual" and self.execution_stage == "manual.adjudication":
            raise TraceRecordValidationError("manual.adjudication is reserved for provenance='manual'")


@dataclass(frozen=True, slots=True)
class TraceDecisionOutcome:
    result: TraceResult
    reason_code: str
    score: Ratio | None = None


class TraceDecisionPolicy(Protocol):
    """Versioned capability that exclusively owns one DECISION fold."""

    @property
    def assertion(self) -> VersionedTraceRef: ...

    @property
    def authority(self) -> TraceAuthorityProfile: ...

    @property
    def causality(self) -> TraceCausality: ...

    @property
    def target_class(self) -> TraceTargetClass: ...

    def fold(self, parents: Sequence[TraceRecord]) -> TraceDecisionOutcome: ...


@dataclass(frozen=True, slots=True)
class TraceDecisionPolicyRegistry:
    policies: tuple[TraceDecisionPolicy, ...] = ()

    def __post_init__(self) -> None:
        assertions = [policy.assertion for policy in self.policies]
        if len(set(assertions)) != len(assertions):
            raise TraceRecordValidationError("decision policy assertions must be unique")

    def resolve(self, assertion: VersionedTraceRef) -> TraceDecisionPolicy:
        for policy in self.policies:
            if policy.assertion == assertion:
                return policy
        raise TraceRecordValidationError(f"no registered decision policy for {assertion}")


@dataclass(frozen=True, slots=True, init=False)
class TraceRecord:
    """One immutable observation or causal authority decision."""

    record_type: TraceRecordType
    scope: TraceScope
    target: VersionedTraceRef
    target_class: TraceTargetClass
    assertion: VersionedTraceRef
    authority: TraceAuthorityProfile
    result: TraceResult
    execution_id: str
    causality: TraceCausality | None
    evidence_manifest_digest: str
    occurred_at: datetime
    parent_ids: tuple[UUID, ...]
    supersedes_id: UUID | None
    score: Ratio | None
    reason_code: str
    schema_version: str
    content_digest: str
    record_id: UUID

    @property
    def lineage(self) -> TraceLineage:
        return TraceLineage.from_refs(self.target, self.assertion)

    @classmethod
    def observation(
        cls,
        *,
        scope: TraceScope,
        target: VersionedTraceRef,
        target_class: TraceTargetClass,
        assertion: VersionedTraceRef,
        authority: TraceAuthorityProfile,
        result: TraceResult,
        execution_id: str,
        evidence_manifest_digest: str,
        occurred_at: datetime,
        score: Ratio | None,
        reason_code: str,
        supersedes_id: UUID | None = None,
    ) -> TraceRecord:
        return cls._construct(
            record_type=TraceRecordType.OBSERVATION,
            scope=scope,
            target=target,
            target_class=target_class,
            assertion=assertion,
            authority=authority,
            result=result,
            execution_id=execution_id,
            causality=None,
            evidence_manifest_digest=evidence_manifest_digest,
            occurred_at=occurred_at,
            parent_ids=(),
            supersedes_id=supersedes_id,
            score=score,
            reason_code=reason_code,
        )

    @classmethod
    def decision(
        cls,
        *,
        scope: TraceScope,
        target: VersionedTraceRef,
        policy: TraceDecisionPolicy,
        execution_id: str,
        occurred_at: datetime,
        parents: Sequence[TraceRecord],
        supersedes_id: UUID | None = None,
    ) -> TraceRecord:
        outcome = policy.fold(parents)
        cls._validate_causality(
            scope=scope,
            target=target,
            target_class=policy.target_class,
            causality=policy.causality,
            execution_id=execution_id,
            authority=policy.authority,
            result=outcome.result,
            parents=parents,
        )
        return cls._construct(
            record_type=TraceRecordType.DECISION,
            scope=scope,
            target=target,
            target_class=policy.target_class,
            assertion=policy.assertion,
            authority=policy.authority,
            result=outcome.result,
            execution_id=execution_id,
            causality=policy.causality,
            evidence_manifest_digest=_parent_manifest_digest(parents),
            occurred_at=occurred_at,
            parent_ids=tuple(sorted((parent.record_id for parent in parents), key=str)),
            supersedes_id=supersedes_id,
            score=outcome.score,
            reason_code=outcome.reason_code,
        )

    @classmethod
    def _construct(
        cls,
        *,
        record_type: TraceRecordType,
        scope: TraceScope,
        target: VersionedTraceRef,
        target_class: TraceTargetClass,
        assertion: VersionedTraceRef,
        authority: TraceAuthorityProfile,
        result: TraceResult,
        execution_id: str,
        causality: TraceCausality | None,
        evidence_manifest_digest: str,
        occurred_at: datetime,
        parent_ids: tuple[UUID, ...],
        supersedes_id: UUID | None,
        score: Ratio | None,
        reason_code: str,
    ) -> TraceRecord:
        observation_results = {
            TraceResult.PASS,
            TraceResult.FAIL,
            TraceResult.ERROR,
            TraceResult.SKIPPED,
            TraceResult.UNPROVEN,
        }
        decision_results = {
            TraceResult.AUTHORITATIVE,
            TraceResult.REVIEW,
            TraceResult.REJECTED,
        }
        if not isinstance(scope, TraceScope):
            raise TraceRecordValidationError("scope must be a TraceScope")
        if not isinstance(target_class, TraceTargetClass):
            raise TraceRecordValidationError("target_class must be a TraceTargetClass")
        if record_type is TraceRecordType.OBSERVATION:
            if result not in observation_results or parent_ids or causality is not None:
                raise TraceRecordValidationError(
                    "OBSERVATION requires an observation result, no parents, and no causality"
                )
        elif record_type is TraceRecordType.DECISION:
            if result not in decision_results:
                raise TraceRecordValidationError("DECISION requires a decision result")
            if not parent_ids or len(set(parent_ids)) != len(parent_ids):
                raise TraceRecordValidationError("DECISION requires non-empty, unique parents")
            if not isinstance(causality, TraceCausality):
                raise TraceRecordValidationError("DECISION requires a registered causality mode")
        else:
            raise TraceRecordValidationError(f"unknown TraceRecord type {record_type!r}")
        _validate_text(execution_id, name="execution_id")
        if not _SHA256_RE.fullmatch(evidence_manifest_digest):
            raise TraceRecordValidationError("evidence_manifest_digest must be a lowercase sha256")
        if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
            raise TraceRecordValidationError("occurred_at must be timezone-aware")
        _validate_text(reason_code, name="reason_code")
        if score is not None:
            if not isinstance(score, Ratio):
                raise TraceRecordValidationError("score must use the audit Ratio type")
            if score.value < Decimal("0") or score.value > Decimal("1"):
                raise TraceRecordValidationError("score must be within [0, 1]")

        record = object.__new__(cls)
        values = {
            "record_type": record_type,
            "scope": scope,
            "target": target,
            "target_class": target_class,
            "assertion": assertion,
            "authority": authority,
            "result": result,
            "execution_id": execution_id,
            "causality": causality,
            "evidence_manifest_digest": evidence_manifest_digest,
            "occurred_at": occurred_at,
            "parent_ids": parent_ids,
            "supersedes_id": supersedes_id,
            "score": score,
            "reason_code": reason_code,
            "schema_version": TRACE_SCHEMA_VERSION,
        }
        for name, value in values.items():
            object.__setattr__(record, name, value)
        digest = hashlib.sha256(
            json.dumps(
                record.semantic_payload(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        object.__setattr__(record, "content_digest", digest)
        object.__setattr__(record, "record_id", uuid5(_TRACE_NAMESPACE, digest))
        return record

    @staticmethod
    def _validate_causality(
        *,
        scope: TraceScope,
        target: VersionedTraceRef,
        target_class: TraceTargetClass,
        causality: TraceCausality,
        execution_id: str,
        authority: TraceAuthorityProfile,
        result: TraceResult,
        parents: Sequence[TraceRecord],
    ) -> None:
        if not parents:
            raise TraceRecordValidationError("DECISION requires at least one parent")
        parent_ids = {parent.record_id for parent in parents}
        if len(parent_ids) != len(parents):
            raise TraceRecordValidationError("DECISION parents must be unique")
        allowed_parent_results = (
            {TraceResult.PASS, TraceResult.AUTHORITATIVE, TraceResult.FAIL}
            if result is TraceResult.REJECTED
            else {TraceResult.PASS, TraceResult.AUTHORITATIVE}
        )
        for parent in parents:
            if parent.scope != scope:
                raise TraceRecordValidationError("cross-scope decision parent")
            if parent.result not in allowed_parent_results:
                raise TraceRecordValidationError(f"unsatisfied decision parent result {parent.result.value!r}")
            if causality is TraceCausality.DIRECT:
                if parent.target != target:
                    raise TraceRecordValidationError("DIRECT decision parent must pin the same target version")
                if parent.execution_id != execution_id:
                    raise TraceRecordValidationError("DIRECT decision parent must share the execution")

        has_llm_financial_parent = (
            target_class is TraceTargetClass.FINANCIAL
            and result is TraceResult.AUTHORITATIVE
            and any(parent.authority.tier in {"LLM-LED", "LLM-ONLY"} for parent in parents)
        )
        if not has_llm_financial_parent:
            return
        has_code_guard = any(
            parent.record_type is TraceRecordType.DECISION
            and parent.target == target
            and parent.target_class is TraceTargetClass.FINANCIAL
            and parent.authority.tier == "CODE-ONLY"
            and parent.assertion.kind in {"invariant", "promotion"}
            and parent.result is TraceResult.AUTHORITATIVE
            for parent in parents
        )
        if authority.tier != "CODE-ONLY" or not has_code_guard:
            raise TraceRecordValidationError(
                "LLM-produced financial authority requires a same-target CODE-ONLY "
                "invariant or promotion DECISION parent"
            )

    def semantic_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_type": self.record_type.value,
            "scope": {"kind": self.scope.kind.value, "id": self.scope.id},
            "target": _ref_payload(self.target),
            "target_class": self.target_class.value,
            "assertion": _ref_payload(self.assertion),
            "authority": {
                "package": self.authority.package,
                "tier": self.authority.tier,
                "proof_kind": self.authority.proof_kind,
                "provenance": self.authority.provenance,
                "execution_stage": self.authority.execution_stage,
                "assertion_owner_digest": self.authority.assertion_owner_digest,
                "producer_version": self.authority.producer_version,
            },
            "result": self.result.value,
            "execution_id": self.execution_id,
            "causality": self.causality.value if self.causality is not None else None,
            "evidence_manifest_digest": self.evidence_manifest_digest,
            "occurred_at": self.occurred_at.astimezone(UTC).isoformat(),
            "parent_ids": [str(value) for value in self.parent_ids],
            "supersedes_id": (str(self.supersedes_id) if self.supersedes_id is not None else None),
            "score": (_decimal_wire(self.score.value) if self.score is not None else None),
            "reason_code": self.reason_code,
        }

    def wire_payload(self) -> dict[str, Any]:
        return {
            **self.semantic_payload(),
            "content_digest": self.content_digest,
            "record_id": str(self.record_id),
        }

    @classmethod
    def restore(cls, payload: dict[str, Any]) -> TraceRecord:
        _validate_wire_scalars(payload)
        record_type = TraceRecordType(payload["record_type"])
        if record_type is TraceRecordType.DECISION:
            raise TraceRecordValidationError("DECISION restore requires repository policy replay")
        scope_payload = payload["scope"]
        record = cls._construct(
            record_type=record_type,
            scope=TraceScope(
                kind=TraceScopeKind(scope_payload["kind"]),
                id=scope_payload["id"],
            ),
            target=VersionedTraceRef(**payload["target"]),
            target_class=TraceTargetClass(payload["target_class"]),
            assertion=VersionedTraceRef(**payload["assertion"]),
            authority=TraceAuthorityProfile(**payload["authority"]),
            result=TraceResult(payload["result"]),
            execution_id=payload["execution_id"],
            causality=(TraceCausality(payload["causality"]) if payload["causality"] is not None else None),
            evidence_manifest_digest=payload["evidence_manifest_digest"],
            occurred_at=datetime.fromisoformat(payload["occurred_at"]),
            parent_ids=tuple(UUID(value) for value in payload["parent_ids"]),
            supersedes_id=(UUID(payload["supersedes_id"]) if payload["supersedes_id"] is not None else None),
            score=(Ratio(Decimal(payload["score"])) if payload["score"] is not None else None),
            reason_code=payload["reason_code"],
        )
        if payload["schema_version"] != TRACE_SCHEMA_VERSION:
            raise TraceRecordValidationError(f"unsupported TraceRecord schema_version {payload['schema_version']!r}")
        if payload["content_digest"] != record.content_digest:
            raise TraceRecordValidationError("TraceRecord content_digest mismatch")
        if UUID(payload["record_id"]) != record.record_id:
            raise TraceRecordValidationError("TraceRecord record_id mismatch")
        return record


def current_heads(records: Iterable[TraceRecord]) -> list[TraceRecord]:
    """Return supersession heads whose complete causal ancestry is also current."""

    values = list(records)
    superseded = {record.supersedes_id for record in values if record.supersedes_id is not None}
    candidates = [record for record in values if record.record_id not in superseded]
    valid_ids = {record.record_id for record in candidates if record.record_type is TraceRecordType.OBSERVATION}
    pending = [record for record in candidates if record.record_type is TraceRecordType.DECISION]
    while pending:
        admitted = [record for record in pending if set(record.parent_ids).issubset(valid_ids)]
        if not admitted:
            break
        valid_ids.update(record.record_id for record in admitted)
        pending = [record for record in pending if record not in admitted]
    return [record for record in candidates if record.record_id in valid_ids]


def parent_manifest_digest(parents: Sequence[TraceRecord]) -> str:
    """Digest the exact unordered parent set for policy-reproducible folds."""

    return _parent_manifest_digest(parents)


def _parent_manifest_digest(parents: Sequence[TraceRecord]) -> str:
    return hashlib.sha256(
        json.dumps(
            sorted(parent.content_digest for parent in parents),
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _ref_payload(value: VersionedTraceRef) -> dict[str, str]:
    return {"kind": value.kind, "id": value.id, "version": value.version}


def _validate_wire_scalars(payload: dict[str, Any]) -> None:
    string_fields = {
        "schema_version",
        "record_type",
        "target_class",
        "result",
        "execution_id",
        "evidence_manifest_digest",
        "occurred_at",
        "reason_code",
        "content_digest",
        "record_id",
    }
    if any(not isinstance(payload.get(name), str) for name in string_fields):
        raise TraceRecordValidationError("TraceRecord wire scalar types are invalid")
    if payload.get("causality") is not None and not isinstance(payload["causality"], str):
        raise TraceRecordValidationError("TraceRecord causality must be a string or null")
    if payload.get("score") is not None and not isinstance(payload["score"], str):
        raise TraceRecordValidationError("TraceRecord score must be a string or null")
    if payload.get("supersedes_id") is not None and not isinstance(payload["supersedes_id"], str):
        raise TraceRecordValidationError("TraceRecord supersedes_id must be a string or null")
    if not isinstance(payload.get("parent_ids"), list) or any(
        not isinstance(value, str) for value in payload["parent_ids"]
    ):
        raise TraceRecordValidationError("TraceRecord parent_ids must be a string list")
    for name in ("scope", "target", "assertion", "authority"):
        if not isinstance(payload.get(name), dict):
            raise TraceRecordValidationError(f"TraceRecord {name} must be an object")


def _validate_text(value: str, *, name: str, maximum: int = 200) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TraceRecordValidationError(f"{name} must be a non-empty string")
    if len(value) > maximum:
        raise TraceRecordValidationError(f"{name} exceeds {maximum} characters")


def _decimal_wire(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    return format(value.normalize(), "f")
