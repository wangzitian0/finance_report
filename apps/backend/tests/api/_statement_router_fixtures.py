"""Shared fixtures and database seed helpers for statements API tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from fastapi import UploadFile

from src.extraction import (
    BankStatementStatus,
    DocumentSource,
    DocumentType,
    ExtractedTransactionRow,
    ExtractionMethod,
    RuleType,
    StatementEvidenceType,
    TransactionDirection,
    UploadedDocument,
)
from src.extraction.extension.deduplication import dual_write_layer2
from src.extraction.extension.result_contract import build_statement_extraction_result
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType


def _compose_mock_ingestion(mock_execute):
    def compose(*, session_maker):
        assert session_maker is not None

        class FakeUseCase:
            async def execute(self, job, *, content=None):
                return await mock_execute(job=job, content=content)

        return FakeUseCase()

    return compose


def make_upload_file(name: str, content: bytes) -> UploadFile:
    """Create an UploadFile for testing."""
    return UploadFile(
        filename=name,
        file=BytesIO(content),
    )


def build_statement(user_id, file_hash: str, confidence_score: int) -> StatementSummary:
    """Build a StatementSummary (DWD conform) envelope for tests.

    Layer-1 file metadata (``file_path``/``original_filename``) now lives on the
    ODS ``UploadedDocument``; use :func:`seed_uploaded_document` to attach one when a
    test needs storage keys, filenames, or transaction resolution.
    """
    return StatementSummary(
        user_id=user_id,
        account_id=None,
        file_hash=file_hash,
        institution="DBS",
        account_last4="1234",
        currency="SGD",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 1, 31),
        opening_balance=Decimal("100.00"),
        closing_balance=Decimal("110.00"),
        status=BankStatementStatus.PARSED,
        confidence_score=confidence_score,
        balance_validated=True,
    )


async def seed_uploaded_document(
    db,
    statement: StatementSummary,
    *,
    file_path: str = "tmp",
    original_filename: str = "stub.pdf",
) -> UploadedDocument:
    """Create the ODS ``UploadedDocument`` backing a statement and link it.

    Idempotent: if the statement already has an ``uploaded_document_id`` the existing
    document is returned. Returns the document so callers can build
    ``AtomicTransaction`` facts that reference it via ``source_documents``.
    """
    if statement.uploaded_document_id is not None:
        existing = await db.get(UploadedDocument, statement.uploaded_document_id)
        if existing is not None:
            return existing
    document = UploadedDocument(
        user_id=statement.user_id,
        file_path=file_path,
        file_hash=statement.file_hash,
        original_filename=original_filename,
        document_type=DocumentType.BANK_STATEMENT,
    )
    db.add(document)
    await db.flush()
    statement.uploaded_document_id = document.id
    db.add(statement)
    await db.flush()
    return document


async def seed_historical_source_evidence(db, statement: StatementSummary) -> None:
    """Retained custody is backed by an immutable source, not a mutable summary."""
    from pathlib import Path

    from tests.extraction.test_source_ingestion_integrity import _parse, _payload, _store_result

    document = await seed_uploaded_document(db, statement)
    source = DocumentSource.resolve(path=Path("synthetic-history.pdf"), content=statement.file_hash.encode())
    document.file_hash = statement.file_hash = source.content_hash
    result = await _parse(
        _payload(
            institution=statement.institution,
            account_last4=statement.account_last4,
            currency=statement.currency,
        ),
        user_id=statement.user_id,
        source=source,
    )
    await _store_result(db, statement, result)


async def persist_mock_result(
    db,
    *,
    source: DocumentSource,
    statement: StatementSummary,
    transactions: list[ExtractedTransactionRow],
):
    """Keep router fakes on the production source-to-fact result boundary."""
    result = build_statement_extraction_result(
        source=source,
        file_type="pdf",
        statement=statement,
        transactions=transactions,
        provider_payload={"transactions": []},
        model="router-fixture",
        provider="router-fixture",
        method=ExtractionMethod.GOLDEN_FIXTURE,
        is_brokerage=False,
        evidence_type=StatementEvidenceType.TRANSACTION_LEDGER,
        positions=[],
    )
    await dual_write_layer2(
        db,
        statement.user_id,
        statement,
        transactions,
        original_filename=source.filename,
        extraction_metadata={"statement_extraction_result": result.to_payload()},
    )
    return result


async def add_reviewed_disposition_rule(
    db,
    *,
    user_id,
    keyword: str,
    account_type: AccountType,
    category: str,
) -> None:
    """Seed explicit user-owned economic meaning for a posting-flow test."""
    account = Account(
        user_id=user_id,
        name=f"{account_type.value.title()} - {category}",
        type=account_type,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    db.add(
        ClassificationRule(
            user_id=user_id,
            version_number=1,
            effective_date=date(2025, 1, 1),
            rule_name=f"Reviewed {category} rule",
            rule_type=RuleType.KEYWORD_MATCH,
            rule_config={"keywords": [keyword]},
            tag_mappings={"category": category},
            default_account_id=account.id,
            created_by=user_id,
        )
    )
    await db.flush()


async def add_txn(
    db,
    statement,
    *,
    txn_date: date,
    description: str,
    amount: Decimal,
    direction: str,
) -> AtomicTransaction:
    """Build, persist, and return a Layer-2 ``AtomicTransaction`` for a statement.

    ``statement`` may be a :class:`StatementSummary` or its ``id`` (UUID). Lazily
    seeds the statement's ODS ``UploadedDocument`` so the fact resolves back to its
    owning envelope via ``source_documents -> UploadedDocument -> StatementSummary``
    (atomic transactions carry no ``statement_id``).
    """
    if not isinstance(statement, StatementSummary):
        statement = await db.get(StatementSummary, statement)
    document = await seed_uploaded_document(db, statement)
    txn = AtomicTransaction(
        user_id=statement.user_id,
        txn_date=txn_date,
        description=description,
        amount=amount,
        direction=TransactionDirection(direction),
        currency=statement.currency or "SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[{"doc_id": str(document.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
    )
    db.add(txn)
    await db.flush()
    return txn
