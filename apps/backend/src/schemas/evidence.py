"""Schemas for Evidence Graph navigation."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

EvidenceLineageDirection = Literal["upstream", "downstream", "both"]


class EvidenceLineageNode(BaseModel):
    id: UUID
    node_kind: str
    entity_type: str
    entity_id: UUID
    properties: dict[str, Any]


class EvidenceLineageEdge(BaseModel):
    id: UUID
    from_node_id: UUID
    to_node_id: UUID
    relation: str
    direction: Literal["upstream", "downstream"]
    depth: int
    properties: dict[str, Any]


class EvidenceLineageBlocker(BaseModel):
    code: str
    message: str


class EvidenceLineageResponse(BaseModel):
    anchor: EvidenceLineageNode | None
    nodes: list[EvidenceLineageNode]
    edges: list[EvidenceLineageEdge]
    blockers: list[EvidenceLineageBlocker]
    max_depth: int
