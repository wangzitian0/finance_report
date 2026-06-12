"""add financial fact constraints"""

import sqlalchemy as sa
from alembic import op

revision = "0033_financial_fact_constraints"
down_revision = "0032_ledger_invariants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM atomic_transactions
        WHERE amount <= 0
    ) THEN
        RAISE EXCEPTION 'preflight failed: atomic_transactions contains non-positive amounts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM atomic_positions
        WHERE market_value < 0
    ) THEN
        RAISE EXCEPTION 'preflight failed: atomic_positions contains negative market values';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM manual_valuation_snapshots
        WHERE value <= 0
           OR recurrence_days <= 0
    ) THEN
        RAISE EXCEPTION 'preflight failed: manual_valuation_snapshots contains non-positive values';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM statement_summaries
        WHERE period_start IS NOT NULL
          AND period_end IS NOT NULL
          AND period_start > period_end
    ) THEN
        RAISE EXCEPTION 'preflight failed: statement_summaries contains inverted periods';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM statement_summaries
        WHERE status::text = 'approved'
          AND (
            account_id IS NULL
            OR NULLIF(BTRIM(currency), '') IS NULL
            OR period_start IS NULL
            OR period_end IS NULL
            OR opening_balance IS NULL
            OR closing_balance IS NULL
          )
    ) THEN
        RAISE EXCEPTION 'preflight failed: approved statement_summaries are missing required envelope fields';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM managed_positions
        GROUP BY user_id, account_id, asset_identifier
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'preflight failed: duplicate managed_positions exist for deterministic scope';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM managed_positions
        WHERE cost_basis < 0
           OR (disposal_date IS NOT NULL AND disposal_date < acquisition_date)
    ) THEN
        RAISE EXCEPTION 'preflight failed: managed_positions contains invalid cost or date facts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM report_snapshots
        WHERE start_date IS NOT NULL
          AND start_date > as_of_date
    ) THEN
        RAISE EXCEPTION 'preflight failed: report_snapshots contains inverted date ranges';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM report_snapshots
        WHERE is_latest = true
          AND start_date IS NULL
        GROUP BY user_id, report_type, as_of_date
        HAVING count(*) > 1
    ) OR EXISTS (
        SELECT 1
        FROM report_snapshots
        WHERE is_latest = true
          AND start_date IS NOT NULL
        GROUP BY user_id, report_type, start_date, as_of_date
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'preflight failed: duplicate latest report_snapshots exist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM fx_rates
        WHERE rate <= 0
    ) THEN
        RAISE EXCEPTION 'preflight failed: fx_rates contains non-positive rates';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM stock_prices
        WHERE price <= 0
    ) THEN
        RAISE EXCEPTION 'preflight failed: stock_prices contains non-positive prices';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM stock_prices
        GROUP BY symbol, currency, source, price_date
        HAVING count(*) > 1
    ) THEN
        RAISE EXCEPTION 'preflight failed: stock_prices contain duplicate provider-scoped facts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM investment_transactions
        WHERE gross_amount <= 0
           OR fees < 0
           OR (
                transaction_type::text IN ('buy', 'sell')
                AND (
                    quantity IS NULL
                    OR quantity <= 0
                    OR unit_price IS NULL
                    OR unit_price < 0
                    OR cost_basis IS NULL
                    OR cost_basis < 0
                )
           )
    ) THEN
        RAISE EXCEPTION 'preflight failed: investment_transactions contains invalid amount or trade facts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM investment_lots
        WHERE original_quantity <= 0
           OR remaining_quantity < 0
           OR remaining_quantity > original_quantity
           OR unit_cost < 0
           OR (disposed_date IS NOT NULL AND disposed_date < acquisition_date)
    ) THEN
        RAISE EXCEPTION 'preflight failed: investment_lots contains invalid quantity, cost, or date facts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM dividend_income
        WHERE amount <= 0
    ) THEN
        RAISE EXCEPTION 'preflight failed: dividend_income contains non-positive amounts';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM market_data_override
        WHERE price <= 0
    ) THEN
        RAISE EXCEPTION 'preflight failed: market_data_override contains non-positive prices';
    END IF;
END
$$
"""
    )

    op.create_check_constraint(
        "ck_atomic_transactions_amount_positive",
        "atomic_transactions",
        "amount > 0",
    )
    op.create_check_constraint(
        "ck_atomic_positions_market_value_non_negative",
        "atomic_positions",
        "market_value >= 0",
    )
    op.create_check_constraint(
        "ck_manual_valuation_snapshots_value_positive",
        "manual_valuation_snapshots",
        "value > 0",
    )
    op.create_check_constraint(
        "ck_manual_valuation_snapshots_recurrence_days_positive",
        "manual_valuation_snapshots",
        "recurrence_days IS NULL OR recurrence_days > 0",
    )
    op.create_check_constraint(
        "ck_statement_summaries_period_order",
        "statement_summaries",
        "period_start IS NULL OR period_end IS NULL OR period_start <= period_end",
    )
    op.create_check_constraint(
        "ck_statement_summaries_approved_complete",
        "statement_summaries",
        "status::text != 'approved' OR ("
        "account_id IS NOT NULL AND "
        "NULLIF(BTRIM(currency), '') IS NOT NULL AND "
        "period_start IS NOT NULL AND "
        "period_end IS NOT NULL AND "
        "opening_balance IS NOT NULL AND "
        "closing_balance IS NOT NULL"
        ")",
    )
    op.create_unique_constraint(
        "uq_managed_positions_user_account_asset",
        "managed_positions",
        ["user_id", "account_id", "asset_identifier"],
    )
    op.create_check_constraint(
        "ck_managed_positions_cost_basis_non_negative",
        "managed_positions",
        "cost_basis >= 0",
    )
    op.create_check_constraint(
        "ck_managed_positions_disposal_after_acquisition",
        "managed_positions",
        "disposal_date IS NULL OR disposal_date >= acquisition_date",
    )
    op.create_check_constraint(
        "ck_report_snapshots_date_order",
        "report_snapshots",
        "start_date IS NULL OR start_date <= as_of_date",
    )
    op.create_index(
        "uq_report_snapshots_latest_point_scope",
        "report_snapshots",
        ["user_id", "report_type", "as_of_date"],
        unique=True,
        postgresql_where=sa.text("is_latest = true AND start_date IS NULL"),
    )
    op.create_index(
        "uq_report_snapshots_latest_range_scope",
        "report_snapshots",
        ["user_id", "report_type", "start_date", "as_of_date"],
        unique=True,
        postgresql_where=sa.text("is_latest = true AND start_date IS NOT NULL"),
    )
    op.create_check_constraint("ck_fx_rates_rate_positive", "fx_rates", "rate > 0")
    op.create_check_constraint("ck_stock_prices_price_positive", "stock_prices", "price > 0")
    op.drop_constraint("uq_stock_prices_symbol_date", "stock_prices", type_="unique")
    op.create_unique_constraint(
        "uq_stock_prices_symbol_currency_source_date",
        "stock_prices",
        ["symbol", "currency", "source", "price_date"],
    )
    op.create_check_constraint(
        "ck_investment_transactions_gross_amount_positive",
        "investment_transactions",
        "gross_amount > 0",
    )
    op.create_check_constraint(
        "ck_investment_transactions_fees_non_negative",
        "investment_transactions",
        "fees >= 0",
    )
    op.create_check_constraint(
        "ck_investment_transactions_trade_values_valid",
        "investment_transactions",
        "transaction_type::text NOT IN ('buy', 'sell') OR ("
        "quantity IS NOT NULL AND quantity > 0 AND "
        "unit_price IS NOT NULL AND unit_price >= 0 AND "
        "cost_basis IS NOT NULL AND cost_basis >= 0"
        ")",
    )
    op.create_check_constraint(
        "ck_investment_lots_original_quantity_positive",
        "investment_lots",
        "original_quantity > 0",
    )
    op.create_check_constraint(
        "ck_investment_lots_remaining_quantity_non_negative",
        "investment_lots",
        "remaining_quantity >= 0",
    )
    op.create_check_constraint(
        "ck_investment_lots_remaining_not_above_original",
        "investment_lots",
        "remaining_quantity <= original_quantity",
    )
    op.create_check_constraint(
        "ck_investment_lots_unit_cost_non_negative",
        "investment_lots",
        "unit_cost >= 0",
    )
    op.create_check_constraint(
        "ck_investment_lots_disposed_after_acquisition",
        "investment_lots",
        "disposed_date IS NULL OR disposed_date >= acquisition_date",
    )
    op.create_check_constraint("ck_dividend_income_amount_positive", "dividend_income", "amount > 0")
    op.create_check_constraint("ck_market_data_override_price_positive", "market_data_override", "price > 0")


def downgrade() -> None:
    op.drop_constraint("ck_market_data_override_price_positive", "market_data_override", type_="check")
    op.drop_constraint("ck_dividend_income_amount_positive", "dividend_income", type_="check")
    op.drop_constraint("ck_investment_lots_disposed_after_acquisition", "investment_lots", type_="check")
    op.drop_constraint("ck_investment_lots_unit_cost_non_negative", "investment_lots", type_="check")
    op.drop_constraint("ck_investment_lots_remaining_not_above_original", "investment_lots", type_="check")
    op.drop_constraint("ck_investment_lots_remaining_quantity_non_negative", "investment_lots", type_="check")
    op.drop_constraint("ck_investment_lots_original_quantity_positive", "investment_lots", type_="check")
    op.drop_constraint("ck_investment_transactions_trade_values_valid", "investment_transactions", type_="check")
    op.drop_constraint("ck_investment_transactions_fees_non_negative", "investment_transactions", type_="check")
    op.drop_constraint("ck_investment_transactions_gross_amount_positive", "investment_transactions", type_="check")
    op.drop_constraint("uq_stock_prices_symbol_currency_source_date", "stock_prices", type_="unique")
    op.create_unique_constraint("uq_stock_prices_symbol_date", "stock_prices", ["symbol", "price_date"])
    op.drop_constraint("ck_stock_prices_price_positive", "stock_prices", type_="check")
    op.drop_constraint("ck_fx_rates_rate_positive", "fx_rates", type_="check")
    op.drop_index("uq_report_snapshots_latest_range_scope", table_name="report_snapshots")
    op.drop_index("uq_report_snapshots_latest_point_scope", table_name="report_snapshots")
    op.drop_constraint("ck_report_snapshots_date_order", "report_snapshots", type_="check")
    op.drop_constraint("ck_managed_positions_disposal_after_acquisition", "managed_positions", type_="check")
    op.drop_constraint("ck_managed_positions_cost_basis_non_negative", "managed_positions", type_="check")
    op.drop_constraint("uq_managed_positions_user_account_asset", "managed_positions", type_="unique")
    op.drop_constraint("ck_statement_summaries_approved_complete", "statement_summaries", type_="check")
    op.drop_constraint("ck_statement_summaries_period_order", "statement_summaries", type_="check")
    op.drop_constraint(
        "ck_manual_valuation_snapshots_recurrence_days_positive",
        "manual_valuation_snapshots",
        type_="check",
    )
    op.drop_constraint("ck_manual_valuation_snapshots_value_positive", "manual_valuation_snapshots", type_="check")
    op.drop_constraint("ck_atomic_positions_market_value_non_negative", "atomic_positions", type_="check")
    op.drop_constraint("ck_atomic_transactions_amount_positive", "atomic_transactions", type_="check")
