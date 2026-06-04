"""Tests for brokerage position parsing into AtomicPosition."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.models import (
    BankStatement,
    BankStatementStatus,
    BankStatementTransaction,
    ConfidenceLevel,
)
from src.models.layer2 import AssetType, AtomicPosition
from src.models.layer3 import ManagedPosition
from src.routers.statements import _brokerage_payload_from_statement
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


def test_AC17_12_2_parse_moomoo_margin_history_rows_as_equity_position_snapshot():
    """AC17.12.2: Sanitized Moomoo margin history rows create portfolio-ready equity snapshots."""
    payload = {
        "institution": "Moomoo",
        "statement": {"period_end": "2026-01-02", "currency": "USD"},
        "margin_history_rows": [
            {
                "Side": "BUY",
                "Symbol": "PONY",
                "Name": "Pony AI Inc ADR",
                "Fill Qty": "12",
                "Fill Amount": "123.45",
                "Currency": "USD",
                "Total": "123.56",
                "Commission": "0.00",
                "Platform Fees": "0.11",
                "Fill Time": "2026-01-02 09:35:21",
                "Sector": "Technology",
                "Geography": "US",
            },
            {
                "Side": "BUY",
                "Symbol": "PONY",
                "Name": "Pony AI Inc ADR",
                "Fill Qty": "24",
                "Fill Amount": "234.56",
                "Currency": "USD",
                "Total": "234.78",
                "Commission": "0.00",
                "Platform Fees": "0.22",
                "Fill Time": "2026-01-02 09:36:44",
                "Sector": "Technology",
                "Geography": "US",
            },
            {
                "Side": "SELL",
                "Symbol": "SKIPME",
                "Name": "Disposed Test Equity",
                "Fill Qty": "3",
                "Fill Amount": "99.99",
                "Currency": "USD",
                "Total": "99.72",
                "Fill Time": "2026-01-02 10:00:00",
            },
        ],
    }

    snapshots = parse_brokerage_positions(payload, filename="synthetic-margin-history.csv")

    assert len(snapshots) == 1
    assert snapshots[0].broker == "Moomoo"
    assert snapshots[0].snapshot_date.isoformat() == "2026-01-02"
    assert snapshots[0].asset_identifier == "PONY"
    assert snapshots[0].quantity == Decimal("36")
    assert snapshots[0].market_value == Decimal("358.01")
    assert snapshots[0].currency == "USD"
    assert snapshots[0].asset_type == AssetType.STOCK
    assert snapshots[0].sector == "Technology"
    assert snapshots[0].geography == "US"


def test_parse_moomoo_skips_non_position_subscription_events():
    """AC17.4.1: Moomoo fallback parsing ignores non-position and invalid subscription events."""
    payload = {
        "statement": {"period_end": "2026-05-18", "currency": "SGD"},
        "events": [
            "not a dict",
            {"description": "Money Market Fund rebate", "amount": "UNKNOWN"},
            {"description": "Money Market Fund redemption", "amount": "-10.00"},
            {"raw_text": ("Subscription 0001 Bad Quantity Fund SGD 2026/05/18 settled 1.0000 UNKNOWN 1250.50")},
            {"description": "Cash transfer", "amount": "100.00"},
        ],
    }

    assert parse_brokerage_positions(payload, filename="moomoo.pdf") == []


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


def test_parse_futu_aggregate_ignores_invalid_events_and_uses_best_value():
    """AC17.4.2: Futu aggregate fallback ignores invalid rows and keeps best securities value."""
    payload = {
        "statement": {"period_end": "2026-05-18", "currency": "HKD"},
        "events": [
            "not a dict",
            {"description": "Cash balance", "amount": "9999.00"},
            {"description": "Stock valuation", "amount": "UNKNOWN"},
            {"description": "Stock valuation", "amount": "100.00"},
            {"description": "Stock and options value", "amount": "250.00"},
        ],
    }

    snapshots = parse_brokerage_positions(payload, filename="futu.pdf")

    assert len(snapshots) == 1
    assert snapshots[0].asset_identifier == "FUTU_STOCK_AND_OPTIONS"
    assert snapshots[0].market_value == Decimal("250.00")


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


@pytest.mark.asyncio
async def test_statement_scoped_brokerage_import_uses_parsed_transactions(client, db, test_user):
    """AC8.13.10/Issue #404: Parsed brokerage statements can import portfolio positions."""
    statement = BankStatement(
        id=uuid4(),
        user_id=test_user.id,
        file_path="statements/moomoo/test.pdf",
        file_hash="issue-404-moomoo",
        original_filename="moomoo-2504.pdf",
        institution="Moomoo",
        account_last4="1582",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("2250.50"),
        status=BankStatementStatus.PARSED,
        confidence_score=95,
        balance_validated=True,
        transactions=[
            BankStatementTransaction(
                txn_date=date(2026, 5, 18),
                description="Fullerton SGD Money Market Fund",
                amount=Decimal("1250.50"),
                direction="IN",
                reference=None,
                currency="SGD",
                balance_after=Decimal("2250.50"),
                confidence=ConfidenceLevel.HIGH,
                raw_text="Subscription 0001 Fullerton SGD Money Market Fund SGD 2026/05/18 settled 1.0000 1250.50 1250.50",
            )
        ],
    )
    statement_id = statement.id
    db.add(statement)
    await db.commit()

    response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert response.status_code == 200
    data = response.json()
    assert data["broker"] == "Moomoo"
    assert data["parsed_positions"] == 1
    assert data["created_atomic_positions"] == 1
    assert data["reconcile_created"] == 1

    positions = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    assert len(positions) == 1
    assert positions[0].asset_identifier == "Fullerton SGD Money Market Fund"
    assert positions[0].market_value == Decimal("1250.50")


@pytest.mark.asyncio
async def test_statement_scoped_brokerage_import_uses_persisted_extraction_positions(client, db, test_user):
    """AC8.13.10/AC17.4.7: Statement import recovers structured OCR positions from metadata."""
    file_hash = "issue-653-moomoo-structured"
    statement = BankStatement(
        id=uuid4(),
        user_id=test_user.id,
        file_path="statements/moomoo/structured.pdf",
        file_hash=file_hash,
        original_filename="moomoo-structured.pdf",
        institution="Moomoo",
        account_last4="1582",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=None,
        closing_balance=None,
        status=BankStatementStatus.PARSED,
        confidence_score=95,
        balance_validated=False,
        extraction_metadata={
            "extraction_payload": {
                "institution": "Moomoo",
                "statement": {"period_end": "2026-05-31", "currency": "SGD"},
                "positions": [
                    {
                        "symbol": "Fullerton SGD Money Market Fund",
                        "quantity": "1",
                        "market_value": "1250.50",
                        "currency": "SGD",
                        "asset_type": "money_market",
                    }
                ],
            }
        },
        transactions=[],
    )
    db.add(statement)
    statement_id = statement.id
    await db.commit()

    response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert response.status_code == 200
    data = response.json()
    assert data["broker"] == "Moomoo"
    assert data["parsed_positions"] == 1
    assert data["created_atomic_positions"] == 1
    assert data["reconcile_created"] == 1

    positions = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    assert len(positions) == 1
    assert positions[0].asset_identifier == "Fullerton SGD Money Market Fund"
    assert positions[0].market_value == Decimal("1250.50")


@pytest.mark.asyncio
async def test_statement_import_flows_to_holdings_and_balance_sheet(client, db, test_user):
    """AC8.13.10/AC17.4.6/AC17.5.4: Parsed brokerage import reaches holdings and balance sheet."""
    statement = BankStatement(
        id=uuid4(),
        user_id=test_user.id,
        file_path="statements/moomoo/full-path.pdf",
        file_hash="core-path-moomoo",
        original_filename="moomoo-core-path.pdf",
        institution="Moomoo",
        account_last4="1582",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("1250.50"),
        status=BankStatementStatus.PARSED,
        confidence_score=98,
        balance_validated=True,
        transactions=[
            BankStatementTransaction(
                txn_date=date(2026, 5, 18),
                description="Fullerton SGD Money Market Fund",
                amount=Decimal("1250.50"),
                direction="IN",
                reference=None,
                currency="SGD",
                balance_after=Decimal("1250.50"),
                confidence=ConfidenceLevel.HIGH,
                raw_text="Subscription 0001 Fullerton SGD Money Market Fund SGD 2026/05/18 settled 1.0000 1250.50 1250.50",
            )
        ],
    )
    statement_id = statement.id
    db.add(statement)
    await db.commit()

    import_response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert import_response.status_code == 200
    import_data = import_response.json()
    assert import_data["broker"] == "Moomoo"
    assert import_data["parsed_positions"] == 1
    assert import_data["created_atomic_positions"] == 1
    assert import_data["reconcile_created"] == 1

    holdings_response = await client.get(
        "/portfolio/holdings",
        params={"as_of_date": "2026-05-31"},
    )

    assert holdings_response.status_code == 200
    holdings = holdings_response.json()
    assert len(holdings) == 1
    assert holdings[0]["asset_identifier"] == "Fullerton SGD Money Market Fund"
    assert holdings[0]["account_name"] == "Moomoo"
    assert Decimal(str(holdings[0]["quantity"])) == Decimal("1250.50")
    assert Decimal(str(holdings[0]["market_value"])) == Decimal("1250.50")
    assert holdings[0]["currency"] == "SGD"

    balance_response = await client.get(
        "/reports/balance-sheet",
        params={"as_of_date": "2026-05-31", "currency": "SGD"},
    )

    assert balance_response.status_code == 200
    balance_sheet = balance_response.json()
    assert Decimal(str(balance_sheet["total_assets"])) == Decimal("1250.50")
    assert Decimal(str(balance_sheet["net_worth_adjustment_gain_loss"])) == Decimal("1250.50")
    assert Decimal(str(balance_sheet["equation_delta"])) == Decimal("0.00")
    assert balance_sheet["is_balanced"] is True
    assert any(
        line["name"] == "Moomoo market valuation adjustment" and Decimal(str(line["amount"])) == Decimal("1250.50")
        for line in balance_sheet["assets"]
    )


@pytest.mark.asyncio
async def test_statement_scoped_brokerage_import_requires_parsed_status(client, db, test_user):
    """AC8.13.10/Issue #404: Position import cannot run before OCR parsing completes."""
    statement = BankStatement(
        id=uuid4(),
        user_id=test_user.id,
        file_path="statements/moomoo/pending.pdf",
        file_hash="issue-404-pending",
        original_filename="moomoo-pending.pdf",
        institution="Moomoo",
        currency="SGD",
        status=BankStatementStatus.PARSING,
    )
    statement_id = statement.id
    db.add(statement)
    await db.commit()

    response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert response.status_code == 400
    assert "must be parsed" in response.text


@pytest.mark.asyncio
async def test_statement_scoped_brokerage_import_explains_internal_state_transition_stall(
    client,
    db,
    test_user,
):
    """AC8.13.10/Issue #409: Import errors distinguish parsed-data routing stalls."""
    statement = BankStatement(
        id=uuid4(),
        user_id=test_user.id,
        file_path="statements/moomoo/stalled.pdf",
        file_hash="issue-409-stalled",
        original_filename="moomoo-stalled.pdf",
        institution="Moomoo",
        currency="SGD",
        status=BankStatementStatus.UPLOADED,
        parsing_progress=100,
        balance_validated=False,
        transactions=[
            BankStatementTransaction(
                txn_date=date(2026, 5, 19),
                description="Withdrawal",
                amount=Decimal("500.00"),
                direction="OUT",
            )
        ],
    )
    statement_id = statement.id
    db.add(statement)
    await db.commit()

    response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert response.status_code == 400
    assert "Internal state-transition failure after OCR extraction" in response.text
    assert "transactions=1" in response.text


@pytest.mark.asyncio
async def test_statement_scoped_brokerage_import_explains_provider_parse_failure(client, db, test_user):
    """AC8.13.10/Issue #409: Import errors distinguish provider parsing failures."""
    statement = BankStatement(
        id=uuid4(),
        user_id=test_user.id,
        file_path="statements/moomoo/rejected.pdf",
        file_hash="issue-409-rejected",
        original_filename="moomoo-rejected.pdf",
        institution="Moomoo",
        currency="SGD",
        status=BankStatementStatus.REJECTED,
        validation_error="OCR provider returned invalid JSON",
    )
    statement_id = statement.id
    db.add(statement)
    await db.commit()

    response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert response.status_code == 400
    assert "Provider parsing failed before brokerage import" in response.text
    assert "OCR provider returned invalid JSON" in response.text


@pytest.mark.asyncio
async def test_statement_scoped_brokerage_import_returns_404_for_missing_statement(client):
    """AC8.13.10/Issue #404: Statement-scoped brokerage import is user-scoped."""
    response = await client.post(f"/statements/{uuid4()}/brokerage/import")

    assert response.status_code == 404


def test_brokerage_payload_from_statement_preserves_outflows_and_empty_metadata():
    """AC8.13.10/Issue #404: Statement payload keeps signed cash events deterministic."""
    statement = BankStatement(
        id=uuid4(),
        user_id=uuid4(),
        file_path="statements/futu/test.pdf",
        file_hash="issue-404-futu-outflow",
        original_filename="futu-2506.pdf",
        institution="Futu",
        currency="SGD",
        status=BankStatementStatus.APPROVED,
        transactions=[
            BankStatementTransaction(
                txn_date=date(2026, 5, 18),
                description="Platform fee",
                amount=Decimal("4.23"),
                direction="OUT",
                reference=None,
                currency=None,
                balance_after=None,
                confidence=ConfidenceLevel.HIGH,
                raw_text=None,
            )
        ],
    )

    payload = _brokerage_payload_from_statement(statement)

    assert payload["institution"] == "Futu"
    assert payload["statement"]["period_end"] is None
    assert payload["statement"]["currency"] == "SGD"
    assert payload["transactions"] == payload["events"]
    assert payload["transactions"] == [
        {
            "date": "2026-05-18",
            "description": "Platform fee",
            "amount": "-4.23",
            "currency": "SGD",
            "raw_text": "Platform fee",
            "balance_after": None,
        }
    ]
