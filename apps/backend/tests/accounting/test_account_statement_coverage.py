from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType

pytestmark = pytest.mark.asyncio


async def _add_stmt(
    db: AsyncSession,
    user_id,
    account: Account,
    file_hash: str,
    start: date,
    end: date,
    opening: str | None,
    closing: str | None,
    *,
    status: BankStatementStatus = BankStatementStatus.APPROVED,
    institution: str = "DBS",
    manual_opening: str | None = None,
) -> StatementSummary:
    stmt = StatementSummary(
        user_id=user_id,
        account_id=account.id,
        file_hash=file_hash,
        institution=institution,
        currency="SGD",
        period_start=start,
        period_end=end,
        opening_balance=Decimal(opening) if opening is not None else None,
        closing_balance=Decimal(closing) if closing is not None else None,
        manual_opening_balance=Decimal(manual_opening) if manual_opening is not None else None,
        status=status,
        balance_validated=status == BankStatementStatus.APPROVED,
    )
    db.add(stmt)
    await db.flush()
    await db.refresh(stmt)
    return stmt


async def _seed_and_fetch(
    client: AsyncClient, db: AsyncSession, user_id, name: str, as_of: str, specs: list[tuple]
) -> tuple[Account, dict]:
    account = Account(user_id=user_id, name=name, type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    stmts = [await _add_stmt(db, user_id, account, *args, **kw) for *args, kw in specs]
    await db.commit()
    resp = await client.get(f"/statements/coverage?as_of={as_of}&stale_after_days=45")
    assert resp.status_code == 200
    item = next(i for i in resp.json()["items"] if i["account_id"] == str(account.id))
    return account, {"item": item, "stmts": stmts}


@pytest.mark.parametrize(
    ("name", "as_of", "specs", "expected"),
    [
        (
            "DBS Multiplier",
            "2025-03-10",
            [
                ("ac371-jan", date(2025, 1, 1), date(2025, 1, 31), "1000.00", "1200.00", {}),
                ("ac371-feb", date(2025, 2, 1), date(2025, 2, 28), "1200.00", "1250.00", {}),
            ],
            ("2025-02-28", "1250.00", False, True, "monthly", False),
        ),
        ("Unconfirmed Cash", "2025-03-10", [], (None, None, True, False, "monthly", False)),
        (
            "Pending Balance Boundary",
            "2025-03-01",
            [
                (
                    "ac372-m-jan",
                    date(2025, 1, 1),
                    date(2025, 1, 31),
                    "1000.00",
                    None,
                    {"status": BankStatementStatus.PARSED},
                ),
                ("ac372-m-feb", date(2025, 2, 1), date(2025, 2, 28), "1100.00", "1200.00", {}),
            ],
            ("2025-02-28", "1200.00", False, True, "monthly", False),
        ),
        (
            "Brokerage Cash",
            "2025-03-16",
            [
                ("ac374-jan", date(2025, 1, 1), date(2025, 1, 31), "1000.00", "1100.00", {"institution": "Futu"}),
                ("ac374-feb", date(2025, 2, 1), date(2025, 2, 28), "1100.00", "1200.00", {"institution": "Futu"}),
                ("ac374-mar", date(2025, 3, 15), date(2025, 3, 15), "1200.00", "1300.00", {"institution": "Futu"}),
            ],
            ("2025-03-15", "1300.00", False, True, "daily_snapshot", True),
        ),
        (
            "Continuity Checking",
            "2025-04-01",
            [
                ("cont-jan", date(2025, 1, 1), date(2025, 1, 31), "1000.00", "1500.00", {}),
                ("cont-feb", date(2025, 1, 31), date(2025, 2, 28), "1500.00", "2000.00", {}),
                ("cont-mar", date(2025, 3, 3), date(2025, 3, 31), "2000.00", "2500.00", {}),
            ],
            ("2025-03-31", "2500.00", False, True, "monthly", False),
        ),
    ],
)
async def test_account_coverage_happy_and_empty_states(
    client: AsyncClient, db: AsyncSession, test_user, name: str, as_of: str, specs: list[tuple], expected: tuple
) -> None:
    _, data = await _seed_and_fetch(client, db, test_user.id, name, as_of, specs)
    item = data["item"]
    bal = None if item["latest_confirmed_balance"] is None else Decimal(str(item["latest_confirmed_balance"]))
    exp_date, exp_bal, exp_stale, exp_complete, exp_cadence, exp_override = expected
    assert (
        item["latest_source_date"],
        bal,
        item["is_stale"],
        item["coverage_complete"],
        item["cadence"],
        item["has_daily_snapshot_override"],
        item["issues"],
    ) == (
        exp_date,
        None if exp_bal is None else Decimal(exp_bal),
        exp_stale,
        exp_complete,
        exp_cadence,
        exp_override,
        [],
    )


async def test_account_coverage_defects_and_empty_user(client: AsyncClient, db: AsyncSession, test_user) -> None:
    resp = await client.get("/statements/coverage?as_of=2025-03-10&stale_after_days=45")
    assert resp.status_code == 200 and resp.json() == {"items": [], "total": 0, "as_of": "2025-03-10"}

    _, mismatch = await _seed_and_fetch(
        client,
        db,
        test_user.id,
        "DBS Continuity",
        "2025-03-01",
        [
            ("ac372-jan", date(2025, 1, 1), date(2025, 1, 31), "1000.00", "1100.00", {}),
            ("ac372-feb", date(2025, 2, 1), date(2025, 2, 28), "1099.99", "1200.00", {}),
        ],
    )
    issue = mismatch["item"]["issues"][0]
    assert mismatch["item"]["coverage_complete"] is False and issue["type"] == "opening_balance_mismatch"
    assert (issue["statement_id"], issue["previous_statement_id"], Decimal(str(issue["delta"]))) == (
        str(mismatch["stmts"][1].id),
        str(mismatch["stmts"][0].id),
        Decimal("0.01"),
    )

    _, defects = await _seed_and_fetch(
        client,
        db,
        test_user.id,
        "DBS Defects",
        "2025-05-01",
        [
            ("ac373-a", date(2025, 1, 1), date(2025, 1, 31), "1000.00", "1100.00", {}),
            ("ac373-b", date(2025, 1, 1), date(2025, 1, 31), "1000.00", "1100.00", {}),
            ("ac373-ov", date(2025, 1, 15), date(2025, 2, 15), "1050.00", "1125.00", {}),
            ("ac373-ap", date(2025, 4, 1), date(2025, 4, 30), "1250.00", "1300.00", {}),
        ],
    )
    assert {"duplicate_period", "overlap", "gap"}.issubset({i["type"] for i in defects["item"]["issues"]})
    gap = next(i for i in defects["item"]["issues"] if i["type"] == "gap")
    assert (gap["period_start"], gap["period_end"], Decimal(str(gap["delta"]))) == (
        "2025-02-16",
        "2025-03-31",
        Decimal("125.00"),
    )

    acct, biz = await _seed_and_fetch(
        client,
        db,
        test_user.id,
        "Biz Gap",
        "2025-04-01",
        [
            ("gap-jan", date(2025, 1, 1), date(2025, 1, 31), "1000.00", "1500.00", {}),
            ("gap-mar", date(2025, 3, 1), date(2025, 3, 31), "0.00", "2000.00", {"manual_opening": "1500.00"}),
        ],
    )
    assert biz["item"]["coverage_complete"] is True and biz["item"]["issues"] == []
    await _add_stmt(db, test_user.id, acct, "gap-may", date(2025, 5, 1), date(2025, 5, 31), "2350.00", "2600.00")
    await db.commit()
    item2 = next(
        i
        for i in (await client.get("/statements/coverage?as_of=2025-06-01&stale_after_days=45")).json()["items"]
        if i["account_id"] == str(acct.id)
    )
    assert item2["coverage_complete"] is False and any(
        i["type"] == "gap" and Decimal(str(i["delta"])) == Decimal("350.00") for i in item2["issues"]
    )


async def test_account_coverage_excludes_non_custody_and_system_accounts(
    client: AsyncClient, db: AsyncSession, test_user
) -> None:
    """#3253: Statement coverage only reports active non-system ASSET/LIABILITY custody accounts."""
    from src.ledger import Account, AccountType

    checking = Account(user_id=test_user.id, name="Custody Checking", type=AccountType.ASSET, currency="SGD")
    card = Account(user_id=test_user.id, name="Custody Card", type=AccountType.LIABILITY, currency="SGD")
    expense = Account(user_id=test_user.id, name="Groceries Expense", type=AccountType.EXPENSE, currency="SGD")
    income = Account(user_id=test_user.id, name="Salary Income", type=AccountType.INCOME, currency="SGD")
    sys_asset = Account(
        user_id=test_user.id, name="System Suspense", type=AccountType.ASSET, currency="SGD", is_system=True
    )
    db.add_all([checking, card, expense, income, sys_asset])
    await db.commit()

    resp = await client.get("/statements/coverage?as_of=2025-06-01&stale_after_days=45")
    assert resp.status_code == 200
    names = {item["account_name"] for item in resp.json()["items"]}
    assert names == {"Custody Checking", "Custody Card"}
