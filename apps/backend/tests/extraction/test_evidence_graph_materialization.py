from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.audit import JournalEntrySourceType
from src.extraction import DocumentStatus, DocumentType, TransactionDirection, UploadedDocument
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.evidence_graph_integration import EvidenceGraphIntegrationService
from src.extraction.extension.evidence_graph_materialization import EvidenceGraphMaterializationService
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.extraction.orm.layer2 import AtomicTransaction
from src.identity import User
from src.ledger import AccountType, Direction, JournalEntry, JournalEntryStatus, JournalLine
from tests.extraction._statement_run_helpers import make_account


async def _create_historical_statement_entry(
    db: AsyncSession, *, user_id, entry_source_id: UUID | None = None
) -> tuple[UploadedDocument, AtomicTransaction, JournalEntry, JournalLine]:
    bank = await make_account(db, user_id, name=f"Lazy Bank {uuid4()}", type=AccountType.ASSET)
    income = await make_account(db, user_id, name=f"Lazy Income {uuid4()}", type=AccountType.INCOME)
    document = UploadedDocument(
        user_id=user_id,
        file_path="s3://lazy/history.csv",
        file_hash=f"lazy-{uuid4().hex}",
        original_filename="history.csv",
        document_type=DocumentType.BANK_STATEMENT,
        status=DocumentStatus.COMPLETED,
    )
    db.add(document)
    await db.flush()
    txn_date, amount, description, reference = (
        date(2026, 5, 1),
        Decimal("42.00"),
        "Historical income",
        f"LZ-{uuid4().hex[:8]}",
    )
    dedup_hash = DeduplicationService.calculate_transaction_hash(
        user_id, txn_date, amount, TransactionDirection.IN, description, reference
    )
    atomic_id = uuid4()
    atomic = AtomicTransaction(
        id=atomic_id,
        user_id=user_id,
        txn_date=txn_date,
        amount=amount,
        direction=TransactionDirection.IN,
        description=description,
        reference=reference,
        currency="SGD",
        dedup_hash=dedup_hash,
        source_documents=[{"doc_id": str(document.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
    )
    entry = JournalEntry(
        user_id=user_id,
        entry_date=txn_date,
        memo="Historical posted income",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=entry_source_id or atomic_id,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([atomic, entry])
    await db.flush()
    debit = JournalLine(
        journal_entry_id=entry.id, account_id=bank.id, direction=Direction.DEBIT, amount=amount, currency="SGD"
    )
    credit = JournalLine(
        journal_entry_id=entry.id, account_id=income.id, direction=Direction.CREDIT, amount=amount, currency="SGD"
    )
    db.add_all([debit, credit])
    await db.flush()
    await db.refresh(entry, ["lines"])
    return document, atomic, entry, credit


async def _graph_counts(db: AsyncSession) -> tuple[int, int]:
    return (await db.execute(select(func.count(EvidenceNode.id)))).scalar_one(), (
        await db.execute(select(func.count(EvidenceEdge.id)))
    ).scalar_one()


async def test_AC18_10_2_graph_writes_share_the_business_transaction(db: AsyncSession, test_user: User):
    _, atomic, entry, _ = await _create_historical_statement_entry(db, user_id=test_user.id)
    await EvidenceGraphIntegrationService().record_journal_posting(
        db, user_id=test_user.id, atomic_transaction=atomic, journal_entry=entry
    )
    assert (await _graph_counts(db))[0] > 0
    await db.rollback()
    assert await _graph_counts(db) == (0, 0)


async def test_AC18_10_4_AC18_10_6_lazy_materialization_is_idempotent_and_preserves_accounting_facts(
    db: AsyncSession, test_user: User
):
    document, atomic, entry, line = await _create_historical_statement_entry(db, user_id=test_user.id)
    orig = (entry.source_type, entry.source_id, line.amount)
    service = EvidenceGraphMaterializationService()
    first = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="journal_line", entity_id=line.id, node_kind="ledger_line"
    )
    first_counts = await _graph_counts(db)
    second = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="journal_line", entity_id=line.id, node_kind="ledger_line"
    )
    node_keys = {
        (n.node_kind, n.entity_type, n.entity_id) for n in (await db.execute(select(EvidenceNode))).scalars().all()
    }
    assert (
        first.blockers,
        second.blockers,
        first.created_nodes > 0,
        first.created_edges > 0,
        second.created_nodes,
        second.created_edges,
        await _graph_counts(db) == first_counts,
        (entry.source_type, entry.source_id, line.amount) == orig,
    ) == ([], [], True, True, 0, 0, True, True)
    assert {
        ("source_document", "uploaded_document", document.id),
        ("atomic_fact", "atomic_transaction", atomic.id),
        ("ledger_entry", "journal_entry", entry.id),
        ("ledger_line", "journal_line", line.id),
    } <= node_keys


async def test_AC18_10_7_materialization_caps_and_unknown_sources_return_blockers(db: AsyncSession, test_user: User):
    _, _, _, line = await _create_historical_statement_entry(db, user_id=test_user.id)
    service = EvidenceGraphMaterializationService()
    capped = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="journal_line", entity_id=line.id, node_kind="ledger_line", max_writes=0
    )
    assert [b.code for b in capped.blockers] == ["materialization_write_cap_reached"] and await _graph_counts(db) == (
        0,
        0,
    )
    _, _, _, unknown_line = await _create_historical_statement_entry(db, user_id=test_user.id, entry_source_id=uuid4())
    unknown = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="journal_line", entity_id=unknown_line.id, node_kind="ledger_line"
    )
    assert "entity_missing" in {b.code for b in unknown.blockers}


async def test_AC18_10_4_direct_entity_materialization_branches_are_idempotent(db: AsyncSession, test_user: User):
    document, atomic, entry, _ = await _create_historical_statement_entry(db, user_id=test_user.id)
    service = EvidenceGraphMaterializationService()
    je_res = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="journal_entry", entity_id=entry.id, node_kind="ledger_entry"
    )
    doc_res = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="uploaded_document", entity_id=document.id
    )
    atm_res = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="atomic_transaction", entity_id=atomic.id, node_kind="atomic_fact"
    )
    unsup = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="future_table", entity_id=uuid4()
    )
    unsup_kind = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="future_table", entity_id=uuid4(), node_kind="ledger_line"
    )
    nodes = {
        (n.node_kind, n.entity_type, n.entity_id): n
        for n in (await db.execute(select(EvidenceNode).where(EvidenceNode.user_id == test_user.id))).scalars()
    }
    edges = {
        (e.from_node_id, e.to_node_id, e.relation)
        for e in (await db.execute(select(EvidenceEdge).where(EvidenceEdge.user_id == test_user.id))).scalars()
    }
    assert (
        je_res.blockers,
        doc_res.blockers,
        atm_res.blockers,
        je_res.has_writes,
        [b.code for b in unsup.blockers],
        [b.code for b in unsup_kind.blockers],
    ) == ([], [], [], True, ["unsupported_provenance"], ["unsupported_provenance"])
    assert {
        ("source_document", "uploaded_document", document.id),
        ("atomic_fact", "atomic_transaction", atomic.id),
        ("ledger_entry", "journal_entry", entry.id),
    } <= set(nodes)
    assert {
        (
            nodes["source_document", "uploaded_document", document.id].id,
            nodes["atomic_fact", "atomic_transaction", atomic.id].id,
            "deduped_into",
        ),
        (
            nodes["atomic_fact", "atomic_transaction", atomic.id].id,
            nodes["ledger_entry", "journal_entry", entry.id].id,
            "posted_as",
        ),
    } <= edges


async def test_AC18_10_7_missing_and_cross_user_requests_return_explicit_blockers(db: AsyncSession, test_user: User):
    other_user = User(email=f"other-{uuid4()}@example.com", hashed_password="x")
    db.add(other_user)
    await db.flush()
    document, atomic, entry, line = await _create_historical_statement_entry(db, user_id=other_user.id)
    service = EvidenceGraphMaterializationService()
    missing = [
        await service.materialize_for_entity(
            db, user_id=test_user.id, entity_type=et, entity_id=uuid4(), **({"node_kind": nk} if nk else {})
        )
        for et, nk in [
            ("journal_line", "ledger_line"),
            ("journal_entry", "ledger_entry"),
            ("uploaded_document", None),
            ("atomic_transaction", "atomic_fact"),
        ]
    ]
    line_cross = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="journal_line", entity_id=line.id, node_kind="ledger_line"
    )
    entry_cross = await service.materialize_for_entity(
        db, user_id=test_user.id, entity_type="journal_entry", entity_id=entry.id, node_kind="ledger_entry"
    )
    assert all(r.blockers[0].code == "entity_missing" for r in missing)
    assert (
        [b.code for b in line_cross.blockers],
        [b.code for b in entry_cross.blockers],
        await _graph_counts(db),
        document.user_id,
        atomic.user_id,
    ) == (["cross_user_lineage_blocked"], ["cross_user_lineage_blocked"], (0, 0), other_user.id, other_user.id)


async def test_record_journal_postings_batch(db: AsyncSession, test_user: User):
    service = EvidenceGraphIntegrationService()
    doc1, atomic1, entry1, line1 = await _create_historical_statement_entry(db, user_id=test_user.id)
    doc2, atomic2, entry2, line2 = await _create_historical_statement_entry(db, user_id=test_user.id)
    await service.record_journal_postings_batch(db, user_id=test_user.id, postings=[])
    assert await _graph_counts(db) == (0, 0)
    await service.record_journal_postings_batch(
        db, user_id=test_user.id, postings=[(entry1, atomic1), (entry2, atomic2)]
    )
    nodes = {
        (n.node_kind, n.entity_type, n.entity_id): n
        for n in (await db.execute(select(EvidenceNode).where(EvidenceNode.user_id == test_user.id))).scalars()
    }
    edges = {
        (e.from_node_id, e.to_node_id, e.relation)
        for e in (await db.execute(select(EvidenceEdge).where(EvidenceEdge.user_id == test_user.id))).scalars()
    }
    assert (len(nodes), len(edges)) == (10, 8)
    assert {
        ("source_document", "uploaded_document", doc1.id),
        ("atomic_fact", "atomic_transaction", atomic1.id),
        ("ledger_entry", "journal_entry", entry1.id),
        ("ledger_line", "journal_line", line1.id),
        ("source_document", "uploaded_document", doc2.id),
        ("atomic_fact", "atomic_transaction", atomic2.id),
        ("ledger_entry", "journal_entry", entry2.id),
        ("ledger_line", "journal_line", line2.id),
    } <= set(nodes)
    assert {
        (
            nodes["source_document", "uploaded_document", doc1.id].id,
            nodes["atomic_fact", "atomic_transaction", atomic1.id].id,
            "deduped_into",
        ),
        (
            nodes["atomic_fact", "atomic_transaction", atomic1.id].id,
            nodes["ledger_entry", "journal_entry", entry1.id].id,
            "posted_as",
        ),
        (
            nodes["ledger_entry", "journal_entry", entry1.id].id,
            nodes["ledger_line", "journal_line", line1.id].id,
            "contains",
        ),
    } <= edges
