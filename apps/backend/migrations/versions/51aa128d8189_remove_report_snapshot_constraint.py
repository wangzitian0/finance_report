"""remove_report_snapshot_constraint"""

from alembic import op

revision = "51aa128d8189"
down_revision = "bcd695dcaf71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_report_snapshot", "report_snapshots", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_report_snapshot",
        "report_snapshots",
        ["user_id", "report_type", "as_of_date", "rule_version_id"],
    )
