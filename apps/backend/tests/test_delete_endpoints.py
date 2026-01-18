from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    Account,
    AccountType,
    BankStatement,
    BankStatementStatus,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
)


@pytest.mark.asyncio
async def test_delete_account(client: AsyncClient, db: AsyncSession, test_user):
    # 1. Create account
    acc = Account(user_id=test_user.id, name="Del", type=AccountType.ASSET, currency="SGD")
    db.add(acc)
    await db.commit()
    await db.refresh(acc)

    # 2. Delete it
    resp = await client.delete(f"/accounts/{acc.id}")
    assert resp.status_code == 204

    # 3. Verify gone
    resp = await client.get(f"/accounts/{acc.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_account_with_transactions_fails(
    client: AsyncClient, db: AsyncSession, test_user
):
    # 1. Create account and entry
    acc = Account(
        user_id=test_user.id, name="DelConstraint", type=AccountType.ASSET, currency="SGD"
    )
    db.add(acc)
    await db.flush()

    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Txn",
        source_type="manual",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()

    line = JournalLine(
        journal_entry_id=entry.id,
        account_id=acc.id,
        direction=Direction.DEBIT,
        amount=Decimal("10"),
        currency="SGD",
    )
    db.add(line)
    await db.commit()
    await db.refresh(acc)

    # 2. Try delete
    resp = await client.delete(f"/accounts/{acc.id}")
    assert resp.status_code == 400
    assert "transactions" in resp.text


@pytest.mark.asyncio
async def test_delete_draft_journal_entry(client: AsyncClient, db: AsyncSession, test_user):
    # 1. Create draft
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Draft",
        source_type="manual",
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    # 2. Delete
    resp = await client.delete(f"/journal-entries/{entry.id}")
    assert resp.status_code == 204

    # 3. Verify gone
    resp = await client.get(f"/journal-entries/{entry.id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_posted_journal_entry_fails(client: AsyncClient, db: AsyncSession, test_user):
    # 1. Create posted
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Posted",
        source_type="manual",
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    # 2. Delete
    resp = await client.delete(f"/journal-entries/{entry.id}")
    assert resp.status_code == 400
    assert "draft" in resp.text.lower()


@pytest.mark.asyncio
async def test_delete_statement(client: AsyncClient, db: AsyncSession, test_user):
    # 1. Create statement
    stmt = BankStatement(
        user_id=test_user.id,
        file_path="test/path.pdf",
        file_hash="hash123",
        original_filename="test.pdf",
        institution="Bank",
        currency="SGD",
        period_start=date.today(),
        period_end=date.today(),
        opening_balance=Decimal("0"),
        closing_balance=Decimal("0"),
        status=BankStatementStatus.PARSED,
    )
    db.add(stmt)
    await db.commit()
    await db.refresh(stmt)

    # 2. Delete
    # Note: This will try to delete from S3 via run_in_threadpool.
    # Since we are mocking storage or relying on S3 service, it might fail if S3 not
    # configured or reachable. However, our code catches Exception log warning and
    # proceeds to DB delete. So unit test should pass 204 regardless of S3 state
    # (unless storage instantiation fails hard). StorageService init might fail if
    # env vars missing. But test_storage.py passes so env likely has defaults.

    resp = await client.delete(f"/statements/{stmt.id}")
    assert resp.status_code == 204

    # 3. Verify gone
    resp = await client.get(f"/statements/{stmt.id}")
    assert resp.status_code == 404
