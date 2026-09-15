"""Source conservation and identity regressions from the PDF-chain audit (#2039)."""

import asyncio
import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.extraction import DocumentSource
from src.extraction.base.paged_extraction import merge_paged_extractions
from src.extraction.base.source_vocabulary import DocumentType, TransactionDirection
from src.extraction.base.validation import validate_balance_per_currency
from src.extraction.extension.brokerage_positions import looks_like_brokerage_payload
from src.extraction.extension.brokerage_statement_payload import _extract_brokerage_payload_from_metadata
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.service import ExtractionError, ExtractionService
from src.extraction.extension.statement_validation import resolve_statement_transactions
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.statement_summary import StatementSummary
from tests.factories import AccountFactory, StatementSummaryFactory


def _payload(**changes):
    return {
        "institution": "Synthetic Bank",
        "account_last4": "0001",
        "currency": "SGD",
        "period_start": "2025-01-01",
        "period_end": "2025-01-31",
        "opening_balance": "100",
        "closing_balance": "110",
        "transactions": [
            {
                "date": "2025-01-02",
                "amount": "10",
                "direction": "IN",
                "currency": "SGD",
                "description": "Synthetic deposit",
            }
        ],
        **changes,
    }


async def _parse(payload, *, db=None, user_id=None, account_id=None, source=None):
    service = ExtractionService()
    service._extract_vision_source = AsyncMock(return_value=payload)
    return await service.parse_document(
        source or DocumentSource.resolve(path=Path("synthetic.pdf"), content=b"synthetic"),
        user_id=user_id or uuid4(),
        account_id=account_id,
        db=db,
    )


@pytest.mark.parametrize("bad_date", ["not-a-date", "None", "", None])
async def test_bad_dates_cannot_hide_offsetting_transactions(bad_date):
    """AC-extraction.source-conservation.1: net equality cannot hide source-row loss."""
    payload = _payload()
    payload["transactions"] += [
        {
            "date": bad_date,
            "amount": "50",
            "direction": direction,
            "currency": "SGD",
            "description": "Synthetic invalid row",
        }
        for direction in ("IN", "OUT")
    ]
    with pytest.raises(ExtractionError, match="[Tt]ransaction"):
        await _parse(payload)


@pytest.mark.parametrize("conflict", [None, "balance", "account"])
def test_paged_currency_and_account_conservation(conflict):
    """AC-extraction.source-conservation.2: union source domains, reject contradictions."""
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
    if conflict == "account":
        parts[1]["account_last4"] = "0002"
    if conflict:
        with pytest.raises(ValueError, match="[Cc]onflict|[Mm]ultiple accounts"):
            merge_paged_extractions(parts)
    else:
        merged = merge_paged_extractions(parts)
        assert validate_balance_per_currency(merged)["balance_valid"]
        assert {row["currency"] for row in merged["balances"]} == {"SGD", "USD", "EUR"}


async def _source(db, user_id, *, account=None, currency="SGD"):
    document = UploadedDocument(
        user_id=user_id,
        file_path=f"synthetic/{uuid4()}.pdf",
        file_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        original_filename="synthetic.pdf",
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    summary = StatementSummaryFactory.build(
        user_id=user_id,
        uploaded_document_id=document.id,
        file_hash=document.file_hash,
        account_id=account.id if account else None,
        currency=currency,
        institution="Synthetic Bank",
    )
    db.add(summary)
    await db.flush()
    return document, summary


async def _upsert(db, user_id, document, *, currency="SGD"):
    return await DeduplicationService().upsert_atomic_transaction(
        db=db,
        user_id=user_id,
        txn_date=date(2025, 1, 2),
        amount=Decimal("10"),
        direction=TransactionDirection.IN,
        description="Synthetic deposit",
        currency=currency,
        balance_after=Decimal("110"),
        source_doc_id=document.id,
        source_doc_type=DocumentType.BANK_STATEMENT,
    )


@pytest.mark.parametrize("dimension", ["currency", "account"])
async def test_identity_distinguishes_custody_and_currency(db, test_user, dimension):
    """AC-extraction.transaction-identity.1: custody-distinct events never collapse."""
    account_a = AccountFactory.build(user_id=test_user.id, currency="SGD")
    account_b = AccountFactory.build(user_id=test_user.id, currency="USD" if dimension == "currency" else "SGD")
    db.add_all([account_a, account_b])
    await db.flush()
    doc_a, _ = await _source(db, test_user.id, account=account_a)
    doc_b, _ = await _source(db, test_user.id, account=account_b, currency=account_b.currency)
    first = await _upsert(db, test_user.id, doc_a)
    second = await _upsert(db, test_user.id, doc_b, currency=account_b.currency)
    assert first.id != second.id
    assert second.currency == account_b.currency
    duplicate = await _upsert(db, test_user.id, doc_b, currency=account_b.currency)
    assert duplicate.id == second.id


async def _legacy(db, user_id, document, currency="SGD"):
    old_hash = DeduplicationService.calculate_transaction_hash(
        user_id,
        date(2025, 1, 2),
        Decimal("10"),
        TransactionDirection.IN,
        "Synthetic deposit",
        balance_after=Decimal("110"),
    )
    old = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2025, 1, 2),
        amount=Decimal("10"),
        direction=TransactionDirection.IN,
        description="Synthetic deposit",
        currency=currency,
        balance_after=Decimal("110"),
        dedup_hash=old_hash,
        source_documents=[{"doc_id": str(document.id), "doc_type": "bank_statement"}],
    )
    db.add(old)
    await db.flush()
    return old


async def test_legacy_identity_reuse_preserves_history(db, test_user):
    """AC-extraction.transaction-identity.2: compatible legacy adoption retains UUID/hash."""
    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    old_doc, _ = await _source(db, test_user.id, account=account)
    new_doc, _ = await _source(db, test_user.id, account=account)
    old = await _legacy(db, test_user.id, old_doc)
    original_id, original_hash = old.id, old.dedup_hash
    adopted = await _upsert(db, test_user.id, new_doc)
    assert adopted.id == original_id and adopted.dedup_hash == original_hash
    from src.extraction.orm.layer2 import AtomicTransactionIdentity

    aliases = list(
        (
            await db.scalars(select(AtomicTransactionIdentity).where(AtomicTransactionIdentity.atomic_txn_id == old.id))
        ).all()
    )
    assert len(aliases) == 1 and aliases[0].user_id == test_user.id


async def test_ambiguous_legacy_identity_is_reviewable(db, test_user):
    """AC-extraction.transaction-identity.3: uncertainty cannot silently migrate old truth."""
    old_doc, _ = await _source(db, test_user.id)
    new_doc, _ = await _source(db, test_user.id)
    await _legacy(db, test_user.id, old_doc)
    with pytest.raises(ExtractionError, match="identity.*review|review.*identity"):
        await _upsert(db, test_user.id, new_doc)


async def test_concurrent_identity_upsert(db, test_user):
    """AC-extraction.transaction-identity.4: equal concurrent imports converge."""
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
    assert first == second
    assert (
        await db.scalar(
            select(func.count()).select_from(AtomicTransaction).where(AtomicTransaction.user_id == test_user.id)
        )
        == 1
    )


async def test_retry_discards_provisional_institution(monkeypatch):
    """AC-extraction.retry-identity.1: transport must not freeze a failed detector placeholder."""
    from src.routers import statements

    statement = StatementSummaryFactory.build(institution="Pending Detection")
    document = MagicMock(file_path="synthetic/source.pdf", original_filename="synthetic.pdf")
    monkeypatch.setattr(statements, "_resolve_uploaded_document", AsyncMock(return_value=document))
    monkeypatch.setattr(statements, "run_in_threadpool", AsyncMock(return_value=b"synthetic"))
    dispatch = AsyncMock(return_value=None)
    monkeypatch.setattr(statements, "submit_parse_pipeline", dispatch)
    await statements._queue_statement_reparse(AsyncMock(), statement, statement.user_id, model=None)
    assert dispatch.call_args.kwargs["job"].institution is None


async def test_bank_result_never_routes_as_brokerage():
    """AC-extraction.source-routing.1: standard bank serialization is not brokerage evidence."""
    result = await _parse(_payload())
    payload = _extract_brokerage_payload_from_metadata({"statement_extraction_result": result.to_payload()})
    assert not looks_like_brokerage_payload(payload)


async def test_empty_brokerage_snapshot_remains_reviewable():
    """AC-extraction.source-routing.2: explicit zero-position evidence retains source kind."""
    result = await _parse(
        _payload(
            institution="Interactive Brokers", positions=[], transactions=[], opening_balance=None, closing_balance=None
        )
    )
    payload = _extract_brokerage_payload_from_metadata({"statement_extraction_result": result.to_payload()})
    assert looks_like_brokerage_payload(payload)
    assert payload["source_type"] == "brokerage_statement"


async def _store_result(db, summary, result):
    from src.audit import SqlTraceRecordRepository, TraceEmitter
    from src.extraction.extension.extraction_trace import (
        build_extraction_trace_records,
        extraction_trace_policy_registry,
    )
    from src.extraction.extension.reviewed_statement_envelope import persist_statement_extraction_result

    records = build_extraction_trace_records(
        result,
        user_id=summary.user_id,
        execution_id=f"test:{summary.id}:{result.result_id}",
        occurred_at=datetime.now(UTC),
    )
    await TraceEmitter(SqlTraceRecordRepository(db, extraction_trace_policy_registry())).emit_many(records)
    return await persist_statement_extraction_result(
        db, statement=summary, result=result, source_trace_record_id=records[0].record_id
    )


async def test_reparse_preserves_history_and_current_membership(db, test_user, monkeypatch):
    """AC-extraction.persistence-proof.1: old atomic facts survive an effective result change."""
    from src.extraction.extension import deduplication

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    document, summary = await _source(db, test_user.id, account=account)
    source = DocumentSource.resolve(
        path=Path(document.file_path),
        content=b"synthetic",
        content_hash=document.file_hash,
        filename=document.original_filename,
    )
    checkpoint = MagicMock()
    monkeypatch.setattr(deduplication.logger, "info", checkpoint)
    first = await _parse(_payload(), db=db, user_id=test_user.id, account_id=account.id, source=source)
    first_record = await _store_result(db, summary, first)
    before = await resolve_statement_transactions(db, summary)
    assert len(before) == 1
    old_id = before[0].id
    changed = _payload(
        closing_balance="120",
        transactions=[
            {
                "date": "2025-01-02",
                "amount": "20",
                "direction": "IN",
                "currency": "SGD",
                "description": "Synthetic corrected deposit",
            }
        ],
    )
    second = await _parse(changed, db=db, user_id=test_user.id, account_id=account.id, source=source)
    await db.refresh(summary)
    second_record = await _store_result(db, summary, second)
    current = await resolve_statement_transactions(db, summary)
    assert await db.get(AtomicTransaction, old_id) is not None
    assert len(current) == 1 and current[0].amount == Decimal("20")
    assert current[0].id != old_id and first.result_id != second.result_id
    from src.audit.orm.trace_record import TraceRecordRow
    from src.extraction.orm.reviewed_statement_envelope import StatementExtractionResultRecord

    preserved = await db.get(StatementExtractionResultRecord, first_record.id)
    assert preserved.payload == first.to_payload()
    assert await db.get(TraceRecordRow, first_record.source_trace_record_id) is not None
    assert summary.current_extraction_result_id == second_record.id
    assert document.file_path == str(source.path)
    completion = [
        call.kwargs for call in checkpoint.call_args_list if call.args == ("Dual write to Layer 2 completed",)
    ]
    assert completion and completion[-1]["statement_summary_id"] == str(summary.id)


async def test_posted_source_cannot_be_silently_superseded(db, test_user):
    """AC-extraction.persistence-proof.1: a corrected parse cannot double-post prior truth."""
    from src.extraction import EconomicIntent
    from src.extraction.extension.review_queue import create_entry_from_txn
    from src.ledger import JournalEntry, JournalEntryStatus
    from tests.statement_ingestion import anchored_reviewed_posting_inputs

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    document, summary = await _source(db, test_user.id, account=account)
    source = DocumentSource.resolve(
        path=Path(document.file_path), content=b"synthetic", content_hash=document.file_hash
    )
    original = await _parse(_payload(), db=db, user_id=test_user.id, account_id=account.id, source=source)
    record = await _store_result(db, summary, original)
    row = (await resolve_statement_transactions(db, summary))[0]
    decision, counter, anchor, emitter = await anchored_reviewed_posting_inputs(
        db, user_id=test_user.id, transaction=row, intent=EconomicIntent.INCOME
    )
    journal = await create_entry_from_txn(
        db,
        row,
        user_id=test_user.id,
        base_currency="SGD",
        auto_post=True,
        preloaded_bank_account=account,
        disposition=decision,
        counter_account=counter,
        source_decision=anchor,
        trace_emitter=emitter,
    )
    assert journal.status is JournalEntryStatus.POSTED
    replacement = _payload(
        closing_balance="120",
        transactions=[
            {
                "date": "2025-01-02",
                "amount": "20",
                "direction": "IN",
                "currency": "SGD",
                "description": "Synthetic corrected deposit",
            }
        ],
    )
    with pytest.raises(ExtractionError, match="posted.*review|review.*posted"):
        await _parse(replacement, db=db, user_id=test_user.id, account_id=account.id, source=source)
    await db.refresh(summary)
    assert summary.current_extraction_result_id == record.id
    assert (await resolve_statement_transactions(db, summary))[0].id == row.id
    assert (
        await db.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.user_id == test_user.id)) == 1
    )


async def test_legacy_result_cannot_bypass_currency_identity(db, test_user):
    """AC-extraction.transaction-identity.2: raw legacy IDs are not a trust bypass."""
    document, summary = await _source(db, test_user.id, currency="SGD")
    wrong = await _legacy(db, test_user.id, document, currency="USD")
    result = await _parse(_payload())
    payload = result.to_payload()
    payload["transactions"][0]["fact_id"] = wrong.dedup_hash
    summary.extraction_metadata = {"statement_extraction_result": payload}
    await db.flush()
    with pytest.raises(ValueError, match="identity|currency"):
        await resolve_statement_transactions(db, summary)


async def test_source_isolation_can_adopt_confirmed_custody(db, test_user):
    """AC-extraction.transaction-identity.3: custody confirmation does not duplicate a source fact."""
    document, summary = await _source(db, test_user.id)
    original = await _upsert(db, test_user.id, document)
    original_hash = original.dedup_hash
    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    summary.account_id = account.id
    await db.flush()
    adopted = await _upsert(db, test_user.id, document)
    assert adopted.id == original.id and adopted.dedup_hash == original_hash


async def test_novel_missing_custody_sources_remain_independent(db, test_user):
    """AC-extraction.transaction-identity.3: provisional v2 facts do not claim cross-document identity."""
    first_doc, _ = await _source(db, test_user.id)
    second_doc, _ = await _source(db, test_user.id)
    first = await _upsert(db, test_user.id, first_doc)
    second = await _upsert(db, test_user.id, second_doc)
    assert first.id != second.id


async def test_failed_extraction_preserves_source_for_review(db, test_user):
    """AC-extraction.source-conservation.1: quarantine never loses the original source artifact."""
    from src.extraction import BankStatementStatus, ParseJob, Stage1Status
    from src.extraction.extension.statement_parsing import handle_parse_failure
    from src.extraction.extension.transaction_identity import TransactionIdentityReviewRequired

    document, summary = await _source(db, test_user.id)
    statement_id, document_id, file_path = summary.id, document.id, document.file_path
    job = ParseJob(
        statement_id=summary.id,
        user_id=test_user.id,
        account_id=None,
        filename=document.original_filename,
        institution=None,
        file_hash=document.file_hash,
        storage_key=document.file_path,
        model=None,
    )
    await db.commit()
    await handle_parse_failure(
        summary,
        db,
        job=job,
        message="Transaction identity requires review",
        error_type=TransactionIdentityReviewRequired.__name__,
    )
    preserved = await db.get(StatementSummary, statement_id)
    assert preserved.status is BankStatementStatus.PARSED
    assert preserved.stage1_status is Stage1Status.PENDING_REVIEW
    assert preserved.uploaded_document_id == document_id
    assert (await db.get(UploadedDocument, document_id)).file_path == file_path


async def test_generated_multicurrency_pdf_preserves_every_batch(db, test_user):
    """AC-extraction.source-conservation.2: rendered PDF pages reach complete persisted balances."""
    from io import BytesIO

    from reportlab.pdfgen import canvas

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    output = BytesIO()
    pdf = canvas.Canvas(output)
    for page in range(6):
        pdf.drawString(72, 720, f"Synthetic statement page {page + 1}")
        pdf.showPage()
    pdf.save()
    first = _payload(
        balances=[
            {"currency": "SGD", "opening": "100", "closing": "110"},
            {"currency": "USD", "opening": "200", "closing": "200"},
        ]
    )
    second = {
        "balances": [{"currency": "EUR", "opening": "300", "closing": "320"}],
        "transactions": [
            {
                "date": "2025-01-03",
                "amount": "20",
                "currency": "EUR",
                "direction": "IN",
                "description": "Synthetic EUR deposit",
            }
        ],
    }
    service = ExtractionService()
    service._extract_json_with_models = AsyncMock(side_effect=[first, second])
    source = DocumentSource.resolve(path=Path("synthetic/multicurrency.pdf"), content=output.getvalue())
    result = await service.parse_document(
        source, user_id=test_user.id, account_id=account.id, db=db, force_model="synthetic-vision"
    )
    assert result.balance_validated is True
    assert {balance.currency for balance in result.balances} == {"SGD", "USD", "EUR"}
    summary = await db.scalar(
        select(StatementSummary).where(
            StatementSummary.file_hash == source.content_hash, StatementSummary.user_id == test_user.id
        )
    )
    assert len(await resolve_statement_transactions(db, summary)) == 2
    assert service._extract_json_with_models.await_count == 2


async def test_membership_rejects_ambiguous_custody(db, test_user):
    """AC-extraction.persistence-proof.2: raw legacy identity cannot authorize two custody accounts."""
    from src.extraction import effective_statement_transaction_filter

    first_account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    second_account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add_all([first_account, second_account])
    await db.flush()
    first_doc, first_summary = await _source(db, test_user.id, account=first_account)
    second_doc, second_summary = await _source(db, test_user.id, account=second_account)
    legacy = await _legacy(db, test_user.id, first_doc)
    legacy.source_documents = [*legacy.source_documents, {"doc_id": str(second_doc.id), "doc_type": "bank_statement"}]
    result = await _parse(_payload())
    payload = result.to_payload()
    payload["transactions"][0]["fact_id"] = legacy.dedup_hash
    for summary in (first_summary, second_summary):
        summary.extraction_metadata = {"statement_extraction_result": payload}
    await db.flush()
    for scope in (None, first_summary.id, second_summary.id):
        ids = set(
            (
                await db.scalars(
                    select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id, scope))
                )
            ).all()
        )
        assert legacy.id not in ids


async def test_effective_membership_excludes_superseded_sources(db, test_user):
    """AC-extraction.persistence-proof.2: downstream selection cannot resurrect historical rows."""
    from src.extraction import effective_statement_transaction_filter

    account = AccountFactory.build(user_id=test_user.id, currency="SGD")
    db.add(account)
    await db.flush()
    document, summary = await _source(db, test_user.id, account=account)
    source = DocumentSource.resolve(
        path=Path(document.file_path), content=b"synthetic", content_hash=document.file_hash
    )
    first = await _parse(_payload(), db=db, user_id=test_user.id, account_id=account.id, source=source)
    await _store_result(db, summary, first)
    old_id = (await resolve_statement_transactions(db, summary))[0].id
    changed = _payload(
        closing_balance="120",
        transactions=[
            {
                "date": "2025-01-02",
                "amount": "20",
                "direction": "IN",
                "currency": "SGD",
                "description": "Synthetic correction",
            }
        ],
    )
    second = await _parse(changed, db=db, user_id=test_user.id, account_id=account.id, source=source)
    await _store_result(db, summary, second)
    new_id = (await resolve_statement_transactions(db, summary))[0].id
    for scope in (None, summary.id):
        ids = set(
            (
                await db.scalars(
                    select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id, scope))
                )
            ).all()
        )
        assert new_id in ids and old_id not in ids
    assert not list(
        (await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(uuid4())))).all()
    )
    standalone = await _legacy(db, test_user.id, type("Source", (), {"id": uuid4()})())
    assert standalone.id in set(
        (
            await db.scalars(select(AtomicTransaction.id).where(effective_statement_transaction_filter(test_user.id)))
        ).all()
    )
