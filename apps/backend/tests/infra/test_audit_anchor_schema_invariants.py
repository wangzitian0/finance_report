"""Database-level audit anchor invariant tests for issue #846."""

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

from src.extraction.extension.evidence_graph_materialization import EvidenceGraphMaterializationService
from src.identity import User
from src.models.account import Account, AccountType
from src.models.evidence import EvidenceEdge, EvidenceNode
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer1 import DocumentStatus, DocumentType, UploadedDocument
from src.models.layer2 import (
    AtomicPosition,
    AtomicPositionSourceDocument,
    AtomicTransaction,
    AtomicTransactionSourceDocument,
    TransactionDirection,
)
from src.models.layer3 import ClassificationRule, ClassificationStatus, RuleType, TransactionClassification
from src.models.reconciliation import ReconciliationMatch, ReconciliationMatchJournalEntry, ReconciliationStatus
from src.models.statement_enums import BankStatementStatus
from src.models.statement_summary import StatementSummary
from src.reconciliation import sync_reconciliation_match_journal_entry_links

BACKEND_DIR = Path(__file__).parent.parent.parent
MIGRATION_PATH = BACKEND_DIR / "migrations" / "versions" / "0034_audit_anchor_referential_integrity.py"
RISK_PATH = BACKEND_DIR.parent.parent / "docs" / "ssot" / "migration-risk.yaml"


async def _expect_integrity_error(db: AsyncSession, *objects: object) -> None:
    db.add_all(objects)
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


async def _make_user(db: AsyncSession, *, email_prefix: str = "anchor") -> User:
    user = User(
        email=f"{email_prefix}-{uuid4().hex}@example.com",
        hashed_password="test",
        ai_settings={},
    )
    db.add(user)
    await db.flush()
    return user


async def _make_account(
    db: AsyncSession,
    user_id,
    *,
    name: str | None = None,
    account_type: AccountType = AccountType.ASSET,
) -> Account:
    account = Account(
        user_id=user_id,
        name=name or f"Anchor Account {uuid4()}",
        type=account_type,
        currency="SGD",
    )
    db.add(account)
    await db.flush()
    return account


async def _make_document(db: AsyncSession, user_id, *, document_type: DocumentType) -> UploadedDocument:
    document = UploadedDocument(
        user_id=user_id,
        file_path=f"s3://anchor/{uuid4().hex}.csv",
        file_hash=uuid4().hex + uuid4().hex,
        original_filename="anchor.csv",
        document_type=document_type,
        status=DocumentStatus.COMPLETED,
    )
    db.add(document)
    await db.flush()
    return document


async def _make_atomic_transaction(
    db: AsyncSession,
    user_id,
    *,
    source_documents: object | None = None,
) -> AtomicTransaction:
    atomic = AtomicTransaction(
        user_id=user_id,
        txn_date=date(2026, 3, 1),
        amount=Decimal("42.00"),
        direction=TransactionDirection.IN,
        description=f"Anchor txn {uuid4()}",
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=source_documents if source_documents is not None else [],
    )
    db.add(atomic)
    await db.flush()
    return atomic


async def _make_atomic_position(
    db: AsyncSession,
    user_id,
    *,
    source_documents: object | None = None,
) -> AtomicPosition:
    position = AtomicPosition(
        user_id=user_id,
        snapshot_date=date(2026, 3, 1),
        asset_identifier=f"ANCHOR-{uuid4().hex[:8]}",
        broker="Anchor Broker",
        quantity=Decimal("1.000000"),
        market_value=Decimal("100.00"),
        currency="SGD",
        dedup_hash=uuid4().hex + uuid4().hex,
        source_documents=source_documents if source_documents is not None else [],
    )
    db.add(position)
    await db.flush()
    return position


async def _make_journal_entry(db: AsyncSession, user_id) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date(2026, 3, 1),
        memo=f"Anchor entry {uuid4()}",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()
    return entry


async def _make_rule(db: AsyncSession, user_id, *, default_account_id=None) -> ClassificationRule:
    rule = ClassificationRule(
        user_id=user_id,
        version_number=1,
        effective_date=date(2026, 3, 1),
        is_active=True,
        rule_name=f"anchor-rule-{uuid4()}",
        rule_type=RuleType.KEYWORD_MATCH,
        rule_config={"keywords": ["anchor"]},
        default_account_id=default_account_id,
        created_by=user_id,
    )
    db.add(rule)
    await db.flush()
    return rule


async def test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC-reconciliation.txn.1: AC18.11.1: Trusted reconciliation anchors are normalized and tenant-scoped."""
    other_user = await _make_user(db, email_prefix="anchor-recon-other")
    atomic = await _make_atomic_transaction(db, test_user.id)
    entry = await _make_journal_entry(db, test_user.id)
    other_entry = await _make_journal_entry(db, other_user.id)
    missing_entry_id = uuid4()
    match = ReconciliationMatch(
        atomic_txn_id=atomic.id,
        journal_entry_ids=[str(entry.id), str(other_entry.id), str(missing_entry_id), "not-a-uuid"],
        match_score=100,
        score_breakdown={"anchor": 100.0},
        status=ReconciliationStatus.ACCEPTED,
    )
    db.add(match)
    await db.flush()
    match_id = match.id
    entry_id = entry.id
    other_entry_id = other_entry.id

    await sync_reconciliation_match_journal_entry_links(db, match)
    await db.commit()

    link = await db.get(ReconciliationMatchJournalEntry, (match_id, entry_id))
    assert link is not None
    assert await db.get(ReconciliationMatchJournalEntry, (match_id, other_entry_id)) is None
    assert await db.get(ReconciliationMatchJournalEntry, (match_id, missing_entry_id)) is None

    await _expect_integrity_error(
        db,
        ReconciliationMatchJournalEntry(match_id=match_id, journal_entry_id=uuid4()),
    )
    await _expect_integrity_error(
        db,
        ReconciliationMatchJournalEntry(match_id=match_id, journal_entry_id=other_entry_id),
    )


async def test_AC18_11_2_atomic_source_links_reject_missing_and_cross_user_documents(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.11.2: Trusted atomic source-document anchors are normalized and tenant-scoped."""
    other_user = await _make_user(db, email_prefix="anchor-doc-other")
    transaction = await _make_atomic_transaction(db, test_user.id)
    position = await _make_atomic_position(db, test_user.id)
    txn_document = await _make_document(db, test_user.id, document_type=DocumentType.BANK_STATEMENT)
    pos_document = await _make_document(db, test_user.id, document_type=DocumentType.BROKERAGE_STATEMENT)
    other_document = await _make_document(db, other_user.id, document_type=DocumentType.BANK_STATEMENT)
    transaction_id = transaction.id
    position_id = position.id
    txn_document_id = txn_document.id
    pos_document_id = pos_document.id
    other_document_id = other_document.id

    db.add_all(
        [
            AtomicTransactionSourceDocument(
                atomic_txn_id=transaction_id,
                uploaded_document_id=txn_document_id,
                doc_type=DocumentType.BANK_STATEMENT.value,
                ordinal=0,
            ),
            AtomicPositionSourceDocument(
                atomic_position_id=position_id,
                uploaded_document_id=pos_document_id,
                doc_type=DocumentType.BROKERAGE_STATEMENT.value,
                ordinal=0,
            ),
        ]
    )
    await db.commit()

    await _expect_integrity_error(
        db,
        AtomicTransactionSourceDocument(
            atomic_txn_id=transaction_id,
            uploaded_document_id=uuid4(),
            doc_type=DocumentType.BANK_STATEMENT.value,
            ordinal=1,
        ),
    )
    await _expect_integrity_error(
        db,
        AtomicPositionSourceDocument(
            atomic_position_id=position_id,
            uploaded_document_id=other_document_id,
            doc_type=DocumentType.BANK_STATEMENT.value,
            ordinal=1,
        ),
    )


async def test_AC18_11_3_evidence_edges_reject_cross_user_endpoints(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.11.3: Evidence Graph edges cannot connect nodes across tenants."""
    other_user = await _make_user(db, email_prefix="anchor-edge-other")
    source = EvidenceNode(
        user_id=test_user.id,
        node_kind="source_document",
        entity_type="uploaded_document",
        entity_id=uuid4(),
        properties={},
    )
    target = EvidenceNode(
        user_id=test_user.id,
        node_kind="atomic_fact",
        entity_type="atomic_transaction",
        entity_id=uuid4(),
        properties={},
    )
    other_target = EvidenceNode(
        user_id=other_user.id,
        node_kind="atomic_fact",
        entity_type="atomic_transaction",
        entity_id=uuid4(),
        properties={},
    )
    db.add_all([source, target, other_target])
    await db.flush()

    db.add(
        EvidenceEdge(
            user_id=test_user.id,
            from_node_id=source.id,
            to_node_id=target.id,
            relation="deduped_into",
            properties={},
        )
    )
    await db.commit()

    await _expect_integrity_error(
        db,
        EvidenceEdge(
            user_id=test_user.id,
            from_node_id=source.id,
            to_node_id=other_target.id,
            relation="deduped_into",
            properties={},
        ),
    )


async def test_AC18_11_3_evidence_edge_relationships_preserve_tenant_scope(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.11.3: ORM evidence edge relationships honor tenant-scoped composite FKs."""
    other_user = await _make_user(db, email_prefix="anchor-edge-relationship-other")
    source = EvidenceNode(
        user_id=test_user.id,
        node_kind="source_document",
        entity_type="uploaded_document",
        entity_id=uuid4(),
        properties={},
    )
    other_target = EvidenceNode(
        user_id=other_user.id,
        node_kind="atomic_fact",
        entity_type="atomic_transaction",
        entity_id=uuid4(),
        properties={},
    )
    db.add_all([source, other_target])
    await db.flush()

    edge = EvidenceEdge(
        user_id=test_user.id,
        from_node_id=source.id,
        to_node_id=other_target.id,
        relation="deduped_into",
        properties={},
    )
    await db.execute(text("SET LOCAL session_replication_role = replica"))
    try:
        db.add(edge)
        await db.flush()
    finally:
        await db.execute(text("SET LOCAL session_replication_role = DEFAULT"))

    edge_id = edge.id
    source_id = source.id
    db.expunge_all()

    reloaded = (
        await db.execute(
            select(EvidenceEdge)
            .options(selectinload(EvidenceEdge.from_node), selectinload(EvidenceEdge.to_node))
            .where(EvidenceEdge.id == edge_id)
        )
    ).scalar_one()

    assert reloaded.from_node is not None
    assert reloaded.from_node.id == source_id
    assert reloaded.to_node is None


async def test_AC18_11_4_account_references_reject_cross_user_accounts(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.11.4: Account-bearing facts reject cross-user account references."""
    test_user_id = test_user.id
    other_user = await _make_user(db, email_prefix="anchor-account-other")
    own_account = await _make_account(db, test_user_id)
    other_account = await _make_account(db, other_user.id)
    entry = await _make_journal_entry(db, test_user_id)
    atomic = await _make_atomic_transaction(db, test_user_id)
    rule = await _make_rule(db, test_user_id)
    own_account_id = own_account.id
    other_account_id = other_account.id
    entry_id = entry.id
    atomic_id = atomic.id
    rule_id = rule.id
    await db.commit()

    await _expect_integrity_error(
        db,
        JournalLine(
            journal_entry_id=entry_id,
            account_id=other_account_id,
            direction=Direction.DEBIT,
            amount=Decimal("10.00"),
            currency="SGD",
        ),
    )
    await _expect_integrity_error(
        db,
        StatementSummary(
            user_id=test_user_id,
            file_hash=uuid4().hex + uuid4().hex,
            institution="Anchor Bank",
            account_id=other_account_id,
            currency="SGD",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("110.00"),
            status=BankStatementStatus.APPROVED,
        ),
    )
    await _expect_integrity_error(
        db,
        TransactionClassification(
            atomic_txn_id=atomic_id,
            rule_version_id=rule_id,
            account_id=other_account_id,
            status=ClassificationStatus.APPLIED,
        ),
    )

    db.add(
        TransactionClassification(
            atomic_txn_id=atomic_id,
            rule_version_id=rule_id,
            account_id=own_account_id,
            status=ClassificationStatus.APPLIED,
        )
    )
    await db.commit()


async def test_AC18_11_5_unresolved_legacy_source_ids_remain_blockers(
    db: AsyncSession,
    test_user: User,
) -> None:
    """AC18.11.5: Unresolved legacy source UUIDs remain blockers, not trusted anchors."""
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=date(2026, 3, 1),
        memo="Unresolved source",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=uuid4(),
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    await db.flush()
    account = await _make_account(db, test_user.id)
    line = JournalLine(
        journal_entry_id=entry.id,
        account_id=account.id,
        direction=Direction.DEBIT,
        amount=Decimal("10.00"),
        currency="SGD",
    )
    db.add(line)
    await db.flush()

    result = await EvidenceGraphMaterializationService().materialize_for_entity(
        db,
        user_id=test_user.id,
        entity_type="journal_line",
        entity_id=line.id,
        node_kind="ledger_line",
    )

    assert "entity_missing" in {blocker.code for blocker in result.blockers}
    trusted_sources = (
        await db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.user_id == test_user.id)
            .where(EvidenceNode.node_kind == "source_document")
        )
    ).scalars()
    assert list(trusted_sources) == []


def test_AC18_11_6_migration_preflights_and_risk_contract_are_declared() -> None:
    """AC18.11.6: Migration declares compatibility preflights, backfills, and risk metadata."""
    migration_source = MIGRATION_PATH.read_text()
    risk_source = RISK_PATH.read_text()

    assert "reconciliation_match_journal_entries" in migration_source
    assert "atomic_transaction_source_documents" in migration_source
    assert "atomic_position_source_documents" in migration_source
    assert "fr_validate_evidence_edge_tenant_scope" in migration_source
    assert "fr_validate_journal_line_account_user" in migration_source
    assert "backfill resolvable legacy audit anchors" in migration_source
    assert "unresolved legacy audit anchors remain preserved" in migration_source
    assert "raw_entry.entry_id_text ~*" in migration_source
    assert "(source_item.value ->> 'doc_id') ~*" in migration_source
    assert "0034_audit_anchor_ri" in risk_source
    assert "Issue #846" in risk_source or 'issue: "#846"' in risk_source
