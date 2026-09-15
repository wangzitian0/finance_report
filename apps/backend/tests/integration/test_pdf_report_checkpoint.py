"""PDF-to-report composition proof using generated sources and provider proposals.

Only model responses and the S3 server are controlled. Upload, PDF rendering,
normalization, persistence, authorization, ledger and report APIs are real.
This deterministic lane does not claim live model accuracy. Provider-backed
deployment journeys verify that separate boundary.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from io import StringIO
from uuid import UUID

import fitz
import pytest_asyncio
from moto import mock_aws
from sqlalchemy import select

from src.audit.orm.trace_record import TraceRecordRow
from src.config import settings
from src.extraction import UploadedDocument
from src.extraction.extension import transaction_classification
from src.extraction.extension.transaction_classification import CategoryProposal
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionSourceDocument
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import create_access_token
from src.ledger import JournalEntry
from src.llm.extension import streaming
from src.routers.statements import wait_for_parse_tasks
from src.runtime import StorageService
from tests.factories import UserFactory


def generated_bank_pdf() -> bytes:
    """A fresh synthetic PDF with an independently specified cash rollforward."""
    document = fitz.open()
    page = document.new_page()
    page.insert_text(
        (50, 60),
        "GENERATED CHECKPOINT BANK\nAccount: ****1234\nCurrency: SGD\n"
        "Statement period: 2026-01-01 to 2026-01-31\nOpening balance: SGD 1000.00\n\n"
        "Date              Description           Credit    Debit    Balance\n"
        "2026-01-05    Salary                     500.00                1500.00\n"
        "2026-01-10    Grocery purchase                      100.00    1400.00\n\n"
        "Closing balance: SGD 1400.00\nGENERATED TEST DATA",
        fontsize=11,
    )
    content = document.tobytes()
    document.close()
    return content


@dataclass(frozen=True)
class PdfCheckpoint:
    statement_id: UUID
    user_id: UUID
    account_id: UUID
    content: bytes


@pytest_asyncio.fixture
async def uploaded_pdf(client, db, test_user, monkeypatch):
    """Exercise public upload with explicit deterministic model proposals."""
    user_id = test_user.id
    monkeypatch.setattr(settings, "s3_endpoint", None)
    monkeypatch.setattr(settings, "s3_access_key", "testing")
    monkeypatch.setattr(settings, "s3_secret_key", "testing")
    monkeypatch.setattr(settings, "s3_bucket", "generated-pdf-checkpoint")
    monkeypatch.setattr(settings, "ai_api_key", "controlled-provider")
    monkeypatch.setattr(settings, "ai_provider", "zai")
    monkeypatch.setattr(settings, "enable_ai_classification", True)
    monkeypatch.setattr(settings, "statement_disposition_mode", "enforce")
    monkeypatch.setattr(settings, "ocr_model", settings.vision_model)
    seen_images: list[bytes] = []

    async def extraction_response(*, messages, **kwargs):
        assert kwargs["user_id"] == user_id
        for message in messages:
            if not isinstance(message.get("content"), list):
                continue
            for part in message["content"]:
                if part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    assert url.startswith("data:image/png;base64,")
                    seen_images.append(base64.b64decode(url.split(",", 1)[1]))
        yield json.dumps(
            {
                "institution": "Generated Checkpoint Bank",
                "account_last4": "1234",
                "currency": "SGD",
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "opening_balance": "1000.00",
                "closing_balance": "1400.00",
                "transactions": [
                    {
                        "date": "2026-01-05",
                        "description": "Salary",
                        "amount": "500.00",
                        "direction": "IN",
                        "currency": "SGD",
                        "balance_after": "1500.00",
                    },
                    {
                        "date": "2026-01-10",
                        "description": "Grocery purchase",
                        "amount": "100.00",
                        "direction": "OUT",
                        "currency": "SGD",
                        "balance_after": "1400.00",
                    },
                ],
            }
        )

    async def category_proposals(transactions, _policy):
        categories = {"Salary": "SALARY", "Grocery purchase": "GROCERIES"}
        return [
            CategoryProposal(category=categories[t.description], confidence=99, reason="Generated proposal")
            for t in transactions
        ]

    # Keep the JSON request adapter and its decoding options real; replace the
    # provider edge so this composition proof needs neither network nor a model.
    monkeypatch.setattr(streaming, "_stream_ai_base", extraction_response)
    monkeypatch.setattr(transaction_classification, "propose_categories", category_proposals)
    content = generated_bank_pdf()
    StorageService._checked_buckets.clear()
    with mock_aws():
        response = await client.post(
            "/statements/upload", files={"file": ("generated-checkpoint.pdf", content, "application/pdf")}
        )
        assert response.status_code == 202, response.text
        statement_id = UUID(response.json()["id"])
        await wait_for_parse_tasks()
        db.expire_all()
        statement = await db.get(StatementSummary, statement_id)
        assert statement is not None
        assert statement.status.value == "approved", statement.validation_error
        assert statement.account_id is not None
        assert len(seen_images) == 1
        assert seen_images[0].startswith(b"\x89PNG")
        yield PdfCheckpoint(statement_id, user_id, statement.account_id, content)
    StorageService._checked_buckets.clear()


async def test_pdf_checkpoint_persists_source_and_fact_identity(uploaded_pdf, db, client):
    """AC-testing.pdf-checkpoint.1: actual source keys and normalized facts agree."""
    case = uploaded_pdf
    statement = await db.get(StatementSummary, case.statement_id)
    document = await db.get(UploadedDocument, statement.uploaded_document_id)
    assert document.user_id == case.user_id
    assert document.file_hash == statement.file_hash == hashlib.sha256(case.content).hexdigest()
    assert StorageService().get_object(document.file_path) == case.content
    result = (
        await db.execute(
            select(StatementExtractionResultRecord).where(
                StatementExtractionResultRecord.statement_id == case.statement_id
            )
        )
    ).scalar_one()
    assert result.user_id == case.user_id
    assert result.source_content_digest == document.file_hash
    assert result.payload["content_digest"] == result.content_digest
    assert len(result.payload["transactions"]) == 2
    rows = (
        (
            await db.execute(
                select(AtomicTransaction)
                .join(AtomicTransactionSourceDocument)
                .where(AtomicTransactionSourceDocument.uploaded_document_id == document.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert {r.user_id for r in rows} == {case.user_id}
    assert {r.currency for r in rows} == {"SGD"}
    assert {(r.description, r.amount, r.direction.value) for r in rows} == {
        ("Salary", Decimal("500"), "IN"),
        ("Grocery purchase", Decimal("100"), "OUT"),
    }
    posted = (
        (
            await db.execute(
                select(JournalEntry).where(
                    JournalEntry.user_id == case.user_id, JournalEntry.source_id.in_([r.id for r in rows])
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(posted) == 2
    assert {entry.source_id for entry in posted} == {r.id for r in rows}
    assert all(entry.decision_anchor_id is not None for entry in posted)
    repeated = await client.post("/statements/upload", files={"file": ("renamed.pdf", case.content, "application/pdf")})
    assert repeated.status_code == 409
    documents = (
        (await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == case.user_id))).scalars().all()
    )
    assert [item.id for item in documents] == [document.id]
    assert statement.validation_error is None


async def test_pdf_checkpoint_report_lineage_reaches_source(uploaded_pdf, client, db):
    """AC-testing.pdf-checkpoint.2: drill-down traverses real posted source IDs."""
    case = uploaded_pdf
    statement = await db.get(StatementSummary, case.statement_id)
    result = (
        await db.execute(
            select(StatementExtractionResultRecord).where(
                StatementExtractionResultRecord.statement_id == case.statement_id
            )
        )
    ).scalar_one()
    trace = await db.get(TraceRecordRow, result.source_trace_record_id)
    assert trace is not None
    assert trace.scope_id == str(case.user_id)
    response = await client.get(
        "/reports/account-lineage",
        params={"account_id": str(case.account_id), "as_of_date": "2026-01-31", "currency": "SGD"},
    )
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["total"]) == Decimal("1400")
    reached_transaction_ids = set()
    for line in response.json()["lines"]:
        journal = await db.get(JournalEntry, UUID(line["journal_entry_id"]))
        source_transaction = await db.get(AtomicTransaction, journal.source_id) if journal.source_id else None
        evidence = await client.get(
            "/evidence/lineage",
            params={"entity_type": "journal_line", "entity_id": line["journal_line_id"], "direction": "upstream"},
        )
        assert evidence.status_code == 200, evidence.text
        reached_sources = {
            node["entity_id"] for node in evidence.json()["nodes"] if node["entity_type"] == "uploaded_document"
        }
        assert str(statement.uploaded_document_id) in reached_sources
        if source_transaction is not None:
            reached_transaction_ids.add(source_transaction.id)
    expected_transaction_ids = set(
        (await db.scalars(select(AtomicTransaction.id).where(AtomicTransaction.user_id == case.user_id))).all()
    )
    assert len(expected_transaction_ids) == 2
    assert reached_transaction_ids == expected_transaction_ids
    other_user = await UserFactory.create_async(db, email="other-checkpoint@example.invalid")
    await db.commit()
    headers = {"Authorization": "Bearer " + create_access_token(data={"sub": str(other_user.id)})}
    foreign_report = await client.get(
        "/reports/account-lineage", params={"account_id": str(case.account_id)}, headers=headers
    )
    assert foreign_report.status_code == 404
    foreign_source = await client.get(
        "/evidence/lineage",
        params={"entity_type": "uploaded_document", "entity_id": str(statement.uploaded_document_id)},
        headers=headers,
    )
    assert foreign_source.status_code == 200
    assert foreign_source.json()["anchor"] is None
    assert foreign_source.json()["nodes"] == []


async def test_pdf_checkpoint_three_statements_and_saved_package(uploaded_pdf, client):
    """AC-testing.pdf-checkpoint.3: imported opening is stock, never period income."""
    query = {"as_of_date": "2026-01-31", "start_date": "2026-01-01", "end_date": "2026-01-31", "currency": "SGD"}
    balance = await client.get("/reports/balance-sheet", params=query)
    income = await client.get("/reports/income-statement", params=query)
    cash = await client.get("/reports/cash-flow", params=query)
    assert balance.status_code == income.status_code == cash.status_code == 200
    assert Decimal(balance.json()["total_assets"]) == Decimal("1400")
    assert Decimal(balance.json()["equation_delta"]) == Decimal("0")
    assert Decimal(income.json()["total_income"]) == Decimal("500")
    assert Decimal(income.json()["total_expenses"]) == Decimal("100")
    assert Decimal(income.json()["net_income"]) == Decimal("400")
    assert Decimal(cash.json()["summary"]["beginning_cash"]) == Decimal("1000")
    assert Decimal(cash.json()["summary"]["net_cash_flow"]) == Decimal("400")
    assert Decimal(cash.json()["summary"]["ending_cash"]) == Decimal("1400")
    generated = await client.post("/reports/package/generate", json=query)
    assert generated.status_code == 200, generated.text
    frozen = generated.json()
    assert frozen["status"] == "trusted"
    assert frozen["document"]["readiness"]["state"] == "ready"
    package_income = frozen["document"]["sections"]["income_statement"]
    category_amounts = {
        line["line_id"]: Decimal(line["amount"]) for line in (*package_income["income"], *package_income["expenses"])
    }
    assert category_amounts["income.salary"] == Decimal("500")
    assert category_amounts["expenses.groceries"] == Decimal("100")
    assert category_amounts["income.dividends_and_interest"] == 0
    assert category_amounts["expenses.investment_fees"] == 0
    snapshot_id = frozen["id"]
    reopened = await client.get(f"/reports/package/snapshots/{snapshot_id}")
    exported = await client.get(f"/reports/package/snapshots/{snapshot_id}/export", params={"format": "json"})
    csv_export = await client.get(f"/reports/package/snapshots/{snapshot_id}/export", params={"format": "csv"})
    assert reopened.status_code == exported.status_code == csv_export.status_code == 200
    assert reopened.json()["document"] == exported.json()["document"] == frozen["document"]
    exported_rows = list(csv.DictReader(StringIO(csv_export.text)))
    assert exported_rows
    assert frozen["document"]["input_manifest"]
    for decision in frozen["document"]["input_manifest"]:
        assert decision["decision_id"] in exported_rows[0]["input_decision_references"]
