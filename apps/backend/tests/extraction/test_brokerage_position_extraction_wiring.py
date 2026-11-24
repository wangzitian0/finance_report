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
from src.extraction.extension.brokerage_positions import (
    BrokeragePositionImportService,
    _parse_structured_positions,
    brokerage_currency_balances,
    looks_like_brokerage_document,
    parse_brokerage_positions,
)
from src.extraction.extension.prompts.statement import BROKERAGE_POSITIONS_PROMPT, SYSTEM_PROMPT, get_parsing_prompt
from src.extraction.extension.result_contract import build_statement_extraction_result
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing import route_brokerage_for_review_if_present
from src.extraction.orm.layer2 import AtomicPosition
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import StatementSummaryFactory
from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background
from tests.statement_ingestion import run_for


def _synthetic_moomoo_positions_payload():
    return {
        "institution": "Moomoo",
        "snapshot_date": "2026-06-30",
        "currency": "USD",
        "positions": [
            {"symbol": "ACME", "quantity": "10", "market_value": "100.00", "currency": "USD", "asset_type": "stock"},
            {"symbol": "GLOBEX", "quantity": "5", "market_value": "250.00", "currency": "USD", "asset_type": "stock"},
        ],
    }


def _synthetic_ibkr_multicurrency_payload():
    return {
        "institution": "Interactive Brokers",
        "snapshot_date": "2026-06-30",
        "positions": [
            {"symbol": "ACME", "quantity": "10", "market_value": "2124.00", "currency": "USD"},
            {"symbol": "GLOBEX", "quantity": "5", "market_value": "2276.00", "currency": "USD"},
            {"symbol": "INITECH", "quantity": "100", "market_value": "80500.00", "currency": "HKD"},
            {"symbol": "UMBRELLA", "quantity": "3", "market_value": "3810.00", "currency": "SGD"},
        ],
    }


def test_AC_B1_looks_like_brokerage_document_routes_by_filename_and_institution():
    assert all(
        looks_like_brokerage_document(filename=fn, institution=inst)
        for fn, inst in [
            ("moomoo-2506.pdf", None),
            ("statement.pdf", "Futu Securities"),
            ("activity.csv", "Interactive Brokers"),
        ]
    )
    assert not any(
        looks_like_brokerage_document(filename=fn, institution=inst)
        for fn, inst in [("dbs-statement.pdf", "DBS"), ("statement.pdf", None)]
    )
    brokerage_prompt, bank_prompt = get_parsing_prompt("Moomoo", document_kind="brokerage"), get_parsing_prompt("DBS")
    assert brokerage_prompt.startswith(BROKERAGE_POSITIONS_PROMPT) and '"positions"' in brokerage_prompt
    assert (
        bank_prompt.startswith(SYSTEM_PROMPT)
        and bank_prompt == get_parsing_prompt("DBS", document_kind="bank")
        and '"positions"' not in SYSTEM_PROMPT
    )


@pytest.mark.parametrize(
    ("institution", "filename", "payload", "expected_prefix"),
    [
        ("Moomoo", "moomoo-positions-2506.png", {"institution": "Moomoo", "positions": []}, BROKERAGE_POSITIONS_PROMPT),
        ("DBS", "dbs-statement.png", {"institution": "DBS", "transactions": []}, SYSTEM_PROMPT),
    ],
)
async def test_AC_B1_extract_financial_data_selects_prompt_by_document_kind(
    monkeypatch, institution, filename, payload, expected_prefix
):
    service, captured = ExtractionService(), {}
    service.api_key = "test-key"

    async def capture_prompt(*, messages, **kwargs):
        captured["prompt"] = messages[0]["content"][0]["text"]
        return payload

    monkeypatch.setattr(service, "_extract_json_with_model", capture_prompt)
    await service.extract_financial_data(
        file_content=b"\x89PNG\r\n",
        institution=institution,
        file_type="png",
        filename=filename,
    )
    assert captured["prompt"].startswith(expected_prefix)


def test_AC_B2_positions_prompt_payload_and_ticker_preference():
    snapshots = parse_brokerage_positions(
        {
            "institution": "Moomoo",
            "snapshot_date": "2026-06-30",
            "currency": "USD",
            "positions": [
                {
                    "symbol": "AAPL",
                    "quantity": "15",
                    "price": "212.40",
                    "market_value": "3186.00",
                    "currency": "USD",
                    "asset_type": "stock",
                }
            ],
        },
        filename="moomoo-positions-2506.pdf",
    )
    assert (
        len(snapshots),
        snapshots[0].asset_identifier,
        snapshots[0].quantity,
        snapshots[0].market_value,
        snapshots[0].currency,
    ) == (1, "AAPL", Decimal("15"), Decimal("3186.00"), "USD")
    preferred = _parse_structured_positions(
        {
            "currency": "USD",
            "positions": [
                {
                    "asset_identifier": "Synthetic Chips Incorporated",
                    "symbol": "SYNC",
                    "quantity": "100",
                    "market_value": "12345.00",
                    "currency": "USD",
                }
            ],
        },
        broker="SynthBroker",
        snapshot_date=date(2025, 6, 30),
    )
    assert (len(preferred), preferred[0].asset_identifier) == (1, "SYNC")


async def test_AC_B5_zero_position_brokerage_doc_raises_visible_review_flag(db, test_user):
    statement_id = uuid4()
    db.add(
        StatementSummaryFactory.build(
            id=statement_id,
            user_id=test_user.id,
            status=BankStatementStatus.PARSED,
            stage1_status=None,
            file_hash="b5-empty-positions",
            institution="Futu",
        )
    )
    await db.commit()
    statement = await db.get(StatementSummary, statement_id)
    await route_brokerage_for_review_if_present(
        summary=statement,
        db=db,
        user_id=test_user.id,
        filename="futu-empty.pdf",
        institution="Futu",
        payload={"institution": "Futu", "positions": []},
    )
    db.expire_all()
    refreshed = await db.get(StatementSummary, statement_id)
    assert (
        refreshed is not None
        and refreshed.stage1_status == Stage1Status.PENDING_REVIEW
        and refreshed.validation_error
        and "no positions detected" in refreshed.validation_error
    )


async def test_AC_B4_AC_B6_moomoo_positions_table_extracts_and_imports(client, db, test_user, monkeypatch):
    fixture, statement_id, user_id, file_hash = (
        _synthetic_moomoo_positions_payload(),
        uuid4(),
        test_user.id,
        "b4-b6-moomoo-positions-table",
    )
    db.add(
        StatementSummaryFactory.build(
            id=statement_id,
            user_id=user_id,
            status=BankStatementStatus.PARSING,
            file_hash=file_hash,
            institution="Moomoo",
        )
    )
    await db.commit()

    async def fake_parse_document(*args, **kwargs):
        source, session = args[1], kwargs["db"]
        summary = await session.get(StatementSummary, statement_id)
        summary.institution, summary.currency, summary.status, summary.confidence_score, summary.balance_validated = (
            "Moomoo",
            "USD",
            BankStatementStatus.PARSED,
            90,
            True,
        )
        summary.currency_balances = [{"currency": "USD", "opening": "350.00", "closing": "350.00"}]
        res = build_statement_extraction_result(
            source=source,
            file_type="pdf",
            statement=summary,
            transactions=[],
            provider_payload=fixture,
            model="fixture-model",
            provider="fixture-provider",
            method=ExtractionMethod.GOLDEN_FIXTURE,
            is_brokerage=True,
            evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
            positions=parse_brokerage_positions(fixture, filename=source.filename, institution="Moomoo"),
        )
        meta = {"statement_extraction_result": res.to_payload()}
        summary.extraction_metadata = meta
        doc = UploadedDocument(
            user_id=user_id,
            file_path="statements/moomoo-positions.pdf",
            file_hash=file_hash,
            original_filename="moomoo-positions-2506.pdf",
            document_type=DocumentType.BROKERAGE_STATEMENT,
            extraction_metadata=meta,
        )
        session.add(doc)
        await session.flush()
        summary.uploaded_document_id = doc.id
        await session.flush()
        return [res]

    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.ExtractionService.parse_documents", fake_parse_document
    )
    await parse_statement_background(
        job=ParseJob(
            statement_id=statement_id,
            run_id=await run_for(db, statement_id),
            filename="moomoo-positions-2506.pdf",
            institution="Moomoo",
            user_id=user_id,
            account_id=None,
            file_hash=file_hash,
            storage_key="statements/moomoo-positions.pdf",
        ),
        content=b"%PDF-1.7",
        session_maker=create_session_maker_from_db(db),
    )
    db.expire_all()
    refreshed = await db.get(StatementSummary, statement_id)
    assert len((await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()) == 0
    assert refreshed is not None and (refreshed.status, refreshed.stage1_status, refreshed.validation_error) == (
        BankStatementStatus.PARSED,
        Stage1Status.PENDING_REVIEW,
        None,
    )

    import_response = await client.post("/portfolio/brokerage-imports", json={"statement_id": str(statement_id)})
    assert import_response.status_code == 200, import_response.text
    db.expire_all()
    by_id = {
        row.asset_identifier: row
        for row in (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()
    }
    assert len(by_id) == len(fixture["positions"])
    for spec in fixture["positions"]:
        row = by_id[spec["symbol"]]
        assert (row.market_value, row.quantity, row.currency, row.snapshot_date) == (
            Decimal(spec["market_value"]),
            Decimal(spec["quantity"]),
            spec["currency"],
            date(2026, 6, 30),
        )


async def test_AC_B6_positions_payload_imports_via_service(db, test_user):
    fixture = _synthetic_moomoo_positions_payload()
    res = await BrokeragePositionImportService().import_positions(
        db,
        user_id=test_user.id,
        payload=fixture,
        filename="moomoo-positions-2506.pdf",
        source_document_id="doc-moomoo-positions",
        reconcile=False,
    )
    await db.commit()
    rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    assert (res.broker, res.parsed_positions, res.created_atomic_positions, len(rows)) == (
        "Moomoo",
        len(fixture["positions"]),
        len(fixture["positions"]),
        len(fixture["positions"]),
    )
    assert sum((r.market_value for r in rows), Decimal("0")) == sum(
        (Decimal(p["market_value"]) for p in fixture["positions"]), Decimal("0")
    )


async def test_AC_B3_multicurrency_brokerage_and_nav_self_check(test_user, monkeypatch):
    payload = _synthetic_ibkr_multicurrency_payload()
    assert brokerage_currency_balances(payload, filename="ibkr-multicurrency-2506.pdf") == []

    service = ExtractionService()
    service.extract_financial_data = AsyncMock(return_value=payload)
    res = await service.parse_document(
        DocumentSource.resolve(path=Path("ibkr-multicurrency-2506.pdf"), content=b"%PDF-1.7"),
        institution="Interactive Brokers",
        user_id=test_user.id,
    )
    assert (
        res.transactions,
        res.evidence_type,
        res.period_start,
        res.period_end,
        res.balances,
        res.missing_required_facts,
    ) == ((), StatementEvidenceType.POSITION_SNAPSHOT, date(2026, 6, 30), date(2026, 6, 30), (), ())

    nav_payload = {
        **payload,
        "balances": [
            {"currency": "USD", "opening": "4400.00", "closing": "4400.00"},
            {"currency": "HKD", "opening": "80500.00", "closing": "80500.00"},
            {"currency": "SGD", "opening": "3810.00", "closing": "3810.00"},
        ],
    }
    service.extract_financial_data = AsyncMock(return_value=nav_payload)
    monkeypatch.setattr(
        "src.extraction.extension.service.validate_balance_per_currency",
        lambda _e: {
            "balance_valid": False,
            "balance_computable": True,
            "per_currency": [
                {"currency": "USD", "balance_valid": False, "expected_closing": "4400.00", "actual_closing": "4000.00"},
                {"currency": "HKD", "balance_valid": True},
            ],
        },
    )
    nav_res = await service.parse_document(
        DocumentSource.resolve(path=Path("ibkr-multicurrency-2506.pdf"), content=b"%PDF-1.7"),
        institution="Interactive Brokers",
        user_id=test_user.id,
    )
    assert (len(nav_res.balances), nav_res.balance_validated, bool(nav_res.review_reasons)) == (3, False, True)
    assert "USD" in nav_res.review_reasons[0] and "self-check failed" in nav_res.review_reasons[0].lower()


@pytest.mark.parametrize(
    ("filename", "institution"),
    [
        ("fidelity_brokerage_sample.pdf", None),
        ("schwab_brokerage_sample.pdf", "Charles Schwab & Co., Inc."),
        ("pershing_brokerage_sample.pdf", "Pershing LLC"),
    ],
)
def test_public_us_brokerages_route_through_brokerage_prompt(filename, institution):
    assert looks_like_brokerage_document(filename=filename, institution=institution)


async def test_text_layer_positions_short_circuit_without_vision_fallback(monkeypatch):
    from io import BytesIO
    from unittest.mock import AsyncMock, MagicMock

    from reportlab.pdfgen import canvas

    from src.config import settings

    monkeypatch.setattr(settings, "ai_provider", "zai")
    service = ExtractionService()
    service.api_key = "test-key"
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(72, 720, "Fidelity Brokerage Statement FXAIX Market Value 1500.00")
    pdf.showPage()
    pdf.drawString(72, 720, "Fidelity Statement Page 2 Total Holdings 1500.00")
    pdf.showPage()
    pdf.save()
    pdf_bytes = buffer.getvalue()

    mock_extract = AsyncMock(
        return_value={
            "institution": "Fidelity",
            "positions": [{"symbol": "FXAIX", "quantity": "10", "market_value": "1500.00", "currency": "USD"}],
            "transactions": [],
        }
    )
    monkeypatch.setattr(service, "_extract_json_with_model", mock_extract)
    vision_spy = MagicMock(side_effect=AssertionError("should not invoke vision fallback when text positions exist"))
    monkeypatch.setattr(service, "_build_vision_media_payload_batches", vision_spy)

    result = await service.extract_financial_data(
        pdf_bytes, institution="Fidelity", file_type="pdf", filename="fidelity_brokerage_sample.pdf"
    )
    assert len(result["positions"]) == 1
    assert mock_extract.await_count == 1
    vision_spy.assert_not_called()
