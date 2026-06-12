"""Evidence graph models for audit lineage."""

from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, and_, event
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from src.database import Base
from src.models.base import TimestampMixin, UserOwnedMixin, UUIDMixin


class EvidenceNode(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    """Auditable state node in the evidence graph."""

    __tablename__ = "evidence_nodes"
    __table_args__ = (
        UniqueConstraint("user_id", "node_kind", "entity_type", "entity_id", name="uq_evidence_nodes_user_entity"),
        UniqueConstraint("user_id", "id", name="uq_evidence_nodes_user_id"),
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
        primaryjoin=lambda: and_(
            EvidenceNode.user_id == foreign(EvidenceEdge.user_id),
            EvidenceNode.id == foreign(EvidenceEdge.from_node_id),
        ),
        foreign_keys=lambda: [EvidenceEdge.user_id, EvidenceEdge.from_node_id],
        cascade="all, delete-orphan",
    )
    incoming_edges: Mapped[list["EvidenceEdge"]] = relationship(
        back_populates="to_node",
        primaryjoin=lambda: and_(
            EvidenceNode.user_id == foreign(EvidenceEdge.user_id),
            EvidenceNode.id == foreign(EvidenceEdge.to_node_id),
        ),
        foreign_keys=lambda: [EvidenceEdge.user_id, EvidenceEdge.to_node_id],
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

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    from_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    to_node_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    relation: Mapped[str] = mapped_column(String(100), nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    from_node: Mapped[EvidenceNode] = relationship(
        back_populates="outgoing_edges",
        primaryjoin=lambda: and_(
            EvidenceNode.user_id == foreign(EvidenceEdge.user_id),
            EvidenceNode.id == foreign(EvidenceEdge.from_node_id),
        ),
        foreign_keys=lambda: [EvidenceEdge.user_id, EvidenceEdge.from_node_id],
    )
    to_node: Mapped[EvidenceNode] = relationship(
        back_populates="incoming_edges",
        primaryjoin=lambda: and_(
            EvidenceNode.user_id == foreign(EvidenceEdge.user_id),
            EvidenceNode.id == foreign(EvidenceEdge.to_node_id),
        ),
        foreign_keys=lambda: [EvidenceEdge.user_id, EvidenceEdge.to_node_id],
        overlaps="from_node,outgoing_edges",
    )


_AUDIT_ANCHOR_SCOPE_SQL = """
CREATE OR REPLACE FUNCTION fr_validate_reconciliation_match_journal_entry_user()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_match_user_id uuid;
    v_entry_user_id uuid;
BEGIN
    SELECT atomic.user_id
    INTO v_match_user_id
    FROM reconciliation_matches match
    JOIN atomic_transactions atomic ON atomic.id = match.atomic_txn_id
    WHERE match.id = NEW.match_id;

    SELECT entry.user_id
    INTO v_entry_user_id
    FROM journal_entries entry
    WHERE entry.id = NEW.journal_entry_id;

    IF v_match_user_id IS NULL OR v_entry_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF v_match_user_id <> v_entry_user_id THEN
        RAISE EXCEPTION 'reconciliation match % cannot link cross-user journal entry %',
            NEW.match_id, NEW.journal_entry_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_reconciliation_match_journal_entries_same_user';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fr_validate_atomic_transaction_source_document_user()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_atomic_user_id uuid;
    v_document_user_id uuid;
BEGIN
    SELECT user_id INTO v_atomic_user_id
    FROM atomic_transactions
    WHERE id = NEW.atomic_txn_id;

    SELECT user_id INTO v_document_user_id
    FROM uploaded_documents
    WHERE id = NEW.uploaded_document_id;

    IF v_atomic_user_id IS NULL OR v_document_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF v_atomic_user_id <> v_document_user_id THEN
        RAISE EXCEPTION 'atomic transaction % cannot link cross-user uploaded document %',
            NEW.atomic_txn_id, NEW.uploaded_document_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_atomic_transaction_source_documents_same_user';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fr_validate_atomic_position_source_document_user()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_atomic_user_id uuid;
    v_document_user_id uuid;
BEGIN
    SELECT user_id INTO v_atomic_user_id
    FROM atomic_positions
    WHERE id = NEW.atomic_position_id;

    SELECT user_id INTO v_document_user_id
    FROM uploaded_documents
    WHERE id = NEW.uploaded_document_id;

    IF v_atomic_user_id IS NULL OR v_document_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF v_atomic_user_id <> v_document_user_id THEN
        RAISE EXCEPTION 'atomic position % cannot link cross-user uploaded document %',
            NEW.atomic_position_id, NEW.uploaded_document_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_atomic_position_source_documents_same_user';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fr_validate_journal_line_account_user()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_entry_user_id uuid;
    v_account_user_id uuid;
BEGIN
    SELECT user_id INTO v_entry_user_id
    FROM journal_entries
    WHERE id = NEW.journal_entry_id;

    SELECT user_id INTO v_account_user_id
    FROM accounts
    WHERE id = NEW.account_id;

    IF v_entry_user_id IS NULL OR v_account_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF v_entry_user_id <> v_account_user_id THEN
        RAISE EXCEPTION 'journal line % cannot reference cross-user account %',
            NEW.id, NEW.account_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_journal_lines_account_same_user';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fr_validate_statement_summary_account_user()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_user_id uuid;
BEGIN
    IF NEW.account_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT user_id INTO v_account_user_id
    FROM accounts
    WHERE id = NEW.account_id;

    IF v_account_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.user_id <> v_account_user_id THEN
        RAISE EXCEPTION 'statement summary % cannot reference cross-user account %',
            NEW.id, NEW.account_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_statement_summaries_account_same_user';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fr_validate_classification_rule_account_user()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_account_user_id uuid;
BEGIN
    IF NEW.default_account_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT user_id INTO v_account_user_id
    FROM accounts
    WHERE id = NEW.default_account_id;

    IF v_account_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.user_id <> v_account_user_id THEN
        RAISE EXCEPTION 'classification rule % cannot reference cross-user default account %',
            NEW.id, NEW.default_account_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_classification_rules_default_account_same_user';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION fr_validate_transaction_classification_user_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_atomic_user_id uuid;
    v_rule_user_id uuid;
    v_account_user_id uuid;
BEGIN
    SELECT user_id INTO v_atomic_user_id
    FROM atomic_transactions
    WHERE id = NEW.atomic_txn_id;

    SELECT user_id INTO v_rule_user_id
    FROM classification_rules
    WHERE id = NEW.rule_version_id;

    IF v_atomic_user_id IS NOT NULL
       AND v_rule_user_id IS NOT NULL
       AND v_atomic_user_id <> v_rule_user_id THEN
        RAISE EXCEPTION 'transaction classification % cannot link cross-user rule %',
            NEW.id, NEW.rule_version_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_transaction_classification_rule_same_user';
    END IF;

    IF NEW.account_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT user_id INTO v_account_user_id
    FROM accounts
    WHERE id = NEW.account_id;

    IF v_atomic_user_id IS NOT NULL
       AND v_account_user_id IS NOT NULL
       AND v_atomic_user_id <> v_account_user_id THEN
        RAISE EXCEPTION 'transaction classification % cannot reference cross-user account %',
            NEW.id, NEW.account_id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_transaction_classification_account_same_user';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_reconciliation_match_journal_entries_same_user ON reconciliation_match_journal_entries;
CREATE TRIGGER trg_reconciliation_match_journal_entries_same_user
BEFORE INSERT OR UPDATE ON reconciliation_match_journal_entries
FOR EACH ROW EXECUTE FUNCTION fr_validate_reconciliation_match_journal_entry_user();

DROP TRIGGER IF EXISTS trg_atomic_transaction_source_documents_same_user ON atomic_transaction_source_documents;
CREATE TRIGGER trg_atomic_transaction_source_documents_same_user
BEFORE INSERT OR UPDATE ON atomic_transaction_source_documents
FOR EACH ROW EXECUTE FUNCTION fr_validate_atomic_transaction_source_document_user();

DROP TRIGGER IF EXISTS trg_atomic_position_source_documents_same_user ON atomic_position_source_documents;
CREATE TRIGGER trg_atomic_position_source_documents_same_user
BEFORE INSERT OR UPDATE ON atomic_position_source_documents
FOR EACH ROW EXECUTE FUNCTION fr_validate_atomic_position_source_document_user();

DROP TRIGGER IF EXISTS trg_journal_lines_account_same_user ON journal_lines;
CREATE TRIGGER trg_journal_lines_account_same_user
BEFORE INSERT OR UPDATE ON journal_lines
FOR EACH ROW EXECUTE FUNCTION fr_validate_journal_line_account_user();

DROP TRIGGER IF EXISTS trg_statement_summaries_account_same_user ON statement_summaries;
CREATE TRIGGER trg_statement_summaries_account_same_user
BEFORE INSERT OR UPDATE ON statement_summaries
FOR EACH ROW EXECUTE FUNCTION fr_validate_statement_summary_account_user();

DROP TRIGGER IF EXISTS trg_classification_rules_default_account_same_user ON classification_rules;
CREATE TRIGGER trg_classification_rules_default_account_same_user
BEFORE INSERT OR UPDATE ON classification_rules
FOR EACH ROW EXECUTE FUNCTION fr_validate_classification_rule_account_user();

DROP TRIGGER IF EXISTS trg_transaction_classification_user_scope ON transaction_classification;
CREATE TRIGGER trg_transaction_classification_user_scope
BEFORE INSERT OR UPDATE ON transaction_classification
FOR EACH ROW EXECUTE FUNCTION fr_validate_transaction_classification_user_scope();
"""


def _split_postgresql_ddl(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    start = 0
    in_dollar_quote = False
    index = 0

    while index < len(sql):
        if sql.startswith("$$", index):
            in_dollar_quote = not in_dollar_quote
            index += 2
            continue

        if sql[index] == ";" and not in_dollar_quote:
            statement = sql[start : index + 1].strip()
            if statement:
                statements.append(statement)
            start = index + 1

        index += 1

    trailing = sql[start:].strip()
    if trailing:
        statements.append(trailing)
    return tuple(statements)


def _install_audit_anchor_scope_ddl(target: Any, connection: Any, **_: Any) -> None:
    if connection.dialect.name != "postgresql":
        return

    for statement in _split_postgresql_ddl(_AUDIT_ANCHOR_SCOPE_SQL):
        connection.exec_driver_sql(statement)


event.listen(Base.metadata, "after_create", _install_audit_anchor_scope_ddl)
