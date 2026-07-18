"""TraceRecord codecs and persistence adapters."""

from src.audit.extension.promotion_trace import (
    PromotionTraceAdapter,
    PromotionTraceContext,
    PromotionTracePolicy,
)
from src.audit.extension.trace_adapters import JsonlTraceRecordStore, TraceJUnitAdapter
from src.audit.extension.trace_codec import TraceRecordCodec
from src.audit.extension.trace_decision_projection import (
    current_authoritative_trace_decision_projection,
    trace_decision_projection,
)
from src.audit.extension.trace_emitter import TraceEmitter
from src.audit.extension.trace_repository import (
    SqlTraceRecordRepository,
    TraceRecordPersistenceError,
)

__all__ = [
    "JsonlTraceRecordStore",
    "PromotionTraceAdapter",
    "PromotionTraceContext",
    "PromotionTracePolicy",
    "SqlTraceRecordRepository",
    "TraceEmitter",
    "TraceJUnitAdapter",
    "TraceRecordCodec",
    "TraceRecordPersistenceError",
    "current_authoritative_trace_decision_projection",
    "trace_decision_projection",
]
