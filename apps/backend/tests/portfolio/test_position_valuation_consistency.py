from datetime import date
from decimal import Decimal

from src.extraction.orm.layer2 import AtomicPosition
from src.ledger import Account, AccountType
from src.portfolio.orm.portfolio import CostBasisMethod, ManagedPosition, PositionStatus
from src.pricing.orm.market_data import FxRate

_ACQ_DATE = date(2025, 1, 15)
_NATIVE_COST = Decimal("10000.00")
_EXPECTED_BASE_COST = Decimal("1700.00")


async def test_ac1_ac2_reporting_and_native_cost_basis_reconcile_on_holdings(client, db, test_user):
    account = Account(user_id=test_user.id, name="HK Broker", type=AccountType.ASSET, currency="HKD")
    db.add(account)
    await db.flush()
    position = ManagedPosition(user_id=test_user.id, account_id=account.id, asset_identifier="0700.HK", quantity=Decimal("100.0"), cost_basis=_NATIVE_COST, acquisition_date=_ACQ_DATE, status=PositionStatus.ACTIVE, currency="HKD", cost_basis_method=CostBasisMethod.FIFO, position_metadata={"broker": "HK Broker"})
    db.add_all([
        position,
        AtomicPosition(user_id=test_user.id, snapshot_date=_ACQ_DATE, asset_identifier="0700.HK", broker="HK Broker", quantity=Decimal("100.0"), market_value=_NATIVE_COST, currency="HKD", dedup_hash="hk_0700_native_snapshot", source_documents={}),
        FxRate(base_currency="HKD", quote_currency="SGD", rate=Decimal("0.17"), rate_date=_ACQ_DATE, source="test"),
    ])
    await db.commit()
    await db.refresh(position)
    resp = await client.get("/portfolio/holdings")
    holding = next((h for h in resp.json()["items"] if h["id"] == str(position.id)), None)
    assert holding is not None
    assert (resp.status_code, holding["currency"], holding["reporting_currency"], holding["native_currency"], Decimal(str(holding["cost_basis"])), Decimal(str(holding["reporting_cost_basis"])), Decimal(str(holding["native_cost_basis"]))) == (200, "SGD", "SGD", "HKD", _EXPECTED_BASE_COST, _EXPECTED_BASE_COST, _NATIVE_COST)
