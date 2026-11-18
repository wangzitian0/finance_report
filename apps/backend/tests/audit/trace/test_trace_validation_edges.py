from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.audit import (
    Ratio,
    TraceAuthorityProfile,
    TraceCausality,
    TraceConfidenceProjection,
    TraceDecisionOutcome,
    TraceDecisionPolicyRegistry,
    TraceEmitter,
    TraceLineage,
    TraceRecord,
    TraceRecordCodec,
    TraceRecordValidationError,
    TraceResult,
    TraceScope,
    TraceTargetClass,
    VersionedTraceRef,
)
from src.audit.base.trace import current_heads
from tests.audit.trace.conftest import authority, decision_policy, observation


@dataclass(frozen=True, slots=True)
class PermissivePolicy:
    result: TraceResult = TraceResult.AUTHORITATIVE
    causality: object = TraceCausality.DIRECT
    target_class: TraceTargetClass = TraceTargetClass.FINANCIAL
    assertion: VersionedTraceRef = VersionedTraceRef("promotion", "edge-policy", "v1")
    authority: TraceAuthorityProfile = authority()

    def fold(self, _parents: Sequence[TraceRecord]) -> TraceDecisionOutcome:
        return TraceDecisionOutcome(result=self.result, reason_code="edge")


def _construct_from(record: TraceRecord, **overrides) -> TraceRecord:
    values = {f: getattr(record, f) for f in ("record_type", "scope", "target", "target_class", "assertion", "authority", "result", "execution_id", "causality", "evidence_manifest_digest", "occurred_at", "parent_ids", "supersedes_id", "score", "reason_code")}
    values.update(overrides)
    return TraceRecord._construct(**values)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"assertion_owner_digest": "not-a-digest"}, "lowercase sha256"),
        ({"execution_stage": "unknown.stage"}, "not registered"),
        ({"provenance": "unregistered"}, "provenance must"),
        ({"tier": "LLM-LED", "proof_kind": "eval", "provenance": "deterministic"}, "cannot claim deterministic"),
        ({"tier": "CODE-ONLY", "provenance": "live_llm"}, "cannot claim live_llm"),
        ({"execution_stage": "manual.adjudication"}, "reserved"),
    ],
)
def test_authority_profile_rejects_unregistered_combinations(kwargs: dict, message: str) -> None:
    values = {"package": "audit", "tier": "CODE-ONLY", "proof_kind": "exact", "provenance": "deterministic", "execution_stage": "github_ci.merge_authority", "assertion_owner_digest": "a" * 64, "producer_version": "test@1"}
    values.update(kwargs)
    with pytest.raises(TraceRecordValidationError, match=message):
        TraceAuthorityProfile(**values)


def test_scope_refs_registry_codec_and_projection_fail_closed() -> None:
    policy, parent = decision_policy(), observation()
    kw = {"scope": parent.scope, "target": parent.target, "execution_id": parent.execution_id, "occurred_at": parent.occurred_at}
    decision = TraceRecord.decision(policy=policy, parents=[parent], **kw)
    correction = observation(scope=parent.scope, target_version="v2", assertion_version="v2", supersedes_id=parent.record_id)
    assert decision.evidence_manifest_digest == hashlib.sha256(json.dumps([parent.content_digest], separators=(",", ":")).encode("utf-8")).hexdigest() and current_heads([parent, decision, correction]) == [correction]

    payload = parent.wire_payload()
    missing = {k: v for k, v in payload.items() if k != "reason_code"}
    dup = observation(scope=parent.scope, target_id=parent.target.id, execution_id="second-measurement")
    with pytest.raises(TypeError, match="expects TraceRecord"):
        TraceRecordCodec.encode({})
    for fn, match in (
        (lambda: TraceScope(kind="tenant", id="opaque"), "scope kind"),
        (lambda: TraceScope.tenant("not-a-uuid"), "must be a UUID"),
        (lambda: VersionedTraceRef(kind="", id="id", version="v1"), "non-empty"),
        (lambda: VersionedTraceRef(kind="kind", id="x" * 201, version="v1"), "exceeds 200"),
        (lambda: TraceDecisionPolicyRegistry((policy, policy)), "unique"),
        (lambda: TraceDecisionPolicyRegistry().resolve(policy.assertion), "no registered"),
        (lambda: TraceRecord.decision(policy=PermissivePolicy(), parents=[], **kw), "at least one parent"),
        (lambda: TraceRecord.decision(policy=PermissivePolicy(), parents=[parent, parent], **kw), "unique"),
        (lambda: TraceRecord.decision(policy=PermissivePolicy(result=TraceResult.PASS), parents=[parent], **kw), "decision result"),
        (lambda: TraceRecord.decision(policy=PermissivePolicy(causality="direct"), parents=[parent], **kw), "registered causality"),
        (lambda: TraceRecordCodec.decode("{"), "valid JSON"),
        (lambda: TraceRecordCodec.decode("[]"), "must be an object"),
        (lambda: TraceRecordCodec.decode(json.dumps(missing)), "missing fields"),
        (lambda: TraceRecordCodec.decode(json.dumps({**payload, "schema_version": "2"})), "unsupported"),
        (lambda: TraceRecordCodec.decode(json.dumps({**payload, "content_digest": "0" * 64})), "content_digest mismatch"),
        (lambda: TraceRecordCodec.decode(json.dumps({**payload, "record_id": str(uuid4())})), "record_id mismatch"),
        (lambda: TraceRecordCodec.decode(json.dumps({**payload, "record_type": "invalid"})), "invalid TraceRecord payload"),
        (lambda: TraceConfidenceProjection("", "v1", (parent.lineage,)), "required"),
        (lambda: TraceConfidenceProjection("cohort", "v1", ()), "non-empty and unique"),
        (lambda: TraceConfidenceProjection("cohort", "v1", (parent.lineage, parent.lineage)), "non-empty and unique"),
        (lambda: TraceConfidenceProjection("cohort", "v1", (parent.lineage,)).evaluate([parent, dup]), "ambiguous"),
    ):
        with pytest.raises(TraceRecordValidationError, match=match):
            fn()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"scope": "tenant"}, "scope must"), ({"target_class": "financial"}, "target_class must"),
        ({"result": TraceResult.AUTHORITATIVE}, "OBSERVATION requires"), ({"causality": TraceCausality.DIRECT}, "OBSERVATION requires"),
        ({"record_type": "unknown"}, "unknown TraceRecord type"), ({"evidence_manifest_digest": "bad"}, "lowercase sha256"),
        ({"occurred_at": datetime(2026, 7, 17)}, "timezone-aware"), ({"score": Decimal("1")}, "audit Ratio"),
        ({"score": Ratio(Decimal("2"))}, "within"),
    ],
)
def test_record_constructor_rejects_invalid_structural_values(overrides: dict, message: str) -> None:
    with pytest.raises(TraceRecordValidationError, match=message):
        _construct_from(observation(), **overrides)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [("schema_version", 1, "scalar types"), ("causality", 1, "causality"), ("supersedes_id", 1, "supersedes_id"), ("parent_ids", [1], "parent_ids"), ("scope", [], "scope must be an object")],
)
def test_wire_payload_rejects_noncanonical_scalar_shapes(field: str, value, message: str) -> None:
    with pytest.raises(TraceRecordValidationError, match=message):
        TraceRecord.restore({**observation().wire_payload(), field: value})


async def test_emitter_and_confidence_cohort_projection() -> None:
    records = (observation(), observation())
    repository = AsyncMock()
    repository.append.side_effect = lambda record: record
    assert await TraceEmitter(repository).emit_many(records) == records

    passed = observation(target_id="machine-a")
    failed = observation(scope=passed.scope, target_id="machine-b", result=TraceResult.FAIL, score="0")
    manual = observation(scope=passed.scope, target_id="manual-extra", profile=authority(tier="CODE-ONLY", proof_kind="exact", provenance="deterministic"))
    correction = observation(scope=passed.scope, target_id="machine-b", target_version="v2", assertion_version="v2", supersedes_id=failed.record_id)
    assert TraceConfidenceProjection(cohort_id="machine-extraction", cohort_version="v1", members=(passed.lineage, failed.lineage)).evaluate([passed, failed, manual, correction]).value == Decimal("1")

    f1 = observation(target_id="shared-target", assertion_id="parser-shape")
    f2 = observation(scope=f1.scope, target_id="shared-target", assertion_id="balance-invariant", result=TraceResult.FAIL, score="0")
    assert TraceConfidenceProjection(cohort_id="two-independent-assertions", cohort_version="v1", members=(TraceLineage.from_refs(f1.target, f1.assertion), TraceLineage.from_refs(f2.target, f2.assertion))).evaluate([f1, f2]).value == Decimal("0.5")

    parent = observation()
    decision = TraceRecord.decision(scope=parent.scope, target=parent.target, policy=decision_policy(assertion_id="terminal-confidence"), execution_id=parent.execution_id, occurred_at=parent.occurred_at, parents=[parent])
    term_proj = TraceConfidenceProjection(cohort_id="terminal-decisions", cohort_version="v1", members=(decision.lineage,))
    assert term_proj.evaluate([parent, decision]).value == Decimal("1")
    with pytest.raises(TraceRecordValidationError, match="missing"):
        term_proj.evaluate([parent, decision, observation(scope=parent.scope, target_version="v2", assertion_version="v2", supersedes_id=parent.record_id)])
