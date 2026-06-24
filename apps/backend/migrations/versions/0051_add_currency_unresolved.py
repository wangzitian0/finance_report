"""add currency_unresolved flag to atomic_transactions (EPIC-012 AC12.40)

Phase E of the currency strong-type invariant (#1341). A transaction's currency
must be established at the ingest boundary: attached explicitly when determinable,
otherwise flagged for human review and blocked from promotion to a JournalLine.

This adds the ``currency_unresolved`` boolean flag plus the resolution-audit
columns ``currency_resolved_by`` / ``currency_resolved_at`` (who/when). The flag
defaults to ``false`` so every existing row is treated as resolved (their currency
was already persisted by the legacy ingest path); only newly-ingested rows whose
currency could not be determined are flagged ``true``.
"""

import sqlalchemy as sa
from alembic import op

revision = "0051_add_currency_unresolved"
down_revision = "0050_add_app_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "atomic_transactions",
        sa.Column(
            "currency_unresolved",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
            comment=(
                "EPIC-012 AC12.40: True when the ingest boundary could NOT determine the "
                "transaction currency (no statement/account metadata). The currency column then "
                "holds a non-authoritative placeholder and the row MUST NOT be promoted to a "
                "JournalLine until a reviewer specifies the currency. Never silent-default."
            ),
        ),
    )
    op.add_column(
        "atomic_transactions",
        sa.Column(
            "currency_resolved_by",
            sa.UUID(),
            sa.ForeignKey("users.id"),
            nullable=True,
            comment="EPIC-012 AC12.40.3: user_id of the reviewer who specified the currency (audit: who).",
        ),
    )
    op.add_column(
        "atomic_transactions",
        sa.Column(
            "currency_resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="EPIC-012 AC12.40.3: timestamp the currency was specified by a reviewer (audit: when).",
        ),
    )


def downgrade() -> None:
    op.drop_column("atomic_transactions", "currency_resolved_at")
    op.drop_column("atomic_transactions", "currency_resolved_by")
    op.drop_column("atomic_transactions", "currency_unresolved")
