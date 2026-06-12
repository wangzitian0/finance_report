"""audit anchor referential integrity"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0034_audit_anchor_ri"
down_revision = "0033_financial_fact_constraints"
branch_labels = None
depends_on = None


UUID_RE = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


AUDIT_ANCHOR_PRECHECK_DDL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM evidence_edges edge
        JOIN evidence_nodes source_node ON source_node.id = edge.from_node_id
        JOIN evidence_nodes target_node ON target_node.id = edge.to_node_id
        WHERE edge.user_id <> source_node.user_id
           OR edge.user_id <> target_node.user_id
    ) THEN
        RAISE EXCEPTION 'preflight failed: evidence_edges contain cross-user endpoints';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM journal_lines line
        JOIN journal_entries entry ON entry.id = line.journal_entry_id
        JOIN accounts account ON account.id = line.account_id
        WHERE account.user_id <> entry.user_id
    ) THEN
        RAISE EXCEPTION 'preflight failed: journal_lines contain cross-user account references';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM statement_summaries summary
        JOIN accounts account ON account.id = summary.account_id
        WHERE summary.account_id IS NOT NULL
          AND account.user_id <> summary.user_id
    ) THEN
        RAISE EXCEPTION 'preflight failed: statement_summaries contain cross-user account references';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM classification_rules rule
        JOIN accounts account ON account.id = rule.default_account_id
        WHERE rule.default_account_id IS NOT NULL
          AND account.user_id <> rule.user_id
    ) THEN
        RAISE EXCEPTION 'preflight failed: classification_rules contain cross-user default accounts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM transaction_classification classification
        JOIN atomic_transactions atomic ON atomic.id = classification.atomic_txn_id
        JOIN classification_rules rule ON rule.id = classification.rule_version_id
        LEFT JOIN accounts account ON account.id = classification.account_id
        WHERE rule.user_id <> atomic.user_id
           OR (classification.account_id IS NOT NULL AND account.user_id <> atomic.user_id)
    ) THEN
        RAISE EXCEPTION 'preflight failed: transaction_classification contains cross-user rule or account references';
    END IF;
END
$$;

-- Existing JSONB/naked UUID fields are compatibility hints. This migration will
-- backfill resolvable legacy audit anchors into normalized link tables.
-- unresolved legacy audit anchors remain preserved for explicit blocker reporting.
"""


AUDIT_ANCHOR_FUNCTION_DDL = """
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

CREATE OR REPLACE FUNCTION fr_validate_evidence_edge_tenant_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_from_user_id uuid;
    v_to_user_id uuid;
BEGIN
    SELECT user_id INTO v_from_user_id
    FROM evidence_nodes
    WHERE id = NEW.from_node_id;

    SELECT user_id INTO v_to_user_id
    FROM evidence_nodes
    WHERE id = NEW.to_node_id;

    IF v_from_user_id IS NULL OR v_to_user_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.user_id <> v_from_user_id OR NEW.user_id <> v_to_user_id THEN
        RAISE EXCEPTION 'evidence edge % cannot connect cross-user endpoints',
            NEW.id
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_evidence_edges_same_user_endpoints';
    END IF;

    RETURN NEW;
END;
$$;
"""


def upgrade() -> None:
    op.execute(AUDIT_ANCHOR_PRECHECK_DDL)

    op.create_table(
        "reconciliation_match_journal_entries",
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("journal_entry_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["reconciliation_matches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("match_id", "journal_entry_id"),
    )
    op.create_index(
        "idx_reconciliation_match_journal_entries_entry",
        "reconciliation_match_journal_entries",
        ["journal_entry_id"],
    )

    op.create_table(
        "atomic_transaction_source_documents",
        sa.Column("atomic_txn_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["atomic_txn_id"], ["atomic_transactions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_document_id"], ["uploaded_documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("atomic_txn_id", "uploaded_document_id"),
    )
    op.create_index(
        "idx_atomic_txn_source_docs_document",
        "atomic_transaction_source_documents",
        ["uploaded_document_id"],
    )

    op.create_table(
        "atomic_position_source_documents",
        sa.Column("atomic_position_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("doc_type", sa.String(length=50), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["atomic_position_id"], ["atomic_positions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_document_id"], ["uploaded_documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("atomic_position_id", "uploaded_document_id"),
    )
    op.create_index(
        "idx_atomic_position_source_docs_document",
        "atomic_position_source_documents",
        ["uploaded_document_id"],
    )

    op.execute(
        f"""
        INSERT INTO reconciliation_match_journal_entries (
            match_id, journal_entry_id, created_at, updated_at
        )
        SELECT DISTINCT match.id, entry.id, now(), now()
        FROM reconciliation_matches match
        JOIN atomic_transactions atomic ON atomic.id = match.atomic_txn_id
        CROSS JOIN LATERAL jsonb_array_elements_text(
            CASE
                WHEN jsonb_typeof(match.journal_entry_ids) = 'array' THEN match.journal_entry_ids
                ELSE '[]'::jsonb
            END
        ) AS raw_entry(entry_id_text)
        JOIN journal_entries entry
          ON raw_entry.entry_id_text ~* '^{UUID_RE}$'
         AND entry.id = raw_entry.entry_id_text::uuid
         AND entry.user_id = atomic.user_id
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        f"""
        INSERT INTO atomic_transaction_source_documents (
            atomic_txn_id, uploaded_document_id, doc_type, ordinal, created_at, updated_at
        )
        SELECT DISTINCT ON (atomic.id, document.id)
            atomic.id,
            document.id,
            COALESCE(NULLIF(source_item.value ->> 'doc_type', ''), 'legacy'),
            source_item.ordinality::integer - 1,
            now(),
            now()
        FROM atomic_transactions atomic
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(atomic.source_documents) = 'array' THEN atomic.source_documents
                WHEN jsonb_typeof(atomic.source_documents) = 'object'
                 AND jsonb_typeof(atomic.source_documents -> 'documents') = 'array'
                    THEN atomic.source_documents -> 'documents'
                ELSE '[]'::jsonb
            END
        ) WITH ORDINALITY AS source_item(value, ordinality)
        JOIN uploaded_documents document
          ON (source_item.value ->> 'doc_id') ~* '^{UUID_RE}$'
         AND document.id = (source_item.value ->> 'doc_id')::uuid
         AND document.user_id = atomic.user_id
        ORDER BY atomic.id, document.id, source_item.ordinality
        ON CONFLICT DO NOTHING
        """
    )

    op.execute(
        f"""
        INSERT INTO atomic_position_source_documents (
            atomic_position_id, uploaded_document_id, doc_type, ordinal, created_at, updated_at
        )
        SELECT DISTINCT ON (position.id, document.id)
            position.id,
            document.id,
            COALESCE(NULLIF(source_item.value ->> 'doc_type', ''), 'legacy'),
            source_item.ordinality::integer - 1,
            now(),
            now()
        FROM atomic_positions position
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(position.source_documents) = 'array' THEN position.source_documents
                WHEN jsonb_typeof(position.source_documents) = 'object'
                 AND jsonb_typeof(position.source_documents -> 'documents') = 'array'
                    THEN position.source_documents -> 'documents'
                ELSE '[]'::jsonb
            END
        ) WITH ORDINALITY AS source_item(value, ordinality)
        JOIN uploaded_documents document
          ON (source_item.value ->> 'doc_id') ~* '^{UUID_RE}$'
         AND document.id = (source_item.value ->> 'doc_id')::uuid
         AND document.user_id = position.user_id
        ORDER BY position.id, document.id, source_item.ordinality
        ON CONFLICT DO NOTHING
        """
    )

    op.create_unique_constraint("uq_evidence_nodes_user_id", "evidence_nodes", ["user_id", "id"])
    op.drop_constraint("evidence_edges_from_node_id_fkey", "evidence_edges", type_="foreignkey")
    op.drop_constraint("evidence_edges_to_node_id_fkey", "evidence_edges", type_="foreignkey")
    op.create_foreign_key(
        "fk_evidence_edges_user_from_node",
        "evidence_edges",
        "evidence_nodes",
        ["user_id", "from_node_id"],
        ["user_id", "id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_evidence_edges_user_to_node",
        "evidence_edges",
        "evidence_nodes",
        ["user_id", "to_node_id"],
        ["user_id", "id"],
        ondelete="CASCADE",
    )

    op.execute(AUDIT_ANCHOR_FUNCTION_DDL)
    for table_name, trigger_name, function_name in [
        (
            "reconciliation_match_journal_entries",
            "trg_reconciliation_match_journal_entries_same_user",
            "fr_validate_reconciliation_match_journal_entry_user",
        ),
        (
            "atomic_transaction_source_documents",
            "trg_atomic_transaction_source_documents_same_user",
            "fr_validate_atomic_transaction_source_document_user",
        ),
        (
            "atomic_position_source_documents",
            "trg_atomic_position_source_documents_same_user",
            "fr_validate_atomic_position_source_document_user",
        ),
        ("journal_lines", "trg_journal_lines_account_same_user", "fr_validate_journal_line_account_user"),
        (
            "statement_summaries",
            "trg_statement_summaries_account_same_user",
            "fr_validate_statement_summary_account_user",
        ),
        (
            "classification_rules",
            "trg_classification_rules_default_account_same_user",
            "fr_validate_classification_rule_account_user",
        ),
        (
            "transaction_classification",
            "trg_transaction_classification_user_scope",
            "fr_validate_transaction_classification_user_scope",
        ),
        ("evidence_edges", "trg_evidence_edges_same_user_endpoints", "fr_validate_evidence_edge_tenant_scope"),
    ]:
        op.execute(
            f"""
            CREATE TRIGGER {trigger_name}
            BEFORE INSERT OR UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION {function_name}()
            """
        )


def downgrade() -> None:
    for table_name, trigger_name in [
        ("evidence_edges", "trg_evidence_edges_same_user_endpoints"),
        ("transaction_classification", "trg_transaction_classification_user_scope"),
        ("classification_rules", "trg_classification_rules_default_account_same_user"),
        ("statement_summaries", "trg_statement_summaries_account_same_user"),
        ("journal_lines", "trg_journal_lines_account_same_user"),
        ("atomic_position_source_documents", "trg_atomic_position_source_documents_same_user"),
        ("atomic_transaction_source_documents", "trg_atomic_transaction_source_documents_same_user"),
        ("reconciliation_match_journal_entries", "trg_reconciliation_match_journal_entries_same_user"),
    ]:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}")

    for function_name in [
        "fr_validate_evidence_edge_tenant_scope",
        "fr_validate_transaction_classification_user_scope",
        "fr_validate_classification_rule_account_user",
        "fr_validate_statement_summary_account_user",
        "fr_validate_journal_line_account_user",
        "fr_validate_atomic_position_source_document_user",
        "fr_validate_atomic_transaction_source_document_user",
        "fr_validate_reconciliation_match_journal_entry_user",
    ]:
        op.execute(f"DROP FUNCTION IF EXISTS {function_name}()")

    op.drop_constraint("fk_evidence_edges_user_to_node", "evidence_edges", type_="foreignkey")
    op.drop_constraint("fk_evidence_edges_user_from_node", "evidence_edges", type_="foreignkey")
    op.create_foreign_key(
        "evidence_edges_to_node_id_fkey",
        "evidence_edges",
        "evidence_nodes",
        ["to_node_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "evidence_edges_from_node_id_fkey",
        "evidence_edges",
        "evidence_nodes",
        ["from_node_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_evidence_nodes_user_id", "evidence_nodes", type_="unique")

    op.drop_index("idx_atomic_position_source_docs_document", table_name="atomic_position_source_documents")
    op.drop_table("atomic_position_source_documents")
    op.drop_index("idx_atomic_txn_source_docs_document", table_name="atomic_transaction_source_documents")
    op.drop_table("atomic_transaction_source_documents")
    op.drop_index("idx_reconciliation_match_journal_entries_entry", table_name="reconciliation_match_journal_entries")
    op.drop_table("reconciliation_match_journal_entries")
