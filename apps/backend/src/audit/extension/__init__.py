"""TraceRecord codecs and persistence adapters."""

from src.audit.extension.terminal_audit import (
    TERMINAL_AUDIT_POLICY_VERSION,
    TerminalAuditVerifier,
)
from src.audit.extension.trace_adapters import TraceJUnitAdapter
from src.audit.extension.trace_codec import TraceRecordCodec
from src.audit.extension.trace_decision_projection import (
    current_authoritative_trace_decision_projection,
    current_authoritative_trace_decisions,
    shared_current_authority,
    trace_decision_projection,
)
from src.audit.extension.trace_emitter import TraceEmitter
from src.audit.extension.trace_repository import (
    SqlTraceRecordRepository,
    TraceRecordPersistenceError,
)

__all__ = [
    "TERMINAL_AUDIT_POLICY_VERSION",
    "TerminalAuditVerifier",
    "SqlTraceRecordRepository",
    "TraceEmitter",
    "TraceJUnitAdapter",
    "TraceRecordCodec",
    "TraceRecordPersistenceError",
    "current_authoritative_trace_decision_projection",
    "current_authoritative_trace_decisions",
    "shared_current_authority",
    "trace_decision_projection",
]
