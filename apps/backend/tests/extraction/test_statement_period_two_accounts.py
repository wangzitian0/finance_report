"""One statement month must not post twice on two accounts of one user (#2917)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from src.audit import STATEMENT_SOURCE_TYPES
from src.extraction import BankStatementStatus, resolve_statement_conflicts
from src.ledger import AccountType, JournalEntry
from tests.api._statement_router_fixtures import (
    add_reviewed_disposition_rule,
    add_statement,
    add_txn,
    create_statement_account,
)
from tests.factories import UserFactory

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


EXTRA = ((date(2025, 1, 25), "5.00"), (date(2025, 1, 27), "6.00"))
FOURTH = (date(2025, 1, 22), "40.00")
SEVEN = (date(2025, 1, 28), "7.00")
TEN = tuple((date(2025, 1, 10 + day), f"{day + 11}.25") for day in range(7))
TEN_OTHER = tuple((date(2025, 1, 18 + day), "91.00") for day in range(3))
TEN_MINE = tuple((date(2025, 1, 18 + day), "92.00") for day in range(3))


@pytest.mark.parametrize(
    ("case", "other_rows", "rows", "statement_fields", "other_user", "matches"),
    [
        ("same_rows", ROWS, ROWS, {}, False, True),
        ("all_four_rows_of_the_smaller_statement", (*ROWS, FOURTH), (*ROWS, FOURTH, EXTRA[0]), {}, False, True),
        ("four_of_five_rows_on_both_sides", (*ROWS, FOURTH, SEVEN), (*ROWS, FOURTH, EXTRA[0]), {}, False, True),
        ("seven_of_ten_rows_on_both_sides", (*TEN[:7], *TEN_OTHER), (*TEN[:7], *TEN_MINE), {}, False, False),
        ("two_rows_only", ROWS, ROWS[:2], {}, False, False),
        ("all_rows_of_the_smaller_statement", ROWS, (*ROWS, *EXTRA), {}, False, True),
        (
            "three_of_five_rows_on_both_sides",
            (*ROWS, FOURTH, (date(2025, 1, 28), "7.00")),
            (*ROWS, *EXTRA),
            {},
            False,
            False,
        ),
        ("other_currency", ROWS, ROWS, {"currency": "USD"}, False, False),
        (
            "period_does_not_overlap",
            ROWS,
            ROWS,
            {"period_start": date(2025, 2, 1), "period_end": date(2025, 2, 28)},
            False,
            False,
        ),
        ("statement_of_another_user", ROWS, ROWS, {}, True, False),
    ],
)
async def test_the_other_account_match_follows_its_definition(
    client: AsyncClient, db, test_user, case, other_rows, rows, statement_fields, other_user, matches
):
    """#2917: each part of the match is pinned: user, currency, overlap, 3 rows, 80 percent of the smaller one."""
    owner = (await UserFactory.create_async(db)).id if other_user else test_user.id
    approved_account = await create_statement_account(db, owner, f"Approved {case}")
    approved = await add_statement(
        db,
        owner,
        f"hash_2917_{case}_a",
        status=BankStatementStatus.APPROVED,
        account_id=approved_account.id,
        closing="40.00",
    )
    for txn_date, amount in other_rows:
        await add_txn(
            db, approved, txn_date=txn_date, description="PAYNOW GROCER", amount=Decimal(amount), direction="OUT"
        )
    account = await create_statement_account(db, test_user.id, f"Second {case}")
    statement = await add_statement(
        db, test_user.id, f"hash_2917_{case}_b", account_id=account.id, closing="40.00", **statement_fields
    )
    for txn_date, amount in rows:
        await add_txn(
            db, statement, txn_date=txn_date, description="PAYNOW CAFE", amount=Decimal(amount), direction="OUT"
        )
    await db.commit()

    found = (await client.get(f"/statements/{statement.id}/conflicts")).json()["other_statement_matches"]
    assert [match["statement_id"] for match in found] == ([str(approved.id)] if matches else [])


async def test_a_quarter_after_an_approved_month_needs_review_before_it_posts(client: AsyncClient, db, test_user):
    """#2917: the month rows are one third of the quarter, and all of the approved month."""
    month = await _month_on_account(db, test_user.id, "hash_2917_month", "DBS Month", suffix="", last4="1234")
    account = await create_statement_account(db, test_user.id, "DBS Quarter")
    quarter = await add_statement(
        db, test_user.id, "hash_2917_quarter", confidence=89, account_id=account.id, closing="16.00", account_last4=None
    )
    later = tuple((date(2025, 1, 22 + day), f"{day + 1}.50") for day in range(6))
    for txn_date, amount in (*ROWS, *later):
        await add_txn(
            db, quarter, txn_date=txn_date, description="PAYNOW GROCER", amount=Decimal(amount), direction="OUT"
        )
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="paynow", account_type=AccountType.EXPENSE, category="TRANSFER_OUT"
    )
    await db.commit()

    assert (await client.post(f"/statements/{month.id}/approvals")).status_code == status.HTTP_200_OK
    blocked = await client.post(f"/statements/{quarter.id}/approvals")
    assert blocked.status_code == status.HTTP_400_BAD_REQUEST
    assert "3 of 9 rows" in blocked.json()["detail"] and "DBS Month" in blocked.json()["detail"]
    assert await _entry_count(db, test_user.id) == 3


async def test_a_confirmation_does_not_cover_a_statement_approved_after_it(client: AsyncClient, db, test_user):
    """#2917: the reviewer confirmed before the other account held an approved month."""
    pdf_month = await _month_on_account(db, test_user.id, "hash_2917_late_a", "DBS Late PDF", suffix="", last4="1234")
    csv_month = await _month_on_account(
        db, test_user.id, "hash_2917_late_b", "DBS Late CSV", suffix=" REF 7781", last4=None
    )
    await add_reviewed_disposition_rule(
        db, user_id=test_user.id, keyword="paynow", account_type=AccountType.EXPENSE, category="TRANSFER_OUT"
    )
    await db.commit()

    confirm_url = f"/statements/{csv_month.id}/conflict-resolutions"
    assert (await client.post(confirm_url, json={})).status_code == status.HTTP_200_OK
    assert (await client.get(f"/statements/{csv_month.id}/conflicts")).json()["resolved"] is True
    assert (await client.post(f"/statements/{pdf_month.id}/approvals")).status_code == status.HTTP_200_OK

    blocked = await client.post(f"/statements/{csv_month.id}/approvals")
    assert blocked.status_code == status.HTTP_400_BAD_REQUEST
    assert "DBS Late PDF" in blocked.json()["detail"]
    assert await _entry_count(db, test_user.id) == 3
    assert (await client.get(f"/statements/{csv_month.id}/conflicts")).json()["resolved"] is False

    assert (await client.post(confirm_url, json={})).status_code == status.HTTP_200_OK
    assert (await client.get(f"/statements/{csv_month.id}/conflicts")).json()["resolved"] is True
    assert (await client.post(f"/statements/{csv_month.id}/approvals")).status_code == status.HTTP_200_OK
    assert await _entry_count(db, test_user.id) == 6


async def test_a_new_extract_run_ends_the_confirmation(db, test_user):
    """#3178: a new extraction gives new rows, so the confirmation of the earlier rows ends."""
    from src.extraction import RunHints
    from src.extraction.extension.statement_runs import start_user_extract_run

    statement = await _month_on_account(db, test_user.id, "hash_3178_rerun", "DBS Rerun", suffix="", last4=None)
    await db.commit()
    assert (await resolve_statement_conflicts(db, statement.id, test_user.id)).stage1_conflicts_resolved_at

    async def content() -> bytes:
        return b"date,amount"

    started = await start_user_extract_run(
        db,
        statement_id=statement.id,
        user_id=test_user.id,
        file_type="csv",
        hints=RunHints(),
        model=None,
        allowed_statuses=frozenset({BankStatementStatus.PARSED}),
        strict_hints=False,
        load_content=content,
    )
    assert started.statement.stage1_conflicts_resolved_at is None


@pytest.mark.parametrize(
    ("changed", "kept"),
    [
        ({}, True),
        ({"account_id": "other"}, False),
        ({"currency": "USD"}, False),
        ({"period_end": date(2025, 3, 31)}, False),
    ],
)
async def test_an_envelope_that_changes_account_currency_or_period_ends_the_confirmation(db, test_user, changed, kept):
    """#3178: the confirmation covered one account, currency and period."""
    from types import SimpleNamespace

    from src.extraction.extension.reviewed_statement_envelope import _apply_envelope_to_statement

    statement = await _month_on_account(
        db, test_user.id, f"hash_3178_env_{len(changed)}{kept}", "DBS Env", suffix="", last4=None
    )
    statement.period_start, statement.period_end = date(2025, 1, 1), date(2025, 1, 31)
    await db.commit()
    await resolve_statement_conflicts(db, statement.id, test_user.id)
    other = await create_statement_account(db, test_user.id, "DBS Env Other")
    facts = {
        "account_id": statement.account_id,
        "currency": statement.currency,
        "period_start": statement.period_start,
        "period_end": statement.period_end,
        "opening_balance": statement.opening_balance,
        "closing_balance": statement.closing_balance,
    } | changed
    if facts["account_id"] == "other":
        facts["account_id"] = other.id

    _apply_envelope_to_statement(statement, SimpleNamespace(**facts))

    assert (statement.stage1_conflicts_resolved_at is not None) is kept
