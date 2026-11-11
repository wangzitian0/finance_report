"""PackageContract for ``audit``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    concepts,
    invs,
    units,
)

CONTRACT = PackageContract(
    name="audit",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    implementations={
        "be": "apps/backend/src/audit",
        "fe": "apps/frontend/src/lib/audit",
    },
    context=ContextScope(
        purpose="Own the shared numeric and executable-assurance language that every financial context can consume.",
        in_scope=[
            "Cross-runtime financial value types and numeric invariants.",
            "Append-only TraceRecord assurance vocabulary and projections.",
            "Promotion and evidence-language policy.",
        ],
        out_of_scope=[
            "Ledger, portfolio, reporting, or other business-domain state ownership.",
            "Cross-domain workflow, transaction, purge, or lifecycle orchestration.",
            "Application delivery, provider configuration, or user-facing policy.",
        ],
    ),
    units=units(
        """
@vo|-|Money Currency ExchangeRate CurrencyBalance CurrencyBalances Ratio Quantity UnitPrice JournalEntrySourceType
@vo|base/promotion.py|InvariantResult PromotionDecision PromotionVerdict
@svc|extension/promotion.py|evaluate_promotion tier_rank
TraceRecord|agg|base/trace.py
@vo|base/trace.py|DeclarativeTracePolicy TraceLineage TraceScope TraceScopeKind TraceTargetClass TraceCausality TraceDecisionOutcome TraceDecisionRef TraceDecisionPolicyRegistry TraceRecordType TraceResult VersionedTraceRef TraceAuthorityProfile
TraceRecordCodec|svc|extension/trace_codec.py
TraceEmitter|svc|extension/trace_emitter.py
TraceJUnitAdapter|svc|extension/trace_adapters.py
TerminalAuditSpec|vo|base/terminal_audit.py
TerminalAuditVerifier|svc|extension/terminal_audit.py
TraceDecisionHead|vo|base/trace_repository.py
TraceConfidenceProjection|proj|data/trace_confidence.py
@svc|extension/trace_decision_projection.py|current_authoritative_trace_decision_projection current_authoritative_trace_decisions shared_current_authority
Unit|vo|-|-|measurement-unit
TraceRecordRepository|repo|base/trace_repository.py|extension/trace_repository.py
"""
    ),
    interface="""
Money Currency InvalidCurrencyError MoneyError balance_check convert
normalize_currency_code to_money canonical_json_digest text_digest ExchangeRate
STATEMENT_SOURCE_TYPES JournalEntrySourceType SourceTypeDowngradeError CurrencyBalance
CurrencyBalances RECONCILIATION_AUTO_ACCEPT_SCORE RECONCILIATION_REVIEW_SCORE
STATEMENT_BALANCE_TOLERANCE InvariantResult PromotionDecision PromotionVerdict
evaluate_promotion tier_rank TraceRecord TraceLineage TraceScope TraceScopeKind
TraceTargetClass TraceCausality TraceDecisionOutcome TraceDecisionRef
TraceDecisionPolicy DeclarativeTracePolicy TraceDecisionPolicyRegistry TraceDecisionHead
TraceRecordType TraceResult VersionedTraceRef TraceAuthorityProfile TraceRecordCodec
TraceEmitter TraceJUnitAdapter TERMINAL_AUDIT_POLICY_VERSION TerminalAuditSpec
TerminalAuditVerifier TraceRecordRepository TraceRecordValidationError
TraceRecordPersistenceError current_authoritative_trace_decision_projection
current_authoritative_trace_decisions shared_current_authority trace_decision_projection
SqlTraceRecordRepository TraceConfidenceProjection Ratio Quantity Unit
UNIT_PRICE_QUANTUM UnitPrice is_user_data_source_type normalize_source_type
promote_entries_source_type promote_entry_source_type source_type_rank
source_type_tiebreak_key statement_source_values
""".split(),
    events=[],
    invariants=invs(
        """
@$t/test_money_conformance.py
money-rounds-half-even|Money quantizes to its currency's minor unit with banker's HALF_EVEN rounding, matching the money conformance vectors.|test_AC2_20_1_conformance_rounding
fx-convert-is-deterministic|Convert applies a typed ExchangeRate and rounds the result deterministically, matching the money conformance vectors.|test_AC2_20_1_conformance_convert
@-
ratio-percent-policy|Ratio percent rendering/application matches its conformance vectors.|$t/test_ratio_conformance.py::test_AC12_9_2_to_percent_matches_standard
@-
quantity-quantizes|Quantity quantizes to 6 dp / ROUND_HALF_UP, matching its conformance vectors.|$t/test_quantity_conformance.py::test_AC12_30_2_quantity_quantize_matches_standard
@-
unit-price-times-quantity-is-money|UnitPrice applied to a same-unit Quantity yields Money, matching the unit_price conformance vectors.|$t/test_unit_price_conformance.py::test_AC12_32_2_unit_price_product_matches_standard
@-
no-float-in-money-narrow-waist|Monetary values never use float in the money narrow waist.|$t/test_money_narrow_waist_guard.py::test_AC2_23_1_money_modules_are_float_free
@-
promotion-gate-invariants-first|Evaluate_promotion rejects on a single failed deterministic invariant regardless of confidence.|$be/audit/promotion/test_promotion_gate.py::test_AC18_13_1_failed_invariant_is_rejected_with_queryable_reason
"""
    ),
    roadmap=acs(
        "audit",
        """
@$be/pricing/test_convert.py
AC-money.22.3||test_convert_amount_wraps_invalid_currency_as_pricing_error
31.2||test_AC12_31_2_convert_amount_routes_through_money_exchange_rate|P1
@$t/test_money_value_type.py
19.1||test_AC2_19_1_money_rejects_float_amount
19.2||test_AC2_19_2_cross_currency_arithmetic_raises
20.1||test_AC2_20_1_convert_rounds_half_even_at_boundary
21.1||test_AC2_21_1_multi_currency_balance_is_not_a_scalar
30.3||test_AC12_30_3_convert_accepts_typed_exchange_rate|P1
@$be/audit/money/test_money_adopt.py|P1
22.1||test_AC2_22_1_statement_summary_typed_currency_balances
22.2||test_AC2_22_2_per_currency_validation_totals_unchanged|P0
22.4||test_AC2_22_4_transfer_leg_exposes_typed_money
@$t/test_composite_ops.py|P1
33.1||test_AC12_33_1_money_predicates_and_sum
33.2||test_AC12_33_2_money_composite_matches_standard
@$t/test_decimal_scalar_ssot.py|P1
36.1||test_AC12_36_1_common_base_packages_share_one_scalar_codec
36.2||test_AC12_36_2_backend_base_packages_share_one_scalar_codec
@$t/test_decimal_boundary_policy.py|P1
31.1||test_AC12_31_1_decimal_boundary_policy_is_mece_and_enforced
31.3||test_AC12_31_3_migrated_hotspots_use_base_packages
@$t/test_base_package_migration_cleanup.py|P1
31.5||test_AC12_31_5_money_fixture_helpers_route_through_base_package
31.6||test_AC12_31_6_confidence_percent_wrapper_is_retired
31.7||test_AC12_31_7_backend_quantity_business_code_uses_value_type
@$t/test_orm_value_type_boundary.py|P1
35.1||test_AC12_35_1_managed_position_exposes_typed_accessors
35.2||test_AC12_35_2_investment_accounting_reads_position_via_accessors
35.3||test_AC12_35_3_portfolio_holdings_value_flows_as_money
35.4||test_AC12_35_4_no_raw_managed_position_money_reads_in_migrated_files
37.1||test_AC12_37_1_journal_line_exposes_money_accessor
37.2||test_AC12_37_2_reconciliation_config_sums_lines_as_money
37.3||test_AC12_37_3_income_statement_fx_is_money_native
38.1||test_AC12_38_1_journal_line_currency_resolves_to_base_ssot
38.2||test_AC12_38_2_balance_core_sums_money
38.3||test_AC12_38_3_annualized_income_reads_line_money
38.4||test_AC12_38_4_no_currency_blind_line_amount_sum
@$be/api/test_app_config_router.py|P1
39.1||test_AC12_39_1_get_returns_env_default_when_unset
39.2||test_AC12_39_2_effective_accessor_falls_back_to_env_default
39.4||test_AC12_39_4_update_persists_and_effective_accessor_returns_new_value
39.5||test_AC12_39_1_invalid_currency_returns_422_and_is_not_persisted
39.6||test_AC_audit_39_6_put_changes_only_the_callers_base_currency
39.7||test_AC_audit_39_7_only_boundary_modules_read_settings_base_currency
39.8||test_AC_audit_39_8_usd_user_reports_and_revaluation_use_user_effective_base_currency
@$be/audit/test_currency_resolution.py
40.1||test_AC12_40_1_attaches_explicit_currency
40.2||test_AC12_40_2_flags_unresolved_instead_of_silent_default
40.3||test_AC12_40_3_reviewer_resolves_currency_with_audit
40.4||test_AC12_40_4_promotion_gate_blocks_unresolved_currency
@$be/audit/promotion/test_promotion_gate.py|P1
41.1||test_AC18_13_1_failed_invariant_is_rejected_with_queryable_reason
41.2||test_AC18_13_2_invariants_pass_but_low_confidence_is_review
41.3||test_AC18_13_3_invariants_pass_and_confidence_met_is_authoritative
41.4||test_AC18_13_4_thresholds_are_centrally_owned_and_consumed_by_services
@$be/infra/test_financial_fact_schema_invariants.py
42.1||test_AC11_18_1_positive_source_fact_constraints
42.2||test_AC11_18_2_statement_summary_approved_completeness_and_period_order
42.3||test_AC11_18_3_portfolio_fact_constraints_and_managed_position_uniqueness
42.4||test_AC11_18_4_report_snapshot_latest_scope_and_date_constraints
42.5||test_AC11_18_5_market_data_constraints_and_stock_price_uniqueness
42.6||test_AC11_18_6_migration_preflights_and_risk_contract_are_declared
@$be/infra/test_audit_anchor_schema_invariants.py
anchor-invariants.1||test_AC18_11_2_atomic_source_links_reject_missing_and_cross_user_documents
anchor-invariants.2||test_AC18_11_3_evidence_edges_reject_cross_user_endpoints
anchor-invariants.3||test_AC18_11_4_account_references_reject_cross_user_accounts
anchor-invariants.4||test_AC18_11_5_unresolved_legacy_source_ids_remain_blockers
anchor-invariants.5||test_AC18_11_6_migration_preflights_and_risk_contract_are_declared
@$be/audit/trace/test_trace_record.py
trace-record.1||test_AC_audit_trace_record_1_schema_and_codec_are_canonical
trace-record.2||test_AC_audit_trace_record_2_authority_profile_reuses_canonical_matrix
@$be/audit/trace/test_trace_causality.py
trace-record.3||test_AC_audit_trace_record_3_decision_causality_fails_closed
trace-record.5||test_AC_audit_trace_record_5_financial_authority_requires_code_parent
@$be/audit/trace/test_trace_repository.py
trace-record.4||test_AC_audit_trace_record_4_repository_is_append_only_and_fail_closed
trace-record.7||test_AC_audit_trace_record_7_decision_head_preserves_absent_current_and_stale_states
@$be/audit/trace/test_trace_repository_batch.py|P1
trace-record.9||test_AC_audit_trace_record_9_batch_rows_equal_the_rows_of_one_append_per_record
trace-record.10||test_AC_audit_trace_record_10_an_append_proves_head_ancestry_and_decision_head_without_a_statement
@$be/audit/trace/test_terminal_audit.py
terminal-trace.1||test_AC_audit_terminal_trace_1_verifies_exact_frozen_graph
terminal-trace.2||test_AC_audit_terminal_trace_2_counterexamples_fail_closed
terminal-trace.3||test_AC_audit_terminal_trace_3_emits_only_canonical_trace_record
terminal-trace.4||test_AC_audit_terminal_trace_4_deletes_audit_owned_shadow_only
terminal-trace.5||test_AC_audit_terminal_trace_5_output_and_diagnostics_are_redaction_safe
@$t/test_money_narrow_waist_guard.py
AC-money.23.1||test_AC2_23_1_guard_flags_injected_float_violation
@$fe/lib/audit/money/money.conformance.test.ts|P2
20.2||AC-audit.20.2 quantize() and convert() share the same rounding vocabulary
@$t/test_ratio_value_type.py|P1
9.1||test_AC12_9_1_ratio_rejects_float_and_is_decimal_backed
@$t/test_ratio_conformance.py|P1
9.2||test_AC12_9_2_to_percent_matches_standard
@$t/test_ratio_adoption.py|P1
9.3||test_AC12_9_3_backend_percentage_call_sites_route_through_ratio
@$t/test_quantity_value_type.py|P1
30.1||test_AC12_30_1_quantity_rejects_float_and_is_decimal_backed
@$t/test_quantity_conformance.py|P1
30.2||test_AC12_30_2_quantity_quantize_matches_standard
@$t/test_quantity_adoption.py|P1
30.4||test_AC12_30_4_frontend_quantity_formatting_is_not_exported_from_money
@$t/test_unit_price_value_type.py|P1
32.1||test_AC12_32_1_unit_price_rejects_float_and_is_decimal_backed
@$t/test_unit_price_conformance.py|P1
32.2||test_AC12_32_2_unit_price_quantize_matches_standard
@$t/test_unit_price_adoption.py|P1
32.3||test_AC12_32_3_investment_accounting_uses_unit_price
@$t/test_composite_ops_adoption.py|P1
33.3||test_AC12_33_3_zero_denominator_branching_routes_through_ratio
@$t/test_audit_kernel_codec_removal.py|P1
31.4||test_AC_audit_31_4_deleted_wire_codecs_do_not_return
@$be/review/test_statement_validation.py|P1
41.5||test_AC18_13_5_balance_chain_decision_routes_through_promotion_gate
@$t/test_audit_mirror_lock.py|P1
43.1||test_AC_audit_43_1_mirrored_modules_are_ast_equal
@$be/audit/test_digest_helpers.py|P1
44.1||test_AC_audit_44_1_canonical_json_digest_keeps_the_old_bytes
@$t/test_digest_single_definition.py|P1
44.2||test_AC_audit_44_2_backend_src_has_no_second_digest_definition
@$be/ledger/test_accounting_equation.py
global-invariant.1||test_accounting_equation_holds_with_all_account_types
@$e2e/test_statement_full_journey.py
global-invariant.2||test_dbs_statement_full_journey
@$be/reporting/test_l1_registry_aggregation.py
global-invariant.3||test_AC20_9_1_framework_balance_sheet_exact_aggregation
@$be/api/test_personal_report_package_contract.py|P1
global-invariant.4||test_AC18_8_4_AC18_8_7_package_traceability_preserves_the_ledger_decision_boundary
@$be/audit/trace/test_trace_decision_projection.py
trace-record.6||test_AC_audit_trace_record_6_current_projection_matches_repository_current_ancestry
@$be/audit/trace/test_shared_current_authority.py|P1
trace-record.8||test_AC_audit_trace_record_8_trace_write_inside_the_block_drops_the_shared_read
@$be/audit/trace/test_trace_confidence.py
trace-projection.1||test_AC_audit_trace_projection_1_uses_fixed_machine_cohort_heads
@$t/test_fk_cascade_ownership.py
deletion-ownership.1||test_AC_audit_deletion_ownership_1_inventory_is_exact_and_valid
""",
    ),
    concepts=concepts(
        """
fk_cascade_ownership|common/audit/data/fk-cascade-ownership.json|Exact ownership and deletion classification for production ForeignKey and ForeignKeyConstraint ondelete=CASCADE declarations, discovered from source and guarded by an independently shrink-only debt baseline.|common/audit/extension/cascade_ownership.py,common/audit/data/fk-cascade-debt-baseline.json,common/audit/readme.md#deletion-ownership,tests/tooling/test_fk_cascade_ownership.py|tests/tooling/test_fk_cascade_ownership.py|platform|baseline|machine_generated
base_packages|common/audit/readme.md#base-packages|The family of value-type narrow-waist base packages (money, ratio, quantity, unit_price) and the canonical structure each follows.|common/audit/ratio/contract/ratio.contract.md,common/audit/ratio/conformance/vectors.json,common/audit/quantity/contract/quantity.contract.md,common/audit/quantity/conformance/vectors.json,apps/backend/src/audit/ratio/__init__.py,apps/backend/src/audit/quantity/__init__.py,apps/frontend/src/lib/audit/ratio/index.ts,apps/frontend/src/lib/audit/quantity/index.ts,docs/project/EPIC-012.foundation-libs.md|tests/tooling/test_ratio_value_type.py,tests/tooling/test_ratio_conformance.py,tests/tooling/test_quantity_value_type.py,tests/tooling/test_quantity_conformance.py|platform|concept|documented_contract
money_value_type|common/audit/money/readme.md#money-type|Money/Currency/ExchangeRate/convert/CurrencyBalances value types in apps/backend/src/audit/money/ make bad money states unrepresentable.|docs/project/EPIC-002.double-entry-core.md,common/audit/money/contract/money.contract.md,common/audit/money/conformance/vectors.json,apps/backend/src/audit/money/__init__.py,apps/frontend/src/lib/audit/money/index.ts|tests/tooling/test_money_value_type.py,tests/tooling/test_money_conformance.py|accounting|concept|documented_contract
source_type_priority|common/audit/readme.md#source-type-trust-hierarchy-provenance|Data trust hierarchy and source_type enum conflict resolution.|common/reconciliation/reconciliation.md,common/extraction/readme.md|-|source|concept
"""
    ),
)
