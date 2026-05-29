"""epic17: add portfolio models and extend positions"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5e7857c97b74"
down_revision = "0013_add_consistency_checks"
branch_labels = None
depends_on = None


def _has_table(inspector, name: str) -> bool:
    return inspector.has_table(name)


def _has_column(inspector, table: str, column: str) -> bool:
    if not inspector.has_table(table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE asset_type_enum AS ENUM ('stock', 'bond', 'etf', 'mutual_fund', 'property', 'cash', 'other'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE cost_basis_method_enum AS ENUM ('FIFO', 'LIFO', 'AvgCost'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE price_source_enum AS ENUM ('manual', 'api'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE dividend_type_enum AS ENUM ('ordinary', 'qualified'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )

    if not _has_table(inspector, "market_data_override"):
        op.create_table(
            "market_data_override",
            sa.Column("asset_identifier", sa.String(length=100), nullable=False),
            sa.Column("price_date", sa.Date(), nullable=False),
            sa.Column("price", sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column(
                "source",
                postgresql.ENUM("manual", "api", name="price_source_enum", create_type=False),
                nullable=False,
            ),
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_market_data_override_user_id ON market_data_override (user_id)")

    if not _has_table(inspector, "dividend_income"):
        op.create_table(
            "dividend_income",
            sa.Column("position_id", sa.UUID(), nullable=False),
            sa.Column("payment_date", sa.Date(), nullable=False),
            sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column(
                "dividend_type",
                postgresql.ENUM("ordinary", "qualified", name="dividend_type_enum", create_type=False),
                nullable=False,
            ),
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("user_id", sa.UUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["position_id"], ["managed_positions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_dividend_income_user_id ON dividend_income (user_id)")

    # Refresh inspector after potential table creations.
    inspector = sa.inspect(bind)

    op.execute("ALTER TABLE accounts DROP CONSTRAINT IF EXISTS accounts_user_id_fkey")
    if not _has_column(inspector, "atomic_positions", "asset_type"):
        op.add_column(
            "atomic_positions",
            sa.Column(
                "asset_type",
                postgresql.ENUM(
                    "stock",
                    "bond",
                    "etf",
                    "mutual_fund",
                    "property",
                    "cash",
                    "other",
                    name="asset_type_enum",
                    create_type=False,
                ),
                nullable=True,
                comment="Asset classification",
            ),
        )
    if not _has_column(inspector, "atomic_positions", "sector"):
        op.add_column(
            "atomic_positions",
            sa.Column("sector", sa.String(length=50), nullable=True, comment="Sector for allocation"),
        )
    if not _has_column(inspector, "atomic_positions", "geography"):
        op.add_column(
            "atomic_positions",
            sa.Column("geography", sa.String(length=50), nullable=True, comment="Country/region"),
        )
    op.execute("DROP INDEX IF EXISTS idx_atomic_pos_date")
    op.execute("DROP INDEX IF EXISTS idx_atomic_pos_dedup")
    op.execute("CREATE INDEX IF NOT EXISTS ix_atomic_positions_user_id ON atomic_positions (user_id)")
    op.execute("ALTER TABLE atomic_positions DROP CONSTRAINT IF EXISTS atomic_positions_user_id_fkey")
    op.execute("DROP INDEX IF EXISTS idx_atomic_txn_date")
    op.execute("DROP INDEX IF EXISTS idx_atomic_txn_dedup")
    op.execute("CREATE INDEX IF NOT EXISTS ix_atomic_transactions_user_id ON atomic_transactions (user_id)")
    op.execute("ALTER TABLE atomic_transactions DROP CONSTRAINT IF EXISTS atomic_transactions_user_id_fkey")
    op.execute("DROP INDEX IF EXISTS ix_bank_statement_transactions_status")
    op.execute("DROP INDEX IF EXISTS ix_bank_statement_transactions_txn_date")
    op.execute("DROP INDEX IF EXISTS ix_bank_statements_status")
    op.execute("ALTER TABLE bank_statements DROP CONSTRAINT IF EXISTS bank_statements_user_id_fkey")
    op.execute("ALTER TABLE chat_sessions DROP CONSTRAINT IF EXISTS chat_sessions_user_id_fkey")
    op.execute("CREATE INDEX IF NOT EXISTS ix_classification_rules_user_id ON classification_rules (user_id)")
    op.execute("ALTER TABLE classification_rules DROP CONSTRAINT IF EXISTS classification_rules_user_id_fkey")
    op.alter_column(
        "consistency_checks",
        "severity",
        existing_type=sa.VARCHAR(length=20),
        nullable=False,
        existing_server_default=sa.text("'medium'::character varying"),
    )
    op.alter_column(
        "consistency_checks",
        "created_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        existing_server_default=sa.text("now()"),
    )
    op.alter_column(
        "consistency_checks",
        "updated_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=False,
        existing_server_default=sa.text("now()"),
    )
    op.execute("DROP INDEX IF EXISTS ix_consistency_checks_status")
    op.execute("DROP INDEX IF EXISTS ix_consistency_checks_user_check_type_status")
    op.execute("ALTER TABLE journal_entries DROP CONSTRAINT IF EXISTS journal_entries_user_id_fkey")
    op.alter_column(
        "journal_lines",
        "fx_rate",
        existing_type=sa.NUMERIC(precision=12, scale=6),
        type_=sa.DECIMAL(precision=18, scale=6),
        existing_nullable=True,
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_journal_lines_account_id ON journal_lines (account_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_journal_lines_journal_entry_id ON journal_lines (journal_entry_id)")
    op.execute("ALTER TABLE journal_lines DROP CONSTRAINT IF EXISTS journal_lines_journal_entry_id_fkey")
    op.create_foreign_key(None, "journal_lines", "journal_entries", ["journal_entry_id"], ["id"])

    inspector = sa.inspect(bind)
    if not _has_column(inspector, "managed_positions", "cost_basis_method"):
        op.add_column(
            "managed_positions",
            sa.Column(
                "cost_basis_method",
                postgresql.ENUM("FIFO", "LIFO", "AvgCost", name="cost_basis_method_enum", create_type=False),
                nullable=True,
                comment="Method for calculating realized P&L",
            ),
        )
    if not _has_column(inspector, "managed_positions", "unrealized_pnl"):
        op.add_column(
            "managed_positions",
            sa.Column(
                "unrealized_pnl",
                sa.Numeric(precision=18, scale=2),
                nullable=True,
                comment="Unrealized gain/loss (market_value - cost_basis)",
            ),
        )
    if not _has_column(inspector, "managed_positions", "realized_pnl"):
        op.add_column(
            "managed_positions",
            sa.Column(
                "realized_pnl",
                sa.Numeric(precision=18, scale=2),
                nullable=True,
                comment="Realized gain/loss from disposals",
            ),
        )
    op.execute("CREATE INDEX IF NOT EXISTS ix_managed_positions_user_id ON managed_positions (user_id)")
    op.execute("ALTER TABLE managed_positions DROP CONSTRAINT IF EXISTS managed_positions_user_id_fkey")
    op.execute("DROP INDEX IF EXISTS idx_reconciliation_matches_atomic_txn")
    op.execute("DROP INDEX IF EXISTS ix_reconciliation_matches_status")
    op.execute("CREATE INDEX IF NOT EXISTS ix_report_snapshots_user_id ON report_snapshots (user_id)")
    op.execute("ALTER TABLE report_snapshots DROP CONSTRAINT IF EXISTS report_snapshots_user_id_fkey")
    op.execute("CREATE INDEX IF NOT EXISTS ix_uploaded_documents_user_id ON uploaded_documents (user_id)")
    op.execute("ALTER TABLE uploaded_documents DROP CONSTRAINT IF EXISTS uploaded_documents_user_id_fkey")
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_foreign_key(
        op.f("uploaded_documents_user_id_fkey"), "uploaded_documents", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_index(op.f("ix_uploaded_documents_user_id"), table_name="uploaded_documents")
    op.create_foreign_key(
        op.f("report_snapshots_user_id_fkey"), "report_snapshots", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_index(op.f("ix_report_snapshots_user_id"), table_name="report_snapshots")
    op.create_index(op.f("ix_reconciliation_matches_status"), "reconciliation_matches", ["status"], unique=False)
    op.create_index(
        op.f("idx_reconciliation_matches_atomic_txn"), "reconciliation_matches", ["atomic_txn_id"], unique=False
    )
    op.create_foreign_key(
        op.f("managed_positions_user_id_fkey"), "managed_positions", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_index(op.f("ix_managed_positions_user_id"), table_name="managed_positions")
    op.drop_column("managed_positions", "realized_pnl")
    op.drop_column("managed_positions", "unrealized_pnl")
    op.drop_column("managed_positions", "cost_basis_method")
    op.drop_constraint(None, "journal_lines", type_="foreignkey")
    op.create_foreign_key(
        op.f("journal_lines_journal_entry_id_fkey"),
        "journal_lines",
        "journal_entries",
        ["journal_entry_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index(op.f("ix_journal_lines_journal_entry_id"), table_name="journal_lines")
    op.drop_index(op.f("ix_journal_lines_account_id"), table_name="journal_lines")
    op.alter_column(
        "journal_lines",
        "fx_rate",
        existing_type=sa.DECIMAL(precision=18, scale=6),
        type_=sa.NUMERIC(precision=12, scale=6),
        existing_nullable=True,
    )
    op.create_foreign_key(op.f("journal_entries_user_id_fkey"), "journal_entries", "users", ["user_id"], ["id"])
    op.create_index(
        op.f("ix_consistency_checks_user_check_type_status"),
        "consistency_checks",
        ["user_id", "check_type", "status"],
        unique=False,
    )
    op.create_index(op.f("ix_consistency_checks_status"), "consistency_checks", ["status"], unique=False)
    op.alter_column(
        "consistency_checks",
        "updated_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
        existing_server_default=sa.text("now()"),
    )
    op.alter_column(
        "consistency_checks",
        "created_at",
        existing_type=postgresql.TIMESTAMP(timezone=True),
        nullable=True,
        existing_server_default=sa.text("now()"),
    )
    op.alter_column(
        "consistency_checks",
        "severity",
        existing_type=sa.VARCHAR(length=20),
        nullable=True,
        existing_server_default=sa.text("'medium'::character varying"),
    )
    op.create_foreign_key(
        op.f("classification_rules_user_id_fkey"),
        "classification_rules",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index(op.f("ix_classification_rules_user_id"), table_name="classification_rules")
    op.create_foreign_key(op.f("chat_sessions_user_id_fkey"), "chat_sessions", "users", ["user_id"], ["id"])
    op.create_foreign_key(op.f("bank_statements_user_id_fkey"), "bank_statements", "users", ["user_id"], ["id"])
    op.create_index(op.f("ix_bank_statements_status"), "bank_statements", ["status"], unique=False)
    op.create_index(
        op.f("ix_bank_statement_transactions_txn_date"), "bank_statement_transactions", ["txn_date"], unique=False
    )
    op.create_index(
        op.f("ix_bank_statement_transactions_status"), "bank_statement_transactions", ["status"], unique=False
    )
    op.create_foreign_key(
        op.f("atomic_transactions_user_id_fkey"),
        "atomic_transactions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index(op.f("ix_atomic_transactions_user_id"), table_name="atomic_transactions")
    op.create_index(op.f("idx_atomic_txn_dedup"), "atomic_transactions", ["user_id", "dedup_hash"], unique=False)
    op.create_index(op.f("idx_atomic_txn_date"), "atomic_transactions", ["user_id", "txn_date"], unique=False)
    op.create_foreign_key(
        op.f("atomic_positions_user_id_fkey"), "atomic_positions", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_index(op.f("ix_atomic_positions_user_id"), table_name="atomic_positions")
    op.create_index(op.f("idx_atomic_pos_dedup"), "atomic_positions", ["user_id", "dedup_hash"], unique=False)
    op.create_index(op.f("idx_atomic_pos_date"), "atomic_positions", ["user_id", "snapshot_date"], unique=False)
    op.drop_column("atomic_positions", "geography")
    op.drop_column("atomic_positions", "sector")
    op.drop_column("atomic_positions", "asset_type")
    op.create_foreign_key(op.f("accounts_user_id_fkey"), "accounts", "users", ["user_id"], ["id"])
    op.drop_index(op.f("ix_dividend_income_user_id"), table_name="dividend_income")
    op.drop_table("dividend_income")
    op.drop_index(op.f("ix_market_data_override_user_id"), table_name="market_data_override")
    op.drop_table("market_data_override")
    # ### end Alembic commands ###
    # Drop enum types
    op.execute("DROP TYPE IF EXISTS cost_basis_method_enum")
    op.execute("DROP TYPE IF EXISTS asset_type_enum")
