"""Test enum casing integrity and migration backward-compatibility.

This test protects against the production-outage bug where PostgreSQL enum types
created with uppercase member names in early staging/prod environments rejected
lowercase values emitted by SQLAlchemy's `values_callable=lambda obj: [e.value ...]`.
"""

from pathlib import Path

from src.advisor.orm.chat import ChatMessageRole, ChatSessionStatus
from src.ledger.orm.journal import JournalEntryStatus


def test_journal_entry_status_case_insensitive_deserialization():
    """Verify JournalEntryStatus handles both uppercase and lowercase DB strings."""
    assert JournalEntryStatus("POSTED") == JournalEntryStatus.POSTED
    assert JournalEntryStatus("posted") == JournalEntryStatus.POSTED
    assert JournalEntryStatus("DRAFT") == JournalEntryStatus.DRAFT
    assert JournalEntryStatus("draft") == JournalEntryStatus.DRAFT
    assert JournalEntryStatus("RECONCILED") == JournalEntryStatus.RECONCILED
    assert JournalEntryStatus("reconciled") == JournalEntryStatus.RECONCILED
    assert JournalEntryStatus("VOID") == JournalEntryStatus.VOID
    assert JournalEntryStatus("void") == JournalEntryStatus.VOID


def test_chat_enums_case_insensitive_deserialization():
    """Verify chat session and message role enums handle both casing variants."""
    assert ChatSessionStatus("ACTIVE") == ChatSessionStatus.ACTIVE
    assert ChatSessionStatus("active") == ChatSessionStatus.ACTIVE
    assert ChatSessionStatus("DELETED") == ChatSessionStatus.DELETED
    assert ChatSessionStatus("deleted") == ChatSessionStatus.DELETED

    assert ChatMessageRole("USER") == ChatMessageRole.USER
    assert ChatMessageRole("user") == ChatMessageRole.USER
    assert ChatMessageRole("ASSISTANT") == ChatMessageRole.ASSISTANT
    assert ChatMessageRole("assistant") == ChatMessageRole.ASSISTANT
    assert ChatMessageRole("SYSTEM") == ChatMessageRole.SYSTEM
    assert ChatMessageRole("system") == ChatMessageRole.SYSTEM


def test_migration_0063_provisions_case_compatibility():
    """Verify migration 0063 defines both uppercase and lowercase values for all at-risk enums."""
    mig_path = Path("apps/backend/migrations/versions/0063_enum_case_compat.py")
    if not mig_path.exists():
        # Running from apps/backend directory
        mig_path = Path("migrations/versions/0063_enum_case_compat.py")
    assert mig_path.exists(), f"Migration file not found at {mig_path}"

    content = mig_path.read_text(encoding="utf-8")
    assert "journal_entry_status_enum" in content
    assert '"posted"' in content or "'posted'" in content
    assert '"POSTED"' in content or "'POSTED'" in content
    assert '"draft"' in content or "'draft'" in content
    assert '"DRAFT"' in content or "'DRAFT'" in content
    assert "chat_session_status_enum" in content
    assert '"active"' in content or "'active'" in content
    assert '"ACTIVE"' in content or "'ACTIVE'" in content
    assert "chat_message_role_enum" in content
    assert '"user"' in content or "'user'" in content
    assert '"USER"' in content or "'USER'" in content
