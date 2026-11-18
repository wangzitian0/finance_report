import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from src.extraction import BankStatementStatus, ParseJob, Stage1Status, StartedRun
from src.extraction.base.paged_extraction import merge_paged_extractions
from src.extraction.base.validation import validate_balance_per_currency
from src.extraction.extension.brokerage_positions import looks_like_brokerage_payload
from src.extraction.extension.brokerage_statement_payload import _extract_brokerage_payload_from_metadata
from src.extraction.extension.service import ExtractionError
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
        AsyncMock(), statement, statement.user_id, allowed_statuses=frozenset(), model=None
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
        model=None,
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
