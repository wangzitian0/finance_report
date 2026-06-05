"""Evidence Graph lazy materialization and consistency detector tests."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from src.models.account import Account, AccountType
from src.models.evidence import EvidenceEdge, EvidenceNode
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement import BankStatement, BankStatementStatus, BankStatementTransaction
from src.services.deduplication import DeduplicationService
from src.services.evidence_graph_integration import EvidenceGraphIntegrationService
from src.services.evidence_graph_materialization import EvidenceGraphMaterializationService


async def _create_historical_statement_entry(
    db: AsyncSession,
    *,
    user_id,
) -> tuple[BankStatement, BankStatementTransaction, AtomicTransaction, JournalEntry, JournalLine]:
    bank = Account(user_id=user_id, name=f"Lazy Bank {uuid4()}", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=user_id, name=f"Lazy Income {uuid4()}", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, income])
    await db.flush()

    statement = BankStatement(
        user_id=user_id,
        account_id=bank.id,
        file_path="s3://lazy/history.csv",
        file_hash=f"lazy-{uuid4().hex}",
        original_filename="history.csv",
        institution="Lazy Bank",
        currency="SGD",
        status=BankStatementStatus.APPROVED,
    )
    txn = BankStatementTransaction(
        statement=statement,
        txn_date=date(2026, 5, 1),
        description="Historical income",
        amount=Decimal("42.00"),
        direction="IN",
        currency="SGD",
        reference="LZ-1",
    )
    db.add_all([statement, txn])
    await db.flush()

    dedup_hash = DeduplicationService.calculate_transaction_hash(
        user_id,
        txn.txn_date,
        txn.amount,
        TransactionDirection.IN,
        txn.description,
        txn.reference,
    )
    atomic = AtomicTransaction(
        user_id=user_id,
        txn_date=txn.txn_date,
        amount=txn.amount,
        direction=TransactionDirection.IN,
        description=txn.description,
        reference=txn.reference,
        currency="SGD",
        dedup_hash=dedup_hash,
        source_documents=[],
    )
    entry = JournalEntry(
        user_id=user_id,
        entry_date=txn.txn_date,
        memo="Historical posted income",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=txn.id,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([atomic, entry])
    await db.flush()
    debit = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank.id,
        direction=Direction.DEBIT,
        amount=txn.amount,
        currency="SGD",
    )
    credit = JournalLine(
        journal_entry_id=entry.id,
        account_id=income.id,
        direction=Direction.CREDIT,
        amount=txn.amount,
        currency="SGD",
    )
    db.add_all([debit, credit])
    await db.flush()
    await db.refresh(entry, ["lines"])
    return statement, txn, atomic, entry, credit


async def _graph_counts(db: AsyncSession) -> tuple[int, int]:
    node_count = (await db.execute(select(func.count(EvidenceNode.id)))).scalar_one()
    edge_count = (await db.execute(select(func.count(EvidenceEdge.id)))).scalar_one()
    return node_count, edge_count


@pytest.mark.asyncio
async def test_AC18_10_2_graph_writes_share_the_business_transaction(
    db: AsyncSession,
    test_user: User,
):
    """AC18.10.2: Graph materialization participates in the same DB transaction as business facts."""
    _, txn, _, entry, _ = await _create_historical_statement_entry(db, user_id=test_user.id)

    await EvidenceGraphIntegrationService().record_journal_posting(
        db,
        user_id=test_user.id,
        source_transaction=txn,
        journal_entry=entry,
    )
    assert (await db.execute(select(func.count(EvidenceNode.id)))).scalar_one() > 0

    await db.rollback()

    assert (await db.execute(select(func.count(EvidenceNode.id)))).scalar_one() == 0
    assert (await db.execute(select(func.count(EvidenceEdge.id)))).scalar_one() == 0


@pytest.mark.asyncio
async def test_AC18_10_4_AC18_10_6_lazy_materialization_is_idempotent_and_preserves_accounting_facts(
    db: AsyncSession,
    test_user: User,
):
    """AC18.10.4 AC18.10.6: Lazy repair is deterministic, idempotent, and does not mutate ledger facts."""
    statement, txn, atomic, entry, line = await _create_historical_statement_entry(db, user_id=test_user.id)
    original_source_type = entry.source_type
    original_source_id = entry.source_id
    original_amount = line.amount
    service = EvidenceGraphMaterializationService()

    first = await service.materialize_for_entity(
        db,
        user_id=test_user.id,
        entity_type="journal_line",
        entity_id=line.id,
        node_kind="ledger_line",
    )
    first_counts = await _graph_counts(db)
    second = await service.materialize_for_entity(
        db,
        user_id=test_user.id,
        entity_type="journal_line",
        entity_id=line.id,
        node_kind="ledger_line",
    )
    second_counts = await _graph_counts(db)

    assert first.blockers == []
    assert second.blockers == []
    assert first.created_nodes > 0
    assert first.created_edges > 0
    assert second.created_nodes == 0
    assert second.created_edges == 0
    assert second_counts == first_counts
    assert entry.source_type == original_source_type
    assert entry.source_id == original_source_id
    assert line.amount == original_amount

    node_keys = {
        (node.node_kind, node.entity_type, node.entity_id)
        for node in (await db.execute(select(EvidenceNode))).scalars().all()
    }
    assert ("source_document", "bank_statement", statement.id) in node_keys
    assert ("extracted_record", "bank_statement_transaction", txn.id) in node_keys
    assert ("atomic_fact", "atomic_transaction", atomic.id) in node_keys
    assert ("ledger_entry", "journal_entry", entry.id) in node_keys
    assert ("ledger_line", "journal_line", line.id) in node_keys


@pytest.mark.asyncio
async def test_AC18_10_5_detector_reports_missing_orphan_and_cross_user_drift(
    db: AsyncSession,
    test_user: User,
):
    """AC18.10.1 AC18.10.5: Detector uses explicit blocker taxonomy for graph drift without writes."""
    _, _, _, _, line = await _create_historical_statement_entry(db, user_id=test_user.id)
    service = EvidenceGraphMaterializationService()
    orphan = EvidenceNode(
        user_id=test_user.id,
        node_kind="ledger_line",
        entity_type="journal_line",
        entity_id=uuid4(),
        properties={},
    )
    other_user_id = uuid4()
    source = EvidenceNode(
        user_id=test_user.id,
        node_kind="source_document",
        entity_type="bank_statement",
        entity_id=uuid4(),
        properties={},
    )
    target = EvidenceNode(
        user_id=other_user_id,
        node_kind="extracted_record",
        entity_type="bank_statement_transaction",
        entity_id=uuid4(),
        properties={},
    )
    db.add_all([orphan, source, target])
    await db.flush()
    db.add(
        EvidenceEdge(
            user_id=test_user.id,
            from_node_id=source.id,
            to_node_id=target.id,
            relation="parsed_into",
            properties={},
        )
    )
    await db.flush()
    before = await _graph_counts(db)

    report = await service.detect_consistency_drift(db, user_id=test_user.id)

    assert await _graph_counts(db) == before
    finding_keys = {(finding.code, finding.entity_type, finding.entity_id) for finding in report.findings}
    assert ("graph_node_missing", "journal_line", line.id) in finding_keys
    assert ("orphan_graph_node", "journal_line", orphan.entity_id) in finding_keys
    assert any(finding.code == "cross_user_lineage_blocked" for finding in report.findings)


@pytest.mark.asyncio
async def test_AC18_10_7_materialization_caps_and_unknown_sources_return_blockers(
    db: AsyncSession,
    test_user: User,
):
    """AC18.10.7: Tests cover write caps and unknown provenance blockers."""
    _, _, _, entry, line = await _create_historical_statement_entry(db, user_id=test_user.id)
    service = EvidenceGraphMaterializationService()

    capped = await service.materialize_for_entity(
        db,
        user_id=test_user.id,
        entity_type="journal_line",
        entity_id=line.id,
        node_kind="ledger_line",
        max_writes=0,
    )

    assert [blocker.code for blocker in capped.blockers] == ["materialization_write_cap_reached"]
    assert await _graph_counts(db) == (0, 0)

    entry.source_id = uuid4()
    await db.flush()
    unknown = await service.materialize_for_entity(
        db,
        user_id=test_user.id,
        entity_type="journal_line",
        entity_id=line.id,
        node_kind="ledger_line",
    )

    assert "entity_missing" in {blocker.code for blocker in unknown.blockers}
