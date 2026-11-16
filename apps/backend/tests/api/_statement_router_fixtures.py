from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from src.extraction import (
    BankStatementStatus,
    ClassificationStatus,
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
from src.extraction.extension.transaction_classification import POLICY_RULE_NAME
from src.extraction.orm.layer2 import AtomicTransaction
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.extraction.orm.statement_summary import StatementSummary
from src.ledger import Account, AccountType, JournalEntry
from src.reconciliation.orm.reconciliation import ReconciliationMatch


def _compose_mock_ingestion(mock_execute):
    def compose(*, session_maker):
        assert session_maker is not None

        class FakeUseCase:
            async def execute(self, job, *, content=None):
                return await mock_execute(job=job, content=content)

        return FakeUseCase()

    return compose


def make_upload_file(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content))


def build_statement(user_id, file_hash: str, confidence_score: int) -> StatementSummary:
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
    from pathlib import Path

    from tests.extraction.test_source_ingestion_integrity import _parse, _payload, _store_result

    document = await seed_uploaded_document(db, statement)
    source = DocumentSource.resolve(path=Path("synthetic-history.pdf"), content=statement.file_hash.encode())
    document.file_hash = statement.file_hash = source.content_hash
    result = await _parse(
        _payload(institution=statement.institution, account_last4=statement.account_last4, currency=statement.currency),
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
    await _apply_rules_to_existing_rows(db, user_id)


async def _apply_rules_to_existing_rows(db, user_id) -> None:
    from src.extraction.extension.classification import ClassificationService

    transactions = (
        (await db.execute(select(AtomicTransaction).where(AtomicTransaction.user_id == user_id))).scalars().all()
    )
    # The classify run applies stored rules; approve no longer does (#2994).
    await ClassificationService().apply_rules(db, user_id, list(transactions))


async def add_txn(
    db,
    statement,
    *,
    txn_date: date,
    description: str,
    amount: Decimal,
    direction: str,
) -> AtomicTransaction:
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


async def create_statement_account(db, user_id, name: str = "DBS Statement Account") -> Account:
    account = Account(user_id=user_id, name=name, type=AccountType.ASSET, currency="SGD")
    db.add(account)
    await db.flush()
    return account


async def create_category_account(db, user_id, name: str, account_type: AccountType) -> Account:
    account = Account(user_id=user_id, name=name, type=account_type, currency="SGD")
    db.add(account)
    await db.flush()
    return account


async def seed_classification(
    db,
    user_id,
    txn,
    *,
    category: str,
    account: Account | None,
    score: int,
    status: ClassificationStatus = ClassificationStatus.DRAFT,
) -> None:
    rule = (
        await db.execute(
            select(ClassificationRule)
            .where(ClassificationRule.user_id == user_id)
            .where(ClassificationRule.rule_name == POLICY_RULE_NAME)
        )
    ).scalar_one_or_none()
    if rule is None:
        rule = ClassificationRule(
            user_id=user_id,
            created_by=user_id,
            rule_name=POLICY_RULE_NAME,
            version_number=2,
            effective_date=date(2020, 1, 1),
            is_active=False,
            rule_type=RuleType.ML_MODEL,
            rule_config={"policy_version": 2},
        )
        db.add(rule)
        await db.flush()
    db.add(
        TransactionClassification(
            atomic_txn_id=txn.id,
            rule_version_id=rule.id,
            account_id=account.id if account else None,
            tags={"category": category, "reason": "test"},
            confidence_score=score,
            status=status,
        )
    )
    await db.flush()


async def create_statement_with_bank(
    db,
    user_id,
    file_hash: str,
    *,
    closing: str = "100.00",
    confidence: int = 88,
    bank_name: str | None = None,
) -> tuple[StatementSummary, Account]:
    bank = await create_statement_account(db, user_id, bank_name or f"Bank {file_hash}")
    statement = build_statement(user_id, file_hash, confidence)
    statement.account_id = bank.id
    statement.closing_balance = Decimal(closing)
    db.add(statement)
    await db.flush()
    return statement, bank


async def counter_account_names(db, txn, bank_id) -> set[str]:
    entry = (
        await db.execute(
            select(JournalEntry).where(JournalEntry.source_id == txn.id).options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    account_ids = {line.account_id for line in entry.lines if line.account_id != bank_id}
    return set((await db.execute(select(Account.name).where(Account.id.in_(account_ids)))).scalars())


async def leg_and_entry_for(db, txn) -> tuple[ReconciliationMatch, JournalEntry]:
    match = (
        await db.execute(select(ReconciliationMatch).where(ReconciliationMatch.atomic_txn_id == txn.id))
    ).scalar_one()
    entry = (
        await db.execute(
            select(JournalEntry)
            .where(JournalEntry.id == match.journal_entry_ids[0])
            .options(selectinload(JournalEntry.lines))
        )
    ).scalar_one()
    return match, entry
