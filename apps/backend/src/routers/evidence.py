"""Evidence Graph navigation endpoints."""

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query

from src.deps import CurrentUserId, DbSession
from src.models.evidence import EvidenceEdge, EvidenceNode
from src.schemas.evidence import (
    EvidenceLineageBlocker,
    EvidenceLineageDirection,
    EvidenceLineageEdge,
    EvidenceLineageNode,
    EvidenceLineageResponse,
)
from src.services.evidence_lineage import DEFAULT_MAX_DEPTH, EvidenceLineageService, EvidenceTraversalStep

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/lineage", response_model=EvidenceLineageResponse)
async def get_evidence_lineage(
    db: DbSession,
    user_id: CurrentUserId,
    entity_type: str = Query(..., min_length=1, max_length=100),
    entity_id: UUID = Query(...),
    node_kind: str | None = Query(default=None, min_length=1, max_length=50),
    direction: EvidenceLineageDirection = Query(default="both"),
    max_depth: int = Query(default=DEFAULT_MAX_DEPTH, ge=0, le=DEFAULT_MAX_DEPTH),
) -> EvidenceLineageResponse:
    """Return bounded user-owned Evidence Graph lineage around one entity anchor."""
    lineage = EvidenceLineageService()
    anchor = await lineage.get_node_for_entity(
        db,
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        node_kind=node_kind,
    )
    if anchor is None:
        return EvidenceLineageResponse(
            anchor=None,
            nodes=[],
            edges=[],
            blockers=[
                EvidenceLineageBlocker(
                    code="graph_node_missing",
                    message="No owned Evidence Graph node exists for this entity identity.",
                )
            ],
            max_depth=max_depth,
        )

    upstream_steps: list[EvidenceTraversalStep] = []
    downstream_steps: list[EvidenceTraversalStep] = []
    if direction in {"upstream", "both"}:
        upstream_steps = await lineage.get_upstream(
            db,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            node_kind=node_kind,
            max_depth=max_depth,
        )
    if direction in {"downstream", "both"}:
        downstream_steps = await lineage.get_downstream(
            db,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            node_kind=node_kind,
            max_depth=max_depth,
        )

    nodes = _unique_nodes([anchor, *(step.node for step in upstream_steps), *(step.node for step in downstream_steps)])
    edges = [
        *(_edge_dto(step, direction="upstream") for step in upstream_steps),
        *(_edge_dto(step, direction="downstream") for step in downstream_steps),
    ]
    return EvidenceLineageResponse(
        anchor=_node_dto(anchor),
        nodes=[_node_dto(node) for node in nodes],
        edges=edges,
        blockers=[],
        max_depth=max_depth,
    )


def _node_dto(node: EvidenceNode) -> EvidenceLineageNode:
    return EvidenceLineageNode(
        id=node.id,
        node_kind=node.node_kind,
        entity_type=node.entity_type,
        entity_id=node.entity_id,
        properties=node.properties,
    )


def _edge_dto(step: EvidenceTraversalStep, *, direction: str) -> EvidenceLineageEdge:
    edge: EvidenceEdge = step.edge
    return EvidenceLineageEdge(
        id=edge.id,
        from_node_id=edge.from_node_id,
        to_node_id=edge.to_node_id,
        relation=edge.relation,
        direction=cast(Literal["upstream", "downstream"], direction),
        depth=step.depth,
        properties=edge.properties,
    )


def _unique_nodes(nodes: list[EvidenceNode]) -> list[EvidenceNode]:
    seen: set[UUID] = set()
    unique: list[EvidenceNode] = []
    for node in nodes:
        if node.id in seen:
            continue
        seen.add(node.id)
        unique.append(node)
    return unique
