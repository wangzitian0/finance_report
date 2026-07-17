"""Contract tests for the extraction package's source-to-fact narrow waist."""

from datetime import date
from decimal import Decimal

import pytest

from src.extraction import (
    SOURCE_CAPABILITIES,
    ExtractedPositionFact,
    ExtractedTransactionFact,
    ExtractionMethod,
    SourceCapabilityStatus,
    SourceProvenance,
    StatementBalanceFact,
    StatementExtractionResult,
    StatementSourceType,
)


def _complete_result() -> StatementExtractionResult:
    return StatementExtractionResult.create(
        producer_version="extractor@abc123",
        source_content_digest="a" * 64,
        source_type=StatementSourceType.BROKERAGE,
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

    for field in ("source_type", "confidence"):
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
    assert restored.provenance.model == "fixture-model-v1"


def test_AC_extraction_result_envelope_1_keeps_missing_source_facts_explicit():
    """CSV and position snapshots cannot manufacture period, balance, or currency facts."""
    result = StatementExtractionResult.create(
        producer_version="csv-parser@1",
        source_content_digest="b" * 64,
        source_type=StatementSourceType.BANK,
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

    assert result.missing_required_facts == ("period", "balances", "transaction_currency")
    assert result.to_payload()["balances"] == []
    assert result.to_payload()["transactions"][0]["currency"] is None


def test_AC_extraction_source_capability_1_declares_semantics_not_test_paths():
    """AC-extraction.source-capability.1: capability truth is semantic product data."""
    by_id = {capability.capability_id: capability for capability in SOURCE_CAPABILITIES}

    assert by_id["settlement_note"].status is SourceCapabilityStatus.GAP
    assert by_id["csv_export"].status is SourceCapabilityStatus.MANUAL_TRUSTED
    assert "pytest" not in repr(SOURCE_CAPABILITIES).lower()
