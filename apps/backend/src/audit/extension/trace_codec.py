"""Canonical JSON codec shared by JSONL and JUnit adapters."""

from __future__ import annotations

import json

from src.audit.base.trace import TraceRecord, TraceRecordValidationError

_FIELDS = frozenset(
    {
        "schema_version",
        "record_type",
        "scope",
        "target",
        "target_class",
        "assertion",
        "authority",
        "result",
        "execution_id",
        "causality",
        "evidence_manifest_digest",
        "occurred_at",
        "parent_ids",
        "supersedes_id",
        "score",
        "reason_code",
        "content_digest",
        "record_id",
    }
)


class TraceRecordCodec:
    """Strict canonical wire codec; unknown or missing fields fail closed."""

    @staticmethod
    def encode(record: TraceRecord) -> str:
        if not isinstance(record, TraceRecord):
            raise TypeError("TraceRecordCodec.encode expects TraceRecord")
        return json.dumps(
            record.wire_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    @staticmethod
    def decode(raw: str) -> TraceRecord:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise TraceRecordValidationError("TraceRecord is not valid JSON") from exc
        if not isinstance(payload, dict):
            raise TraceRecordValidationError("TraceRecord payload must be an object")
        unknown = sorted(set(payload) - _FIELDS)
        missing = sorted(_FIELDS - set(payload))
        if unknown:
            raise TraceRecordValidationError(f"TraceRecord has unknown fields: {', '.join(unknown)}")
        if missing:
            raise TraceRecordValidationError(f"TraceRecord is missing fields: {', '.join(missing)}")
        try:
            return TraceRecord.restore(payload)
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, TraceRecordValidationError):
                raise
            raise TraceRecordValidationError(f"invalid TraceRecord payload: {exc}") from exc
