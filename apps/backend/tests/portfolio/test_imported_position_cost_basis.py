"""An imported position has no cost basis until a purchase is recorded (#2920)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.layer2 import AtomicPosition
from src.ledger import Account, AccountType
from src.portfolio import (
    InvestmentAccountingService,
    PortfolioService,
    PositionService,
    TradeAccounts,
    TradeOrder,
    build_investment_performance_report_schedule,
)
from src.portfolio.orm.portfolio import InvestmentTransaction, InvestmentTransactionType, ManagedPosition
from src.reporting.extension.portfolio_market import (
    _portfolio_market_adjustment_lines_from_basis,
    _portfolio_market_basis_by_account,
)
from tests.extraction._statement_run_helpers import migration_db_url, run_alembic

JUNE = date(2026, 6, 30)
SEPTEMBER = date(2026, 9, 30)


def _snapshot(user_id: object, snapshot_date: date, market_value: str) -> AtomicPosition:
    return AtomicPosition(
        user_id=user_id,
        snapshot_date=snapshot_date,
        asset_identifier="VWRA",
        broker="Moomoo",
        quantity=Decimal("10"),
        market_value=Decimal(market_value),
        currency="SGD",
        dedup_hash=f"vwra_2920_{snapshot_date.isoformat()}",
        source_documents={},
    )


async def _import_two_snapshots(db: AsyncSession, user_id: object) -> ManagedPosition:
    for snapshot in (_snapshot(user_id, JUNE, "2000.00"), _snapshot(user_id, SEPTEMBER, "2100.00")):
        db.add(snapshot)
        await db.flush()
        await PositionService().reconcile_positions(db, user_id)
    return (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == user_id))).scalar_one()


async def test_reconcile_stores_no_cost_basis_for_a_position_without_a_purchase(db, test_user):
    position = await _import_two_snapshots(db, test_user.id)

    assert (position.quantity, position.cost_basis, position.position_metadata["latest_snapshot_date"]) == (
        Decimal("10"),
        None,
        SEPTEMBER.isoformat(),
    )


async def test_holdings_return_no_cost_and_no_profit_without_a_purchase(db, test_user):
    await _import_two_snapshots(db, test_user.id)
    service = PortfolioService()

    current = (await service.get_holdings(db, test_user.id, base_currency="SGD"))[0]
    as_of_june = (await service.get_holdings(db, test_user.id, as_of_date=JUNE, base_currency="SGD"))[0]
    summary = await service.get_portfolio_summary(db, test_user.id, base_currency="SGD")

    assert [
        (h.market_value, h.cost_basis, h.native_cost_basis, h.unrealized_pnl, h.unrealized_pnl_percent)
        for h in (current, as_of_june)
    ] == [
        (Decimal("2100.00"), None, None, None, None),
        (Decimal("2000.00"), None, None, None, None),
    ]
    assert (
        summary.total_market_value,
        summary.total_cost_basis,
        summary.total_unrealized_pnl,
        summary.total_unrealized_pnl_percent,
        summary.net_pnl,
        summary.positions_without_cost_count,
    ) == (Decimal("2100.00"), None, None, None, None, 1)


async def test_one_position_without_a_purchase_empties_the_summary_totals_of_two_positions(db, test_user):
    cash = Account(user_id=test_user.id, name="Brokerage Cash", type=AccountType.ASSET, currency="SGD")
    broker = Account(user_id=test_user.id, name="Moomoo", type=AccountType.ASSET, currency="SGD")
    db.add_all([cash, broker])
    await db.flush()
    await InvestmentAccountingService().post_buy(
        db,
        user_id=test_user.id,
        order=TradeOrder.create(
            transaction_date=date(2026, 6, 15),
            asset_identifier="ES3",
            quantity=Decimal("10"),
            unit_price=Decimal("180.00"),
            currency="SGD",
        ),
        accounts=TradeAccounts(cash=cash.id, investment=broker.id),
    )
    bought = _snapshot(test_user.id, SEPTEMBER, "2000.00")
    bought.asset_identifier, bought.dedup_hash = "ES3", "es3_2920_summary"
    db.add_all([bought, _snapshot(test_user.id, SEPTEMBER, "2100.00")])
    await db.flush()
    await PositionService().reconcile_positions(db, test_user.id)
    service = PortfolioService()

    by_asset = {h.asset_identifier: h for h in await service.get_holdings(db, test_user.id, base_currency="SGD")}
    summary = await service.get_portfolio_summary(db, test_user.id, base_currency="SGD")

    assert {asset: (h.cost_basis, h.unrealized_pnl) for asset, h in by_asset.items()} == {
        "ES3": (Decimal("1800.00"), Decimal("200.00")),
        "VWRA": (None, None),
    }
    assert (
        summary.total_market_value,
        summary.total_cost_basis,
        summary.total_unrealized_pnl,
        summary.net_pnl,
        summary.positions_without_cost_count,
    ) == (Decimal("4100.00"), None, None, None, 1)


async def test_performance_schedule_row_has_no_cost_and_no_profit_without_a_purchase(db, test_user):
    await _import_two_snapshots(db, test_user.id)

    schedule = await build_investment_performance_report_schedule(
        db, test_user.id, period_start=date(2026, 7, 1), period_end=SEPTEMBER, as_of_date=SEPTEMBER, currency="SGD"
    )
    row = schedule.holdings[0]

    assert (row.market_value, row.cost_basis, row.unrealized_pnl, schedule.unrealized_pnl) == (
        Decimal("2100.00"),
        None,
        None,
        None,
    )
    assert "No purchase is recorded for VWRA; cost basis and unrealized profit are not available." in schedule.notes


async def test_balance_sheet_basis_carries_zero_ledger_cost_without_a_purchase(db, test_user):
    position = await _import_two_snapshots(db, test_user.id)

    basis = await _portfolio_market_basis_by_account(db, test_user.id, as_of_date=SEPTEMBER, target_currency="SGD")

    assert (basis[position.account_id]["market_value"], basis[position.account_id]["cost_basis"]) == (
        Decimal("2100.00"),
        Decimal("0"),
    )


async def test_recorded_purchase_gives_the_cost_and_a_later_snapshot_keeps_it(db, test_user):
    cash = Account(user_id=test_user.id, name="Brokerage Cash", type=AccountType.ASSET, currency="SGD")
    broker = Account(user_id=test_user.id, name="Moomoo", type=AccountType.ASSET, currency="SGD")
    db.add_all([cash, broker, _snapshot(test_user.id, date(2026, 5, 31), "0.00")])
    await db.flush()
    await InvestmentAccountingService().post_buy(
        db,
        user_id=test_user.id,
        order=TradeOrder.create(
            transaction_date=date(2026, 6, 15),
            asset_identifier="VWRA",
            quantity=Decimal("10"),
            unit_price=Decimal("180.00"),
            currency="SGD",
            fees=Decimal("5.00"),
        ),
        accounts=TradeAccounts(cash=cash.id, investment=broker.id),
    )
    position = await _import_two_snapshots(db, test_user.id)
    service = PortfolioService()

    by_date = {
        as_of: (await service.get_holdings(db, test_user.id, as_of_date=as_of, base_currency="SGD"))[0]
        for as_of in (date(2026, 5, 31), JUNE, SEPTEMBER)
    }
    current = (await service.get_holdings(db, test_user.id, base_currency="SGD"))[0]

    assert position.cost_basis == Decimal("1805.00")
    assert {as_of: (h.cost_basis, h.unrealized_pnl) for as_of, h in by_date.items()} == {
        date(2026, 5, 31): (None, None),
        JUNE: (Decimal("1805.00"), Decimal("195.00")),
        SEPTEMBER: (Decimal("1805.00"), Decimal("295.00")),
    }
    assert (current.cost_basis, current.unrealized_pnl, current.unrealized_pnl_percent) == (
        Decimal("1805.00"),
        Decimal("295.00"),
        Decimal("16.34"),
    )


@pytest.mark.parametrize("method", ["FIFO", "LIFO", "AvgCost"])
async def test_cost_of_today_equals_cost_from_the_trade_rows_after_a_buy_and_a_sale(db, test_user, method):
    cash = Account(user_id=test_user.id, name="Brokerage Cash", type=AccountType.ASSET, currency="SGD")
    broker = Account(user_id=test_user.id, name="Moomoo", type=AccountType.ASSET, currency="SGD")
    pnl = Account(user_id=test_user.id, name="Realized P&L", type=AccountType.INCOME, currency="SGD")
    db.add_all([cash, broker, pnl])
    await db.flush()
    service, accounts = (
        InvestmentAccountingService(),
        TradeAccounts(cash=cash.id, investment=broker.id, realized_pnl=pnl.id),
    )
    for day, quantity, price in ((1, "6", "100.00"), (2, "4", "150.00")):
        await service.post_buy(
            db,
            user_id=test_user.id,
            order=TradeOrder.create(
                transaction_date=date(2026, 6, day),
                asset_identifier="VWRA",
                quantity=Decimal(quantity),
                unit_price=Decimal(price),
                currency="SGD",
                cost_basis_method=method,
            ),
            accounts=accounts,
        )
    sold = await service.post_sell(
        db,
        user_id=test_user.id,
        order=TradeOrder.create(
            transaction_date=date(2026, 6, 20),
            asset_identifier="VWRA",
            quantity=Decimal("5"),
            unit_price=Decimal("200.00"),
            currency="SGD",
            cost_basis_method=method,
        ),
        accounts=accounts,
    )
    db.add(_snapshot(test_user.id, JUNE, "1000.00"))
    await db.flush()
    portfolio = PortfolioService()

    current = (await portfolio.get_holdings(db, test_user.id, base_currency="SGD"))[0]
    as_of_june = (await portfolio.get_holdings(db, test_user.id, as_of_date=JUNE, base_currency="SGD"))[0]

    expected = {"FIFO": Decimal("700.00"), "LIFO": Decimal("500.00"), "AvgCost": Decimal("600.00")}[method]
    assert (sold.position.cost_basis, current.cost_basis, as_of_june.cost_basis) == (expected, expected, expected)


async def test_a_sale_without_a_recorded_purchase_gives_no_cost_at_a_past_date(db, test_user):
    position = await _import_two_snapshots(db, test_user.id)
    db.add(
        InvestmentTransaction(
            user_id=test_user.id,
            position_id=position.id,
            transaction_date=date(2026, 7, 15),
            transaction_type=InvestmentTransactionType.SELL,
            asset_identifier="VWRA",
            quantity=Decimal("1"),
            unit_price=Decimal("210.00"),
            gross_amount=Decimal("210.00"),
            fees=Decimal("0.00"),
            currency="SGD",
            cost_basis=Decimal("50.00"),
            realized_pnl=Decimal("160.00"),
        )
    )
    await db.flush()

    holding = (await PortfolioService().get_holdings(db, test_user.id, as_of_date=SEPTEMBER, base_currency="SGD"))[0]

    assert (holding.cost_basis, holding.unrealized_pnl) == (None, None)


async def test_a_disposed_imported_position_does_not_empty_the_schedule_total(db, test_user):
    cash = Account(user_id=test_user.id, name="Brokerage Cash", type=AccountType.ASSET, currency="SGD")
    broker = Account(user_id=test_user.id, name="Moomoo", type=AccountType.ASSET, currency="SGD")
    db.add_all([cash, broker])
    await db.flush()
    await InvestmentAccountingService().post_buy(
        db,
        user_id=test_user.id,
        order=TradeOrder.create(
            transaction_date=date(2026, 6, 15),
            asset_identifier="VWRA",
            quantity=Decimal("10"),
            unit_price=Decimal("180.00"),
            currency="SGD",
        ),
        accounts=TradeAccounts(cash=cash.id, investment=broker.id),
    )
    await _import_two_snapshots(db, test_user.id)
    for snapshot_date, quantity in ((JUNE, "3"), (SEPTEMBER, "0")):
        sold_out = _snapshot(test_user.id, snapshot_date, "300.00" if quantity != "0" else "0.00")
        sold_out.asset_identifier, sold_out.quantity = "ES3", Decimal(quantity)
        sold_out.dedup_hash = f"es3_2920_{snapshot_date.isoformat()}"
        db.add(sold_out)
        await db.flush()
        await PositionService().reconcile_positions(db, test_user.id)

    schedule = await build_investment_performance_report_schedule(
        db, test_user.id, period_start=date(2026, 7, 1), period_end=SEPTEMBER, as_of_date=SEPTEMBER, currency="SGD"
    )

    assert (
        {row.asset_identifier: (row.cost_basis, row.unrealized_pnl) for row in schedule.holdings},
        schedule.unrealized_pnl,
        [note for note in schedule.notes if note.startswith("No purchase is recorded")],
    ) == ({"VWRA": (Decimal("1800.00"), Decimal("300.00")), "ES3": (None, None)}, Decimal("300.00"), [])


async def test_balance_sheet_adds_the_full_market_value_when_the_broker_account_holds_ledger_cash():
    account_id = uuid4()
    basis = {
        account_id: {
            "account": Account(name="Moomoo", type=AccountType.ASSET, currency="SGD"),
            "market_value": Decimal("2100.00"),
            "cost_basis": Decimal("0"),
            "source_currencies": {"SGD"},
        }
    }

    lines = _portfolio_market_adjustment_lines_from_basis(
        basis, asset_lines=[{"account_id": account_id, "amount": Decimal("5000.00")}], target_currency="SGD"
    )

    assert [line["amount"] for line in lines] == [Decimal("2100.00")]


@pytest.mark.no_db
def test_migration_0079_clears_the_cost_of_positions_without_a_buy_and_keeps_the_others():
    name = f"fr_2920_cost_{uuid4().hex[:12]}"
    admin = create_engine(migration_db_url("postgres").replace("+asyncpg", ""), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    database_url = migration_db_url(name)
    engine = create_engine(database_url.replace("+asyncpg", ""))
    user_id, account_id, imported_id, bought_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        run_alembic(database_url, "upgrade", "0078_outbox_dead_letter")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, email, hashed_password, ai_settings, created_at, updated_at) "
                    "VALUES (:id, :email, 'generated-hash', CAST('{}' AS jsonb), NOW(), NOW())"
                ),
                {"id": user_id, "email": f"cost-{user_id.hex}@example.test"},
            )
            connection.execute(
                text(
                    "INSERT INTO accounts (id, user_id, name, type, currency, is_active, is_system, created_at, updated_at) "
                    "VALUES (:id, :user_id, 'Moomoo', 'ASSET', 'SGD', true, false, NOW(), NOW())"
                ),
                {"id": account_id, "user_id": user_id},
            )
            for position_id, asset in ((imported_id, "VWRA"), (bought_id, "ES3")):
                connection.execute(
                    text(
                        "INSERT INTO managed_positions (id, user_id, account_id, asset_identifier, quantity, cost_basis, "
                        "unrealized_pnl, acquisition_date, status, currency, created_at, updated_at) "
                        "VALUES (:id, :user_id, :account_id, :asset, 10, 2100.00, 0, DATE '2026-06-30', 'active', 'SGD', "
                        "NOW(), TIMESTAMP '2026-06-30 00:00:00')"
                    ),
                    {"id": position_id, "user_id": user_id, "account_id": account_id, "asset": asset},
                )
            for kind, quantity, unit_price, gross_amount, cost in (
                ("buy", 10, "180.50", "1805.00", "1805.00"),
                ("sell", 3, "200.00", "600.00", "500.00"),
            ):
                connection.execute(
                    text(
                        "INSERT INTO investment_transactions (id, user_id, position_id, transaction_date, "
                        "transaction_type, asset_identifier, quantity, unit_price, gross_amount, fees, currency, "
                        "cost_basis, created_at, updated_at) "
                        "VALUES (:id, :user_id, :position_id, DATE '2026-06-30', :kind, 'ES3', :quantity, :unit_price, "
                        ":gross_amount, 0, 'SGD', :cost, NOW(), NOW())"
                    ),
                    {
                        "id": uuid4(),
                        "user_id": user_id,
                        "position_id": bought_id,
                        "kind": kind,
                        "quantity": quantity,
                        "unit_price": unit_price,
                        "gross_amount": gross_amount,
                        "cost": cost,
                    },
                )

        run_alembic(database_url, "upgrade", "0079_position_cost_nullable")
        with engine.connect() as connection:
            upgraded = {
                asset: (cost, pnl, touched)
                for asset, cost, pnl, touched in connection.execute(
                    text(
                        "SELECT asset_identifier, cost_basis, unrealized_pnl, "
                        "updated_at > TIMESTAMP '2026-07-01 00:00:00' FROM managed_positions"
                    )
                )
            }
        run_alembic(database_url, "check")
        run_alembic(database_url, "downgrade", "0078_outbox_dead_letter")
        with engine.connect() as connection:
            downgraded = dict(
                connection.execute(text("SELECT asset_identifier, cost_basis FROM managed_positions")).tuples().all()
            )
        run_alembic(database_url, "upgrade", "head")

        assert (upgraded, downgraded) == (
            # ES3: the cost of its BUY row (1805.00) less the cost of its SELL row (500.00).
            # Each rewritten row gets a new updated_at, which invalidates the workflow input stamp.
            {"VWRA": (None, None, True), "ES3": (Decimal("1305.00"), Decimal("0.00"), True)},
            {"VWRA": Decimal("0.00"), "ES3": Decimal("1305.00")},
        )
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
