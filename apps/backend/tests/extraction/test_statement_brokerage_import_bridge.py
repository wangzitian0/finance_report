"""Tests for the statement upload to brokerage position import bridge."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.database import create_session_maker_from_db
from src.models import BankStatementStatus
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition
from src.models.statement_summary import StatementSummary
from src.services import statement_parsing
from src.services.brokerage_positions import looks_like_brokerage_payload, parse_brokerage_positions
from src.services.extraction import ExtractionService
from src.services.statement_parsing import (
    _count_brokerage_positions,
    _filter_failure_handler_kwargs,
    import_brokerage_payload_if_present,
    parse_statement_background,
)
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


def test_looks_like_brokerage_payload_detection_paths():
    """AC17.4.7: Brokerage detection handles structured, nested, and non-broker payloads."""
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
    """AC17.4.7: Brokerage import counts top-level and nested parsed position arrays."""
    assert _count_brokerage_positions({"positions": [{}, {}]}) == 2
    assert _count_brokerage_positions({"statement": {"holdings": [{}]}}) == 1
    assert _count_brokerage_positions({"statement": {"positions": [{}, {}, {}]}}) == 3
    assert _count_brokerage_positions({}) is None
    assert _count_brokerage_positions({"statement": {"holdings": "unstructured"}}) is None


def test_filter_failure_handler_kwargs_returns_original_when_signature_unavailable(monkeypatch):
    """AC17.4.7: Parse failure compatibility shim tolerates opaque handlers."""
    payload = {"message": "parse failed", "future_arg": "preserved"}

    def raise_value_error(_callable):
        raise ValueError("opaque callable")

    monkeypatch.setattr(statement_parsing, "signature", raise_value_error)

    assert _filter_failure_handler_kwargs(payload) is payload


def test_filter_failure_handler_kwargs_keeps_payload_for_var_keyword_handler(monkeypatch):
    """AC17.4.7: Parse failure compatibility shim preserves kwargs-capable handlers."""
    payload = {"message": "parse failed", "future_arg": "preserved"}

    async def accepts_kwargs(*_args, **_kwargs):
        return None

    monkeypatch.setattr(statement_parsing, "handle_parse_failure", accepts_kwargs)

    assert _filter_failure_handler_kwargs(payload) is payload


def test_filter_failure_handler_kwargs_drops_unknown_keys_for_fixed_handler(monkeypatch):
    """AC17.4.7: Parse failure compatibility shim filters unknown kwargs."""
    payload = {"message": "parse failed", "future_arg": "dropped"}

    async def fixed_handler(_statement, _db, *, message):
        return message

    monkeypatch.setattr(statement_parsing, "handle_parse_failure", fixed_handler)

    assert _filter_failure_handler_kwargs(payload) == {"message": "parse failed"}


def test_parse_brokerage_positions_skips_malformed_moomoo_subscription_row():
    """AC17.4.7: Malformed brokerage rows are ignored instead of imported as positions."""
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


@pytest.mark.asyncio
async def test_parse_document_preserves_brokerage_payload_for_background_import(test_user):
    """AC17.4.7: Extraction keeps structured brokerage payloads available for import."""
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


@pytest.mark.asyncio
async def test_parse_document_skips_non_bank_rows_in_brokerage_payload(test_user):
    """AC17.4.7: Brokerage transaction-like rows do not block position import handoff."""
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


@pytest.mark.asyncio
async def test_parse_document_normalizes_signed_outflows_before_brokerage_routing():
    """AC8.13.10/Issue #409: Signed OUT brokerage rows do not stall parsed routing."""
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


@pytest.mark.asyncio
async def test_parse_document_infers_direction_from_signed_brokerage_amounts():
    """AC8.13.10/Issue #409: Non-standard debit directions normalize deterministically."""
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


@pytest.mark.asyncio
async def test_parse_document_routes_brokerage_balance_mismatch_to_parsed():
    """AC8.13.10/Issue #409: Brokerage payloads do not stall after OCR balance mismatch."""
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


@pytest.mark.asyncio
async def test_import_brokerage_payload_if_present_ignores_bank_payload(db, test_user, monkeypatch):
    """AC17.4.7: Bank statement payloads do not call brokerage import."""
    statement = _parsed_statement(test_user.id, "bank-hash")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("brokerage import should not be called for bank payloads")

    monkeypatch.setattr("src.services.statement_parsing._brokerage_import_service.import_positions", fail_if_called)

    await import_brokerage_payload_if_present(
        summary=statement,
        db=db,
        user_id=test_user.id,
        filename="dbs.pdf",
        institution="DBS",
        payload={"institution": "DBS", "transactions": []},
    )

    assert statement.validation_error is None


@pytest.mark.asyncio
async def test_import_brokerage_payload_if_present_records_zero_position_payload(db, test_user):
    """AC17.4.7: Recognized brokerage payloads with no positions remain visible."""
    statement_id = uuid4()
    statement = StatementSummaryFactory.build(
        id=statement_id,
        user_id=test_user.id,
        status=BankStatementStatus.PARSED,
        file_hash="futu-empty-hash",
        institution="Futu",
    )
    db.add(statement)
    await db.commit()

    await import_brokerage_payload_if_present(
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


@pytest.mark.asyncio
async def test_import_brokerage_payload_if_present_uses_nested_statement_institution(db, test_user, monkeypatch):
    """AC17.4.7: Brokerage import reads broker identity from nested statement metadata."""
    statement = _parsed_statement(test_user.id, "nested-broker-hash")
    info_events = []

    async def fake_import_positions(*_args, **_kwargs):
        return SimpleNamespace(
            broker="Interactive Brokers",
            parsed_positions=1,
            created_atomic_positions=0,
            existing_atomic_positions=0,
            reconcile_created=0,
            reconcile_updated=0,
            reconcile_disposed=0,
        )

    def capture_info(event_name, **kwargs):
        info_events.append((event_name, kwargs))

    monkeypatch.setattr(statement_parsing._brokerage_import_service, "import_positions", fake_import_positions)
    monkeypatch.setattr(statement_parsing.logger, "info", capture_info)

    await import_brokerage_payload_if_present(
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
        kwargs for event_name, kwargs in info_events if event_name == "statement.brokerage_import.started"
    ]
    assert started_events[0]["broker"] == "Interactive Brokers"


@pytest.mark.asyncio
async def test_import_brokerage_payload_if_present_stops_when_failed_statement_is_missing(monkeypatch):
    """AC17.4.7: Brokerage import failure handling tolerates deleted statements."""
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

        async def rollback(self):
            self.rolled_back = True

        async def get(self, model, lookup_id):
            self.lookup = (model, lookup_id)
            return None

    async def fail_import_positions(*_args, **_kwargs):
        raise RuntimeError("forced import failure")

    db = MissingStatementDb()
    monkeypatch.setattr(statement_parsing._brokerage_import_service, "import_positions", fail_import_positions)

    await import_brokerage_payload_if_present(
        summary=statement,
        db=db,
        user_id=statement.user_id,
        filename="moomoo-statement.pdf",
        institution="Moomoo",
        payload={"institution": "Moomoo", "positions": [{"symbol": "AAPL"}]},
    )

    assert db.rolled_back is True
    assert db.lookup == (StatementSummary, statement_id)


@pytest.mark.asyncio
async def test_parse_statement_background_imports_brokerage_positions(client, db, test_user, monkeypatch):
    """AC17.4.7/AC17.5.4/AC8.13.10: Background brokerage import reaches reports."""
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
        await session.flush()
        summary._extracted_payload = _brokerage_payload()
        return summary, []

    monkeypatch.setattr("src.services.statement_parsing.ExtractionService.parse_document", fake_parse_document)
    monkeypatch.setattr(
        "src.services.statement_parsing.StorageService.generate_presigned_url",
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
    assert len(atomic_rows) == 1
    assert atomic_rows[0].asset_identifier == _BRIDGE_ASSET_IDENTIFIER
    assert atomic_rows[0].source_documents["documents"][0]["doc_id"] == str(statement_id)
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


@pytest.mark.asyncio
async def test_parse_statement_background_persists_brokerage_import_failure(db, test_user, monkeypatch):
    """AC17.4.7: Brokerage import failures are visible on the parsed statement."""
    statement_id = uuid4()
    user_id = test_user.id
    file_hash = "brokerage-failure-hash"
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

    async def fail_import(*args, **kwargs):
        raise RuntimeError("forced import failure")

    monkeypatch.setattr("src.services.statement_parsing.ExtractionService.parse_document", fake_parse_document)
    monkeypatch.setattr(
        "src.services.statement_parsing.StorageService.generate_presigned_url",
        lambda *args, **kwargs: "https://example.com/moomoo-fail.pdf",
    )
    monkeypatch.setattr("src.services.statement_parsing._brokerage_import_service.import_positions", fail_import)

    await parse_statement_background(
        statement_id=statement_id,
        filename="moomoo-fail.pdf",
        institution="Moomoo",
        user_id=user_id,
        account_id=None,
        file_hash=file_hash,
        storage_key="statements/moomoo-fail.pdf",
        content=b"%PDF-1.7",
        model=None,
        session_maker=create_session_maker_from_db(db),
    )

    db.expire_all()
    refreshed = await db.get(StatementSummary, statement_id)

    assert refreshed is not None
    assert refreshed.status == BankStatementStatus.PARSED
    assert refreshed.validation_error is not None
    assert refreshed.validation_error.startswith("existing parser note; ")
    assert "Brokerage import failed" in refreshed.validation_error
    assert "forced import failure" not in refreshed.validation_error
