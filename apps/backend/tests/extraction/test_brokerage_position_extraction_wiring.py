"""Producer-side wiring for brokerage POSITION extraction (issue #1139, covers #1088).

Registered ACs: AC-extraction.304.9 (AC-B1), AC-extraction.304.10 (AC-B2), AC-extraction.304.11 (AC-B5),
AC-extraction.304.12 (AC-B4/AC-B6) under EPIC-017 AC17.4.

These tests cover the producer half that was previously missing: routing a brokerage
document to a positions-emitting prompt BEFORE the model call (AC-B1), the brokerage
positions output schema and parser path (AC-B2), surfacing zero-position brokerage docs
as a visible review flag (AC-B5), and an end-to-end fixture-driven import assertion
(AC-B4/AC-B6) including the moomoo holdings-table shape for #1088.

Because real LLM calls cannot run in CI, the model output is injected by stubbing
``ExtractionService.extract_financial_data`` (the existing extraction test seam) or by
loading a recorded payload fixture, so routing + import + flag logic is asserted
deterministically without a live model.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select

from src.database import create_session_maker_from_db
from src.extraction import DocumentType, ParseJob, UploadedDocument
from src.extraction.extension.brokerage_positions import (
    BrokeragePositionImportService,
    brokerage_currency_balances,
    looks_like_brokerage_document,
    parse_brokerage_positions,
)
from src.extraction.extension.prompts.statement import (
    BROKERAGE_POSITIONS_PROMPT,
    SYSTEM_PROMPT,
    get_parsing_prompt,
)
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing import parse_statement_background, route_brokerage_for_review_if_present
from src.extraction.orm.layer2 import AtomicPosition
from src.extraction.orm.statement_enums import BankStatementStatus, Stage1Status
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import StatementSummaryFactory


def _synthetic_moomoo_positions_payload() -> dict:
    """Synthetic Moomoo holdings-table payload (no real account data).

    Mirrors the structured ``positions[]`` envelope a brokerage OCR pass emits: a
    month-end snapshot date plus one row per holding with an exact Decimal-safe
    market value. Two obviously-fake tickers drive the multi-row import assertions.
    """
    return {
        "institution": "Moomoo",
        "snapshot_date": "2026-06-30",
        "currency": "USD",
        "positions": [
            {
                "symbol": "ACME",
                "quantity": "10",
                "market_value": "100.00",
                "currency": "USD",
                "asset_type": "stock",
            },
            {
                "symbol": "GLOBEX",
                "quantity": "5",
                "market_value": "250.00",
                "currency": "USD",
                "asset_type": "stock",
            },
        ],
    }


def _synthetic_ibkr_multicurrency_payload() -> dict:
    """Synthetic multi-currency IBKR positions payload (no real account data).

    Two USD rows (2124 + 2276 = 4400), one HKD row (80500) and one SGD row (3810)
    exercise the per-currency NAV buckets without ever cross-summing into the
    meaningless 88710 scalar.
    """
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


# --------------------------------------------------------------------------- AC-B1


def test_AC_B1_looks_like_brokerage_document_routes_by_filename_and_institution():
    """AC-extraction.304.9 (AC-B1): Pre-call brokerage routing decides from filename/institution keywords."""
    assert looks_like_brokerage_document(filename="moomoo-2506.pdf", institution=None)
    assert looks_like_brokerage_document(filename="statement.pdf", institution="Futu Securities")
    assert looks_like_brokerage_document(filename="activity.csv", institution="Interactive Brokers")
    # Bank documents must NOT be routed to the brokerage prompt.
    assert not looks_like_brokerage_document(filename="dbs-statement.pdf", institution="DBS")
    assert not looks_like_brokerage_document(filename="statement.pdf", institution=None)


def test_AC_B1_get_parsing_prompt_selects_positions_prompt_for_brokerage():
    """AC-extraction.304.9/AC-extraction.304.10 (AC-B1/AC-B2): Brokerage routing selects the positions prompt; bank stays unchanged."""
    brokerage_prompt = get_parsing_prompt("Moomoo", document_kind="brokerage")
    assert brokerage_prompt.startswith(BROKERAGE_POSITIONS_PROMPT)
    assert '"positions"' in brokerage_prompt

    bank_prompt = get_parsing_prompt("DBS")
    assert bank_prompt.startswith(SYSTEM_PROMPT)
    assert bank_prompt == get_parsing_prompt("DBS", document_kind="bank")
    # The bank prompt schema must remain balance/transaction-only (no positions field).
    assert '"positions"' not in SYSTEM_PROMPT


async def test_AC_B1_extract_financial_data_uses_brokerage_prompt_before_model_call(monkeypatch):
    """AC-extraction.304.9 (AC-B1): The brokerage prompt is selected pre-call from the upload filename."""
    service = ExtractionService()
    service.api_key = "test-key"
    captured: dict[str, str] = {}

    async def capture_prompt(*, messages, models, prompt, **kwargs):
        captured["prompt"] = prompt
        return {"institution": "Moomoo", "positions": []}

    monkeypatch.setattr(service, "_extract_json_with_models", capture_prompt)

    await service.extract_financial_data(
        file_content=b"\x89PNG\r\n",
        institution="Moomoo",
        file_type="png",
        force_model="glm-4.6v",
        filename="moomoo-positions-2506.png",
    )

    assert captured["prompt"].startswith(BROKERAGE_POSITIONS_PROMPT)


async def test_AC_B1_extract_financial_data_keeps_bank_prompt_for_bank_upload(monkeypatch):
    """AC-extraction.304.9 (AC-B1): A bank upload keeps the unchanged bank prompt (no producer reroute)."""
    service = ExtractionService()
    service.api_key = "test-key"
    captured: dict[str, str] = {}

    async def capture_prompt(*, messages, models, prompt, **kwargs):
        captured["prompt"] = prompt
        return {"institution": "DBS", "transactions": []}

    monkeypatch.setattr(service, "_extract_json_with_models", capture_prompt)

    await service.extract_financial_data(
        file_content=b"\x89PNG\r\n",
        institution="DBS",
        file_type="png",
        force_model="glm-4.6v",
        filename="dbs-statement.png",
    )

    assert captured["prompt"].startswith(SYSTEM_PROMPT)


# --------------------------------------------------------------------------- AC-B2


def test_AC_B2_positions_prompt_payload_is_understood_by_consumer_parser():
    """AC-extraction.304.10 (AC-B2): positions[] emitted under the new schema flows into AtomicPosition snapshots."""
    payload = {
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
    }

    snapshots = parse_brokerage_positions(payload, filename="moomoo-positions-2506.pdf")

    assert len(snapshots) == 1
    assert snapshots[0].asset_identifier == "AAPL"
    assert snapshots[0].quantity == Decimal("15")
    assert snapshots[0].market_value == Decimal("3186.00")
    assert snapshots[0].currency == "USD"


# --------------------------------------------------------------------------- AC-B5


async def test_AC_B5_zero_position_brokerage_doc_raises_visible_review_flag(db, test_user):
    """AC-extraction.304.11 (AC-B5): A brokerage doc with zero positions is surfaced as a review flag, not buried."""
    statement_id = uuid4()
    statement = StatementSummaryFactory.build(
        id=statement_id,
        user_id=test_user.id,
        status=BankStatementStatus.PARSED,
        stage1_status=None,
        file_hash="b5-empty-positions",
        institution="Futu",
    )
    db.add(statement)
    await db.commit()

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

    assert refreshed is not None
    # Visible review flag: lands in the Stage-1 pending-review queue ...
    assert refreshed.stage1_status == Stage1Status.PENDING_REVIEW
    # ... and keeps the human-readable reason.
    assert refreshed.validation_error is not None
    assert "no positions detected" in refreshed.validation_error


# ----------------------------------------------------------------- AC-B4 / AC-B6


async def test_AC_B4_AC_B6_moomoo_positions_table_extracts_and_imports(client, db, test_user, monkeypatch):
    """AC-extraction.304.12 (AC-B4/AC-B6) (#1088): Moomoo holdings TABLE -> extracted positions -> imported AtomicPositions.

    AtomicPosition row count must equal the holdings-table row count, with exact market_value.
    The parsed payload is loaded from a recorded fixture and injected via the extraction seam,
    so the producer routing + import are asserted deterministically without a live model.
    """
    fixture = _synthetic_moomoo_positions_payload()
    expected_rows = fixture["positions"]

    statement_id = uuid4()
    user_id = test_user.id
    file_hash = "b4-b6-moomoo-positions-table"
    statement = StatementSummaryFactory.build(
        id=statement_id,
        user_id=user_id,
        status=BankStatementStatus.PARSING,
        file_hash=file_hash,
        institution="Moomoo",
    )
    db.add(statement)
    await db.commit()

    async def fake_parse_document(*args, **kwargs):
        session = kwargs["db"]
        summary = await session.get(StatementSummary, statement_id)
        summary.institution = "Moomoo"
        summary.currency = "USD"
        summary.status = BankStatementStatus.PARSED
        summary.confidence_score = 90
        summary.balance_validated = True
        # The real parse_document persists the OCR payload; the explicit import endpoint
        # (#1408) recovers positions from extraction_metadata.
        summary.extraction_metadata = {"extraction_payload": fixture}
        doc = UploadedDocument(
            user_id=user_id,
            file_path="statements/moomoo-positions.pdf",
            file_hash=file_hash,
            original_filename="moomoo-positions-2506.pdf",
            document_type=DocumentType.BANK_STATEMENT,
        )
        session.add(doc)
        await session.flush()
        summary.uploaded_document_id = doc.id
        await session.flush()
        summary._extracted_payload = fixture
        return summary, []

    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.ExtractionService.parse_document", fake_parse_document
    )
    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.StorageService.generate_presigned_url",
        lambda *args, **kwargs: "https://example.com/moomoo-positions-2506.pdf",
    )

    await parse_statement_background(
        job=ParseJob(
            statement_id=statement_id,
            filename="moomoo-positions-2506.pdf",
            institution="Moomoo",
            user_id=user_id,
            account_id=None,
            file_hash=file_hash,
            storage_key="statements/moomoo-positions.pdf",
            model=None,
        ),
        content=b"%PDF-1.7",
        session_maker=create_session_maker_from_db(db),
    )

    db.expire_all()
    # #1408: parse routes the brokerage statement to review WITHOUT importing positions.
    atomic_rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()
    assert len(atomic_rows) == 0
    refreshed = await db.get(StatementSummary, statement_id)
    assert refreshed is not None
    assert refreshed.status == BankStatementStatus.PARSED
    assert refreshed.stage1_status == Stage1Status.PENDING_REVIEW
    # Positions exist (no zero-position review flag), so no validation note is added.
    assert refreshed.validation_error is None

    # #1408: the explicit import endpoint is the only path that creates positions.
    import_response = await client.post(f"/statements/{statement_id}/brokerage/import")
    assert import_response.status_code == 200, import_response.text

    db.expire_all()
    atomic_rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()

    # AtomicPosition rows == holdings-table rows.
    assert len(atomic_rows) == len(expected_rows)

    by_identifier = {row.asset_identifier: row for row in atomic_rows}
    for spec in expected_rows:
        identifier = spec["symbol"]
        assert identifier in by_identifier, f"missing imported position {identifier}"
        row = by_identifier[identifier]
        # market_value exact (Decimal, never float).
        assert row.market_value == Decimal(spec["market_value"])
        assert row.quantity == Decimal(spec["quantity"])
        assert row.currency == spec["currency"]
        assert row.snapshot_date == date(2026, 6, 30)


async def test_AC_B6_positions_payload_imports_via_service(db, test_user):
    """AC-extraction.304.12 (AC-B6): The recorded moomoo positions fixture imports the full table via the service."""
    service = BrokeragePositionImportService()
    fixture = _synthetic_moomoo_positions_payload()

    result = await service.import_positions(
        db,
        user_id=test_user.id,
        payload=fixture,
        filename="moomoo-positions-2506.pdf",
        source_document_id="doc-moomoo-positions",
        reconcile=False,
    )
    await db.commit()

    assert result.broker == "Moomoo"
    assert result.parsed_positions == len(fixture["positions"])
    assert result.created_atomic_positions == len(fixture["positions"])

    rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == test_user.id))).scalars().all()
    assert len(rows) == len(fixture["positions"])
    total_market_value = sum((row.market_value for row in rows), Decimal("0"))
    expected_total = sum((Decimal(p["market_value"]) for p in fixture["positions"]), Decimal("0"))
    assert total_market_value == expected_total


# --------------------------------------------------------------------------- AC-B3


def test_AC_B3_multi_currency_brokerage_emits_per_currency_balances():
    """AC-extraction.304.13 (AC-B3): A multi-currency brokerage snapshot yields one NAV bucket per currency.

    USD = 2124 + 2276 = 4400, HKD = 80500, SGD = 3810. The currencies must NOT be
    cross-summed into a single scalar (88710) — each currency is an independent
    closed loop whose opening == closing == its own position NAV.
    """
    fixture = _synthetic_ibkr_multicurrency_payload()

    balances = brokerage_currency_balances(fixture, filename="ibkr-multicurrency-2506.pdf")

    by_currency = {b["currency"]: b for b in balances}
    # Every distinct position currency round-trips as its own bucket.
    assert set(by_currency) == {"USD", "HKD", "SGD"}
    assert by_currency["USD"]["closing"] == Decimal("4400.00")
    assert by_currency["HKD"]["closing"] == Decimal("80500.00")
    assert by_currency["SGD"]["closing"] == Decimal("3810.00")
    # Snapshot has no cash flow: opening == closing per currency (zero-net loop).
    for bucket in balances:
        assert bucket["opening"] == bucket["closing"]
    # No cross-sum: no bucket carries the meaningless 88710 aggregate, and the
    # number of buckets equals the number of distinct currencies.
    assert all(b["closing"] != Decimal("88710.00") for b in balances)
    assert len(balances) == 3


async def test_AC_B3_parse_document_persists_currency_balances_without_cross_sum(test_user):
    """AC-extraction.304.13 (AC-B3): parse_document persists the per-currency NAV array on the statement.

    The scalar opening/closing stay None for the position snapshot (no running-balance
    chain), while ``currency_balances`` carries the independent per-currency NAV — the
    multi-currency NAV no longer collapses to one scalar. Decimal-safe round-trip: the
    JSONB values are strings that parse back to the exact per-currency NAV.
    """
    from unittest.mock import AsyncMock

    service = ExtractionService()
    payload = _synthetic_ibkr_multicurrency_payload()
    service.extract_financial_data = AsyncMock(return_value=payload)

    statement, transactions = await service.parse_document(
        file_path=Path("ibkr-multicurrency-2506.pdf"),
        institution="Interactive Brokers",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="ibkr-multicurrency-hash",
        original_filename="ibkr-multicurrency-2506.pdf",
    )

    assert transactions == []
    assert statement.status == BankStatementStatus.PARSED
    # The per-currency NAV is persisted; it does not collapse to a single scalar.
    assert statement.currency_balances is not None
    by_currency = {b["currency"]: b for b in statement.currency_balances}
    assert set(by_currency) == {"USD", "HKD", "SGD"}
    # Decimal round-trip: stored strings parse back to the exact per-currency NAV.
    assert Decimal(by_currency["USD"]["closing"]) == Decimal("4400.00")
    assert Decimal(by_currency["HKD"]["closing"]) == Decimal("80500.00")
    assert Decimal(by_currency["SGD"]["closing"]) == Decimal("3810.00")
    # No cross-sum into one scalar: three independent buckets, none equal to 88710.
    assert len(statement.currency_balances) == 3
    assert all(Decimal(b["closing"]) != Decimal("88710.00") for b in statement.currency_balances)


async def test_per_currency_nav_self_check_failure_marks_statement_invalid(test_user, monkeypatch):
    """#1160 CR1: a failing per-currency NAV self-check is respected, not ignored.

    Previously ``validate_balance_per_currency`` could return ``balance_valid=False``
    yet ``currency_balances`` was persisted as if reconciled — only a warning was
    logged. The fix surfaces the failure on the persisted statement
    (``balance_validated`` False + a ``validation_error``), mirroring the scalar
    invalid-balance path, while still persisting the per-currency evidence array.
    """
    from unittest.mock import AsyncMock

    service = ExtractionService()
    payload = _synthetic_ibkr_multicurrency_payload()
    service.extract_financial_data = AsyncMock(return_value=payload)

    # Force the per-currency self-check to fail for one currency.
    def _failing_per_currency(_extracted):
        return {
            "balance_valid": False,
            "balance_computable": True,
            "per_currency": [
                {
                    "currency": "USD",
                    "balance_valid": False,
                    "expected_closing": "4400.00",
                    "actual_closing": "4000.00",
                },
                {"currency": "HKD", "balance_valid": True},
            ],
        }

    monkeypatch.setattr("src.extraction.extension.service.validate_balance_per_currency", _failing_per_currency)

    statement, _ = await service.parse_document(
        file_path=Path("ibkr-multicurrency-2506.pdf"),
        institution="Interactive Brokers",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="ibkr-multicurrency-invalid-hash",
        original_filename="ibkr-multicurrency-2506.pdf",
    )

    # The per-currency evidence array is still persisted (it is the audit trail)...
    assert statement.currency_balances is not None
    assert len(statement.currency_balances) == 3
    # ...but the statement is NOT marked balance-valid, and the failure is surfaced.
    assert statement.balance_validated is False
    assert statement.validation_error is not None
    assert "USD" in statement.validation_error
    assert "self-check failed" in statement.validation_error.lower()
