from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.ledger import AccountType
from src.pricing import FxConversion
from src.reporting import generate_balance_sheet, generate_income_statement
from tests.reporting._report_fixtures import post_pair, seed_accounts, seed_fx_rates

_OUT_SGD = Decimal("1360.00")
_IN_USD = Decimal("1000.00")
_RATE = Decimal("1.360000")
_SALARY_SGD = Decimal("5000.00")
_FEE_SGD = Decimal("2.50")
_REPORT_DATE = date(2025, 6, 30)
_PERIOD_START = date(2025, 6, 1)
_TXN_DATE = date(2025, 6, 15)


async def _seed_transfer(db: AsyncSession, user_id, *, with_conversion_row: bool) -> None:
    await seed_fx_rates(
        db,
        ("USD", "SGD", _RATE, _TXN_DATE),
        ("SGD", "USD", (Decimal("1") / _RATE).quantize(Decimal("0.000001")), _TXN_DATE),
        commit=False,
    )
    sgd_bank, usd_bank, salary, x_in, x_out = await seed_accounts(
        db,
        user_id,
        ("SGD Bank", AccountType.ASSET, "SGD"),
        ("USD Bank", AccountType.ASSET, "USD"),
        ("Salary", AccountType.INCOME, "SGD"),
        ("Misclassified Transfer In", AccountType.INCOME, "USD"),
        ("Misclassified Transfer Out", AccountType.EXPENSE, "SGD"),
    )
    await post_pair(db, user_id, _TXN_DATE, "sal", sgd_bank, salary, _SALARY_SGD, currency="SGD")
    in_e = await post_pair(db, user_id, _TXN_DATE, "in", usd_bank, x_in, _IN_USD, currency="USD", fx_rate=_RATE)
    out_e = await post_pair(db, user_id, _TXN_DATE, "out", x_out, sgd_bank, _OUT_SGD, currency="SGD")
    if with_conversion_row:
        db.add(
            FxConversion(
                user_id=user_id,
                from_account_id=sgd_bank.id,
                to_account_id=usd_bank.id,
                amount_from=_OUT_SGD,
                currency_from="SGD",
                amount_to=_IN_USD,
                currency_to="USD",
                rate=_RATE,
                fee=_FEE_SGD,
                fee_currency="SGD",
                conversion_date=_TXN_DATE,
                from_journal_entry_id=out_e.id,
                to_journal_entry_id=in_e.id,
            )
        )
    await db.commit()


async def test_AC2_raw_ledger_internal_transfer_autodiscovered_e2e(db: AsyncSession, test_user) -> None:
    await _seed_transfer(db, test_user.id, with_conversion_row=False)
    assert (await db.execute(select(FxConversion).where(FxConversion.user_id == test_user.id))).scalars().all() == []
    rep = await generate_income_statement(
        db, test_user.id, start_date=_PERIOD_START, end_date=_REPORT_DATE, currency="SGD"
    )
    assert (rep["total_income"], rep["total_expenses"], rep["net_income"]) == (
        _SALARY_SGD,
        Decimal("0.00"),
        _SALARY_SGD,
    )
    assert (
        await generate_balance_sheet(
            db, test_user.id, as_of_date=_REPORT_DATE, currency="SGD", include_trust_signals=False
        )
    )["net_income"] == _SALARY_SGD


async def test_AC4_same_day_round_trip_nets_zero_pnl_through_live_report(db: AsyncSession, test_user) -> None:
    await seed_fx_rates(
        db,
        ("USD", "SGD", _RATE, _TXN_DATE),
        ("SGD", "USD", (Decimal("1") / _RATE).quantize(Decimal("0.000001")), _TXN_DATE),
        commit=False,
    )
    sgd_b, usd_b, in_u, out_s, in_s, out_u = await seed_accounts(
        db,
        test_user.id,
        ("SGD Bank", AccountType.ASSET, "SGD"),
        ("USD Bank", AccountType.ASSET, "USD"),
        ("Transfer In USD", AccountType.INCOME, "USD"),
        ("Transfer Out SGD", AccountType.EXPENSE, "SGD"),
        ("Transfer In SGD", AccountType.INCOME, "SGD"),
        ("Transfer Out USD", AccountType.EXPENSE, "USD"),
    )
    await post_pair(db, test_user.id, _TXN_DATE, "1", out_s, sgd_b, _OUT_SGD, currency="SGD")
    await post_pair(db, test_user.id, _TXN_DATE, "2", usd_b, in_u, _IN_USD, currency="USD", fx_rate=_RATE)
    await post_pair(db, test_user.id, _TXN_DATE, "3", out_u, usd_b, _IN_USD, currency="USD", fx_rate=_RATE)
    await post_pair(db, test_user.id, _TXN_DATE, "4", sgd_b, in_s, _OUT_SGD, currency="SGD", commit=True)
    rep = await generate_income_statement(
        db, test_user.id, start_date=_PERIOD_START, end_date=_REPORT_DATE, currency="SGD"
    )
    assert (rep["total_income"], rep["total_expenses"], rep["net_income"]) == (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    )


async def test_AC3_internal_transfer_excluded_and_fee_only_e2e(db: AsyncSession, test_user) -> None:
    await _seed_transfer(db, test_user.id, with_conversion_row=True)
    rep = await generate_income_statement(
        db, test_user.id, start_date=_PERIOD_START, end_date=_REPORT_DATE, currency="SGD"
    )
    assert (rep["total_income"], rep["total_expenses"], rep["net_income"]) == (
        _SALARY_SGD,
        _FEE_SGD,
        Decimal("4997.50"),
    )
    assert sum((Decimal(str(item["amount"])) for item in rep["expenses"]), Decimal("0")) == _FEE_SGD
    fees = [item for item in rep["expenses"] if Decimal(str(item["amount"])) == _FEE_SGD]
    assert len(fees) == 1 and fees[0]["account_id"] is not None
    assert sum((Decimal(str(t["total_expenses"])) for t in rep["trends"]), Decimal("0")) == _FEE_SGD
    assert (
        await generate_balance_sheet(
            db, test_user.id, as_of_date=_REPORT_DATE, currency="SGD", include_trust_signals=False
        )
    )["net_income"] == Decimal("4997.50")
