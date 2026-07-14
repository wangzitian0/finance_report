"""Schemas for Evidence Graph navigation.

Property payloads on graph nodes and edges are small, closed audit-metadata
records. Each ``node_kind`` and edge ``relation`` produced by deterministic
materialization carries a known, documented shape (see
``common/extraction/evidence-lineage.md``). The typed models below replace the previous
``dict[str, Any]`` so callers and the OpenAPI schema describe these shapes
explicitly. Monetary fields stay as strings (never ``float``) to preserve exact
``Decimal`` serialization.

The property models tolerate historical rows: every field is optional and
unknown keys are preserved (``extra="allow"``). This keeps reads of legacy or
partially-materialized rows backward-compatible while still documenting the
canonical fields.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer
from pydantic_core.core_schema import SerializerFunctionWrapHandler

EvidenceLineageDirection = Literal["upstream", "downstream", "both"]


class _EvidenceProperties(BaseModel):
    """Base for closed audit-metadata property records.

    Unknown keys are preserved so historical rows round-trip unchanged, and all
    declared fields are optional so partially-materialized rows stay valid.

    Backward-compat serialization: declared fields are all optional and default
    to ``None``, so a legacy/partial row that omits a field would otherwise emit
    an explicit ``null`` key (e.g. ``document_type: null``) once typed, changing
    the historical JSON shape. The serializer below drops ``None``-valued keys so
    absent fields stay absent, while populated fields and preserved extra keys
    (``extra="allow"``) still serialize. This holds for both direct
    ``model_dump()`` and FastAPI ``response_model`` serialization (which
    re-validates and would otherwise mark defaults as "set").
    """

    model_config = ConfigDict(extra="allow")

    @model_serializer(mode="wrap")
    def _omit_none_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        return {key: value for key, value in handler(self).items() if value is not None}


class SourceDocumentProperties(_EvidenceProperties):
    """Properties for ``source_document`` nodes (``uploaded_document``)."""

    document_type: str | None = None
    original_filename: str | None = None
    file_hash: str | None = None


class AtomicFactProperties(_EvidenceProperties):
    """Properties for ``atomic_fact`` nodes (``atomic_transaction``)."""

    dedup_hash: str | None = None
    txn_date: str | None = None
    direction: str | None = None
    # Monetary amount is a Decimal-as-string; never a float.
    amount: str | None = None
    currency: str | None = None


class LedgerEntryProperties(_EvidenceProperties):
    """Properties for ``ledger_entry`` nodes (``journal_entry``)."""

    source_type: str | None = None
    source_id: str | None = None
    status: str | None = None


class LedgerLineProperties(_EvidenceProperties):
    """Properties for ``ledger_line`` nodes (``journal_line``)."""

    journal_entry_id: str | None = None
    account_id: str | None = None
    direction: str | None = None
    # Monetary amount is a Decimal-as-string; never a float.
    amount: str | None = None
    currency: str | None = None


class GenericNodeProperties(_EvidenceProperties):
    """Fallback for node kinds without a dedicated closed schema yet."""


# Closed mapping from node_kind to its typed property model. Node kinds without a
# dedicated model fall back to GenericNodeProperties (still extra-tolerant).
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
    """Coerce a raw JSONB property dict into the typed model for ``node_kind``."""
    model = NODE_PROPERTY_MODELS.get(node_kind, GenericNodeProperties)
    return model.model_validate(raw or {})


class MaterializationEdgeProperties(_EvidenceProperties):
    """Properties for edges written by deterministic lazy materialization."""

    adapter: str | None = None
    dedup_hash: str | None = None


def build_edge_properties(raw: dict[str, object]) -> MaterializationEdgeProperties:
    """Coerce a raw JSONB edge property dict into its typed model."""
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
    """Structured error body returned when materialization genuinely fails.

    Distinct from the 200 partial/empty response: a non-empty ``blockers`` list
    here is surfaced via a non-2xx HTTP status (set as the ``detail`` of an
    ``HTTPException``) so clients can tell a real failure from an empty graph.
    """

    error: Annotated[str, Field(description="Stable machine-readable error code.")] = "evidence_materialization_failed"
    message: str
    blockers: list[EvidenceLineageBlocker]
