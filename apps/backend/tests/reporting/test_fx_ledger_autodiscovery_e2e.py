"""AC4.14.13 / AC4.14.14 — FX/transfer ledger auto-discovery, end to end (#1123 AC2/AC4).

The live-consumption proofs that close the last gap of #1123: a cross-currency
internal transfer recorded ONLY as raw journal lines (NO pre-seeded
``fx_conversions`` row) must still be netted out of net income end to end, because
``_internal_transfer_adjustment`` now auto-discovers the leg pair from the ledger.

- AC4.14.13: a single SGD→USD internal transfer is auto-discovered and excluded
  from the income statement, so net worth is unchanged except for any real fee.
- AC4.14.14: a same-day SGD→USD→SGD round-trip nets ~zero realized P&L through the
  real income statement — the two conversions are discovered and netted, leaving no
  conversion-event gain/loss (the rate move belongs to revaluation, not here).

Everything flows through the *real* ``generate_income_statement`` /
``generate_balance_sheet`` against a seeded DB session, asserting actual numbers.
"""

from datetime import date
from decimal import Decimal

from common.testing.ac_proof import ac_proof
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.account import Account, AccountType
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.pricing import FxConversion
from src.pricing.orm.market_data import FxRate
from src.services.fx import clear_fx_cache
from src.services.reporting import generate_balance_sheet, generate_income_statement

_OUT_SGD = Decimal("1360.00")
_IN_USD = Decimal("1000.00")
_RATE_SGD_PER_USD = Decimal("1.360000")
_SALARY_SGD = Decimal("5000.00")

_REPORT_DATE = date(2025, 6, 30)
_PERIOD_START = date(2025, 6, 1)
_TXN_DATE = date(2025, 6, 15)


async def _account(db, user_id, *, name, account_type, currency="SGD") -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency=currency)
    db.add(account)
    await db.flush()
    return account


async def _post_entry(db, user_id, *, debit_account, credit_account, amount, currency) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=_TXN_DATE,
        memo="seed",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
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


async def _seed_fx_rate(db) -> None:
    clear_fx_cache()
    db.add(
        FxRate(
            base_currency="USD",
            quote_currency="SGD",
            rate=_RATE_SGD_PER_USD,
            rate_date=_TXN_DATE,
            source="test",
        )
    )
    db.add(
        FxRate(
            base_currency="SGD",
            quote_currency="USD",
            rate=(Decimal("1") / _RATE_SGD_PER_USD).quantize(Decimal("0.000001")),
            rate_date=_TXN_DATE,
            source="test",
        )
    )


async def _seed_raw_ledger_transfer(db: AsyncSession, user_id) -> None:
    """Seed a cross-currency internal transfer as RAW journal lines ONLY.

    No ``fx_conversions`` row is recorded — the reporting layer must auto-discover
    the pair from the asset-account lines. The transfer is naively double-booked
    (transfer-in to an INCOME account, transfer-out to an EXPENSE account), exactly
    the #1123 double-count, plus a genuine 5000 SGD salary so the exclusion shows up.
    """
    await _seed_fx_rate(db)

    sgd_bank = await _account(db, user_id, name="SGD Bank", account_type=AccountType.ASSET, currency="SGD")
    usd_bank = await _account(db, user_id, name="USD Bank", account_type=AccountType.ASSET, currency="USD")
    salary_income = await _account(db, user_id, name="Salary", account_type=AccountType.INCOME, currency="SGD")
    transfer_income = await _account(
        db, user_id, name="Misclassified Transfer In", account_type=AccountType.INCOME, currency="USD"
    )
    transfer_expense = await _account(
        db, user_id, name="Misclassified Transfer Out", account_type=AccountType.EXPENSE, currency="SGD"
    )

    await _post_entry(
        db,
        user_id,
        debit_account=sgd_bank,
        credit_account=salary_income,
        amount=_SALARY_SGD,
        currency="SGD",
    )
    # Transfer-in: 1000 USD arrives in USD asset (DEBIT asset = IN), mis-booked income.
    await _post_entry(
        db,
        user_id,
        debit_account=usd_bank,
        credit_account=transfer_income,
        amount=_IN_USD,
        currency="USD",
    )
    # Transfer-out: 1360 SGD leaves SGD asset (CREDIT asset = OUT), mis-booked expense.
    await _post_entry(
        db,
        user_id,
        debit_account=transfer_expense,
        credit_account=sgd_bank,
        amount=_OUT_SGD,
        currency="SGD",
    )
    await db.commit()


@ac_proof(
    "fx-ledger-autodiscovery-income-statement-e2e",
    ac_ids=["AC-reconciliation.fx-transfer.13"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
async def test_AC2_raw_ledger_internal_transfer_autodiscovered_e2e(db: AsyncSession, test_user, ac_evidence):
    """AC-reconciliation.fx-transfer.13: AC4.14.13: a raw-ledger transfer (no fx_conversions row) is netted out.

    Without auto-discovery, total_income would be inflated by the 1000 USD
    (=1360 SGD) transfer-in leg and total_expenses by the 1360 SGD transfer-out leg.
    With it, income reflects only the 5000 SGD salary and expenses are 0 (no fee on
    this raw transfer), so net income is exactly 5000.00.
    """
    await _seed_raw_ledger_transfer(db, test_user.id)

    # Guard: there is genuinely NO recorded conversion — discovery is doing the work.
    recorded = (await db.execute(select(FxConversion).where(FxConversion.user_id == test_user.id))).scalars().all()
    assert recorded == [], "scenario must rely on auto-discovery, not a recorded fx_conversions row"

    report = await generate_income_statement(
        db,
        test_user.id,
        start_date=_PERIOD_START,
        end_date=_REPORT_DATE,
        currency="SGD",
    )

    assert report["total_income"] == _SALARY_SGD
    assert report["total_expenses"] == Decimal("0.00")
    assert report["net_income"] == _SALARY_SGD

    # Same single wiring point: the cumulative balance-sheet net income also nets the
    # auto-discovered transfer out, so net worth is unchanged by it (salary only).
    balance_sheet = await generate_balance_sheet(
        db, test_user.id, as_of_date=_REPORT_DATE, currency="SGD", include_trust_signals=False
    )
    assert balance_sheet["net_income"] == _SALARY_SGD

    ac_evidence(
        ac_id="AC-reconciliation.fx-transfer.13",
        score=1.0,
        metric="raw_ledger_transfer_autodiscovered_and_excluded_fee_only",
        provenance="deterministic",
        comment="Raw-ledger cross-currency transfer auto-discovered + excluded via generate_income_statement (#1123 AC2 live).",
    )


@ac_proof(
    "fx-ledger-autodiscovery-roundtrip-pnl-e2e",
    ac_ids=["AC-reconciliation.fx-transfer.14"],
    scope="behavioral",
    ci_tier="pr_ci",
    trust_mode="deterministic_pr",
    source_classes=["manual_record"],
    issue="#1123",
)
async def test_AC4_same_day_round_trip_nets_zero_pnl_through_live_report(db: AsyncSession, test_user, ac_evidence):
    """AC-reconciliation.fx-transfer.14: AC4.14.14: a same-day SGD→USD→SGD round-trip nets ~zero realized P&L live.

    Two conversions on the same day at the same rate: 1360 SGD → 1000 USD, then
    1000 USD → 1360 SGD. Both are mis-booked as income/expense. Auto-discovery
    pairs and nets BOTH, so the income statement shows zero net income from the
    round-trip — the conversion event produces no realized gain/loss.
    """
    await _seed_fx_rate(db)

    sgd_bank = await _account(db, test_user.id, name="SGD Bank", account_type=AccountType.ASSET, currency="SGD")
    usd_bank = await _account(db, test_user.id, name="USD Bank", account_type=AccountType.ASSET, currency="USD")
    transfer_income_usd = await _account(
        db, test_user.id, name="Transfer In USD", account_type=AccountType.INCOME, currency="USD"
    )
    transfer_expense_sgd = await _account(
        db, test_user.id, name="Transfer Out SGD", account_type=AccountType.EXPENSE, currency="SGD"
    )
    transfer_income_sgd = await _account(
        db, test_user.id, name="Transfer In SGD", account_type=AccountType.INCOME, currency="SGD"
    )
    transfer_expense_usd = await _account(
        db, test_user.id, name="Transfer Out USD", account_type=AccountType.EXPENSE, currency="USD"
    )

    # Leg 1: 1360 SGD out of SGD asset, 1000 USD into USD asset.
    await _post_entry(
        db,
        test_user.id,
        debit_account=transfer_expense_sgd,
        credit_account=sgd_bank,
        amount=_OUT_SGD,
        currency="SGD",
    )
    await _post_entry(
        db,
        test_user.id,
        debit_account=usd_bank,
        credit_account=transfer_income_usd,
        amount=_IN_USD,
        currency="USD",
    )
    # Leg 2 (return): 1000 USD out of USD asset, 1360 SGD into SGD asset.
    await _post_entry(
        db,
        test_user.id,
        debit_account=transfer_expense_usd,
        credit_account=usd_bank,
        amount=_IN_USD,
        currency="USD",
    )
    await _post_entry(
        db,
        test_user.id,
        debit_account=sgd_bank,
        credit_account=transfer_income_sgd,
        amount=_OUT_SGD,
        currency="SGD",
    )
    await db.commit()

    report = await generate_income_statement(
        db,
        test_user.id,
        start_date=_PERIOD_START,
        end_date=_REPORT_DATE,
        currency="SGD",
    )

    # Both conversions are netted out: the round-trip yields zero realized P&L.
    assert report["total_income"] == Decimal("0.00")
    assert report["total_expenses"] == Decimal("0.00")
    assert report["net_income"] == Decimal("0.00")

    ac_evidence(
        ac_id="AC-reconciliation.fx-transfer.14",
        score=1.0,
        metric="same_day_round_trip_nets_zero_realized_pnl_through_live_report",
        provenance="deterministic",
        comment="Same-day SGD->USD->SGD round-trip nets zero realized P&L via generate_income_statement (#1123 AC4 live).",
    )
