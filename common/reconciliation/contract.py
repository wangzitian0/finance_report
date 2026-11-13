"""PackageContract for ``reconciliation``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    concepts,
    invs,
    rels,
    units,
)

CONTRACT = PackageContract(
    name="reconciliation",
    status="active",
    tier="CODE-ONLY",
    depends_on="audit extraction ledger llm observability platform pricing".split(),
    roles="base extension data".split(),
    implementations={"be": "apps/backend/src/reconciliation", "fe": None},
    context=ContextScope(
        purpose="Own the confidence-scored matching and review lifecycle that links independent source transactions to ledger facts.",
        in_scope=[
            "ReconciliationMatch lifecycle, candidate generation, scoring.",
            "Many-to-one and FX transfer matching, anomaly and consistency diagnostics.",
            "Reconciliation statistics and match-outcome evidence.",
        ],
        out_of_scope=[
            "Source-document and AtomicTransaction ownership.",
            "Journal-entry ownership, double-entry posting.",
            "Shared money, model-provider, telemetry, persistence.",
        ],
    ),
    relationships=rels(
        "reconciliation",
        """
audit|published-language|Uses audit monetary, ratio, provenance.
extraction|projection|Reads extraction-owned AtomicTransaction facts and reviewed dispositions as one side of matching.
ledger|published-language|Uses ledger journal/account language as the independent accounting side of a match.
llm|published-language|Uses the LLM semantic-score facade as an advisory signal.
observability|published-language|Uses published safe logging and reconciliation-outcome telemetry language.
platform|composition|Uses platform persistence mixins.
pricing|published-language|Uses pricing FX-conversion language for cross-currency transfer matching.
""",
    ),
    units=units(
        """
ReconciliationMatch|agg
ReconciliationMatchJournalEntry|ent
@vo|-|ReconciliationStatus TransferLeg
@vo|base/config.py|ReconciliationConfig MatchCandidate
@proj|data/stats.py|ReconciliationStats get_reconciliation_stats ReconciliationStatsProjection
load_reconciliation_config|svc|extension/config.py
execute_matching|svc|extension/matching.py
@svc|extension/transfer_pairs.py|persist_transfer_pairs paired_transfer_entry_ids
@svc|extension/candidate_policy.py|prune_candidates build_many_to_one_groups
@svc|extension/scoring.py|score_amount score_date score_description score_business_logic score_pattern
EventBusMatchOutcome|bus|extension/matching.py
@proj|-|ScoreBreakdownProjection MatchStatusHistoryProjection UnmatchedTransactionsProjection
pair_fx_legs|svc|extension/fx_transfer.py
discover_fx_conversions|svc|extension/fx_transfer_discovery.py
detect_anomalies|svc|extension/anomaly.py
run_all_consistency_checks|svc|extension/consistency_checks.py
ReviewedDispositionCommand|vo|base/reviewed_disposition.py
@svc|extension/reviewed_disposition.py|ReviewedDispositionDependencies submit_reviewed_disposition
ReconciliationRepository|repo|base/repository.py|extension/repository.py
"""
    ),
    interface="""
AmountMismatchError CheckResolutionAction CheckStatus CheckType ConsistencyCheck
ConsistencyCheckNotFoundError DEFAULT_CONFIG DEFAULT_RATE_TOLERANCE DEFAULT_TIME_WINDOW
EntryCreationError FxTransferError InvalidCheckActionError MAX_COMBINATION_CANDIDATES
MatchCandidate MatchNotFoundError MatchingContext NamedTransfer
RECONCILIATION_SEMANTIC_PROMPT ReconciliationConfig ReconciliationError
ReconciliationMatch ReconciliationMatchJournalEntry ReconciliationStats
ReconciliationStatus ReviewedDispositionCommand ReviewedDispositionDependencies
ReviewedDispositionError TransferLeg _candidate_is_better _find_many_to_one_candidates
_find_normal_candidates _find_transfer_candidates _within_combination_tolerance
accept_match accept_pending_matches accepted_transfer_txn_ids apply_reconciliation_feedback auto_accept
batch_accept build_many_to_one_groups build_reconciliation_prompt
classify_internal_transfer count_pending_review_items derive_reconciliation_score_tier
detect_anomalies discover_fx_conversions entry_bank_side_amount entry_total_amount
execute_matching extract_merchant_tokens get_pending_items get_reconciliation_stats
get_stage2_queue has_unresolved_checks is_cross_period is_entry_balanced list_checks
load_reconciliation_config normalize_text pair_fx_legs paired_transfer_entry_ids
post_named_transfer_legs posted_statement_source_ids prune_candidates reject_match
release_transaction_dispositions resolve_check run_all_consistency_checks score_amount
score_business_logic score_date score_description score_group score_single score_pattern
submit_reviewed_disposition supersede_transaction_transfer_legs
sync_reconciliation_matches_journal_entry_links_batch weighted_total
""".split(),
    events=["WorkflowEvent.reconciliation_match_outcome"],
    invariants=invs(
        """
@$t/test_reconciliation_package.py
converges-by-layer|The package converges into base/ + extension/ + data/.|test_reconciliation_converges_by_layer
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_reconciliation_only_all_is_the_published_language
base-layer-pure|Base/ never imports the package's own extension/ or ORM/runtime adapters.|test_reconciliation_base_layer_is_pure
passes-own-governance-gate|Check_package_contract validates reconciliation with no violations.|test_reconciliation_package_contract_gate_passes
"""
    ),
    roadmap=acs(
        "reconciliation",
        """
@$be/reconciliation/test_rejection_recovery.py
rejection-recovery.4||test_historical_source_transactions_are_not_actionable
rejection-recovery.1||test_rejected_match_can_be_reviewed
rejection-recovery.2||test_active_match_blocks_and_rerun_honors_rejection
rejection-recovery.3||test_concurrent_review_after_rejection
@$be/reconciliation/test_config_boundary.py|P0|done|property
config-boundary.2||test_runtime_configuration_file_precedence_and_cache
config-boundary.3||test_entry_readers_preserve_money_and_candidate_semantics
2677.1||test_AC_reconciliation_2677_1_ai_reconciliation_defaults_true_and_reads_settings|P1
@$be/reconciliation/test_reconciliation_engine.py|P1
match.1||test_execute_matching_many_to_one_keeps_same_existing_match|P0
score.2||test_auto_accept_threshold
group-matching.1||test_execute_matching_many_to_one_group|P0
group-matching.3||test_execute_matching_multi_entry_combinations
review-queue.1||test_review_queue_actions_and_entry_creation|P0
anomaly-detection.1||test_detect_anomalies_flags_expected_patterns|P2
source-type-transfer.2||test_transfer_pair_not_double_counted|P0
source-type-transfer.7||test_execute_matching_many_to_one_layer2_sets_atomic_txn_id
recovered-coverage.2||test_execute_matching_three_entry_combination_skips_unbalanced_member
recovered-coverage.3||test_execute_matching_layer2_atomic_match_and_transfer_pair_logging
2548.2||test_AC_reconciliation_2548_2_normal_matching_enforces_entry_exclusivity|:property
2548.4||test_AC_reconciliation_2548_4_detect_anomalies_scopes_currency_and_date_window|:property
@$be/reconciliation/test_reconciliation_matching_unit.py
match.2||test_normal_matching_auto_accept_reconciles_entries
matching-core.3||test_score_amount_tiers
source-type-transfer.3||test_AC4_6_3_candidate_tie_breaker_prefers_higher_source_trust
layer2-dedup.1||test_execute_matching_many_to_one_batch
dwd-cutover.1||test_transfer_out_creates_match
@$be/reconciliation/test_reconciliation_scoring.py|P1
score.1||test_weighted_total_and_balance_helpers
matching-core.1||test_score_amount_branches|P0
matching-core.2||test_score_date_branches|P0
matching-core.4||test_normalize_and_description_scoring
group-matching.2||test_score_group_many_to_one_bonus
source-type-transfer.1||test_amount_tolerance_0_10_boundary|P0
2548.1||test_AC_reconciliation_2548_1_cjk_and_truncated_memo_scoring|:property
@$be/reconciliation/test_reconciliation_stats.py|P1|done|property
stats.1||test_get_reconciliation_stats_dedups_multiple_accepted_matches|P2:exact
2465.1||test_AC_reconciliation_2465_1_statement_posted_rows_count_as_matched
2548.3||test_AC_reconciliation_2548_3_stats_unmatched_aligns_with_unmatched_query
2561.1||test_AC_reconciliation_2561_1_run_after_statement_posting_creates_no_self_match
2826.1||test_AC_reconciliation_2826_1_stage2_scope_excludes_unapproved_stage1_statements|P0
@$be/infra/test_audit_anchor_schema_invariants.py
txn.1|ReconciliationMatch references AtomicTransaction and JournalEntry by id only.|test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries
audit-anchors.1|Reconciliation match journal-entry anchors are represented by a normalized link table that rejects missing or cross-user journal entries.|^
@$be/api/test_reconciliation_router.py|P1
review-queue.3||test_accept_match_success
review-queue.4||test_accept_match_not_found
review-queue.5||test_reject_match_success
review-queue.6||test_reject_match_not_found
review-queue.7||test_reconciliation_stats_success
review-queue.8||test_list_unmatched_success
review-queue.9||test_submit_reviewed_disposition_from_unmatched_success|P0
review-queue.10||test_submit_reviewed_disposition_not_found|P0
review-queue.11||test_unauthenticated_access
review-queue.12||test_user_isolation
review-queue.13||test_legacy_unmatched_entry_routes_are_absent|P0
review-queue.15||test_AC_reconciliation_review_queue_15_filters_unmatched_by_statement|P0
reviewed-disposition.1||test_reviewed_disposition_is_idempotent_and_rejects_account_intent_conflict|P0
reviewed-disposition.3||test_reviewed_disposition_rejects_unmatched_bypasses_without_persisting|P0
reviewed-disposition.4||test_reviewed_disposition_rolls_back_its_decision_when_posting_fails|P0
anomaly-detection.2||test_list_anomalies_not_found
@$be/reconciliation/test_review_queue.py
review-queue.14||test_accept_match_without_reviewed_disposition_requires_entry_context
review-hardening.2||test_AC_review_hardening_2_accept_match_validation_unconditional
@$fe/__tests__/unmatchedBoardComponent.test.tsx
reviewed-disposition.2|The unmatched-transaction UI requires intent, a compatible counter account, required P&L category.|AC-reconciliation.reviewed-disposition.2 / AC-reconciliation.fe-stage2-review.9 submits an explicit reviewed command instead of a raw create action
fe-stage2-review.9|Unmatched board requires an explicit reviewed disposition and exposes no raw create-entry or batch-create action.|^|P2
fe-stage2-review.10|Unmatched board flag and hide actions update local triage state.|AC-reconciliation.fe-stage2-review.10 / AC-reconciliation.fe-stage2-review.25 keeps local flags and hiding separate from an accounting decision|P2
fe-stage2-review.25|Unmatched transaction flag/hide actions are labeled as local-only triage.|^
fe-stage2-review.30||AC-reconciliation.fe-stage2-review.30 scopes the queue and returns to statement review
fe-stage2-review.31||AC-reconciliation.fe-stage2-review.31 requires explicit intent instead of deriving it from direction
first-use.1||AC-reconciliation.first-use.1 creates a missing account and resumes the same explicit review
fe-remainder-reconciliation.1||AC4.11.1 renders unmatched monetary amounts with Decimal-safe currency formatting
@$be/reconciliation/test_signature_surgery.py|P1
reviewed-disposition.5||test_unmatched_posting_has_one_reviewed_writer_boundary|P0
signature-surgery.1||test_public_reconciliation_signatures_are_typed_and_bounded
signature-surgery.2||test_matching_phases_return_created_matches
signature-surgery.3||test_scoring_has_explicit_modes_and_no_hidden_environment_switch
signature-surgery.4||test_reconciliation_errors_and_resolve_actions_are_typed
signature-surgery.5||test_description_similarity_has_one_owner_and_both_consumers_agree
signature-surgery.6||test_transfer_detection_surfaces_processing_currency_conflicts|P0
signature-surgery.7||test_transfer_detection_leaves_foreign_account_candidate_unmatched|P0
@$be/reconciliation/test_performance.py|P1
performance.1||test_batch_1000_transactions_reasonable_time
performance.2||test_month_end_to_month_start_match
@$be/review/test_statement_validation.py|P1
source-type-transfer.5||test_duplicate_guard_distinguishes_by_balance_after
source-type-transfer.6||test_duplicate_guard_flags_when_balance_after_equal_or_absent
@$be/api/test_review_router.py
bank-side-amount.2||test_accept_match_retry_is_idempotent_after_success
bank-side-amount.3||test_create_entry_from_txn_auto_post_rejects_inactive_statement_account
bank-side-amount.4||test_get_stage2_review_queue_with_pending_match|P1
stage2-batch.1||test_batch_approve_matches_blocked_by_unresolved_checks
stage2-batch.2||test_batch_approve_matches_without_entry_requires_review
review-hardening.1||test_AC16_32_3_stage2_queue_returns_all_pending_checks
run-scoped-review.1||test_AC19_11_1_stage2_run_queue_filters_by_run_id
stage2-batch.5||test_batch_approve_matches_reconciles_referenced_entry|P1
conflict-resolution.1||test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts
conflict-resolution.2||test_AC16_34_1_resolve_unblocks_stage1_approval
conflict-resolution.3||test_AC16_34_2_reject_clears_conflict_resolution
@$be/reconciliation/test_reconciliation_audit.py|P1
audit-harness.1||test_AC4_10_1_backend_reconciliation_audit_writes_reports
audit-harness.2||test_AC4_10_2_backend_reconciliation_audit_classifies_failure_modes
@$be/api/test_typed_contract_sweep.py|P2
uuid-path-params.1||test_AC4_12_1_accept_match_malformed_uuid_returns_422
uuid-path-params.2||test_AC4_12_2_reviewed_disposition_malformed_uuid_returns_422
stage2-batch.3||test_AC16_35_1_batch_approve_empty_returns_typed_response|P1
stage2-batch.4||test_AC16_35_2_batch_approve_blocked_returns_409|P1
@$be/accounting/test_validation.py
per-currency-balance.1||test_AC1_per_currency_reconcile_does_not_cross_sum
per-currency-balance.2||test_AC1_per_currency_reconcile_flags_only_offending_currency
per-currency-balance.3||test_AC1_single_currency_degenerate_path_still_passes
per-currency-balance.4||test_AC1_single_currency_degenerate_path_detects_mismatch|P1
per-currency-balance.5||test_AC1_currency_balance_schema_round_trips_decimals|P1
per-currency-balance.6||test_AC1_orphan_currency_transaction_is_surfaced_not_dropped
per-currency-balance.7||test_AC1_duplicate_currency_in_balances_is_rejected|P1
per-currency-balance.8||test_AC4_13_9_bank_currency_balances_emitted_only_when_multi_currency
@$be/accounting/test_fx_transfer.py
fx-transfer.1||test_AC2_pairs_out_ccyA_with_in_ccyB_within_rate_tolerance
fx-transfer.2||test_AC2_implied_rate_outside_tolerance_does_not_pair
fx-transfer.3||test_AC2_non_candidate_legs_do_not_pair
fx-transfer.4||test_AC3_internal_transfer_classified_net_zero
fx-transfer.5||test_AC3_net_worth_unchanged_by_internal_transfer_minus_fee
fx-transfer.6||test_AC4_same_day_round_trip_nets_zero_pnl_minus_fee
fx-transfer.7||test_AC4_revaluation_pnl_routed_through_fx_revaluation_source_type|P1
fx-transfer.8||test_AC2_fx_conversion_model_round_trips_decimals|P1
@$be/reporting/test_fx_ledger_autodiscovery_e2e.py
fx-transfer.9||test_AC3_internal_transfer_excluded_from_income_statement_e2e
fx-transfer.10||test_AC3_internal_transfer_net_income_fee_only_e2e
fx-transfer.13||test_AC2_raw_ledger_internal_transfer_autodiscovered_e2e
fx-transfer.14||test_AC4_same_day_round_trip_nets_zero_pnl_through_live_report
@$be/accounting/test_fx_transfer_discovery.py
fx-transfer.11||test_AC2_discover_pairs_unambiguous_cross_currency_legs_from_ledger
fx-transfer.12||test_AC2_discover_skips_ambiguous_candidate_legs
@$be/reconciliation/test_reconciliation_shift_left.py|P1
reconciliation-engine.1||test_reconciliation_scoring_engine_algorithms|P0
reconciliation-engine.2||test_reconciliation_stats_endpoint
reconciliation-engine.3||test_reconciliation_match_state_and_acceptance
@$be/review/test_consistency_checks.py|P1
consistency-checks.1|Detect_duplicates runs a global scan.|test_global_scan_no_statement_id
consistency-checks.3|Detect_transfer_pairs runs a global scan.|^
consistency-checks.2||test_idempotent_duplicate_detection
consistency-checks.4||test_resolve_check_invalid_action_raises
consistency-checks.5||test_resolve_check_not_found_raises
consistency-checks.6||test_resolve_check_sets_flagged
consistency-checks.7||test_get_pending_filters_by_severity
consistency-checks.8||test_detect_duplicates
consistency-checks.9||test_detect_transfer_pairs
consistency-checks.10||test_AC_consistency_checks_10_list_endpoint_rejects_unbounded_limit
2548.5||test_AC_reconciliation_2548_5_consistency_checks_guard_same_account_refund_and_adjacent_day_spend|:property
@$be/reconciliation/test_transfer_integration.py
dwd-cutover.2||test_mixed_transactions_both_phases_execute
2884.1||test_AC_reconciliation_2884_1_matching_run_pairs_transfer_legs_of_parsed_statements|:property
@$be/review/test_review_conflicts_router.py
conflict-resolution.4||test_review_conflicts_returns_duplicate_and_transfer_candidates
conflict-resolution.5||test_review_conflicts_returns_404_for_missing_statement
@$fe/__tests__/reviewQueuePage.test.tsx|P2
fe-stage2-review.1||AC16.2.4/AC16.17.3 approves selected matches through the batch approval API|P1
fe-stage2-review.3||AC16.17.1 shows an error fallback and retries the Stage 2 queue fetch
fe-stage2-review.4||AC16.2.3/AC16.17.2 disables batch approval while unresolved checks remain
fe-stage2-review.5||AC16.17.3 rejects selected matches through the batch rejection API
fe-stage2-review.6||AC16.17.4 resolves a consistency check from the dialog actions
fe-stage2-review.26||AC16.32.3 requests an expanded consistency-check limit for unblockable queues|P0
fe-stage2-review.28||AC16.36.1 renders the Stage-2 review queue with its heading in the reconciliation tab|P1
fe-stage2-review.29||AC16.36.2 loads the global queue (no run filter) in the reconciliation tab
@$fe/__tests__/reconciliationWorkbenchComponent.test.tsx|P1
fe-stage2-review.7||AC16.20.1 loads stats and pending queue with default selection|P2
fe-stage2-review.8||AC16.20.2 triggers run, batch, accept, and reject APIs|P2
fe-stage2-review.11||AC16.20.6 score distribution renders 0% height for buckets with value 0
fe-tabs.1||AC-reconciliation.fe-tabs.1 shows the tab that the tab query parameter names and links each tab to its URL
fe-tabs.2||AC-reconciliation.fe-tabs.2 opens on Unmatched when an unmatched row exists and on Matches otherwise
@apps/frontend/playwright/mobile-ux.spec.ts
fe-stage2-review.12||AC16.25.1 mobile review routes avoid document horizontal scrolling
fe-stage2-review.13||AC16.25.2 AI suggestions mobile cards expose feedback actions
@$fe/__tests__/stage2ReviewQueueCoverage99.test.tsx
fe-stage2-review.14||AC8.13.76/AC16.26.2 mobile queue renders selectable match cards and batch actions
fe-stage2-review.15||AC16.26.3 mobile run review preserves approval gate and pending match workflow
fe-stage2-review.16||AC16.27.1 keeps mobile pending-match cards in the DOM without matchMedia gating
fe-stage2-review.17||AC8.13.82/AC16.27.3 exposes a fixed desktop pending-match region for responsive UX proofs
fe-stage2-review.19||AC16.23.4/AC8.13.48 persists Stage 2 filters in the URL while approving after filter changes|P2
@$fe/__tests__/statementDetailReview.test.tsx|P2
fe-stage2-review.18|Conflict resolution dialog `<ConflictResolutionDialog />` opens.|AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist
fe-stage2-review.23|Stage 1 conflict dialog loads duplicate and transfer-pair candidates from `GET /api/review/conflicts/{statement_id}`.|^|P0
@$fe/__tests__/reviewRunPage.test.tsx|P2
fe-stage2-review.20|Stage 2 run-level review at `/audit?run_id=<id>` summarizes duplicate, transfer-pair.|AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval
fe-stage2-review.21|Stage 2 run-level page shows unresolved transfer and Processing pending counts, then disables run approval.|^
fe-stage2-review.24|Stage 2 run review page states that it uses the shared Stage 2 queue endpoint.|^|P0
fe-stage2-review.22||AC16.24.3 approves all pending matches through the batch approval API
@$fe/__tests__/attention.test.ts|P1
fe-ia-reconciliation.3||AC22.6.1 folds the open attention sources into one list sorted by ascending confidence
fe-ia-reconciliation.6||AC22.11.2 every item explains why it was flagged
fe-ia-reconciliation.10||AC-reconciliation.fe-ia-reconciliation.10 names the unmatched item by its newest row
@$fe/__tests__/homeActionBanner.test.tsx|P1
fe-ia-reconciliation.4||AC22.6.2 shows the confirmation count of the attention sources and links to the /audit queue
2823.1||AC-reconciliation.2823.1 prioritises pending Stage-1 statement_review over unmatched_transactions in firstItem
@$fe/__tests__/attentionQueue.test.tsx|P1
fe-ia-reconciliation.7|Attention-origin action links preserve `from=attention`.|AC22.6.1 AC22.11.3 AC22.12.4 renders the open attention items with readable reasons and action links
fe-ia-reconciliation.8|Attention-queue reason text uses the normal muted content token, not a lower-opacity muted variant.|^
@$fe/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx|P2
fe-remainder-reconciliation.2||AC18.5.3 — AI Suggestion Review Queue page renders suggestions
fe-remainder-reconciliation.3||AC18.5.4 — feedback POST on accept/reject/edit
@$be/reconciliation/test_reconciliation_hybrid_scoring.py|P1
1803.1||test_score_single_applies_hybrid_ai_scoring
1803.2||test_score_single_flag_off_skips_ai_scoring
1803.3||test_AC_reconciliation_1803_3_execute_matching_uses_per_user_ai_reconciliation_override
@$be/reconciliation/test_economic_disposition.py
economic-disposition.1||test_AC_reconciliation_economic_disposition_1_normal_candidate_precedes_transfer
economic-disposition.2||test_AC_reconciliation_economic_disposition_2_database_rejects_duplicate_active_heads
economic-disposition.3||test_AC_reconciliation_economic_disposition_3_two_sessions_converge
economic-disposition.4||test_AC_reconciliation_economic_disposition_4_transfer_pair_round_trip
economic-disposition.5||test_AC_reconciliation_economic_disposition_5_currency_is_explicit
economic-disposition.6||test_AC_reconciliation_economic_disposition_6_retry_and_phase_permutation_are_idempotent
economic-disposition.7||test_AC_reconciliation_economic_disposition_7_processing_uses_typed_ledger_boundary
@$be/reconciliation/test_named_transfer_legs.py|P0|done|property
named-transfer-legs.1||test_AC_reconciliation_named_transfer_legs_1_an_outgoing_row_posts_dr_processing_cr_bank
named-transfer-legs.2||test_AC_reconciliation_named_transfer_legs_2_a_second_call_posts_nothing_more
named-transfer-legs.3||test_AC_reconciliation_named_transfer_legs_3_two_identical_rows_post_two_legs
named-transfer-legs.4||test_AC_reconciliation_named_transfer_legs_4_the_legs_pair_in_the_next_reconciliation_run|P1
named-transfer-legs.5||test_AC_reconciliation_named_transfer_legs_5_a_long_description_posts_a_leg_with_a_bounded_memo
@$be/reconciliation/test_multi_tenant_stats_budget.py|P1|done|property
2617.1||test_AC_reconciliation_2617_1_stats_do_not_read_matches_of_other_tenants
2617.2||test_AC_reconciliation_2617_2_stats_equal_the_pre_change_values|:exact
@$be/reconciliation/test_candidate_policy.py|P0|done|property
candidate-policy.1||test_live_and_audit_choose_the_same_evidence
@$t/test_reconciliation_config_boundary.py|P0|done|property
config-boundary.1||test_configuration_ownership_is_explicit
@$be/reconciliation/test_reconciliation_router_additional.py|P1
review-queue.2||test_accept_reject_batch_accept
@$be/reconciliation/test_source_type.py|P1
source-type-transfer.4||test_manual_wins_conflict_resolution
@$be/api/test_corrections_router.py|P1
recovered-coverage.1||test_post_create_correction_and_stats
@$be/reconciliation/test_reconciliation_financial_logic.py
bank-side-amount.1||test_AC4_9_1_entry_total_uses_bank_side_line_for_outflow
@$be/reconciliation/test_confidence_tier.py|P1
bank-side-amount.5||test_ac4_9_4_derive_reconciliation_score_tier
@$be/extraction/test_bank_multi_currency_balances.py
per-currency-balance.9||test_AC4_13_9_bank_multi_currency_statement_persists_balances_and_per_currency_governs
@$be/review/test_falsifiable_consistency.py|P1
consistency-checks.11||test_consistency_checks_strictly_partition_by_currency
@$be/reconciliation/test_reconciliation_scoring_helpers.py|P2
candidate-matching.1||test_find_transfer_candidates_returns_pair
@$fe/__tests__/reconciliationEntryPages.test.tsx|P2
fe-stage2-review.2||AC16.16.4 renders workbench in reconciliation page
@$fe/__tests__/ConflictResolutionDialog.test.tsx
fe-stage2-review.27||AC16.34.3 Resolve and Link Pair buttons call onResolve with the matching action
@$fe/__tests__/aiSettingsPage.test.tsx|P1
fe-ia-reconciliation.1||AC22.4.3 links to the AI suggestion review surface so it is not orphaned
@apps/frontend/playwright/epic022-attention-journey.spec.ts|P1
fe-ia-reconciliation.2||${label}: both Stage 1 and Stage 2 attention surface in the upload workflow notices with deep links
@apps/frontend/playwright/attention-surface.spec.ts|P1
fe-ia-reconciliation.5||${label} renders the attention queue ranked by confidence without overflow
@$fe/__tests__/stage2ReviewQueueParts.test.tsx|P1
fe-ia-reconciliation.9||AC22.17.2 PendingMatchesPanel renders mobile + desktop rows and wires selection/batch callbacks
@$be/reconciliation/test_keyword_leg_base_currency.py|P0|done|property
named-transfer-legs.6||test_AC_reconciliation_named_transfer_legs_6_a_foreign_row_posts_no_leg_and_creates_no_account
@$fe/__tests__/TransactionTable.test.tsx|P1
2465.2||AC-reconciliation.2465.2 defaults transaction status to matched when the statement is approved
@$be/reconciliation/test_statement_release.py|P0|done|property
2888.1||test_AC_reconciliation_2888_1_released_leg_breaks_the_pair_for_readers
""",
    ),
    concepts=concepts(
        """
reconciliation_state_machine|common/reconciliation/readme.md#state-machine|pending → auto_accepted / pending_review → accepted / rejected.|common/reconciliation/confirmation-workflow.md,common/reconciliation/reconciliation.md|-|reconciliation|model
reconciliation_thresholds|common/reconciliation/readme.md#thresholds|Score ≥85 auto-accept; 60-84 review; <60 unmatched.|docs/agents/red-lines.md,common/reconciliation/reconciliation.md|-|reconciliation|baseline
"""
    ),
)
