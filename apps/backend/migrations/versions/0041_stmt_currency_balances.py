"""statement per-currency balances

Persist ``currency_balances`` on ``statement_summaries`` (#1123 AC1).

A multi-currency statement (Wise / IBKR / Futu) cannot be represented by the
scalar ``opening_balance`` / ``closing_balance`` columns. This adds an additive
JSONB array of ``{currency, opening, closing}`` so each currency carries its own
opening/closing pair and reconciliation can run per currency
(``open + ΣIN − ΣOUT ≈ close``) without ever summing across currencies. The
scalar columns stay populated for the single-currency degenerate case and
backward compatibility.

FX leg pairing, internal-transfer net-worth, and FX P&L (#1123 AC2/AC3/AC4) are
out of scope here and tracked as follow-up.

Migration risk: low (additive nullable column, no backfill). Existing rows keep
``currency_balances = NULL`` and are interpreted via the scalar columns.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0041_stmt_currency_balances"
down_revision = "0040_retire_bank_stmt_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "statement_summaries",
        sa.Column(
            "currency_balances",
            postgresql.JSONB(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("statement_summaries", "currency_balances")
