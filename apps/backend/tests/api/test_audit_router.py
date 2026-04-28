"""API tests for EPIC-018 transaction audit trail endpoint."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType, JournalAuditLog, JournalEntry, JournalEntrySourceType, JournalEntryStatus, User

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def audited_entry(db: AsyncSession, test_user: User) -> JournalEntry:
    """Create a journal entry with two audit records for the current user."""
    account = Account(
        id=uuid4(),
        user_id=test_user.id,
        name="Audit Cash",
        type=AccountType.ASSET,
        currency="SGD",
    )
    entry = JournalEntry(
        id=uuid4(),
        user_id=test_user.id,
        entry_date=date(2026, 4, 1),
        memo="Audited transaction",
        source_type=JournalEntrySourceType.BANK_STATEMENT,
        status=JournalEntryStatus.DRAFT,
    )
    db.add_all([account, entry])
    await db.flush()

    db.add_all(
        [
            JournalAuditLog(
                id=uuid4(),
                entry_id=entry.id,
                actor="user",
                action="created",
                old_value=None,
                new_value={"memo": "Audited transaction"},
                created_at=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
            ),
            JournalAuditLog(
                id=uuid4(),
                entry_id=entry.id,
                actor="ai",
                action="classified",
                old_value={"category": None},
                new_value={"category": "Food & Dining", "amount": str(Decimal("12.50"))},
                created_at=datetime(2026, 4, 1, 9, 5, tzinfo=UTC),
            ),
        ]
    )
    await db.commit()
    return entry


async def test_ac18_5_6_get_transaction_audit_returns_chronological_records(
    client: AsyncClient,
    audited_entry: JournalEntry,
) -> None:
    """AC18.5.6: GET /transactions/{id}/audit returns chronological audit trail records."""
    response = await client.get(f"/transactions/{audited_entry.id}/audit")

    assert response.status_code == 200
    data = response.json()
    assert [item["actor"] for item in data["items"]] == ["user", "ai"]
    assert [item["action"] for item in data["items"]] == ["created", "classified"]
    assert data["items"][1]["new_value"]["category"] == "Food & Dining"


async def test_ac18_5_6_get_transaction_audit_scopes_to_current_user(
    client: AsyncClient,
    db: AsyncSession,
) -> None:
    """AC18.5.6: audit endpoint does not expose another user's transaction trail."""
    other_entry = JournalEntry(
        id=uuid4(),
        user_id=uuid4(),
        entry_date=date(2026, 4, 2),
        memo="Other user transaction",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(other_entry)
    await db.flush()
    db.add(
        JournalAuditLog(
            id=uuid4(),
            entry_id=other_entry.id,
            actor="ai",
            action="classified",
            old_value=None,
            new_value={"category": "Hidden"},
            created_at=datetime.now(UTC) + timedelta(minutes=1),
        )
    )
    await db.commit()

    response = await client.get(f"/transactions/{other_entry.id}/audit")

    assert response.status_code == 404
