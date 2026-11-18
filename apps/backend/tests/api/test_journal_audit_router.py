from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.identity import User
from src.ledger import AccountType, JournalAuditLog, JournalEntry, JournalEntryStatus
from tests.factories import AccountFactory, UserFactory

pytestmark = pytest.mark.asyncio


async def test_ac18_5_6_get_transaction_audit_chronological_and_user_scoped(
    client: AsyncClient, db: AsyncSession, test_user: User
) -> None:
    await AccountFactory.create_async(db, user_id=test_user.id, name="Audit Cash", type=AccountType.ASSET)
    entry = JournalEntry(
        id=uuid4(),
        user_id=test_user.id,
        entry_date=date(2026, 4, 1),
        memo="Audited",
        source_type=JournalEntrySourceType.AUTO_PARSED,
        status=JournalEntryStatus.DRAFT,
    )
    other_entry = JournalEntry(
        id=uuid4(),
        user_id=(await UserFactory.create_async(db)).id,
        entry_date=date(2026, 4, 2),
        memo="Other",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add_all([entry, other_entry])
    await db.flush()
    db.add_all(
        [
            JournalAuditLog(
                id=uuid4(),
                entry_id=entry.id,
                actor="user",
                action="created",
                old_value=None,
                new_value={"memo": "Audited"},
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
            JournalAuditLog(
                id=uuid4(),
                entry_id=other_entry.id,
                actor="ai",
                action="classified",
                old_value=None,
                new_value={"category": "Hidden"},
                created_at=datetime.now(UTC) + timedelta(minutes=1),
            ),
        ]
    )
    await db.commit()
    resp = await client.get(f"/journal-entries/{entry.id}/audit")
    items = resp.json()["items"]
    assert resp.status_code == 200 and [(i["actor"], i["action"]) for i in items] == [
        ("user", "created"),
        ("ai", "classified"),
    ]
    assert items[1]["new_value"]["category"] == "Food & Dining"
    assert (await client.get(f"/journal-entries/{other_entry.id}/audit")).status_code == 404
