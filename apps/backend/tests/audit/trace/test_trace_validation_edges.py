"""AC-audit.trace-record.1-.5: fail-closed boundary and adapter edges."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.audit import (
    JsonlTraceRecordStore,
    Ratio,
    TraceAuthorityProfile,
    TraceCausality,
    TraceConfidenceProjection,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceEmitter,
    TraceRecord,
    TraceRecordCodec,
    TraceRecordValidationError,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.audit.base.trace import parent_manifest_digest

from .conftest import authority, decision_policy, observation


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"assertion_owner_digest": "not-a-digest"}, "lowercase sha256"),
        ({"execution_stage": "unknown.stage"}, "not registered"),
        ({"provenance": "unregistered"}, "provenance must"),
        (
            {"tier": "LLM-LED", "proof_kind": "eval", "provenance": "deterministic"},
            "cannot claim deterministic",
        ),
        ({"tier": "CODE-ONLY", "provenance": "live_llm"}, "cannot claim live_llm"),
        ({"execution_stage": "manual.adjudication"}, "reserved"),
    ],
)
def test_authority_profile_rejects_unregistered_combinations(kwargs, message):
    values = {
        "package": "audit",
        "tier": "CODE-ONLY",
        "proof_kind": "exact",
        "provenance": "deterministic",
        "execution_stage": "github_ci.merge_authority",
        "assertion_owner_digest": "a" * 64,
        "producer_version": "test@1",
    }
    values.update(kwargs)

    with pytest.raises(TraceRecordValidationError, match=message):
        TraceAuthorityProfile(**values)


def test_scope_refs_registry_and_text_fields_fail_closed():
    with pytest.raises(TraceRecordValidationError, match="scope kind"):
        TraceScope(kind="tenant", id="opaque")  # type: ignore[arg-type]
    with pytest.raises(TraceRecordValidationError, match="must be a UUID"):
        TraceScope.tenant("not-a-uuid")  # type: ignore[arg-type]
    with pytest.raises(TraceRecordValidationError, match="non-empty"):
        VersionedTraceRef(kind="", id="id", version="v1")
    with pytest.raises(TraceRecordValidationError, match="exceeds 200"):
        VersionedTraceRef(kind="kind", id="x" * 201, version="v1")

    policy = decision_policy()
    with pytest.raises(TraceRecordValidationError, match="unique"):
        TraceDecisionPolicyRegistry((policy, policy))
    with pytest.raises(TraceRecordValidationError, match="no registered"):
        TraceDecisionPolicyRegistry().resolve(policy.assertion)


def _construct_from(record: TraceRecord, **overrides) -> TraceRecord:
    values = {
        "record_type": record.record_type,
        "scope": record.scope,
        "target": record.target,
        "target_class": record.target_class,
        "assertion": record.assertion,
        "authority": record.authority,
        "result": record.result,
        "execution_id": record.execution_id,
        "causality": record.causality,
        "evidence_manifest_digest": record.evidence_manifest_digest,
        "occurred_at": record.occurred_at,
        "parent_ids": record.parent_ids,
        "supersedes_id": record.supersedes_id,
        "score": record.score,
        "reason_code": record.reason_code,
    }
    values.update(overrides)
    return TraceRecord._construct(**values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"scope": "tenant"}, "scope must"),
        ({"target_class": "financial"}, "target_class must"),
        ({"result": TraceResult.AUTHORITATIVE}, "OBSERVATION requires"),
        ({"causality": TraceCausality.DIRECT}, "OBSERVATION requires"),
        ({"record_type": "unknown"}, "unknown TraceRecord type"),
        ({"evidence_manifest_digest": "bad"}, "lowercase sha256"),
        ({"occurred_at": datetime(2026, 7, 17)}, "timezone-aware"),
        ({"score": Decimal("1")}, "audit Ratio"),
        ({"score": Ratio(Decimal("2"))}, "within"),
    ],
)
def test_record_constructor_rejects_invalid_structural_values(overrides, message):
    with pytest.raises(TraceRecordValidationError, match=message):
        _construct_from(observation(), **overrides)


@dataclass(frozen=True, slots=True)
class PermissivePolicy:
    result: TraceResult = TraceResult.AUTHORITATIVE
    causality: object = TraceCausality.DIRECT
    target_class: TraceTargetClass = TraceTargetClass.FINANCIAL
    assertion: VersionedTraceRef = VersionedTraceRef("promotion", "edge-policy", "v1")
    authority: TraceAuthorityProfile = authority()

    def fold(self, _parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        return TraceDecisionOutcome(result=self.result, reason_code="edge")


def test_decision_constructor_rejects_empty_duplicate_and_invalid_policy_outputs():
    parent = observation()
    kwargs = {
        "scope": parent.scope,
        "target": parent.target,
        "execution_id": parent.execution_id,
        "occurred_at": parent.occurred_at,
    }
    with pytest.raises(TraceRecordValidationError, match="at least one parent"):
        TraceRecord.decision(policy=PermissivePolicy(), parents=[], **kwargs)
    with pytest.raises(TraceRecordValidationError, match="unique"):
        TraceRecord.decision(policy=PermissivePolicy(), parents=[parent, parent], **kwargs)
    with pytest.raises(TraceRecordValidationError, match="decision result"):
        TraceRecord.decision(
            policy=PermissivePolicy(result=TraceResult.PASS),
            parents=[parent],
            **kwargs,
        )
    with pytest.raises(TraceRecordValidationError, match="registered causality"):
        TraceRecord.decision(
            policy=PermissivePolicy(causality="direct"),
            parents=[parent],
            **kwargs,
        )


def test_current_heads_and_manifest_drop_stale_or_causally_orphaned_decisions():
    parent = observation()
    decision = TraceRecord.decision(
        scope=parent.scope,
        target=parent.target,
        policy=decision_policy(),
        execution_id=parent.execution_id,
        occurred_at=parent.occurred_at,
        parents=[parent],
    )
    correction = observation(
        scope=parent.scope,
        target_version="v2",
        assertion_version="v2",
        supersedes_id=parent.record_id,
    )

    assert parent_manifest_digest([parent]) == decision.evidence_manifest_digest
    from src.audit.base.trace import current_heads

    assert current_heads([parent, decision, correction]) == [correction]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 1, "scalar types"),
        ("causality", 1, "causality"),
        ("supersedes_id", 1, "supersedes_id"),
        ("parent_ids", [1], "parent_ids"),
        ("scope", [], "scope must be an object"),
    ],
)
def test_wire_payload_rejects_noncanonical_scalar_shapes(field, value, message):
    payload = observation().wire_payload()
    payload[field] = value
    with pytest.raises(TraceRecordValidationError, match=message):
        TraceRecord.restore(payload)


def test_codec_and_restore_reject_every_integrity_envelope_failure():
    record = observation()
    payload = record.wire_payload()

    with pytest.raises(TypeError, match="expects TraceRecord"):
        TraceRecordCodec.encode({})  # type: ignore[arg-type]
    for raw, message in (("{", "valid JSON"), ("[]", "must be an object")):
        with pytest.raises(TraceRecordValidationError, match=message):
            TraceRecordCodec.decode(raw)

    missing = dict(payload)
    missing.pop("reason_code")
    with pytest.raises(TraceRecordValidationError, match="missing fields"):
        TraceRecordCodec.decode(json.dumps(missing))

    for field, value, message in (
        ("schema_version", "2", "unsupported"),
        ("content_digest", "0" * 64, "content_digest mismatch"),
        ("record_id", str(uuid4()), "record_id mismatch"),
        ("record_type", "invalid", "invalid TraceRecord payload"),
    ):
        changed = dict(payload)
        changed[field] = value
        with pytest.raises(TraceRecordValidationError, match=message):
            TraceRecordCodec.decode(json.dumps(changed))


def test_jsonl_adapter_handles_empty_invalid_and_collision_paths(tmp_path: Path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    store = JsonlTraceRecordStore(path)
    assert store.read_all() == []

    path.write_text("\n  \n{\n", encoding="utf-8")
    with pytest.raises(TraceRecordValidationError, match="line 3"):
        store.read_all()

    record = observation()
    monkeypatch.setattr(
        "src.audit.extension.trace_adapters._decode_jsonl",
        lambda _content: [SimpleNamespace(record_id=record.record_id, content_digest="0" * 64)],
    )
    with pytest.raises(TraceRecordValidationError, match="collision"):
        store.append(record)


async def test_emitter_returns_the_complete_ordered_graph():
    records = (observation(), observation())
    repository = AsyncMock()
    repository.append.side_effect = lambda record: record

    assert await TraceEmitter(repository).emit_many(records) == records


def test_confidence_projection_rejects_invalid_or_ambiguous_fixed_cohorts():
    member = observation()
    with pytest.raises(TraceRecordValidationError, match="required"):
        TraceConfidenceProjection("", "v1", (member.lineage,))
    for members in ((), (member.lineage, member.lineage)):
        with pytest.raises(TraceRecordValidationError, match="non-empty and unique"):
            TraceConfidenceProjection("cohort", "v1", members)

    duplicate_head = observation(
        scope=member.scope,
        target_id=member.target.id,
        execution_id="second-measurement",
    )
    projection = TraceConfidenceProjection("cohort", "v1", (member.lineage,))
    with pytest.raises(TraceRecordValidationError, match="ambiguous"):
        projection.evaluate([member, duplicate_head])
