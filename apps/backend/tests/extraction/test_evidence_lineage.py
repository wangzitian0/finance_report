from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.extension.evidence_lineage import DEFAULT_MAX_DEPTH, EvidenceLineageService
from tests.factories import UserFactory


async def test_AC18_7_lineage_upsert_traversal_depth_and_tenant_isolation(db: AsyncSession, test_user):
    service, uid, sid, rid = EvidenceLineageService(), test_user.id, uuid4(), uuid4()
    src = await service.upsert_node(
        db,
        user_id=uid,
        node_kind="source_document",
        entity_type="bank_statement",
        entity_id=sid,
        properties={"label": "May statement"},
    )
    src_again = await service.upsert_node(
        db,
        user_id=uid,
        node_kind="source_document",
        entity_type="bank_statement",
        entity_id=sid,
        properties={"label": "May statement updated"},
    )
    rec = await service.upsert_node(
        db, user_id=uid, node_kind="extracted_record", entity_type="bank_statement_transaction", entity_id=rid
    )
    edge = await service.upsert_edge(
        db,
        user_id=uid,
        from_node_id=src.id,
        to_node_id=rec.id,
        relation="parsed_into",
        properties={"parser": "fixture"},
    )
    edge_again = await service.upsert_edge(
        db,
        user_id=uid,
        from_node_id=src.id,
        to_node_id=rec.id,
        relation="parsed_into",
        properties={"parser": "fixture-v2"},
    )
    assert (src_again.id, src_again.properties, edge_again.id, edge_again.properties) == (
        src.id,
        {"label": "May statement updated"},
        edge.id,
        {"parser": "fixture-v2"},
    )

    aid = uuid4()
    atm = await service.upsert_node(
        db, user_id=uid, node_kind="atomic_fact", entity_type="atomic_transaction", entity_id=aid
    )
    await service.upsert_edge(db, user_id=uid, from_node_id=rec.id, to_node_id=atm.id, relation="deduped_into")
    downstream = await service.get_downstream(db, user_id=uid, entity_type="bank_statement", entity_id=sid)
    upstream = await service.get_upstream(db, user_id=uid, entity_type="atomic_transaction", entity_id=aid)
    one_hop = await service.get_downstream(db, user_id=uid, entity_type="bank_statement", entity_id=sid, max_depth=1)
    assert (
        DEFAULT_MAX_DEPTH,
        [(s.depth, s.edge.relation, s.node.entity_type) for s in downstream],
        [(s.depth, s.edge.relation, s.node.entity_type) for s in upstream],
        [(s.depth, s.node.entity_type) for s in one_hop],
    ) == (
        6,
        [(1, "parsed_into", "bank_statement_transaction"), (2, "deduped_into", "atomic_transaction")],
        [(1, "deduped_into", "bank_statement_transaction"), (2, "parsed_into", "bank_statement")],
        [(1, "bank_statement_transaction")],
    )

    user_b = (await UserFactory.create_async(db)).id
    src_b = await service.upsert_node(
        db, user_id=user_b, node_kind="source_document", entity_type="bank_statement", entity_id=sid
    )
    with pytest.raises(ValueError, match="same user"):
        await service.upsert_edge(db, user_id=uid, from_node_id=src_b.id, to_node_id=rec.id, relation="parsed_into")
    assert (
        src.id != src_b.id
        and await service.get_downstream(db, user_id=user_b, entity_type="bank_statement", entity_id=sid) == []
    )
