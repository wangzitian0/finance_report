import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.extraction import (
    BankStatementStatus,
    DocumentType,
    ExtractedPositionFact,
    ExtractionMethod,
    SourceProvenance,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
    TransactionDirection,
    UploadedDocument,
    parse_brokerage_csv_payload,
)
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
from src.extraction.orm.layer2 import AssetType, AtomicPosition, AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType
from src.portfolio import ManagedPosition, PositionService
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
    doc = UploadedDocument(
        user_id=user_id,
        file_path=file_path,
        file_hash=file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
        extraction_metadata=extraction_metadata,
    )
    db.add(doc)
    await db.flush()
    stmt = StatementSummary(
        user_id=user_id,
        uploaded_document_id=doc.id,
        file_hash=file_hash,
        institution=institution,
        currency=currency,
        status=status,
        extraction_metadata=extraction_metadata,
        **summary_kwargs,
    )
    db.add(stmt)
    await db.flush()
    db.add_all(
        [
            AtomicTransaction(
                user_id=user_id,
                txn_date=t["txn_date"],
                description=t["description"],
                amount=t["amount"],
                direction=t["direction"],
                reference=t.get("reference"),
                currency=t.get("currency", currency),
                dedup_hash=uuid4().hex + uuid4().hex,
                source_documents=[{"doc_id": str(doc.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
            )
            for t in transactions or []
        ]
    )
    await db.flush()
    return stmt


def test_detect_broker_and_value_coercion_helpers():
    assert (
        detect_broker(filename="moomoo-2504.pdf", institution=None, text=""),
        detect_broker(filename="statement.pdf", institution="Futu Securities", text=""),
        detect_broker(filename="activity.csv", institution=None, text="Interactive Brokers LLC"),
        _clean_decimal(None),
        _clean_decimal("N/A"),
        _clean_decimal("1,234.56"),
        _clean_decimal(Decimal("7.89")),
        _clean_decimal("not-a-number"),
        _parse_date(None),
        _parse_date("UNKNOWN"),
        _parse_date("2026-05").isoformat(),
        _parse_date("2026/05/18").isoformat(),
        _parse_date("bad-date"),
        _payload_currency({}, default="sgd"),
        _statement_date({"snapshot_date": "2026-06-01"}).isoformat(),
        _asset_type("fund"),
        _asset_type("money_market"),
        _asset_type("equity"),
        _asset_type("etf"),
        _asset_type("unsupported"),
    ) == (
        "Moomoo",
        "Futu",
        "Interactive Brokers",
        None,
        None,
        Decimal("1234.56"),
        Decimal("7.89"),
        None,
        None,
        None,
        "2026-05-31",
        "2026-05-18",
        None,
        "SGD",
        "2026-06-01",
        AssetType.MUTUAL_FUND,
        AssetType.MUTUAL_FUND,
        AssetType.STOCK,
        AssetType.ETF,
        None,
    )
    req = BrokerageImportRequest(payload={"positions": []}, filename="ibkr.csv", source_document_id="doc-1")
    resp = BrokerageImportResponse(
        broker="Interactive Brokers",
        parsed_positions=0,
        created_atomic_positions=0,
        existing_atomic_positions=0,
        reconcile_created=0,
        reconcile_updated=0,
        reconcile_disposed=0,
        skipped=0,
    )
    assert (req.filename, req.source_document_id, resp.created_atomic_positions) == ("ibkr.csv", "doc-1", 0)


@pytest.mark.parametrize(
    ("filename", "payload", "expected"),
    [
        (
            "moomoo-2504.pdf",
            {
                "institution": "Moomoo",
                "statement": {"period_end": "2025-04-30", "currency": "SGD"},
                "events": [{"description": "ACME Money Market Fund", "amount": "100.00"}],
            },
            (
                "Moomoo",
                "ACME Money Market Fund",
                "2025-04-30",
                Decimal("1"),
                Decimal("100.00"),
                "SGD",
                AssetType.MUTUAL_FUND,
                None,
                None,
            ),
        ),
        (
            "activity.csv",
            {
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
            },
            (
                "Interactive Brokers",
                "SG9999000001",
                "2026-05-31",
                Decimal("1234.5"),
                Decimal("9876.54"),
                "USD",
                AssetType.MUTUAL_FUND,
                "Cash",
                "SG",
            ),
        ),
        (
            "ibkr.csv",
            {
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
            },
            ("IBKR UK", "VWRA", "2026-06-02", Decimal("3"), Decimal("360.12"), "USD", AssetType.ETF, None, None),
        ),
        (
            "moomoo-statement.pdf",
            {
                "statement": {"period_end": "2026/05/18", "currency": "SGD"},
                "events": [
                    {
                        "raw_text": "Subscription 0001 Fullerton SGD Cash Fund SGD 2026/05/18 settled 1.0000 1250.50 1250.50"
                    }
                ],
            },
            (
                "Moomoo",
                "Fullerton SGD Cash Fund",
                "2026-05-18",
                Decimal("1250.50"),
                Decimal("1250.50"),
                "SGD",
                AssetType.MUTUAL_FUND,
                None,
                None,
            ),
        ),
        (
            "synthetic-margin-history.csv",
            {
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
            },
            (
                "Moomoo",
                "PONY",
                "2026-01-02",
                Decimal("36"),
                Decimal("358.01"),
                "USD",
                AssetType.STOCK,
                "Technology",
                "US",
            ),
        ),
        (
            "moomoo-margin.csv",
            {
                "institution": "Moomoo",
                "statement": {"period_end": "2026-01-31", "currency": "USD"},
                "margin_history_rows": [
                    {
                        "Side": "BUY",
                        "Symbol": "PONY",
                        "Fill Qty": "30",
                        "Fill Amount": "300.00",
                        "Currency": "USD",
                        "Sector": "Technology",
                        "Geography": "US",
                    },
                    {"Side": "SELL", "Symbol": "PONY", "Fill Qty": "10", "Fill Amount": "150.00", "Currency": "USD"},
                    {"Side": "BUY", "Symbol": "CLOSED", "Fill Qty": "15", "Fill Amount": "150.00", "Currency": "USD"},
                    {"Side": "SELL", "Symbol": "CLOSED", "Fill Qty": "15", "Fill Amount": "180.00", "Currency": "USD"},
                ],
            },
            (
                "Moomoo",
                "PONY",
                "2026-01-31",
                Decimal("20"),
                Decimal("200.00"),
                "USD",
                AssetType.STOCK,
                "Technology",
                "US",
            ),
        ),
    ],
)
def test_parse_brokerage_positions_valid_cases(filename, payload, expected):
    snaps = parse_brokerage_positions(payload, filename=filename)
    assert len(snaps) == 1
    s = snaps[0]
    assert (
        s.broker,
        s.asset_identifier,
        s.snapshot_date.isoformat(),
        s.quantity,
        s.market_value,
        s.currency,
        s.asset_type,
        s.sector,
        s.geography,
    ) == expected


@pytest.mark.parametrize(
    ("filename", "payload"),
    [
        (
            "futu-2506.pdf",
            {
                "institution": "Futu",
                "statement": {"period_end": "2025-06-30", "currency": "HKD"},
                "events": [{"description": "Stock and options valuation", "amount": "100.00"}],
            },
        ),
        (
            "futu.pdf",
            {
                "statement": {"period_end": "2026-05-18", "currency": "HKD"},
                "events": [
                    "not a dict",
                    {"description": "Cash balance", "amount": "9999.00"},
                    {"description": "Stock valuation", "amount": "UNKNOWN"},
                    {"description": "Stock valuation", "amount": "100.00"},
                    {"description": "Stock valuation", "amount": "-1.41"},
                    {"description": "Stock and options value", "amount": "250.00"},
                ],
            },
        ),
        (
            "moomoo.pdf",
            {
                "statement": {"period_end": "2026-05-18", "currency": "SGD"},
                "events": [
                    "not a dict",
                    {"description": "Money Market Fund rebate", "amount": "UNKNOWN"},
                    {"description": "Money Market Fund redemption", "amount": "-10.00"},
                    {"description": "Money Market Fund dividend", "amount": "25.00"},
                    {"description": "Money Market Fund transfer", "amount": "100.00", "direction": "OUT"},
                    {"raw_text": "Subscription 0001 Bad Quantity Fund SGD 2026/05/18 settled 1.0000 UNKNOWN 1250.50"},
                    {"raw_text": "Subscription 0001 Zero Value Fund SGD 2026/05/18 settled 1.0000 10.00 0.00"},
                    {"raw_text": "Subscription 0001 Zero Quantity Fund SGD 2026/05/18 settled 1.0000 0.00 10.00"},
                    {"description": "Cash transfer", "amount": "100.00"},
                ],
            },
        ),
        (
            "futu.pdf",
            {
                "statement": {"period_end": "2026-05-18", "currency": "HKD"},
                "events": [{"description": "Cash balance", "amount": "999.00"}],
            },
        ),
        ("unknown.pdf", {"positions": [{"symbol": "BAD", "quantity": "UNKNOWN", "market_value": None}]}),
        (
            "futu.pdf",
            {
                "statement": {"period_end": "2026-05-18", "currency": "SGD"},
                "events": [
                    {"description": "Platform fee", "amount": "-1.41"},
                    {"description": "Platform fee", "amount": "1.41", "direction": "OUT"},
                    {"description": "Securities transfer", "amount": "100.00", "direction": "OUT"},
                    {"description": "Dividend income", "amount": "50.00", "direction": "IN"},
                    {"description": "腾讯控股 股息", "amount": "120.00", "direction": "IN"},
                    {"description": "Brokerage cash interest", "amount": "5.11", "direction": "IN"},
                    {"description": "Stock valuation", "amount": "0.00"},
                    {"description": "Stock valuation", "amount": "-1.41"},
                ],
            },
        ),
    ],
)
def test_parse_brokerage_positions_ignores_non_position_events(filename, payload):
    assert parse_brokerage_positions(payload, filename=filename) == []


def test_brokerage_payload_from_statement_preserves_outflow_sign():
    stmt = StatementSummary(
        id=uuid4(),
        user_id=uuid4(),
        file_hash="issue-404-futu-outflow",
        institution="Futu",
        currency="SGD",
        status=BankStatementStatus.APPROVED,
    )
    txns = [
        AtomicTransaction(
            user_id=stmt.user_id,
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
    payload = _brokerage_payload_from_statement(stmt, txns)
    assert (
        payload["institution"],
        payload["statement"]["period_end"],
        payload["statement"]["currency"],
        payload["transactions"] == payload["events"],
        payload["transactions"],
    ) == (
        "Futu",
        None,
        "SGD",
        True,
        [
            {
                "date": "2026-05-18",
                "description": "Platform fee",
                "amount": "-4.23",
                "currency": "SGD",
                "raw_text": "Platform fee",
            }
        ],
    )


def _import_svc() -> BrokeragePositionImportService:
    return BrokeragePositionImportService(position_reconciler=PositionService().reconcile_positions)


async def test_import_interactive_brokers_positions_idempotently_reconciles(db, test_user):
    service = _import_svc()
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
    atomic_rows = (
        (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    )
    managed_rows = (
        (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == test_user.id))).scalars().all()
    )
    assert (
        first.created_atomic_positions,
        first.reconcile_created,
        second.created_atomic_positions,
        second.reconcile_created,
        len(atomic_rows),
        atomic_rows[0].asset_identifier,
        atomic_rows[0].sector,
        len(managed_rows),
        managed_rows[0].asset_identifier,
        managed_rows[0].quantity,
    ) == (1, 1, 0, 0, 1, "AAPL", "Technology", 1, "AAPL", Decimal("10"))


async def test_AC17_33_3_broker_account_currency_and_normalization(db, test_user):
    await _import_svc().import_positions(
        db,
        user_id=test_user.id,
        payload={
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
        },
        source_document_id="doc-futu-hkd",
    )
    pos_svc = PositionService()
    lower = await pos_svc._get_or_create_broker_account(db, test_user.id, "Lower Broker", "hkd ")
    blank = await pos_svc._get_or_create_broker_account(db, test_user.id, "Blank Broker", "   ")
    await db.commit()
    futu_acct = (
        await db.execute(
            select(Account).where(
                Account.user_id == test_user.id, Account.type == AccountType.ASSET, Account.name == "Futu"
            )
        )
    ).scalar_one()
    assert (futu_acct.currency, lower.currency, blank.currency) == ("HKD", "HKD", "USD")


async def test_AC17_34_1_brokerage_import_persists_short_positions_with_negative_market_value(db, test_user):
    payload = {
        "institution": "Interactive Brokers",
        "statement": {"period_end": "2026-05-18", "currency": "USD"},
        "positions": [
            {"symbol": "AAPL", "quantity": "10", "market_value": "1900.25", "currency": "USD", "asset_type": "stock"},
            {
                "symbol": "NIO270115P7000",
                "quantity": "-100",
                "market_value": "-27069.00",
                "currency": "USD",
                "asset_type": "stock",
            },
        ],
    }
    result = await _import_svc().import_positions(
        db, user_id=test_user.id, payload=payload, source_document_id="doc-short"
    )
    await db.commit()
    atomic_rows = (
        (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    )
    short_atomic = next(r for r in atomic_rows if r.asset_identifier == "NIO270115P7000")
    short_managed = next(
        p
        for p in (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == test_user.id)))
        .scalars()
        .all()
        if p.asset_identifier == "NIO270115P7000"
    )
    assert (
        result.parsed_positions,
        result.created_atomic_positions,
        result.skipped,
        {r.asset_identifier for r in atomic_rows},
        short_atomic.quantity < 0,
        short_atomic.market_value < 0,
        short_managed.quantity < 0,
        short_managed.cost_basis,
    ) == (2, 2, 0, {"AAPL", "NIO270115P7000"}, True, True, True, None)


async def test_AC17_4_8_brokerage_import_survives_concurrent_auto_and_manual_import(db_engine, test_user):
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
    async with sessionmaker() as auto_s, sessionmaker() as manual_s:
        auto_res = await service.import_positions(
            auto_s, user_id=test_user.id, payload=payload, source_document_id="auto-parse-doc", reconcile=False
        )
        manual_task = asyncio.create_task(
            service.import_positions(
                manual_s, user_id=test_user.id, payload=payload, source_document_id="manual-import-doc", reconcile=False
            )
        )
        await asyncio.sleep(0.2)
        await auto_s.commit()
        manual_res = await asyncio.wait_for(manual_task, timeout=5)
        await manual_s.commit()
    async with sessionmaker() as verify_s:
        positions = (
            (await verify_s.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id)))
            .scalars()
            .all()
        )
    assert (
        auto_res.created_atomic_positions,
        manual_res.created_atomic_positions,
        manual_res.existing_atomic_positions,
        len(positions),
        positions[0].asset_identifier,
    ) == (1, 0, 1, 1, "Fullerton SGD Money Market Fund")


async def test_import_empty_and_direct_endpoint_payloads(client, db, test_user):
    svc_res = await BrokeragePositionImportService().import_positions(
        db,
        user_id=test_user.id,
        payload={"institution": "Unknown Broker", "transactions": []},
        filename="unknown.pdf",
        reconcile=False,
    )
    empty_ep = await client.post(
        "/portfolio/brokerage-imports", json={"filename": "unknown.pdf", "payload": {"transactions": []}}
    )
    ok_ep = await client.post(
        "/portfolio/brokerage-imports",
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
    assert (
        (
            svc_res.broker,
            svc_res.parsed_positions,
            svc_res.created_atomic_positions,
            svc_res.existing_atomic_positions,
            svc_res.reconcile_created,
            svc_res.reconcile_updated,
            svc_res.reconcile_disposed,
        ),
        empty_ep.status_code,
        (
            empty_ep.json()["broker"],
            empty_ep.json()["parsed_positions"],
            empty_ep.json()["created_atomic_positions"],
            empty_ep.json()["reconcile_created"],
        ),
        ok_ep.status_code,
        (
            ok_ep.json()["broker"],
            ok_ep.json()["parsed_positions"],
            ok_ep.json()["created_atomic_positions"],
            ok_ep.json()["reconcile_created"],
        ),
    ) == (("Unknown Broker", 0, 0, 0, 0, 0, 0), 200, ("Unknown Broker", 0, 0, 0), 200, ("Interactive Brokers", 1, 1, 1))


@pytest.mark.parametrize("use_structured", [False, True])
async def test_statement_scoped_brokerage_import_and_account_link(client, db, test_user, use_structured):
    kwargs = {}
    if use_structured:
        ext_res = StatementExtractionResult.create(
            producer_version="extractor@brokerage-test",
            source_content_digest="b" * 64,
            source_type=StatementSourceType.BROKERAGE,
            evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
            statement_currency="SGD",
            institution="Moomoo",
            account_last4="1582",
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            balances=(),
            transactions=(),
            positions=(
                ExtractedPositionFact(
                    fact_id="moomoo-position-1",
                    symbol="Fullerton SGD Money Market Fund",
                    quantity=Decimal("1"),
                    market_value=Decimal("1250.50"),
                    currency="SGD",
                    confidence=Decimal("0.95"),
                    asset_type="money_market",
                ),
            ),
            confidence=Decimal("0.95"),
            balance_validated=None,
            warnings=(),
            review_reasons=("position import requires explicit review",),
            provenance=SourceProvenance(
                intake_mode="pdf",
                method=ExtractionMethod.GOLDEN_FIXTURE,
                provider="fixture-provider",
                model="fixture-model-v1",
            ),
        )
        kwargs = {
            "opening_balance": None,
            "closing_balance": None,
            "balance_validated": False,
            "extraction_metadata": {"statement_extraction_result": ext_res.to_payload()},
            "transactions": [],
        }
    else:
        kwargs = {
            "opening_balance": Decimal("1000.00"),
            "closing_balance": Decimal("2250.50"),
            "balance_validated": True,
            "transactions": [
                {
                    "txn_date": date(2026, 5, 18),
                    "description": "Fullerton SGD Money Market Fund",
                    "amount": Decimal("1250.50"),
                    "direction": TransactionDirection.IN,
                    "currency": "SGD",
                }
            ],
        }
    stmt = await _seed_statement(
        db,
        test_user.id,
        file_hash=f"issue-404-{use_structured}",
        file_path="statements/moomoo/test.pdf",
        original_filename="moomoo-2504.pdf",
        account_last4="1582",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        confidence_score=95,
        **kwargs,
    )
    stmt_id = stmt.id
    await db.commit()
    resp = await client.post("/portfolio/brokerage-imports", json={"statement_id": str(stmt_id)})
    data = resp.json()
    positions = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    linked = (await db.execute(select(StatementSummary).where(StatementSummary.id == stmt_id))).scalar_one()
    acct = await db.get(Account, linked.account_id)
    assert (
        resp.status_code,
        data["broker"],
        data["parsed_positions"],
        data["created_atomic_positions"],
        data["reconcile_created"],
        len(positions),
        positions[0].asset_identifier,
        positions[0].market_value,
        data["account_id"],
        acct.type,
        acct.name,
    ) == (
        200,
        "Moomoo",
        1,
        1,
        1,
        1,
        "Fullerton SGD Money Market Fund",
        Decimal("1250.50"),
        str(linked.account_id),
        AccountType.ASSET,
        "Moomoo",
    )


async def test_statement_import_flows_to_holdings_and_balance_sheet(client, db, test_user):
    stmt = await _seed_statement(
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
    await db.commit()
    imp = await client.post("/portfolio/brokerage-imports", json={"statement_id": str(stmt.id)})
    holdings_resp = await client.get("/portfolio/holdings", params={"as_of_date": "2026-05-31"})
    balance_resp = await client.get("/reports/balance-sheet", params={"as_of_date": "2026-05-31", "currency": "SGD"})
    h = holdings_resp.json()["items"][0]
    bs = balance_resp.json()
    assert (
        imp.status_code,
        (
            imp.json()["broker"],
            imp.json()["parsed_positions"],
            imp.json()["created_atomic_positions"],
            imp.json()["reconcile_created"],
        ),
        holdings_resp.status_code,
        len(holdings_resp.json()["items"]),
        (
            h["asset_identifier"],
            h["account_name"],
            Decimal(str(h["quantity"])),
            Decimal(str(h["market_value"])),
            h["currency"],
        ),
        balance_resp.status_code,
        (
            Decimal(str(bs["total_assets"])),
            Decimal(str(bs["net_worth_adjustment_gain_loss"])),
            Decimal(str(bs["equation_delta"])),
            bs["is_balanced"],
        ),
        any(
            line["name"] == "Moomoo market valuation adjustment" and Decimal(str(line["amount"])) == Decimal("1250.50")
            for line in bs["assets"]
        ),
    ) == (
        200,
        ("Moomoo", 1, 1, 1),
        200,
        1,
        ("Fullerton SGD Money Market Fund", "Moomoo", Decimal("1"), Decimal("1250.50"), "SGD"),
        200,
        (Decimal("1250.50"), Decimal("1250.50"), Decimal("0.00"), True),
        True,
    )


@pytest.mark.parametrize(
    ("status", "extra", "fragments"),
    [
        (BankStatementStatus.PARSING, {}, ["must be parsed"]),
        (
            BankStatementStatus.UPLOADED,
            {
                "balance_validated": False,
                "transactions": [
                    {
                        "txn_date": date(2026, 5, 19),
                        "description": "Withdrawal",
                        "amount": Decimal("500.00"),
                        "direction": TransactionDirection.OUT,
                    }
                ],
            },
            ["Provider parsing has not completed", "statement must be parsed before brokerage import"],
        ),
        (
            BankStatementStatus.REJECTED,
            {"validation_error": "OCR provider returned invalid JSON"},
            ["Provider parsing failed before brokerage import", "OCR provider returned invalid JSON"],
        ),
    ],
)
async def test_statement_scoped_brokerage_import_status_errors(client, db, test_user, status, extra, fragments):
    stmt = await _seed_statement(
        db,
        test_user.id,
        file_hash=f"issue-409-{status.value}",
        file_path=f"statements/moomoo/{status.value}.pdf",
        original_filename=f"moomoo-{status.value}.pdf",
        status=status,
        **extra,
    )
    await db.commit()
    resp = await client.post("/portfolio/brokerage-imports", json={"statement_id": str(stmt.id)})
    assert resp.status_code == 400
    assert all(frag in resp.text for frag in fragments)


async def test_brokerage_import_validation_404_and_json_float_guards(client):
    assert (await client.post("/portfolio/brokerage-imports", json={"statement_id": str(uuid4())})).status_code == 404
    assert (await client.post("/portfolio/brokerage-imports", json={})).status_code == 422
    assert (
        await client.post(
            "/portfolio/brokerage-imports", json={"statement_id": str(uuid4()), "payload": {"positions": []}}
        )
    ).status_code == 422
    float_resp = await client.post(
        "/portfolio/brokerage-imports",
        json={
            "filename": "ibkr.csv",
            "payload": {
                "institution": "Interactive Brokers",
                "statement": {"period_end": "2026-05-18", "currency": "USD"},
                "positions": [{"symbol": "MSFT", "quantity": 2.5, "market_value": 860.0, "currency": "USD"}],
            },
        },
    )
    str_resp = await client.post(
        "/portfolio/brokerage-imports",
        json={
            "filename": "ibkr.csv",
            "payload": {
                "institution": "Interactive Brokers",
                "statement": {"period_end": "2026-05-18", "currency": "USD"},
                "positions": [{"symbol": "MSFT", "quantity": "2", "market_value": "860.00", "currency": "USD"}],
            },
        },
    )
    assert (float_resp.status_code, "float" in str(float_resp.json()["detail"]).lower(), str_resp.status_code) == (
        422,
        True,
        200,
    )


async def test_AC_extraction_2661_1_positions_csv_with_date_column_imports_without_422(client, db, test_user):
    headers = ["Symbol", "Quantity", "Market Value", "Currency", "As-Of Date"]
    rows = [
        {"Symbol": "AAPL", "Quantity": "10", "Market Value": "1900.25", "Currency": "USD", "As-Of Date": "2026-05-15"},
        {"Symbol": "MSFT", "Quantity": "5", "Market Value": "2150.00", "Currency": "USD", "As-Of Date": "2026-05-18"},
    ]
    payload = parse_brokerage_csv_payload(headers, rows, institution="Interactive Brokers", filename="positions.csv")
    resp = await client.post("/portfolio/brokerage-imports", json={"filename": "positions.csv", "payload": payload})
    data = resp.json()
    assert (
        payload["period_start"],
        payload["period_end"],
        payload["snapshot_date"],
        payload["statement"]["period_end"],
        [p["snapshot_date"] for p in payload["positions"]],
        resp.status_code,
        data["parsed_positions"],
        data["created_atomic_positions"],
        data["reconcile_created"],
    ) == ("2026-05-15", "2026-05-18", "2026-05-18", "2026-05-18", ["2026-05-15", "2026-05-18"], 200, 2, 2, 2)
