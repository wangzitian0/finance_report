from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.ledger import AccountType, Direction
from src.ledger.extension.accounting import post_opening_balance_entry
from src.reporting import generate_balance_sheet
from src.reporting.extension._core import _aggregate_equity_translation_variance_sql
from src.reporting.extension.net_worth import get_net_worth_allocation_schedule
from src.schemas.reporting import BalanceSheetResponse, ReportLine
from tests.reporting._report_fixtures import post_pair, seed_accounts, seed_fx_rates

AS_OF = date(2026, 4, 30)
_INTERNAL_ALLOC_KEYS = {"allocation_asset_class", "allocation_liquidity_class"}


async def test_balance_sheet_multicurrency_cta_and_equity_variance(db: AsyncSession, test_user) -> None:
    uid = test_user.id
    chk_usd, inc_usd, eq_usd, chk_eur, eq_eur = await seed_accounts(
        db,
        uid,
        ("Checking USD", AccountType.ASSET, "USD"),
        ("Revenue USD", AccountType.INCOME, "USD"),
        ("Equity USD", AccountType.EQUITY, "USD"),
        ("Checking EUR", AccountType.ASSET, "EUR"),
        ("Equity EUR", AccountType.EQUITY, "EUR"),
    )
    await seed_fx_rates(
        db,
        ("USD", "SGD", "1.20", date(2025, 1, 1)),
        ("USD", "SGD", "1.30", date(2025, 1, 15)),
        ("USD", "SGD", "1.40", date(2025, 1, 31)),
        ("USD", "SGD", "1.30", date(2025, 1, 5)),
        ("USD", "HKD", "7.75", date(2025, 1, 5)),
        ("USD", "HKD", "7.80", date(2025, 1, 31)),
        ("EUR", "SGD", "1.45", date(2025, 1, 5)),
        ("EUR", "HKD", "8.50", date(2025, 1, 31)),
    )
    await post_pair(
        db,
        uid,
        date(2025, 1, 5),
        "Rev USD",
        chk_usd,
        inc_usd,
        "1000.00",
        currency="USD",
        fx_rate=Decimal("1.20"),
        commit=True,
    )
    bs = await generate_balance_sheet(db, uid, as_of_date=date(2025, 1, 31), currency="SGD")
    assert (
        bs["total_assets"],
        bs["net_income"],
        bs["unrealized_fx_gain_loss"],
        bs["cta_adjustment"],
        bs["equation_delta"],
        bs["is_balanced"],
    ) == (Decimal("1400.00"), Decimal("1300.00"), Decimal("200.00"), Decimal("-100.00"), Decimal("0.00"), True)

    await post_pair(
        db,
        uid,
        date(2025, 1, 5),
        "Cap USD",
        chk_usd,
        eq_usd,
        "500.00",
        currency="USD",
        fx_rate=Decimal("1.30"),
        commit=True,
    )
    assert await _aggregate_equity_translation_variance_sql(
        db, uid, target_currency="HKD", as_of_date=date(2025, 1, 31), base_currency="SGD"
    ) == Decimal("25.00")

    await post_pair(
        db,
        uid,
        date(2025, 1, 5),
        "Cap EUR",
        chk_eur,
        eq_eur,
        "300.00",
        currency="EUR",
        fx_rate=Decimal("1.45"),
        commit=True,
    )
    assert await _aggregate_equity_translation_variance_sql(
        db, uid, target_currency="HKD", as_of_date=date(2025, 1, 31), base_currency="SGD"
    ) == Decimal("25.00")


async def test_AC2_16_4_opening_balance_gate_warning_and_clearing(db: AsyncSession, test_user) -> None:
    cash, income = await seed_accounts(db, test_user.id, ("Bank", AccountType.ASSET), ("Salary", AccountType.INCOME))
    await post_pair(
        db,
        test_user.id,
        date(2026, 3, 1),
        "confirmed",
        cash,
        income,
        "1000.00",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        commit=True,
    )
    bs_warn = await generate_balance_sheet(db, test_user.id, as_of_date=AS_OF, currency="SGD")
    assert any(w.get("type") == "missing_opening_balance" for w in bs_warn["opening_balance_warnings"])
    assert (await get_net_worth_allocation_schedule(db, test_user.id, as_of_date=AS_OF, currency="SGD"))[
        "opening_balance_warnings"
    ]

    await post_opening_balance_entry(
        db,
        test_user.id,
        entry_date=date(2026, 1, 1),
        balances={cash.id: Decimal("500.00")},
        currency="SGD",
        base_currency="SGD",
        memo="Opening",
    )
    await db.commit()
    assert (await generate_balance_sheet(db, test_user.id, as_of_date=AS_OF, currency="SGD"))[
        "opening_balance_warnings"
    ] == []


async def test_balance_sheet_provenance_and_allocation_metadata(db: AsyncSession, test_user) -> None:
    cash, wallet, salary = await seed_accounts(
        db, test_user.id, ("Cash", AccountType.ASSET), ("Wallet", AccountType.ASSET), ("Salary", AccountType.INCOME)
    )
    await post_pair(
        db,
        test_user.id,
        date(2026, 1, 15),
        "auto",
        cash,
        salary,
        "100.00",
        source_type=JournalEntrySourceType.AUTO_PARSED,
        commit=True,
    )
    assert (await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31), currency="SGD"))[
        "provenance"
    ] == "imported"
    skipped = await generate_balance_sheet(
        db, test_user.id, as_of_date=date(2026, 12, 31), include_trust_signals=False, currency="SGD"
    )
    assert all(line["provenance"] is None for line in skipped["assets"])

    await post_pair(
        db,
        test_user.id,
        date(2026, 1, 15),
        "manual",
        wallet,
        salary,
        "50.00",
        source_type=JournalEntrySourceType.MANUAL,
        commit=True,
    )
    mixed = await generate_balance_sheet(db, test_user.id, as_of_date=date(2026, 12, 31), currency="SGD")
    assert mixed["provenance"] == "derived"
    assert all((_INTERNAL_ALLOC_KEYS | {"allocation_source_type"}) <= set(line) for line in mixed["assets"])
    resp_lines = BalanceSheetResponse.model_validate(mixed).model_dump()["assets"]
    assert resp_lines and all(
        not (_INTERNAL_ALLOC_KEYS & set(line)) and line.get("allocation_source_type") == "ledger_account"
        for line in resp_lines
    )
    for st in (
        "ledger_account",
        "manual_valuation",
        "portfolio_market_adjustment",
        "portfolio_cost_basis",
        "internal_transfer_fee",
    ):
        assert (
            ReportLine.model_validate({**mixed["assets"][0], "allocation_source_type": st}).allocation_source_type == st
        )
