"""Evidence Graph navigation API tests."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction import DocumentStatus, DocumentType, UploadedDocument
from src.extraction.extension.deduplication import DeduplicationService
from src.extraction.extension.evidence_lineage import EvidenceLineageService
from src.identity import User
from src.models.account import Account, AccountType
from src.models.evidence import EvidenceEdge, EvidenceNode
from src.models.journal import Direction, JournalEntry, JournalEntrySourceType, JournalEntryStatus, JournalLine
from src.models.layer2 import AtomicTransaction, TransactionDirection
from src.routers.evidence import _materialization_failure_status, _should_attempt_lazy_materialization
from src.schemas.evidence import (
    EvidenceLineageBlocker,
    LedgerLineProperties,
    MaterializationEdgeProperties,
    build_edge_properties,
    build_node_properties,
)
from tests.factories import UserFactory


async def test_AC18_9_1_AC18_9_2_lineage_api_resolves_owned_anchor_and_both_directions(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    """AC-extraction.1809.1 AC-extraction.1809.2: AC18.9.1 AC18.9.2: API resolves an owned anchor and returns bounded bidirectional DTOs."""
    service = EvidenceLineageService()
    source_id = uuid4()
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
        db, user_id=test_user.id, from_node_id=source.id, to_node_id=atomic.id, relation="deduped_into"
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
    assert ("atomic_fact", "atomic_transaction", str(atomic_id)) in node_keys
    assert ("ledger_entry", "journal_entry", str(entry_id)) in node_keys
    assert ("ledger_line", "journal_line", str(line_id)) in node_keys
    assert ("report_line", "package_traceability_line", str(report_line_id)) in node_keys

    edge_keys = {(edge["relation"], edge["direction"], edge["depth"]) for edge in payload["edges"]}
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
    assert ("aggregated_into", "downstream", 4) in {
        (edge["relation"], edge["direction"], edge["depth"]) for edge in source_payload["edges"]
    }


async def test_AC18_9_3_lineage_api_returns_blocker_for_missing_or_cross_user_anchor(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    """AC-extraction.1809.3: AC18.9.3: Missing or cross-user graph identities return explicit blocker state."""
    service = EvidenceLineageService()
    other_user_id = (await UserFactory.create_async(db)).id
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


async def test_AC18_10_3_AC18_10_4_lineage_api_lazily_materializes_historical_journal_line(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    """AC-extraction.1810.3: AC18.10.3 AC18.10.4: Lineage reads repair a missing historical graph path once and idempotently."""
    bank = Account(user_id=test_user.id, name="Lazy API Bank", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=test_user.id, name="Lazy API Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, income])
    await db.flush()

    document = UploadedDocument(
        user_id=test_user.id,
        file_path="s3://lazy/api.csv",
        file_hash=f"lazy-api-{uuid4().hex}",
        original_filename="lazy-api.csv",
        document_type=DocumentType.BANK_STATEMENT,
        status=DocumentStatus.COMPLETED,
    )
    db.add(document)
    await db.flush()

    txn_date = date(2026, 5, 2)
    amount = Decimal("77.00")
    description = "Lazy API income"
    reference = "API-1"
    atomic_id = uuid4()
    atomic = AtomicTransaction(
        id=atomic_id,
        user_id=test_user.id,
        txn_date=txn_date,
        amount=amount,
        direction=TransactionDirection.IN,
        description=description,
        reference=reference,
        currency="SGD",
        dedup_hash=DeduplicationService.calculate_transaction_hash(
            test_user.id,
            txn_date,
            amount,
            TransactionDirection.IN,
            description,
            reference,
        ),
        source_documents=[{"doc_id": str(document.id), "doc_type": DocumentType.BANK_STATEMENT.value}],
    )
    entry = JournalEntry(
        user_id=test_user.id,
        entry_date=txn_date,
        memo="Lazy API posted income",
        source_type=JournalEntrySourceType.USER_CONFIRMED,
        source_id=atomic_id,
        status=JournalEntryStatus.POSTED,
    )
    db.add_all([atomic, entry])
    await db.flush()
    debit_line = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank.id,
        direction=Direction.DEBIT,
        amount=amount,
        currency="SGD",
    )
    line = JournalLine(
        journal_entry_id=entry.id,
        account_id=income.id,
        direction=Direction.CREDIT,
        amount=amount,
        currency="SGD",
    )
    db.add_all([debit_line, line])
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
    assert ("source_document", "uploaded_document", str(document.id)) in node_keys
    assert ("atomic_fact", "atomic_transaction", str(atomic.id)) in node_keys
    assert ("ledger_entry", "journal_entry", str(entry.id)) in node_keys
    assert ("ledger_line", "journal_line", str(line.id)) in node_keys
    assert {edge["relation"] for edge in payload["edges"]} >= {"deduped_into", "posted_as", "contains"}
    db_edges = {
        (edge.from_node_id, edge.to_node_id, edge.relation)
        for edge in (await db.execute(select(EvidenceEdge).where(EvidenceEdge.user_id == test_user.id))).scalars()
    }
    nodes_by_key = {
        (node.node_kind, node.entity_type, node.entity_id): node
        for node in (await db.execute(select(EvidenceNode).where(EvidenceNode.user_id == test_user.id))).scalars()
    }
    source_node = nodes_by_key[("source_document", "uploaded_document", document.id)]
    atomic_node = nodes_by_key[("atomic_fact", "atomic_transaction", atomic.id)]
    ledger_entry_node = nodes_by_key[("ledger_entry", "journal_entry", entry.id)]
    ledger_line_node = nodes_by_key[("ledger_line", "journal_line", line.id)]
    assert (source_node.id, atomic_node.id, "deduped_into") in db_edges
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


def test_AC18_10_7_lazy_materialization_requires_supported_entity_type_and_matching_node_kind() -> None:
    """AC18.10.7: Lazy materialization is keyed by entity identity, not a free-form node_kind fallback."""
    assert (
        _should_attempt_lazy_materialization(entity_type="journal_line", node_kind="ledger_line", anchor=None) is True
    )
    assert _should_attempt_lazy_materialization(entity_type="journal_line", node_kind=None, anchor=None) is True
    assert (
        _should_attempt_lazy_materialization(entity_type="future_table", node_kind="ledger_line", anchor=None) is False
    )
    assert (
        _should_attempt_lazy_materialization(entity_type="journal_line", node_kind="source_document", anchor=None)
        is False
    )


def test_AC18_31_1_node_properties_are_typed_and_round_trip() -> None:
    """AC-extraction.1831.1: AC18.31.1: ledger_line properties coerce into a typed model and preserve monetary string amounts."""
    raw = {
        "journal_entry_id": str(uuid4()),
        "account_id": str(uuid4()),
        "direction": "DEBIT",
        "amount": "123.45",
        "currency": "SGD",
    }
    typed = build_node_properties("ledger_line", raw)

    assert isinstance(typed, LedgerLineProperties)
    # Monetary amount stays a string (Decimal-as-string), never a float.
    assert typed.amount == "123.45"
    assert isinstance(typed.amount, str)
    # Round-trips back to the same JSON shape clients already consume.
    assert typed.model_dump() == raw


def test_AC18_31_1_node_properties_preserve_unknown_and_partial_keys() -> None:
    """AC18.31.1: typed properties stay backward-compatible with legacy/partial rows.

    Typing the properties must not change the legacy JSON shape: a partial row
    must serialize to EXACTLY the keys it had, with no new ``null`` keys for the
    declared-but-unset optional fields (e.g. no ``document_type: null``). Asserts
    exact equality with both ``model_dump()`` and ``model_dump(exclude_unset=True)``
    so a regression that re-adds default keys is caught.
    """
    legacy_row = {"original_filename": "may.csv", "legacy_key": "kept"}
    partial = build_node_properties("source_document", legacy_row)

    # Exact legacy shape: populated + preserved extra keys only, no null defaults.
    assert partial.model_dump() == legacy_row
    assert partial.model_dump(exclude_unset=True) == legacy_row
    # No declared-but-unset optional field leaks in as a null key.
    assert "document_type" not in partial.model_dump()
    assert "file_hash" not in partial.model_dump()
    # Unknown node kinds still coerce (generic fallback) instead of raising.
    assert build_node_properties("future_kind", {"anything": "ok"}).model_dump() == {"anything": "ok"}


def test_AC18_31_1_edge_properties_are_typed() -> None:
    """AC18.31.1: edge properties coerce into the materialization edge model."""
    typed = build_edge_properties({"adapter": "lazy_materialization", "dedup_hash": "abc"})

    assert isinstance(typed, MaterializationEdgeProperties)
    assert typed.adapter == "lazy_materialization"
    assert typed.dedup_hash == "abc"


def test_AC18_31_2_failure_status_distinguishes_genuine_failure_from_empty() -> None:
    """AC-extraction.1831.2: AC18.31.2: only genuine-failure blocker codes map to a non-2xx status."""
    # Absent-anchor states are valid empty results, not failures.
    assert _materialization_failure_status([]) is None
    assert _materialization_failure_status([EvidenceLineageBlocker(code="graph_node_missing", message="x")]) is None
    assert _materialization_failure_status([EvidenceLineageBlocker(code="entity_missing", message="x")]) is None
    # Genuine failures map to dedicated statuses.
    assert (
        _materialization_failure_status([EvidenceLineageBlocker(code="cross_user_lineage_blocked", message="x")]) == 409
    )
    assert _materialization_failure_status([EvidenceLineageBlocker(code="unsupported_provenance", message="x")]) == 422
    assert (
        _materialization_failure_status([EvidenceLineageBlocker(code="materialization_write_cap_reached", message="x")])
        == 503
    )
    # The most severe (highest) status wins when several genuine failures co-occur.
    assert (
        _materialization_failure_status(
            [
                EvidenceLineageBlocker(code="cross_user_lineage_blocked", message="x"),
                EvidenceLineageBlocker(code="materialization_write_cap_reached", message="y"),
            ]
        )
        == 503
    )


async def test_AC18_31_2_lineage_api_returns_non_200_on_materialization_failure(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    """AC18.31.2: a genuine materialization failure returns a non-200 status with structured detail.

    A journal line owned by another user can be resolved by the deterministic
    materializer but is blocked cross-user. This is a real failure, not an empty
    graph, so the endpoint must return 409 with an EvidenceLineageError body
    instead of 200-with-blockers.
    """
    other_user = await UserFactory.create_async(db)
    bank = Account(user_id=other_user.id, name="Other Bank", type=AccountType.ASSET, currency="SGD")
    income = Account(user_id=other_user.id, name="Other Income", type=AccountType.INCOME, currency="SGD")
    db.add_all([bank, income])
    await db.flush()
    entry = JournalEntry(
        user_id=other_user.id,
        entry_date=date(2026, 5, 3),
        memo="Cross-user entry",
        source_type=JournalEntrySourceType.MANUAL,
        status=JournalEntryStatus.POSTED,
    )
    db.add(entry)
    await db.flush()
    line = JournalLine(
        journal_entry_id=entry.id,
        account_id=bank.id,
        direction=Direction.DEBIT,
        amount=Decimal("10.00"),
        currency="SGD",
    )
    other_line = JournalLine(
        journal_entry_id=entry.id,
        account_id=income.id,
        direction=Direction.CREDIT,
        amount=Decimal("10.00"),
        currency="SGD",
    )
    db.add_all([line, other_line])
    await db.commit()

    response = await client.get(
        "/evidence/lineage",
        params={
            "entity_type": "journal_line",
            "entity_id": str(line.id),
            "node_kind": "ledger_line",
            "direction": "upstream",
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "evidence_materialization_failed"
    assert any(blocker["code"] == "cross_user_lineage_blocked" for blocker in detail["blockers"])


async def test_AC18_31_2_lineage_api_keeps_200_for_empty_graph(
    client: AsyncClient,
    db: AsyncSession,
    test_user: User,
):
    """AC18.31.2: an absent anchor stays a 200 empty/blocker result (backward-compatible)."""
    response = await client.get(
        "/evidence/lineage",
        params={
            "entity_type": "uploaded_document",
            "entity_id": str(uuid4()),
            "direction": "downstream",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["anchor"] is None
    assert payload["blockers"] == [
        {
            "code": "graph_node_missing",
            "message": "No owned Evidence Graph node exists for this entity identity.",
        }
    ]
