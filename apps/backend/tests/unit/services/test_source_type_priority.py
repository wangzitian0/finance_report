"""Unit coverage for source_type trust hierarchy helpers."""

from uuid import uuid4

import pytest

from src.models.journal import JournalEntry, JournalEntrySourceType
from src.services.source_type_priority import (
    SourceTypeDowngradeError,
    is_user_data_source_type,
    normalize_source_type,
    promote_entries_source_type,
    promote_entry_source_type,
    source_type_rank,
    source_type_tiebreak_key,
    statement_source_values,
)


def test_normalize_source_type_defaults_and_legacy_values() -> None:
    """Legacy bank_statement values normalize to auto_parsed."""
    assert normalize_source_type(None) == JournalEntrySourceType.MANUAL
    assert normalize_source_type("bank_statement") == JournalEntrySourceType.AUTO_PARSED
    assert normalize_source_type(JournalEntrySourceType.BANK_STATEMENT) == JournalEntrySourceType.AUTO_PARSED


def test_invalid_and_non_user_source_types_are_not_ranked() -> None:
    """Invalid and system source types are outside the user-data trust ladder."""
    assert source_type_rank("unknown") == 0
    assert not is_user_data_source_type("unknown")
    assert not is_user_data_source_type(JournalEntrySourceType.SYSTEM)
    assert statement_source_values() == [
        "auto_parsed",
        "bank_statement",
        "auto_matched",
        "user_confirmed",
    ]


def test_promote_entry_source_type_preserves_higher_trust_values() -> None:
    """Higher-trust values are not silently downgraded."""
    entry = JournalEntry(source_type=JournalEntrySourceType.MANUAL)

    changed = promote_entry_source_type(entry, JournalEntrySourceType.AUTO_PARSED)

    assert not changed
    assert entry.source_type == JournalEntrySourceType.MANUAL


def test_promote_entry_source_type_normalizes_legacy_value_when_preserving() -> None:
    """Legacy bank_statement is normalized even when no rank promotion occurs."""
    entry = JournalEntry(source_type=JournalEntrySourceType.BANK_STATEMENT)

    changed = promote_entry_source_type(entry, JournalEntrySourceType.AUTO_PARSED)

    assert changed
    assert entry.source_type == JournalEntrySourceType.AUTO_PARSED


def test_promote_entry_source_type_preserves_higher_string_current() -> None:
    """String source_type values still participate in no-downgrade checks."""
    entry = JournalEntry(source_type="user_confirmed")

    changed = promote_entry_source_type(entry, JournalEntrySourceType.AUTO_MATCHED)

    assert not changed
    assert entry.source_type == "user_confirmed"


def test_promote_entry_source_type_rejects_explicit_downgrade() -> None:
    """Explicit downgrade attempts raise instead of changing source_type."""
    entry = JournalEntry(source_type=JournalEntrySourceType.USER_CONFIRMED)

    with pytest.raises(SourceTypeDowngradeError):
        promote_entry_source_type(entry, JournalEntrySourceType.AUTO_MATCHED, preserve_higher=False)

    assert entry.source_type == JournalEntrySourceType.USER_CONFIRMED


def test_promote_entry_source_type_ignores_non_user_data_sources() -> None:
    """System-generated entries are not part of statement/manual promotion."""
    entry = JournalEntry(source_type=JournalEntrySourceType.SYSTEM)

    changed = promote_entry_source_type(entry, JournalEntrySourceType.AUTO_MATCHED)

    assert not changed
    assert entry.source_type == JournalEntrySourceType.SYSTEM


def test_promote_entry_source_type_reports_no_change_for_same_value() -> None:
    """Idempotent promotion returns False."""
    entry = JournalEntry(source_type=JournalEntrySourceType.AUTO_MATCHED)

    changed = promote_entry_source_type(entry, JournalEntrySourceType.AUTO_MATCHED)

    assert not changed
    assert entry.source_type == JournalEntrySourceType.AUTO_MATCHED


def test_promote_entries_source_type_promotes_all_eligible_entries() -> None:
    """Batch promotion preserves manual entries while promoting lower-trust entries."""
    auto_parsed = JournalEntry(source_type=JournalEntrySourceType.AUTO_PARSED)
    manual = JournalEntry(source_type=JournalEntrySourceType.MANUAL)

    promote_entries_source_type([auto_parsed, manual], JournalEntrySourceType.AUTO_MATCHED)

    assert auto_parsed.source_type == JournalEntrySourceType.AUTO_MATCHED
    assert manual.source_type == JournalEntrySourceType.MANUAL


def test_source_type_tiebreak_key_uses_rank_then_entry_id() -> None:
    """Candidate sorting prefers higher source_type rank before entry id."""
    entry_id = uuid4()
    entry = JournalEntry(id=entry_id, source_type=JournalEntrySourceType.USER_CONFIRMED)

    assert source_type_tiebreak_key(entry) == (3, entry_id)
