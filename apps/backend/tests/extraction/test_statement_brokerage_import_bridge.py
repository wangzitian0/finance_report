"""Tests for the statement upload to brokerage position import bridge."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from sqlalchemy import select

from src.database import create_session_maker_from_db
from src.extraction import DocumentType, UploadedDocument
from src.extraction.extension import statement_parsing
from src.extraction.extension.brokerage_positions import looks_like_brokerage_payload, parse_brokerage_positions
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing import (
    _count_brokerage_positions,
    _filter_failure_handler_kwargs,
    parse_statement_background,
    route_brokerage_for_review_if_present,
)
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition
from src.models.statement_enums import BankStatementStatus, Stage1Status
from src.models.statement_summary import StatementSummary
from tests.factories import StatementSummaryFactory

_BRIDGE_ASSET_IDENTIFIER = "BRIDGE_TEST_STOCK"


def _parsed_statement(user_id, file_hash: str) -> StatementSummary:
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


def _apply_parsed_envelope(summary: StatementSummary, *, validation_error: str | None = None) -> None:
    """Mirror the envelope fields dual_write_layer2 would persist onto the pre-created row."""
    summary.institution = "Moomoo"
    summary.account_last4 = "1234"
    summary.currency = "SGD"
    summary.period_start = date(2026, 5, 1)
    summary.period_end = date(2026, 5, 18)
    summary.opening_balance = Decimal("0.00")
    summary.closing_balance = Decimal("0.00")
    summary.status = BankStatementStatus.PARSED
    summary.confidence_score = 90
    summary.balance_validated = True
    summary.validation_error = validation_error


def _brokerage_payload() -> dict:
    return {
        "institution": "Moomoo",
        "period_start": "2026-05-01",
        "period_end": "2026-05-18",
        "statement": {"period_end": "2026-05-18", "currency": "SGD"},
        "positions": [
            {
                "symbol": _BRIDGE_ASSET_IDENTIFIER,
                "snapshot_date": date(2026, 5, 18),
                "quantity": "10",
                "market_value": "1900.25",
                "currency": "SGD",
                "asset_type": "stock",
                "sector": "Technology",
                "geography": "US",
            }
        ],
    }


def _brokerage_payload_json_safe() -> dict:
    """JSON-serializable variant for persisting to extraction_metadata (string snapshot_date)."""
    payload = _brokerage_payload()
    payload["positions"][0]["snapshot_date"] = "2026-05-18"
    return payload


def test_looks_like_brokerage_payload_detection_paths():
    """AC-extraction.304.7: Brokerage detection handles structured, nested, and non-broker payloads."""
    assert looks_like_brokerage_payload({"positions": []}, filename="unknown.pdf")
    assert looks_like_brokerage_payload(
        {"statement": {"holdings": []}},
        filename="statement.pdf",
        institution="Interactive Brokers",
    )
    assert not looks_like_brokerage_payload(
        {"institution": "DBS", "transactions": []},
        filename="dbs-statement.pdf",
        institution="DBS",
    )


def test_count_brokerage_positions_handles_empty_and_nested_payloads():
    """AC-extraction.304.7: Brokerage import counts top-level and nested parsed position arrays."""
    assert _count_brokerage_positions({"positions": [{}, {}]}) == 2
    assert _count_brokerage_positions({"statement": {"holdings": [{}]}}) == 1
    assert _count_brokerage_positions({"statement": {"positions": [{}, {}, {}]}}) == 3
    assert _count_brokerage_positions({}) is None
    assert _count_brokerage_positions({"statement": {"holdings": "unstructured"}}) is None


def test_filter_failure_handler_kwargs_returns_original_when_signature_unavailable(monkeypatch):
    """AC-extraction.304.7: Parse failure compatibility shim tolerates opaque handlers."""
    payload = {"message": "parse failed", "future_arg": "preserved"}

    def raise_value_error(_callable):
        raise ValueError("opaque callable")

    monkeypatch.setattr(statement_parsing, "signature", raise_value_error)

    assert _filter_failure_handler_kwargs(payload) is payload


def test_filter_failure_handler_kwargs_keeps_payload_for_var_keyword_handler(monkeypatch):
    """AC-extraction.304.7: Parse failure compatibility shim preserves kwargs-capable handlers."""
    payload = {"message": "parse failed", "future_arg": "preserved"}

    async def accepts_kwargs(*_args, **_kwargs):
        return None

    monkeypatch.setattr(statement_parsing, "handle_parse_failure", accepts_kwargs)

    assert _filter_failure_handler_kwargs(payload) is payload


def test_filter_failure_handler_kwargs_drops_unknown_keys_for_fixed_handler(monkeypatch):
    """AC-extraction.304.7: Parse failure compatibility shim filters unknown kwargs."""
    payload = {"message": "parse failed", "future_arg": "dropped"}

    async def fixed_handler(_statement, _db, *, message):
        return message

    monkeypatch.setattr(statement_parsing, "handle_parse_failure", fixed_handler)

    assert _filter_failure_handler_kwargs(payload) == {"message": "parse failed"}


def test_parse_brokerage_positions_skips_malformed_moomoo_subscription_row():
    """AC-extraction.304.7: Malformed brokerage rows are ignored instead of imported as positions."""
    snapshots = parse_brokerage_positions(
        {
            "institution": "Moomoo",
            "transactions": [
                {
                    "raw_text": "Subscription X FULLERTON SGD CASH FUND SGD 2026/05/18 X . . .",
                },
            ],
        },
        filename="moomoo-statement.pdf",
    )

    assert snapshots == []


async def test_parse_document_preserves_brokerage_payload_for_background_import(test_user):
    """AC-extraction.304.7: Extraction keeps structured brokerage payloads available for import."""
    service = ExtractionService()
    payload = _brokerage_payload()
    service.extract_financial_data = AsyncMock(return_value=payload)

    statement, transactions = await service.parse_document(
        file_path=Path("moomoo-positions.pdf"),
        institution="Moomoo",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="brokerage-payload-hash",
        original_filename="moomoo-positions.pdf",
    )

    assert transactions == []
    assert statement.status == BankStatementStatus.PARSED
    assert statement.period_start == date(2026, 5, 1)
    assert statement.period_end == date(2026, 5, 18)
    assert statement.opening_balance is None
    assert statement.closing_balance is None
    assert statement._extracted_payload == payload
    assert statement.extraction_metadata == {"extraction_payload": payload}


async def test_parse_document_skips_non_bank_rows_in_brokerage_payload(test_user):
    """AC-extraction.304.7: Brokerage transaction-like rows do not block position import handoff."""
    service = ExtractionService()
    payload = {
        "institution": "Moomoo",
        "transactions": [
            {"raw_text": "FULLERTON SGD CASH FUND 100 units market value 100.00"},
            {"date": "not-a-date", "amount": "10.00", "description": "not bank txn"},
            {"date": "2026-05-18", "amount": "not-a-number", "description": "not bank amount"},
        ],
    }
    service.extract_financial_data = AsyncMock(return_value=payload)

    statement, transactions = await service.parse_document(
        file_path=Path("moomoo-statement.pdf"),
        institution="Moomoo",
        user_id=test_user.id,
        file_content=b"%PDF-1.7",
        file_hash="brokerage-raw-rows-hash",
        original_filename="moomoo-statement.pdf",
    )

    assert transactions == []
    assert statement.status == BankStatementStatus.PARSED
    assert statement._extracted_payload == payload


async def test_parse_document_normalizes_signed_outflows_before_brokerage_routing():
    """AC-extraction.813.10/Issue #409: Signed OUT brokerage rows do not stall parsed routing."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
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
                    "description": "Fullerton SGD Money Market Fund",
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
        }
    )

    statement, transactions = await service.parse_document(
        file_path=Path("moomoo-statement.pdf"),
        institution="Moomoo",
        user_id=uuid4(),
        file_content=b"%PDF-1.7",
        file_hash="issue-409-signed-outflow",
        original_filename="moomoo-statement.pdf",
    )

    assert statement.status == BankStatementStatus.PARSED
    assert statement.balance_validated is True
    assert transactions[1].direction == "OUT"
    assert transactions[1].amount == Decimal("500.00")


async def test_parse_document_infers_direction_from_signed_brokerage_amounts():
    """AC-extraction.813.10/Issue #409: Non-standard debit directions normalize deterministically."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
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
                },
            ],
        }
    )

    statement, transactions = await service.parse_document(
        file_path=Path("moomoo-statement.pdf"),
        institution="Moomoo",
        user_id=uuid4(),
        file_content=b"%PDF-1.7",
        file_hash="issue-409-inferred-outflow",
        original_filename="moomoo-statement.pdf",
    )

    assert statement.status == BankStatementStatus.PARSED
    assert statement.balance_validated is True
    assert transactions[0].direction == "OUT"
    assert transactions[0].amount == Decimal("500.00")


async def test_parse_document_routes_brokerage_balance_mismatch_to_parsed():
    """AC-extraction.813.10/Issue #409: Brokerage payloads do not stall after OCR balance mismatch."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "Moomoo",
            "currency": "SGD",
            "period_start": "2026-05-01",
            "period_end": "2026-05-31",
            "opening_balance": "0.00",
            "closing_balance": "0.00",
            "transactions": [
                {
                    "date": "2026-05-18",
                    "description": "Fullerton SGD Money Market Fund",
                    "amount": "1250.50",
                    "direction": "IN",
                    "currency": "SGD",
                }
            ],
            "positions": [
                {
                    "symbol": "Fullerton SGD Money Market Fund",
                    "quantity": "1250.50",
                    "market_value": "1250.50",
                    "currency": "SGD",
                    "asset_type": "money_market",
                }
            ],
        }
    )

    statement, transactions = await service.parse_document(
        file_path=Path("moomoo-statement.pdf"),
        institution="Moomoo",
        user_id=uuid4(),
        file_content=b"%PDF-1.7",
        file_hash="issue-409-brokerage-balance-mismatch",
        original_filename="moomoo-statement.pdf",
    )

    assert statement.status == BankStatementStatus.PARSED
    assert statement.balance_validated is False
    assert statement.validation_error == "Balance mismatch: expected 1250.50, got 0.00"
    assert transactions[0].amount == Decimal("1250.50")
    assert statement._extracted_payload["positions"][0]["market_value"] == "1250.50"


async def test_route_brokerage_for_review_ignores_bank_payload(db, test_user):
    """AC-extraction.304.7/#1408: Bank statement payloads are not routed for brokerage review."""
    statement = _parsed_statement(test_user.id, "bank-hash")
    statement.stage1_status = None

    await route_brokerage_for_review_if_present(
        summary=statement,
        db=db,
        user_id=test_user.id,
        filename="dbs.pdf",
        institution="DBS",
        payload={"institution": "DBS", "transactions": []},
    )

    assert statement.validation_error is None
    # A bank payload must not be moved into the brokerage review queue.
    assert statement.stage1_status is None


async def test_route_brokerage_for_review_records_zero_position_payload(db, test_user):
    """AC-extraction.304.7/#1408: Recognized brokerage payloads with no positions stay visible and route to review."""
    statement_id = uuid4()
    statement = StatementSummaryFactory.build(
        id=statement_id,
        user_id=test_user.id,
        status=BankStatementStatus.PARSED,
        stage1_status=None,
        file_hash="futu-empty-hash",
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
    assert refreshed.validation_error is not None
    assert "no positions detected" in refreshed.validation_error
    # #1408: surfaced as a Stage-1 review flag, not auto-settled.
    assert refreshed.stage1_status == Stage1Status.PENDING_REVIEW


async def test_route_brokerage_for_review_uses_nested_statement_institution(db, test_user, monkeypatch):
    """AC-extraction.304.7/#1408: Review routing reads broker identity from nested statement metadata."""
    statement = _parsed_statement(test_user.id, "nested-broker-hash")
    db.add(statement)
    await db.commit()
    info_events = []

    def capture_info(event_name, **kwargs):
        info_events.append((event_name, kwargs))

    monkeypatch.setattr(statement_parsing.logger, "info", capture_info)

    await route_brokerage_for_review_if_present(
        summary=statement,
        db=db,
        user_id=test_user.id,
        filename="ibkr-statement.pdf",
        institution=None,
        payload={
            "statement": {
                "institution": "Interactive Brokers",
                "positions": [{"symbol": "AAPL"}],
            }
        },
    )

    started_events = [
        kwargs for event_name, kwargs in info_events if event_name == "statement.brokerage_review_routing.started"
    ]
    assert started_events[0]["broker"] == "Interactive Brokers"
    # #1408: routing surfaces the statement for review without importing positions.
    assert statement.stage1_status == Stage1Status.PENDING_REVIEW


async def test_route_brokerage_for_review_stops_when_failed_statement_is_missing():
    """AC-extraction.304.7/#1408: Review-routing failure handling tolerates deleted statements.

    If the routing commit raises, the function rolls back and tries to attach a
    validation note to a re-fetched row; when that row is gone it must exit cleanly.
    """
    statement_id = uuid4()
    statement = StatementSummaryFactory.build(
        id=statement_id,
        user_id=uuid4(),
        status=BankStatementStatus.PARSED,
        file_hash="missing-after-failure-hash",
        institution="Moomoo",
    )

    class MissingStatementDb:
        def __init__(self):
            self.rolled_back = False
            self.lookup = None
            self._commits = 0

        async def commit(self):
            # First commit (the routing write) fails; a second commit (post-rollback
            # note) would only run if the re-fetched row exists, which it does not.
            self._commits += 1
            if self._commits == 1:
                raise RuntimeError("forced commit failure")

        async def rollback(self):
            self.rolled_back = True

        async def get(self, model, lookup_id):
            self.lookup = (model, lookup_id)
            return None

    db = MissingStatementDb()

    await route_brokerage_for_review_if_present(
        summary=statement,
        db=db,
        user_id=statement.user_id,
        filename="moomoo-statement.pdf",
        institution="Moomoo",
        payload={"institution": "Moomoo", "positions": [{"symbol": "AAPL"}]},
    )

    assert db.rolled_back is True
    assert db.lookup == (StatementSummary, statement_id)


async def test_parse_statement_background_imports_brokerage_positions(client, db, test_user, monkeypatch):
    """AC-extraction.304.7/AC17.5.4/AC-extraction.813.10: Background brokerage import reaches reports."""
    statement_id = uuid4()
    user_id = test_user.id
    file_hash = "brokerage-success-hash"
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
        _apply_parsed_envelope(summary)
        # The real parse_document persists the OCR payload here; the explicit import
        # endpoint (#1408) recovers positions from extraction_metadata.
        summary.extraction_metadata = {"extraction_payload": _brokerage_payload_json_safe()}
        # Link an ODS document so the explicit import resolves a source filename.
        doc = UploadedDocument(
            user_id=user_id,
            file_path="statements/moomoo.pdf",
            file_hash=file_hash,
            original_filename="moomoo-positions.pdf",
            document_type=DocumentType.BANK_STATEMENT,
        )
        session.add(doc)
        await session.flush()
        summary.uploaded_document_id = doc.id
        await session.flush()
        summary._extracted_payload = _brokerage_payload()
        return summary, []

    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.ExtractionService.parse_document", fake_parse_document
    )
    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.StorageService.generate_presigned_url",
        lambda *args, **kwargs: "https://example.com/moomoo-positions.pdf",
    )

    await parse_statement_background(
        statement_id=statement_id,
        filename="moomoo-positions.pdf",
        institution="Moomoo",
        user_id=user_id,
        account_id=None,
        file_hash=file_hash,
        storage_key="statements/moomoo.pdf",
        content=b"%PDF-1.7",
        model=None,
        session_maker=create_session_maker_from_db(db),
    )

    db.expire_all()
    atomic_rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()
    managed_rows = (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == user_id))).scalars().all()
    refreshed = await db.get(StatementSummary, statement_id)

    assert refreshed is not None
    assert refreshed.status == BankStatementStatus.PARSED
    assert refreshed.confidence_score == 90
    assert refreshed.balance_validated is True
    assert refreshed.validation_error is None
    # #1408: parse does NOT auto-import positions; the statement is only routed to review.
    assert refreshed.stage1_status == Stage1Status.PENDING_REVIEW
    assert len(atomic_rows) == 0
    assert len(managed_rows) == 0

    # Holdings stay empty until the user triggers the explicit import endpoint.
    pre_import_holdings = await client.get("/portfolio/holdings", params={"as_of_date": "2026-05-18"})
    assert pre_import_holdings.status_code == 200
    assert pre_import_holdings.json() == []

    # #1408: the explicit, user-initiated endpoint is the only path that creates positions.
    import_response = await client.post(f"/statements/{statement_id}/brokerage/import")
    assert import_response.status_code == 200, import_response.text

    db.expire_all()
    atomic_rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()
    managed_rows = (await db.execute(select(ManagedPosition).where(ManagedPosition.user_id == user_id))).scalars().all()
    assert len(atomic_rows) == 1
    assert atomic_rows[0].asset_identifier == _BRIDGE_ASSET_IDENTIFIER
    assert len(managed_rows) == 1
    assert managed_rows[0].asset_identifier == _BRIDGE_ASSET_IDENTIFIER
    assert managed_rows[0].quantity == Decimal("10")

    holdings_response = await client.get(
        "/portfolio/holdings",
        params={"as_of_date": "2026-05-18"},
    )
    assert holdings_response.status_code == 200
    holdings = holdings_response.json()
    assert len(holdings) == 1
    assert holdings[0]["asset_identifier"] == _BRIDGE_ASSET_IDENTIFIER
    assert holdings[0]["account_name"] == "Moomoo"
    assert Decimal(str(holdings[0]["quantity"])) == Decimal("10.00000000")
    assert Decimal(str(holdings[0]["market_value"])) == Decimal("1900.25")
    assert holdings[0]["currency"] == "SGD"

    async def skip_report_market_data_refresh(*args, **kwargs):
        return None

    monkeypatch.setattr("src.routers.reports.ensure_market_data_fresh", skip_report_market_data_refresh)
    balance_response = await client.get(
        "/reports/balance-sheet",
        params={"as_of_date": "2026-05-18", "currency": "SGD"},
    )
    assert balance_response.status_code == 200
    balance_sheet = balance_response.json()
    assert Decimal(str(balance_sheet["net_worth_adjustment_gain_loss"])) == Decimal("1900.25")
    assert Decimal(str(balance_sheet["equation_delta"])) == Decimal("0.00")
    assert balance_sheet["is_balanced"] is True
    assert any(
        line["name"] == "Moomoo market valuation adjustment" and Decimal(str(line["amount"])) == Decimal("1900.25")
        for line in balance_sheet["assets"]
    )


async def test_parse_statement_background_routes_brokerage_to_review_without_importing(db, test_user, monkeypatch):
    """#1408: parse routes a brokerage statement to Stage-1 review and imports no positions,
    preserving any existing parser validation note."""
    statement_id = uuid4()
    user_id = test_user.id
    file_hash = "brokerage-review-routing-hash"
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
        _apply_parsed_envelope(summary, validation_error="existing parser note")
        await session.flush()
        summary._extracted_payload = _brokerage_payload()
        return summary, []

    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.ExtractionService.parse_document", fake_parse_document
    )
    monkeypatch.setattr(
        "src.extraction.extension.statement_parsing.StorageService.generate_presigned_url",
        lambda *args, **kwargs: "https://example.com/moomoo-review.pdf",
    )

    await parse_statement_background(
        statement_id=statement_id,
        filename="moomoo-review.pdf",
        institution="Moomoo",
        user_id=user_id,
        account_id=None,
        file_hash=file_hash,
        storage_key="statements/moomoo-review.pdf",
        content=b"%PDF-1.7",
        model=None,
        session_maker=create_session_maker_from_db(db),
    )

    db.expire_all()
    refreshed = await db.get(StatementSummary, statement_id)
    atomic_rows = (await db.execute(select(AtomicPosition).where(AtomicPosition.user_id == user_id))).scalars().all()

    assert refreshed is not None
    assert refreshed.status == BankStatementStatus.PARSED
    # #1408: routed to review, no positions imported, existing parser note preserved.
    assert refreshed.stage1_status == Stage1Status.PENDING_REVIEW
    assert refreshed.validation_error == "existing parser note"
    assert len(atomic_rows) == 0


async def test_AC3_12_1_brokerage_without_balances_reports_balance_validated_none_not_vacuous_true():
    """AC-extraction.12.1: a brokerage holdings statement with no opening/closing balances reports
    balance_validated=None (not-applicable), not a vacuous 0==0 True (#1443)."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "Futu",
            "currency": "HKD",
            "positions": [
                {"symbol": "01810", "quantity": "100", "market_value": "5500.00", "currency": "HKD"},
            ],
        }
    )

    statement, _txns = await service.parse_document(
        file_path=Path("futu-positions.pdf"),
        institution="Futu",
        user_id=uuid4(),
        file_content=b"%PDF-1.7",
        file_hash="ac-3-12-1-no-balances",
        original_filename="futu-positions.pdf",
    )

    assert statement.opening_balance is None
    assert statement.closing_balance is None
    assert statement.balance_validated is None
