from __future__ import annotations

import os
import subprocess
import sys
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
    SourceCapability,
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
        balances=(StatementBalanceFact(currency="USD", opening=Decimal("100.00"), closing=Decimal("125.25")),),
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


def test_AC_extraction_result_envelope_2_round_trips_and_missing_facts():
    result = _complete_result()
    restored = StatementExtractionResult.from_payload(result.to_payload())
    assert (
        restored == result,
        restored.result_id,
        restored.content_digest,
        restored.positions[0].quantity,
        restored.transactions[0].balance_after,
        restored.balances[0].closing,
        restored.statement_currency,
        restored.provenance.model,
    ) == (
        True,
        result.result_id,
        result.content_digest,
        Decimal("2.5000"),
        Decimal("125.25"),
        Decimal("125.25"),
        "USD",
        "fixture-model-v1",
    )

    cash_ledger = replace(result, evidence_type=StatementEvidenceType.TRANSACTION_LEDGER, positions=())
    pos_snap = replace(
        cash_ledger,
        evidence_type=StatementEvidenceType.POSITION_SNAPSHOT,
        period_start=None,
        period_end=None,
        balances=(),
    )
    legacy = replace(result, schema_version="1")
    legacy_payload = legacy.to_payload()
    assert (
        cash_ledger.missing_required_facts,
        pos_snap.missing_required_facts,
        pos_snap.requires_review,
        "evidence_type" not in legacy_payload,
        StatementExtractionResult.from_payload(legacy_payload) == legacy,
    ) == ((), ("period", "positions"), True, True, True)
    invalid_v2 = result.to_payload()
    del invalid_v2["evidence_type"]
    with pytest.raises(ValueError, match="evidence_type"):
        StatementExtractionResult.from_payload(invalid_v2)

    unqualified = StatementExtractionResult.create(
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
            intake_mode="csv", method=ExtractionMethod.DETERMINISTIC, provider="csv-parser", model="csv-parser@1"
        ),
    )
    up = unqualified.to_payload()
    assert (
        unqualified.missing_required_facts,
        up["statement_currency"],
        up["balances"],
        up["transactions"][0]["currency"],
    ) == (("statement_currency", "period", "balances", "transaction_currency"), None, [], None)

    multi_ccy = replace(
        result,
        source_type=StatementSourceType.BANK,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        statement_currency=None,
        balances=(
            StatementBalanceFact("USD", Decimal("100.00"), Decimal("125.25")),
            StatementBalanceFact("SGD", Decimal("200.00"), Decimal("250.00")),
        ),
        positions=(),
    )
    assert (multi_ccy.to_payload()["statement_currency"], multi_ccy.missing_required_facts) == (None, ())


def test_AC_extraction_11_1_2_period_guards():
    with pytest.raises(ValueError, match="period bounds must both be present or both be absent"):
        replace(_complete_result(), period_start=None)
    result = replace(_complete_result(), period_start=None, period_end=None)
    assert (
        result.transactions[0].transaction_date,
        result.period_start,
        result.period_end,
        result.missing_required_facts,
        result.requires_review,
    ) == (date(2026, 1, 12), None, None, ("period",), True)


async def test_AC_extraction_11_3_missing_transaction_date_rejects_and_unqualified_needs_review():
    service = ExtractionService()
    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "Example Bank",
            "transactions": [{"description": "Undated row", "amount": "10.00", "direction": "IN"}],
        }
    )
    with pytest.raises(ExtractionError, match="date or amount"):
        await service.parse_document(
            DocumentSource.resolve(path=Path("undated-live.pdf"), content=b"undated-live"),
            institution="Example Bank",
            user_id=uuid4(),
        )

    service.extract_financial_data = AsyncMock(
        return_value={
            "institution": "Example Bank",
            "transactions": [
                {"date": "2026-02-01", "description": "Unqualified live row", "amount": "10.00", "direction": "IN"}
            ],
        }
    )
    res = await service.parse_document(
        DocumentSource.resolve(path=Path("partial-live.pdf"), content=b"partial-live"),
        institution="Example Bank",
        user_id=uuid4(),
    )
    assert (
        res.missing_required_facts,
        res.balance_validated,
        res.confidence <= Decimal("0.59"),
        res.review_reasons,
    ) == (
        ("statement_currency", "period", "balances", "transaction_currency"),
        None,
        True,
        (
            "Source is missing required facts: statement currency, statement period, opening and closing balances, transaction currency",
        ),
    )


def test_AC_extraction_source_capability_1_declares_semantics_not_test_paths():
    by_id = {c.capability_id: c for c in SOURCE_CAPABILITIES}
    assert len(by_id) == len(SOURCE_CAPABILITIES) and "pytest" not in repr(SOURCE_CAPABILITIES).lower()
    assert {cid: c.status for cid, c in by_id.items()} == {
        "bank_statement": SourceCapabilityStatus.SUPPORTED,
        "brokerage_statement": SourceCapabilityStatus.SUPPORTED,
        "csv_export": SourceCapabilityStatus.MANUAL_TRUSTED,
        "esop_rsu_plan": SourceCapabilityStatus.MANUAL_TRUSTED,
        "liability_statement": SourceCapabilityStatus.MANUAL_TRUSTED,
        "manual_record": SourceCapabilityStatus.MANUAL_TRUSTED,
        "property_statement": SourceCapabilityStatus.MANUAL_TRUSTED,
        "settlement_note": SourceCapabilityStatus.GAP,
    }
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    completed = subprocess.run(
        [sys.executable, "-c", "from src.extraction.base.result import SOURCE_CAPABILITIES"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_AC_extraction_result_envelope_1_rejects_malformed_source_facts():
    complete = _complete_result()
    checks = [
        (
            lambda: SourceProvenance("pdf", ExtractionMethod.DETERMINISTIC, " ", "model"),
            ValueError,
            "provider is required",
        ),
        (
            lambda: SourceProvenance("pdf", "deterministic", "provider", "model"),
            TypeError,
            "method must be ExtractionMethod",
        ),
        (
            lambda: StatementBalanceFact("US", Decimal("0"), Decimal("1")),
            ValueError,
            "currency must be a three-letter code",
        ),
        (lambda: StatementBalanceFact("USD", 0, Decimal("1")), TypeError, "balances must use Decimal"),
        (lambda: replace(complete.transactions[0], direction="SIDEWAYS"), ValueError, "transaction direction"),
        (lambda: replace(complete.transactions[0], amount=Decimal("0")), ValueError, "positive Decimal"),
        (lambda: replace(complete.transactions[0], balance_after=0), TypeError, "balance_after must use Decimal"),
        (lambda: replace(complete.transactions[0], confidence=Decimal("1.01")), ValueError, "transaction confidence"),
        (lambda: replace(complete.positions[0], quantity=1), TypeError, "position values must use Decimal"),
        (
            lambda: SourceCapability(
                "invalid", "supported", ("pdf",), ("statement",), ("transaction",), "review", "trace"
            ),
            TypeError,
            "status must be SourceCapabilityStatus",
        ),
        (
            lambda: SourceCapability(
                "invalid",
                SourceCapabilityStatus.SUPPORTED,
                ("pytest",),
                ("statement",),
                ("transaction",),
                "review",
                "trace",
            ),
            ValueError,
            "cannot own test paths",
        ),
        (
            lambda: SourceCapability(
                "invalid", SourceCapabilityStatus.SUPPORTED, ("",), ("statement",), ("transaction",), "review", "trace"
            ),
            ValueError,
            "requires semantic identifiers",
        ),
    ]
    for fn, exc, match in checks:
        with pytest.raises(exc, match=match):
            fn()
    for invalid in (
        {"schema_version": "999"},
        {"source_content_digest": "A" * 64},
        {"source_type": "bank_statement"},
        {"evidence_type": "transaction_ledger"},
        {"account_last4": "12345"},
        {"period_start": date(2026, 2, 1), "period_end": date(2026, 1, 1)},
        {"balances": (complete.balances[0], complete.balances[0])},
        {"confidence": 1},
        {"confidence": Decimal("-0.01")},
        {"warnings": ("",)},
    ):
        with pytest.raises((TypeError, ValueError)):
            replace(complete, **invalid)
    mismatch = complete.to_payload()
    mismatch["content_digest"] = "0" * 64
    with pytest.raises(ValueError, match="identity mismatch"):
        StatementExtractionResult.from_payload(mismatch)
