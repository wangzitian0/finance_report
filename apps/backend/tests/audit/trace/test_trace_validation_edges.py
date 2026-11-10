'AC-audit.trace-record.1'; from __future__ import annotations; import hashlib; import json; from collections.abc import Sequence; from dataclasses import dataclass; from datetime import datetime; from decimal import Decimal; from unittest.mock import AsyncMock; from uuid import uuid4; import pytest; from src.audit import Ratio, TraceAuthorityProfile, TraceCausality, TraceConfidenceProjection, TraceDecisionOutcome, TraceDecisionPolicyRegistry, TraceEmitter, TraceRecord, TraceRecordCodec, TraceRecordValidationError, TraceResult, TraceScope, TraceTargetClass, VersionedTraceRef; from .conftest import authority, decision_policy, observation
@pytest.mark.parametrize(('kwargs', 'message'), [({'assertion_owner_digest': 'not-a-digest'}, 'lowercase sha256'), ({'execution_stage': 'unknown.stage'}, 'not registered'), ({'provenance': 'unregistered'}, 'provenance must'), ({'tier': 'LLM-LED', 'proof_kind': 'eval', 'provenance': 'deterministic'}, 'cannot claim deterministic'), ({'tier': 'CODE-ONLY', 'provenance': 'live_llm'}, 'cannot claim live_llm'), ({'execution_stage': 'manual.adjudication'}, 'reserved')])
def test_authority_profile_rejects_unregistered_combinations(kwargs, message):
    values = {'package': 'audit', 'tier': 'CODE-ONLY', 'proof_kind': 'exact', 'provenance': 'deterministic', 'execution_stage': 'github_ci.merge_authority', 'assertion_owner_digest': 'a' * 64, 'producer_version': 'test@1'}; values.update(kwargs)
    with pytest.raises(TraceRecordValidationError, match=message): TraceAuthorityProfile(**values)
def test_scope_refs_registry_and_text_fields_fail_closed():
    with pytest.raises(TraceRecordValidationError, match='scope kind'): TraceScope(kind='tenant', id='opaque')
    with pytest.raises(TraceRecordValidationError, match='must be a UUID'): TraceScope.tenant('not-a-uuid')
    with pytest.raises(TraceRecordValidationError, match='non-empty'): VersionedTraceRef(kind='', id='id', version='v1')
    with pytest.raises(TraceRecordValidationError, match='exceeds 200'): VersionedTraceRef(kind='kind', id='x' * 201, version='v1')
    policy = decision_policy()
    with pytest.raises(TraceRecordValidationError, match='unique'): TraceDecisionPolicyRegistry((policy, policy))
    with pytest.raises(TraceRecordValidationError, match='no registered'): TraceDecisionPolicyRegistry().resolve(policy.assertion)
    _m1_parent = observation(); _m1_kwargs = {'scope': _m1_parent.scope, 'target': _m1_parent.target, 'execution_id': _m1_parent.execution_id, 'occurred_at': _m1_parent.occurred_at}
    with pytest.raises(TraceRecordValidationError, match='at least one parent'): TraceRecord.decision(policy=PermissivePolicy(), parents=[], **_m1_kwargs)
    with pytest.raises(TraceRecordValidationError, match='unique'): TraceRecord.decision(policy=PermissivePolicy(), parents=[_m1_parent, _m1_parent], **_m1_kwargs)
    with pytest.raises(TraceRecordValidationError, match='decision result'): TraceRecord.decision(policy=PermissivePolicy(result=TraceResult.PASS), parents=[_m1_parent], **_m1_kwargs)
    with pytest.raises(TraceRecordValidationError, match='registered causality'): TraceRecord.decision(policy=PermissivePolicy(causality='direct'), parents=[_m1_parent], **_m1_kwargs)
    _m2_parent = observation(); _m2_decision = TraceRecord.decision(scope=_m2_parent.scope, target=_m2_parent.target, policy=decision_policy(), execution_id=_m2_parent.execution_id, occurred_at=_m2_parent.occurred_at, parents=[_m2_parent]); _m2_correction = observation(scope=_m2_parent.scope, target_version='v2', assertion_version='v2', supersedes_id=_m2_parent.record_id); _m2_expected_manifest_digest = hashlib.sha256(json.dumps([_m2_parent.content_digest], separators=(',', ':')).encode('utf-8')).hexdigest(); assert _m2_decision.evidence_manifest_digest == _m2_expected_manifest_digest; from src.audit.base.trace import current_heads; assert current_heads([_m2_parent, _m2_decision, _m2_correction]) == [_m2_correction]; _m3_record = observation(); _m3_payload = _m3_record.wire_payload()
    with pytest.raises(TypeError, match='expects TraceRecord'): TraceRecordCodec.encode({})
    for (_m3_raw, _m3_message) in (('{', 'valid JSON'), ('[]', 'must be an object')):
        with pytest.raises(TraceRecordValidationError, match=_m3_message): TraceRecordCodec.decode(_m3_raw)
    _m3_missing = dict(_m3_payload); _m3_missing.pop('reason_code')
    with pytest.raises(TraceRecordValidationError, match='missing fields'): TraceRecordCodec.decode(json.dumps(_m3_missing))
    for (_m3_field, _m3_value, _m3_message) in (('schema_version', '2', 'unsupported'), ('content_digest', '0' * 64, 'content_digest mismatch'), ('record_id', str(uuid4()), 'record_id mismatch'), ('record_type', 'invalid', 'invalid TraceRecord payload')):
        _m3_changed = dict(_m3_payload); _m3_changed[_m3_field] = _m3_value
        with pytest.raises(TraceRecordValidationError, match=_m3_message): TraceRecordCodec.decode(json.dumps(_m3_changed))
    _m4_member = observation()
    with pytest.raises(TraceRecordValidationError, match='required'): TraceConfidenceProjection('', 'v1', (_m4_member.lineage,))
    for _m4_members in ((), (_m4_member.lineage, _m4_member.lineage)):
        with pytest.raises(TraceRecordValidationError, match='non-empty and unique'): TraceConfidenceProjection('cohort', 'v1', _m4_members)
    _m4_duplicate_head = observation(scope=_m4_member.scope, target_id=_m4_member.target.id, execution_id='second-measurement'); _m4_projection = TraceConfidenceProjection('cohort', 'v1', (_m4_member.lineage,))
    with pytest.raises(TraceRecordValidationError, match='ambiguous'): _m4_projection.evaluate([_m4_member, _m4_duplicate_head])
def _construct_from(record: TraceRecord, **overrides) -> TraceRecord: values = {'record_type': record.record_type, 'scope': record.scope, 'target': record.target, 'target_class': record.target_class, 'assertion': record.assertion, 'authority': record.authority, 'result': record.result, 'execution_id': record.execution_id, 'causality': record.causality, 'evidence_manifest_digest': record.evidence_manifest_digest, 'occurred_at': record.occurred_at, 'parent_ids': record.parent_ids, 'supersedes_id': record.supersedes_id, 'score': record.score, 'reason_code': record.reason_code}; values.update(overrides); return TraceRecord._construct(**values)
@pytest.mark.parametrize(('overrides', 'message'), [({'scope': 'tenant'}, 'scope must'), ({'target_class': 'financial'}, 'target_class must'), ({'result': TraceResult.AUTHORITATIVE}, 'OBSERVATION requires'), ({'causality': TraceCausality.DIRECT}, 'OBSERVATION requires'), ({'record_type': 'unknown'}, 'unknown TraceRecord type'), ({'evidence_manifest_digest': 'bad'}, 'lowercase sha256'), ({'occurred_at': datetime(2026, 7, 17)}, 'timezone-aware'), ({'score': Decimal('1')}, 'audit Ratio'), ({'score': Ratio(Decimal('2'))}, 'within')])
def test_record_constructor_rejects_invalid_structural_values(overrides, message):
    with pytest.raises(TraceRecordValidationError, match=message): _construct_from(observation(), **overrides)
@dataclass(frozen=True, slots=True)
class PermissivePolicy:
    result: TraceResult = TraceResult.AUTHORITATIVE; causality: object = TraceCausality.DIRECT; target_class: TraceTargetClass = TraceTargetClass.FINANCIAL; assertion: VersionedTraceRef = VersionedTraceRef('promotion', 'edge-policy', 'v1'); authority: TraceAuthorityProfile = authority()
    def fold(self, _parents: Sequence[TraceRecord]) -> TraceDecisionOutcome: return TraceDecisionOutcome(result=self.result, reason_code='edge')
@pytest.mark.parametrize(('field', 'value', 'message'), [('schema_version', 1, 'scalar types'), ('causality', 1, 'causality'), ('supersedes_id', 1, 'supersedes_id'), ('parent_ids', [1], 'parent_ids'), ('scope', [], 'scope must be an object')])
def test_wire_payload_rejects_noncanonical_scalar_shapes(field, value, message):
    payload = observation().wire_payload(); payload[field] = value
    with pytest.raises(TraceRecordValidationError, match=message): TraceRecord.restore(payload)
async def test_emitter_returns_the_complete_ordered_graph(): records = (observation(), observation()); repository = AsyncMock(); repository.append.side_effect = lambda record: record; assert await TraceEmitter(repository).emit_many(records) == records
