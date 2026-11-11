"""Schemas for Evidence Graph navigation."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler

EvidenceLineageDirection = Literal["upstream", "downstream", "both"]


class _EvidenceProperties(BaseModel):
    model_config = ConfigDict(extra="allow")

    @model_serializer(mode="wrap")
    def _omit_none_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return {k: v for k, v in handler(self).items() if v is not None}


class SourceDocumentProperties(_EvidenceProperties):
    document_type: str | None = None
    original_filename: str | None = None
    file_hash: str | None = None


class AtomicFactProperties(_EvidenceProperties):
    dedup_hash: str | None = None
    txn_date: str | None = None
    direction: str | None = None
    amount: str | None = None
    currency: str | None = None


class LedgerEntryProperties(_EvidenceProperties):
    source_type: str | None = None
    source_id: str | None = None
    status: str | None = None


class LedgerLineProperties(_EvidenceProperties):
    journal_entry_id: str | None = None
    account_id: str | None = None
    direction: str | None = None
    amount: str | None = None
    currency: str | None = None


class GenericNodeProperties(_EvidenceProperties):
    pass


NODE_PROPERTY_MODELS: dict[str, type[_EvidenceProperties]] = {
    "source_document": SourceDocumentProperties,
    "atomic_fact": AtomicFactProperties,
    "ledger_entry": LedgerEntryProperties,
    "ledger_line": LedgerLineProperties,
}

EvidenceNodeProperties = (
    SourceDocumentProperties
    | AtomicFactProperties
    | LedgerEntryProperties
    | LedgerLineProperties
    | GenericNodeProperties
)


def build_node_properties(node_kind: str, raw: dict[str, object]) -> _EvidenceProperties:
    return NODE_PROPERTY_MODELS.get(node_kind, GenericNodeProperties).model_validate(raw or {})


class MaterializationEdgeProperties(_EvidenceProperties):
    adapter: str | None = None
    dedup_hash: str | None = None


def build_edge_properties(raw: dict[str, object]) -> MaterializationEdgeProperties:
    return MaterializationEdgeProperties.model_validate(raw or {})


class EvidenceLineageNode(BaseModel):
    id: UUID
    node_kind: str
    entity_type: str
    entity_id: UUID
    properties: EvidenceNodeProperties


class EvidenceLineageEdge(BaseModel):
    id: UUID
    from_node_id: UUID
    to_node_id: UUID
    relation: str
    direction: Literal["upstream", "downstream"]
    depth: int
    properties: MaterializationEdgeProperties


class EvidenceLineageBlocker(BaseModel):
    code: str
    message: str


class EvidenceLineageResponse(BaseModel):
    anchor: EvidenceLineageNode | None
    nodes: list[EvidenceLineageNode]
    edges: list[EvidenceLineageEdge]
    blockers: list[EvidenceLineageBlocker]
    max_depth: int


class EvidenceLineageError(BaseModel):
    error: str = "evidence_materialization_failed"
    message: str
    blockers: list[EvidenceLineageBlocker]
