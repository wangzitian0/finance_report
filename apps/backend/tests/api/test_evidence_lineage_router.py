"""Evidence Graph navigation API tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
from src.models.account import Account, AccountType
from src.models.evidence import EvidenceEdge, EvidenceNode
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.models.statement import BankStatement, BankStatementStatus, BankStatementTransaction
from src.services.deduplication import DeduplicationService
from src.services.evidence_lineage import EvidenceLineageService


@pytest.mark.asyncio
async def test_AC18_9_1_AC18_9_2_lineage_api_resolves_owned_anchor_and_both_directions(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    """AC18.9.1 AC18.9.2: API resolves an owned anchor and returns bounded bidirectional DTOs."""
    service = EvidenceLineageService()
    source_id = uuid4()
    extracted_id = uuid4()
    atomic_id = uuid4()
    entry_id = uuid4()
    line_id = uuid4()
    report_line_id = uuid4()

    source = await service.upsert_node(
        db,
        user_id=test_user.id,
        node_kind="source_document",
        entity_type="uploaded_document",
        entity_id=source_id,
        properties={"original_filename": "may.csv"},
    )
    extracted = await service.upsert_node(
        db,
        user_id=test_user.id,
        node_kind="extracted_record",
        entity_type="bank_statement_transaction",
        entity_id=extracted_id,
    )
    atomic = await service.upsert_node(
        db,
        user_id=test_user.id,
        node_kind="atomic_fact",
        entity_type="atomic_transaction",
        entity_id=atomic_id,
    )
    entry = await service.upsert_node(
        db,
        user_id=test_user.id,
        node_kind="ledger_entry",
        entity_type="journal_entry",
        entity_id=entry_id,
    )
    line = await service.upsert_node(
        db,
        user_id=test_user.id,
        node_kind="ledger_line",
        entity_type="journal_line",
        entity_id=line_id,
    )
    report_line = await service.upsert_node(
        db,
        user_id=test_user.id,
        node_kind="report_line",
        entity_type="package_traceability_line",
        entity_id=report_line_id,
    )
    await service.upsert_edge(
        db, user_id=test_user.id, from_node_id=source.id, to_node_id=extracted.id, relation="parsed_into"
    )
    await service.upsert_edge(
        db, user_id=test_user.id, from_node_id=extracted.id, to_node_id=atomic.id, relation="deduped_into"
    )
    await service.upsert_edge(
        db, user_id=test_user.id, from_node_id=atomic.id, to_node_id=entry.id, relation="posted_as"
    )
    await service.upsert_edge(db, user_id=test_user.id, from_node_id=entry.id, to_node_id=line.id, relation="contains")
    await service.upsert_edge(
        db, user_id=test_user.id, from_node_id=line.id, to_node_id=report_line.id, relation="aggregated_into"
    )
    await db.commit()

    response = await client.get(
        "/evidence/lineage",
        params={
            "entity_type": "journal_line",
            "entity_id": str(line_id),
            "node_kind": "ledger_line",
            "direction": "both",
            "max_depth": "5",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["anchor"]["entity_type"] == "journal_line"
    assert payload["anchor"]["node_kind"] == "ledger_line"
    assert payload["max_depth"] == 5
    assert payload["blockers"] == []

    node_keys = {(node["node_kind"], node["entity_type"], node["entity_id"]) for node in payload["nodes"]}
    assert ("source_document", "uploaded_document", str(source_id)) in node_keys
    assert ("extracted_record", "bank_statement_transaction", str(extracted_id)) in node_keys
    assert ("atomic_fact", "atomic_transaction", str(atomic_id)) in node_keys
    assert ("ledger_entry", "journal_entry", str(entry_id)) in node_keys
    assert ("ledger_line", "journal_line", str(line_id)) in node_keys
    assert ("report_line", "package_traceability_line", str(report_line_id)) in node_keys

    edge_keys = {(edge["relation"], edge["direction"], edge["depth"]) for edge in payload["edges"]}
    assert ("parsed_into", "upstream", 4) in edge_keys
    assert ("deduped_into", "upstream", 3) in edge_keys
    assert ("posted_as", "upstream", 2) in edge_keys
    assert ("contains", "upstream", 1) in edge_keys
    assert ("aggregated_into", "downstream", 1) in edge_keys

    source_response = await client.get(
        "/evidence/lineage",
        params={
            "entity_type": "uploaded_document",
            "entity_id": str(source_id),
            "node_kind": "source_document",
            "direction": "downstream",
            "max_depth": "5",
        },
    )

    assert source_response.status_code == 200
    source_payload = source_response.json()
    source_downstream_nodes = {
        (node["node_kind"], node["entity_type"], node["entity_id"]) for node in source_payload["nodes"]
    }
    assert ("ledger_line", "journal_line", str(line_id)) in source_downstream_nodes
    assert ("report_line", "package_traceability_line", str(report_line_id)) in source_downstream_nodes
    assert ("aggregated_into", "downstream", 5) in {
        (edge["relation"], edge["direction"], edge["depth"]) for edge in source_payload["edges"]
    }


@pytest.mark.asyncio
async def test_AC18_9_3_lineage_api_returns_blocker_for_missing_or_cross_user_anchor(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    """AC18.9.3: Missing or cross-user graph identities return explicit blocker state."""
    service = EvidenceLineageService()
    other_user_id = uuid4()
    other_entity_id = uuid4()
    await service.upsert_node(
        db,
        user_id=other_user_id,
        node_kind="source_document",
        entity_type="uploaded_document",
        entity_id=other_entity_id,
    )
    await db.commit()

    response = await client.get(
        "/evidence/lineage",
        params={
            "entity_type": "uploaded_document",
            "entity_id": str(other_entity_id),
            "direction": "downstream",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["anchor"] is None
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert payload["blockers"] == [
        {
            "code": "graph_node_missing",
            "message": "No owned Evidence Graph node exists for this entity identity.",
        }
    ]


@pytest.mark.asyncio
async def test_AC18_10_3_AC18_10_4_lineage_api_lazily_materializes_historical_journal_line(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    """AC18.10.3 AC18.10.4: Lineage reads repair a missing historical graph path once and idempotently."""
    bank = Account(user_id=test_user.id, name="Lazy API Bank", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Lazy API Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, income])
    await db.flush()

    statement = BankStatement(
        user_id=test_user.id,
        account_id=bank.id,
        file_path="s3://lazy/api.csv",
        file_hash=f"lazy-api-{uuid4().hex}",
        original_filename="lazy-api.csv",
        institution="Lazy API Bank",
        currency="SGD",
        status=BankStatementStatus.APPROVED,
    )
    txn = BankStatementTransaction(
        statement=statement,
        txn_date=date(2026, 5, 2),
        description="Lazy API income",
        amount=Decimal("77.00"),
        direction="IN",
        currency="SGD",
        reference="API-1",
    )
    db.add_all([statement, txn])
    await db.flush()

    atomic = AtomicTransaction(
        user_id=test_user.id,
        txn_date=txn.txn_date,
        amount=txn.amount,
        direction=TransactionDirection.IN,
        description=txn.description,
        reference=txn.reference,
        currency="SGD",
        dedup_hash=DeduplicationService.calculate_transaction_hash(
            test_user.id,
            txn.txn_date,
            txn.amount,
            TransactionDirection.IN,
            txn.description,
            txn.reference,
        ),
        source_documents=[],
    )
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=txn.txn_date,
        memo="Lazy API posted income",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=txn.id,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([atomic, entry])
    await db.flush()
    line = JournalLine(
        journal_entry_id=entry.id,
        account_id=income.id,
        direction=Direction.CREDIT,
        amount=txn.amount,
        currency="SGD",
    )
    db.add(line)
    await db.commit()

    first = await client.get(
        "/evidence/lineage",
        params={
            "entity_type": "journal_line",
            "entity_id": str(line.id),
            "node_kind": "ledger_line",
            "direction": "upstream",
            "max_depth": "5",
        },
    )

    assert first.status_code == 200
    payload = first.json()
    assert payload["blockers"] == []
    node_keys = {(node["node_kind"], node["entity_type"], node["entity_id"]) for node in payload["nodes"]}
    assert ("source_document", "bank_statement", str(statement.id)) in node_keys
    assert ("extracted_record", "bank_statement_transaction", str(txn.id)) in node_keys
    assert ("atomic_fact", "atomic_transaction", str(atomic.id)) in node_keys
    assert ("ledger_entry", "journal_entry", str(entry.id)) in node_keys
    assert ("ledger_line", "journal_line", str(line.id)) in node_keys
    assert {edge["relation"] for edge in payload["edges"]} >= {"parsed_into", "posted_as", "contains"}
    db_edges = {
        (edge.from_node_id, edge.to_node_id, edge.relation)
        for edge in (await db.execute(select(EvidenceEdge).where(EvidenceEdge.user_id == test_user.id))).scalars()
    }
    nodes_by_key = {
        (node.node_kind, node.entity_type, node.entity_id): node
        for node in (await db.execute(select(EvidenceNode).where(EvidenceNode.user_id == test_user.id))).scalars()
    }
    source_node = nodes_by_key[("source_document", "bank_statement", statement.id)]
    extracted_node = nodes_by_key[("extracted_record", "bank_statement_transaction", txn.id)]
    atomic_node = nodes_by_key[("atomic_fact", "atomic_transaction", atomic.id)]
    ledger_entry_node = nodes_by_key[("ledger_entry", "journal_entry", entry.id)]
    ledger_line_node = nodes_by_key[("ledger_line", "journal_line", line.id)]
    assert (source_node.id, extracted_node.id, "parsed_into") in db_edges
    assert (extracted_node.id, atomic_node.id, "deduped_into") in db_edges
    assert (extracted_node.id, ledger_entry_node.id, "posted_as") in db_edges
    assert (atomic_node.id, ledger_entry_node.id, "posted_as") in db_edges
    assert (ledger_entry_node.id, ledger_line_node.id, "contains") in db_edges

    counts_after_first = (
        (await db.execute(select(func.count(EvidenceNode.id)))).scalar_one(),
        (await db.execute(select(func.count(EvidenceEdge.id)))).scalar_one(),
    )
    second = await client.get(
        "/evidence/lineage",
        params={
            "entity_type": "journal_line",
            "entity_id": str(line.id),
            "node_kind": "ledger_line",
            "direction": "upstream",
            "max_depth": "5",
        },
    )
    counts_after_second = (
        (await db.execute(select(func.count(EvidenceNode.id)))).scalar_one(),
        (await db.execute(select(func.count(EvidenceEdge.id)))).scalar_one(),
    )

    assert second.status_code == 200
    assert counts_after_second == counts_after_first
