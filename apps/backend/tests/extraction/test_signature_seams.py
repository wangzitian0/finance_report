"""Contract tests for issue #1866's extraction signature seams."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from inspect import Parameter, getsource, signature
from pathlib import Path
from typing import get_type_hints
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentSource, ExtractedTransactionRow, ParseJob
from src.extraction.extension import statement_parsing, statement_pipeline
from src.extraction.extension.deduplication import DeduplicationService, dual_write_layer2
from src.extraction.extension.service import ExtractionService

pytestmark = pytest.mark.no_db


def _parse_job() -> ParseJob:
    return ParseJob(
        statement_id=uuid4(),
        filename="statement.pdf",
        institution="DBS",
        user_id=uuid4(),
        account_id=uuid4(),
        file_hash="a" * 64,
        storage_key="statements/source.pdf",
        model="vision-model",
        request_id="request-1",
    )


def _valid_payload() -> dict[str, object]:
    return {
        "institution": "DBS",
        "account_last4": "1234",
        "currency": "SGD",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "opening_balance": "0.00",
        "closing_balance": "0.00",
        "transactions": [],
    }


def test_AC_extraction_signature_seams_1_parse_job_round_trips_prefect_params() -> None:
    """AC-extraction.signature-seams.1: ParseJob owns the serializable worker contract."""
    job = _parse_job()

    prefect_params = job.to_prefect_params()

    assert ParseJob.from_prefect_params(prefect_params) == job
    assert set(prefect_params) == {
        "statement_id",
        "filename",
        "institution",
        "user_id",
        "account_id",
        "file_hash",
        "storage_key",
        "model",
        "request_id",
    }
    assert all(value is None or isinstance(value, str) for value in prefect_params.values())
    with pytest.raises(FrozenInstanceError):
        job.filename = "mutated.pdf"  # type: ignore[misc]


def test_AC_extraction_signature_seams_2_document_source_resolves_once() -> None:
    """AC-extraction.signature-seams.2: all source aliases resolve into one immutable value."""
    source = DocumentSource.resolve(
        path=Path("statements/storage-key.pdf"),
        content=b"statement-bytes",
        url="https://storage.example/source.pdf",
        content_hash=None,
        filename="January statement.pdf",
    )

    assert source.path == Path("statements/storage-key.pdf")
    assert source.content == b"statement-bytes"
    assert source.url == "https://storage.example/source.pdf"
    assert source.content_hash == "84c100c63b19e58806ef5d6b164adc8c8f9e94808a4261415982b1948d0f0e11"
    assert source.filename == "January statement.pdf"
    with pytest.raises(FrozenInstanceError):
        source.filename = "mutated.pdf"  # type: ignore[misc]


async def test_AC_extraction_signature_seams_3_csv_and_vision_paths_are_separate() -> None:
    """AC-extraction.signature-seams.3: parse_document dispatches to explicit source paths."""
    service = ExtractionService()
    payload = _valid_payload()
    service._extract_csv_source = AsyncMock(return_value=payload)
    service._extract_vision_source = AsyncMock(return_value=payload)

    csv_source = DocumentSource.resolve(path=Path("statement.csv"), content=b"csv")
    await service.parse_document(
        csv_source,
        institution="DBS",
        user_id=uuid4(),
        file_type="csv",
    )
    service._extract_csv_source.assert_awaited_once_with(csv_source, institution="DBS")
    service._extract_vision_source.assert_not_awaited()

    service._extract_csv_source.reset_mock()
    vision_source = DocumentSource.resolve(path=Path("statement.pdf"), content=b"pdf")
    await service.parse_document(
        vision_source,
        institution="DBS",
        user_id=uuid4(),
        file_type="pdf",
    )
    service._extract_vision_source.assert_awaited_once()
    service._extract_csv_source.assert_not_awaited()


async def test_AC_extraction_signature_seams_4_typed_rows_and_failure_contract() -> None:
    """AC-extraction.signature-seams.4: typed rows replace ORM stowaways at the DB seam."""
    service = ExtractionService()
    payload = _valid_payload()
    payload["closing_balance"] = "10.00"
    payload["transactions"] = [
        {
            "date": "2026-01-05",
            "amount": "10.00",
            "direction": "IN",
            "description": "Deposit",
            "currency": "SGD",
            "balance_after": "10.00",
        }
    ]
    service._extract_csv_source = AsyncMock(return_value=payload)

    _, rows = await service.parse_document(
        DocumentSource.resolve(path=Path("statement.csv"), content=b"csv"),
        institution="DBS",
        user_id=uuid4(),
        file_type="csv",
    )

    assert rows == [
        ExtractedTransactionRow(
            user_id=rows[0].user_id,
            txn_date=date(2026, 1, 5),
            amount=Decimal("10.00"),
            direction=rows[0].direction,
            description="Deposit",
            reference=None,
            currency="SGD",
            currency_unresolved=False,
            balance_after=Decimal("10.00"),
            occurrence_index=0,
            dedup_hash=rows[0].dedup_hash,
        )
    ]
    assert get_type_hints(dual_write_layer2)["db"] is AsyncSession
    assert get_type_hints(ExtractionService.parse_document)["db"] == AsyncSession | None
    assert "_extracted_balance_after" not in getsource(dual_write_layer2)
    assert "_occurrence_index" not in getsource(dual_write_layer2)
    assert "_currency_unresolved" not in getsource(dual_write_layer2)
    assert "signature(" not in getsource(statement_parsing)
    parse_params = signature(ExtractionService.parse_document).parameters
    assert parse_params["source"].kind is Parameter.POSITIONAL_OR_KEYWORD
    assert all(
        parse_params[name].kind is Parameter.KEYWORD_ONLY
        for name in ("user_id", "file_type", "account_id", "force_model", "db")
    )
    upsert_params = signature(DeduplicationService.upsert_atomic_transaction).parameters
    assert all(
        upsert_params[name].kind is Parameter.KEYWORD_ONLY for name in ("db", "row", "source_doc_id", "source_doc_type")
    )
    pipeline_params = signature(statement_pipeline.submit_parse_pipeline).parameters
    assert all(parameter.kind is Parameter.KEYWORD_ONLY for parameter in pipeline_params.values())
    failure_params = signature(statement_parsing.handle_parse_failure).parameters
    assert len(failure_params) <= 8
    assert "job" in failure_params
    assert (
        not {
            "request_id",
            "statement_id",
            "file_hash",
            "storage_key",
            "original_filename",
        }
        & failure_params.keys()
    )
