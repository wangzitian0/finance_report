"""Persistence port for the append-only assurance record."""

from __future__ import annotations

from dataclasses import dataclass

from src.audit.base.trace import TraceRecord


@dataclass(frozen=True, slots=True)
class TraceDecisionHead:
    """The physical decision head and whether its complete ancestry is current."""

    record: TraceRecord
    ancestry_current: bool
