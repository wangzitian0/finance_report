"""Trust hierarchy helpers for journal entry source_type.

This module also *owns* :class:`JournalEntrySourceType` — the provenance/trust
vocabulary the hierarchy ranks (moved here from ``src/models/journal.py`` in
#1675 D5). ``audit`` (L1 infra) can never import upward into ``ledger`` (L3
domain), so the vocabulary lives with its trust policy and the ledger ORM
imports it downward (``from src.audit import JournalEntrySourceType``). The
helpers accept any journal-entry-shaped object structurally (see
:class:`SourceTypedEntry`) rather than importing the ledger ORM class.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable
from typing import Any, Protocol


class JournalEntrySourceType(str, enum.Enum):
    """Source type of a journal entry."""

    MANUAL = "manual"
    USER_CONFIRMED = "user_confirmed"
    AUTO_MATCHED = "auto_matched"
    AUTO_PARSED = "auto_parsed"
    # NOTE: the legacy ``bank_statement`` value was retired in migration 0040
    # (#896). Data was migrated to ``auto_parsed`` in 0018 and no write path
    # emits it. The raw string is still tolerated defensively by
    # ``normalize_source_type`` and the immutability trigger's text guards.
    SYSTEM = "system"
    FX_REVALUATION = "fx_revaluation"


class SourceTypedEntry(Protocol):
    """Structural stand-in for ``ledger``'s ``JournalEntry`` ORM class.

    audit sits below ledger in the layer topology, so these helpers depend on
    the *shape* they need (a mutable ``source_type`` plus an ``id`` tiebreak
    key), never on the ORM class itself.
    """

    source_type: Any
    id: Any


class SourceTypeDowngradeError(ValueError):
    """Raised when a source_type transition would reduce trust."""


# Raw text of the retired ``bank_statement`` source_type (migration 0040, #896).
# Kept as a string so historical values are still normalized away even though
# the enum no longer defines the member.
_LEGACY_BANK_STATEMENT_VALUE = "bank_statement"

TRUST_RANK: dict[JournalEntrySourceType, int] = {
    JournalEntrySourceType.AUTO_PARSED: 1,
    JournalEntrySourceType.AUTO_MATCHED: 2,
    JournalEntrySourceType.USER_CONFIRMED: 3,
    JournalEntrySourceType.MANUAL: 4,
}

STATEMENT_SOURCE_TYPES: tuple[JournalEntrySourceType, ...] = (
    JournalEntrySourceType.AUTO_PARSED,
    JournalEntrySourceType.AUTO_MATCHED,
    JournalEntrySourceType.USER_CONFIRMED,
)

USER_DATA_SOURCE_TYPES: tuple[JournalEntrySourceType, ...] = (
    JournalEntrySourceType.AUTO_PARSED,
    JournalEntrySourceType.AUTO_MATCHED,
    JournalEntrySourceType.USER_CONFIRMED,
    JournalEntrySourceType.MANUAL,
)


def normalize_source_type(source_type: JournalEntrySourceType | str | None) -> JournalEntrySourceType:
    """Normalize legacy source types to the current hierarchy values."""
    if source_type is None:
        return JournalEntrySourceType.MANUAL
    value = source_type.value if isinstance(source_type, JournalEntrySourceType) else str(source_type)
    if value == _LEGACY_BANK_STATEMENT_VALUE:
        return JournalEntrySourceType.AUTO_PARSED
    return JournalEntrySourceType(value)


def source_type_rank(source_type: JournalEntrySourceType | str | None) -> int:
    """Return the trust rank for a source type."""
    try:
        normalized = normalize_source_type(source_type)
    except ValueError:
        return 0
    return TRUST_RANK.get(normalized, 0)


def is_user_data_source_type(source_type: JournalEntrySourceType | str | None) -> bool:
    """Return True when source_type participates in the no-downgrade hierarchy."""
    try:
        normalized = normalize_source_type(source_type)
    except ValueError:
        return False
    return normalized in USER_DATA_SOURCE_TYPES


def statement_source_values() -> list[str]:
    """Return source_type DB values that represent statement-derived entries."""
    return [source_type.value for source_type in STATEMENT_SOURCE_TYPES]


def promote_entry_source_type(
    entry: SourceTypedEntry,
    target: JournalEntrySourceType | str,
    *,
    preserve_higher: bool = True,
) -> bool:
    """Promote an entry source_type without silently downgrading trust.

    Returns True when the entry source_type changed. If preserve_higher is
    False, lower-rank transitions raise SourceTypeDowngradeError.
    """
    current = normalize_source_type(entry.source_type)
    target_type = normalize_source_type(target)

    if not is_user_data_source_type(current) or not is_user_data_source_type(target_type):
        return False

    current_rank = source_type_rank(current)
    target_rank = source_type_rank(target_type)
    if target_rank < current_rank:
        if preserve_higher:
            return False
        raise SourceTypeDowngradeError(f"Cannot downgrade source_type from {current.value} to {target_type.value}")

    if entry.source_type != target_type:
        entry.source_type = target_type
        return True
    return False


def promote_entries_source_type(
    entries: Iterable[SourceTypedEntry],
    target: JournalEntrySourceType | str,
) -> None:
    """Promote all eligible entries to target, preserving higher-trust values."""
    for entry in entries:
        promote_entry_source_type(entry, target)


def source_type_tiebreak_key(entry: SourceTypedEntry) -> tuple[int, Any]:
    """Sort key component for source-aware candidate selection."""
    return (source_type_rank(entry.source_type), entry.id)
