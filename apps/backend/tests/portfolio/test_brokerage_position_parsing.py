"""Tests for brokerage position parsing into AtomicPosition."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from src.models.layer2 import AssetType, AtomicPosition
from src.models.layer3 import ManagedPosition
from src.services.brokerage_positions import BrokeragePositionImportService, detect_broker, parse_brokerage_positions

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load_fixture(name: str) -> dict:
    with (FIXTURES / name).open() as fh:
        return json.load(fh)


def test_detect_broker_moomoo_futu_and_interactive_brokers():
    """AC17.4.4/AC17.4.5: Broker auto-detection supports known broker names."""
    assert detect_broker(filename="moomoo-2504.pdf", institution=None, text="") == "Moomoo"
    assert detect_broker(filename="statement.pdf", institution="Futu Securities", text="") == "Futu"
    assert detect_broker(filename="activity.csv", institution=None, text="Interactive Brokers LLC") == "Interactive Brokers"


def test_parse_moomoo_fixture_subscription_positions():
    """AC17.4.1: Moomoo parsed fixtures produce AtomicPosition-ready snapshots."""
    payload = _load_fixture("moomoo-2504_parsed.json")

    snapshots = parse_brokerage_positions(payload, filename="moomoo-2504.pdf")

    csop = next(item for item in snapshots if item.asset_identifier == "CSOP USD Money Market Fund")
    assert csop.broker == "Moomoo"
    assert csop.snapshot_date.isoformat() == "2025-04-30"
    assert csop.quantity == Decimal("1")
    assert csop.market_value == Decimal("80.27")
    assert csop.currency == "SGD"
    assert csop.asset_type == AssetType.MUTUAL_FUND


def test_parse_futu_fixture_aggregate_position():
    """AC17.4.2: Futu parsed fixtures preserve aggregate securities valuation."""
    payload = _load_fixture("futu-2506_parsed.json")

    snapshots = parse_brokerage_positions(payload, filename="futu-2506.pdf")

    assert len(snapshots) == 1
    assert snapshots[0].broker == "Futu"
    assert snapshots[0].asset_identifier == "FUTU_STOCK_AND_OPTIONS"
    assert snapshots[0].snapshot_date.isoformat() == "2025-06-30"
    assert snapshots[0].quantity == Decimal("1")
    assert snapshots[0].market_value == Decimal("323730.00")
    assert snapshots[0].currency == "HKD"


@pytest.mark.asyncio
async def test_import_interactive_brokers_positions_idempotently_reconciles(db, test_user):
    """AC17.4.3: Interactive Brokers payloads import to AtomicPosition and reconcile once."""
    service = BrokeragePositionImportService()
    payload = {
        "institution": "Interactive Brokers",
        "statement": {"period_end": "2026-05-18", "currency": "USD"},
        "positions": [
            {
                "symbol": "AAPL",
                "quantity": "10",
                "market_value": "1900.25",
                "currency": "USD",
                "asset_type": "stock",
                "sector": "Technology",
                "geography": "US",
            }
        ],
    }

    first = await service.import_positions(db, user_id=test_user.id, payload=payload, source_document_id="doc-ibkr")
    second = await service.import_positions(db, user_id=test_user.id, payload=payload, source_document_id="doc-ibkr")
    await db.commit()

    assert first.created_atomic_positions == 1
    assert first.reconcile_created == 1
    assert second.created_atomic_positions == 0
    assert second.reconcile_created == 0

    atomic_rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    assert len(atomic_rows) == 1
    assert atomic_rows[0].asset_identifier == "AAPL"
    assert atomic_rows[0].sector == "Technology"

    managed_rows = (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == test_user.id))).scalars().all()
    assert len(managed_rows) == 1
    assert managed_rows[0].asset_identifier == "AAPL"
    assert managed_rows[0].quantity == Decimal("10")


@pytest.mark.asyncio
async def test_brokerage_import_endpoint(client, db):
    """AC17.4.6: Brokerage import endpoint returns atomic and reconciliation counts."""
    response = await client.post(
        "/portfolio/brokerage/import",
        json={
            "filename": "ibkr.csv",
            "payload": {
                "institution": "Interactive Brokers",
                "statement": {"period_end": "2026-05-18", "currency": "USD"},
                "positions": [{"symbol": "MSFT", "quantity": "2", "market_value": "860.00", "currency": "USD"}],
            },
            "source_document_id": "doc-msft",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["broker"] == "Interactive Brokers"
    assert data["parsed_positions"] == 1
    assert data["created_atomic_positions"] == 1
    assert data["reconcile_created"] == 1
