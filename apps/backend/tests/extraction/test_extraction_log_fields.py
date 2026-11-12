"""Log fields of the extraction path (#2985).

Evidence of the run of 2026-11-11 on staging: for a failed statement the logs showed neither
which batch call was slow, nor the account suffixes that the merge compared, nor the delta
and the suspect rows of a quarantined credit card. A parse also wrote one INFO line with the
amount for every row, which hid the lines above.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import structlog
from structlog.testing import capture_logs

from src.config import settings
from src.extraction import BankStatementStatus, DocumentSource, DocumentType, TransactionDirection
from src.extraction.base.types import ExtractedTransactionRow
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing_supervisor import reap_stale_parsing_runs
from src.extraction.extension.statement_runs import DEFAULT_STALE_AFTER
from tests.factories import StatementSummaryFactory


def _events(logs: list[dict], name: str) -> list[dict]:
    return [entry for entry in logs if entry["event"] == name]


async def test_AC_extraction_2985_1_each_model_call_logs_batch_pages_rows_and_duration():
    """AC-extraction.2985.1: Every model call of a paged extraction logs its batch, pages, rows and duration."""
    service = ExtractionService()
    meta = {"institution": "DBS", "account_last4": "1234", "currency": "SGD"}
    parts = [
        meta,
        {"transactions": [{"amount": "1.00"}, {"amount": "2.00"}]},
        {"transactions": [{"amount": "3.00"}]},
        {"transactions": []},
    ]
    batches = [[{"page": n} for n in range(first, first + size)] for first, size in ((1, 5), (6, 5), (11, 2))]
    with patch.object(service, "_extract_json_with_model", AsyncMock(side_effect=parts)), capture_logs() as logs:
        await service._extract_json_from_media_batches(
            media_batches=batches, model="m", prompt="p", seed_override=None, user_id=None
        )
    calls = _events(logs, "statement.extraction.call_completed")
    assert [(c["batch_index"], c["batch_count"], c["pages"], c["rows"]) for c in calls] == [
        (0, 3, 10, 0),
        (1, 3, 5, 2),
        (2, 3, 5, 1),
        (3, 3, 2, 0),
    ]
    assert all(isinstance(c["duration_ms"], int) and c["duration_ms"] >= 0 for c in calls)


async def test_AC_extraction_2985_2_a_single_batch_call_logs_the_same_fields():
    """AC-extraction.2985.2: A one-batch extraction logs one call with batch 1 of 1."""
    service = ExtractionService()
    part = {"transactions": [{"amount": "1.00"}]}
    with patch.object(service, "_extract_json_with_model", AsyncMock(return_value=part)), capture_logs() as logs:
        await service._extract_json_from_media_batches(
            media_batches=[[{"page": 1}, {"page": 2}]], model="m", prompt="p", seed_override=None, user_id=None
        )
    (call,) = _events(logs, "statement.extraction.call_completed")
    assert (call["batch_index"], call["batch_count"], call["pages"], call["rows"]) == (1, 1, 2, 1)


async def test_AC_extraction_2985_3_the_merge_logs_the_account_suffixes_with_their_part_index():
    """AC-extraction.2985.3: A merge of two accounts logs each suffix with the parts that reported it."""
    service = ExtractionService()
    parts = [{"account_last4": "1234"}, {"transactions": []}, {"account_last4": "5678"}, {"account_last4": "XX-1234"}]
    batches = [[{"page": 1}], [{"page": 2}], [{"page": 3}]]
    with patch.object(service, "_extract_json_with_model", AsyncMock(side_effect=parts)), capture_logs() as logs:
        with pytest.raises(ValueError, match="Multiple accounts"):
            await service._extract_json_from_media_batches(
                media_batches=batches, model="m", prompt="p", seed_override=None, user_id=None
            )
    (entry,) = _events(logs, "Multiple accounts in paged extraction")
    assert entry["parts_by_account"] == {"1234": [0, 3], "5678": [2]}


async def test_AC_extraction_2985_4_the_quarantine_log_holds_row_count_gap_directions_and_suspect_rows(tmp_path):
    """AC-extraction.2985.4: A quarantined statement logs row count, gap, IN and OUT counts and suspect rows."""
    pdf = tmp_path / "card.pdf"
    pdf.write_bytes(b"dummy")
    rows = [("100.00", "IN"), ("700.00", "IN"), ("50.00", "OUT"), ("350.00", "OUT")]
    payload = {
        "institution": "DBS",
        "account_last4": "1234",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "1000.00",
        "closing_balance": "700.00",
        "transactions": [
            {"date": "2025-01-15", "description": f"row {i}", "amount": amount, "direction": direction}
            for i, (amount, direction) in enumerate(rows)
        ],
    }
    service = ExtractionService()
    with patch.object(service, "extract_financial_data", AsyncMock(return_value=payload)), capture_logs() as logs:
        await service.parse_document(DocumentSource.resolve(path=pdf, content=b"dummy"), "DBS", user_id=uuid4())
    (entry,) = [e for e in logs if str(e["event"]).startswith("LLM-LED invariant gate quarantined")]
    assert entry["row_count"] == 4
    assert entry["balance_gap"] == "700.00"
    assert (entry["in_count"], entry["out_count"]) == (2, 2)
    assert entry["suspect_rows"] == [1, 3]
    rest = str({key: value for key, value in entry.items() if key != "balance_gap"})
    assert not [amount for amount in ("100.00", "50.00", "350.00") if amount in rest]
    assert "row 1" not in rest


async def test_AC_extraction_2985_5_the_watchdog_log_holds_the_age_of_the_row(db, test_user):
    """AC-extraction.2985.5: The watchdog timeout log holds the age of the run heartbeat in seconds."""
    from src.database import create_session_maker_from_db
    from tests.extraction.test_statement_parsing_supervisor import _running_statement

    statement = await _running_statement(
        db, test_user, file_hash=f"age-{uuid4()}", heartbeat_age=DEFAULT_STALE_AFTER + timedelta(minutes=2)
    )
    with capture_logs() as logs:
        await reap_stale_parsing_runs(create_session_maker_from_db(db))
    (entry,) = [
        e for e in _events(logs, "statement.parsing.watchdog_timeout") if e["statement_id"] == str(statement.id)
    ]
    assert entry["age_seconds"] >= int(DEFAULT_STALE_AFTER.total_seconds()) + 120
    assert entry["error_code"] == "heartbeat_lost"


async def test_AC_extraction_2985_6_every_log_line_of_a_pass_carries_the_attempt_number():
    """AC-extraction.2985.6: The attempt number is bound while a pass runs and unbound after the loop."""
    seen: list[int | None] = []

    async def fake_extract(**_kwargs):
        seen.append(structlog.contextvars.get_contextvars().get("extract_attempt"))
        diff = "12.50" if len(seen) == 1 else "0"
        amount = Decimal("100.00") - Decimal(diff)
        return {
            "institution": "DBS",
            "period_start": "2025-01-01",
            "period_end": "2025-01-31",
            "opening_balance": "0.00",
            "closing_balance": "100.00",
            "currency": "SGD",
            "transactions": [{"date": "2025-01-10", "amount": f"{amount:.2f}", "direction": "IN", "currency": "SGD"}],
        }

    service = ExtractionService()
    with (
        patch.object(settings, "ai_extract_max_attempts", 2),
        patch.object(service, "extract_financial_data", fake_extract),
    ):
        await service._extract_with_balance_retry(
            file_content=b"x", institution=None, file_type="pdf", file_url=None, force_model=None, filename="s.pdf"
        )
    assert seen == [1, 2]
    assert "extract_attempt" not in structlog.contextvars.get_contextvars()


async def test_AC_extraction_2985_7_creating_an_atomic_transaction_writes_no_per_row_log(db, test_user):
    """AC-extraction.2985.7: One upserted row writes neither a created line nor its amount to the log."""
    service = DeduplicationService()
    amount = Decimal("123.45")
    row = ExtractedTransactionRow(
        user_id=test_user.id,
        txn_date=date(2024, 1, 15),
        amount=amount,
        direction=TransactionDirection.IN.value,
        description="Test Transaction",
        reference=None,
        currency="USD",
        currency_unresolved=False,
        balance_after=None,
        occurrence_index=0,
        dedup_hash=service.calculate_transaction_hash(
            test_user.id, date(2024, 1, 15), amount, TransactionDirection.IN, "Test Transaction"
        ),
    )
    with capture_logs() as logs:
        txn = await service.upsert_scoped_atomic_transaction(
            db=db, row=row, source_doc_id=uuid4(), source_doc_type=DocumentType.BANK_STATEMENT
        )
    assert txn.id is not None
    assert not [e for e in logs if "atomic transaction" in str(e["event"]).lower()]
    assert "123.45" not in str(logs)
