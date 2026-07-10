"""#1098 — unified position valuation: /assets/positions and /portfolio/holdings
must be currency-explicit and reconcilable.

Behavioral regression repro for the staging bug where the same position showed
two currencies because the two read paths applied different currency policies:
- /portfolio/holdings converted cost/value to base currency (returns BASE).
- /assets/positions returned the raw ManagedPosition (returns NATIVE).

These tests pin down that BOTH endpoints now expose native AND base values
derived from the single convert_money authority, and that an FX failure degrades
the reporting view to null instead of 500-ing the read.
"""

from datetime import date
from decimal import Decimal

from src.models.account import Account, AccountType
from src.models.layer2 import AtomicPosition
from src.models.layer3 import CostBasisMethod, ManagedPosition, PositionStatus
from src.pricing.orm.market_data import FxRate

# Base reporting currency is SGD (config default); native is HKD.
_ACQ_DATE = date(2025, 1, 15)
_HKD_TO_SGD = Decimal("0.17")
_NATIVE_COST = Decimal("10000.00")  # HKD
_EXPECTED_BASE_COST = Decimal("1700.00")  # 10000 * 0.17 SGD


async def _seed_position(db, test_user, *, with_fx_rate: bool) -> ManagedPosition:
    """Seed a ManagedPosition (HKD) plus a matching AtomicPosition snapshot so
    both endpoints surface the same logical position. Optionally seed the
    HKD->SGD FX rate the reporting conversion needs."""
    account = Account(
        user_id=test_user.id,
        name="HK Broker",
        type=AccountType.ASSET,
        currency="HKD",
    )
    db.add(account)
    await db.flush()

    position = ManagedPosition(
        user_id=test_user.id,
        account_id=account.id,
        asset_identifier="0700.HK",
        quantity=Decimal("100.0"),
        cost_basis=_NATIVE_COST,
        acquisition_date=_ACQ_DATE,
        status=PositionStatus.ACTIVE,
        currency="HKD",
        cost_basis_method=CostBasisMethod.FIFO,
        position_metadata={"broker": "HK Broker"},
    )
    # Matching atomic snapshot: gives /portfolio/holdings (get_holdings path) a
    # per-unit market price in the same native currency.
    snapshot = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=_ACQ_DATE,
        asset_identifier="0700.HK",
        broker="HK Broker",
        quantity=Decimal("100.0"),
        market_value=_NATIVE_COST,
        currency="HKD",
        dedup_hash="hk_0700_native_snapshot",
        source_documents={},
    )
    db.add_all([position, snapshot])

    if with_fx_rate:
        db.add(
            FxRate(
                base_currency="HKD",
                quote_currency="SGD",
                rate=_HKD_TO_SGD,
                rate_date=_ACQ_DATE,
                source="test",
            )
        )
    await db.commit()
    await db.refresh(position)
    return position


def _find_holding(holdings: list[dict], position_id: str) -> dict:
    match = next((h for h in holdings if h["id"] == position_id), None)
    assert match is not None, f"holding {position_id} not found in {holdings}"
    return match


async def test_ac1_reporting_cost_basis_reconciles_on_base(client, db, test_user):
    """AC1: /assets/positions reporting_cost_basis (base SGD) reconciles with
    /portfolio/holdings base cost_basis for the same position."""
    position = await _seed_position(db, test_user, with_fx_rate=True)

    positions_resp = await client.get("/assets/positions")
    assert positions_resp.status_code == 200
    item = next(i for i in positions_resp.json()["items"] if i["id"] == str(position.id))

    holdings_resp = await client.get("/portfolio/holdings")
    assert holdings_resp.status_code == 200
    holding = _find_holding(holdings_resp.json(), str(position.id))

    # /assets/positions exposes the base-converted cost basis ...
    assert item["reporting_currency"] == "SGD"
    assert Decimal(str(item["reporting_cost_basis"])) == _EXPECTED_BASE_COST
    # ... and it equals what /portfolio/holdings reports as its base cost_basis.
    assert holding["currency"] == "SGD"
    assert Decimal(str(item["reporting_cost_basis"])) == Decimal(str(holding["cost_basis"]))


async def test_ac2_native_values_reconcile(client, db, test_user):
    """AC2: /assets/positions native cost_basis/currency equals /portfolio/holdings
    native_cost_basis/native_currency for the same position."""
    position = await _seed_position(db, test_user, with_fx_rate=True)

    positions_resp = await client.get("/assets/positions")
    assert positions_resp.status_code == 200
    item = next(i for i in positions_resp.json()["items"] if i["id"] == str(position.id))

    holdings_resp = await client.get("/portfolio/holdings")
    assert holdings_resp.status_code == 200
    holding = _find_holding(holdings_resp.json(), str(position.id))

    assert item["currency"] == "HKD"
    assert Decimal(str(item["cost_basis"])) == _NATIVE_COST
    assert holding["native_currency"] == "HKD"
    assert Decimal(str(holding["native_cost_basis"])) == _NATIVE_COST
    # Cross-endpoint native reconciliation.
    assert item["currency"] == holding["native_currency"]
    assert Decimal(str(item["cost_basis"])) == Decimal(str(holding["native_cost_basis"]))


async def test_ac3_missing_fx_rate_does_not_500(client, db, test_user):
    """AC3: with NO FX rate for the pair, /assets/positions returns 200 and
    reporting_cost_basis is null (graceful, never a 500)."""
    position = await _seed_position(db, test_user, with_fx_rate=False)

    positions_resp = await client.get("/assets/positions")
    assert positions_resp.status_code == 200
    item = next(i for i in positions_resp.json()["items"] if i["id"] == str(position.id))

    # Native view still present; reporting view degraded to null.
    assert item["currency"] == "HKD"
    assert Decimal(str(item["cost_basis"])) == _NATIVE_COST
    assert item["reporting_cost_basis"] is None
    assert item["reporting_currency"] is None

    # Single-position endpoint must also stay graceful.
    single_resp = await client.get(f"/assets/positions/{position.id}")
    assert single_resp.status_code == 200
    single = single_resp.json()
    assert single["reporting_cost_basis"] is None
    assert single["reporting_currency"] is None


async def test_native_and_reporting_currency_fields_are_identically_named_across_endpoints(client, db, test_user):
    """#1482: both endpoints expose the SAME explicit currency fields
    (`native_currency`, `reporting_currency`) with identical meaning, so a client
    never has to read the endpoint-local bare `currency` — which means NATIVE on
    /assets/positions but REPORTING on /portfolio/holdings."""
    position = await _seed_position(db, test_user, with_fx_rate=True)

    positions_resp = await client.get("/assets/positions")
    assert positions_resp.status_code == 200
    item = next(i for i in positions_resp.json()["items"] if i["id"] == str(position.id))

    holdings_resp = await client.get("/portfolio/holdings")
    assert holdings_resp.status_code == 200
    holding = _find_holding(holdings_resp.json(), str(position.id))

    # Both endpoints now carry BOTH explicit, identically-named currency fields.
    assert item["native_currency"] == holding["native_currency"] == "HKD"
    assert item["reporting_currency"] == holding["reporting_currency"] == "SGD"
    # Cost-basis aliases line up the same way.
    assert Decimal(str(item["native_cost_basis"])) == Decimal(str(holding["native_cost_basis"])) == _NATIVE_COST
    assert (
        Decimal(str(item["reporting_cost_basis"]))
        == Decimal(str(holding["reporting_cost_basis"]))
        == _EXPECTED_BASE_COST
    )
    # The explicit fields are pure aliases of each endpoint's legacy bare field,
    # not newly-computed values: native on the native endpoint, reporting on the
    # reporting endpoint.
    assert item["native_currency"] == item["currency"]
    assert holding["reporting_currency"] == holding["currency"]
