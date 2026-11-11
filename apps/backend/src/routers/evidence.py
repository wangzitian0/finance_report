"""Evidence Graph navigation endpoints."""

from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from src.deps import CurrentUserId, DbSession
from src.extraction import (
    DEFAULT_MAX_DEPTH,
    EvidenceGraphMaterializationService,
    EvidenceLineageService,
    EvidenceNode,
    EvidenceTraversalStep,
)
from src.schemas.evidence import (
    EvidenceLineageBlocker,
    EvidenceLineageDirection,
    EvidenceLineageEdge,
    EvidenceLineageError,
    EvidenceLineageNode,
    EvidenceLineageResponse,
    EvidenceNodeProperties,
    build_edge_properties,
    build_node_properties,
)

router = APIRouter(prefix="/evidence", tags=["evidence"])

_LAZY_MATERIALIZATION_ENTITY_NODE_KINDS = {
    "journal_line": {"ledger_line"},
    "journal_entry": {"ledger_entry"},
    "uploaded_document": {"source_document"},
    "atomic_transaction": {"atomic_fact"},
    "opening_position": {"atomic_fact"},
}
_GENUINE_FAILURE_BLOCKER_CODES = {
    "materialization_write_cap_reached": 503,
    "cross_user_lineage_blocked": 409,
    "unsupported_provenance": 422,
    "opening_authority_unproven": 409,
}


def _materialization_failure_status(blockers: list[EvidenceLineageBlocker]) -> int | None:
    statuses = [_GENUINE_FAILURE_BLOCKER_CODES[b.code] for b in blockers if b.code in _GENUINE_FAILURE_BLOCKER_CODES]
    return max(statuses) if statuses else None


def _should_attempt_lazy_materialization(*, entity_type: str, node_kind: str | None, anchor: EvidenceNode | None) -> bool:
    if anchor is not None and entity_type not in {"opening_position", "journal_entry", "journal_line"}:
        return False
    expected = _LAZY_MATERIALIZATION_ENTITY_NODE_KINDS.get(entity_type)
    return expected is not None and (node_kind is None or node_kind in expected)


def _node_dto(node: EvidenceNode) -> EvidenceLineageNode:
    return EvidenceLineageNode(
        id=node.id,
        node_kind=node.node_kind,
        entity_type=node.entity_type,
        entity_id=node.entity_id,
        properties=cast(EvidenceNodeProperties, build_node_properties(node.node_kind, node.properties)),
    )


def _edge_dto(step: EvidenceTraversalStep, *, direction: str) -> EvidenceLineageEdge:
    e = step.edge
    return EvidenceLineageEdge(
        id=e.id,
        from_node_id=e.from_node_id,
        to_node_id=e.to_node_id,
        relation=e.relation,
        direction=cast(Literal["upstream", "downstream"], direction),
        depth=step.depth,
        properties=build_edge_properties(e.properties),
    )


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
        db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, node_kind=node_kind
    )
    mat_blockers: list[EvidenceLineageBlocker] = []
    if _should_attempt_lazy_materialization(entity_type=entity_type, node_kind=node_kind, anchor=anchor):
        mat = await EvidenceGraphMaterializationService().materialize_for_entity(
            db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, node_kind=node_kind
        )
        mat_blockers = [
            EvidenceLineageBlocker(code=b.code, message=b.message)
            for b in mat.blockers
            if anchor is None or b.code != "entity_missing"
        ]
        if mat.has_writes:
            await db.commit()
        failure_status = _materialization_failure_status(mat_blockers)
        if failure_status is not None:
            raise HTTPException(
                status_code=failure_status,
                detail=EvidenceLineageError(
                    message="Evidence Graph materialization could not complete for this entity.",
                    blockers=mat_blockers,
                ).model_dump(),
            )
        anchor = await lineage.get_node_for_entity(
            db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, node_kind=node_kind
        )

    if anchor is None:
        missing = EvidenceLineageBlocker(
            code="graph_node_missing",
            message="No owned Evidence Graph node exists for this entity identity.",
        )
        return EvidenceLineageResponse(
            anchor=None,
            nodes=[],
            edges=[],
            blockers=[missing, *(b for b in mat_blockers if b.code != "entity_missing")],
            max_depth=max_depth,
        )

    up_steps = (
        await lineage.get_upstream(
            db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, node_kind=node_kind, max_depth=max_depth
        )
        if direction in {"upstream", "both"}
        else []
    )
    down_steps = (
        await lineage.get_downstream(
            db, user_id=user_id, entity_type=entity_type, entity_id=entity_id, node_kind=node_kind, max_depth=max_depth
        )
        if direction in {"downstream", "both"}
        else []
    )
    nodes = list(
        {n.id: n for n in (anchor, *(s.node for s in up_steps), *(s.node for s in down_steps))}.values()
    )
    opening_blockers = await EvidenceGraphMaterializationService().validate_opening_nodes(db, user_id=user_id, nodes=nodes)
    if opening_blockers:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=EvidenceLineageError(
                message="Opening lineage no longer has current source authority.",
                blockers=[EvidenceLineageBlocker(code=b.code, message=b.message) for b in opening_blockers],
            ).model_dump(),
        )
    return EvidenceLineageResponse(
        anchor=_node_dto(anchor),
        nodes=[_node_dto(n) for n in nodes],
        edges=[*(_edge_dto(s, direction="upstream") for s in up_steps), *(_edge_dto(s, direction="downstream") for s in down_steps)],
        blockers=mat_blockers,
        max_depth=max_depth,
    )
