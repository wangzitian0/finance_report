"""One statement month must not post twice on two accounts of one user (#2917)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from src.audit import STATEMENT_SOURCE_TYPES
from src.extraction import BankStatementStatus
from src.ledger import AccountType, JournalEntry
from tests.api._statement_router_fixtures import (
    add_reviewed_disposition_rule,
    add_statement,
    add_txn,
    create_statement_account,
)

pytestmark = pytest.mark.asyncio

ROWS = ((date(2025, 1, 3), "10.00"), (date(2025, 1, 9), "20.00"), (date(2025, 1, 21), "30.00"))


async def _month_on_account(db, user_id, file_hash: str, account_name: str, *, suffix: str, last4: str | None):
    account = await create_statement_account(db, user_id, account_name)
    statement = await add_statement(
        db, user_id, file_hash, confidence=89, account_id=account.id, closing="40.00", account_last4=last4
    )
    for txn_date, amount in ROWS:
        await add_txn(
            db,
            statement,
            txn_date=txn_date,
            description=f"PAYNOW GROCER{suffix}",
            amount=Decimal(amount),
            direction="OUT",
        )
    return statement


async def _entry_count(db, user_id) -> int:
    rows = await db.execute(
        select(JournalEntry).where(
            JournalEntry.user_id == user_id, JournalEntry.source_type.in_(STATEMENT_SOURCE_TYPES)
        )
    )
    return len(rows.scalars().all())


async def test_same_month_on_a_second_account_needs_review_before_it_posts(client: AsyncClient, db, test_user):
    pdf_month = await _month_on_account(db, test_user.id, "hash_2917_pdf", "DBS From PDF", suffix="", last4="1234")
    csv_month = await _month_on_account(
        db, test_user.id, "hash_2917_csv", "DBS From CSV", suffix=" REF 7781", last4=None
    )
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="paynow", account_type=AccountType.EXPENSE, category="TRANSFER_OUT"
    )
    await db.commit()

    first = await client.post(f"/statements/{pdf_month.id}/approvals")
    assert first.status_code == status.HTTP_200_OK and first.json()["journal_entries_created"] == 3

    blocked = await client.post(f"/statements/{csv_month.id}/approvals")
    assert blocked.status_code == status.HTTP_400_BAD_REQUEST
    assert "DBS From PDF" in blocked.json()["detail"]
    assert await _entry_count(db, test_user.id) == 3

    conflicts = (await client.get(f"/statements/{csv_month.id}/conflicts")).json()
    assert conflicts["other_statement_matches"] == [
        {"statement_id": str(pdf_month.id), "account_name": "DBS From PDF", "matched_rows": 3, "total_rows": 3}
    ]

    assert (
        await client.post(f"/statements/{csv_month.id}/conflict-resolutions", json={})
    ).status_code == status.HTTP_200_OK
    confirmed = await client.post(f"/statements/{csv_month.id}/approvals")
    assert confirmed.status_code == status.HTTP_200_OK
    assert confirmed.json()["status"] == BankStatementStatus.APPROVED.value
    assert await _entry_count(db, test_user.id) == 6


async def test_two_matching_rows_of_another_account_do_not_block(client: AsyncClient, db, test_user):
    pdf_month = await _month_on_account(db, test_user.id, "hash_2917_a", "DBS Main", suffix="", last4="1234")
    other = await create_statement_account(db, test_user.id, "DBS Second")
    statement = await add_statement(
        db, test_user.id, "hash_2917_b", confidence=89, account_id=other.id, closing="65.00", account_last4=None
    )
    for txn_date, amount in (*ROWS[:2], (date(2025, 1, 25), "5.00")):
        await add_txn(
            db, statement, txn_date=txn_date, description="PAYNOW CAFE", amount=Decimal(amount), direction="OUT"
        )
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="paynow", account_type=AccountType.EXPENSE, category="TRANSFER_OUT"
    )
    await db.commit()

    assert (await client.post(f"/statements/{pdf_month.id}/approvals")).status_code == status.HTTP_200_OK
    assert (await client.post(f"/statements/{statement.id}/approvals")).status_code == status.HTTP_200_OK
    assert await _entry_count(db, test_user.id) == 6
