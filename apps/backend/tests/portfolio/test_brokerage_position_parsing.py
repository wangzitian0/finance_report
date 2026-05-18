"""Tests for brokerage position parsing into AtomicPosition."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from src.models.layer2 import AssetType, AtomicPosition
from src.models.layer3 import ManagedPosition
from src.schemas.portfolio import BrokerageImportRequest, BrokerageImportResponse
from src.services.brokerage_positions import (
    BrokeragePositionImportService,
    _asset_type,
    _clean_decimal,
    _parse_date,
    _payload_currency,
    _statement_date,
    detect_broker,
    parse_brokerage_positions,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load_fixture(name: str) -> dict:
    with (FIXTURES / name).open() as fh:
        return json.load(fh)


def test_detect_broker_moomoo_futu_and_interactive_brokers():
    """AC17.4.4/AC17.4.5: Broker auto-detection supports known broker names."""
    assert detect_broker(filename="moomoo-2504.pdf", institution=None, text="") == "Moomoo"
    assert detect_broker(filename="statement.pdf", institution="Futu Securities", text="") == "Futu"
    assert (
        detect_broker(filename="activity.csv", institution=None, text="Interactive Brokers LLC")
        == "Interactive Brokers"
    )


def test_brokerage_parser_helpers_handle_common_empty_and_alias_values():
    """AC17.4.5: Parser helpers normalize common brokerage statement values."""
    assert _clean_decimal(None) is None
    assert _clean_decimal("N/A") is None
    assert _clean_decimal("1,234.56") == Decimal("1234.56")
    assert _clean_decimal(Decimal("7.89")) == Decimal("7.89")
    assert _clean_decimal("not-a-number") is None

    assert _parse_date(None) is None
    assert _parse_date("UNKNOWN") is None
    assert _parse_date("2026-05").isoformat() == "2026-05-31"
    assert _parse_date("2026/05/18").isoformat() == "2026-05-18"
    assert _parse_date("bad-date") is None

    assert _payload_currency({}, default="sgd") == "SGD"
    assert _statement_date({"snapshot_date": "2026-06-01"}).isoformat() == "2026-06-01"
    assert _asset_type("fund") == AssetType.MUTUAL_FUND
    assert _asset_type("money_market") == AssetType.MUTUAL_FUND
    assert _asset_type("equity") == AssetType.STOCK
    assert _asset_type("etf") == AssetType.ETF
    assert _asset_type("unsupported") is None


def test_brokerage_import_schemas_accept_zero_count_responses():
    """AC17.4.6: Brokerage import schemas expose payload and non-negative count contract."""
    request = BrokerageImportRequest(
        payload={"positions": []},
        filename="ibkr.csv",
        source_document_id="doc-1",
    )
    response = BrokerageImportResponse(
        broker="Interactive Brokers",
        parsed_positions=0,
        created_atomic_positions=0,
        existing_atomic_positions=0,
        reconcile_created=0,
        reconcile_updated=0,
        reconcile_disposed=0,
        skipped=0,
    )

    assert request.filename == "ibkr.csv"
    assert request.source_document_id == "doc-1"
    assert response.created_atomic_positions == 0


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


def test_parse_statement_holdings_skips_invalid_rows_and_normalizes_metadata():
    """AC17.4.3: Structured statement holdings skip incomplete rows and normalize metadata."""
    payload = {
        "statement": {
            "institution": "Interactive Brokers",
            "period_end": "2026-05",
            "currency": "usd",
            "holdings": [
                {"symbol": "BROKEN", "quantity": "N/A", "market_value": "100.00"},
                {
                    "isin": "SG9999000001",
                    "quantity": "1,234.5",
                    "marketValue": "9,876.54",
                    "asset_class": "money_market",
                    "sector": "Cash",
                    "geography": "SG",
                },
            ],
        }
    }

    snapshots = parse_brokerage_positions(payload, filename="activity.csv")

    assert len(snapshots) == 1
    assert snapshots[0].snapshot_date.isoformat() == "2026-05-31"
    assert snapshots[0].asset_identifier == "SG9999000001"
    assert snapshots[0].quantity == Decimal("1234.5")
    assert snapshots[0].market_value == Decimal("9876.54")
    assert snapshots[0].currency == "USD"
    assert snapshots[0].asset_type == AssetType.MUTUAL_FUND
    assert snapshots[0].sector == "Cash"
    assert snapshots[0].geography == "SG"


def test_parse_top_level_securities_accepts_item_broker_and_snapshot_date():
    """AC17.4.3: Top-level securities payloads can override broker and snapshot date per row."""
    payload = {
        "institution": "Interactive Brokers",
        "snapshot_date": "2026-06-01",
        "currency": "USD",
        "securities": [
            {
                "ticker": "VWRA",
                "broker": "IBKR UK",
                "snapshot_date": "2026-06-02",
                "position": "3",
                "value": "360.123",
                "asset_type": "etf",
                "currency": "usd",
            }
        ],
    }

    snapshots = parse_brokerage_positions(payload, filename="ibkr.csv")

    assert len(snapshots) == 1
    assert snapshots[0].broker == "IBKR UK"
    assert snapshots[0].snapshot_date.isoformat() == "2026-06-02"
    assert snapshots[0].asset_identifier == "VWRA"
    assert snapshots[0].quantity == Decimal("3")
    assert snapshots[0].market_value == Decimal("360.12")
    assert snapshots[0].asset_type == AssetType.ETF


def test_parse_moomoo_raw_subscription_text_position():
    """AC17.4.1: Moomoo raw subscription event text is parsed when structured holdings are absent."""
    payload = {
        "statement": {"period_end": "2026/05/18", "currency": "SGD"},
        "events": [
            {"raw_text": ("Subscription 0001 Fullerton SGD Cash Fund SGD 2026/05/18 settled 1.0000 1250.50 1250.50")}
        ],
    }

    snapshots = parse_brokerage_positions(payload, filename="moomoo-statement.pdf")

    assert len(snapshots) == 1
    assert snapshots[0].asset_identifier == "Fullerton SGD Cash Fund"
    assert snapshots[0].quantity == Decimal("1250.50")
    assert snapshots[0].market_value == Decimal("1250.50")
    assert snapshots[0].currency == "SGD"


def test_parse_futu_cash_only_and_unknown_broker_payloads_return_no_positions():
    """AC17.4.2/AC17.4.5: Non-position events and unsupported brokers do not create snapshots."""
    futu_cash_only = {
        "statement": {"period_end": "2026-05-18", "currency": "HKD"},
        "events": [{"description": "Cash balance", "amount": "999.00"}],
    }
    unknown_payload = {
        "positions": [{"symbol": "BAD", "quantity": "UNKNOWN", "market_value": None}],
    }

    assert parse_brokerage_positions(futu_cash_only, filename="futu.pdf") == []
    assert parse_brokerage_positions(unknown_payload, filename="unknown.pdf") == []


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

    atomic_rows = (
        (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    )
    assert len(atomic_rows) == 1
    assert atomic_rows[0].asset_identifier == "AAPL"
    assert atomic_rows[0].sector == "Technology"

    managed_rows = (
        (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == test_user.id))).scalars().all()
    )
    assert len(managed_rows) == 1
    assert managed_rows[0].asset_identifier == "AAPL"
    assert managed_rows[0].quantity == Decimal("10")


@pytest.mark.asyncio
async def test_import_empty_payload_without_reconcile_returns_zero_counts(db, test_user):
    """AC17.4.6: Empty imports return zero counts without invoking reconciliation."""
    service = BrokeragePositionImportService()

    result = await service.import_positions(
        db,
        user_id=test_user.id,
        payload={"institution": "Unknown Broker", "transactions": []},
        filename="unknown.pdf",
        reconcile=False,
    )

    assert result.broker == "Unknown Broker"
    assert result.parsed_positions == 0
    assert result.created_atomic_positions == 0
    assert result.existing_atomic_positions == 0
    assert result.reconcile_created == 0
    assert result.reconcile_updated == 0
    assert result.reconcile_disposed == 0


@pytest.mark.asyncio
async def test_brokerage_import_endpoint_empty_payload_returns_zero_counts(client):
    """AC17.4.6: Brokerage import endpoint accepts empty parsed payloads without reconciliation."""
    response = await client.post(
        "/portfolio/brokerage/import",
        json={
            "filename": "unknown.pdf",
            "payload": {"transactions": []},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["broker"] == "Unknown Broker"
    assert data["parsed_positions"] == 0
    assert data["created_atomic_positions"] == 0
    assert data["reconcile_created"] == 0


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
