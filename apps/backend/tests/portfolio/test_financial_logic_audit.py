from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import TransactionDirection
from src.extraction.orm.layer2 import AtomicPosition, AtomicTransaction
from src.ledger import Account, AccountType
from src.portfolio import DividendIncome, InvestmentTransaction, InvestmentTransactionType, calculate_money_weighted_return, calculate_time_weighted_return, calculate_xirr
from src.portfolio.extension.performance_report import _source_document_links
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.pricing.orm.market_data import FxRate


async def _investment_position(db: AsyncSession, test_user, asset_identifier: str) -> ManagedPosition:
    account = Account(user_id=test_user.id, name="Test Broker", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    position = ManagedPosition(user_id=test_user.id, account_id=account.id, asset_identifier=asset_identifier, quantity=Decimal("100"), cost_basis=Decimal("10000.00"), currency="SGD", acquisition_date=date.today() - timedelta(days=365), status=PositionStatus.ACTIVE, cost_basis_method=CostBasisMethod.FIFO)
    db.add(position)
    await db.flush()
    return position


def test_AC17_11_4_source_document_links_ignore_non_structured_payloads():
    assert _source_document_links("legacy-import") == []


async def test_AC17_11_1_3_returns_exclude_unrelated_bank_transactions(db: AsyncSession, test_user):
    pos = await _investment_position(db, test_user, "XIRRAUDIT")
    today = date.today()
    start_year, start_30 = today - timedelta(days=365), today - timedelta(days=30)
    db.add_all([
        InvestmentTransaction(user_id=test_user.id, position_id=pos.id, transaction_date=start_year, transaction_type=InvestmentTransactionType.BUY, asset_identifier=pos.asset_identifier, quantity=Decimal("100"), unit_price=Decimal("100.00"), gross_amount=Decimal("10000.00"), fees=Decimal("0.00"), currency="SGD", cost_basis=Decimal("10000.00"), realized_pnl=Decimal("0.00"), cost_basis_method=CostBasisMethod.FIFO),
        AtomicTransaction(user_id=test_user.id, txn_date=start_year, amount=Decimal("50000.00"), currency="SGD", direction=TransactionDirection.IN, description="Unrelated salary deposit", source_documents={}, dedup_hash="unrelated_salary_deposit"),
        AtomicTransaction(user_id=test_user.id, txn_date=start_30 + timedelta(days=10), amount=Decimal("5000.00"), currency="SGD", direction=TransactionDirection.IN, description="Unrelated bank deposit", source_documents={}, dedup_hash="unrelated_bank_deposit_twr"),
        AtomicPosition(user_id=test_user.id, snapshot_date=start_30, asset_identifier=pos.asset_identifier, broker="Test Broker", quantity=Decimal("100"), market_value=Decimal("10000.00"), currency="SGD", dedup_hash="twr_audit_start", source_documents={}),
        AtomicPosition(user_id=test_user.id, snapshot_date=today, asset_identifier=pos.asset_identifier, broker="Test Broker", quantity=Decimal("100"), market_value=Decimal("11000.00"), currency="SGD", dedup_hash="xirr_audit_snapshot", source_documents={}),
    ])
    await db.flush()
    xirr = await calculate_xirr(db, test_user.id, base_currency="SGD")
    mwr = await calculate_money_weighted_return(db, test_user.id, base_currency="SGD")
    twr = await calculate_time_weighted_return(db, test_user.id, start_30, today, base_currency="SGD")
    assert (abs(xirr - Decimal("10.00")) <= Decimal("0.01"), mwr == xirr, twr) == (True, True, Decimal("10.0"))


async def test_AC17_11_2_summary_ytd_amounts_convert_to_presentation_currency(client: AsyncClient, db: AsyncSession, test_user):
    pos = await _investment_position(db, test_user, "USDAUDIT")
    today = date.today()
    sell_date, div_date = date(today.year, 3, 1), date(today.year, 4, 1)
    db.add_all([
        *(FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=d, source="test") for d in (today, pos.acquisition_date, sell_date, div_date)),
        AtomicPosition(user_id=test_user.id, snapshot_date=today, asset_identifier=pos.asset_identifier, broker="Test Broker", quantity=Decimal("100"), market_value=Decimal("1000.00"), currency="SGD", dedup_hash="summary_audit_snapshot", source_documents={}),
        InvestmentTransaction(user_id=test_user.id, position_id=pos.id, transaction_date=sell_date, transaction_type=InvestmentTransactionType.SELL, asset_identifier=pos.asset_identifier, quantity=Decimal("5"), unit_price=Decimal("100.00"), gross_amount=Decimal("500.00"), fees=Decimal("0.00"), currency="USD", cost_basis=Decimal("400.00"), realized_pnl=Decimal("100.00"), cost_basis_method=CostBasisMethod.FIFO),
        DividendIncome(user_id=test_user.id, position_id=pos.id, payment_date=div_date, amount=Decimal("10.00"), currency="USD"),
    ])
    await db.commit()
    resp = await client.get("/portfolio/summary")
    data = resp.json()
    assert (resp.status_code, data["currency"], data["realized_pnl_ytd"], data["dividend_income_ytd"]) == (200, "SGD", "135.00", "13.50")
