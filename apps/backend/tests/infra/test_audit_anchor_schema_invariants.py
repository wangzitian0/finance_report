from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.audit import JournalEntrySourceType
from src.extraction import BankStatementStatus, ClassificationStatus, DocumentStatus, DocumentType, RuleType
from src.extraction.extension.evidence_graph_materialization import EvidenceGraphMaterializationService
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode
from src.extraction.orm.layer2 import AtomicPosition, AtomicPositionSourceDocument, AtomicTransactionSourceDocument
from src.extraction.orm.layer3 import ClassificationRule, TransactionClassification
from src.extraction.orm.statement_summary import StatementSummary
from src.identity import User
from src.ledger import Direction, JournalEntryStatus, JournalLine
from src.reconciliation import (
    ReconciliationMatch,
    ReconciliationMatchJournalEntry,
    ReconciliationStatus,
    sync_reconciliation_matches_journal_entry_links_batch,
)
from tests.factories import (
    AccountFactory,
    AtomicTransactionFactory,
    JournalEntryFactory,
    UploadedDocumentFactory,
    UserFactory,
)

BACKEND_DIR = Path(__file__).parent.parent.parent


async def _reject_integrity(db: AsyncSession, *objects: object) -> None:
    db.add_all(objects)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries(
    db: AsyncSession, test_user: User
) -> None:
    other = await UserFactory.create_async(db)
    atomic = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, source_documents=[])
    entry = await JournalEntryFactory.create_async(db, user_id=test_user.id, status=JournalEntryStatus.DRAFT)
    other_entry = await JournalEntryFactory.create_async(db, user_id=other.id, status=JournalEntryStatus.DRAFT)
    missing_id = uuid4()
    match = ReconciliationMatch(
        atomic_txn_id=atomic.id,
        journal_entry_ids=[str(entry.id), str(other_entry.id), str(missing_id), "not-a-uuid"],
        match_score=100,
        score_breakdown={"anchor": 100.0},
        status=ReconciliationStatus.ACCEPTED,
    )
    db.add(match)
    await db.flush()
    mid, eid, oeid = match.id, entry.id, other_entry.id
    await sync_reconciliation_matches_journal_entry_links_batch(db, [match])
    await db.commit()
    assert await db.get(ReconciliationMatchJournalEntry, (mid, eid)) is not None
    assert (
        await db.get(ReconciliationMatchJournalEntry, (mid, oeid)) is None
        and await db.get(ReconciliationMatchJournalEntry, (mid, missing_id)) is None
    )
    for bad in (uuid4(), oeid):
        await _reject_integrity(db, ReconciliationMatchJournalEntry(match_id=mid, journal_entry_id=bad))


async def test_AC18_11_2_atomic_source_links_reject_missing_and_cross_user_documents(
    db: AsyncSession, test_user: User
) -> None:
    other = await UserFactory.create_async(db)
    txn = await AtomicTransactionFactory.create_async(db, user_id=test_user.id, source_documents=[])
    pos = AtomicPosition(
        user_id=test_user.id,
        snapshot_date=date(2026, 3, 1),
        asset_identifier=f"A-{uuid4().hex[:8]}",
        broker="Anchor",
        quantity=Decimal("1"),
        market_value=Decimal("100.00"),
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=[],
    )
    db.add(pos)
    await db.flush()
    t_doc = await UploadedDocumentFactory.create_async(db, user_id=test_user.id, status=DocumentStatus.COMPLETED)
    p_doc = await UploadedDocumentFactory.create_async(
        db, user_id=test_user.id, document_type=DocumentType.BROKERAGE_STATEMENT, status=DocumentStatus.COMPLETED
    )
    o_doc = await UploadedDocumentFactory.create_async(db, user_id=other.id, status=DocumentStatus.COMPLETED)
    tid, pid, odid = txn.id, pos.id, o_doc.id
    db.add_all(
        [
            AtomicTransactionSourceDocument(
                atomic_txn_id=tid, uploaded_document_id=t_doc.id, doc_type=DocumentType.BANK_STATEMENT.value, ordinal=0
            ),
            AtomicPositionSourceDocument(
                atomic_position_id=pid,
                uploaded_document_id=p_doc.id,
                doc_type=DocumentType.BROKERAGE_STATEMENT.value,
                ordinal=0,
            ),
        ]
    )
    await db.commit()
    await _reject_integrity(
        db,
        AtomicTransactionSourceDocument(
            atomic_txn_id=tid, uploaded_document_id=uuid4(), doc_type=DocumentType.BANK_STATEMENT.value, ordinal=1
        ),
    )
    await _reject_integrity(
        db,
        AtomicPositionSourceDocument(
            atomic_position_id=pid, uploaded_document_id=odid, doc_type=DocumentType.BANK_STATEMENT.value, ordinal=1
        ),
    )


async def test_AC18_11_3_evidence_edges_reject_cross_user_endpoints_and_preserve_tenant_scope(
    db: AsyncSession, test_user: User
) -> None:
    other = await UserFactory.create_async(db)
    uid = test_user.id
    src, tgt = (
        EvidenceNode(
            user_id=uid, node_kind="source_document", entity_type="uploaded_document", entity_id=uuid4(), properties={}
        ),
        EvidenceNode(
            user_id=uid, node_kind="atomic_fact", entity_type="atomic_transaction", entity_id=uuid4(), properties={}
        ),
    )
    otgt = EvidenceNode(
        user_id=other.id, node_kind="atomic_fact", entity_type="atomic_transaction", entity_id=uuid4(), properties={}
    )
    db.add_all([src, tgt, otgt])
    await db.flush()
    sid, otgt_id = src.id, otgt.id
    db.add(EvidenceEdge(user_id=uid, from_node_id=sid, to_node_id=tgt.id, relation="deduped_into", properties={}))
    await db.commit()
    await _reject_integrity(
        db, EvidenceEdge(user_id=uid, from_node_id=sid, to_node_id=otgt_id, relation="deduped_into", properties={})
    )

    edge = EvidenceEdge(user_id=uid, from_node_id=sid, to_node_id=otgt_id, relation="deduped_into", properties={})
    await db.execute(text("SET LOCAL session_replication_role = replica"))
    try:
        db.add(edge)
        await db.flush()
    finally:
        await db.execute(text("SET LOCAL session_replication_role = DEFAULT"))
    eid = edge.id
    db.expunge_all()
    reloaded = (
        await db.execute(
            select(EvidenceEdge)
            .options(selectinload(EvidenceEdge.from_node), selectinload(EvidenceEdge.to_node))
            .where(EvidenceEdge.id == eid)
        )
    ).scalar_one()
    assert reloaded.from_node.id == sid and reloaded.to_node is None


async def test_AC18_11_4_and_5_account_refs_and_legacy_source_ids(db: AsyncSession, test_user: User) -> None:
    other = await UserFactory.create_async(db)
    uid = test_user.id
    own_acc, other_acc = (
        await AccountFactory.create_async(db, user_id=uid),
        await AccountFactory.create_async(db, user_id=other.id),
    )
    entry = await JournalEntryFactory.create_async(
        db,
        user_id=uid,
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=uuid4(),
        status=JournalEntryStatus.DRAFT,
    )
    atomic = await AtomicTransactionFactory.create_async(db, user_id=uid, source_documents=[])
    rule = ClassificationRule(
        user_id=uid,
        version_number=1,
        effective_date=date(2026, 3, 1),
        is_active=True,
        rule_name=f"r-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["anchor"]},
        created_by=uid,
    )
    db.add(rule)
    await db.flush()
    own_id, other_id, eid, aid, rid = own_acc.id, other_acc.id, entry.id, atomic.id, rule.id
    await db.commit()
    for bad in (
        JournalLine(
            journal_entry_id=eid,
            account_id=other_id,
            direction=Direction.DEBIT,
            amount=Decimal("10.00"),
            currency="SGD",
        ),
        StatementSummary(
            user_id=uid,
            file_hash=uuid4().hex + uuid4().hex,
            institution="B",
            account_id=other_id,
            currency="SGD",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            opening_balance=Decimal("100"),
            closing_balance=Decimal("110"),
            status=BankStatementStatus.APPROVED,
        ),
        TransactionClassification(
            atomic_txn_id=aid, rule_version_id=rid, account_id=other_id, status=ClassificationStatus.APPLIED
        ),
    ):
        await _reject_integrity(db, bad)
    own_line = JournalLine(
        journal_entry_id=eid, account_id=own_id, direction=Direction.DEBIT, amount=Decimal("10.00"), currency="SGD"
    )
    db.add_all(
        [
            TransactionClassification(
                atomic_txn_id=aid, rule_version_id=rid, account_id=own_id, status=ClassificationStatus.APPLIED
            ),
            own_line,
        ]
    )
    await db.flush()
    lid = own_line.id
    await db.commit()
    mat = await EvidenceGraphMaterializationService().materialize_for_entity(
        db, user_id=uid, entity_type="journal_line", entity_id=lid, node_kind="ledger_line"
    )
    assert (
        "entity_missing" in {b.code for b in mat.blockers}
        and list(
            (
                await db.execute(
                    select(EvidenceNode).where(EvidenceNode.user_id == uid, EvidenceNode.node_kind == "source_document")
                )
            ).scalars()
        )
        == []
    )


def test_AC18_11_6_migration_preflights_and_risk_contract_are_declared() -> None:
    mig = (BACKEND_DIR / "migrations" / "versions" / "0034_audit_anchor_referential_integrity.py").read_text()
    risk = (BACKEND_DIR.parent.parent / "common" / "meta" / "data" / "migration-risk.yaml").read_text()
    assert all(
        t in mig
        for t in (
            "reconciliation_match_journal_entries",
            "atomic_transaction_source_documents",
            "atomic_position_source_documents",
            "fr_validate_evidence_edge_tenant_scope",
            "fr_validate_journal_line_account_user",
            "backfill resolvable legacy audit anchors",
            "unresolved legacy audit anchors remain preserved",
            "raw_entry.entry_id_text ~*",
            "(source_item.value ->> 'doc_id') ~*",
        )
    )
    assert "0034_audit_anchor_ri" in risk and ("Issue #846" in risk or 'issue: "#846"' in risk)
