"""Canonical JSONL/JUnit adapters for TraceRecord."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.audit.base.trace import (
    TraceRecord,
    TraceRecordType,
    TraceRecordValidationError,
)
from src.audit.extension.trace_codec import TraceRecordCodec


class JsonlTraceRecordStore:
    """Small append-only artifact adapter used outside the production database."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def append(self, record: TraceRecord) -> TraceRecord:
        if record.record_type is TraceRecordType.DECISION:
            raise TraceRecordValidationError("DECISION artifacts require repository policy validation")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                for existing in _decode_jsonl(handle.read()):
                    if existing.record_id == record.record_id:
                        if existing.content_digest != record.content_digest:
                            raise TraceRecordValidationError("TraceRecord id collision in JSONL")
                        return existing
                handle.seek(0, os.SEEK_END)
                handle.write(TraceRecordCodec.encode(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return record

    def read_all(self) -> list[TraceRecord]:
        if not self._path.exists():
            return []
        with self._path.open("r", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                return _decode_jsonl(handle.read())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class TraceJUnitAdapter:
    """Emit the same canonical record through pytest/JUnit properties."""

    PROPERTY_KEY = "trace_record"

    @classmethod
    def emit(
        cls,
        record_property: Callable[[str, Any], None],
        record: TraceRecord,
    ) -> TraceRecord:
        if record.record_type is TraceRecordType.DECISION:
            raise TraceRecordValidationError("DECISION artifacts require repository policy validation")
        record_property(cls.PROPERTY_KEY, TraceRecordCodec.encode(record))
        return record


def _decode_jsonl(content: str) -> list[TraceRecord]:
    records: list[TraceRecord] = []
    for line_number, raw in enumerate(content.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            records.append(TraceRecordCodec.decode(raw))
        except TraceRecordValidationError as exc:
            raise TraceRecordValidationError(f"invalid TraceRecord JSONL line {line_number}: {exc}") from exc
    return records
