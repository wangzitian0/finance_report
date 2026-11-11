"""Machine-checkable PackageContract for ``audit``."""

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
@vo|base/trace.py|TraceLineage TraceScope TraceScopeKind TraceTargetClass TraceCausality TraceDecisionOutcome TraceDecisionRef TraceDecisionPolicyRegistry TraceRecordType TraceResult VersionedTraceRef TraceAuthorityProfile
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
STATEMENT_SOURCE_TYPES JournalEntrySourceType SourceTypeDowngradeError
CurrencyBalance CurrencyBalances RECONCILIATION_AUTO_ACCEPT_SCORE
RECONCILIATION_REVIEW_SCORE STATEMENT_BALANCE_TOLERANCE InvariantResult
PromotionDecision PromotionVerdict evaluate_promotion tier_rank TraceRecord
TraceLineage TraceScope TraceScopeKind TraceTargetClass TraceCausality
TraceDecisionOutcome TraceDecisionRef TraceDecisionPolicy
TraceDecisionPolicyRegistry TraceDecisionHead TraceRecordType TraceResult
VersionedTraceRef TraceAuthorityProfile TraceRecordCodec TraceEmitter
TraceJUnitAdapter TERMINAL_AUDIT_POLICY_VERSION TerminalAuditSpec
TerminalAuditVerifier TraceRecordRepository TraceRecordValidationError
TraceRecordPersistenceError current_authoritative_trace_decision_projection
current_authoritative_trace_decisions shared_current_authority
trace_decision_projection SqlTraceRecordRepository TraceConfidenceProjection Ratio
Quantity Unit UNIT_PRICE_QUANTUM UnitPrice is_user_data_source_type
normalize_source_type promote_entries_source_type promote_entry_source_type
source_type_rank source_type_tiebreak_key statement_source_values
""".split(),
    events=[],
    invariants=invs(
        """
@$t/test_money_conformance.py
money-rounds-half-even|Money quantizes to its currency's minor unit with banker's HALF_EVEN rounding, matching the money conformance vectors.|test_AC2_20_1_conformance_rounding
fx-convert-is-deterministic|Convert applies a typed ExchangeRate and rounds the result deterministically, matching the money conformance vectors.|test_AC2_20_1_conformance_convert
@-
ratio-percent-policy|Ratio percent rendering/application matches its conformance vectors.|$t/test_ratio_conformance.py::test_AC12_9_2_to_percent_matches_standard
quantity-quantizes|Quantity quantizes to 6 dp / ROUND_HALF_UP, matching its conformance vectors.|$t/test_quantity_conformance.py::test_AC12_30_2_quantity_quantize_matches_standard
unit-price-times-quantity-is-money|UnitPrice applied to a same-unit Quantity yields Money, matching the unit_price conformance vectors.|$t/test_unit_price_conformance.py::test_AC12_32_2_unit_price_product_matches_standard
no-float-in-money-narrow-waist|Monetary values never use float in the money narrow waist.|$t/test_money_narrow_waist_guard.py::test_AC2_23_1_money_modules_are_float_free
promotion-gate-invariants-first|Evaluate_promotion rejects on a single failed deterministic invariant regardless of confidence.|$be/audit/promotion/test_promotion_gate.py::test_AC18_13_1_failed_invariant_is_rejected_with_queryable_reason
"""
    ),
    roadmap=acs(
        "audit",
        """
@$be/pricing/test_convert.py|P0
AC-money.22.3|Reporting currency conversion goes.|test_convert_amount_wraps_invalid_currency_as_pricing_error
31.2|The FX service preserves the legacy Decimal return contract for DB/API callers but routes cross-currency conversion.|test_AC12_31_2_convert_amount_routes_through_money_exchange_rate|P1
@$t/test_money_value_type.py|P0
19.1|Money rejects float/bool, is Decimal-backed and immutable.|test_AC2_19_1_money_rejects_float_amount
19.2|Same-currency +/-/compare works.|test_AC2_19_2_cross_currency_arithmetic_raises
20.1|Convert applies a Decimal rate into an explicit target currency, rejects float rates, quantizes with banker's rounding at the boundary.|test_AC2_20_1_convert_rounds_half_even_at_boundary
21.1|CurrencyBalances holds one balance per currency with no scalar accessor and round-trips the StatementSummary.currency_balances JSONB shape.|test_AC2_21_1_multi_currency_balance_is_not_a_scalar
30.3|Money conversion uses typed ExchangeRate.|test_AC12_30_3_convert_accepts_typed_exchange_rate|P1
@$be/audit/money/test_money_adopt.py|P1
22.1|StatementSummary.typed_currency_balances reads the per-currency JSONB as a typed CurrencyBalances.|test_AC2_22_1_statement_summary_typed_currency_balances
22.2|Reconciliation per-currency balance check routes.|test_AC2_22_2_per_currency_validation_totals_unchanged|P0
22.4|TransferLeg.money exposes a leg's value as a typed Money.|test_AC2_22_4_transfer_leg_exposes_typed_money
@$t/test_composite_ops.py|P1
33.1|Money exposes is_zero/is_positive/is_negative and a typed Money.sum.|test_AC12_33_1_money_predicates_and_sum
33.2|Cross-language conformance.|test_AC12_33_2_money_composite_matches_standard
@$t/test_decimal_scalar_ssot.py|P1
36.1|The four common/ base-package value types route construction-time Decimal coercion.|test_AC12_36_1_common_base_packages_share_one_scalar_codec
36.2|The backend self-contained mirror routes every base-package coercion.|test_AC12_36_2_backend_base_packages_share_one_scalar_codec
@$t/test_decimal_boundary_policy.py|P1
31.1|The SSOT declares a MECE raw-Decimal boundary policy.|test_AC12_31_1_decimal_boundary_policy_is_mece_and_enforced
31.3|Migrated quantity/reporting/application hotspots use Quantity helpers.|test_AC12_31_3_migrated_hotspots_use_base_packages
@$t/test_base_package_migration_cleanup.py|P1
31.5|Migration cleanup removes duplicated money/percent adapters.|test_AC12_31_5_money_fixture_helpers_route_through_base_package
31.6|Post-merge cleanup retires remaining base-package drift.|test_AC12_31_6_confidence_percent_wrapper_is_retired
31.7|Backend Quantity migration cleanup keeps Quantity objects in service calculations, removes service-local and package-level Decimal-to-Decimal quantity facades.|test_AC12_31_7_backend_quantity_business_code_uses_value_type
@$t/test_orm_value_type_boundary.py|P1
35.1|ManagedPosition exposes typed read accessors at the ORM boundary.|test_AC12_35_1_managed_position_exposes_typed_accessors
35.2|Investment accounting updates position state.|test_AC12_35_2_investment_accounting_reads_position_via_accessors
35.3|The FX boundary is Money-native.|test_AC12_35_3_portfolio_holdings_value_flows_as_money
35.4|Ratchet: the migrated business files read ManagedPosition money only.|test_AC12_35_4_no_raw_managed_position_money_reads_in_migrated_files
37.1|JournalLine exposes a typed money read accessor (Money, currency mirroring the column's configured base-currency default for unflushed rows) at the ORM boundary.|test_AC12_37_1_journal_line_exposes_money_accessor
37.2|The reconciliation entry-amount helpers sum journal lines.|test_AC12_37_2_reconciliation_config_sums_lines_as_money
37.3|The income-statement slow-path FX converts journal lines.|test_AC12_37_3_income_statement_fx_is_money_native
38.1|JournalLine currency resolves to the single settings.base_currency SSOT.|test_AC12_38_1_journal_line_currency_resolves_to_base_ssot
38.2|The journal balance core computes balance currency- checked.|test_AC12_38_2_balance_core_sums_money
38.3|Annualized-income read line.money / sum.|test_AC12_38_3_annualized_income_reads_line_money
38.4|Ratchet: no service/ledger code sums journal-line amounts raw (sum / line.amount for …).|test_AC12_38_4_no_currency_blind_line_amount_sum
@$be/api/test_app_config_router.py|P1
39.1|GET /app-config/base-currency returns the env-default base currency.|test_AC12_39_1_get_returns_env_default_when_unset
39.2|Get_effective_base_currency returns the user own value, else the operator default, else settings.base_currency.|test_AC12_39_2_effective_accessor_falls_back_to_env_default
39.4|PUT /app-config/base-currency persists an ISO-4217-validated override for the caller.|test_AC12_39_4_update_persists_and_effective_accessor_returns_new_value
39.5|PUT /app-config/base-currency rejects a non-ISO-4217 code with HTTP 422 and does not persist it.|test_AC12_39_1_invalid_currency_returns_422_and_is_not_persisted
39.6|PUT /app-config/base-currency writes only the own value of the caller.|test_AC_audit_39_6_put_changes_only_the_callers_base_currency
39.7|Only the config and ORM-default boundary modules read settings.base_currency.|test_AC_audit_39_7_only_boundary_modules_read_settings_base_currency
39.8|A user whose users.base_currency is USD sees USD balance-sheet, income-statement.|test_AC_audit_39_8_usd_user_reports_and_revaluation_use_user_effective_base_currency
@$be/audit/test_currency_resolution.py|P0
40.1|Resolve_ingest_currency attaches the first valid ISO-4217 candidate.|test_AC12_40_1_attaches_explicit_currency
40.2|Resolve_ingest_currency flags the row currency_unresolved with a non-trusted placeholder and never silently defaults to a base currency.|test_AC12_40_2_flags_unresolved_instead_of_silent_default
40.3|Resolve_transaction_currency lets a reviewer set an ISO-4217-validated currency on an unresolved transaction, recording who and.|test_AC12_40_3_reviewer_resolves_currency_with_audit
40.4|Create_entry_from_txn raises CurrencyUnresolvedError and refuses to proceed.|test_AC12_40_4_promotion_gate_blocks_unresolved_currency
@$be/audit/promotion/test_promotion_gate.py|P1
41.1|A failed deterministic invariant rejects the version regardless of confidence, with a queryable reason.|test_AC18_13_1_failed_invariant_is_rejected_with_queryable_reason
41.2|Invariants pass but confidence is below threshold yields a non-authoritative review candidate.|test_AC18_13_2_invariants_pass_but_low_confidence_is_review
41.3|Invariants pass and confidence meets threshold yields authoritative.|test_AC18_13_3_invariants_pass_and_confidence_met_is_authoritative
41.4|The previously-scattered thresholds are named, centrally owned.|test_AC18_13_4_thresholds_are_centrally_owned_and_consumed_by_services
@$be/infra/test_financial_fact_schema_invariants.py|P0
42.1|Positive source fact constraints reject zero/negative transaction amounts and manual-valuation values.|test_AC11_18_1_positive_source_fact_constraints
42.2|Approved statement summaries require account, currency, period.|test_AC11_18_2_statement_summary_approved_completeness_and_period_order
42.3|Managed positions, investment lots.|test_AC11_18_3_portfolio_fact_constraints_and_managed_position_uniqueness
42.4|Latest report snapshots cannot conflict for the same logical report scope and report date ranges cannot be inverted.|test_AC11_18_4_report_snapshot_latest_scope_and_date_constraints
42.5|Market-data facts enforce positive rates/prices and stock prices are unique by symbol, currency, provider source.|test_AC11_18_5_market_data_constraints_and_stock_price_uniqueness
42.6|The constraint migration declares preflight checks and migration-risk classification for existing data compatibility.|test_AC11_18_6_migration_preflights_and_risk_contract_are_declared
@$be/infra/test_audit_anchor_schema_invariants.py|P0
anchor-invariants.1|Atomic transaction and position source-document anchors are represented by normalized link tables that reject missing or cross-user uploaded documents.|test_AC18_11_2_atomic_source_links_reject_missing_and_cross_user_documents
anchor-invariants.2|Evidence Graph edges are tenant-scoped at the database boundary and cannot connect nodes owned by different users.|test_AC18_11_3_evidence_edges_reject_cross_user_endpoints
anchor-invariants.3|Journal lines, approved statement summaries.|test_AC18_11_4_account_references_reject_cross_user_accounts
anchor-invariants.4|Unresolved legacy source UUIDs remain explicit blockers and are never promoted to trusted source anchors.|test_AC18_11_5_unresolved_legacy_source_ids_remain_blockers
anchor-invariants.5|The audit-anchor migration declares preflights, backfills resolvable legacy anchors, preserves unresolved hints.|test_AC18_11_6_migration_preflights_and_risk_contract_are_declared
@$be/audit/trace/test_trace_record.py|P0
trace-record.1|One immutable, versioned, Decimal-safe TraceRecord schema and canonical codec represent OBSERVATION and DECISION.|test_AC_audit_trace_record_1_schema_and_codec_are_canonical
trace-record.2|Every TraceRecord carries a resolved package authority, proof-kind, execution stage.|test_AC_audit_trace_record_2_authority_profile_reuses_canonical_matrix
@$be/audit/trace/test_trace_causality.py|P0
trace-record.3|A DECISION is constructible only.|test_AC_audit_trace_record_3_decision_causality_fails_closed
trace-record.5|An LLM-produced financial observation can become authoritative only.|test_AC_audit_trace_record_5_financial_authority_requires_code_parent
@$be/audit/trace/test_trace_repository.py|P0
trace-record.4|Trace persistence is typed-scope, append-only, content-idempotent.|test_AC_audit_trace_record_4_repository_is_append_only_and_fail_closed
trace-record.7|The TraceRecord repository exposes a typed physical decision head that distinguishes an absent lineage from a head whose complete ancestry is current or stale.|test_AC_audit_trace_record_7_decision_head_preserves_absent_current_and_stale_states
@$be/audit/trace/test_trace_repository_batch.py|P1
trace-record.9|Append_many persists an ordered causal set with the checks of append and the rows of one append per record, with a number of SQL statements that does not grow with the set.|test_AC_audit_trace_record_9_batch_rows_equal_the_rows_of_one_append_per_record
trace-record.10|What an append proves answers later reads of the same unit of work.|test_AC_audit_trace_record_10_an_append_proves_head_ancestry_and_decision_head_without_a_statement
@$be/audit/trace/test_terminal_audit.py|P0|done|exact
terminal-trace.1|Exact selected package and manifest decision refs resolve in one tenant scope.|test_AC_audit_terminal_trace_1_verifies_exact_frozen_graph
terminal-trace.2|Missing, cross-scope, wrong type, result, target, assertion, disconnected.|test_AC_audit_terminal_trace_2_counterexamples_fail_closed
terminal-trace.3|Exact testing executed-proof coordinates are mandatory and successful composition emits only a canonical TraceRecord round-trippable.|test_AC_audit_terminal_trace_3_emits_only_canonical_trace_record
terminal-trace.4|The audit-owned promotion shadow exports, file.|test_AC_audit_terminal_trace_4_deletes_audit_owned_shadow_only
terminal-trace.5|The terminal TraceRecord and first-boundary failure diagnostics are redaction-safe and contain no financial payload, source text, prompt, identity, or secret.|test_AC_audit_terminal_trace_5_output_and_diagnostics_are_redaction_safe
@-|P1
AC-money.23.1|The narrow-waist guard flags a money-shaped float violation on an injected sample and reports none on the real money modules.|$t/test_money_narrow_waist_guard.py::test_AC2_23_1_guard_flags_injected_float_violation|P0
20.2|The frontend money conformance suite's rounding and convert vector tables share one rounding vocabulary.|$fe/lib/audit/money/money.conformance.test.ts::AC-audit.20.2 quantize() and convert() share the same rounding vocabulary|P2
9.1|Ratio rejects float, is Decimal-backed/immutable.|$t/test_ratio_value_type.py::test_AC12_9_1_ratio_rejects_float_and_is_decimal_backed
9.2|Cross-language conformance.|$t/test_ratio_conformance.py::test_AC12_9_2_to_percent_matches_standard
9.3|Ratio adoption: portfolio performance/P&L percentages, allocation shares, reconciliation match rate.|$t/test_ratio_adoption.py::test_AC12_9_3_backend_percentage_call_sites_route_through_ratio
30.1|Quantity rejects float/bool, is Decimal-backed/immutable, quantizes to 6 dp / ROUND_HALF_UP, supports same-unit arithmetic/comparison.|$t/test_quantity_value_type.py::test_AC12_30_1_quantity_rejects_float_and_is_decimal_backed
30.2|Cross-language conformance.|$t/test_quantity_conformance.py::test_AC12_30_2_quantity_quantize_matches_standard
30.4|Quantity adoption: frontend quantity formatting is public only from lib/quantity.|$t/test_quantity_adoption.py::test_AC12_30_4_frontend_quantity_formatting_is_not_exported_from_money
32.1|UnitPrice rejects float/bool, is Decimal-backed/immutable, quantizes to 6 dp / ROUND_HALF_UP, applies to a same-unit Quantity to yield Money.|$t/test_unit_price_value_type.py::test_AC12_32_1_unit_price_rejects_float_and_is_decimal_backed
32.2|Cross-language conformance.|$t/test_unit_price_conformance.py::test_AC12_32_2_unit_price_quantize_matches_standard
32.3|UnitPrice adoption: investment accounting prices buys/sells and lot/avg-cost.|$t/test_unit_price_adoption.py::test_AC12_32_3_investment_accounting_uses_unit_price
33.3|Adoption: zero-denominator ratio branching routes.|$t/test_composite_ops_adoption.py::test_AC12_33_3_zero_denominator_branching_routes_through_ratio
31.4|The Python audit kernel has no wire or DB codec for the value types and no helper.|$t/test_audit_kernel_codec_removal.py::test_AC_audit_31_4_deleted_wire_codecs_do_not_return
41.5|Stage-1 statement balance-chain approval is disposed by the promotion gate, making the gate load-bearing for a real decision.|$be/review/test_statement_validation.py::test_AC18_13_5_balance_chain_decision_routes_through_promotion_gate
43.1|Apps/backend/src/audit is the single Python kernel implementation.|$t/test_audit_mirror_lock.py::test_AC_audit_43_1_mirrored_modules_are_ast_equal
44.1|Canonical_json_digest and text_digest in apps/backend/src/audit/digest.py return the exact bytes of the private copies and inline expressions that they replaced, for the digests that trace records, command digests, result ids, transaction hashes and policy versions store.|$be/audit/test_digest_helpers.py::test_AC_audit_44_1_canonical_json_digest_keeps_the_old_bytes
44.2|Apps/backend/src holds one definition of the canonical-JSON SHA-256 and one of the text SHA-256.|$t/test_digest_single_definition.py::test_AC_audit_44_2_backend_src_has_no_second_digest_definition
global-invariant.1|Global accounting identity.|$be/ledger/test_accounting_equation.py::test_accounting_equation_holds_with_all_account_types|P0
global-invariant.2|The extraction source->fact balance chain reconciles to posted ledger entries.|$e2e/test_statement_full_journey.py::test_dbs_statement_full_journey|P0
global-invariant.3|Report lines reconcile to ledger balances.|$be/reporting/test_l1_registry_aggregation.py::test_AC20_9_1_framework_balance_sheet_exact_aggregation|P0
global-invariant.4|Every displayed posted number retains a ledger DecisionAnchor whose TraceRecord parents preserve the reviewed source decision.|$be/api/test_personal_report_package_contract.py::test_AC18_8_4_AC18_8_7_package_traceability_preserves_the_ledger_decision_boundary
trace-record.6|The public current-authoritative TraceRecord projection returns only financial decisions whose complete parent graph is current.|$be/audit/trace/test_trace_decision_projection.py::test_AC_audit_trace_record_6_current_projection_matches_repository_current_ancestry|P0
trace-record.8|Current_authoritative_trace_decisions returns the current authoritative decisions among the requested ids with one statement.|$be/audit/trace/test_shared_current_authority.py::test_AC_audit_trace_record_8_trace_write_inside_the_block_drops_the_shared_read|:exact
trace-projection.1|Confidence projects from a fixed machine-produced cohort of stable target/assertion lineages and their current version-pinned supersession heads.|$be/audit/trace/test_trace_confidence.py::test_AC_audit_trace_projection_1_uses_fixed_machine_cohort_heads|P0
deletion-ownership.1|Every production SQLAlchemy ForeignKey or ForeignKeyConstraint ondelete=CASCADE site realized on a mapped table is classified exactly once with its source owner, target owner, deletion class.|$t/test_fk_cascade_ownership.py::test_AC_audit_deletion_ownership_1_inventory_is_exact_and_valid|P0
""",
    ),
    concepts=concepts(
        """
fk_cascade_ownership|common/audit/data/fk-cascade-ownership.json|Exact ownership and deletion classification for production ForeignKey and ForeignKeyConstraint ondelete=CASCADE declarations, discovered from source and guarded by an independently shrink-only debt baseline.|common/audit/extension/cascade_ownership.py,common/audit/data/fk-cascade-debt-baseline.json,common/audit/readme.md#deletion-ownership,tests/tooling/test_fk_cascade_ownership.py|tests/tooling/test_fk_cascade_ownership.py|platform|baseline|machine_generated
base_packages|common/audit/readme.md#base-packages|The family of value-type narrow-waist base packages (money, ratio, quantity, unit_price) and the canonical structure each follows (#1167 / AC12.30). Internalized into the audit package (the number-governor that declares the value family).|common/audit/ratio/contract/ratio.contract.md,common/audit/ratio/conformance/vectors.json,common/audit/quantity/contract/quantity.contract.md,common/audit/quantity/conformance/vectors.json,apps/backend/src/audit/ratio/__init__.py,apps/backend/src/audit/quantity/__init__.py,apps/frontend/src/lib/audit/ratio/index.ts,apps/frontend/src/lib/audit/quantity/index.ts,docs/project/EPIC-012.foundation-libs.md|tests/tooling/test_ratio_value_type.py,tests/tooling/test_ratio_conformance.py,tests/tooling/test_quantity_value_type.py,tests/tooling/test_quantity_conformance.py|platform|concept|documented_contract
money_value_type|common/audit/money/readme.md#money-type|Money/Currency/ExchangeRate/convert/CurrencyBalances value types in apps/backend/src/audit/money/ make bad money states unrepresentable (#1167).|docs/project/EPIC-002.double-entry-core.md,common/audit/money/contract/money.contract.md,common/audit/money/conformance/vectors.json,apps/backend/src/audit/money/__init__.py,apps/frontend/src/lib/audit/money/index.ts|tests/tooling/test_money_value_type.py,tests/tooling/test_money_conformance.py|accounting|concept|documented_contract
source_type_priority|common/audit/readme.md#source-type-trust-hierarchy-provenance|Data trust hierarchy and source_type enum conflict resolution.|common/reconciliation/reconciliation.md,common/extraction/readme.md|-|source|concept
"""
    ),
)
