"""Tests for the statement upload to brokerage position import bridge."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.database import create_session_maker_from_db
from src.models import BankStatement, BankStatementStatus, BankStatementTransaction
from src.models.layer2 import AtomicPosition
from src.models.layer3 import ManagedPosition
from src.services.brokerage_positions import looks_like_brokerage_payload, parse_brokerage_positions
from src.services.extraction import ExtractionService
from src.services.statement_parsing import import_brokerage_payload_if_present, parse_statement_background


def _parsed_statement(user_id, file_hash: str) -> BankStatement:
    return BankStatement(
        user_id=user_id,
        file_path="moomoo-positions.pdf",
        file_hash=file_hash,
        original_filename="moomoo-positions.pdf",
        institution="Moomoo",
        account_last4="1234",
        currency="USD",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 18),
        opening_balance=Decimal("0.00"),
        closing_balance=Decimal("0.00"),
        status=BankStatementStatus.PARSED,
        confidence_score=90,
        balance_validated=True,
    )


def _brokerage_payload() -> dict:
    return {
        "institution": "Moomoo",
        "period_start": "2026-05-01",
        "period_end": "2026-05-18",
        "statement": {"period_end": "2026-05-18", "currency": "USD"},
        "positions": [
            {
                "symbol": "AAPL",
                "snapshot_date": date(2026, 5, 18),
                "quantity": "10",
                "market_value": "1900.25",
                "currency": "USD",
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
    """AC8.13.10/Issue #409: Non-standard signed directions normalize deterministically."""
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
                    "amount": "-500.00",
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
async def test_import_brokerage_payload_if_present_ignores_bank_payload(db, test_user, monkeypatch):
    """AC17.4.7: Bank statement payloads do not call brokerage import."""
    statement = _parsed_statement(test_user.id, "bank-hash")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("brokerage import should not be called for bank payloads")

    monkeypatch.setattr("src.services.statement_parsing._brokerage_import_service.import_positions", fail_if_called)

    await import_brokerage_payload_if_present(
        statement=statement,
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
    statement = BankStatement(
        id=statement_id,
        user_id=test_user.id,
        status=BankStatementStatus.PARSED,
        file_path="statements/futu-empty.pdf",
        file_hash="futu-empty-hash",
        original_filename="futu-empty.pdf",
        institution="Futu",
    )
    db.add(statement)
    await db.commit()

    await import_brokerage_payload_if_present(
        statement=statement,
        db=db,
        user_id=test_user.id,
        filename="futu-empty.pdf",
        institution="Futu",
        payload={"institution": "Futu", "positions": []},
    )

    db.expire_all()
    refreshed = await db.get(BankStatement, statement_id)

    assert refreshed is not None
    assert refreshed.validation_error is not None
    assert "no positions detected" in refreshed.validation_error


@pytest.mark.asyncio
async def test_parse_statement_background_imports_brokerage_positions(db, test_user, monkeypatch):
    """AC17.4.7: Parsed brokerage uploads import positions without a manual API call."""
    statement_id = uuid4()
    user_id = test_user.id
    file_hash = "brokerage-success-hash"
    statement = BankStatement(
        id=statement_id,
        user_id=user_id,
        status=BankStatementStatus.PARSING,
        file_path="statements/moomoo.pdf",
        file_hash=file_hash,
        original_filename="moomoo-positions.pdf",
        institution="Moomoo",
    )
    statement.transactions = [
        BankStatementTransaction(
            txn_date=date(2026, 5, 17),
            description="stale transaction",
            amount=Decimal("1.00"),
            direction="IN",
        )
    ]
    db.add(statement)
    await db.commit()

    async def fake_parse_document(*args, **kwargs):
        parsed = _parsed_statement(user_id, file_hash)
        parsed._extracted_payload = _brokerage_payload()
        return parsed, []

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
    refreshed = await db.get(BankStatement, statement_id)

    assert refreshed is not None
    assert refreshed.status == BankStatementStatus.PARSED
    assert refreshed.validation_error is None
    assert len(atomic_rows) == 1
    assert atomic_rows[0].asset_identifier == "AAPL"
    assert atomic_rows[0].source_documents["documents"][0]["doc_id"] == str(statement_id)
    assert len(managed_rows) == 1
    assert managed_rows[0].asset_identifier == "AAPL"
    assert managed_rows[0].quantity == Decimal("10")


@pytest.mark.asyncio
async def test_parse_statement_background_persists_brokerage_import_failure(db, test_user, monkeypatch):
    """AC17.4.7: Brokerage import failures are visible on the parsed statement."""
    statement_id = uuid4()
    user_id = test_user.id
    file_hash = "brokerage-failure-hash"
    statement = BankStatement(
        id=statement_id,
        user_id=user_id,
        status=BankStatementStatus.PARSING,
        file_path="statements/moomoo-fail.pdf",
        file_hash=file_hash,
        original_filename="moomoo-fail.pdf",
        institution="Moomoo",
    )
    db.add(statement)
    await db.commit()

    async def fake_parse_document(*args, **kwargs):
        parsed = _parsed_statement(user_id, file_hash)
        parsed._extracted_payload = _brokerage_payload()
        parsed.validation_error = "existing parser note"
        return parsed, []

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
    refreshed = await db.get(BankStatement, statement_id)

    assert refreshed is not None
    assert refreshed.status == BankStatementStatus.PARSED
    assert refreshed.validation_error is not None
    assert refreshed.validation_error.startswith("existing parser note; ")
    assert "Brokerage import failed" in refreshed.validation_error
    assert "forced import failure" not in refreshed.validation_error
