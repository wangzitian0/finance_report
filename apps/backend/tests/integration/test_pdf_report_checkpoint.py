from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from io import StringIO
from unittest.mock import AsyncMock
from uuid import UUID

import fitz
import pytest_asyncio
from moto import mock_aws
from sqlalchemy import select
from src.audit.orm.trace_record import TraceRecordRow
from src.config import settings
from src.extraction import UploadedDocument, wait_for_parse_tasks
from src.extraction.extension import transaction_classification
from src.extraction.extension.transaction_classification import CategoryProposal
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionSourceDocument
from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import create_access_token
from src.ledger import JournalEntry
from src.llm.extension import streaming
from src.runtime import StorageService
from tests.factories import UserFactory


def generated_bank_pdf() -> bytes:
    with fitz.open() as doc:
        doc.new_page().insert_text(
            (50, 60),
            "GENERATED CHECKPOINT BANK\nAccount: ****1234\nCurrency: SGD\nStatement period: 2026-01-01 to 2026-01-31\nOpening balance: SGD 1000.00\n\nDate              Description           Credit    Debit    Balance\n2026-01-05    Salary                     500.00                1500.00\n2026-01-10    Grocery purchase                      100.00    1400.00\n\nClosing balance: SGD 1400.00\nGENERATED TEST DATA",
            fontsize=11,
        )
        return doc.tobytes()


@dataclass(frozen=True)
class PdfCheckpoint:
    statement_id: UUID
    user_id: UUID
    account_id: UUID
    content: bytes


@pytest_asyncio.fixture
async def uploaded_pdf(client, db, test_user, monkeypatch):
    user_id = test_user.id
    for attr, val in (
        ("s3_endpoint", None),
        ("s3_access_key", "testing"),
        ("s3_secret_key", "testing"),
        ("s3_bucket", "generated-pdf-checkpoint"),
        ("ai_api_key", "controlled-provider"),
        ("ai_provider", "zai"),
        ("enable_ai_classification", True),
        ("statement_disposition_mode", "enforce"),
    ):
        monkeypatch.setattr(settings, attr, val)
    seen_text: list[str] = []

    async def extraction_response(*, messages, **kwargs):
        assert kwargs["user_id"] == user_id
        for part in (p for m in messages if isinstance(m.get("content"), list) for p in m["content"]):
            assert part.get("type") != "image_url"
            if part.get("type") == "text":
                seen_text.append(part["text"])
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

    monkeypatch.setattr(streaming, "_stream_ai_base", extraction_response)
    monkeypatch.setattr(
        transaction_classification,
        "propose_categories",
        AsyncMock(
            side_effect=lambda txns, _p: [
                CategoryProposal(
                    category={"Salary": "SALARY", "Grocery purchase": "GROCERIES"}[t.description],
                    confidence=99,
                    reason="Generated proposal",
                )
                for t in txns
            ]
        ),
    )
    content = generated_bank_pdf()
    StorageService._checked_buckets.clear()
    try:
        with mock_aws():
            assert (
                response := await client.post(
                    "/statements", files={"file": ("generated-checkpoint.pdf", content, "application/pdf")}
                )
            ).status_code == 202
            statement_id = UUID(response.json()["id"])
            await wait_for_parse_tasks()
            db.expire_all()
            statement = await db.get(StatementSummary, statement_id)
            assert (
                statement is not None
                and statement.status.value == "approved"
                and statement.account_id is not None
                and statement.validation_error is None
            )
            assert len(
                [t for t in seen_text if t.startswith("[Page 1]")]
            ) == 1 and "GENERATED CHECKPOINT BANK" in "".join(seen_text)
            yield PdfCheckpoint(statement_id, user_id, statement.account_id, content)
    finally:
        StorageService._checked_buckets.clear()


async def test_pdf_checkpoint_source_lineage_and_reports(uploaded_pdf: PdfCheckpoint, client, db):
    statement_id, user_id, content = uploaded_pdf.statement_id, uploaded_pdf.user_id, uploaded_pdf.content
    statement = await db.get(StatementSummary, statement_id)
    assert statement is not None
    document, sha = await db.get(UploadedDocument, statement.uploaded_document_id), hashlib.sha256(content).hexdigest()
    assert (
        document.user_id,
        document.file_hash,
        statement.file_hash,
        StorageService().get_object(document.file_path),
    ) == (user_id, sha, sha, content)
    result = (
        await db.execute(
            select(StatementExtractionResultRecord).where(StatementExtractionResultRecord.statement_id == statement_id)
        )
    ).scalar_one()
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
    posted = (
        (
            await db.execute(
                select(JournalEntry).where(
                    JournalEntry.user_id == user_id, JournalEntry.source_id.in_([r.id for r in rows])
                )
            )
        )
        .scalars()
        .all()
    )
    assert (
        result.user_id,
        result.source_content_digest,
        result.payload["content_digest"],
        len(result.payload["transactions"]),
    ) == (user_id, sha, result.content_digest, 2)
    assert (
        {r.user_id for r in rows},
        {r.currency for r in rows},
        {(r.description, r.amount, r.direction.value) for r in rows},
    ) == ({user_id}, {"SGD"}, {("Salary", Decimal("500"), "IN"), ("Grocery purchase", Decimal("100"), "OUT")})
    assert {e.source_id for e in posted} == {r.id for r in rows} and all(
        e.decision_anchor_id is not None for e in posted
    )
    assert (
        await client.post("/statements", files={"file": ("renamed.pdf", content, "application/pdf")})
    ).status_code == 409
    assert [
        i.id
        for i in (await db.execute(select(UploadedDocument).where(UploadedDocument.user_id == user_id))).scalars().all()
    ] == [document.id]
    assert (trace := await db.get(TraceRecordRow, result.source_trace_record_id)) is not None and trace.scope_id == str(
        user_id
    )

    lineage = await client.get(
        "/reports/account-lineage",
        params={"account_id": str(statement.account_id), "as_of_date": "2026-01-31", "currency": "SGD"},
    )
    assert lineage.status_code == 200 and Decimal(lineage.json()["total"]) == Decimal("1400")
    reached = set()
    for line in lineage.json()["lines"]:
        assert (
            ev := await client.get(
                "/statements/evidence-lineage",
                params={"entity_type": "journal_line", "entity_id": line["journal_line_id"], "direction": "upstream"},
            )
        ).status_code == 200 and str(statement.uploaded_document_id) in {
            n["entity_id"] for n in ev.json()["nodes"] if n["entity_type"] == "uploaded_document"
        }
        if (journal := await db.get(JournalEntry, UUID(line["journal_entry_id"]))).source_id:
            reached.add(journal.source_id)
    assert (
        reached
        == set((await db.scalars(select(AtomicTransaction.id).where(AtomicTransaction.user_id == user_id))).all())
        and len(reached) == 2
    )

    other = await UserFactory.create_async(db, email="other-checkpoint@example.invalid")
    await db.commit()
    headers = {"Authorization": "Bearer " + create_access_token(data={"sub": str(other.id)})}
    assert (
        await client.get("/reports/account-lineage", params={"account_id": str(statement.account_id)}, headers=headers)
    ).status_code == 404
    assert (
        f_src := await client.get(
            "/statements/evidence-lineage",
            params={"entity_type": "uploaded_document", "entity_id": str(statement.uploaded_document_id)},
            headers=headers,
        )
    ).status_code == 200 and (f_src.json()["anchor"], f_src.json()["nodes"]) == (None, [])

    query = {"as_of_date": "2026-01-31", "start_date": "2026-01-01", "end_date": "2026-01-31", "currency": "SGD"}
    bal, inc, cash = (
        await client.get("/reports/balance-sheet", params=query),
        await client.get("/reports/income-statement", params=query),
        await client.get("/reports/cash-flow", params=query),
    )
    assert bal.status_code == inc.status_code == cash.status_code == 200
    assert (
        Decimal(bal.json()["total_assets"]),
        Decimal(bal.json()["equation_delta"]),
        Decimal(inc.json()["total_income"]),
        Decimal(inc.json()["total_expenses"]),
        Decimal(inc.json()["net_income"]),
        Decimal(cash.json()["summary"]["beginning_cash"]),
        Decimal(cash.json()["summary"]["net_cash_flow"]),
        Decimal(cash.json()["summary"]["ending_cash"]),
    ) == (
        Decimal("1400"),
        Decimal("0"),
        Decimal("500"),
        Decimal("100"),
        Decimal("400"),
        Decimal("1000"),
        Decimal("400"),
        Decimal("1400"),
    )
    frozen = (await client.post("/reports/package/snapshots", json=query)).json()
    cats = {
        line["line_id"]: Decimal(line["amount"])
        for line in (
            *frozen["document"]["sections"]["income_statement"]["income"],
            *frozen["document"]["sections"]["income_statement"]["expenses"],
        )
    }
    assert (
        frozen["status"],
        frozen["document"]["readiness"]["state"],
        cats["income.salary"],
        cats["expenses.groceries"],
        cats["income.dividends_and_interest"],
        cats["expenses.investment_fees"],
    ) == ("trusted", "ready", Decimal("500"), Decimal("100"), 0, 0)
    sid = frozen["id"]
    reopened, exported, csv_export = (
        await client.get(f"/reports/package/snapshots/{sid}"),
        await client.get(f"/reports/package/snapshots/{sid}/exports", params={"format": "json"}),
        await client.get(f"/reports/package/snapshots/{sid}/exports", params={"format": "csv"}),
    )
    assert (
        reopened.status_code == exported.status_code == csv_export.status_code == 200
        and reopened.json()["document"] == exported.json()["document"] == frozen["document"]
    )
    csv_rows = list(csv.DictReader(StringIO(csv_export.text)))
    assert (
        csv_rows
        and frozen["document"]["input_manifest"]
        and all(
            d["decision_id"] in csv_rows[0]["input_decision_references"] for d in frozen["document"]["input_manifest"]
        )
    )
