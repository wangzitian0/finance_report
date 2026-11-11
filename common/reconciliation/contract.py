"""Machine-checkable PackageContract for ``reconciliation``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    GovernanceGuarantee,
    GovernanceInitiative,
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
ConsistencyCheckNotFoundError DEFAULT_CONFIG DEFAULT_RATE_TOLERANCE
DEFAULT_TIME_WINDOW EntryCreationError FxTransferError InvalidCheckActionError
MAX_COMBINATION_CANDIDATES MatchCandidate MatchNotFoundError MatchingContext
NamedTransfer RECONCILIATION_SEMANTIC_PROMPT ReconciliationConfig
ReconciliationError ReconciliationMatch ReconciliationMatchJournalEntry
ReconciliationStats ReconciliationStatus ReviewedDispositionCommand
ReviewedDispositionDependencies ReviewedDispositionError TransferLeg
_candidate_is_better _find_many_to_one_candidates _find_normal_candidates
_find_transfer_candidates _within_combination_tolerance accept_match
accepted_transfer_txn_ids apply_reconciliation_feedback auto_accept batch_accept
build_many_to_one_groups build_reconciliation_prompt classify_internal_transfer
count_pending_review_items derive_reconciliation_score_tier detect_anomalies
discover_fx_conversions entry_bank_side_amount entry_total_amount execute_matching
extract_merchant_tokens get_pending_items get_reconciliation_stats get_stage2_queue
has_unresolved_checks is_cross_period is_entry_balanced list_checks
load_reconciliation_config normalize_text pair_fx_legs paired_transfer_entry_ids
post_named_transfer_legs posted_statement_source_ids prune_candidates reject_match
release_transaction_dispositions resolve_check run_all_consistency_checks
score_amount score_business_logic score_date score_description score_group
score_single score_pattern submit_reviewed_disposition
supersede_transaction_transfer_legs sync_reconciliation_match_journal_entry_links
weighted_total
""".split(),
    events="WorkflowEvent.reconciliation_match_outcome".split(),
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
@$be/reconciliation/test_rejection_recovery.py|P0
rejection-recovery.4|Historical retired or superseded source facts cannot reenter unmatched queues, automatic candidates, or direct reviewed posting.|test_historical_source_transactions_are_not_actionable
rejection-recovery.1|Rejected suggestions remain historical evidence.|test_rejected_match_can_be_reviewed
rejection-recovery.2|Active matches cannot be bypassed and background reruns honor rejected suggestions.|test_active_match_blocks_and_rerun_honors_rejection
rejection-recovery.3|Concurrent manual recovery creates at most one source journal command.|test_concurrent_review_after_rejection
@$be/reconciliation/test_config_boundary.py|P0|done|property
config-boundary.2|The runtime loader reads the documented backend configuration file, parses YAML booleans explicitly, preserves defaults/YAML/environment precedence and cache reload semantics.|test_runtime_configuration_file_precedence_and_cache
config-boundary.3|Relocated entry readers preserve currency-filtered Money totals, ledger balance validation.|test_entry_readers_preserve_money_and_candidate_semantics
2677.1|Enable_ai_reconciliation defaults to True in Settings and DEFAULT_CONFIG.|test_AC_reconciliation_2677_1_ai_reconciliation_defaults_true_and_reads_settings|P1
@$be/reconciliation/test_reconciliation_engine.py|P1
match.1|At most one active ReconciliationMatch exists per AtomicTransaction.|test_execute_matching_many_to_one_keeps_same_existing_match|P0
score.2|Scores at/above auto-accept threshold auto-accept.|test_auto_accept_threshold
group-matching.1|Execute_matching groups same-day, same-description bank transactions that sum to one manual journal entry's amount into a many-to-one match and auto-accepts all of them.|test_execute_matching_many_to_one_group|P0
group-matching.3|Execute_matching finds the combination of multiple journal entries whose lines sum to a single transaction's amount, records a multi_entry count in the score breakdown.|test_execute_matching_multi_entry_combinations
review-queue.1|Accept_match, reject_match.|test_review_queue_actions_and_entry_creation|P0
anomaly-detection.1|Detect_anomalies flags LARGE_AMOUNT and FREQUENCY_SPIKE for an outsized transaction against a merchant with recent history.|test_detect_anomalies_flags_expected_patterns|P2
source-type-transfer.2|Execute_matching matches an OUT transfer transaction and its paired IN transaction each to their own generated system Processing entry and auto-accepts both.|test_transfer_pair_not_double_counted|P0
source-type-transfer.7|Execute_matching's layer-2 matching path stamps atomic_txn_id on the resulting ReconciliationMatch.|test_execute_matching_many_to_one_layer2_sets_atomic_txn_id
recovered-coverage.2|Execute_matching's phase-2 combination search skips a 3-entry combination.|test_execute_matching_three_entry_combination_skips_unbalanced_member
recovered-coverage.3|Execute_matching's layer-2 path records an atomic match for a single-entry candidate and supports transfer-pair logging within the same phase.|test_execute_matching_layer2_atomic_match_and_transfer_pair_logging
2548.2|Normal 1:1 matching enforces single-claim journal entry exclusivity within a batch and.|test_AC_reconciliation_2548_2_normal_matching_enforces_entry_exclusivity|:property
2548.4|Detect_anomalies scopes 30-day average and 90-day merchant history queries to the transaction currency, effective statement membership.|test_AC_reconciliation_2548_4_detect_anomalies_scopes_currency_and_date_window|:property
@$be/reconciliation/test_reconciliation_matching_unit.py|P0
match.2|Reconciliation status follows PENDING_REVIEW→ACCEPTED/AUTO_ACCEPTED/REJECTED→SUPERSEDED and posted entries are immutable.|test_normal_matching_auto_accept_reconciles_entries
matching-core.3|Score_amount applies tiered tolerance bands.|test_score_amount_tiers
source-type-transfer.3|_candidate_is_better deterministically prefers the MANUAL-sourced entry over the AUTO_PARSED one, recording a higher source_type_winner_rank than source_type_loser_rank in the breakdown.|test_AC4_6_3_candidate_tie_breaker_prefers_higher_source_trust
layer2-dedup.1|Many-to-one matching works on Layer 2.|test_execute_matching_many_to_one_batch
dwd-cutover.1|Transfer OUT/IN detection resolves the custody account from the DWD conform and creates the Processing entry under the Layer-2 read path.|test_transfer_out_creates_match
@$be/reconciliation/test_reconciliation_scoring.py|P1
score.1|Match score is weighted composite amount/date/description/business/history in [0,100].|test_weighted_total_and_balance_helpers
matching-core.1|Score_amount returns 100 for an exact amount match and graduated lower scores as the absolute and percentage delta from the target amount widens.|test_score_amount_branches|P0
matching-core.2|Score_date returns 100 for a same-day match and graduated lower scores as the day gap widens, with a same-window cross-month bonus over a plain in-month gap of the same size.|test_score_date_branches|P0
matching-core.4|Score_description normalizes text and returns >=95 for near-identical descriptions differing only by case.|test_normalize_and_description_scoring
group-matching.2|Score_group adds a many_to_one_bonus.|test_score_group_many_to_one_bonus
source-type-transfer.1|Score_amount's absolute tolerance boundary holds exactly at 0.10.|test_amount_tolerance_0_10_boundary|P0
2548.1|Normalize_text and extract_merchant_tokens preserve Unicode/CJK merchant text.|test_AC_reconciliation_2548_1_cjk_and_truncated_memo_scoring|:property
@$be/reconciliation/test_reconciliation_stats.py|P1|done|property
stats.1|Stats projection match_rate is consistent with active accepted/auto-accepted match states.|test_get_reconciliation_stats_dedups_multiple_accepted_matches|P2:-
2465.1|A transaction with a live posted journal entry from its own statement counts as matched in get_reconciliation_stats, using the same posted_statement_source_ids query as the unmatched list.|test_AC_reconciliation_2465_1_statement_posted_rows_count_as_matched
2548.3|Get_reconciliation_stats applies effective_statement_transaction_filter, ignores superseded matches.|test_AC_reconciliation_2548_3_stats_unmatched_aligns_with_unmatched_query
2561.1|List_pending_transactions excludes a statement transaction that its own statement already posted.|test_AC_reconciliation_2561_1_run_after_statement_posting_creates_no_self_match
2826.1|Effective_statement_transaction_filter restricts statement-backed transactions to APPROVED statements.|test_AC_reconciliation_2826_1_stage2_scope_excludes_unapproved_stage1_statements|P0
@$be/infra/test_audit_anchor_schema_invariants.py|P0
txn.1|ReconciliationMatch references AtomicTransaction and JournalEntry by id only.|test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries
audit-anchors.1|Reconciliation match journal-entry anchors are represented by a normalized link table that rejects missing or cross-user journal entries.|test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries
@$be/api/test_reconciliation_router.py|P1
review-queue.3|POST /reconciliation/matches/{id}/accept returns 200 with the match status set to ACCEPTED.|test_accept_match_success
review-queue.4|POST /reconciliation/matches/{id}/accept for a non-existent match id returns 404 with 'Match' in the error detail.|test_accept_match_not_found
review-queue.5|POST /reconciliation/matches/{id}/reject returns 200 with the match status set to REJECTED.|test_reject_match_success
review-queue.6|POST /reconciliation/matches/{id}/reject for a non-existent match id returns 404 with 'Match' in the error detail.|test_reject_match_not_found
review-queue.7|GET /reconciliation/stats returns 200 with a stats payload containing total/matched/unmatched counts, match_rate.|test_reconciliation_stats_success
review-queue.8|GET /reconciliation/unmatched returns 200 with a paginated items/total payload listing unmatched transactions.|test_list_unmatched_success
review-queue.9|POST /reconciliation/unmatched/{txn_id}/reviewed-disposition creates one source-anchored journal entry only.|test_submit_reviewed_disposition_from_unmatched_success|P0
review-queue.10|POST /reconciliation/unmatched/{txn_id}/reviewed-disposition for a non-existent transaction id returns 404 with 'Transaction' in the error detail.|test_submit_reviewed_disposition_not_found|P0
review-queue.11|Reconciliation endpoints reject unauthenticated requests with 401.|test_unauthenticated_access
review-queue.12|GET /reconciliation/unmatched scopes results to the authenticated user and never returns another user's transactions.|test_user_isolation
review-queue.13|The legacy unparameterized create-entry and batch-create endpoints are absent.|test_legacy_unmatched_entry_routes_are_absent|P0
review-queue.15|GET /reconciliation/unmatched accepts an optional statement_id and then returns only unresolved transactions anchored to that user-owned statement.|test_AC_reconciliation_review_queue_15_filters_unmatched_by_statement|P0
reviewed-disposition.1|A reviewed-disposition command is idempotent only for the same immutable normalized intent, counter-account, applicable category.|test_reviewed_disposition_is_idempotent_and_rejects_account_intent_conflict|P0
reviewed-disposition.3|A reviewed-disposition command rejects an unmatched transfer or a transaction that already has a current non-rejected reconciliation match.|test_reviewed_disposition_rejects_unmatched_bypasses_without_persisting|P0
reviewed-disposition.4|The injected TraceEmitter appends the manual observation and CODE-ONLY disposition/invariant TraceRecord causal set in the same caller-owned transaction as posting.|test_reviewed_disposition_rolls_back_its_decision_when_posting_fails|P0
anomaly-detection.2|GET /reconciliation/transactions/{txn_id}/anomalies for a non-existent transaction id returns 404 with 'Transaction' in the error detail.|test_list_anomalies_not_found
@$be/reconciliation/test_review_queue.py|P0
review-queue.14|Accept_match reconciles only a pre-existing linked source entry.|test_accept_match_without_reviewed_disposition_requires_entry_context
review-hardening.2|`accept_match` validates journal-entry amounts against the transaction unconditionally.|test_AC_review_hardening_2_accept_match_validation_unconditional
@$fe/__tests__/unmatchedBoardComponent.test.tsx|P0
reviewed-disposition.2|The unmatched-transaction UI requires intent, a compatible counter account, required P&L category.|AC-reconciliation.reviewed-disposition.2 / AC-reconciliation.fe-stage2-review.9 submits an explicit reviewed command instead of a raw create action
fe-stage2-review.9|Unmatched board requires an explicit reviewed disposition and exposes no raw create-entry or batch-create action.|AC-reconciliation.reviewed-disposition.2 / AC-reconciliation.fe-stage2-review.9 submits an explicit reviewed command instead of a raw create action|P2
fe-stage2-review.10|Unmatched board flag and hide actions update local triage state.|AC-reconciliation.fe-stage2-review.10 / AC-reconciliation.fe-stage2-review.25 keeps local flags and hiding separate from an accounting decision|P2
fe-stage2-review.25|Unmatched transaction flag/hide actions are labeled as local-only triage.|AC-reconciliation.fe-stage2-review.10 / AC-reconciliation.fe-stage2-review.25 keeps local flags and hiding separate from an accounting decision
fe-stage2-review.30|The unmatched board honors a statement_id scope, preserves the statement-review return target.|AC-reconciliation.fe-stage2-review.30 scopes the queue and returns to statement review
fe-stage2-review.31|The unmatched board initializes every reviewed disposition as unknown regardless of cash direction and requires the reviewer to select economic intent explicitly.|AC-reconciliation.fe-stage2-review.31 requires explicit intent instead of deriving it from direction
first-use.1|Missing counter-account setup reuses the ledger account form.|AC-reconciliation.first-use.1 creates a missing account and resumes the same explicit review
fe-remainder-reconciliation.1|The unmatched transaction board models unmatched amounts as shared `MoneyValue` payloads and renders queue/detail/created-entry amounts.|AC4.11.1 renders unmatched monetary amounts with Decimal-safe currency formatting
@$be/reconciliation/test_signature_surgery.py|P1
reviewed-disposition.5|A capability-level structural lock enumerates reconciliation posting and match side effects.|test_unmatched_posting_has_one_reviewed_writer_boundary|P0
signature-surgery.1|Public reconciliation extension functions have fully annotated signatures and no more than eight parameters.|test_public_reconciliation_signatures_are_typed_and_bounded
signature-surgery.2|Execute_matching drives the ReconciliationRepository port and each phase returns its created matches.|test_matching_phases_return_created_matches
signature-surgery.3|Normal single-/multi-entry scoring and many-to-one group scoring use distinct typed entry points.|test_scoring_has_explicit_modes_and_no_hidden_environment_switch
signature-surgery.4|Reconciliation failures use typed domain errors, router status mapping does not inspect exception text.|test_reconciliation_errors_and_resolve_actions_are_typed
signature-surgery.5|Reconciliation owns the sole SequenceMatcher description-similarity kernel.|test_description_similarity_has_one_owner_and_both_consumers_agree
signature-surgery.6|Transfer detection propagates processing-account currency conflicts.|test_transfer_detection_surfaces_processing_currency_conflicts|P0
signature-surgery.7|Transfer detection leaves a foreign-account candidate unmatched.|test_transfer_detection_leaves_foreign_account_candidate_unmatched|P0
@$be/reconciliation/test_performance.py|P1
performance.1|Execute_matching processes 100 transactions against 20 candidate entries in under 5 seconds.|test_batch_1000_transactions_reasonable_time
performance.2|Score_single still scores a transaction dated one day.|test_month_end_to_month_start_match
@$be/review/test_statement_validation.py|P1
source-type-transfer.5|The Stage-1 duplicate guard does NOT flag two transactions identical in date/description/amount/direction as duplicate candidates.|test_duplicate_guard_distinguishes_by_balance_after
source-type-transfer.6|The Stage-1 duplicate guard still flags two transactions identical in date/description/amount/direction as duplicate candidates.|test_duplicate_guard_flags_when_balance_after_equal_or_absent
@$be/api/test_review_router.py|P0
bank-side-amount.2|Retrying accept_match_service on an already-ACCEPTED match returns the same version and the same journal_entry_ids.|test_accept_match_retry_is_idempotent_after_success
bank-side-amount.3|Create_entry_from_txn with auto_post=True raises ValueError and creates no journal entry.|test_create_entry_from_txn_auto_post_rejects_inactive_statement_account
bank-side-amount.4|Get_stage2_review_queue returns a pending PENDING_REVIEW match with a confidence_tier of MEDIUM derived from its match_score.|test_get_stage2_review_queue_with_pending_match|P1
stage2-batch.1|A Stage-2 pending_review -> accepted transition is blocked.|test_batch_approve_matches_blocked_by_unresolved_checks
stage2-batch.2|A Stage-2 batch approve may reconcile an existing source entry but cannot create a journal entry for a pending match.|test_batch_approve_matches_without_entry_requires_review
review-hardening.1|Stage-2 review check lists request the full unresolved blocker set needed to unblock batch approval.|test_AC16_32_3_stage2_queue_returns_all_pending_checks
run-scoped-review.1|/audit?run_id={runId} uses a run-scoped Stage-2 queue and batch-approval API.|test_AC19_11_1_stage2_run_queue_filters_by_run_id
stage2-batch.5|Stage 2 batch approval reconciles a match against an existing referenced journal entry.|test_batch_approve_matches_reconciles_referenced_entry|P1
conflict-resolution.1|Stage 1 approval and edit-approval are blocked.|test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts
conflict-resolution.2|POST /api/review/conflicts/{statement_id}/resolve records the reviewer's resolution.|test_AC16_34_1_resolve_unblocks_stage1_approval
conflict-resolution.3|A reject/reparse clears a prior conflict resolution.|test_AC16_34_2_reject_clears_conflict_resolution
@$t/test_reconciliation_audit.py|P1
audit-harness.1|The reconciliation audit harness's build_report/write_report emit a JSON report and a companion Markdown report.|test_AC4_10_1_reconciliation_audit_report_schema_and_outputs
audit-harness.2|The reconciliation audit harness's diagnostics report an intentionally-seeded false-positive scenario, identifying it by scenario id in the audit output.|test_AC4_10_2_reconciliation_audit_reports_intentional_false_positive
@$be/api/test_typed_contract_sweep.py|P2
uuid-path-params.1|POST /reconciliation/matches/{match_id}/accept with a non-UUID match_id returns 422 at the FastAPI path-param boundary.|test_AC4_12_1_accept_match_malformed_uuid_returns_422
uuid-path-params.2|POST /reconciliation/unmatched/{txn_id}/reviewed-disposition with a non-UUID txn_id returns 422 at the FastAPI path-param boundary.|test_AC4_12_2_reviewed_disposition_malformed_uuid_returns_422
stage2-batch.3|An empty batch approve returns the typed counters with no success field.|test_AC16_35_1_batch_approve_empty_returns_typed_response|P1
stage2-batch.4|Unresolved consistency checks block batch approve with a 409 structured error.|test_AC16_35_2_batch_approve_blocked_returns_409|P1
@$be/accounting/test_validation.py|P0
per-currency-balance.1|Validate_balance_per_currency reconciles a multi-currency statement's SGD and USD buckets independently and never produces a cross-currency summed total.|test_AC1_per_currency_reconcile_does_not_cross_sum
per-currency-balance.2|Validate_balance_per_currency flags only the offending currency as invalid.|test_AC1_per_currency_reconcile_flags_only_offending_currency
per-currency-balance.3|Validate_balance_per_currency falls back to a single synthetic currency bucket and reproduces the legacy scalar balance check.|test_AC1_single_currency_degenerate_path_still_passes
per-currency-balance.4|The degenerate single-currency validation path still detects and flags a balance mismatch.|test_AC1_single_currency_degenerate_path_detects_mismatch|P1
per-currency-balance.5|The CurrencyBalance schema normalizes a lower-case currency code to upper-case ISO and round-trips opening/closing as Decimal.|test_AC1_currency_balance_schema_round_trips_decimals|P1
per-currency-balance.6|Validate_balance_per_currency surfaces a transaction in a currency with no declared balance bucket as its own per-currency result flagged declared_balance=False and forces the overall result invalid.|test_AC1_orphan_currency_transaction_is_surfaced_not_dropped
per-currency-balance.7|Validate_balance_per_currency rejects a balances array containing two buckets for the same currency.|test_AC1_duplicate_currency_in_balances_is_rejected|P1
per-currency-balance.8|Bank_currency_balances returns the per-currency array only.|test_AC4_13_9_bank_currency_balances_emitted_only_when_multi_currency
@$be/accounting/test_fx_transfer.py|P0
fx-transfer.1|Pair_fx_legs pairs an out-leg in one currency with an in-leg in another for the same owner.|test_AC2_pairs_out_ccyA_with_in_ccyB_within_rate_tolerance
fx-transfer.2|Pair_fx_legs returns None.|test_AC2_implied_rate_outside_tolerance_does_not_pair
fx-transfer.3|Pair_fx_legs refuses to pair legs that fall outside the configured time window, share the same direction, or belong to different owners.|test_AC2_non_candidate_legs_do_not_pair
fx-transfer.4|Classify_internal_transfer marks a paired FX transfer as an internal transfer with zero income_amount and zero expense_amount.|test_AC3_internal_transfer_classified_net_zero
fx-transfer.5|Classify_internal_transfer's net_worth_delta is exactly zero for a fee-less paired transfer and exactly -fee.|test_AC3_net_worth_unchanged_by_internal_transfer_minus_fee
fx-transfer.6|Round_trip_realized_pnl returns exactly 0.00 for a same-day round trip at an unchanged rate with no fee.|test_AC4_same_day_round_trip_nets_zero_pnl_minus_fee
fx-transfer.7|Round_trip_realized_pnl yields zero P&L for an unchanged-rate conversion event.|test_AC4_revaluation_pnl_routed_through_fx_revaluation_source_type|P1
fx-transfer.8|Build_fx_conversion constructs an FxConversion record from a paired leg whose amount_from/amount_to round-trip as Decimal with normalized ISO currency codes.|test_AC2_fx_conversion_model_round_trips_decimals|P1
@$be/reporting/test_fx_ledger_autodiscovery_e2e.py|P0
fx-transfer.9|Generate_income_statement excludes a recorded internal transfer's income/expense legs entirely and includes only the transfer's fee as an expense line.|test_AC3_internal_transfer_excluded_from_income_statement_e2e
fx-transfer.10|Generate_balance_sheet's cumulative net_income excludes a recorded internal transfer's legs and reflects only the fee, matching the income statement's net contribution.|test_AC3_internal_transfer_net_income_fee_only_e2e
fx-transfer.13|Generate_income_statement and generate_balance_sheet, with no recorded fx_conversions row at all, still auto-discover a cross-currency transfer from raw ledger lines and exclude it end to end.|test_AC2_raw_ledger_internal_transfer_autodiscovered_e2e
fx-transfer.14|Auto-discovery nets both conversions.|test_AC4_same_day_round_trip_nets_zero_pnl_through_live_report
@$be/accounting/test_fx_transfer_discovery.py|P0
fx-transfer.11|Discover_fx_conversions auto-discovers an unambiguous out-leg/in-leg cross-currency conversion directly from raw asset-account journal lines, recovering the correct accounts, amounts, currencies.|test_AC2_discover_pairs_unambiguous_cross_currency_legs_from_ledger
fx-transfer.12|Discover_fx_conversions refuses to pair an out-leg that matches two candidate in-legs on the same day.|test_AC2_discover_skips_ambiguous_candidate_legs
@$be/reconciliation/test_reconciliation_shift_left.py|P1
reconciliation-engine.1|The reconciliation engine runs end to end through the API.|test_reconciliation_scoring_engine_algorithms|P0
reconciliation-engine.2|The reconciliation stats endpoint returns run statistics.|test_reconciliation_stats_endpoint
reconciliation-engine.3|A reconciliation match can be accepted through the API.|test_reconciliation_match_state_and_acceptance
@$be/review/test_consistency_checks.py|P1
consistency-checks.1|Detect_duplicates runs a global scan.|test_global_scan_no_statement_id
consistency-checks.2|Detect_duplicates is idempotent.|test_idempotent_duplicate_detection
consistency-checks.3|Detect_transfer_pairs runs a global scan.|test_global_scan_no_statement_id
consistency-checks.4|Resolve_check raises ValueError on an invalid resolution action.|test_resolve_check_invalid_action_raises
consistency-checks.5|Resolve_check raises ValueError when the check is not found.|test_resolve_check_not_found_raises
consistency-checks.6|Resolve_check sets FLAGGED status when action=flag.|test_resolve_check_sets_flagged
consistency-checks.7|List_checks filters pending results by severity.|test_get_pending_filters_by_severity
consistency-checks.8|Deduplication detection accuracy is >= 95% on the consistency-check corpus.|test_detect_duplicates
consistency-checks.9|Transfer-pair detection accuracy is >= 90% on the consistency-check corpus.|test_detect_transfer_pairs
consistency-checks.10|`GET /statements/consistency-checks/list` enforces a bounded page size.|test_AC_consistency_checks_10_list_endpoint_rejects_unbounded_limit
2548.5|Detect_duplicates requires same-day and compatible account scope.|test_AC_reconciliation_2548_5_consistency_checks_guard_same_account_refund_and_adjacent_day_spend|:property
@$be/reconciliation/test_transfer_integration.py|P0
dwd-cutover.2|Mixed transfer and normal transactions both reconcile correctly under the Layer-2 read path.|test_mixed_transactions_both_phases_execute
2884.1|List_pending_transactions reads current rows of every statement that is not RETIRED or REJECTED.|test_AC_reconciliation_2884_1_matching_run_pairs_transfer_legs_of_parsed_statements|:property
@$be/review/test_review_conflicts_router.py|P0
conflict-resolution.4|GET /api/review/conflicts/{statement_id} returns {duplicates.|test_review_conflicts_returns_duplicate_and_transfer_candidates
conflict-resolution.5|The conflicts endpoint returns 404.|test_review_conflicts_returns_404_for_missing_statement
@$fe/__tests__/reviewQueuePage.test.tsx|P2
fe-stage2-review.1|Stage 2 UI supports batch operations.|AC16.2.4/AC16.17.3 approves selected matches through the batch approval API|P1
fe-stage2-review.3|Stage 2 review queue shows failure fallback and supports retry.|AC16.17.1 shows an error fallback and retries the Stage 2 queue fetch
fe-stage2-review.4|Stage 2 review queue indicates unresolved checks and disables batch approval.|AC16.2.3/AC16.17.2 disables batch approval while unresolved checks remain
fe-stage2-review.5|Stage 2 review queue rejects selected matches.|AC16.17.3 rejects selected matches through the batch rejection API
fe-stage2-review.6|Stage 2 review queue resolves consistency checks.|AC16.17.4 resolves a consistency check from the dialog actions
fe-stage2-review.26|Stage 2 review check lists request the full unresolved blocker set needed to unblock batch approval.|AC16.32.3 requests an expanded consistency-check limit for unblockable queues|P0
fe-stage2-review.28|The review queue tab of `/reconciliation` renders the Stage-2 review queue with its heading.|AC16.36.1 renders the Stage-2 review queue with its heading in the reconciliation tab|P1
fe-stage2-review.29|The review queue tab loads the global queue (no run filter).|AC16.36.2 loads the global queue (no run filter) in the reconciliation tab
@$fe/__tests__/reconciliationWorkbenchComponent.test.tsx|P1
fe-stage2-review.7|Reconciliation workbench loads stats and pending queue with default selection.|AC16.20.1 loads stats and pending queue with default selection|P2
fe-stage2-review.8|Reconciliation workbench triggers run, accept, reject.|AC16.20.2 triggers run, batch, accept, and reject APIs|P2
fe-stage2-review.11|Score distribution renders 0% height for buckets with value 0.|AC16.20.6 score distribution renders 0% height for buckets with value 0
fe-tabs.1|The `/reconciliation` page shows the tab that the query parameter `tab` names.|AC-reconciliation.fe-tabs.1 shows the tab that the tab query parameter names and links each tab to its URL
fe-tabs.2|With no `tab` value or an unknown value, `/reconciliation` waits for the statistics, then opens on Unmatched.|AC-reconciliation.fe-tabs.2 opens on Unmatched when an unmatched row exists and on Matches otherwise
@apps/frontend/playwright/mobile-ux.spec.ts|P0
fe-stage2-review.12|Review, journal details, and mobile navigation surfaces do not create document-level horizontal scrolling at phone widths.|AC16.25.1 mobile review routes avoid document horizontal scrolling
fe-stage2-review.13|AI suggestion review queue exposes accept, reject, correction.|AC16.25.2 AI suggestions mobile cards expose feedback actions
@$fe/__tests__/stage2ReviewQueueCoverage99.test.tsx|P0
fe-stage2-review.14|Stage 2 pending matches use selectable mobile cards with direct reject and approve selected actions visible.|AC8.13.76/AC16.26.2 mobile queue renders selectable match cards and batch actions
fe-stage2-review.15|Stage 2 run review keeps the run approval gate and pending match workflow usable at phone widths.|AC16.26.3 mobile run review preserves approval gate and pending match workflow
fe-stage2-review.16|Stage 1 and Stage 2 mobile review lists render.|AC16.27.1 keeps mobile pending-match cards in the DOM without matchMedia gating
fe-stage2-review.17|Stage 2 desktop review keeps pending match rows readable at 1440px with the sidebar visible.|AC8.13.82/AC16.27.3 exposes a fixed desktop pending-match region for responsive UX proofs
fe-stage2-review.19|Stage 2 listing exposes severity filter, check-type filter.|AC16.23.4/AC8.13.48 persists Stage 2 filters in the URL while approving after filter changes|P2
@$fe/__tests__/statementDetailReview.test.tsx|P2
fe-stage2-review.18|Conflict resolution dialog `<ConflictResolutionDialog />` opens.|AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist
fe-stage2-review.23|Stage 1 conflict dialog loads duplicate and transfer-pair candidates from `GET /api/review/conflicts/{statement_id}`.|AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist|P0
@$fe/__tests__/reviewRunPage.test.tsx|P2
fe-stage2-review.20|Stage 2 run-level review at `/audit?run_id=<id>` summarizes duplicate, transfer-pair.|AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval
fe-stage2-review.21|Stage 2 run-level page shows unresolved transfer and Processing pending counts, then disables run approval.|AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval
fe-stage2-review.22|Stage 2 run-level approval submits all pending matches.|AC16.24.3 approves all pending matches through the batch approval API
fe-stage2-review.24|Stage 2 run review page states that it uses the shared Stage 2 queue endpoint.|AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval|P0
@$fe/__tests__/attention.test.ts|P1
fe-ia-reconciliation.3|The Needs Confirmation queue on `/audit` folds the open attention sources into a single list sorted by ascending confidence, each row deep-linking to its action surface, with an all-clear empty state.|AC22.6.1 folds the open attention sources into one list sorted by ascending confidence
fe-ia-reconciliation.6|Each attention-queue item surfaces a plain-language reason it was flagged.|AC22.11.2 every item explains why it was flagged
fe-ia-reconciliation.10|The unmatched item of the confidence queue takes the description of the newest unmatched row as its title, with the count of the other rows.|AC-reconciliation.fe-ia-reconciliation.10 names the unmatched item by its newest row
@$fe/__tests__/homeActionBanner.test.tsx|P1
fe-ia-reconciliation.4|Home shows one action banner from the same attention model.|AC22.6.2 shows the confirmation count of the attention sources and links to the /audit queue
2823.1|PickHomeAction selects a pending Stage-1 statement_review item ahead of Stage-2 unmatched_transactions for the Home action banner firstItem.|AC-reconciliation.2823.1 prioritises pending Stage-1 statement_review over unmatched_transactions in firstItem
@$fe/__tests__/attentionQueue.test.tsx|P1
fe-ia-reconciliation.7|Attention-origin action links preserve `from=attention`.|AC22.6.1 AC22.11.3 AC22.12.4 renders the open attention items with readable reasons and action links
fe-ia-reconciliation.8|Attention-queue reason text uses the normal muted content token, not a lower-opacity muted variant.|AC22.6.1 AC22.11.3 AC22.12.4 renders the open attention items with readable reasons and action links
@$fe/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx|P2
fe-remainder-reconciliation.2|The AI suggestions queue on `/audit` lists pending AI classifications and AI reconciliation matches in score band 60-84 with `{transaction, suggested_category_or_match, ai_score, ai_reasoning}`.|AC18.5.3 — AI Suggestion Review Queue page renders suggestions
fe-remainder-reconciliation.3|Queue actions: `Accept`, `Reject`, `Edit-then-Accept`.|AC18.5.4 — feedback POST on accept/reject/edit
@$be/reconciliation/test_reconciliation_hybrid_scoring.py|P1
1803.1|Hybrid scoring: score_single blends 0.7 * algorithmic + 0.3 * AI semantic score, applied only.|test_score_single_applies_hybrid_ai_scoring
1803.2|Feature flag ENABLE_AI_RECONCILIATION gates the hybrid-AI branch.|test_score_single_flag_off_skips_ai_scoring
1803.3|Execute_matching resolves enable_ai_reconciliation from the per-user ai_settings override.|test_AC_reconciliation_1803_3_execute_matching_uses_per_user_ai_reconciliation_override
@$be/reconciliation/test_economic_disposition.py|P0
economic-disposition.1|An eligible journal candidate wins.|test_AC_reconciliation_economic_disposition_1_normal_candidate_precedes_transfer
economic-disposition.2|The database permits at most one active economic-disposition head for each AtomicTransaction.|test_AC_reconciliation_economic_disposition_2_database_rejects_duplicate_active_heads
economic-disposition.3|Independent sessions racing on one AtomicTransaction converge on one winner.|test_AC_reconciliation_economic_disposition_3_two_sessions_converge
economic-disposition.4|A transfer pair persists both uniquely owned disposition legs, its decision version.|test_AC_reconciliation_economic_disposition_4_transfer_pair_round_trip
economic-disposition.5|Every statement-to-ledger amount comparison names the transaction currency.|test_AC_reconciliation_economic_disposition_5_currency_is_explicit
economic-disposition.6|Retry, worker restart, and phase permutation preserve disposition, journal.|test_AC_reconciliation_economic_disposition_6_retry_and_phase_permutation_are_idempotent
economic-disposition.7|Processing effects are invoked only.|test_AC_reconciliation_economic_disposition_7_processing_uses_typed_ledger_boundary
@$be/reconciliation/test_named_transfer_legs.py|P0|done|property
named-transfer-legs.1|Post_named_transfer_legs posts the same Processing leg as the keyword fallback for a transaction that the AI classification named a transfer or a card repayment.|test_AC_reconciliation_named_transfer_legs_1_an_outgoing_row_posts_dr_processing_cr_bank
named-transfer-legs.2|A named transaction is skipped.|test_AC_reconciliation_named_transfer_legs_2_a_second_call_posts_nothing_more
named-transfer-legs.3|Two transactions with the same date, text and amount get two legs with two journal entries.|test_AC_reconciliation_named_transfer_legs_3_two_identical_rows_post_two_legs
named-transfer-legs.4|The legs from post_named_transfer_legs carry the normalized anchors.|test_AC_reconciliation_named_transfer_legs_4_the_legs_pair_in_the_next_reconciliation_run|P1
named-transfer-legs.5|The memo of a transfer leg holds at most 500 characters, the size of the memo column.|test_AC_reconciliation_named_transfer_legs_5_a_long_description_posts_a_leg_with_a_bounded_memo
@$be/reconciliation/test_multi_tenant_stats_budget.py|P1|done|property
2617.1|With 100 more users and their accepted matches in the database, GET /reconciliation/stats reads at most 1.25 times the rows that it reads for one user alone.|test_AC_reconciliation_2617_1_stats_do_not_read_matches_of_other_tenants
2617.2|Get_reconciliation_stats returns the values of the version.|test_AC_reconciliation_2617_2_stats_equal_the_pre_change_values|:exact
@-|P1
candidate-policy.1|Live matching and the deterministic accuracy audit share candidate enumeration, rule scoring and source-rank ordering.|$be/reconciliation/test_candidate_policy.py::test_live_and_audit_choose_the_same_evidence|P0:property
config-boundary.1|Configuration values have no direct runtime or ledger dependency.|$t/test_reconciliation_config_boundary.py::test_configuration_ownership_is_explicit|P0:property
review-queue.2|The reconciliation router's accept_match/reject_match/batch_accept service calls transition matches to ACCEPTED/REJECTED/ACCEPTED and batch_accept reports the accepted count.|$be/reconciliation/test_reconciliation_router_additional.py::test_accept_reject_batch_accept
source-type-transfer.4|Execute_matching's conflict resolution assigns a source_type_winner_rank of 4.0 to a MANUAL entry and source_type_loser_rank of 1.0 to a same-score AUTO_PARSED entry.|$be/reconciliation/test_source_type.py::test_manual_wins_conflict_resolution
recovered-coverage.1|POST /corrections persists a category correction for a transaction and GET /corrections/stats subsequently reports it in total_corrections and top_corrections.|$be/api/test_corrections_router.py::test_post_create_correction_and_stats
bank-side-amount.1|Score_single computes the 'amount' score dimension from the bank/cash account's line amount.|$be/reconciliation/test_reconciliation_financial_logic.py::test_AC4_9_1_entry_total_uses_bank_side_line_for_outflow|P0
bank-side-amount.5|Derive_reconciliation_score_tier maps a reconciliation match_score to LOW, MEDIUM, or HIGH.|$be/reconciliation/test_confidence_tier.py::test_ac4_9_4_derive_reconciliation_score_tier
per-currency-balance.9|ExtractionService.parse_document persists a multi-currency bank statement's per-currency currency_balances and sets balance_validated True because each currency independently reconciles.|$be/extraction/test_bank_multi_currency_balances.py::test_AC4_13_9_bank_multi_currency_statement_persists_balances_and_per_currency_governs|P0
consistency-checks.11|Consistency check detection strictly partitions by transaction currency, preventing false duplicate and cross-currency transfer pair collisions.|$be/review/test_falsifiable_consistency.py::test_consistency_checks_strictly_partition_by_currency
candidate-matching.1|_find_transfer_candidates, _find_normal_candidates.|$be/reconciliation/test_reconciliation_scoring_helpers.py::test_find_transfer_candidates_returns_pair|P2
fe-stage2-review.2|The `/reconciliation` page renders the reconciliation workbench.|$fe/__tests__/reconciliationEntryPages.test.tsx::AC16.16.4 renders workbench in reconciliation page|P2
fe-stage2-review.27|The ConflictResolutionDialog `Resolve` / `Link Pair` buttons call the resolve endpoint with the matching action and disable.|$fe/__tests__/ConflictResolutionDialog.test.tsx::AC16.34.3 Resolve and Link Pair buttons call onResolve with the matching action|P0
fe-ia-reconciliation.1|The AI suggestions queue on `/audit` is reachable from AI Settings.|$fe/__tests__/aiSettingsPage.test.tsx::AC22.4.3 links to the AI suggestion review surface so it is not orphaned
fe-ia-reconciliation.2|E2E: a user with Stage 1 and Stage 2 attention sees both in the upload page workflow notices and can open each detail surface.|apps/frontend/playwright/epic022-attention-journey.spec.ts::${label}: both Stage 1 and Stage 2 attention surface in the upload workflow notices with deep links
fe-ia-reconciliation.5|Desktop and mobile smoke covers the Needs Confirmation queue on `/audit` and the Home trust meter.|apps/frontend/playwright/attention-surface.spec.ts::${label} renders the attention queue ranked by confidence without overflow
fe-ia-reconciliation.9|The Stage 2 review queue is composed from extracted sub-components with unchanged review behavior.|$fe/__tests__/stage2ReviewQueueParts.test.tsx::AC22.17.2 PendingMatchesPanel renders mobile + desktop rows and wires selection/batch callbacks
economic-disposition.8|The governance detail projects exact detector, proof-strength, target-SHA.|$be/reconciliation/test_economic_disposition_governance.py::test_AC_reconciliation_economic_disposition_8_governance_detail_is_exact|P0
named-transfer-legs.6|The keyword fallback posts a Processing leg only for a transaction in the effective base currency.|$be/reconciliation/test_keyword_leg_base_currency.py::test_AC_reconciliation_named_transfer_legs_6_a_foreign_row_posts_no_leg_and_creates_no_account|P0:property
2465.2|On the statement page transaction table, a transaction whose statement is approved defaults to matched status.|$fe/__tests__/TransactionTable.test.tsx::AC-reconciliation.2465.2 defaults transaction status to matched when the statement is approved
2888.1|Release_transaction_dispositions supersedes the active matches of the released rows.|$be/reconciliation/test_statement_release.py::test_AC_reconciliation_2888_1_released_leg_breaks_the_pair_for_readers|P0:property
""",
    ),
    concepts=concepts(
        """
reconciliation_state_machine|common/reconciliation/readme.md#state-machine|pending → auto_accepted / pending_review → accepted / rejected.|common/reconciliation/confirmation-workflow.md,common/reconciliation/reconciliation.md|-|reconciliation|model
reconciliation_thresholds|common/reconciliation/readme.md#thresholds|Score ≥85 auto-accept; 60-84 review; <60 unmatched.|docs/agents/red-lines.md,common/reconciliation/reconciliation.md|-|reconciliation|baseline
"""
    ),
    governance=[
        GovernanceInitiative(
            id="economic-disposition-atomicity",
            title="Economic disposition atomicity and persistent transfer state",
            issue="https://github.com/wangzitian0/finance_report/issues/1994",
            depends_on=["meta/governance-control-plane"],
            guarantees=[
                GovernanceGuarantee(
                    id="normal-candidate-first",
                    statement="Eligible journal candidates precede transfer fallback.",
                    affected_acs=["AC-reconciliation.economic-disposition.1"],
                    detector="transfer-priority-violations",
                    target="0 priority violations",
                    lock="ci.backend",
                    proof="economic-disposition-normal-first",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="one-active-head",
                    statement="Each source transaction has at most one active disposition head.",
                    affected_acs=["AC-reconciliation.economic-disposition.2"],
                    detector="duplicate-active-disposition-heads",
                    target="0 duplicate active heads",
                    lock="ci.backend_integration",
                    proof="economic-disposition-active-head-schema",
                    required_proof_strength="schema",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="worker-convergence",
                    statement="Independent workers converge without duplicate financial effects.",
                    affected_acs=["AC-reconciliation.economic-disposition.3"],
                    detector="non-convergent-disposition-races",
                    target="0 race losers creating effects",
                    lock="ci.backend_integration",
                    proof="economic-disposition-two-session-race",
                    required_proof_strength="concurrency",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="persistent-transfer-pair",
                    statement="Transfer decisions and unique leg membership are persistent facts.",
                    affected_acs=["AC-reconciliation.economic-disposition.4"],
                    detector="unpersisted-or-duplicate-transfer-memberships",
                    target="0 unpersisted or duplicate memberships",
                    lock="ci.backend_integration",
                    proof="economic-disposition-transfer-pair",
                    required_proof_strength="schema",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="currency-explicit",
                    statement="Disposition comparisons operate in an explicit currency domain.",
                    affected_acs=["AC-reconciliation.economic-disposition.5"],
                    detector="implicit-currency-comparison-calls",
                    target="0 implicit currency calls",
                    lock="ci.backend",
                    proof="economic-disposition-currency-oracle",
                    required_proof_strength="value-oracle",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="idempotent-command",
                    statement="Retries and phase permutations preserve aggregate cardinality.",
                    affected_acs=["AC-reconciliation.economic-disposition.6"],
                    detector="non-idempotent-disposition-retries",
                    target="0 cardinality drift",
                    lock="ci.backend_integration",
                    proof="economic-disposition-idempotency",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend_integration",
                ),
                GovernanceGuarantee(
                    id="typed-ledger-boundary",
                    statement="All Processing writes cross ledger's typed command boundary.",
                    affected_acs=["AC-reconciliation.economic-disposition.7"],
                    detector="reconciliation-owned-ledger-writes",
                    target="0 alternate posting paths",
                    lock="ci.backend",
                    proof="economic-disposition-ledger-boundary",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
                GovernanceGuarantee(
                    id="exact-governance-detail",
                    statement="Control-plane detail exposes current exact proof and enforcement facts.",
                    affected_acs=["AC-reconciliation.economic-disposition.8"],
                    detector="economic-disposition-governance-join-gaps",
                    target="0 missing detail facts",
                    lock="ci.backend",
                    proof="economic-disposition-governance-detail",
                    required_proof_strength="exact",
                    enforcing_gate="ci.backend",
                ),
            ],
        )
    ],
)
