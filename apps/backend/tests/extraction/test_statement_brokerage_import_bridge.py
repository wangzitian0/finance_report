from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.database import create_session_maker_from_db
from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    DocumentType,
    ExtractionMethod,
    ParseJob,
    Stage1Status,
    StatementEvidenceType,
    UploadedDocument,
)
from src.extraction.base.result import (
    ExtractedTransactionFact,
    SourceProvenance,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.extension import statement_parsing
from src.extraction.extension.brokerage_positions import looks_like_brokerage_payload, parse_brokerage_positions
from src.extraction.extension.brokerage_statement_payload import (
    _enrich_brokerage_payload_from_statement,
    _extract_brokerage_payload_from_metadata,
)
from src.extraction.extension.prompts.statement import get_parsing_prompt
from src.extraction.extension.result_contract import build_statement_extraction_result
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_parsing import _count_brokerage_positions, route_brokerage_for_review_if_present
from src.extraction.orm.layer2 import AtomicPosition, AtomicTransaction, TransactionDirection
from src.extraction.orm.statement_summary import StatementSummary
from src.portfolio.orm.portfolio import ManagedPosition
from tests.factories import StatementSummaryFactory
from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background, run_for

_BRIDGE_ASSET = "BRIDGE_TEST_STOCK"


def _parsed_stmt(user_id, file_hash: str) -> StatementSummary:
    return StatementSummaryFactory.build(
        user_id=user_id,
        file_hash=file_hash,
        institution="Moomoo",
        account_last4="1234",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 18),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.PARSED,
        confidence_score=90,
        balance_validated=True,
    )


def _brokerage_payload(*, date_str: bool = False) -> dict:
    return {
        "institution": "Moomoo",
        "period_start": "2026-05-01",
        "period_end": "2026-05-18",
        "statement": {"period_end": "2026-05-18", "currency": "SGD"},
        "positions": [
            {
                "symbol": _BRIDGE_ASSET,
                "snapshot_date": "2026-05-18" if date_str else date(2026, 5, 18),
                "quantity": "10",
                "market_value": "1900.25",
                "currency": "SGD",
                "asset_type": "stock",
                "sector": "Technology",
                "geography": "US",
            }
        ],
    }


def _brokerage_result(source: DocumentSource, summary: StatementSummary, payload: dict):
    return build_statement_extraction_result(
        source=source,
        file_type="pdf",
        statement=summary,
        transactions=[],
        provider_payload=payload,
        model="fixture-model",
        provider="fixture-provider",
        method=ExtractionMethod.GOLDEN_FIXTURE,
        is_brokerage=True,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        positions=parse_brokerage_positions(payload, filename=source.filename, institution=summary.institution),
    )


def test_looks_like_brokerage_payload_detection_enrichment_and_prompt():
    assert (
        not looks_like_brokerage_payload({"positions": []}, filename="unknown.pdf")
        and looks_like_brokerage_payload(
            {"statement": {"holdings": []}}, filename="statement.pdf", institution="Interactive Brokers"
        )
        and not looks_like_brokerage_payload(
            {"institution": "DBS", "transactions": []}, filename="dbs-statement.pdf", institution="DBS"
        )
    )
    assert (
        _count_brokerage_positions({"positions": [{}, {}]}),
        _count_brokerage_positions({"statement": {"holdings": [{}]}}),
        _count_brokerage_positions({"statement": {"positions": [{}, {}, {}]}}),
        _count_brokerage_positions({}),
        _count_brokerage_positions({"statement": {"holdings": "unstructured"}}),
    ) == (2, 1, 3, None, None)
    assert (
        parse_brokerage_positions(
            {
                "institution": "Moomoo",
                "transactions": [{"raw_text": "Subscription X FULLERTON SGD CASH FUND SGD 2026/05/18 X . . ."}],
            },
            filename="moomoo-statement.pdf",
        )
        == []
    )

    res = StatementExtractionResult.create(
        producer_version="extractor@brokerage-test",
        source_content_digest="c" * 64,
        source_type=StatementSourceType.BROKERAGE,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        statement_currency="SGD",
        institution="Moomoo",
        account_last4="1582",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        balances=(),
        transactions=(
            ExtractedTransactionFact(
                fact_id="moomoo-txn-1",
                transaction_date=date(2026, 5, 18),
                description="Fullerton SGD Money Market Fund",
                amount=Decimal("1250.50"),
                direction="IN",
                currency="SGD",
                balance_after=None,
                confidence=Decimal("0.95"),
            ),
        ),
        positions=(),
        confidence=Decimal("0.95"),
        balance_validated=None,
        warnings=(),
        review_reasons=(),
        provenance=SourceProvenance(
            intake_mode="pdf",
            method=ExtractionMethod.GOLDEN_FIXTURE,
            provider="fixture-provider",
            model="fixture-model-v1",
        ),
    )
    payload = _extract_brokerage_payload_from_metadata({"statement_extraction_result": res.to_payload()})
    snaps = parse_brokerage_positions(payload, filename="moomoo-2605.pdf")
    assert payload is not None and (
        payload["positions"],
        payload["statement"]["currency"],
        len(payload["transactions"]),
        payload["transactions"] == payload["events"],
        len(snaps),
        snaps[0].asset_identifier,
        snaps[0].market_value,
    ) == ([], "SGD", 1, True, 1, "Fullerton SGD Money Market Fund", Decimal("1250.50"))

    stmt = StatementSummaryFactory.build(
        institution="Moomoo",
        currency="SGD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        status=BankStatementStatus.PARSED,
    )
    txn = AtomicTransaction(
        user_id=stmt.user_id,
        txn_date=date(2026, 5, 18),
        description="Fullerton SGD Money Market Fund",
        amount=Decimal("1250.50"),
        direction=TransactionDirection.IN,
        currency="SGD",
        dedup_hash="d" * 64,
        source_documents=[],
    )
    enriched = _enrich_brokerage_payload_from_statement({"positions": []}, stmt, [txn])
    prompt = get_parsing_prompt(document_kind="brokerage").lower()
    assert (
        enriched["transactions"] == enriched["events"]
        and parse_brokerage_positions(enriched, filename="moomoo-fallback.pdf")[0].asset_identifier
        == "Fullerton SGD Money Market Fund"
    )
    assert "extract both" in prompt and "no cash transactions occurred" in prompt


@pytest.mark.parametrize(
    (
        "payload",
        "institution",
        "filename",
        "expected_txns",
        "expected_pos_len",
        "expected_reason",
        "expected_valid",
        "raises_match",
    ),
    [
        (_brokerage_payload(), "Moomoo", "moomoo-positions.pdf", 0, 1, None, None, None),
        (
            {
                "institution": "Moomoo",
                "transactions": [
                    {"raw_text": "FULLERTON 100"},
                    {"date": "bad", "amount": "10.00", "description": "x"},
                    {"date": "2026-05-18", "amount": "bad", "description": "y"},
                ],
            },
            "Moomoo",
            "moomoo-statement.pdf",
            0,
            0,
            None,
            None,
            "Transaction missing",
        ),
        (
            {
                "institution": "Moomoo",
                "account_last4": "1582",
                "currency": "SGD",
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
                "opening_balance": "10000.00",
                "closing_balance": "10500.00",
                "transactions": [
                    {
                        "date": "2026-05-18",
                        "description": "Fullerton",
                        "amount": "1000.00",
                        "direction": "IN",
                        "currency": "SGD",
                        "balance_after": "11000.00",
                    },
                    {
                        "date": "2026-05-19",
                        "description": "Withdrawal",
                        "amount": "-500.00",
                        "direction": "OUT",
                        "currency": "SGD",
                        "balance_after": "10500.00",
                    },
                ],
            },
            "Moomoo",
            "moomoo-statement.pdf",
            2,
            0,
            None,
            True,
            None,
        ),
        (
            {
                "institution": "Moomoo",
                "currency": "SGD",
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
                "opening_balance": "10000.00",
                "closing_balance": "9500.00",
                "transactions": [
                    {
                        "date": "2026-05-19",
                        "description": "Withdrawal",
                        "amount": "500.00",
                        "direction": "DEBIT",
                        "currency": "SGD",
                    }
                ],
            },
            "Moomoo",
            "moomoo-statement.pdf",
            1,
            0,
            None,
            True,
            None,
        ),
        (
            {
                "institution": "Moomoo",
                "currency": "SGD",
                "period_start": "2026-05-01",
                "period_end": "2026-05-31",
                "opening_balance": "0.00",
                "closing_balance": "0.00",
                "transactions": [
                    {
                        "date": "2026-05-18",
                        "description": "Fullerton",
                        "amount": "1250.50",
                        "direction": "IN",
                        "currency": "SGD",
                    }
                ],
                "positions": [
                    {
                        "symbol": "Fullerton",
                        "quantity": "1250.50",
                        "market_value": "1250.50",
                        "currency": "SGD",
                        "asset_type": "money_market",
                    }
                ],
            },
            "Moomoo",
            "moomoo-statement.pdf",
            1,
            1,
            "Balance mismatch: expected 1250.50, got 0.00",
            False,
            None,
        ),
        (
            {
                "institution": "Futu",
                "currency": "HKD",
                "positions": [{"symbol": "01810", "quantity": "100", "market_value": "5500.00", "currency": "HKD"}],
            },
            "Futu",
            "futu-positions.pdf",
            0,
            1,
            None,
            None,
            None,
        ),
        (
            {
                "institution": "Futu",
                "currency": "USD",
                "period_start": "2025-01-01",
                "period_end": "2025-01-31",
                "positions": [],
                "transactions": [],
            },
            "Futu",
            "futu_empty.pdf",
            0,
            0,
            "no transactions or holdings in recognizable format",
            None,
            None,
        ),
    ],
)
async def test_parse_document_brokerage_payload_variants(
    payload, institution, filename, expected_txns, expected_pos_len, expected_reason, expected_valid, raises_match
):
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=payload)
    source = DocumentSource.resolve(path=Path(filename), content=b"%PDF-1.7")
    if raises_match:
        with pytest.raises(ExtractionError, match=raises_match):
            await service.parse_document(source, institution=institution, user_id=uuid4())
        return
    result = await service.parse_document(source, institution=institution, user_id=uuid4())
    assert (len(result.transactions), len(result.positions), result.balance_validated) == (
        expected_txns,
        expected_pos_len,
        expected_valid,
    ) and (
        not expected_reason or any(expected_reason in r.lower() or expected_reason in r for r in result.review_reasons)
    )


async def test_route_brokerage_for_review_paths(db, test_user, monkeypatch):
    uid, bank_stmt = test_user.id, _parsed_stmt(test_user.id, "bank-hash")
    bank_stmt.stage1_status = None
    await route_brokerage_for_review_if_present(
        summary=bank_stmt,
        db=db,
        user_id=uid,
        filename="dbs.pdf",
        institution="DBS",
        payload={"institution": "DBS", "transactions": []},
    )
    assert (bank_stmt.validation_error, bank_stmt.stage1_status) == (None, None)

    empty_id = uuid4()
    db.add(
        StatementSummaryFactory.build(
            id=empty_id,
            user_id=uid,
            status=BankStatementStatus.PARSED,
            stage1_status=None,
            file_hash="futu-empty-hash",
            institution="Futu",
        )
    )
    await db.commit()
    empty_stmt = await db.get(StatementSummary, empty_id)
    await route_brokerage_for_review_if_present(
        summary=empty_stmt,
        db=db,
        user_id=uid,
        filename="futu-empty.pdf",
        institution="Futu",
        payload={"institution": "Futu", "positions": []},
    )
    db.expire_all()
    refreshed = await db.get(StatementSummary, empty_id)
    assert (
        refreshed is not None
        and refreshed.stage1_status == Stage1Status.PENDING_REVIEW
        and "no positions detected" in (refreshed.validation_error or "")
    )

    nested_stmt, events = _parsed_stmt(uid, "nested-broker-hash"), []
    db.add(nested_stmt)
    await db.commit()
    monkeypatch.setattr(statement_parsing.logger, "info", lambda ev, **kw: events.append((ev, kw)))
    await route_brokerage_for_review_if_present(
        summary=nested_stmt,
        db=db,
        user_id=uid,
        filename="ibkr-statement.pdf",
        institution=None,
        payload={"statement": {"institution": "Interactive Brokers", "positions": [{"symbol": "AAPL"}]}},
    )
    assert [kw for ev, kw in events if ev == "statement.brokerage_review_routing.started"][0][
        "broker"
    ] == "Interactive Brokers" and nested_stmt.stage1_status == Stage1Status.PENDING_REVIEW


@pytest.mark.parametrize("with_import", [True, False])
async def test_parse_statement_background_brokerage_review_and_import(client, db, test_user, monkeypatch, with_import):
    sid, uid, fhash = uuid4(), test_user.id, f"brokerage-{with_import}"
    db.add(
        StatementSummaryFactory.build(
            id=sid, user_id=uid, status=BankStatementStatus.PARSING, file_hash=fhash, institution="Moomoo"
        )
    )
    await db.commit()

    async def fake_parse_document(*args, **kwargs):
        session = kwargs["db"]
        summary, parsed = await session.get(StatementSummary, sid), _parsed_stmt(uid, fhash)
        for f in (
            "institution",
            "account_last4",
            "currency",
            "period_start",
            "period_end",
            "opening_balance",
            "closing_balance",
            "status",
            "confidence_score",
            "balance_validated",
        ):
            setattr(summary, f, getattr(parsed, f))
        summary.validation_error = None if with_import else "existing parser note"
        res = _brokerage_result(args[1], summary, _brokerage_payload(date_str=True))
        summary.extraction_metadata = {"statement_extraction_result": res.to_payload()}
        if with_import:
            doc = UploadedDocument(
                user_id=uid,
                file_path="statements/moomoo.pdf",
                file_hash=fhash,
                original_filename="moomoo-positions.pdf",
                document_type=DocumentType.BANK_STATEMENT,
            )
            session.add(doc)
            await session.flush()
            summary.uploaded_document_id = doc.id
        await session.flush()
        return res

    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.ExtractionService.parse_document", fake_parse_document
    )
    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.StorageService.generate_presigned_url",
        lambda *_a, **_kw: "https://example.com/moomoo.pdf",
    )
    await parse_statement_background(
        job=ParseJob(
            statement_id=sid,
            run_id=await run_for(db, sid),
            filename="moomoo-positions.pdf",
            institution="Moomoo",
            user_id=uid,
            account_id=None,
            file_hash=fhash,
            storage_key="statements/moomoo.pdf",
            model=None,
        ),
        content=b"%PDF-1.7",
        session_maker=create_session_maker_from_db(db),
    )
    db.expire_all()
    refreshed = await db.get(StatementSummary, sid)
    assert (
        refreshed.status,
        refreshed.stage1_status,
        len((await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == uid))).scalars().all()),
    ) == (BankStatementStatus.PARSED, Stage1Status.PENDING_REVIEW, 0)
    if not with_import:
        assert refreshed.validation_error == "existing parser note"
        provenance = (refreshed.extraction_metadata or {}).get("artifact_provenance")
        assert isinstance(provenance, dict)
        assert provenance["resolved_model_id"] == "fixture-model"
        assert len(provenance["artifact_dependency_digest"]) == 64
        return
    assert (await client.get("/portfolio/holdings", params={"as_of_date": "2026-05-18"})).json()["items"] == [] and (
        await client.post("/portfolio/brokerage-imports", json={"statement_id": str(sid)})
    ).status_code == 200
    db.expire_all()
    managed, holdings, bs = (
        (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == uid))).scalars().all(),
        (await client.get("/portfolio/holdings", params={"as_of_date": "2026-05-18"})).json()["items"],
        (await client.get("/reports/balance-sheet", params={"as_of_date": "2026-05-18", "currency": "SGD"})).json(),
    )
    assert (
        len(managed),
        managed[0].asset_identifier,
        managed[0].quantity,
        holdings[0]["account_name"],
        Decimal(str(holdings[0]["market_value"])),
        Decimal(str(bs["net_worth_adjustment_gain_loss"])),
        bs["is_balanced"],
    ) == (1, _BRIDGE_ASSET, Decimal("10"), "Moomoo", Decimal("1900.25"), Decimal("1900.25"), True)
