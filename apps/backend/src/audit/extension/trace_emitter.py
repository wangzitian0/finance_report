"""Fail-closed TraceRecord writer composed with a repository port."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src.audit.base.trace import TraceRecord
from src.audit.base.trace_repository import TraceRecordRepository


@dataclass(frozen=True, slots=True)
class TraceEmitter:
    repository: TraceRecordRepository

    async def emit(self, record: TraceRecord) -> TraceRecord:
        """Return after the repository flushes the append in the caller's UoW."""
        return await self.repository.append(record)

    async def emit_many(self, records: Sequence[TraceRecord]) -> tuple[TraceRecord, ...]:
        """Flush an ordered causal set; any failure must abort the caller's UoW."""
        emitted: list[TraceRecord] = []
        for record in records:
            emitted.append(await self.emit(record))
        return tuple(emitted)
