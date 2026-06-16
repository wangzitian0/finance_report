"""AC17.11: Portfolio financial logic audit tests."""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Account, AccountType, FxRate
from src.models.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.models.portfolio import DividendIncome, InvestmentTransaction, InvestmentTransactionType
from src.services.performance import calculate_money_weighted_return, calculate_time_weighted_return, calculate_xirr
from src.services.performance_report import _source_document_links


async def _investment_position(db: AsyncSession, test_user, *, asset_identifier: str = "AUDIT") -> ManagedPosition:
    account = Account(user_id=test_user.id, name="Investment Account", type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    position = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier=asset_identifier,
        quantity=Decimal("100"),
        cost_basis=Decimal("10000.00"),
        currency="SGD",
        acquisition_date=date.today() - timedelta(days=365),
        status=PositionStatus.ACTIVE,
        cost_basis_method=CostBasisMethod.FIFO,
    )
    db.add(position)
    await db.flush()
    return position


def test_AC17_11_4_source_document_links_ignore_non_structured_payloads():
    """AC17.11.4: Non-structured source document payloads produce no audit links."""
    assert _source_document_links("legacy-import") == []


async def test_AC17_11_1_xirr_excludes_unrelated_bank_transactions(db: AsyncSession, test_user):
    """AC17.11.1: XIRR/MWR use investment transactions, not unrelated bank atomic transactions."""
    position = await _investment_position(db, test_user, asset_identifier="XIRRAUDIT")
    start = date.today() - timedelta(days=365)
    db.add_all(
        [
            InvestmentTransaction(
                user_id=test_user.id,
                position_id=position.id,
                transaction_date=start,
                transaction_type=InvestmentTransactionType.BUY,
                asset_identifier=position.asset_identifier,
                quantity=Decimal("100"),
                unit_price=Decimal("100.00"),
                gross_amount=Decimal("10000.00"),
                fees=Decimal("0.00"),
                currency="SGD",
                cost_basis=Decimal("10000.00"),
                realized_pnl=Decimal("0.00"),
                cost_basis_method=CostBasisMethod.FIFO,
            ),
            AtomicTransaction(
                user_id=test_user.id,
                txn_date=start,
                amount=Decimal("50000.00"),
                currency="SGD",
                direction=TransactionDirection.IN,
                description="Unrelated salary deposit",
                source_documents={},
                dedup_hash="unrelated_salary_deposit",
            ),
            AtomicPosition(
                user_id=test_user.id,
                snapshot_date=date.today(),
                asset_identifier=position.asset_identifier,
                broker="Test Broker",
                quantity=Decimal("100"),
                market_value=Decimal("11000.00"),
                currency="SGD",
                dedup_hash="xirr_audit_snapshot",
                source_documents={},
            ),
        ]
    )
    await db.flush()

    xirr = await calculate_xirr(db, test_user.id)
    mwr = await calculate_money_weighted_return(db, test_user.id)

    assert abs(xirr - Decimal("10.00")) <= Decimal("0.01")
    assert mwr == xirr


async def test_AC17_11_3_twr_excludes_unrelated_bank_transactions(db: AsyncSession, test_user):
    """AC17.11.3: TWR excludes unrelated bank transactions from cash-flow adjustment."""
    position = await _investment_position(db, test_user, asset_identifier="TWRAUDIT")
    start = date.today() - timedelta(days=30)
    end = date.today()
    db.add_all(
        [
            AtomicPosition(
                user_id=test_user.id,
                snapshot_date=start,
                asset_identifier=position.asset_identifier,
                broker="Test Broker",
                quantity=Decimal("100"),
                market_value=Decimal("10000.00"),
                currency="SGD",
                dedup_hash="twr_audit_start",
                source_documents={},
            ),
            AtomicPosition(
                user_id=test_user.id,
                snapshot_date=end,
                asset_identifier=position.asset_identifier,
                broker="Test Broker",
                quantity=Decimal("100"),
                market_value=Decimal("11000.00"),
                currency="SGD",
                dedup_hash="twr_audit_end",
                source_documents={},
            ),
            AtomicTransaction(
                user_id=test_user.id,
                txn_date=start + timedelta(days=10),
                amount=Decimal("5000.00"),
                currency="SGD",
                direction=TransactionDirection.IN,
                description="Unrelated bank deposit",
                source_documents={},
                dedup_hash="unrelated_bank_deposit_twr",
            ),
        ]
    )
    await db.flush()

    twr = await calculate_time_weighted_return(db, test_user.id, start, end)

    assert twr == Decimal("10.0")


async def test_AC17_11_2_summary_ytd_amounts_convert_to_presentation_currency(
    client: AsyncClient,
    db: AsyncSession,
    test_user,
):
    """AC17.11.2: Summary YTD realized/dividend amounts are converted before aggregation."""
    position = await _investment_position(db, test_user, asset_identifier="USDAUDIT")
    today = date.today()
    sell_date = date(today.year, 3, 1)
    dividend_date = date(today.year, 4, 1)
    db.add_all(
        [
            FxRate(base_currency="USD", quote_currency="SGD", rate=Decimal("1.350000"), rate_date=today, source="test"),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.350000"),
                rate_date=position.acquisition_date,
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.350000"),
                rate_date=sell_date,
                source="test",
            ),
            FxRate(
                base_currency="USD",
                quote_currency="SGD",
                rate=Decimal("1.350000"),
                rate_date=dividend_date,
                source="test",
            ),
            AtomicPosition(
                user_id=test_user.id,
                snapshot_date=today,
                asset_identifier=position.asset_identifier,
                broker="Test Broker",
                quantity=Decimal("100"),
                market_value=Decimal("1000.00"),
                currency="SGD",
                dedup_hash="summary_audit_snapshot",
                source_documents={},
            ),
            InvestmentTransaction(
                user_id=test_user.id,
                position_id=position.id,
                transaction_date=sell_date,
                transaction_type=InvestmentTransactionType.SELL,
                asset_identifier=position.asset_identifier,
                quantity=Decimal("5"),
                unit_price=Decimal("100.00"),
                gross_amount=Decimal("500.00"),
                fees=Decimal("0.00"),
                currency="USD",
                cost_basis=Decimal("400.00"),
                realized_pnl=Decimal("100.00"),
                cost_basis_method=CostBasisMethod.FIFO,
            ),
            DividendIncome(
                user_id=test_user.id,
                position_id=position.id,
                payment_date=dividend_date,
                amount=Decimal("10.00"),
                currency="USD",
            ),
        ]
    )
    await db.commit()

    response = await client.get("/portfolio/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "SGD"
    assert data["realized_pnl_ytd"] == "135.00"
    assert data["dividend_income_ytd"] == "13.50"
