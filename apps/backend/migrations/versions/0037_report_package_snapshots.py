"""report package snapshots

Extends Layer 4 report snapshots so the personal report package can be saved
as an immutable generated artifact. Package snapshots freeze framework and
readiness context rather than a classification rule version, so
rule_version_id becomes nullable while statement snapshots may keep using it.

Migration risk: low-medium (enum expansion plus nullable FK column). Existing
rows keep their rule_version_id values.
"""

from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0037_report_package_snapshots"
down_revision = "0036_confidence_metric_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE report_type_enum ADD VALUE IF NOT EXISTS 'package'")
    op.alter_column(
        "report_snapshots",
        "rule_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("DELETE FROM report_snapshots WHERE report_type = 'package'")
    op.alter_column(
        "report_snapshots",
        "rule_version_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    # PostgreSQL enum labels cannot be removed without rebuilding the type.
