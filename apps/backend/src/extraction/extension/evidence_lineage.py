"""Evidence graph foundation service and shared node/edge builders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode

DEFAULT_MAX_DEPTH = 6


def doc_node_props(doc: Any, *, doc_type_value: str | None = None) -> dict[str, Any]:
    return {
        "document_type": doc_type_value if doc_type_value is not None else doc.document_type.value,
        "original_filename": doc.original_filename,
        "file_hash": doc.file_hash,
    }


def txn_node_props(txn: Any) -> dict[str, Any]:
    return {
        "dedup_hash": txn.dedup_hash,
        "txn_date": txn.txn_date.isoformat(),
        "direction": txn.direction.value,
        "amount": str(txn.amount),
        "currency": txn.currency,
    }


def entry_node_props(entry: Any) -> dict[str, Any]:
    return {
        "source_type": entry.source_type.value,
        "source_id": str(entry.source_id) if entry.source_id else None,
        "status": entry.status.value,
    }


def line_node_props(line: Any) -> dict[str, Any]:
    return {
        "journal_entry_id": str(line.journal_entry_id),
        "account_id": str(line.account_id),
        "direction": line.direction.value,
        "amount": str(line.amount),
        "currency": line.currency,
    }


async def upsert_nodes_batch(
    db: AsyncSession,
    *,
    user_id: UUID,
    specs: Sequence[tuple[str, str, UUID, dict[str, Any]]],
) -> dict[tuple[str, str, UUID], EvidenceNode]:
    if not specs:
        return {}
    entity_ids = [s[2] for s in specs]
    existing = (
        await db.execute(
            select(EvidenceNode).where(EvidenceNode.user_id == user_id, EvidenceNode.entity_id.in_(entity_ids))
        )
    ).scalars().all()
    by_key = {(n.node_kind, n.entity_type, n.entity_id): n for n in existing}
    created = False
    for kind, etype, eid, props in specs:
        key = (kind, etype, eid)
        node = by_key.get(key)
        if node is None:
            node = EvidenceNode(user_id=user_id, node_kind=kind, entity_type=etype, entity_id=eid, properties=props)
            db.add(node)
            by_key[key] = node
            created = True
        elif props is not None:
            node.properties = props
    if created:
        await db.flush()
    return by_key


async def upsert_edges_batch(
    db: AsyncSession,
    *,
    user_id: UUID,
    specs: Sequence[tuple[EvidenceNode, EvidenceNode, str, dict[str, Any]]],
) -> None:
    if not specs:
        return
    from_ids = {s[0].id for s in specs}
    to_ids = {s[1].id for s in specs}
    existing = (
        await db.execute(
            select(EvidenceEdge).where(
                EvidenceEdge.user_id == user_id,
                EvidenceEdge.from_node_id.in_(from_ids),
                EvidenceEdge.to_node_id.in_(to_ids),
            )
        )
    ).scalars().all()
    by_key = {(e.from_node_id, e.to_node_id, e.relation): e for e in existing}
    created = False
    for from_node, to_node, relation, props in specs:
        key = (from_node.id, to_node.id, relation)
        edge = by_key.get(key)
        if edge is None:
            edge = EvidenceEdge(
                user_id=user_id, from_node_id=from_node.id, to_node_id=to_node.id, relation=relation, properties=props
            )
            db.add(edge)
            by_key[key] = edge
            created = True
        elif props is not None:
            edge.properties = props
    if created:
        await db.flush()


@dataclass(frozen=True)
class EvidenceTraversalStep:
    """Single hop returned by evidence graph traversal."""

    depth: int
    edge: EvidenceEdge
    node: EvidenceNode


class EvidenceLineageService:
    """User-scoped evidence graph node, edge, and traversal operations."""

    async def upsert_node(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        node_kind: str,
        entity_type: str,
        entity_id: UUID,
        properties: dict | None = None,
    ) -> EvidenceNode:
        node = (
            await db.execute(
                select(EvidenceNode)
                .where(
                    EvidenceNode.user_id == user_id,
                    EvidenceNode.node_kind == node_kind,
                    EvidenceNode.entity_type == entity_type,
                    EvidenceNode.entity_id == entity_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if node is None:
            node = EvidenceNode(
                user_id=user_id,
                node_kind=node_kind,
                entity_type=entity_type,
                entity_id=entity_id,
                properties=properties or {},
            )
            db.add(node)
        elif properties is not None:
            node.properties = properties
        await db.flush()
        return node

    async def get_node_for_entity(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        entity_type: str,
        entity_id: UUID,
        node_kind: str | None = None,
    ) -> EvidenceNode | None:
        query = select(EvidenceNode).where(
            EvidenceNode.user_id == user_id,
            EvidenceNode.entity_type == entity_type,
            EvidenceNode.entity_id == entity_id,
        )
        if node_kind is not None:
            query = query.where(EvidenceNode.node_kind == node_kind)
        return (
            await db.execute(query.order_by(EvidenceNode.created_at.asc(), EvidenceNode.id.asc()).limit(1))
        ).scalar_one_or_none()

    async def upsert_edge(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        from_node_id: UUID,
        to_node_id: UUID,
        relation: str,
        properties: dict | None = None,
        from_node: EvidenceNode | None = None,
        to_node: EvidenceNode | None = None,
    ) -> EvidenceEdge:
        from_node = from_node or await db.get(EvidenceNode, from_node_id)
        to_node = to_node or await db.get(EvidenceNode, to_node_id)
        if from_node is None or to_node is None:
            raise ValueError("from_node_id and to_node_id must reference existing evidence nodes")
        if from_node.user_id != user_id or to_node.user_id != user_id:
            raise ValueError("evidence edge endpoints must belong to the same user")

        edge = (
            await db.execute(
                select(EvidenceEdge)
                .where(
                    EvidenceEdge.user_id == user_id,
                    EvidenceEdge.from_node_id == from_node_id,
                    EvidenceEdge.to_node_id == to_node_id,
                    EvidenceEdge.relation == relation,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if edge is None:
            edge = EvidenceEdge(
                user_id=user_id,
                from_node_id=from_node_id,
                to_node_id=to_node_id,
                relation=relation,
                properties=properties or {},
            )
            db.add(edge)
        elif properties is not None:
            edge.properties = properties
        await db.flush()
        return edge

    async def get_downstream(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        entity_type: str,
        entity_id: UUID,
        node_kind: str | None = None,
        max_depth: int | None = DEFAULT_MAX_DEPTH,
    ) -> list[EvidenceTraversalStep]:
        return await self._traverse_from_entity(
            db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, node_kind=node_kind, max_depth=max_depth, downstream=True
        )

    async def get_upstream(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        entity_type: str,
        entity_id: UUID,
        node_kind: str | None = None,
        max_depth: int | None = DEFAULT_MAX_DEPTH,
    ) -> list[EvidenceTraversalStep]:
        return await self._traverse_from_entity(
            db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, node_kind=node_kind, max_depth=max_depth, downstream=False
        )

    async def _traverse_from_entity(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        entity_type: str,
        entity_id: UUID,
        node_kind: str | None,
        max_depth: int | None,
        downstream: bool,
    ) -> list[EvidenceTraversalStep]:
        start = await self.get_node_for_entity(
            db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, node_kind=node_kind
        )
        if start is None:
            return []
        depth_limit = self._depth_limit(max_depth)
        if depth_limit == 0:
            return []

        match_col = EvidenceEdge.from_node_id if downstream else EvidenceEdge.to_node_id
        next_attr = "to_node_id" if downstream else "from_node_id"
        steps: list[EvidenceTraversalStep] = []
        frontier = {start.id}
        visited = {start.id}

        for depth in range(1, depth_limit + 1):
            if not frontier:
                break
            edges = list(
                (
                    await db.execute(
                        select(EvidenceEdge)
                        .where(EvidenceEdge.user_id == user_id, match_col.in_(frontier))
                        .order_by(EvidenceEdge.created_at.asc(), EvidenceEdge.id.asc())
                    )
                ).scalars().all()
            )
            unvisited = {getattr(e, next_attr) for e in edges} - visited
            node_by_id = (
                {
                    n.id: n
                    for n in (
                        await db.execute(
                            select(EvidenceNode)
                            .where(EvidenceNode.user_id == user_id, EvidenceNode.id.in_(unvisited))
                            .order_by(EvidenceNode.created_at.asc(), EvidenceNode.id.asc())
                        )
                    ).scalars().all()
                }
                if unvisited
                else {}
            )
            frontier = set()
            for edge in edges:
                nid = getattr(edge, next_attr)
                node = node_by_id.get(nid)
                if node is not None:
                    steps.append(EvidenceTraversalStep(depth=depth, edge=edge, node=node))
                    frontier.add(nid)
                    visited.add(nid)
        return steps

    @staticmethod
    def _depth_limit(max_depth: int | None) -> int:
        if max_depth is None:
            return DEFAULT_MAX_DEPTH
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if max_depth > DEFAULT_MAX_DEPTH:
            raise ValueError("max_depth exceeds default evidence traversal bound")
        return max_depth
