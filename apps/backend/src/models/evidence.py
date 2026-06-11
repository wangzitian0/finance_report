"""Evidence graph models for audit lineage."""

from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class EvidenceNode(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Auditable state node in the evidence graph."""

    __tablename__ = "evidence_nodes"
    __table_args__ = (
        UniqueConstraint("user_id", "node_kind", "entity_type", "entity_id", name="uq_evidence_nodes_user_entity"),
        Index("idx_evidence_nodes_user_entity", "user_id", "entity_type", "entity_id"),
        Index("idx_evidence_nodes_user_kind", "user_id", "node_kind"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    outgoing_edges: Mapped[list["EvidenceEdge"]] = relationship(
        back_populates="from_node",
        foreign_keys="EvidenceEdge.from_node_id",
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list["EvidenceEdge"]] = relationship(
        back_populates="to_node",
        foreign_keys="EvidenceEdge.to_node_id",
        cascade="all, delete-orphan",
    )


class EvidenceEdge(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Transformation edge connecting two evidence nodes."""

    __tablename__ = "evidence_edges"
    __table_args__ = (
        UniqueConstraint("user_id", "from_node_id", "to_node_id", "relation", name="uq_evidence_edges_user_relation"),
        Index("idx_evidence_edges_user_from", "user_id", "from_node_id"),
        Index("idx_evidence_edges_user_to", "user_id", "to_node_id"),
        Index("idx_evidence_edges_user_relation_from", "user_id", "relation", "from_node_id"),
        Index("idx_evidence_edges_user_relation_to", "user_id", "relation", "to_node_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("evidence_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation: Mapped[str] = mapped_column(String(100), nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    from_node: Mapped[EvidenceNode] = relationship(
        back_populates="outgoing_edges",
        foreign_keys=[from_node_id],
    )
    to_node: Mapped[EvidenceNode] = relationship(
        back_populates="incoming_edges",
        foreign_keys=[to_node_id],
    )
