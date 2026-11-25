from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.audit import (
    TraceAuthorityProfile,
    TraceJUnitAdapter,
    TraceRecord,
    TraceRecordCodec,
    TraceRecordValidationError,
)
from tests.audit.trace.conftest import authority, decision_policy, observation


def test_AC_audit_trace_record_1_and_2_codec_junit_and_authority_matrix() -> None:
    record = observation()
    encoded = TraceRecordCodec.encode(record)
    decoded = TraceRecordCodec.decode(encoded)
    same_instant = observation(
        scope=record.scope, occurred_at=datetime(2026, 7, 17, 8, tzinfo=timezone(timedelta(hours=8)))
    )
    captured: dict[str, str] = {}
    TraceJUnitAdapter.emit(lambda name, value: captured.__setitem__(name, value), record)
    manual = TraceAuthorityProfile(
        package="operator",
        tier="CODE-LED",
        proof_kind="exact",
        provenance="manual",
        execution_stage="manual.adjudication",
        assertion_owner_digest="c" * 64,
        producer_version="operator-review@1",
    )
    assert (
        decoded,
        TraceRecordCodec.encode(decoded),
        json.loads(encoded)["score"],
        len(record.content_digest),
        str(record.record_id),
        same_instant.record_id,
        TraceRecordCodec.decode(captured[TraceJUnitAdapter.PROPERTY_KEY]),
        manual.tier,
    ) == (
        record,
        encoded,
        "1",
        64,
        str(decoded.record_id),
        record.record_id,
        record,
        "CODE-LED",
    )

    decision = TraceRecord.decision(
        scope=record.scope,
        target=record.target,
        policy=decision_policy(),
        execution_id=record.execution_id,
        occurred_at=record.occurred_at,
        parents=[record],
    )
    payload = json.loads(encoded)
    for fn, match in (
        (
            lambda: TraceRecordCodec.decode(json.dumps({**payload, "raw_financial_payload": {"amount": "100.00"}})),
            "unknown fields",
        ),
        (
            lambda: TraceRecordCodec.decode(
                json.dumps(
                    {
                        **payload,
                        "record_type": "decision",
                        "result": "authoritative",
                        "content_digest": "0" * 64,
                        "record_id": "00000000-0000-0000-0000-000000000000",
                    }
                )
            ),
            "policy replay",
        ),
        (lambda: TraceRecordCodec.decode(json.dumps({**payload, "score": 1})), "score must be a string"),
        (lambda: TraceRecordCodec.decode(TraceRecordCodec.encode(decision)), "policy replay"),
        (lambda: TraceJUnitAdapter.emit(lambda _n, _v: None, decision), "policy validation"),
        (lambda: authority(tier="LLM-ONLY", proof_kind="exact"), "proof_kind"),
        (lambda: authority(provenance="manual", stage="github_ci.merge_authority"), "manual.adjudication"),
        (
            lambda: TraceAuthorityProfile(
                package="operator",
                tier="HU",
                proof_kind="evidence",
                provenance="manual",
                execution_stage="manual.adjudication",
                assertion_owner_digest="c" * 64,
                producer_version="operator-review@1",
            ),
            "unknown authority tier",
        ),
    ):
        with pytest.raises(TraceRecordValidationError, match=match):
            fn()
