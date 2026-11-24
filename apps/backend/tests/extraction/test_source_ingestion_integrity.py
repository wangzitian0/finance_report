import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.extraction import BankStatementStatus, DocumentSource, DocumentType, ParseJob, Stage1Status, StartedRun
from src.extraction.base.paged_extraction import merge_paged_extractions
from src.extraction.base.validation import split_multi_account_extraction, validate_balance_per_currency
from src.extraction.extension.brokerage_positions import looks_like_brokerage_payload
from src.extraction.extension.brokerage_statement_payload import _extract_brokerage_payload_from_metadata
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_parsing import handle_parse_failure
from src.extraction.extension.statement_validation import resolve_statement_transactions
from src.extraction.extension.transaction_identity import TransactionIdentityReviewRequired
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction, AtomicTransactionIdentity
from src.extraction.orm.statement_summary import StatementSummary
from src.routers import statements
from tests.extraction._statement_run_helpers import (
    integrity_legacy_txn as _legacy,
    integrity_parse as _parse,
    integrity_payload as _payload,
    integrity_source as _source,
    integrity_store_result as _store_result,
    integrity_upsert as _upsert,
    verify_identity_rejection_case,
    verify_membership_excludes_ambiguous_and_superseded,
    verify_multicurrency_pdf_batches,
    verify_posted_cannot_be_superseded,
    verify_reparse_preserves_history,
)
from tests.factories import AccountFactory, StatementSummaryFactory, UserFactory
from tests.statement_ingestion import run_for

__all__ = ["_parse", "_payload", "_source", "_store_result"]


@pytest.mark.parametrize("bad_date", ["not-a-date", "None", "", None])
async def test_bad_dates_cannot_hide_offsetting_transactions(bad_date):
    payload = _payload()
    payload["transactions"] += [
        {"date": bad_date, "amount": "50", "direction": d, "currency": "SGD", "description": "Synthetic invalid row"}
        for d in ("IN", "OUT")
    ]
    with pytest.raises(ExtractionError, match="[Tt]ransaction"):
        await _parse(payload)


@pytest.mark.parametrize("conflict", [None, "balance", "account"])
def test_paged_currency_and_account_conservation(conflict):
    parts = [
        {
            "account_last4": "0001",
            "balances": [
                {"currency": "SGD", "opening": "100", "closing": "110"},
                {"currency": "USD", "opening": "200", "closing": "200"},
            ],
            "transactions": [{"currency": "SGD", "amount": "10", "direction": "IN"}],
        },
        {
            "account_last4": "0001",
            "balances": [{"currency": "EUR", "opening": "300", "closing": "320"}],
            "transactions": [{"currency": "EUR", "amount": "20", "direction": "IN"}],
        },
    ]
    if conflict == "balance":
        parts[1]["balances"].append({"currency": "SGD", "opening": "99", "closing": "110"})
    elif conflict == "account":
        parts[1]["account_last4"] = "0002"
    if conflict:
        with pytest.raises(ValueError, match="[Cc]onflict|[Mm]ultiple accounts"):
            merge_paged_extractions(parts)
    else:
        merged = merge_paged_extractions(parts)
        assert validate_balance_per_currency(merged)["balance_valid"] and {
            r["currency"] for r in merged["balances"]
        } == {"SGD", "USD", "EUR"}


@pytest.mark.parametrize("dimension", ["currency", "account"])
async def test_identity_distinguishes_custody_and_currency(db, test_user, dimension):
    account_a, account_b = (
        AccountFactory.build(user_id=test_user.id, currency="SGD"),
        AccountFactory.build(user_id=test_user.id, currency="USD" if dimension == "currency" else "SGD"),
    )
    db.add_all([account_a, account_b])
    await db.flush()
    doc_a, _ = await _source(db, test_user.id, account=account_a)
    doc_b, _ = await _source(db, test_user.id, account=account_b, currency=account_b.currency)
    first, second, duplicate = (
        await _upsert(db, test_user.id, doc_a),
        await _upsert(db, test_user.id, doc_b, currency=account_b.currency),
        await _upsert(db, test_user.id, doc_b, currency=account_b.currency),
    )
    assert first.id != second.id and second.currency == account_b.currency and duplicate.id == second.id


async def test_legacy_identity_reuse_and_ambiguity(db, test_user):
    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    old_doc, _ = await _source(db, test_user.id, account=account)
    new_doc, _ = await _source(db, test_user.id, account=account)
    old = await _legacy(db, test_user.id, old_doc)
    adopted = await _upsert(db, test_user.id, new_doc)
    aliases = list(
        (
            await db.scalars(select(AtomicTransactionIdentity).where(AtomicTransactionIdentity.atomic_txn_id == old.id))
        ).all()
    )
    assert (adopted.id, adopted.dedup_hash, len(aliases), aliases[0].user_id) == (
        old.id,
        old.dedup_hash,
        1,
        test_user.id,
    )

    other = await UserFactory.create_async(db)
    amb_old, _ = await _source(db, other.id)
    amb_new, _ = await _source(db, other.id)
    await _legacy(db, other.id, amb_old)
    with pytest.raises(ExtractionError, match="identity.*review|review.*identity"):
        await _upsert(db, other.id, amb_new)


async def test_concurrent_identity_upsert(db, test_user):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    doc_a, _ = await _source(db, test_user.id, account=account)
    doc_b, _ = await _source(db, test_user.id, account=account)
    await db.commit()
    sessions = async_sessionmaker(db.bind, expire_on_commit=False)

    async def insert(document):
        async with sessions() as session:
            row = await _upsert(session, test_user.id, document)
            await session.commit()
            return row.id

    first, second = await asyncio.gather(insert(doc_a), insert(doc_b))
    assert (
        first == second
        and await db.scalar(
            select(func.count()).select_from(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)
        )
        == 1
    )


async def test_retry_discards_provisional_institution(monkeypatch):
    statement = StatementSummaryFactory.build(institution="Pending Detection")
    monkeypatch.setattr(
        statements,
        "_resolve_uploaded_document",
        AsyncMock(return_value=MagicMock(file_path="synthetic/source.pdf", original_filename="synthetic.pdf")),
    )
    monkeypatch.setattr(statements, "run_in_threadpool", AsyncMock(return_value=b"synthetic"))
    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(statements, "submit_parse_pipeline", dispatch)
    monkeypatch.setattr(
        statements,
        "start_user_extract_run",
        AsyncMock(return_value=StartedRun(run_id=uuid4(), statement=statement, content=b"synthetic")),
    )
    await statements._queue_statement_reparse(
        AsyncMock(), statement, statement.user_id, allowed_statuses=frozenset()
    )
    assert dispatch.call_args.kwargs["job"].institution is None


@pytest.mark.parametrize(
    ("overrides", "expected_brokerage"),
    [
        ({}, False),
        (
            {
                "institution": "Interactive Brokers",
                "positions": [],
                "transactions": [],
                "opening_balance": None,
                "closing_balance": None,
            },
            True,
        ),
    ],
)
async def test_bank_vs_brokerage_payload_routing(overrides, expected_brokerage):
    payload = _extract_brokerage_payload_from_metadata(
        {"statement_extraction_result": (await _parse(_payload(**overrides))).to_payload()}
    )
    assert looks_like_brokerage_payload(payload) is expected_brokerage and (
        not expected_brokerage or payload["source_type"] == "brokerage_statement"
    )


async def test_reparse_preserves_history_and_current_membership(db, test_user, monkeypatch):
    await verify_reparse_preserves_history(db, test_user, monkeypatch)


async def test_posted_source_cannot_be_silently_superseded(db, test_user):
    await verify_posted_cannot_be_superseded(db, test_user)


async def test_legacy_result_cannot_bypass_currency_identity(db, test_user):
    document, summary = await _source(db, test_user.id, currency="SGD")
    wrong = await _legacy(db, test_user.id, document, currency="USD")
    payload = (await _parse(_payload())).to_payload()
    payload["transactions"][0]["fact_id"] = wrong.dedup_hash
    summary.extraction_metadata = {"statement_extraction_result": payload}
    await db.flush()
    with pytest.raises(ValueError, match="identity|currency"):
        await resolve_statement_transactions(db, summary)


async def test_source_isolation_adoption_and_novel_independence(db, test_user):
    document, summary = await _source(db, test_user.id)
    original = await _upsert(db, test_user.id, document)
    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    summary.account_id = account.id
    await db.flush()
    adopted = await _upsert(db, test_user.id, document)
    assert (adopted.id, adopted.dedup_hash) == (original.id, original.dedup_hash)
    first_doc, _ = await _source(db, test_user.id)
    second_doc, _ = await _source(db, test_user.id)
    assert (await _upsert(db, test_user.id, first_doc)).id != (await _upsert(db, test_user.id, second_doc)).id


async def test_failed_extraction_preserves_source_for_review(db, test_user):
    document, summary = await _source(db, test_user.id)
    statement_id, document_id, file_path = summary.id, document.id, document.file_path
    job = ParseJob(
        statement_id=summary.id,
        run_id=await run_for(db, summary.id),
        user_id=test_user.id,
        account_id=None,
        filename=document.original_filename,
        institution=None,
        file_hash=document.file_hash,
        storage_key=document.file_path,
    )
    summary.status = BankStatementStatus.PARSING
    await db.commit()
    await handle_parse_failure(
        summary,
        db,
        job=job,
        message="Transaction identity requires review",
        error_type=TransactionIdentityReviewRequired.__name__,
    )
    preserved = await db.get(StatementSummary, statement_id)
    assert (
        preserved.status,
        preserved.stage1_status,
        preserved.uploaded_document_id,
        (await db.get(UploadedDocument, document_id)).file_path,
    ) == (BankStatementStatus.PARSED, Stage1Status.PENDING_REVIEW, document_id, file_path)


async def test_generated_multicurrency_pdf_preserves_every_batch(db, test_user):
    await verify_multicurrency_pdf_batches(db, test_user)


async def test_membership_rejects_ambiguous_custody_and_excludes_superseded_sources(db, test_user):
    await verify_membership_excludes_ambiguous_and_superseded(db, test_user)


@pytest.mark.parametrize(
    "failure",
    [
        "foreign_document",
        "changed_account",
        "missing_account",
        "malformed_lineage",
        "currency_conflict",
        "different_currency",
        "missing_custody",
        "inconsistent_alias",
    ],
)
async def test_transaction_identity_rejects_unproven_adoption(db, test_user, failure):
    await verify_identity_rejection_case(db, test_user, failure)


async def test_AC_extraction_2983_consolidated_multi_account_pdf_creates_independent_statement_summaries(db, test_user):
    """#2983: A consolidated multi-account PDF splits into N StatementSummary rows anchored to 1 UploadedDocument."""
    from io import BytesIO
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, "BNP Checking 1234 EUR Opening: 100.00 Closing: 150.00")
    pdf.drawString(72, 700, "2025-01-05 Deposit 50.00")
    pdf.showPage()
    pdf.drawString(72, 720, "BNP Savings 5678 EUR Opening: 200.00 Closing: 180.00")
    pdf.drawString(72, 700, "2025-01-06 Withdrawal 20.00")
    pdf.showPage()
    pdf.save()
    pdf_bytes = buf.getvalue()
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    doc = UploadedDocument(
        user_id=test_user.id,
        file_path=f"statements/{test_user.id}/{file_hash}.pdf",
        file_hash=file_hash,
        original_filename="consolidated.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(doc)
    await db.flush()
    primary = StatementSummaryFactory.build(
        user_id=test_user.id,
        uploaded_document_id=doc.id,
        file_hash=file_hash,
        institution="BNP",
        status="parsing",
    )
    db.add(primary)
    await db.flush()

    service = ExtractionService()
    service.api_key = "synthetic-provider-key"
    service._extract_vision_source = AsyncMock(
        return_value=(
            split_multi_account_extraction(
                {
                    "institution": "BNP",
                    "accounts": [
                        {
                            "account_last4": "1234",
                            "currency": "EUR",
                            "period_start": "2025-01-01",
                            "period_end": "2025-01-31",
                            "opening_balance": "100.00",
                            "closing_balance": "150.00",
                            "transactions": [
                                {
                                    "date": "2025-01-05",
                                    "description": "Deposit",
                                    "amount": "50.00",
                                    "direction": "IN",
                                    "currency": "EUR",
                                }
                            ],
                        },
                        {
                            "account_last4": "5678",
                            "currency": "EUR",
                            "period_start": "2025-01-01",
                            "period_end": "2025-01-31",
                            "opening_balance": "200.00",
                            "closing_balance": "180.00",
                            "transactions": [
                                {
                                    "date": "2025-01-06",
                                    "description": "Withdrawal",
                                    "amount": "20.00",
                                    "direction": "OUT",
                                    "currency": "EUR",
                                }
                            ],
                        },
                    ],
                }
            ),
            None,
        )
    )
    source = DocumentSource.resolve(
        path=Path(doc.file_path), content=pdf_bytes, content_hash=file_hash, filename="consolidated.pdf"
    )
    results = await service.parse_documents(source, user_id=test_user.id, db=db)

    assert len(results) == 2
    assert {r.account_last4 for r in results} == {"1234", "5678"}
    assert all(r.balance_validated is True for r in results)

    summaries = list(
        (
            await db.scalars(
                select(StatementSummary).where(
                    StatementSummary.user_id == test_user.id, StatementSummary.file_hash == file_hash
                )
            )
        ).all()
    )
    assert len(summaries) == 2
    assert {s.account_last4 for s in summaries} == {"1234", "5678"}
    assert {s.uploaded_document_id for s in summaries} == {doc.id}
    assert len({s.sub_account_key for s in summaries}) == 2
    assert len({s.account_id for s in summaries if s.account_id is not None}) == 2


async def test_AC_extraction_2983_paged_multiple_accounts_splits_without_rejecting(db, test_user):
    """#2983: Paged extraction batches with distinct account_last4 split into separate StatementExtractionResults."""
    from io import BytesIO
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    for idx in range(6):
        pdf.drawString(72, 720, f"Consolidated BNP page {idx + 1}")
        pdf.showPage()
    pdf.save()
    pdf_bytes = buf.getvalue()
    meta = {
        "institution": "BNP",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100.00",
        "closing_balance": "150.00",
    }
    part1 = {
        "institution": "BNP",
        "account_last4": "1234",
        "currency": "EUR",
        "opening_balance": "100.00",
        "closing_balance": "150.00",
        "transactions": [
            {"date": "2025-01-05", "description": "Deposit", "amount": "50.00", "direction": "IN", "currency": "EUR"}
        ],
    }
    part2 = {
        "institution": "BNP",
        "account_last4": "5678",
        "currency": "EUR",
        "opening_balance": "300.00",
        "closing_balance": "280.00",
        "transactions": [
            {
                "date": "2025-01-06",
                "description": "Withdrawal",
                "amount": "20.00",
                "direction": "OUT",
                "currency": "EUR",
            }
        ],
    }
    service = ExtractionService()
    service.api_key = "synthetic-provider-key"
    service._extract_json_with_model = AsyncMock(side_effect=[meta, part1, part2])
    source = DocumentSource.resolve(path=Path("synthetic/paged_multi.pdf"), content=pdf_bytes)
    results = await service.parse_documents(source, user_id=test_user.id, db=db)
    assert len(results) == 2
    assert [r.account_last4 for r in results] == ["1234", "5678"]
    assert all(r.balance_validated is True for r in results)


async def test_multi_account_sibling_records_extract_run_and_converges_metadata(db, test_user, monkeypatch):
    """Multi-account ingestion strips duplicate metadata, records sibling provenance, and links classify runs."""
    import fitz

    from src.database import create_session_maker_from_db
    from src.extraction import ParseJob, RunKind, RunState, register_statement_source
    from src.extraction.orm.statement_run import StatementRun
    from tests.statement_ingestion import execute_statement_ingestion as parse_statement_background, run_for

    buf = fitz.open()
    page = buf.new_page()
    for idx, line in enumerate(
        [
            "Consolidated Statement Period 2025-01-01 to 2025-01-31",
            "Account 1234 Opening Balance 100.00",
            "2025-01-05 Deposit 50.00 Closing Balance 150.00",
            "Account 5678 Opening Balance 200.00",
            "2025-01-06 Withdrawal 20.00 Closing Balance 180.00",
        ]
    ):
        page.insert_text((72, 72 + 16 * idx), line)
    pdf_bytes = buf.tobytes()
    buf.close()
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    primary_stmt = StatementSummary(
        user_id=test_user.id,
        file_hash=file_hash,
        institution="BNP",
        status="parsing",
    )
    db.add(primary_stmt)
    await db.flush()
    doc = await register_statement_source(
        db,
        statement=primary_stmt,
        storage_key=f"statements/{file_hash}.pdf",
        original_filename="consolidated.pdf",
    )
    await db.commit()
    extract_run_id = await run_for(db, primary_stmt.id)

    multi_payload = {
        "institution": "BNP",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "accounts": [
            {
                "account_last4": "1234",
                "currency": "EUR",
                "opening_balance": "100.00",
                "closing_balance": "150.00",
                "transactions": [
                    {
                        "date": "2025-01-05",
                        "description": "Deposit",
                        "amount": "50.00",
                        "direction": "IN",
                        "currency": "EUR",
                    }
                ],
            },
            {
                "account_last4": "5678",
                "currency": "EUR",
                "opening_balance": "200.00",
                "closing_balance": "180.00",
                "transactions": [
                    {
                        "date": "2025-01-06",
                        "description": "Withdrawal",
                        "amount": "20.00",
                        "direction": "OUT",
                        "currency": "EUR",
                    }
                ],
            },
        ],
    }

    monkeypatch.setattr(ExtractionService, "extract_financial_data", AsyncMock(return_value=multi_payload))
    outcome = await parse_statement_background(
        job=ParseJob(
            statement_id=primary_stmt.id,
            run_id=extract_run_id,
            filename="consolidated.pdf",
            institution="BNP",
            user_id=test_user.id,
            account_id=None,
            file_hash=file_hash,
            storage_key=f"statements/{file_hash}.pdf",
        ),
        content=pdf_bytes,
        session_maker=create_session_maker_from_db(db),
    )
    assert outcome.status.value == "completed"

    user_id = test_user.id
    doc_id = doc.id
    primary_stmt_id = primary_stmt.id
    db.expire_all()
    summaries = list(
        (
            await db.scalars(
                select(StatementSummary).where(
                    StatementSummary.user_id == user_id, StatementSummary.file_hash == file_hash
                )
            )
        ).all()
    )
    assert len(summaries) == 2
    for s in summaries:
        assert s.current_extraction_result_id is not None
        meta = s.extraction_metadata or {}
        assert "statement_extraction_result" not in meta
        assert meta.get("artifact_provenance", {}).get("resolved_model_id") == "synthetic-vision"
        assert meta.get("artifact_provenance", {}).get("artifact_dependency_digest")

    refreshed_doc = await db.get(UploadedDocument, doc_id)
    assert refreshed_doc is not None
    assert refreshed_doc.extraction_metadata is None

    sibling = next(s for s in summaries if s.id != primary_stmt_id)
    sib_runs = list(
        (
            await db.scalars(
                select(StatementRun).where(StatementRun.statement_id == sibling.id).order_by(StatementRun.seq)
            )
        ).all()
    )
    sib_extract = next(r for r in sib_runs if r.kind is RunKind.EXTRACT)
    sib_classify = next(r for r in sib_runs if r.kind is RunKind.CLASSIFY)
    assert sib_extract.state is RunState.SUCCEEDED
    assert sib_extract.result_summary == {"auto_approve_candidate": True}
    assert sib_classify.parent_run_id == sib_extract.id
