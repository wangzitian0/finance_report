from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.identity import User
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine


async def create_test_bank_account(db, user: User, currency: str = "SGD") -> Account:
    account = Account(
        user_id=user.id, name=f"Bank Account {uuid4().hex[:8]}", type=AccountType.ASSET, currency=currency
    )
    db.add(account)
    await db.flush()
    return account


class TestReconciliationAdjustmentApi:
    @pytest.mark.parametrize(
        ("bank_balance", "expected_diff", "is_gain", "bank_dir", "rounding_dir"),
        [
            ("500.03", "0.03", True, Direction.DEBIT, Direction.CREDIT),
            ("499.97", "-0.03", False, Direction.CREDIT, Direction.DEBIT),
        ],
    )
    async def test_adjustment_gain_and_loss_success(
        self, client: AsyncClient, db, test_user: User, bank_balance, expected_diff, is_gain, bank_dir, rounding_dir
    ):
        bank = await create_test_bank_account(db, test_user, currency="SGD")
        await db.commit()
        resp = await client.post(
            "/reconciliation/adjustments",
            json={"account_id": str(bank.id), "bank_balance": bank_balance, "book_balance": "500.00"},
        )
        assert resp.status_code == status.HTTP_200_OK
        data = resp.json()
        assert (data["account_id"], data["difference"], data["is_gain"]) == (str(bank.id), expected_diff, is_gain)
        entry = (
            await db.execute(
                select(JournalEntry)
                .options(selectinload(JournalEntry.lines).selectinload(JournalLine.account))
                .where(JournalEntry.id == UUID(data["journal_entry_id"]))
            )
        ).scalar_one()
        assert entry.status == JournalEntryStatus.POSTED and len(entry.lines) == 2
        lines = {line.account_id: line for line in entry.lines}
        rounding = next(line for line in entry.lines if line.account_id != bank.id)
        assert (lines[bank.id].direction, lines[bank.id].amount) == (bank_dir, Decimal("0.03"))
        assert (rounding.account.name, rounding.account.currency, rounding.direction, rounding.amount) == (
            "BankRoundingDifference",
            "SGD",
            rounding_dir,
            Decimal("0.03"),
        )
        assert rounding.account.type in (AccountType.INCOME, AccountType.EXPENSE)

    @pytest.mark.parametrize(
        ("missing_acc", "currency", "bank_balance", "expected_status", "detail_part"),
        [
            (False, "SGD", "501.00", status.HTTP_400_BAD_REQUEST, "exceeds immaterial threshold"),
            (True, "SGD", "500.03", status.HTTP_404_NOT_FOUND, None),
            (False, "USD", "500.03", status.HTTP_400_BAD_REQUEST, "fx_rate is required"),
        ],
    )
    async def test_adjustment_error_cases(
        self,
        client: AsyncClient,
        db,
        test_user: User,
        missing_acc,
        currency,
        bank_balance,
        expected_status,
        detail_part,
    ):
        if missing_acc:
            acc_id = uuid4()
        else:
            acc_id = (await create_test_bank_account(db, test_user, currency=currency)).id
            await db.commit()
        resp = await client.post(
            "/reconciliation/adjustments",
            json={"account_id": str(acc_id), "bank_balance": bank_balance, "book_balance": "500.00"},
        )
        assert resp.status_code == expected_status
        if detail_part:
            assert detail_part in resp.json()["detail"]

    async def test_adjustment_zero_diff_no_entry(self, client: AsyncClient, db, test_user: User):
        bank = await create_test_bank_account(db, test_user)
        await db.commit()
        data = (
            await client.post(
                "/reconciliation/adjustments",
                json={"account_id": str(bank.id), "bank_balance": "500.00", "book_balance": "500.00"},
            )
        ).json()
        assert (data["difference"], data["journal_entry_id"], data.get("entry")) == ("0.00", None, None)

    async def test_adjustment_non_base_currency_with_fx_rate(self, client: AsyncClient, db, test_user: User):
        bank = await create_test_bank_account(db, test_user, currency="USD")
        await db.commit()
        resp = await client.post(
            "/reconciliation/adjustments",
            json={"account_id": str(bank.id), "bank_balance": "500.03", "book_balance": "500.00", "fx_rate": "1.35"},
        )
        assert resp.status_code == status.HTTP_200_OK
        entry = (
            await db.execute(
                select(JournalEntry)
                .options(selectinload(JournalEntry.lines))
                .where(JournalEntry.id == UUID(resp.json()["journal_entry_id"]))
            )
        ).scalar_one()
        assert all(line.fx_rate == Decimal("1.35") for line in entry.lines)
