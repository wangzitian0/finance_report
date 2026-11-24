"""Log fields of the extraction path (#2985)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import structlog
from structlog.testing import capture_logs

from src.config import settings
from src.database import create_session_maker_from_db
from src.extraction import DocumentSource, DocumentType, TransactionDirection
from src.extraction.base.types import ExtractedTransactionRow
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.service import ExtractionService
from src.extraction.extension.statement_parsing_supervisor import reap_stale_parsing_runs
from src.extraction.extension.statement_runs import DEFAULT_STALE_AFTER
from tests.extraction.test_statement_parsing_supervisor import _running_statement


def _events(logs: list[dict], name: str) -> list[dict]:
    return [entry for entry in logs if entry["event"] == name]


async def test_AC_extraction_2985_1_2_3_model_call_and_merge_log_fields():
    service = ExtractionService()
    parts = [
        {"institution": "DBS", "account_last4": "1234", "currency": "SGD"},
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

    with (
        patch.object(
            service, "_extract_json_with_model", AsyncMock(return_value={"transactions": [{"amount": "1.00"}]})
        ),
        capture_logs() as logs2,
    ):
        await service._extract_json_from_media_batches(
            media_batches=[[{"page": 1}, {"page": 2}]], model="m", prompt="p", seed_override=None, user_id=None
        )
    (call,) = _events(logs2, "statement.extraction.call_completed")
    assert (call["batch_index"], call["batch_count"], call["pages"], call["rows"]) == (1, 1, 2, 1)

    parts_err = [
        {"account_last4": "1234"},
        {"transactions": []},
        {"account_last4": "5678"},
        {"account_last4": "XX-1234"},
    ]
    with patch.object(service, "_extract_json_with_model", AsyncMock(side_effect=parts_err)), capture_logs() as logs3:
        merged, _ = await service._extract_json_from_media_batches(
            media_batches=[[{"page": 1}], [{"page": 2}], [{"page": 3}]],
            model="m",
            prompt="p",
            seed_override=None,
            user_id=None,
        )
    (entry,) = _events(logs3, "Multiple accounts in paged extraction")
    assert entry["parts_by_account"] == {"1234": [0, 3], "5678": [2]}
    assert [acct["account_last4"] for acct in merged["accounts"]] == ["1234", "5678"]


async def test_AC_extraction_2985_4_the_quarantine_log_holds_row_count_gap_directions_and_suspect_rows(tmp_path):
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
            {"date": "2025-01-15", "description": f"row {i}", "amount": a, "direction": d}
            for i, (a, d) in enumerate(rows)
        ],
    }
    service = ExtractionService()
    with patch.object(service, "extract_financial_data", AsyncMock(return_value=payload)), capture_logs() as logs:
        await service.parse_document(DocumentSource.resolve(path=pdf, content=b"dummy"), "DBS", user_id=uuid4())
    (entry,) = [e for e in logs if str(e["event"]).startswith("LLM-LED invariant gate quarantined")]
    rest = str({k: v for k, v in entry.items() if k != "balance_gap"})
    assert (entry["row_count"], entry["balance_gap"], entry["in_count"], entry["out_count"], entry["suspect_rows"]) == (
        4,
        "700.00",
        2,
        2,
        [1, 3],
    )
    assert all(a not in rest for a in ("100.00", "50.00", "350.00")) and "row 1" not in rest


async def test_AC_extraction_2985_5_6_7_watchdog_attempt_and_silent_atomic_upsert(db, test_user):
    statement = await _running_statement(
        db, test_user, file_hash=f"age-{uuid4()}", heartbeat_age=DEFAULT_STALE_AFTER + timedelta(minutes=2)
    )
    with capture_logs() as logs:
        await reap_stale_parsing_runs(create_session_maker_from_db(db))
    (entry,) = [
        e for e in _events(logs, "statement.parsing.watchdog_timeout") if e["statement_id"] == str(statement.id)
    ]
    assert (
        entry["age_seconds"] >= int(DEFAULT_STALE_AFTER.total_seconds()) + 120
        and entry["error_code"] == "heartbeat_lost"
    )

    seen: list[int | None] = []

    async def fake_extract(**_kwargs):
        seen.append(structlog.contextvars.get_contextvars().get("extract_attempt"))
        amount = Decimal("100.00") - Decimal("12.50" if len(seen) == 1 else "0")
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
            file_content=b"x", institution=None, file_type="pdf", file_url=None, filename="s.pdf"
        )
    assert seen == [1, 2] and "extract_attempt" not in structlog.contextvars.get_contextvars()

    dedup = DeduplicationService()
    row = ExtractedTransactionRow(
        user_id=test_user.id,
        txn_date=date(2024, 1, 15),
        amount=Decimal("123.45"),
        direction=TransactionDirection.IN.value,
        description="Test Transaction",
        reference=None,
        currency="USD",
        currency_unresolved=False,
        balance_after=None,
        occurrence_index=0,
        dedup_hash=dedup.calculate_transaction_hash(
            test_user.id, date(2024, 1, 15), Decimal("123.45"), TransactionDirection.IN, "Test Transaction"
        ),
    )
    with capture_logs() as txn_logs:
        txn = await dedup.upsert_scoped_atomic_transaction(
            db=db, row=row, source_doc_id=uuid4(), source_doc_type=DocumentType.BANK_STATEMENT
        )
    assert (
        txn.id is not None
        and not [e for e in txn_logs if "atomic transaction" in str(e["event"]).lower()]
        and "123.45" not in str(txn_logs)
    )
