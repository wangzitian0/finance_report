"""harden workflow event contract"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_harden_workflow_event_contract"
down_revision = "0021_add_workflow_events"
branch_labels = None
depends_on = None


REPORT_IMPACT_VALUES = ("none", "processing", "ready", "blocked", "stale")


def _create_enum_if_missing(name: str, values: tuple[str, ...]) -> None:
    quoted_values = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({quoted_values}); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("workflow_events"):
        return

    _create_enum_if_missing("workflow_report_impact_enum", REPORT_IMPACT_VALUES)
    op.execute(
        "ALTER TABLE workflow_events "
        "ALTER COLUMN report_impact TYPE workflow_report_impact_enum "
        "USING report_impact::workflow_report_impact_enum"
    )
    op.execute(
        "DO $$ BEGIN "
        "ALTER TABLE workflow_events ADD CONSTRAINT ck_workflow_events_action_href_internal "
        "CHECK (action_href LIKE '/%' AND action_href NOT LIKE '//%' AND action_href NOT LIKE '%://%'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$;"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("workflow_events"):
        op.execute("DROP TYPE IF EXISTS workflow_report_impact_enum")
        return

    op.execute("ALTER TABLE workflow_events DROP CONSTRAINT IF EXISTS ck_workflow_events_action_href_internal")
    op.execute(
        "ALTER TABLE workflow_events "
        "ALTER COLUMN report_impact TYPE VARCHAR(50) "
        "USING report_impact::text"
    )
    op.execute("DROP TYPE IF EXISTS workflow_report_impact_enum")
