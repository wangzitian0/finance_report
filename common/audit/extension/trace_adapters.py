"""Canonical JUnit adapter for TraceRecord."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from common.audit.base.trace import (
    TraceRecord,
    TraceRecordType,
    TraceRecordValidationError,
)
from common.audit.extension.trace_codec import TraceRecordCodec


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
            raise TraceRecordValidationError(
                "DECISION artifacts require repository policy validation"
            )
        record_property(cls.PROPERTY_KEY, TraceRecordCodec.encode(record))
        return record
