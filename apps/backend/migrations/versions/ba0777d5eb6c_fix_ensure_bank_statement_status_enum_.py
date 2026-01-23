"""fix: ensure bank_statement_status_enum has PARSING"""

from alembic import op

revision = "ba0777d5eb6c"
down_revision = "0007_normalize_all_enums"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use op.get_bind().dialect.name to check if we're on postgres
    op.execute("ALTER TYPE bank_statement_status_enum ADD VALUE IF NOT EXISTS 'PARSING'")
    op.execute("ALTER TYPE bank_statement_status_enum ADD VALUE IF NOT EXISTS 'UPLOADED'")
    op.execute("ALTER TYPE bank_statement_status_enum ADD VALUE IF NOT EXISTS 'PARSED'")
    op.execute("ALTER TYPE bank_statement_status_enum ADD VALUE IF NOT EXISTS 'APPROVED'")
    op.execute("ALTER TYPE bank_statement_status_enum ADD VALUE IF NOT EXISTS 'REJECTED'")


def downgrade() -> None:
    # PostgreSQL doesn't easily support removing enum values
    pass
