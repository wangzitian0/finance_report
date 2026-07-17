"""Contract tests for the extraction package's source-to-fact narrow waist."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.extraction import (
    SOURCE_CAPABILITIES,
    DocumentSource,
    ExtractedPositionFact,
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceCapabilityStatus,
    SourceProvenance,
    StatementBalanceFact,
    StatementEvidenceType,
    StatementExtractionResult,
    StatementSourceType,
)
from src.extraction.extension.service import ExtractionError, ExtractionService


def _complete_result() -> StatementExtractionResult:
    return StatementExtractionResult.create(
        producer_version="extractor@abc123",
        source_content_digest="a" * 64,
        source_type=StatementSourceType.BROKERAGE,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        statement_currency="USD",
        institution="Example Broker",
        account_last4="4321",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 1, 31),
        balances=(
            StatementBalanceFact(
                currency="USD",
                opening=Decimal("100.00"),
                closing=Decimal("125.25"),
            ),
        ),
        transactions=(
            ExtractedTransactionFact(
                fact_id="txn-1",
                transaction_date=date(2026, 1, 12),
                description="Dividend",
                amount=Decimal("25.25"),
                direction="IN",
                currency="USD",
                balance_after=Decimal("125.25"),
                confidence=Decimal("0.97"),
            ),
        ),
        positions=(
            ExtractedPositionFact(
                fact_id="position-1",
                symbol="ACME",
                quantity=Decimal("2.5000"),
                market_value=Decimal("125.25"),
                currency="USD",
                confidence=Decimal("0.93"),
            ),
        ),
        confidence=Decimal("0.96"),
        balance_validated=True,
        warnings=("generated-fixture",),
        review_reasons=("position-import-requires-review",),
        provenance=SourceProvenance(
            intake_mode="pdf",
            method=ExtractionMethod.GOLDEN_FIXTURE,
            provider="fixture-provider",
            model="fixture-model-v1",
        ),
    )


def test_AC_extraction_result_envelope_1_rejects_unknown_versions_and_defaults():
    """AC-extraction.result-envelope.1: incompatible or incomplete facts fail closed."""
    payload = _complete_result().to_payload()

    payload["schema_version"] = "999"
    with pytest.raises(ValueError, match="schema version"):
        StatementExtractionResult.from_payload(payload)

    for field in ("source_type", "confidence", "statement_currency"):
        incomplete = _complete_result().to_payload()
        del incomplete[field]
        with pytest.raises((KeyError, TypeError, ValueError)):
            StatementExtractionResult.from_payload(incomplete)

    incomplete_balance = _complete_result().to_payload()
    del incomplete_balance["balances"][0]["closing"]
    with pytest.raises((KeyError, TypeError, ValueError)):
        StatementExtractionResult.from_payload(incomplete_balance)


def test_AC_extraction_result_envelope_2_round_trips_complete_facts():
    """AC-extraction.result-envelope.2: every typed fact survives exact serialization."""
    result = _complete_result()

    restored = StatementExtractionResult.from_payload(result.to_payload())

    assert restored == result
    assert restored.result_id == result.result_id
    assert restored.content_digest == result.content_digest
    assert restored.positions[0].quantity == Decimal("2.5000")
    assert restored.transactions[0].balance_after == Decimal("125.25")
    assert restored.balances[0].closing == Decimal("125.25")
    assert restored.statement_currency == "USD"
    assert restored.provenance.model == "fixture-model-v1"


def test_AC_extraction_result_envelope_2_uses_evidence_type_for_promotion_requirements():
    """Broker identity does not decide whether a source requires positions or cash balances."""
    brokerage_cash_ledger = replace(
        _complete_result(),
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        positions=(),
    )
    position_snapshot = replace(
        brokerage_cash_ledger,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        period_start=None,
        period_end=None,
        balances=(),
    )

    assert brokerage_cash_ledger.missing_required_facts == ()
    assert position_snapshot.missing_required_facts == ("period", "positions")
    assert position_snapshot.requires_review is True


def test_AC_extraction_result_envelope_2_reads_legacy_payload_without_weakening_new_contract():
    """Schema-v1 metadata remains readable while schema-v2 requires explicit evidence type."""
    legacy = replace(_complete_result(), schema_version="1")
    legacy_payload = legacy.to_payload()

    assert "evidence_type" not in legacy_payload
    assert StatementExtractionResult.from_payload(legacy_payload) == legacy

    invalid_v2 = _complete_result().to_payload()
    del invalid_v2["evidence_type"]
    with pytest.raises(ValueError, match="evidence_type"):
        StatementExtractionResult.from_payload(invalid_v2)


def test_AC_extraction_result_envelope_1_keeps_missing_source_facts_explicit():
    """CSV and position snapshots cannot manufacture period, balance, or currency facts."""
    result = StatementExtractionResult.create(
        producer_version="csv-parser@1",
        source_content_digest="b" * 64,
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        institution="Example Bank",
        account_last4=None,
        period_start=None,
        period_end=None,
        balances=(),
        transactions=(
            ExtractedTransactionFact(
                fact_id="export-row-1",
                transaction_date=date(2026, 2, 1),
                description="Unqualified export row",
                amount=Decimal("10.00"),
                direction="IN",
                currency=None,
                balance_after=None,
                confidence=None,
            ),
        ),
        positions=(),
        confidence=Decimal("0.70"),
        balance_validated=None,
        warnings=(),
        review_reasons=("source facts require confirmation",),
        provenance=SourceProvenance(
            intake_mode="csv",
            method=ExtractionMethod.DETERMINISTIC,
            provider="csv-parser",
            model="csv-parser@1",
        ),
    )

    assert result.missing_required_facts == ("statement_currency", "period", "balances", "transaction_currency")
    assert result.to_payload()["statement_currency"] is None
    assert result.to_payload()["balances"] == []
    assert result.to_payload()["transactions"][0]["currency"] is None


def test_AC_extraction_result_envelope_1_accepts_source_declared_multi_currency_balances():
    """A ledger's exact balance buckets declare currency without inventing a scalar default."""
    result = replace(
        _complete_result(),
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        statement_currency=None,
        balances=(
            StatementBalanceFact(currency="USD", opening=Decimal("100.00"), closing=Decimal("125.25")),
            StatementBalanceFact(currency="SGD", opening=Decimal("200.00"), closing=Decimal("250.00")),
        ),
        positions=(),
    )

    assert result.to_payload()["statement_currency"] is None
    assert result.missing_required_facts == ()


def test_AC_extraction_11_1_partial_period_rejects_without_copying():
    """AC-extraction.11.1: a lone period bound is malformed source evidence."""
    with pytest.raises(ValueError, match="period bounds must both be present or both be absent"):
        replace(_complete_result(), period_start=None)


def test_AC_extraction_11_2_transaction_dates_do_not_establish_statement_period():
    """AC-extraction.11.2: dated rows cannot promote an absent source period."""
    result = replace(_complete_result(), period_start=None, period_end=None)

    assert result.transactions[0].transaction_date == date(2026, 1, 12)
    assert result.period_start is None
    assert result.period_end is None
    assert result.missing_required_facts == ("period",)
    assert result.requires_review is True


async def test_AC_extraction_11_3_missing_transaction_date_rejects():
    """AC-extraction.11.3: row dates are source facts and cannot be synthesized."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "Example Bank",
            "transactions": [
                {
                    "description": "Undated row",
                    "amount": "10.00",
                    "direction": "IN",
                }
            ],
        }
    )

    with pytest.raises(ExtractionError, match="date or amount"):
        await service.parse_document(
            DocumentSource.resolve(path=Path("undated-live.pdf"), content=b"undated-live"),
            institution="Example Bank",
            user_id=uuid4(),
        )


async def test_AC_extraction_result_envelope_1_live_missing_facts_are_review_only():
    """A partial live parse is retained as source evidence, never rejected or promoted."""
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "Example Bank",
            "transactions": [
                {
                    "date": "2026-02-01",
                    "description": "Unqualified live row",
                    "amount": "10.00",
                    "direction": "IN",
                },
            ],
        }
    )

    result = await service.parse_document(
        DocumentSource.resolve(path=Path("partial-live.pdf"), content=b"partial-live"),
        institution="Example Bank",
        user_id=uuid4(),
    )

    assert result.missing_required_facts == ("statement_currency", "period", "balances", "transaction_currency")
    assert result.balance_validated is None
    assert result.confidence <= Decimal("0.59")
    assert result.review_reasons == (
        "Source is missing required facts: statement currency, statement period, opening and closing balances, transaction currency",
    )


def test_AC_extraction_source_capability_1_declares_semantics_not_test_paths():
    """AC-extraction.source-capability.1: capability truth is semantic product data."""
    by_id = {capability.capability_id: capability for capability in SOURCE_CAPABILITIES}

    assert by_id["settlement_note"].status is SourceCapabilityStatus.GAP
    assert by_id["csv_export"].status is SourceCapabilityStatus.MANUAL_TRUSTED
    assert "pytest" not in repr(SOURCE_CAPABILITIES).lower()
