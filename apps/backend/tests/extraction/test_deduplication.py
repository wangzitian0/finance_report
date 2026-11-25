import asyncio
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentType, TransactionDirection
from src.extraction.base.types import ExtractedTransactionRow
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.transaction_identity import TransactionIdentityReviewRequired
from src.extraction.orm.layer1 import UploadedDocument
from src.extraction.orm.layer2 import AtomicTransaction
from tests.factories import AccountFactory, StatementSummaryFactory, UserFactory


async def _known_custody_sources(db, user_id):
    account = AccountFactory.build(user_id=user_id, currency="USD")
    db.add(account)
    await db.flush()
    docs = []
    for kind in (DocumentType.BANK_STATEMENT, DocumentType.BROKERAGE_STATEMENT):
        doc = UploadedDocument(
            user_id=user_id,
            file_path=f"synthetic/{uuid4()}.pdf",
            file_hash=uuid4().hex * 2,
            original_filename="synthetic.pdf",
            document_type=kind,
        )
        db.add(doc)
        await db.flush()
        db.add(
            StatementSummaryFactory.build(
                user_id=user_id,
                uploaded_document_id=doc.id,
                file_hash=doc.file_hash,
                account_id=account.id,
                currency="USD",
            )
        )
        docs.append(doc.id)
    await db.flush()
    return docs


async def _upsert(
    service,
    *,
    db,
    user_id,
    txn_date,
    amount,
    direction,
    description,
    currency,
    source_doc_id,
    source_doc_type,
    reference=None,
    balance_after=None,
):
    row = ExtractedTransactionRow(
        user_id=user_id,
        txn_date=txn_date,
        amount=amount,
        direction=direction.value,
        description=description,
        reference=reference,
        currency=currency,
        currency_unresolved=False,
        balance_after=balance_after,
        occurrence_index=0,
        dedup_hash=service.calculate_transaction_hash(
            user_id, txn_date, amount, direction, description, reference=reference, balance_after=balance_after
        ),
    )
    return await service.upsert_scoped_atomic_transaction(
        db=db, row=row, source_doc_id=source_doc_id, source_doc_type=source_doc_type
    )


def test_calculate_transaction_hash_determinism_and_dimensions():
    service, uid, d = DeduplicationService(), uuid4(), date(2024, 1, 15)
    h = lambda desc="Test Transaction", ref="REF123", amt=Decimal(
        "100.50"
    ), bal=None, occ=0: service.calculate_transaction_hash(
        uid, d, amt, TransactionDirection.IN, desc, reference=ref, balance_after=bal, occurrence_index=occ
    )
    assert len(h()) == 64 and all(c in "0123456789abcdef" for c in h())
    assert h() == h(desc="TEST TRANSACTION") and h(ref=None) == h(ref="")
    assert h(bal=Decimal("950.00")) != h(bal=Decimal("900.00"))
    assert h(bal=Decimal("950")) == h(bal=Decimal("950.00")) == h(bal=Decimal("950.000"))
    assert h(bal=Decimal("1750.00"), occ=0) != h(bal=Decimal("1750.00"), occ=1)
    assert h(occ=0) != h(occ=1) and h(amt=Decimal("50")) == h(amt=Decimal("50.00"))


async def test_upsert_scoped_atomic_transaction_create_append_and_isolation(db, test_user):
    service, doc1_id, d = DeduplicationService(), uuid4(), date(2024, 1, 15)
    txn = await _upsert(
        service,
        db=db,
        user_id=test_user.id,
        txn_date=d,
        amount=Decimal("100.50"),
        direction=TransactionDirection.IN,
        description="Test Transaction",
        currency="USD",
        source_doc_id=doc1_id,
        source_doc_type=DocumentType.BANK_STATEMENT,
        reference="REF123",
        balance_after=Decimal("3966.50"),
    )
    reloaded = (await db.execute(select(AtomicTransaction).where(AtomicTransaction.id == txn.id))).scalar_one()
    assert (
        txn.user_id,
        txn.amount,
        txn.direction,
        txn.description,
        txn.reference,
        txn.currency,
        len(txn.dedup_hash),
        txn.source_documents,
        reloaded.balance_after,
    ) == (
        test_user.id,
        Decimal("100.50"),
        TransactionDirection.IN,
        "Test Transaction",
        "REF123",
        "USD",
        64,
        [{"doc_id": str(doc1_id), "doc_type": DocumentType.BANK_STATEMENT.value}],
        Decimal("3966.50"),
    )
    same = await _upsert(
        service,
        db=db,
        user_id=test_user.id,
        txn_date=d,
        amount=Decimal("100.50"),
        direction=TransactionDirection.IN,
        description="Test Transaction",
        currency="USD",
        source_doc_id=doc1_id,
        source_doc_type=DocumentType.BANK_STATEMENT,
        reference="REF123",
        balance_after=Decimal("3966.50"),
    )
    assert same.id == txn.id and len(same.source_documents) == 1

    other_user = await UserFactory.create_async(db)
    other_txn = await _upsert(
        service,
        db=db,
        user_id=other_user.id,
        txn_date=d,
        amount=Decimal("100.50"),
        direction=TransactionDirection.IN,
        description="Test Transaction",
        currency="USD",
        source_doc_id=doc1_id,
        source_doc_type=DocumentType.BANK_STATEMENT,
        reference="REF123",
        balance_after=Decimal("3966.50"),
    )
    assert other_txn.id != txn.id and other_txn.dedup_hash != txn.dedup_hash


async def test_upsert_merges_known_custody_sources_and_preserves_legacy_null_balance(db, test_user):
    service, (doc1_id, doc2_id) = DeduplicationService(), await _known_custody_sources(db, test_user.id)
    fields = dict(
        txn_date=date(2025, 6, 25),
        amount=Decimal("1033.50"),
        direction=TransactionDirection.OUT,
        description="Buy to Open NIO Inc NIO",
        reference=None,
    )
    legacy = AtomicTransaction(
        user_id=test_user.id,
        currency="USD",
        dedup_hash=service.calculate_transaction_hash(test_user.id, balance_after=Decimal("3966.50"), **fields),
        balance_after=None,
        source_documents=[{"doc_id": str(doc1_id), "doc_type": "brokerage_statement"}],
        **fields,
    )
    db.add(legacy)
    await db.flush()
    merged = await _upsert(
        service,
        db=db,
        user_id=test_user.id,
        currency="USD",
        source_doc_id=doc2_id,
        source_doc_type=DocumentType.BROKERAGE_STATEMENT,
        balance_after=Decimal("3966.50"),
        **fields,
    )
    assert (merged.id, merged.balance_after, {d["doc_id"] for d in merged.source_documents}) == (
        legacy.id,
        None,
        {str(doc1_id), str(doc2_id)},
    )


async def test_concurrent_upsert_same_hash_no_duplicates(db_engine, db, test_user):
    service, (doc1_id, doc2_id) = DeduplicationService(), await _known_custody_sources(db, test_user.id)
    await db.commit()

    async def upsert_in_session(doc_id):
        async with AsyncSession(db_engine) as session, session.begin():
            txn = await _upsert(
                service,
                db=session,
                user_id=test_user.id,
                txn_date=date(2024, 1, 15),
                amount=Decimal("100.50"),
                direction=TransactionDirection.IN,
                description="Concurrent Test",
                currency="USD",
                source_doc_id=doc_id,
                source_doc_type=DocumentType.BANK_STATEMENT,
                reference="CONCURRENT",
            )
            return {"id": txn.id, "dedup_hash": txn.dedup_hash, "source_count": len(txn.source_documents)}

    results = await asyncio.gather(upsert_in_session(doc1_id), upsert_in_session(doc2_id), return_exceptions=True)
    ok = [r for r in results if not isinstance(r, Exception)]
    if any(isinstance(r, IntegrityError) for r in results):
        assert len(ok) == 1 and ok[0]["source_count"] == 1
    else:
        assert len(ok) == 2 and ok[0]["id"] == ok[1]["id"]
        async with AsyncSession(db_engine) as session:
            assert (
                len(
                    (
                        await session.execute(
                            select(AtomicTransaction).where(AtomicTransaction.dedup_hash == ok[0]["dedup_hash"])
                        )
                    )
                    .scalars()
                    .all()
                )
                == 1
            )


async def test_upsert_scoped_atomic_transaction_handles_non_list_source_documents(db, test_user):
    service = DeduplicationService()
    txn = await _upsert(
        service,
        db=db,
        user_id=test_user.id,
        txn_date=date(2024, 2, 1),
        amount=Decimal("12.00"),
        direction=TransactionDirection.OUT,
        description="Bad source docs",
        currency="SGD",
        source_doc_id=uuid4(),
        source_doc_type=DocumentType.BANK_STATEMENT,
    )
    txn.source_documents = {"bad": "shape"}
    await db.flush()
    with pytest.raises(TransactionIdentityReviewRequired, match="review"):
        await _upsert(
            service,
            db=db,
            user_id=test_user.id,
            txn_date=date(2024, 2, 1),
            amount=Decimal("12.00"),
            direction=TransactionDirection.OUT,
            description="Bad source docs",
            currency="SGD",
            source_doc_id=uuid4(),
            source_doc_type=DocumentType.BROKERAGE_STATEMENT,
        )
