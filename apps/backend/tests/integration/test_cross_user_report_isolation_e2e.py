"""Cross-user report-number isolation (EPIC-008 AC8.16, #1055 / #990 / #991).

#990 flagged that a report could aggregate a *wrong* row into a correct sum, and
named cross-user leakage as one face of it. That assertion was impossible to make
while the test schema dropped the `users` FK; #991 restored it. This test makes the
assertion at the report-NUMBER level: with posted entries for two real users, user
A's balance sheet / income statement / net-worth reflect ONLY A's facts — user B's
accounts never appear and never inflate a total.

The existing AC5.5.4 `test_user_isolation` only checks `/reports/trend?account_id=`
returns 400 for another user's account; it does not assert that report *totals*
exclude another user's posted entries. This closes that gap.
"""

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.identity import User
from src.models.account import Account, AccountType
from src.models.journal import JournalEntrySourceType
from src.models.layer3 import ManualValuationComponentType
from src.services.accounting import create_journal_entry, post_journal_entry
from src.services.assets import AssetService
from src.services.reporting import generate_balance_sheet, generate_income_statement
from tests.factories import UserFactory


async def _account(db: AsyncSession, user_id: UUID, *, name: str, account_type: AccountType) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency="SGD")
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def _post(db: AsyncSession, user_id: UUID, *, debit: Account, credit: Account, amount: Decimal) -> None:
    entry = await create_journal_entry(
        db=db,
        user_id=user_id,
        entry_date=date(2026, 3, 15),
        memo="iso",
        lines_data=[
            {"account_id": debit.id, "direction": "DEBIT", "amount": amount, "currency": "SGD"},
            {"account_id": credit.id, "direction": "CREDIT", "amount": amount, "currency": "SGD"},
        ],
        source_type=JournalEntrySourceType.MANUAL,
    )
    await post_journal_entry(db, entry.id, user_id)


async def test_AC8_16_2_reports_exclude_other_users_entries(db: AsyncSession, test_user: User, ac_evidence) -> None:
    """AC8.16.2: user A's report totals reflect only A's facts; B's data never leaks in."""
    user_a = test_user.id
    user_b = (await UserFactory.create_async(db)).id

    # User A: open with 1000 of equity, then 500 of salary income.
    a_bank = await _account(db, user_a, name="A Bank", account_type=AccountType.ASSET)
    a_equity = await _account(db, user_a, name="A Equity", account_type=AccountType.EQUITY)
    a_salary = await _account(db, user_a, name="A Salary", account_type=AccountType.INCOME)
    await _post(db, user_a, debit=a_bank, credit=a_equity, amount=Decimal("1000.00"))
    await _post(db, user_a, debit=a_bank, credit=a_salary, amount=Decimal("500.00"))

    # User B: deliberately larger, distinct amounts — a leak would be unmistakable.
    b_bank = await _account(db, user_b, name="B Bank", account_type=AccountType.ASSET)
    b_equity = await _account(db, user_b, name="B Equity", account_type=AccountType.EQUITY)
    b_salary = await _account(db, user_b, name="B Salary", account_type=AccountType.INCOME)
    await _post(db, user_b, debit=b_bank, credit=b_equity, amount=Decimal("9999.00"))
    await _post(db, user_b, debit=b_bank, credit=b_salary, amount=Decimal("7777.00"))
    await db.commit()

    period_start, period_end = date(2026, 1, 1), date(2026, 12, 31)

    # --- User A's reports see only A ---
    a_bs = await generate_balance_sheet(db, user_a, as_of_date=period_end, currency="SGD")
    a_is = await generate_income_statement(db, user_a, start_date=period_start, end_date=period_end, currency="SGD")

    assert a_bs["total_assets"] == Decimal("1500.00")  # not 1500 + 17776
    assert a_bs["is_balanced"] is True
    assert a_is["total_income"] == Decimal("500.00")  # not 500 + 7777
    assert a_is["net_income"] == Decimal("500.00")

    # B's accounts must not appear in any of A's report lines.
    a_line_names = {line["name"] for section in ("assets", "liabilities", "equity") for line in a_bs[section]}
    assert not any(name.startswith("B ") for name in a_line_names), a_line_names

    # --- Symmetry: B genuinely has data (so the test isn't vacuously passing) ---
    b_bs = await generate_balance_sheet(db, user_b, as_of_date=period_end, currency="SGD")
    assert b_bs["total_assets"] == Decimal("17776.00")  # B's own 9999 + 7777, not A's

    # --- Net-worth isolation: a manual valuation for each user must not cross into the
    # other's net worth. Added after the ledger reports above so it does not perturb them. ---
    service = AssetService()
    await service.create_valuation_snapshot(
        db,
        user_id=user_a,
        value=Decimal("200000.00"),
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=period_end,
        currency="SGD",
        source="A appraisal",
    )
    await service.create_valuation_snapshot(
        db,
        user_id=user_b,
        value=Decimal("800000.00"),
        component_type=ManualValuationComponentType.PROPERTY_VALUE,
        as_of_date=period_end,
        currency="SGD",
        source="B appraisal",
    )
    await db.commit()

    a_nw = await service.get_latest_valuation_components(db, user_a, as_of_date=period_end)
    b_nw = await service.get_latest_valuation_components(db, user_b, as_of_date=period_end)
    assert a_nw.total_assets == Decimal("200000.00")  # A's appraisal only, not 200000 + 800000
    assert b_nw.total_assets == Decimal("800000.00")  # B's own, not A's

    # Behavioral evidence (#990 cross-user input selection): A's assets total is its
    # own 1500.00, never 1500 + B's 17776; A's net-worth valuation is 200000.00, never
    # 200000 + B's 800000. A cross-user leak would move both off these golden numbers.
    ac_evidence(
        ac_id="AC8.16.2",
        score=1.0,
        metric="cross_user_excluded_own_totals_match",
        comment="A assets 1500.00 (not 1500+17776) and A net-worth 200000.00 (not +800000); B never leaks in",
        provenance="deterministic",
    )
