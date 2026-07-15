"""Evidence Graph navigation endpoints."""

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from src.deps import CurrentUserId, DbSession
from src.extraction import (
    DEFAULT_MAX_DEPTH,
    EvidenceGraphMaterializationService,
    EvidenceLineageService,
    EvidenceTraversalStep,
)
from src.extraction.base.types.evidence import (
    EvidenceLineageBlocker,
    EvidenceLineageDirection,
    EvidenceLineageEdge,
    EvidenceLineageError,
    EvidenceLineageNode,
    EvidenceLineageResponse,
    build_edge_properties,
    build_node_properties,
)
from src.extraction.orm.evidence import EvidenceEdge, EvidenceNode

router = APIRouter(prefix="/evidence", tags=["evidence"])

_LAZY_MATERIALIZATION_ENTITY_TYPES = {
    "journal_line",
    "journal_entry",
    "uploaded_document",
    "atomic_transaction",
}
_LAZY_MATERIALIZATION_ENTITY_NODE_KINDS = {
    "journal_line": {"ledger_line"},
    "journal_entry": {"ledger_entry"},
    "uploaded_document": {"source_document"},
    "atomic_transaction": {"atomic_fact"},
}

# Blocker codes that mean materialization genuinely failed (as opposed to the
# anchor simply not existing yet, which is a legitimate empty/partial result).
# When any of these surface, the request must NOT return 200-with-blockers; it
# returns a non-2xx status with a structured EvidenceLineageError detail so
# clients can distinguish a real failure from an empty graph.
_GENUINE_FAILURE_BLOCKER_CODES = {
    "materialization_write_cap_reached": 503,
    "cross_user_lineage_blocked": 409,
    "unsupported_provenance": 422,
}


def _materialization_failure_status(blockers: list[EvidenceLineageBlocker]) -> int | None:
    """Return the HTTP status for the most severe genuine-failure blocker, if any.

    ``entity_missing`` and ``graph_node_missing`` are deliberately excluded: they
    represent an absent anchor, which is a valid empty result, not a failure.
    """
    statuses = [
        _GENUINE_FAILURE_BLOCKER_CODES[blocker.code]
        for blocker in blockers
        if blocker.code in _GENUINE_FAILURE_BLOCKER_CODES
    ]
    return max(statuses) if statuses else None


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
    materialization_blockers: list[EvidenceLineageBlocker] = []
    if _should_attempt_lazy_materialization(entity_type=entity_type, node_kind=node_kind, anchor=anchor):
        materialization = await EvidenceGraphMaterializationService().materialize_for_entity(
            db,
            user_id=user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            node_kind=node_kind,
        )
        materialization_blockers = [
            EvidenceLineageBlocker(code=blocker.code, message=blocker.message) for blocker in materialization.blockers
        ]
        if materialization.has_writes:
            await db.commit()
        failure_status = _materialization_failure_status(materialization_blockers)
        if failure_status is not None:
            raise HTTPException(
                status_code=failure_status,
                detail=EvidenceLineageError(
                    message="Evidence Graph materialization could not complete for this entity.",
                    blockers=materialization_blockers,
                ).model_dump(),
            )
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
            ]
            + _visible_missing_anchor_blockers(materialization_blockers),
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
        blockers=materialization_blockers,
        max_depth=max_depth,
    )


def _should_attempt_lazy_materialization(
    *,
    entity_type: str,
    node_kind: str | None,
    anchor: EvidenceNode | None,
) -> bool:
    if anchor is not None:
        return False
    expected_node_kinds = _LAZY_MATERIALIZATION_ENTITY_NODE_KINDS.get(entity_type)
    if expected_node_kinds is None:
        return False
    if node_kind is not None and node_kind not in expected_node_kinds:
        return False
    return True


def _visible_missing_anchor_blockers(
    materialization_blockers: list[EvidenceLineageBlocker],
) -> list[EvidenceLineageBlocker]:
    return [blocker for blocker in materialization_blockers if blocker.code != "entity_missing"]


def _node_dto(node: EvidenceNode) -> EvidenceLineageNode:
    return EvidenceLineageNode(
        id=node.id,
        node_kind=node.node_kind,
        entity_type=node.entity_type,
        entity_id=node.entity_id,
        properties=build_node_properties(node.node_kind, node.properties),
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
        properties=build_edge_properties(edge.properties),
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
