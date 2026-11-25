from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import AccountType, Direction, JournalEntry, JournalEntryStatus, post_journal_entry, void_journal_entry
from src.platform import DomainError
from src.request_context import RequestContext
from src.routers.journal import create_entry, get_journal_entry, list_journal_entries, post_entry, void_entry
from src.schemas.journal import JournalEntryCreate, JournalLineCreate, VoidJournalEntryRequest
from tests.ledger._ledger_helpers import (
    create_anchored_test_journal_entry as create_journal_entry,
    create_valid_posted_entry,
    create_valid_void_entry,
    lines_pair,
    make_account,
)


async def test_journal_entry_endpoints_lifecycle(client: AsyncClient, db: AsyncSession, test_user) -> None:
    debit = (await client.post("/accounts", json={"name": "Bank", "type": "ASSET", "currency": "SGD"})).json()
    credit = (await client.post("/accounts", json={"name": "Revenue", "type": "INCOME", "currency": "SGD"})).json()
    older_date = date.today() - timedelta(days=10)

    def _payload(entry_date: date, memo: str, amt: str) -> dict:
        return {
            "entry_date": entry_date.isoformat(),
            "memo": memo,
            "lines": [
                {"account_id": debit["id"], "direction": "DEBIT", "amount": amt, "currency": "SGD"},
                {"account_id": credit["id"], "direction": "CREDIT", "amount": amt, "currency": "SGD"},
            ],
        }

    entry = (await client.post("/journal-entries", json=_payload(date.today(), "Current", "100.00"))).json()
    older = (await client.post("/journal-entries", json=_payload(older_date, "Older", "50.00"))).json()
    draft_del = (await client.post("/journal-entries", json=_payload(date.today(), "Draft del", "10.00"))).json()

    assert (await client.get("/journal-entries", params={"status_filter": "draft"})).json()["total"] >= 2
    start_ids = {
        i["id"]
        for i in (await client.get("/journal-entries", params={"start_date": date.today().isoformat()})).json()["items"]
    }
    end_ids = {
        i["id"]
        for i in (await client.get("/journal-entries", params={"end_date": older_date.isoformat()})).json()["items"]
    }
    assert older["id"] not in start_ids and older["id"] in end_ids

    assert (await client.get(f"/journal-entries/{entry['id']}")).status_code == 200
    assert (await client.get(f"/journal-entries/{uuid4()}")).status_code == 404
    assert (await client.post(f"/journal-entries/{entry['id']}/postings")).json()["status"] == "posted"
    assert (await client.post(f"/journal-entries/{entry['id']}/voidings", json={"reason": "Test void"})).json()[
        "status"
    ] == "posted"
    assert (await client.post(f"/journal-entries/{uuid4()}/postings")).status_code == 404
    assert (await client.post(f"/journal-entries/{uuid4()}/voidings", json={"reason": "missing"})).status_code == 400

    assert (await client.delete(f"/journal-entries/{draft_del['id']}")).status_code == 204
    assert (await client.get(f"/journal-entries/{draft_del['id']}")).status_code == 404
    assert (await client.delete(f"/journal-entries/{uuid4()}")).status_code == 404

    posted = await create_valid_posted_entry(db, test_user.id, memo="Posted")
    voided = await create_valid_void_entry(db, test_user.id, memo="Voided")
    assert (await client.delete(f"/journal-entries/{posted.id}")).status_code == 400
    assert (await client.delete(f"/journal-entries/{voided.id}")).status_code == 400


async def test_journal_router_direct_and_void_memo_limit(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    ctx = RequestContext(db, uid)
    bank = await make_account(db, uid, "Bank", AccountType.ASSET)
    revenue = await make_account(db, uid, "Revenue", AccountType.INCOME, commit=True)

    created = await create_entry(
        JournalEntryCreate(
            entry_date=date.today(),
            memo="Direct",
            lines=[
                JournalLineCreate(
                    account_id=bank.id, direction=Direction.DEBIT, amount=Decimal("100.00"), currency="SGD"
                ),
                JournalLineCreate(
                    account_id=revenue.id, direction=Direction.CREDIT, amount=Decimal("100.00"), currency="SGD"
                ),
            ],
        ),
        ctx,
    )
    older = await create_entry(
        JournalEntryCreate(
            entry_date=date.today() - timedelta(days=7),
            memo="Older",
            lines=[
                JournalLineCreate(
                    account_id=bank.id, direction=Direction.DEBIT, amount=Decimal("50.00"), currency="SGD"
                ),
                JournalLineCreate(
                    account_id=revenue.id, direction=Direction.CREDIT, amount=Decimal("50.00"), currency="SGD"
                ),
            ],
        ),
        ctx,
    )
    listed = await list_journal_entries(
        status_filter=JournalEntryStatus.DRAFT, start_date=date.today(), limit=50, offset=0, ctx=ctx
    )
    older_list = await list_journal_entries(end_date=older.entry_date, limit=50, offset=0, ctx=ctx)
    assert any(i.id == created.id for i in listed.items) and any(i.id == older.id for i in older_list.items)
    assert (await get_journal_entry(created.id, ctx=ctx)).id == created.id
    assert (await post_entry(created.id, ctx=ctx)).status == JournalEntryStatus.POSTED
    assert (
        await void_entry(created.id, VoidJournalEntryRequest(reason="Test void"), ctx=ctx)
    ).status == JournalEntryStatus.POSTED
    for fn in (
        lambda: get_journal_entry(uuid4(), ctx=ctx),
        lambda: post_entry(uuid4(), ctx=ctx),
        lambda: void_entry(uuid4(), VoidJournalEntryRequest(reason="Missing"), ctx=ctx),
    ):
        with pytest.raises(DomainError):
            await fn()

    memo = "M" * 500
    full_entry = await create_journal_entry(
        db, uid, date(2026, 1, 1), memo, lines_pair(bank.id, revenue.id, "10.00"), base_currency="SGD"
    )
    await post_journal_entry(db, full_entry.id, uid, base_currency="SGD")
    await db.commit()
    reversal = await void_journal_entry(db, full_entry.id, "Correction", uid, base_currency="SGD")
    assert len(reversal.memo) == 500 and reversal.memo == ("VOID: " + memo)[:500]
