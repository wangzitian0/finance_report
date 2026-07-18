"""Typed, immutable reference from a ledger command to an authority decision."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from src.audit import TraceRecord, TraceRecordType, TraceResult, TraceTargetClass, VersionedTraceRef
from src.ledger.base.types.errors import LedgerError


class DecisionAnchorError(LedgerError):
    """A ledger command lacks a current, exact financial authority decision."""


def journal_command_target(
    *,
    entry_date: date,
    memo: str,
    lines_data: list[dict],
    base_currency: str,
    source_identity: str,
) -> VersionedTraceRef:
    """Return the exact financial target for one normalized journal command.

    A source transaction is evidence for a command, not the command itself. The
    target therefore includes every persisted financial field and the effective
    base currency used by the independent balance and FX validators.
    """
    normalized_base_currency = base_currency.upper()
    lines = [
        {
            "account_id": str(line["account_id"]),
            "direction": getattr(line["direction"], "value", str(line["direction"])),
            "amount": str(Decimal(str(line["amount"]))),
            "currency": str(line.get("currency") or normalized_base_currency).upper(),
            "fx_rate": str(Decimal(str(line["fx_rate"]))) if line.get("fx_rate") is not None else None,
            "event_type": line.get("event_type"),
            "tags": line.get("tags"),
        }
        for line in lines_data
    ]
    payload = json.dumps(
        {
            "schema_version": "1",
            "entry_date": entry_date.isoformat(),
            "memo": memo,
            "lines": lines,
            "base_currency": normalized_base_currency,
            "source_identity": source_identity,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return VersionedTraceRef("journal_command", source_identity, digest)


@dataclass(frozen=True, slots=True)
class DecisionAnchor:
    """Exact decision, target, and policy versions that authorize one command."""

    decision_id: UUID
    target: VersionedTraceRef
    policy_assertion: VersionedTraceRef

    @classmethod
    def from_record(cls, record: TraceRecord) -> DecisionAnchor:
        if record.record_type is not TraceRecordType.DECISION:
            raise DecisionAnchorError("decision anchor must reference a TraceRecord decision")
        if record.result is not TraceResult.AUTHORITATIVE:
            raise DecisionAnchorError("decision anchor must reference authoritative authority")
        if record.target_class is not TraceTargetClass.FINANCIAL:
            raise DecisionAnchorError("decision anchor must target a financial fact")
        return cls(
            decision_id=record.record_id,
            target=record.target,
            policy_assertion=record.assertion,
        )
