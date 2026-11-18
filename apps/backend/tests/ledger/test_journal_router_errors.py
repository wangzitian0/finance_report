from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from src.ledger import AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine, ValidationError
from src.schemas.journal import JournalLineCreate
from tests.ledger._ledger_helpers import make_account


async def test_journal_router_error_responses(client, db, test_user) -> None:
    cash = await make_account(db, test_user.id, "Cash", AccountType.ASSET)
    revenue = await make_account(db, test_user.id, "Revenue", AccountType.INCOME, commit=True)

    unbalanced = await client.post(
        "/journal-entries",
        json={
            "entry_date": str(date.today()),
            "memo": "Unbalanced",
            "lines": [
                {"account_id": str(cash.id), "direction": "DEBIT", "amount": "100.00", "currency": "SGD"},
                {"account_id": str(revenue.id), "direction": "CREDIT", "amount": "200.00", "currency": "SGD"},
            ],
        },
    )
    assert unbalanced.status_code == 400 and "balance" in str(unbalanced.json()).lower()

    unknown = await client.post(
        "/journal-entries",
        json={
            "entry_date": str(date.today()),
            "memo": "Unknown",
            "lines": [
                {"account_id": str(uuid4()), "direction": "DEBIT", "amount": "100.00", "currency": "SGD"},
                {"account_id": str(uuid4()), "direction": "CREDIT", "amount": "100.00", "currency": "SGD"},
            ],
        },
    )
    assert unknown.status_code == 400 and "not found" in unknown.json()["detail"].lower()

    assert (await client.post("/journal-entries", json={"entry_date": "2024-01-01", "lines": "bad"})).status_code == 422

    unproven = JournalEntry(
        user_id=test_user.id,
        entry_date=date.today(),
        memo="Unproven",
        status=JournalEntryStatus.DRAFT,
        lines=[
            JournalLine(account=cash, direction=Direction.DEBIT, amount=Decimal("100.00"), currency="SGD"),
            JournalLine(account=revenue, direction=Direction.CREDIT, amount=Decimal("100.00"), currency="SGD"),
        ],
    )
    db.add(unproven)
    await db.commit()
    post_resp = await client.post(f"/journal-entries/{unproven.id}/postings")
    assert post_resp.status_code == 400 and "legacy-unproven" in post_resp.json()["detail"].lower()

    with patch("src.routers.journal.void_journal_entry", new_callable=AsyncMock, side_effect=ValidationError("Cannot void draft entry")):
        void_resp = await client.post(f"/journal-entries/{unproven.id}/voidings", json={"reason": "Test void"})
        assert void_resp.status_code == 400 and "draft" in void_resp.json()["detail"].lower()


async def test_journal_wire_bounds_and_tags_validation(client, db, test_user) -> None:
    cash = await make_account(db, test_user.id, "Wire Cash", AccountType.ASSET)
    rev = await make_account(db, test_user.id, "Wire Rev", AccountType.INCOME, commit=True)
    for bad_amount in ("10000000000000000.00", "1E+20", "10.123"):
        with pytest.raises(PydanticValidationError):
            JournalLineCreate(account_id=cash.id, direction=Direction.DEBIT, amount=bad_amount, currency="SGD")
    for bad_fx in ("1000000000000.000000", "1E+15", "1.1234567"):
        with pytest.raises(PydanticValidationError):
            JournalLineCreate(account_id=cash.id, direction=Direction.DEBIT, amount="100.00", currency="USD", fx_rate=bad_fx)
    for bad_tags in ({"rate": 1.25}, {"nested": [1, 1e16]}, {"bad\x00key": "ok"}, {"key": "bad\x00val"}):
        resp = await client.post(
            "/journal-entries",
            json={
                "entry_date": str(date.today()),
                "memo": "Bad tags",
                "lines": [
                    {"account_id": str(cash.id), "direction": "DEBIT", "amount": "100.00", "currency": "SGD", "tags": bad_tags},
                    {"account_id": str(rev.id), "direction": "CREDIT", "amount": "100.00", "currency": "SGD"},
                ],
            },
        )
        assert resp.status_code == 422
