"""Tests for brokerage position parsing into AtomicPosition."""

import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction import DocumentType, UploadedDocument
from src.extraction.extension.brokerage_positions import (
    BrokeragePositionImportService,
    _asset_type,
    _clean_decimal,
    _parse_date,
    _payload_currency,
    _statement_date,
    detect_broker,
    parse_brokerage_positions,
)
from src.extraction.extension.brokerage_statement_payload import _brokerage_payload_from_statement
from src.extraction.orm.layer2 import AssetType, AtomicPosition, AtomicTransaction, TransactionDirection
from src.extraction.orm.layer3 import ManagedPosition
from src.extraction.orm.statement_enums import BankStatementStatus
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from src.portfolio import PositionService
from src.schemas.portfolio import BrokerageImportRequest, BrokerageImportResponse


async def _seed_statement(
    db,
    user_id,
    *,
    file_hash,
    file_path,
    original_filename,
    institution="Moomoo",
    status=BankStatementStatus.PARSED,
    currency="SGD",
    extraction_metadata=None,
    transactions=None,
    **summary_kwargs,
) -> StatementSummary:
    """Create UploadedDocument + StatementSummary + linked AtomicTransactions."""
    document = UploadedDocument(
        user_id=user_id,
        file_path=file_path,
        file_hash=file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
        extraction_metadata=extraction_metadata,
    )
    db.add(document)
    await db.flush()

    statement = StatementSummary(
        user_id=user_id,
        uploaded_document_id=document.id,
        file_hash=file_hash,
        institution=institution,
        currency=currency,
        status=status,
        extraction_metadata=extraction_metadata,
        **summary_kwargs,
    )
    db.add(statement)
    await db.flush()

    for txn_spec in transactions or []:
        txn = AtomicTransaction(
            user_id=user_id,
            txn_date=txn_spec["txn_date"],
            description=txn_spec["description"],
            amount=txn_spec["amount"],
            direction=txn_spec["direction"],
            reference=txn_spec.get("reference"),
            currency=txn_spec.get("currency", currency),
            dedup_hash=(uuid4().hex + uuid4().hex),
            source_documents=[{"doc_id": str(document.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
        )
        db.add(txn)
    await db.flush()
    return statement


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
    """AC17.4.1: Moomoo subscription payloads produce AtomicPosition-ready snapshots."""
    # Synthetic Moomoo money-market subscription payload (no real account data): the
    # subscription fallback turns a "Money Market Fund" cash event into a 1-unit
    # MUTUAL_FUND snapshot valued at the event amount.
    payload = {
        "institution": "Moomoo",
        "statement": {"period_end": "2025-04-30", "currency": "SGD"},
        "events": [
            {"description": "ACME Money Market Fund", "amount": "100.00"},
        ],
    }

    snapshots = parse_brokerage_positions(payload, filename="moomoo-2504.pdf")

    fund = next(item for item in snapshots if item.asset_identifier == "ACME Money Market Fund")
    assert fund.broker == "Moomoo"
    assert fund.snapshot_date.isoformat() == "2025-04-30"
    assert fund.quantity == Decimal("1")
    assert fund.market_value == Decimal("100.00")
    assert fund.currency == "SGD"
    assert fund.asset_type == AssetType.MUTUAL_FUND


def test_parse_futu_fixture_aggregate_position():
    """AC17.4.2: Futu parsed payloads preserve aggregate securities valuation."""
    # Synthetic Futu payload (no real account data): the aggregate fallback collapses
    # the best non-cash valuation event into a single FUTU_STOCK_AND_OPTIONS snapshot.
    payload = {
        "institution": "Futu",
        "statement": {"period_end": "2025-06-30", "currency": "HKD"},
        "events": [
            {"description": "Stock and options valuation", "amount": "100.00"},
        ],
    }

    snapshots = parse_brokerage_positions(payload, filename="futu-2506.pdf")

    assert len(snapshots) == 1
    assert snapshots[0].broker == "Futu"
    assert snapshots[0].asset_identifier == "FUTU_STOCK_AND_OPTIONS"
    assert snapshots[0].snapshot_date.isoformat() == "2025-06-30"
    assert snapshots[0].quantity == Decimal("1")
    assert snapshots[0].market_value == Decimal("100.00")
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


async def test_AC17_33_3_broker_account_uses_snapshot_currency_not_hardcoded_usd(db, test_user):
    """AC17.33.3: an auto-created broker account adopts the holding's currency, not a hardcoded USD."""
    service = BrokeragePositionImportService()
    payload = {
        "institution": "Futu",
        "statement": {"period_end": "2026-05-18", "currency": "HKD"},
        "positions": [
            {
                "symbol": "01810",
                "quantity": "100",
                "market_value": "5500.00",
                "currency": "HKD",
                "asset_type": "stock",
                "geography": "HK",
            }
        ],
    }

    await service.import_positions(db, user_id=test_user.id, payload=payload, source_document_id="doc-futu-hkd")
    await db.commit()

    account = (
        await db.execute(select(Account).where(Account.user_id == test_user.id, Account.type == AccountType.ASSET))
    ).scalar_one()
    assert account.currency == "HKD"


async def test_AC17_34_1_brokerage_import_persists_short_positions_with_negative_market_value(db, test_user):
    """AC17.34.1: short positions import as signed positions, not skipped or crashed (#1448).

    A margin/options account can hold short positions — a directly-shorted stock or a
    sold option — with negative quantity AND negative market value. The non-negative
    market-value / cost-basis CHECK constraints are gone, so a short persists (reducing
    portfolio value) instead of violating a constraint (500) or being silently dropped.
    """
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
            },
            {
                "symbol": "NIO270115P7000",
                "quantity": "-100",
                "market_value": "-27069.00",
                "currency": "USD",
                "asset_type": "stock",
            },
        ],
    }

    result = await service.import_positions(db, user_id=test_user.id, payload=payload, source_document_id="doc-short")
    await db.commit()

    assert result.parsed_positions == 2
    assert result.created_atomic_positions == 2
    assert result.skipped == 0

    atomic_rows = (
        (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    )
    assert {row.asset_identifier for row in atomic_rows} == {"AAPL", "NIO270115P7000"}
    short_atomic = next(row for row in atomic_rows if row.asset_identifier == "NIO270115P7000")
    assert short_atomic.quantity < 0
    assert short_atomic.market_value < 0

    managed_rows = (
        (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == test_user.id))).scalars().all()
    )
    short_managed = next(p for p in managed_rows if p.asset_identifier == "NIO270115P7000")
    assert short_managed.quantity < 0
    assert short_managed.cost_basis < 0


async def test_AC17_4_8_brokerage_import_survives_concurrent_auto_and_manual_import(db_engine, test_user):
    """AC17.4.8: Auto parse import and manual statement import race without duplicate-position 500s."""
    service = BrokeragePositionImportService()
    payload = {
        "institution": "Moomoo",
        "statement": {"period_end": "2026-06-30", "currency": "SGD"},
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
    sessionmaker = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)

    async with sessionmaker() as auto_session, sessionmaker() as manual_session:
        auto_result = await service.import_positions(
            auto_session,
            user_id=test_user.id,
            payload=payload,
            source_document_id="auto-parse-doc",
            reconcile=False,
        )

        manual_task = asyncio.create_task(
            service.import_positions(
                manual_session,
                user_id=test_user.id,
                payload=payload,
                source_document_id="manual-import-doc",
                reconcile=False,
            )
        )
        await asyncio.sleep(0.2)
        await auto_session.commit()

        manual_result = await asyncio.wait_for(manual_task, timeout=5)
        await manual_session.commit()

    async with sessionmaker() as verify_session:
        positions = (
            (await verify_session.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id)))
            .scalars()
            .all()
        )

    assert auto_result.created_atomic_positions == 1
    assert manual_result.created_atomic_positions == 0
    assert manual_result.existing_atomic_positions == 1
    assert len(positions) == 1
    assert positions[0].asset_identifier == "Fullerton SGD Money Market Fund"


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


async def test_statement_scoped_brokerage_import_uses_parsed_transactions(client, db, test_user):
    """AC-extraction.813.10/Issue #404: Parsed brokerage statements can import portfolio positions."""
    statement = await _seed_statement(
        db,
        test_user.id,
        file_hash="issue-404-moomoo",
        file_path="statements/moomoo/test.pdf",
        original_filename="moomoo-2504.pdf",
        account_last4="1582",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("2250.50"),
        confidence_score=95,
        balance_validated=True,
        transactions=[
            {
                "txn_date": date(2026, 5, 18),
                "description": "Fullerton SGD Money Market Fund",
                "amount": Decimal("1250.50"),
                "direction": TransactionDirection.IN,
                "currency": "SGD",
            }
        ],
    )
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


async def test_statement_scoped_brokerage_import_uses_persisted_extraction_positions(client, db, test_user):
    """AC-extraction.813.10/AC-extraction.304.7: Statement import recovers structured OCR positions from metadata."""
    file_hash = "issue-653-moomoo-structured"
    statement = await _seed_statement(
        db,
        test_user.id,
        file_hash=file_hash,
        file_path="statements/moomoo/structured.pdf",
        original_filename="moomoo-structured.pdf",
        account_last4="1582",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=None,
        closing_balance=None,
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


async def test_statement_import_flows_to_holdings_and_balance_sheet(client, db, test_user):
    """AC-portfolio.valuation.1: AC-extraction.813.10/AC17.4.6/AC17.5.4: Parsed brokerage import reaches holdings and balance sheet."""
    statement = await _seed_statement(
        db,
        test_user.id,
        file_hash="core-path-moomoo",
        file_path="statements/moomoo/full-path.pdf",
        original_filename="moomoo-core-path.pdf",
        account_last4="1582",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("1250.50"),
        confidence_score=98,
        balance_validated=True,
        transactions=[
            {
                "txn_date": date(2026, 5, 18),
                "description": "Fullerton SGD Money Market Fund",
                "amount": Decimal("1250.50"),
                "direction": TransactionDirection.IN,
                "currency": "SGD",
            }
        ],
    )
    statement_id = statement.id
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
    holdings = holdings_response.json()["items"]
    assert len(holdings) == 1
    assert holdings[0]["asset_identifier"] == "Fullerton SGD Money Market Fund"
    assert holdings[0]["account_name"] == "Moomoo"
    # Quantity is parser-derived; market_value drives the balance-sheet valuation below.
    assert Decimal(str(holdings[0]["quantity"])) == Decimal("1")
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


async def test_statement_scoped_brokerage_import_requires_parsed_status(client, db, test_user):
    """AC-extraction.813.10/Issue #404: Position import cannot run before OCR parsing completes."""
    statement = await _seed_statement(
        db,
        test_user.id,
        file_hash="issue-404-pending",
        file_path="statements/moomoo/pending.pdf",
        original_filename="moomoo-pending.pdf",
        status=BankStatementStatus.PARSING,
    )
    statement_id = statement.id
    await db.commit()

    response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert response.status_code == 400
    assert "must be parsed" in response.text


async def test_statement_scoped_brokerage_import_explains_internal_state_transition_stall(
    client,
    db,
    test_user,
):
    """AC-extraction.813.10/Issue #409: Import errors distinguish parsed-data routing stalls."""
    statement = await _seed_statement(
        db,
        test_user.id,
        file_hash="issue-409-stalled",
        file_path="statements/moomoo/stalled.pdf",
        original_filename="moomoo-stalled.pdf",
        status=BankStatementStatus.UPLOADED,
        balance_validated=False,
        transactions=[
            {
                "txn_date": date(2026, 5, 19),
                "description": "Withdrawal",
                "amount": Decimal("500.00"),
                "direction": TransactionDirection.OUT,
            }
        ],
    )
    statement_id = statement.id
    await db.commit()

    response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert response.status_code == 400
    assert "Provider parsing has not completed" in response.text
    assert "statement must be parsed before brokerage import" in response.text


async def test_statement_scoped_brokerage_import_explains_provider_parse_failure(client, db, test_user):
    """AC-extraction.813.10/Issue #409: Import errors distinguish provider parsing failures."""
    statement = await _seed_statement(
        db,
        test_user.id,
        file_hash="issue-409-rejected",
        file_path="statements/moomoo/rejected.pdf",
        original_filename="moomoo-rejected.pdf",
        status=BankStatementStatus.REJECTED,
        validation_error="OCR provider returned invalid JSON",
    )
    statement_id = statement.id
    await db.commit()

    response = await client.post(f"/statements/{statement_id}/brokerage/import")

    assert response.status_code == 400
    assert "Provider parsing failed before brokerage import" in response.text
    assert "OCR provider returned invalid JSON" in response.text


async def test_statement_scoped_brokerage_import_returns_404_for_missing_statement(client):
    """AC-extraction.813.10/Issue #404: Statement-scoped brokerage import is user-scoped."""
    response = await client.post(f"/statements/{uuid4()}/brokerage/import")

    assert response.status_code == 404


def test_brokerage_payload_from_statement_preserves_outflows_and_empty_metadata():
    """AC-extraction.813.10/Issue #404: Statement payload keeps signed cash events deterministic."""
    statement = StatementSummary(
        id=uuid4(),
        user_id=uuid4(),
        file_hash="issue-404-futu-outflow",
        institution="Futu",
        currency="SGD",
        status=BankStatementStatus.APPROVED,
    )
    transactions = [
        AtomicTransaction(
            user_id=statement.user_id,
            txn_date=date(2026, 5, 18),
            description="Platform fee",
            amount=Decimal("4.23"),
            direction=TransactionDirection.OUT,
            reference=None,
            currency=None,
            dedup_hash="issue-404-futu-outflow-txn",
            source_documents=[],
        )
    ]

    payload = _brokerage_payload_from_statement(statement, transactions)

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
        }
    ]


async def test_AC17_33_3_broker_account_currency_is_normalized_with_usd_fallback(db, test_user):
    """AC17.33.3 (CR on #1453): an auto-created broker account normalizes the snapshot
    currency (strip/upper) and falls back to USD for a blank one — never persisting a
    non-canonical or empty currency code."""
    service = PositionService()
    lower = await service._get_or_create_broker_account(db, test_user.id, "Lower Broker", "hkd ")
    blank = await service._get_or_create_broker_account(db, test_user.id, "Blank Broker", "   ")
    await db.commit()

    assert lower.currency == "HKD"
    assert blank.currency == "USD"


async def test_AC17_4_14_brokerage_import_links_statement_to_broker_account(client, db, test_user):
    """AC17.4.14 (#1484): importing brokerage positions links the statement to the
    broker ASSET account it reconciles into, closing the source->account
    traceability gap (statement.account_id was previously left None)."""
    statement = await _seed_statement(
        db,
        test_user.id,
        file_hash="issue-1484-moomoo",
        file_path="statements/moomoo/test.pdf",
        original_filename="moomoo-2504.pdf",
        account_last4="1582",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        opening_balance=Decimal("1000.00"),
        closing_balance=Decimal("2250.50"),
        confidence_score=95,
        balance_validated=True,
        transactions=[
            {
                "txn_date": date(2026, 5, 18),
                "description": "Fullerton SGD Money Market Fund",
                "amount": Decimal("1250.50"),
                "direction": TransactionDirection.IN,
                "currency": "SGD",
            }
        ],
    )
    statement_id = statement.id
    await db.commit()
    assert statement.account_id is None  # precondition: not yet linked

    response = await client.post(f"/statements/{statement_id}/brokerage/import")
    assert response.status_code == 200, response.text

    # The statement is now anchored to the broker ASSET account the import created.
    linked = (await db.execute(select(StatementSummary).where(StatementSummary.id == statement_id))).scalar_one()
    assert linked.account_id is not None, "brokerage import must link statement.account_id to its broker account"
    # The linked account is also surfaced on the HTTP response.
    assert response.json()["account_id"] == str(linked.account_id)
    account = await db.get(Account, linked.account_id)
    assert account is not None
    assert account.type == AccountType.ASSET
    assert account.name == "Moomoo"
