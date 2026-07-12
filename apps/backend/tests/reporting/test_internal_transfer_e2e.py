"""AC4.14.9 / AC4.14.10 — internal transfer net-worth neutrality, end to end (#1123 AC3).

These are the *live-wiring* proofs the unit primitives in ``test_fx_transfer.py``
could not give: a recorded ``fx_conversions`` row whose two legs are booked into
the ledger (as income / expense accounts — exactly the double-count #1123 warns
about) must be excluded from the reporting income/expense aggregation, so the
generated income statement and the cumulative balance-sheet net income treat the
internal transfer as net-zero except for the fee.

The scenario flows through the *real* ``generate_income_statement`` /
``generate_balance_sheet`` services against a seeded DB session, asserting the
actual numbers — not a mocked primitive.
"""

from datetime import date
from decimal import Decimal

from common.testing.ac_proof import ac_proof
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import Account, AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from src.pricing import FxConversion
from src.pricing.orm.market_data import FxRate
from src.reporting import generate_balance_sheet, generate_income_statement

# A representative cross-currency internal transfer: 1360.00 SGD leaves a SGD
# bank account, 1000.00 USD arrives in a USD bank account, at 1.36 SGD/USD, with a
# 2.50 SGD fee. Implied rate 1360/1000 = 1.36 == market rate -> a genuine pair.
_OUT_SGD = Decimal("1360.00")
_IN_USD = Decimal("1000.00")
_RATE_SGD_PER_USD = Decimal("1.360000")
_FEE_SGD = Decimal("2.50")
_SALARY_SGD = Decimal("5000.00")

_REPORT_DATE = date(2025, 6, 30)
_PERIOD_START = date(2025, 6, 1)
_TXN_DATE = date(2025, 6, 15)


async def _account(db, user_id, *, name, account_type, currency="SGD") -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency)
    db.add(account)
    await db.flush()
    return account


async def _post_entry(
    db,
    user_id,
    *,
    debit_account,
    credit_account,
    amount,
    currency,
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=_TXN_DATE,
        memo="seed",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    # Non-base-currency (non-SGD) lines require a positive fx_rate to the base
    # currency, enforced by the ledger DB trigger. SGD lines stay None.
    line_fx_rate = None if currency.upper() == "SGD" else _RATE_SGD_PER_USD
    db.add_all(
        [
            JournalLine(
                journal_entry_id=entry.id,
                account_id=debit_account.id,
                direction=Direction.DEBIT,
                amount=amount,
                currency=currency,
                fx_rate=line_fx_rate,
            ),
            JournalLine(
                journal_entry_id=entry.id,
                account_id=credit_account.id,
                direction=Direction.CREDIT,
                amount=amount,
                currency=currency,
                fx_rate=line_fx_rate,
            ),
        ]
    )
    await db.flush()
    return entry


async def _seed_internal_transfer_scenario(db: AsyncSession, user_id) -> None:
    """Seed a real internal transfer that is naively double-booked as income+expense.

    The "naive" booking is exactly the bug #1123 AC3 fixes: the transfer-in lands
    in an INCOME account and the transfer-out in an EXPENSE account. We then record
    the ``fx_conversions`` link anchoring both journal entries, which the reporting
    layer uses to net them back out. A genuine 5000 SGD salary is seeded alongside
    so the exclusion is observable in the totals.
    """
    # FX rate USD -> SGD so income-statement / balance-sheet conversion can run.
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=_RATE_SGD_PER_USD,
            rate_date=_TXN_DATE,
            source="test",
        )
    )

    sgd_bank = await _account(db, user_id, name="SGD Bank", account_type=AccountType.ASSET, currency="SGD")
    usd_bank = await _account(db, user_id, name="USD Bank", account_type=AccountType.ASSET, currency="USD")
    salary_income = await _account(db, user_id, name="Salary", account_type=AccountType.INCOME, currency="SGD")
    transfer_income = await _account(
        db, user_id, name="Misclassified Transfer In", account_type=AccountType.INCOME, currency="USD"
    )
    transfer_expense = await _account(
        db, user_id, name="Misclassified Transfer Out", account_type=AccountType.EXPENSE, currency="SGD"
    )

    # Real income: 5000 SGD salary (DEBIT asset, CREDIT income).
    await _post_entry(
        db,
        user_id,
        debit_account=sgd_bank,
        credit_account=salary_income,
        amount=_SALARY_SGD,
        currency="SGD",
    )

    # Naive transfer-in booking: 1000 USD arrives, mis-booked as INCOME.
    in_entry = await _post_entry(
        db,
        user_id,
        debit_account=usd_bank,
        credit_account=transfer_income,
        amount=_IN_USD,
        currency="USD",
    )
    # Naive transfer-out booking: 1360 SGD leaves, mis-booked as EXPENSE.
    out_entry = await _post_entry(
        db,
        user_id,
        debit_account=transfer_expense,
        credit_account=sgd_bank,
        amount=_OUT_SGD,
        currency="SGD",
    )

    # Record the linking fx_conversions row anchoring BOTH legs. This is the signal
    # the reporting layer re-validates and uses to net the legs back out.
    db.add(
        FxConversion(
            user_id=user_id,
            from_account_id=sgd_bank.id,
            to_account_id=usd_bank.id,
            amount_from=_OUT_SGD,
            currency_from="SGD",
            amount_to=_IN_USD,
            currency_to="USD",
            rate=_RATE_SGD_PER_USD,
            fee=_FEE_SGD,
            fee_currency="SGD",
            conversion_date=_TXN_DATE,
            from_journal_entry_id=out_entry.id,
            to_journal_entry_id=in_entry.id,
        )
    )
    await db.commit()


@ac_proof(
    "internal-transfer-income-statement-e2e",
    ac_ids=["AC-reconciliation.fx-transfer.9"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
async def test_AC3_internal_transfer_excluded_from_income_statement_e2e(db: AsyncSession, test_user, ac_evidence):
    """AC-reconciliation.fx-transfer.9: AC4.14.9: the income statement excludes a recorded internal transfer's legs.

    Without the wiring, total_income would be inflated by the 1000 USD (=1360 SGD)
    transfer-in leg and total_expenses by the 1360 SGD transfer-out leg. With it,
    income reflects only the 5000 SGD salary and expenses reflect only the 2.50 SGD
    fee, so net income is 5000 - 2.50 = 4997.50.
    """
    await _seed_internal_transfer_scenario(db, test_user.id)

    report = await generate_income_statement(
        db,
        test_user.id,
        start_date=_PERIOD_START,
        end_date=_REPORT_DATE,
        currency="SGD",
    )

    # Income excludes the mis-booked 1360 SGD-equivalent transfer-in leg.
    assert report["total_income"] == _SALARY_SGD
    # Expenses are JUST the fee — the 1360 SGD transfer-out leg is netted out.
    assert report["total_expenses"] == _FEE_SGD
    # Net income reflects salary minus the fee only.
    assert report["net_income"] == Decimal("4997.50")

    # Coherence (#1162 CR2): the fee is a real expense LINE, not an out-of-band bump,
    # so the expense lines sum exactly to total_expenses and the fee is drill-downable.
    expense_lines = report["expenses"]
    expense_line_sum = sum((Decimal(str(line["amount"])) for line in expense_lines), Decimal("0"))
    assert expense_line_sum == report["total_expenses"]
    fee_lines = [line for line in expense_lines if Decimal(str(line["amount"])) == _FEE_SGD]
    assert len(fee_lines) == 1, "internal-transfer fee must appear as a single expense line"
    assert fee_lines[0]["account_id"] is not None
    # The fee also lands in a monthly trend expense bucket (charts must see it).
    assert sum((Decimal(str(t["total_expenses"])) for t in report["trends"]), Decimal("0")) == _FEE_SGD

    ac_evidence(
        ac_id="AC-reconciliation.fx-transfer.9",
        score=1.0,
        metric="income_statement_excludes_internal_transfer_legs_fee_only",
        provenance="deterministic",
        comment="Live-wired internal-transfer exclusion proven end to end via generate_income_statement (#1123 AC3).",
    )


@ac_proof(
    "internal-transfer-balance-sheet-net-income-e2e",
    ac_ids=["AC-reconciliation.fx-transfer.10"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
async def test_AC3_internal_transfer_net_income_fee_only_e2e(db: AsyncSession, test_user, ac_evidence):
    """AC-reconciliation.fx-transfer.10: AC4.14.10: cumulative balance-sheet net income excludes the transfer, fee only.

    The balance sheet's cumulative net income (Income - Expenses up to as_of_date)
    must net the internal transfer's legs out and reflect only the fee, so the
    figure is 5000 - 2.50 = 4997.50 — the same net-worth contribution as the income
    statement, confirming a single coherent wiring point.
    """
    await _seed_internal_transfer_scenario(db, test_user.id)

    report = await generate_balance_sheet(
        db,
        test_user.id,
        as_of_date=_REPORT_DATE,
        currency="SGD",
        include_trust_signals=False,
    )

    # Net income carries only the real salary minus the transfer fee.
    assert report["net_income"] == Decimal("4997.50")

    ac_evidence(
        ac_id="AC-reconciliation.fx-transfer.10",
        score=1.0,
        metric="balance_sheet_net_income_excludes_internal_transfer_fee_only",
        provenance="deterministic",
        comment="Live-wired internal-transfer exclusion proven end to end via generate_balance_sheet (#1123 AC3).",
    )
