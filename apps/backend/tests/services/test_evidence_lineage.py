"""Evidence Graph foundation service tests."""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.services.evidence_lineage import DEFAULT_MAX_DEPTH, EvidenceLineageService
from tests.factories import UserFactory


async def test_AC18_7_4_node_and_edge_upserts_are_idempotent(db: AsyncSession, test_user):
    """AC18.7.4: Evidence lineage service supports idempotent node and edge upsert."""
    service = EvidenceLineageService()
    user_id = test_user.id
    source_entity_id = uuid4()
    record_entity_id = uuid4()

    source = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="source_document",
        entity_type="bank_statement",
        entity_id=source_entity_id,
        properties={"label": "May statement"},
    )
    source_again = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="source_document",
        entity_type="bank_statement",
        entity_id=source_entity_id,
        properties={"label": "May statement updated"},
    )
    record = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="extracted_record",
        entity_type="bank_statement_transaction",
        entity_id=record_entity_id,
    )

    edge = await service.upsert_edge(
        db,
        user_id=user_id,
        from_node_id=source.id,
        to_node_id=record.id,
        relation="parsed_into",
        properties={"parser": "fixture"},
    )
    edge_again = await service.upsert_edge(
        db,
        user_id=user_id,
        from_node_id=source.id,
        to_node_id=record.id,
        relation="parsed_into",
        properties={"parser": "fixture-v2"},
    )

    assert source_again.id == source.id
    assert source_again.properties == {"label": "May statement updated"}
    assert edge_again.id == edge.id
    assert edge_again.properties == {"parser": "fixture-v2"}


async def test_AC18_7_5_traversal_resolves_upstream_and_downstream_by_entity(db: AsyncSession, test_user):
    """AC18.7.5: Evidence lineage traverses upstream and downstream within user scope."""
    service = EvidenceLineageService()
    user_id = test_user.id
    source_entity_id = uuid4()
    extracted_entity_id = uuid4()
    atomic_entity_id = uuid4()

    source = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="source_document",
        entity_type="bank_statement",
        entity_id=source_entity_id,
    )
    extracted = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="extracted_record",
        entity_type="bank_statement_transaction",
        entity_id=extracted_entity_id,
    )
    atomic = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="atomic_fact",
        entity_type="atomic_transaction",
        entity_id=atomic_entity_id,
    )
    await service.upsert_edge(
        db, user_id=user_id, from_node_id=source.id, to_node_id=extracted.id, relation="parsed_into"
    )
    await service.upsert_edge(
        db,
        user_id=user_id,
        from_node_id=extracted.id,
        to_node_id=atomic.id,
        relation="deduped_into",
    )

    downstream = await service.get_downstream(
        db,
        user_id=user_id,
        entity_type="bank_statement",
        entity_id=source_entity_id,
    )
    upstream = await service.get_upstream(
        db,
        user_id=user_id,
        entity_type="atomic_transaction",
        entity_id=atomic_entity_id,
    )

    assert [(step.depth, step.edge.relation, step.node.entity_type) for step in downstream] == [
        (1, "parsed_into", "bank_statement_transaction"),
        (2, "deduped_into", "atomic_transaction"),
    ]
    assert [(step.depth, step.edge.relation, step.node.entity_type) for step in upstream] == [
        (1, "deduped_into", "bank_statement_transaction"),
        (2, "parsed_into", "bank_statement"),
    ]


async def test_AC18_7_6_traversal_enforces_depth_limit(db: AsyncSession, test_user):
    """AC18.7.6: Evidence lineage traversal never walks unbounded graphs."""
    service = EvidenceLineageService()
    user_id = test_user.id
    entity_ids = [uuid4(), uuid4(), uuid4()]
    first = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="source_document",
        entity_type="source",
        entity_id=entity_ids[0],
    )
    second = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="extracted_record",
        entity_type="middle",
        entity_id=entity_ids[1],
    )
    third = await service.upsert_node(
        db,
        user_id=user_id,
        node_kind="atomic_fact",
        entity_type="leaf",
        entity_id=entity_ids[2],
    )
    await service.upsert_edge(db, user_id=user_id, from_node_id=first.id, to_node_id=second.id, relation="parsed_into")
    await service.upsert_edge(db, user_id=user_id, from_node_id=second.id, to_node_id=third.id, relation="deduped_into")

    one_hop = await service.get_downstream(
        db,
        user_id=user_id,
        entity_type="source",
        entity_id=entity_ids[0],
        max_depth=1,
    )

    assert DEFAULT_MAX_DEPTH == 6
    assert [(step.depth, step.node.entity_type) for step in one_hop] == [(1, "middle")]


async def test_AC18_7_5_cross_user_edges_and_traversal_are_blocked(db: AsyncSession, test_user):
    """AC18.7.5 AC18.7.7: Evidence lineage enforces user-scoped graph isolation."""
    service = EvidenceLineageService()
    user_a = test_user.id
    user_b = (await UserFactory.create_async(db)).id
    shared_entity_id = uuid4()
    source_a = await service.upsert_node(
        db,
        user_id=user_a,
        node_kind="source_document",
        entity_type="bank_statement",
        entity_id=shared_entity_id,
    )
    source_b = await service.upsert_node(
        db,
        user_id=user_b,
        node_kind="source_document",
        entity_type="bank_statement",
        entity_id=shared_entity_id,
    )
    target_a = await service.upsert_node(
        db,
        user_id=user_a,
        node_kind="extracted_record",
        entity_type="bank_statement_transaction",
        entity_id=uuid4(),
    )

    with pytest.raises(ValueError, match="same user"):
        await service.upsert_edge(
            db,
            user_id=user_a,
            from_node_id=source_b.id,
            to_node_id=target_a.id,
            relation="parsed_into",
        )

    await service.upsert_edge(
        db,
        user_id=user_a,
        from_node_id=source_a.id,
        to_node_id=target_a.id,
        relation="parsed_into",
    )
    user_b_downstream = await service.get_downstream(
        db,
        user_id=user_b,
        entity_type="bank_statement",
        entity_id=shared_entity_id,
    )

    assert source_a.id != source_b.id
    assert user_b_downstream == []
