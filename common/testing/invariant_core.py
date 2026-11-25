"""Single source of truth for the L3 financial and security invariant core."""

from __future__ import annotations

INVARIANT_CORE_PILLARS: dict[str, tuple[str, ...]] = {
    "double_entry_conservation": (
        "apps/backend/tests/ledger/test_accounting_equation.py",
        "apps/backend/tests/ledger/test_entry_and_balance_unit.py",
        "apps/backend/tests/ledger/test_accounting_integration.py",
        "apps/backend/tests/ledger/test_opening_input_guards.py",
        "apps/backend/tests/ledger/test_multicurrency_integrity.py",
        "apps/backend/tests/ledger/test_ledger_authority_boundary.py",
        "apps/backend/tests/accounting/test_validation.py",
        "apps/backend/tests/accounting/test_fx_transfer.py",
        "apps/backend/tests/reporting/test_balance_sheet_invariants.py",
        "apps/backend/tests/reporting/test_equation_diagnostics.py",
    ),
    "decimal_precision": (
        "apps/backend/tests/audit/money/test_money.py",
        "apps/backend/tests/audit/money/test_money_adopt.py",
        "apps/backend/tests/accounting/test_schemas.py",
        "apps/backend/tests/reporting/test_balance_sheet_translation_rounding.py",
        "apps/backend/tests/reporting/test_pure_reporting_calculators.py",
        "apps/backend/tests/portfolio/test_pure_valuation_calculator.py",
        "apps/frontend/src/lib/audit/money/money.conformance.test.ts",
        "apps/frontend/src/lib/audit/money/format.test.ts",
        "apps/frontend/src/lib/audit/money/currency.test.ts",
        "apps/frontend/src/lib/audit/quantity/quantity.conformance.test.ts",
        "apps/frontend/src/lib/audit/ratio/ratio.conformance.test.ts",
        "apps/frontend/src/lib/audit/ratio/format.test.ts",
        "apps/frontend/src/__tests__/types.test.ts",
    ),
    "three_statement_articulation": (
        "apps/backend/tests/reporting/test_bench_articulation_matrix.py",
        "apps/backend/tests/reporting/test_cash_flow_invariants.py",
        "apps/backend/tests/reporting/test_falsifiable_cash_flow.py",
        "apps/backend/tests/reporting/test_net_worth_one_definition.py",
        "apps/backend/tests/reporting/test_cross_endpoint_parity.py",
        "apps/backend/tests/reporting/test_financial_logic_audit.py",
        "apps/backend/tests/reporting/test_cash_event_projection.py",
        "apps/backend/tests/reporting/test_net_income_average_rates.py",
        "apps/backend/tests/reporting/test_report_integrity.py",
    ),
    "ledger_and_fact_schema_invariants": (
        "apps/backend/tests/ledger/test_ledger_schema_invariants.py",
        "apps/backend/tests/infra/test_financial_fact_schema_invariants.py",
        "apps/backend/tests/infra/test_audit_anchor_schema_invariants.py",
        "apps/backend/tests/infra/test_trigger_function_drift.py",
        "apps/backend/tests/infra/test_schema_guardrails.py",
        "apps/backend/tests/infra/test_schema_drift.py",
        "apps/backend/tests/platform/test_outbox_atomicity.py",
    ),
    "multi_tenant_isolation": (
        "apps/backend/tests/integration/test_cross_user_report_isolation_e2e.py",
        "apps/backend/tests/ledger/test_account_parent_ownership.py",
        "apps/backend/tests/portfolio/test_managed_position_ownership.py",
        "apps/backend/tests/pricing/test_manual_valuation_ownership.py",
        "apps/backend/tests/extraction/test_statement_release_ownership.py",
        "apps/backend/tests/identity/test_account_purge.py",
        "apps/backend/tests/api/test_evidence_lineage_router.py",
    ),
    "authz_and_route_boundaries": (
        "apps/backend/tests/identity/test_auth.py",
        "apps/backend/tests/identity/test_auth_edge_cases.py",
        "apps/backend/tests/identity/test_auth_router.py",
        "apps/backend/tests/infra/test_router_contract.py",
        "apps/backend/tests/api/test_router_boundary.py",
        "apps/frontend/src/__tests__/auth.test.ts",
        "apps/frontend/src/__tests__/auth_ssr.test.ts",
        "apps/frontend/src/__tests__/middleware.test.ts",
    ),
    "pii_redaction_and_sanitization": (
        "apps/backend/tests/ai/test_pii_redaction.py",
        "apps/backend/tests/infra/test_snapshot_anonymizer.py",
        "apps/backend/tests/infra/test_logger.py",
    ),
}

ALL_INVARIANT_CORE_FILES: frozenset[str] = frozenset(
    path for paths in INVARIANT_CORE_PILLARS.values() for path in paths
)
BACKEND_INVARIANT_CORE_FILES: frozenset[str] = frozenset(
    path for path in ALL_INVARIANT_CORE_FILES if path.startswith("apps/backend/")
)
BACKEND_INVARIANT_CORE_REL_FILES: frozenset[str] = frozenset(
    path.removeprefix("apps/backend/") for path in BACKEND_INVARIANT_CORE_FILES
)
FRONTEND_INVARIANT_CORE_FILES: frozenset[str] = frozenset(
    path for path in ALL_INVARIANT_CORE_FILES if path.startswith("apps/frontend/")
)
