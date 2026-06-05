"""Evidence graph foundation service."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.evidence import EvidenceEdge, EvidenceNode

DEFAULT_MAX_DEPTH = 6


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
        """Create or update a node keyed by user, node kind, and entity identity."""
        result = await db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.user_id == user_id)
            .where(EvidenceNode.node_kind == node_kind)
            .where(EvidenceNode.entity_type == entity_type)
            .where(EvidenceNode.entity_id == entity_id)
            .limit(1)
        )
        node = result.scalar_one_or_none()
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
        """Resolve one user-owned evidence node for an entity identity."""
        query = (
            select(EvidenceNode)
            .where(EvidenceNode.user_id == user_id)
            .where(EvidenceNode.entity_type == entity_type)
            .where(EvidenceNode.entity_id == entity_id)
        )
        if node_kind is not None:
            query = query.where(EvidenceNode.node_kind == node_kind)

        result = await db.execute(query.order_by(EvidenceNode.created_at.asc(), EvidenceNode.id.asc()).limit(1))
        return result.scalar_one_or_none()

    async def upsert_edge(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        from_node_id: UUID,
        to_node_id: UUID,
        relation: str,
        properties: dict | None = None,
    ) -> EvidenceEdge:
        """Create or update a user-scoped edge between two nodes."""
        from_node = await self._get_node_by_id(db, node_id=from_node_id)
        to_node = await self._get_node_by_id(db, node_id=to_node_id)
        if from_node is None or to_node is None:
            raise ValueError("from_node_id and to_node_id must reference existing evidence nodes")
        if from_node.user_id != user_id or to_node.user_id != user_id:
            raise ValueError("evidence edge endpoints must belong to the same user")

        result = await db.execute(
            select(EvidenceEdge)
            .where(EvidenceEdge.user_id == user_id)
            .where(EvidenceEdge.from_node_id == from_node_id)
            .where(EvidenceEdge.to_node_id == to_node_id)
            .where(EvidenceEdge.relation == relation)
            .limit(1)
        )
        edge = result.scalar_one_or_none()
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
        """Traverse user-scoped evidence edges from an entity toward derived states."""
        start = await self.get_node_for_entity(
            db,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            node_kind=node_kind,
        )
        if start is None:
            return []
        return await self._traverse(
            db, user_id=user_id, start_node_id=start.id, direction="downstream", max_depth=max_depth
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
        """Traverse user-scoped evidence edges from an entity back to source states."""
        start = await self.get_node_for_entity(
            db,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            node_kind=node_kind,
        )
        if start is None:
            return []
        return await self._traverse(
            db, user_id=user_id, start_node_id=start.id, direction="upstream", max_depth=max_depth
        )

    async def _get_node_by_id(self, db: AsyncSession, *, node_id: UUID) -> EvidenceNode | None:
        result = await db.execute(select(EvidenceNode).where(EvidenceNode.id == node_id).limit(1))
        return result.scalar_one_or_none()

    async def _traverse(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        start_node_id: UUID,
        direction: str,
        max_depth: int | None,
    ) -> list[EvidenceTraversalStep]:
        depth_limit = self._depth_limit(max_depth)
        if depth_limit == 0:
            return []

        steps: list[EvidenceTraversalStep] = []
        frontier = {start_node_id}
        visited = {start_node_id}

        for depth in range(1, depth_limit + 1):
            if not frontier:
                break

            if direction == "downstream":
                edge_query = (
                    select(EvidenceEdge)
                    .where(EvidenceEdge.user_id == user_id)
                    .where(EvidenceEdge.from_node_id.in_(frontier))
                    .order_by(EvidenceEdge.created_at.asc(), EvidenceEdge.id.asc())
                )
                next_node_attr = "to_node_id"
            else:
                edge_query = (
                    select(EvidenceEdge)
                    .where(EvidenceEdge.user_id == user_id)
                    .where(EvidenceEdge.to_node_id.in_(frontier))
                    .order_by(EvidenceEdge.created_at.asc(), EvidenceEdge.id.asc())
                )
                next_node_attr = "from_node_id"

            edges = list((await db.execute(edge_query)).scalars().all())
            next_node_ids = {getattr(edge, next_node_attr) for edge in edges}
            nodes = await self._get_nodes_for_user(db, user_id=user_id, node_ids=next_node_ids - visited)
            node_by_id = {node.id: node for node in nodes}

            frontier = set()
            for edge in edges:
                next_node_id = getattr(edge, next_node_attr)
                node = node_by_id.get(next_node_id)
                if node is None:
                    continue
                steps.append(EvidenceTraversalStep(depth=depth, edge=edge, node=node))
                frontier.add(next_node_id)
                visited.add(next_node_id)

        return steps

    async def _get_nodes_for_user(
        self,
        db: AsyncSession,
        *,
        user_id: UUID,
        node_ids: set[UUID],
    ) -> list[EvidenceNode]:
        if not node_ids:
            return []
        result = await db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.user_id == user_id)
            .where(EvidenceNode.id.in_(node_ids))
            .order_by(EvidenceNode.created_at.asc(), EvidenceNode.id.asc())
        )
        return list(result.scalars().all())

    @staticmethod
    def _depth_limit(max_depth: int | None) -> int:
        if max_depth is None:
            return DEFAULT_MAX_DEPTH
        if max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if max_depth > DEFAULT_MAX_DEPTH:
            raise ValueError("max_depth exceeds default evidence traversal bound")
        return max_depth
