"""AC-extraction.2504.1: a CSV that declares both balances routes by its own reconciliation (#2504).

#2481 marks a CSV with both declared balances as `declared_in_csv_export`. The blocking LLM-LED balance gate
exempted only `missing_from_csv_export`. A declared CSV whose balances did not reconcile was then quarantined:
no rows and a message that told the user to retry the parse. The user cannot fix a CSV file by a retry.
A declared CSV that does not reconcile stays reviewable. It keeps its rows and records a failed balance check.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from src.extraction.base.result import StatementExtractionResult
from src.extraction.base.types import DocumentSource
from src.extraction.extension.service import ExtractionService

DECLARED_HEADER = (
    "Statement Currency,Statement Period Start,Statement Period End,"
    "Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"
)
# The upload of the confidence journey (tests/e2e/test_confidence_metrics_journey.py, checkpoint U13).
JOURNEY_HEADER = "Statement Currency,Statement Opening Balance,Statement Closing Balance,Date,Description,Amount"

RECONCILED = f"{DECLARED_HEADER}\nSGD,2025-01-01,2025-01-31,100.00,125.00,2025-01-15,Interest,25.00\n"
UNRECONCILED = f"{DECLARED_HEADER}\nSGD,2025-01-01,2025-01-31,100.00,999.00,2025-01-15,Interest,25.00\n"
JOURNEY_UPLOAD = f"{JOURNEY_HEADER}\nSGD,20000.00,99999.00,2026-02-10,Unverified Expense,-500.00\n"
NO_BALANCES = "Date,Description,Amount\n2025-01-15,Interest,25.00\n"


async def _parse(text: str) -> StatementExtractionResult:
    return await ExtractionService().parse_document(
        DocumentSource.resolve(path=Path("/tmp/declared.csv"), content=text.encode(), filename="declared.csv"),
        "Example Bank",
        user_id=uuid4(),
        file_type="csv",
        account_id=uuid4(),
        db=None,
    )


@pytest.mark.parametrize("text", [UNRECONCILED, JOURNEY_UPLOAD], ids=["opening-100-closing-999", "journey-upload"])
async def test_AC_extraction_2504_1_an_unreconciled_declared_csv_stays_reviewable(text: str) -> None:
    result = await _parse(text)

    assert len(result.transactions) == 1
    assert result.balance_validated is False
    assert result.confidence < Decimal("0.5")
    assert not any("llm_led" in reason for reason in result.review_reasons)
    assert not any("Retry parsing" in reason for reason in result.review_reasons)


async def test_AC_extraction_2504_1_an_unreconciled_declared_csv_names_the_failed_balance_check() -> None:
    result = await _parse(UNRECONCILED)

    assert result.review_reasons == ("Balance mismatch: expected 125.00, got 999.00",)


async def test_AC_extraction_2504_1_a_reconciled_declared_csv_keeps_its_confidence() -> None:
    result = await _parse(RECONCILED)

    assert len(result.transactions) == 1
    assert result.balance_validated is True
    assert result.confidence == Decimal("0.8")


async def test_AC_extraction_2504_1_a_csv_without_declared_balances_stays_unproven() -> None:
    result = await _parse(NO_BALANCES)

    assert len(result.transactions) == 1
    assert result.balance_validated is None
    assert result.confidence == Decimal("0.25")
