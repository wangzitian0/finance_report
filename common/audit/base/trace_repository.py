"""Persistence port for the append-only assurance record."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from common.audit.base.trace import TraceLineage, TraceRecord, TraceScope


class TraceRecordRepository(Protocol):
    async def append(self, record: TraceRecord) -> TraceRecord:
        """Flush idempotently in the caller-owned unit of work or raise."""
        ...

    async def get(self, scope: TraceScope, record_id: UUID) -> TraceRecord | None:
        """Read one record within its typed scope."""
        ...

    async def current_decision(
        self, scope: TraceScope, lineage: TraceLineage
    ) -> TraceRecord | None:
        """Return the singleton head only while its full ancestry is current."""
        ...
