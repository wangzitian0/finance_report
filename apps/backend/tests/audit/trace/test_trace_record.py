"""AC-audit.trace-record.1-.2: schema, codec, and authority profile."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.audit import (
    JsonlTraceRecordStore,
    TraceAuthorityProfile,
    TraceJUnitAdapter,
    TraceRecord,
    TraceRecordCodec,
    TraceRecordValidationError,
)

from .conftest import authority, decision_policy, observation


def test_AC_audit_trace_record_1_schema_and_codec_are_canonical():
    record = observation()

    encoded = TraceRecordCodec.encode(record)
    decoded = TraceRecordCodec.decode(encoded)

    assert decoded == record
    assert TraceRecordCodec.encode(decoded) == encoded
    assert json.loads(encoded)["score"] == "1"
    assert len(record.content_digest) == 64
    assert str(record.record_id) == str(decoded.record_id)

    same_instant = observation(
        scope=record.scope,
        occurred_at=datetime(
            2026,
            7,
            17,
            8,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )
    assert same_instant.record_id == record.record_id

    payload = json.loads(encoded)
    payload["raw_financial_payload"] = {"amount": "100.00"}
    with pytest.raises(TraceRecordValidationError, match="unknown fields"):
        TraceRecordCodec.decode(json.dumps(payload))

    structurally_invalid = json.loads(encoded)
    structurally_invalid["record_type"] = "decision"
    structurally_invalid["result"] = "authoritative"
    structurally_invalid["content_digest"] = "0" * 64
    structurally_invalid["record_id"] = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(TraceRecordValidationError, match="policy replay"):
        TraceRecordCodec.decode(json.dumps(structurally_invalid))

    wrong_score_type = json.loads(encoded)
    wrong_score_type["score"] = 1
    with pytest.raises(TraceRecordValidationError, match="score must be a string"):
        TraceRecordCodec.decode(json.dumps(wrong_score_type))


def test_trace_record_jsonl_and_junit_adapters_use_the_canonical_codec(tmp_path: Path):
    record = observation()
    store = JsonlTraceRecordStore(tmp_path / "trace.jsonl")

    assert store.append(record) == record
    assert store.append(record) == record
    assert store.read_all() == [record]

    captured: dict[str, str] = {}
    TraceJUnitAdapter.emit(lambda name, value: captured.__setitem__(name, value), record)
    assert TraceRecordCodec.decode(captured[TraceJUnitAdapter.PROPERTY_KEY]) == record

    decision = TraceRecord.decision(
        scope=record.scope,
        target=record.target,
        policy=decision_policy(),
        execution_id=record.execution_id,
        occurred_at=record.occurred_at,
        parents=[record],
    )
    with pytest.raises(TraceRecordValidationError, match="policy replay"):
        TraceRecordCodec.decode(TraceRecordCodec.encode(decision))
    with pytest.raises(TraceRecordValidationError, match="policy validation"):
        store.append(decision)
    with pytest.raises(TraceRecordValidationError, match="policy validation"):
        TraceJUnitAdapter.emit(lambda _name, _value: None, decision)


def test_AC_audit_trace_record_2_authority_profile_reuses_canonical_matrix():
    with pytest.raises(TraceRecordValidationError, match="proof_kind"):
        authority(tier="LLM-ONLY", proof_kind="exact")

    with pytest.raises(TraceRecordValidationError, match="manual.adjudication"):
        authority(provenance="manual", stage="github_ci.merge_authority")

    manual = TraceAuthorityProfile(
        package="operator",
        tier="CODE-LED",
        proof_kind="exact",
        provenance="manual",
        execution_stage="manual.adjudication",
        assertion_owner_digest="c" * 64,
        producer_version="operator-review@1",
    )
    assert manual.tier == "CODE-LED"

    with pytest.raises(TraceRecordValidationError, match="unknown authority tier"):
        TraceAuthorityProfile(
            package="operator",
            tier="HU",
            proof_kind="evidence",
            provenance="manual",
            execution_stage="manual.adjudication",
            assertion_owner_digest="c" * 64,
            producer_version="operator-review@1",
        )
