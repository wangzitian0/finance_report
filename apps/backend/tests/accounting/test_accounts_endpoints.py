from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import (
    Account,
    AccountType,
    Direction,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    ValidationError,
    account_service,
    get_or_create_processing_account,
)
from src.ledger.extension.account_service import AccountNotFoundError
from src.portfolio.extension.positions import PositionService
from src.schemas.account import AccountCreate, AccountUpdate


async def test_accounts_endpoints(client: AsyncClient, db: AsyncSession, test_user) -> None:
    resp = await client.post("/accounts", json={"name": "Cash", "type": "ASSET", "currency": "SGD"})
    assert resp.status_code == 201, resp.text
    account = resp.json()

    basic = await client.get("/accounts")
    assert basic.status_code == 200 and basic.json()["total"] >= 1
    with_bal = await client.get("/accounts", params={"include_balance": "true"})
    assert with_bal.status_code == 200 and with_bal.json()["items"][0]["balance"] is not None
    assert (await client.get("/accounts", params={"account_type": "ASSET"})).status_code == 200

    updated = await client.put(
        f"/accounts/{account['id']}", json={"name": "Cash Vault", "code": "1001", "description": "Updated"}
    )
    assert updated.status_code == 200 and updated.json()["name"] == "Cash Vault"
    deactivated = await client.put(f"/accounts/{account['id']}", json={"is_active": False})
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    inactive = await client.get("/accounts", params={"is_active": "false"})
    assert inactive.status_code == 200 and inactive.json()["total"] >= 1
    assert (await client.put(f"/accounts/{uuid4()}", json={"name": "Missing"})).status_code == 404

    del_resp = await client.delete(f"/accounts/{account['id']}")
    assert del_resp.status_code == 204
    assert account["id"] not in {item["id"] for item in (await client.get("/accounts")).json()["items"]}


async def test_system_accounts_cannot_be_updated_or_deleted(client: AsyncClient, db: AsyncSession, test_user) -> None:
    sys_account = await get_or_create_processing_account(db, test_user.id, currency="SGD")
    await db.commit()
    with pytest.raises(ValidationError, match="System accounts cannot be modified or deleted"):
        await account_service.update_account(db, test_user.id, sys_account.id, AccountUpdate(name="Renamed System"))
    for resp in (
        await client.put(f"/accounts/{sys_account.id}", json={"name": "Renamed System"}),
        await client.delete(f"/accounts/{sys_account.id}"),
    ):
        assert resp.status_code == 400 and "System accounts cannot be modified or deleted" in resp.json()["detail"]

    inactive_broker = Account(
        user_id=test_user.id, name="Moomoo SG", type=AccountType.ASSET, currency="SGD", code="AUTO-ASSET", is_active=False
    )
    db.add(inactive_broker)
    await db.commit()
    resolved = await PositionService()._get_or_create_broker_account(
        db, user_id=test_user.id, broker_name="Moomoo SG", currency="SGD"
    )
    assert resolved.id != inactive_broker.id and resolved.is_active is True


async def test_delete_account_with_transactions_and_delete_statement(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    acc = Account(user_id=test_user.id, name="DelConstraint", type=AccountType.ASSET, currency="SGD")
    db.add(acc)
    await db.flush()
    entry = JournalEntry(
        user_id=test_user.id, entry_date=date.today(), memo="Txn", source_type="manual", status=JournalEntryStatus.DRAFT
    )
    db.add(entry)
    await db.flush()
    db.add(
        JournalLine(
            journal_entry_id=entry.id,
            account_id=acc.id,
            direction=Direction.DEBIT,
            amount=Decimal("10"),
            currency="SGD",
        )
    )
    stmt = StatementSummary(
        user_id=test_user.id,
        file_hash="hash123",
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
    del_acc = await client.delete(f"/accounts/{acc.id}")
    assert del_acc.status_code == 400 and "transactions" in del_acc.text.lower()
    assert (await client.delete(f"/statements/{stmt.id}")).status_code == 204
    assert (await client.get(f"/statements/{stmt.id}")).status_code == 404


async def test_accounts_service_crud_and_not_found(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    acc1 = await account_service.create_account(
        db,
        uid,
        AccountCreate(name="Operating", type=AccountType.ASSET, currency="SGD", code="1001", description="Main"),
    )
    await account_service.create_account(db, uid, AccountCreate(name="Card", type=AccountType.LIABILITY, currency="SGD"))
    fetched = await account_service.get_account(db, uid, acc1.id)
    assert fetched.id == acc1.id and fetched.code == "1001"
    updated = await account_service.update_account(
        db, uid, acc1.id, AccountUpdate(name="New Name", code="2002", description="Updated", is_active=False)
    )
    assert (updated.name, updated.code, updated.description, updated.is_active) == (
        "New Name",
        "2002",
        "Updated",
        False,
    )
    results, total = await account_service.list_accounts(db, uid)
    assert total >= 2 and len(results) >= 2
    liab, liab_total = await account_service.list_accounts(db, uid, account_type=AccountType.LIABILITY)
    assert liab_total >= 1 and all(a.type == AccountType.LIABILITY for a in liab)
    with pytest.raises(AccountNotFoundError):
        await account_service.get_account(db, uid, uuid4())
    with pytest.raises(AccountNotFoundError):
        await account_service.update_account(db, uid, uuid4(), AccountUpdate(name="Missing"))
