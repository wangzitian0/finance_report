"""AC3.7: Account-level statement coverage and balance continuity API."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType

pytestmark = pytest.mark.asyncio


async def _create_account(
    db: AsyncSession,
    user_id,
    *,
    name: str,
    currency: str = "SGD",
) -> Account:
    account = Account(user_id=user_id, name=name, type=AccountType.ASSET, currency=currency)
    db.add(account)
    await db.flush()
    return account


async def _create_statement(
    db: AsyncSession,
    user_id,
    account: Account,
    *,
    file_hash: str,
    period_start: date,
    period_end: date,
    opening_balance: Decimal | None,
    closing_balance: Decimal | None,
    status: BankStatementStatus = BankStatementStatus.APPROVED,
    institution: str = "DBS",
    currency: str = "SGD",
) -> StatementSummary:
    statement = StatementSummary(
        user_id=user_id,
        account_id=account.id,
        file_hash=file_hash,
        institution=institution,
        currency=currency,
        period_start=period_start,
        period_end=period_end,
        opening_balance=opening_balance,
        closing_balance=closing_balance,
        status=status,
        balance_validated=status == BankStatementStatus.APPROVED,
    )
    db.add(statement)
    await db.flush()
    await db.refresh(statement)
    return statement


def _coverage_item(payload: dict, account: Account) -> dict:
    for item in payload["items"]:
        if item["account_id"] == str(account.id):
            return item
    raise AssertionError(f"missing coverage item for {account.id}")


def _decimal(value) -> Decimal:
    return Decimal(str(value))


async def test_account_coverage_reports_latest_confirmed_balance_and_stale_status(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """AC-extraction.7.1: Each account reports latest source date, balance, and stale status."""
    account = await _create_account(db, test_user.id, name="DBS Multiplier")
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac371-jan",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1200.00"),
    )
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac371-feb",
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
        opening_balance=Decimal("1200.00"),
        closing_balance=Decimal("1250.00"),
    )
    await db.commit()

    response = await client.get("/accounts/coverage?as_of=2025-03-10&stale_after_days=45")

    assert response.status_code == 200
    payload = response.json()
    item = _coverage_item(payload, account)
    assert item["latest_source_date"] == "2025-02-28"
    assert _decimal(item["latest_confirmed_balance"]) == Decimal("1250.00")
    assert item["is_stale"] is False
    assert item["coverage_complete"] is True
    assert item["issues"] == []


async def test_account_coverage_reports_empty_active_account_as_stale(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """AC-extraction.7.1: Active accounts without approved statements are stale and incomplete."""
    account = await _create_account(db, test_user.id, name="Unconfirmed Cash")
    await db.commit()

    response = await client.get("/accounts/coverage?as_of=2025-03-10&stale_after_days=45")

    assert response.status_code == 200
    item = _coverage_item(response.json(), account)
    assert item["latest_source_date"] is None
    assert item["latest_confirmed_balance"] is None
    assert item["is_stale"] is True
    assert item["coverage_complete"] is False
    assert item["issues"] == []


async def test_account_coverage_detects_adjacent_opening_balance_mismatch(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """AC-extraction.7.2: Adjacent monthly statements verify previous close equals next open."""
    account = await _create_account(db, test_user.id, name="DBS Continuity")
    previous = await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac372-jan",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1100.00"),
    )
    current = await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac372-feb",
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
        opening_balance=Decimal("1099.99"),
        closing_balance=Decimal("1200.00"),
    )
    await db.commit()

    response = await client.get("/accounts/coverage?as_of=2025-03-01&stale_after_days=45")

    assert response.status_code == 200
    item = _coverage_item(response.json(), account)
    assert item["coverage_complete"] is False
    issue = item["issues"][0]
    assert issue["type"] == "opening_balance_mismatch"
    assert issue["statement_id"] == str(current.id)
    assert issue["previous_statement_id"] == str(previous.id)
    assert _decimal(issue["expected_opening_balance"]) == Decimal("1100.00")
    assert _decimal(issue["actual_opening_balance"]) == Decimal("1099.99")
    assert _decimal(issue["delta"]) == Decimal("0.01")


async def test_account_coverage_ignores_incomplete_unapproved_boundary_statement(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """AC-extraction.7.2: Incomplete unapproved boundary statements do not create continuity issues."""
    account = await _create_account(db, test_user.id, name="Pending Balance Boundary")
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac372-missing-jan",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=None,
        status=BankStatementStatus.PARSED,
    )
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac372-missing-feb",
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
        opening_balance=Decimal("1100.00"),
        closing_balance=Decimal("1200.00"),
    )
    await db.commit()

    response = await client.get("/accounts/coverage?as_of=2025-03-01&stale_after_days=45")

    assert response.status_code == 200
    item = _coverage_item(response.json(), account)
    assert [issue["type"] for issue in item["issues"]] == []


async def test_account_coverage_reports_missing_overlapping_and_duplicate_ranges(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """AC-extraction.7.3: Missing, overlapping, and duplicate statement periods are visible."""
    account = await _create_account(db, test_user.id, name="DBS Coverage Defects")
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac373-jan-a",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1100.00"),
    )
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac373-jan-b",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1100.00"),
    )
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac373-overlap",
        period_start=date(2025, 1, 15),
        period_end=date(2025, 2, 15),
        opening_balance=Decimal("1050.00"),
        closing_balance=Decimal("1125.00"),
    )
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac373-apr",
        period_start=date(2025, 4, 1),
        period_end=date(2025, 4, 30),
        opening_balance=Decimal("1125.00"),
        closing_balance=Decimal("1300.00"),
    )
    await db.commit()

    response = await client.get("/accounts/coverage?as_of=2025-05-01&stale_after_days=45")

    assert response.status_code == 200
    item = _coverage_item(response.json(), account)
    issue_types = {issue["type"] for issue in item["issues"]}
    assert {"duplicate_period", "overlap", "gap"}.issubset(issue_types)
    gap = next(issue for issue in item["issues"] if issue["type"] == "gap")
    assert gap["period_start"] == "2025-02-16"
    assert gap["period_end"] == "2025-03-31"


async def test_account_coverage_accepts_broker_monthly_cadence_with_daily_snapshot_override(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """AC-extraction.7.4: Broker monthly cadence can use a daily snapshot as latest source."""
    account = await _create_account(db, test_user.id, name="Brokerage Cash")
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac374-jan",
        institution="Futu",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("1100.00"),
    )
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac374-feb",
        institution="Futu",
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
        opening_balance=Decimal("1100.00"),
        closing_balance=Decimal("1200.00"),
    )
    await _create_statement(
        db,
        test_user.id,
        account,
        file_hash="ac374-mar15",
        institution="Futu",
        period_start=date(2025, 3, 15),
        period_end=date(2025, 3, 15),
        opening_balance=Decimal("1200.00"),
        closing_balance=Decimal("1300.00"),
    )
    await db.commit()

    response = await client.get("/accounts/coverage?as_of=2025-03-16&stale_after_days=45")

    assert response.status_code == 200
    item = _coverage_item(response.json(), account)
    assert item["cadence"] == "daily_snapshot"
    assert item["has_daily_snapshot_override"] is True
    assert item["latest_source_date"] == "2025-03-15"
    assert _decimal(item["latest_confirmed_balance"]) == Decimal("1300.00")
    assert item["coverage_complete"] is True
    assert item["issues"] == []


async def test_account_coverage_returns_empty_list_when_user_has_no_active_accounts(client: AsyncClient) -> None:
    """AC-extraction.7.1: Users without active accounts receive an empty coverage list."""
    response = await client.get("/accounts/coverage?as_of=2025-03-10&stale_after_days=45")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "as_of": "2025-03-10"}
