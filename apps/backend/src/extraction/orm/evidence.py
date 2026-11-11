"""Evidence graph models for audit lineage."""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, and_, event
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from src.database import Base, split_postgresql_ddl
from src.platform.orm.base import TimestampMixin, UserOwnedMixin, UUIDMixin


def _edge_join(attr: str):
    return lambda: and_(
        EvidenceNode.user_id == foreign(EvidenceEdge.user_id),
        EvidenceNode.id == foreign(getattr(EvidenceEdge, attr)),
    )


def _edge_fks(attr: str):
    return lambda: [EvidenceEdge.user_id, getattr(EvidenceEdge, attr)]


class EvidenceNode(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Auditable state node in the evidence graph."""

    __tablename__ = "evidence_nodes"
    __table_args__ = (
        UniqueConstraint("user_id", "node_kind", "entity_type", "entity_id", name="uq_evidence_nodes_user_entity"),
        UniqueConstraint("user_id", "id", name="uq_evidence_nodes_user_id"),
        Index("idx_evidence_nodes_user_entity", "user_id", "entity_type", "entity_id"),
        Index("idx_evidence_nodes_user_kind", "user_id", "node_kind"),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    node_kind: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    outgoing_edges: Mapped[list["EvidenceEdge"]] = relationship(
        back_populates="from_node",
        primaryjoin=_edge_join("from_node_id"),
        foreign_keys=_edge_fks("from_node_id"),
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list["EvidenceEdge"]] = relationship(
        back_populates="to_node",
        primaryjoin=_edge_join("to_node_id"),
        foreign_keys=_edge_fks("to_node_id"),
        cascade="all, delete-orphan",
        overlaps="from_node,outgoing_edges",
    )


class EvidenceEdge(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Transformation edge connecting two evidence nodes."""

    __tablename__ = "evidence_edges"
    __table_args__ = (
        UniqueConstraint("user_id", "from_node_id", "to_node_id", "relation", name="uq_evidence_edges_user_relation"),
        ForeignKeyConstraint(
            ["user_id", "from_node_id"],
            ["evidence_nodes.user_id", "evidence_nodes.id"],
            name="fk_evidence_edges_user_from_node",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["user_id", "to_node_id"],
            ["evidence_nodes.user_id", "evidence_nodes.id"],
            name="fk_evidence_edges_user_to_node",
            ondelete="CASCADE",
        ),
        Index("idx_evidence_edges_user_from", "user_id", "from_node_id"),
        Index("idx_evidence_edges_user_to", "user_id", "to_node_id"),
        Index("idx_evidence_edges_user_relation_from", "user_id", "relation", "from_node_id"),
        Index("idx_evidence_edges_user_relation_to", "user_id", "relation", "to_node_id"),
    )

    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    from_node_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    to_node_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    relation: Mapped[str] = mapped_column(String(100), nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    from_node: Mapped[EvidenceNode] = relationship(
        back_populates="outgoing_edges",
        primaryjoin=_edge_join("from_node_id"),
        foreign_keys=_edge_fks("from_node_id"),
    )
    to_node: Mapped[EvidenceNode] = relationship(
        back_populates="incoming_edges",
        primaryjoin=_edge_join("to_node_id"),
        foreign_keys=_edge_fks("to_node_id"),
        overlaps="from_node,outgoing_edges",
    )


def _pair_trigger_fn(
    fn_name: str,
    left_sql: str,
    right_sql: str,
    msg: str,
    left_ref: str,
    right_ref: str,
    constraint: str,
    *,
    null_guard: str = "",
) -> str:
    return f"""
CREATE OR REPLACE FUNCTION {fn_name}()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_left uuid; v_right uuid;
BEGIN
    {null_guard}{left_sql}
    {right_sql}
    IF v_left IS NULL OR v_right IS NULL THEN RETURN NEW; END IF;
    IF v_left <> v_right THEN
        RAISE EXCEPTION '{msg}', {left_ref}, {right_ref}
            USING ERRCODE = '23514', CONSTRAINT = '{constraint}';
    END IF;
    RETURN NEW;
END;
$$;"""


_PAIR_SPECS = (
    (
        "reconciliation_match_journal_entries",
        "trg_reconciliation_match_journal_entries_same_user",
        "fr_validate_reconciliation_match_journal_entry_user",
        "SELECT atomic.user_id INTO v_left FROM reconciliation_matches match JOIN atomic_transactions atomic ON atomic.id = match.atomic_txn_id WHERE match.id = NEW.match_id;",
        "SELECT user_id INTO v_right FROM journal_entries WHERE id = NEW.journal_entry_id;",
        "reconciliation match % cannot link cross-user journal entry %",
        "NEW.match_id",
        "NEW.journal_entry_id",
        "ck_reconciliation_match_journal_entries_same_user",
        "",
    ),
    (
        "atomic_transaction_source_documents",
        "trg_atomic_transaction_source_documents_same_user",
        "fr_validate_atomic_transaction_source_document_user",
        "SELECT user_id INTO v_left FROM atomic_transactions WHERE id = NEW.atomic_txn_id;",
        "SELECT user_id INTO v_right FROM uploaded_documents WHERE id = NEW.uploaded_document_id;",
        "atomic transaction % cannot link cross-user uploaded document %",
        "NEW.atomic_txn_id",
        "NEW.uploaded_document_id",
        "ck_atomic_transaction_source_documents_same_user",
        "",
    ),
    (
        "atomic_position_source_documents",
        "trg_atomic_position_source_documents_same_user",
        "fr_validate_atomic_position_source_document_user",
        "SELECT user_id INTO v_left FROM atomic_positions WHERE id = NEW.atomic_position_id;",
        "SELECT user_id INTO v_right FROM uploaded_documents WHERE id = NEW.uploaded_document_id;",
        "atomic position % cannot link cross-user uploaded document %",
        "NEW.atomic_position_id",
        "NEW.uploaded_document_id",
        "ck_atomic_position_source_documents_same_user",
        "",
    ),
    (
        "journal_lines",
        "trg_journal_lines_account_same_user",
        "fr_validate_journal_line_account_user",
        "SELECT user_id INTO v_left FROM journal_entries WHERE id = NEW.journal_entry_id;",
        "SELECT user_id INTO v_right FROM accounts WHERE id = NEW.account_id;",
        "journal line % cannot reference cross-user account %",
        "NEW.id",
        "NEW.account_id",
        "ck_journal_lines_account_same_user",
        "",
    ),
    (
        "statement_summaries",
        "trg_statement_summaries_account_same_user",
        "fr_validate_statement_summary_account_user",
        "v_left := NEW.user_id;",
        "SELECT user_id INTO v_right FROM accounts WHERE id = NEW.account_id;",
        "statement summary % cannot reference cross-user account %",
        "NEW.id",
        "NEW.account_id",
        "ck_statement_summaries_account_same_user",
        "IF NEW.account_id IS NULL THEN RETURN NEW; END IF;\n    ",
    ),
    (
        "classification_rules",
        "trg_classification_rules_default_account_same_user",
        "fr_validate_classification_rule_account_user",
        "v_left := NEW.user_id;",
        "SELECT user_id INTO v_right FROM accounts WHERE id = NEW.default_account_id;",
        "classification rule % cannot reference cross-user default account %",
        "NEW.id",
        "NEW.default_account_id",
        "ck_classification_rules_default_account_same_user",
        "IF NEW.default_account_id IS NULL THEN RETURN NEW; END IF;\n    ",
    ),
)

_CLASSIFICATION_FN_SQL = """
CREATE OR REPLACE FUNCTION fr_validate_transaction_classification_user_scope()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_atomic uuid; v_rule uuid; v_account uuid;
BEGIN
    SELECT user_id INTO v_atomic FROM atomic_transactions WHERE id = NEW.atomic_txn_id;
    SELECT user_id INTO v_rule FROM classification_rules WHERE id = NEW.rule_version_id;
    IF v_atomic IS NOT NULL AND v_rule IS NOT NULL AND v_atomic <> v_rule THEN
        RAISE EXCEPTION 'transaction classification % cannot link cross-user rule %', NEW.id, NEW.rule_version_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_transaction_classification_rule_same_user';
    END IF;
    IF NEW.account_id IS NULL THEN RETURN NEW; END IF;
    SELECT user_id INTO v_account FROM accounts WHERE id = NEW.account_id;
    IF v_atomic IS NOT NULL AND v_account IS NOT NULL AND v_atomic <> v_account THEN
        RAISE EXCEPTION 'transaction classification % cannot reference cross-user account %', NEW.id, NEW.account_id
            USING ERRCODE = '23514', CONSTRAINT = 'ck_transaction_classification_account_same_user';
    END IF;
    RETURN NEW;
END;
$$;"""

_ALL_TRIGGERS = tuple((tbl, trg, fn) for tbl, trg, fn, *_ in _PAIR_SPECS) + (
    ("transaction_classification", "trg_transaction_classification_user_scope", "fr_validate_transaction_classification_user_scope"),
)

_AUDIT_ANCHOR_SCOPE_SQL = "\n".join(
    [
        *(
            _pair_trigger_fn(fn, l_sql, r_sql, msg, l_ref, r_ref, ck, null_guard=ng)
            for _, _, fn, l_sql, r_sql, msg, l_ref, r_ref, ck, ng in _PAIR_SPECS
        ),
        _CLASSIFICATION_FN_SQL,
        *(
            f"DROP TRIGGER IF EXISTS {trg} ON {tbl};\n"
            f"CREATE TRIGGER {trg} BEFORE INSERT OR UPDATE ON {tbl} FOR EACH ROW EXECUTE FUNCTION {fn}();"
            for tbl, trg, fn in _ALL_TRIGGERS
        ),
    ]
)


def _install_audit_anchor_scope_ddl(target: Any, connection: Any, **_: Any) -> None:
    _ = target
    if connection.dialect.name != "postgresql":
        return
    for statement in split_postgresql_ddl(_AUDIT_ANCHOR_SCOPE_SQL):
        connection.exec_driver_sql(statement)


event.listen(Base.metadata, "after_create", _install_audit_anchor_scope_ddl)
