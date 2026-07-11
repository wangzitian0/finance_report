"""The ``reconciliation`` package's machine-checkable :class:`PackageContract`."""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="reconciliation",
    status="active",
    tier="CODE-ONLY",
    # #1674 contract-honesty audit (2026-07-09): portfolio/platform/pricing/config
    # were declared but had zero real imports — removed. Re-add each with its
    # first real import, not before (a declared-but-unused edge now fails
    # check_package_contract).
    # llm added #1670: extension/scoring.py's AI semantic-match scoring streams
    # a prompt through src.llm (graceful None fallback on any error — advisory
    # signal, not a hard dependency on model correctness).
    # pricing re-added #1675: extension/fx_transfer.py + fx_transfer_discovery.py
    # read the FxConversion model, now published on pricing's root.
    depends_on=["audit", "extraction", "ledger", "llm", "observability", "pricing"],
    roles=["base", "extension", "data"],
    units=[
        Unit(name="ReconciliationMatch", kind=Kind.AGGREGATE_ROOT),
        Unit(name="ReconciliationMatchJournalEntry", kind=Kind.ENTITY),
        Unit(name="ReconciliationStatus", kind=Kind.VALUE_OBJECT),
        Unit(
            name="ReconciliationConfig", kind=Kind.VALUE_OBJECT, module="base/config.py"
        ),
        Unit(name="MatchCandidate", kind=Kind.VALUE_OBJECT, module="base/config.py"),
        Unit(name="ReconciliationStats", kind=Kind.PROJECTION, module="data/stats.py"),
        Unit(
            name="load_reconciliation_config",
            kind=Kind.FACTORY,
            module="base/config.py",
        ),
        Unit(
            name="ReconciliationRepository",
            kind=Kind.REPOSITORY,
            module="base/repository.py",
            impl="extension/repository.py",
        ),
        Unit(
            name="execute_matching",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/matching.py",
        ),
        Unit(
            name="calculate_match_score",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/matching.py",
        ),
        Unit(
            name="find_candidates",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/matching.py",
        ),
        Unit(
            name="prune_candidates",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/matching.py",
        ),
        Unit(
            name="build_many_to_one_groups",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/matching.py",
        ),
        Unit(
            name="get_reconciliation_stats",
            kind=Kind.PROJECTION,
            module="data/stats.py",
        ),
        Unit(
            name="score_amount", kind=Kind.DOMAIN_SERVICE, module="extension/scoring.py"
        ),
        Unit(
            name="score_date", kind=Kind.DOMAIN_SERVICE, module="extension/scoring.py"
        ),
        Unit(
            name="score_description",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/scoring.py",
        ),
        Unit(
            name="score_business_logic",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/scoring.py",
        ),
        Unit(
            name="score_pattern",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/scoring.py",
        ),
        Unit(
            name="EventBusMatchOutcome",
            kind=Kind.EVENT_BUS,
            module="extension/matching.py",
        ),
        Unit(
            name="ReconciliationStatsProjection",
            kind=Kind.PROJECTION,
            module="data/stats.py",
        ),
        Unit(name="ScoreBreakdownProjection", kind=Kind.PROJECTION),
        Unit(name="MatchStatusHistoryProjection", kind=Kind.PROJECTION),
        Unit(name="UnmatchedTransactionsProjection", kind=Kind.PROJECTION),
        Unit(name="TransferLeg", kind=Kind.VALUE_OBJECT),
        Unit(
            name="pair_fx_legs",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/fx_transfer.py",
        ),
        Unit(
            name="discover_fx_conversions",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/fx_transfer_discovery.py",
        ),
        Unit(
            name="detect_anomalies",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/anomaly.py",
        ),
        Unit(
            name="run_all_consistency_checks",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/consistency_checks.py",
        ),
    ],
    implementations={"be": "apps/backend/src/reconciliation", "fe": None},
    interface=[
        "CheckStatus",
        "CheckType",
        "ConsistencyCheck",
        "DEFAULT_CONFIG",
        "DEFAULT_RATE_TOLERANCE",
        "DEFAULT_TIME_WINDOW",
        "FxTransferError",
        "MAX_COMBINATION_CANDIDATES",
        "MatchCandidate",
        "RECONCILIATION_SEMANTIC_PROMPT",
        "ReconciliationConfig",
        "ReconciliationStats",
        "TransferLeg",
        "_candidate_is_better",
        "_find_many_to_one_candidates",
        "_find_normal_candidates",
        "_find_transfer_candidates",
        "_get_existing_active_match",
        "_get_pending_layer2_transactions",
        "_within_combination_tolerance",
        "accept_match",
        "ai_semantic_score",
        "auto_accept",
        "batch_accept",
        "build_many_to_one_groups",
        "build_reconciliation_prompt",
        "calculate_match_score",
        "classify_internal_transfer",
        "detect_anomalies",
        "discover_fx_conversions",
        "entry_bank_side_amount",
        "entry_total_amount",
        "execute_matching",
        "extract_merchant_tokens",
        "find_candidates",
        "get_pending_checks",
        "get_pending_items",
        "get_reconciliation_stats",
        "get_stage2_queue",
        "has_unresolved_checks",
        "is_cross_period",
        "is_entry_balanced",
        "list_checks",
        "load_reconciliation_config",
        "normalize_text",
        "pair_fx_legs",
        "prune_candidates",
        "reject_match",
        "resolve_check",
        "run_all_consistency_checks",
        "score_amount",
        "score_business_logic",
        "score_date",
        "score_description",
        "score_pattern",
        "sync_reconciliation_match_journal_entry_links",
        "weighted_total",
    ],
    events=["WorkflowEvent.reconciliation_match_outcome"],
    invariants=[
        Invariant(
            id="converges-by-layer",
            statement=(
                "The package converges into base/ (value objects + repository port) + "
                "extension/ (matching/services/adapters) + data/ (stats projection)."
            ),
            test="tests/tooling/test_reconciliation_package.py::test_reconciliation_converges_by_layer",
        ),
        Invariant(
            id="interface-equals-published-language",
            statement="The published language (contract.interface) equals __init__.__all__.",
            test="tests/tooling/test_reconciliation_package.py::test_reconciliation_only_all_is_the_published_language",
        ),
        Invariant(
            id="base-layer-pure",
            statement="base/ never imports the package's own extension/ or ORM/runtime adapters.",
            test="tests/tooling/test_reconciliation_package.py::test_reconciliation_base_layer_is_pure",
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates reconciliation with no violations.",
            test="tests/tooling/test_reconciliation_package.py::test_reconciliation_package_contract_gate_passes",
        ),
    ],
    roadmap=[
        ACRecord(
            id="AC-reconciliation.match.1",
            statement=(
                "At most one active ReconciliationMatch exists per AtomicTransaction; newer matches supersede prior active rows."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_execute_matching_many_to_one_keeps_same_existing_match"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.match.2",
            statement=(
                "Reconciliation status follows PENDING_REVIEW→ACCEPTED/AUTO_ACCEPTED/REJECTED→SUPERSEDED and posted entries are immutable."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py"
                "::test_normal_matching_auto_accept_reconciles_entries"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.score.1",
            statement="Match score is weighted composite amount/date/description/business/history in [0,100].",
            test="apps/backend/tests/reconciliation/test_reconciliation_scoring.py::test_weighted_total_and_balance_helpers",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.score.2",
            statement="Scores at/above auto-accept threshold auto-accept; review-band scores route to PENDING_REVIEW.",
            test="apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_auto_accept_threshold",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.stats.1",
            statement="Stats projection match_rate is consistent with active accepted/auto-accepted match states.",
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_stats.py"
                "::test_get_reconciliation_stats_dedups_multiple_accepted_matches"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.txn.1",
            statement="ReconciliationMatch references AtomicTransaction and JournalEntry by id only (no cross-domain FK).",
            test=(
                "apps/backend/tests/infra/test_audit_anchor_schema_invariants.py"
                "::test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries"
            ),
            priority="P0",
            status="done",
        ),
        # ============================= matching-core (AC4.1) =============================
        ACRecord(
            id="AC-reconciliation.matching-core.1",
            statement=(
                "score_amount returns 100 for an exact amount match and graduated lower scores "
                "(90/70/40/0) as the absolute and percentage delta from the target amount widens."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_scoring.py"
                "::test_score_amount_branches"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.matching-core.2",
            statement=(
                "score_date returns 100 for a same-day match and graduated lower scores (90/75/0) "
                "as the day gap widens, with a same-window cross-month bonus over a plain in-month "
                "gap of the same size."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_scoring.py"
                "::test_score_date_branches"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.matching-core.3",
            statement=(
                "score_amount applies tiered tolerance bands (exact, 0.5%-or-tighter, $5 flat, "
                "multi-entry tolerance, ratio-based fallback) rather than a single pass/fail cutoff, "
                "including scoring a zero-amount transaction as 0."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py"
                "::test_score_amount_tiers"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.matching-core.4",
            statement=(
                "score_description normalizes text (case/punctuation-insensitive) and returns >=95 "
                "for near-identical descriptions differing only by case, while returning 0 for None, "
                "blank, or punctuation-only inputs."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_scoring.py"
                "::test_normalize_and_description_scoring"
            ),
            priority="P1",
            status="done",
        ),
        # ============================= group-matching (AC4.2) =============================
        ACRecord(
            id="AC-reconciliation.group-matching.1",
            statement=(
                "execute_matching groups same-day, same-description bank transactions that sum to "
                "one manual journal entry's amount into a many-to-one match and auto-accepts all of them."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_execute_matching_many_to_one_group"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.group-matching.2",
            statement=(
                "calculate_match_score adds a many_to_one_bonus (10 points) when scoring a "
                "batch-payment transaction against a single matching journal entry with "
                "is_multi/is_many_to_one set, pushing the composite score above the auto-accept threshold."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_scoring.py"
                "::test_calculate_match_score_many_to_one_bonus"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.group-matching.3",
            statement=(
                "execute_matching finds the combination of multiple journal entries (one-to-many "
                "split) whose lines sum to a single transaction's amount, records a multi_entry count "
                "in the score breakdown, and auto-accepts the best combination."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_execute_matching_multi_entry_combinations"
            ),
            priority="P1",
            status="done",
        ),
        # ============================= review-queue (AC4.3) =============================
        # NB: old AC4.3.1 is NOT here -- it is a duplicate of the already-migrated
        # AC-reconciliation.score.2 (identical test: test_auto_accept_threshold).
        ACRecord(
            id="AC-reconciliation.review-queue.1",
            statement=(
                "accept_match, reject_match, and batch_accept transition PENDING_REVIEW matches to "
                "ACCEPTED/REJECTED/ACCEPTED respectively, and accepting a match reconciles its linked "
                "journal entry (status -> RECONCILED)."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_review_queue_actions_and_entry_creation"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.2",
            statement=(
                "The reconciliation router's accept_match/reject_match/batch_accept service calls "
                "transition matches to ACCEPTED/REJECTED/ACCEPTED and batch_accept reports the "
                "accepted count."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_router_additional.py"
                "::test_accept_reject_batch_accept"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.3",
            statement="POST /reconciliation/matches/{id}/accept returns 200 with the match status set to ACCEPTED.",
            test="apps/backend/tests/api/test_reconciliation_router.py::test_accept_match_success",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.4",
            statement=(
                "POST /reconciliation/matches/{id}/accept for a non-existent match id returns 404 "
                "with 'Match' in the error detail."
            ),
            test="apps/backend/tests/api/test_reconciliation_router.py::test_accept_match_not_found",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.5",
            statement="POST /reconciliation/matches/{id}/reject returns 200 with the match status set to REJECTED.",
            test="apps/backend/tests/api/test_reconciliation_router.py::test_reject_match_success",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.6",
            statement=(
                "POST /reconciliation/matches/{id}/reject for a non-existent match id returns 404 "
                "with 'Match' in the error detail."
            ),
            test="apps/backend/tests/api/test_reconciliation_router.py::test_reject_match_not_found",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.7",
            statement=(
                "GET /reconciliation/stats returns 200 with a stats payload containing "
                "total/matched/unmatched counts, match_rate, and score_distribution."
            ),
            test="apps/backend/tests/api/test_reconciliation_router.py::test_reconciliation_stats_success",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.8",
            statement=(
                "GET /reconciliation/unmatched returns 200 with a paginated items/total payload "
                "listing unmatched transactions."
            ),
            test="apps/backend/tests/api/test_reconciliation_router.py::test_list_unmatched_success",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.9",
            statement=(
                "POST /reconciliation/unmatched/{txn_id}/create-entry returns 200 with a created "
                "journal entry (id/entry_date/memo/status/total_amount)."
            ),
            test=(
                "apps/backend/tests/api/test_reconciliation_router.py"
                "::test_create_entry_from_unmatched_success"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.10",
            statement=(
                "POST /reconciliation/unmatched/{txn_id}/create-entry for a non-existent transaction "
                "id returns 404 with 'Transaction' in the error detail."
            ),
            test=(
                "apps/backend/tests/api/test_reconciliation_router.py"
                "::test_create_entry_from_unmatched_not_found"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.11",
            statement=(
                "Reconciliation endpoints reject unauthenticated requests with 401 (verified via "
                "GET /reconciliation/stats on an unauthenticated client)."
            ),
            test="apps/backend/tests/api/test_reconciliation_router.py::test_unauthenticated_access",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.12",
            statement=(
                "GET /reconciliation/unmatched scopes results to the authenticated user and never "
                "returns another user's transactions."
            ),
            test="apps/backend/tests/api/test_reconciliation_router.py::test_user_isolation",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.13",
            statement=(
                "POST /reconciliation/unmatched/batch-create with all=True creates journal entries "
                "for every unmatched transaction and reports the created_count."
            ),
            test=(
                "apps/backend/tests/api/test_reconciliation_router.py"
                "::test_batch_create_entries_for_all_unmatched"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.review-queue.14",
            statement=(
                "POST /reconciliation/unmatched/batch-create without an all or txn_ids filter "
                "returns 400 with 'txn_ids' named in the error detail."
            ),
            test=(
                "apps/backend/tests/api/test_reconciliation_router.py"
                "::test_batch_create_entries_requires_filter"
            ),
            priority="P1",
            status="done",
        ),
        # ============================= performance (AC4.4) =============================
        ACRecord(
            id="AC-reconciliation.performance.1",
            statement=(
                "execute_matching processes 100 transactions against 20 candidate entries in under "
                "5 seconds (representative sample standing in for the 10,000-transaction target)."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_performance.py"
                "::test_batch_1000_transactions_reasonable_time"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.performance.2",
            statement=(
                "calculate_match_score still scores a transaction dated one day before month-end "
                "against an entry dated the first of the next month at >=70 (cross-month date proximity)."
            ),
            test="apps/backend/tests/reconciliation/test_performance.py::test_month_end_to_month_start_match",
            priority="P1",
            status="done",
        ),
        # ============================= anomaly-detection (AC4.5) =============================
        ACRecord(
            id="AC-reconciliation.anomaly-detection.1",
            statement=(
                "detect_anomalies flags LARGE_AMOUNT and FREQUENCY_SPIKE for an outsized transaction "
                "against a merchant with recent history, and flags NEW_MERCHANT and WEEKEND_LARGE for "
                "a large transaction on a weekend with no prior merchant history."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_detect_anomalies_flags_expected_patterns"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.anomaly-detection.2",
            statement=(
                "GET /reconciliation/transactions/{txn_id}/anomalies for a non-existent transaction "
                "id returns 404 with 'Transaction' in the error detail."
            ),
            test="apps/backend/tests/api/test_reconciliation_router.py::test_list_anomalies_not_found",
            priority="P1",
            status="done",
        ),
        # ============================= source-type-transfer (AC4.6) =============================
        # NB: old AC4.6.4 is NOT here -- its test/file were not found under any name (flagged).
        ACRecord(
            id="AC-reconciliation.source-type-transfer.1",
            statement=(
                "score_amount's absolute tolerance boundary holds exactly at 0.10: a $0.10 delta "
                "still scores 90 while a $0.11 delta scores below 90."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_scoring.py"
                "::test_amount_tolerance_0_10_boundary"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.source-type-transfer.2",
            statement=(
                "execute_matching matches an OUT transfer transaction and its paired IN transaction "
                "(within days, opposite direction, same amount) each to their own generated system "
                "Processing entry and auto-accepts both without double-booking one side against the other."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_transfer_pair_not_double_counted"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.source-type-transfer.3",
            statement=(
                "When two candidate journal entries tie on score, _candidate_is_better deterministically "
                "prefers the MANUAL-sourced entry over the AUTO_PARSED one, recording a higher "
                "source_type_winner_rank than source_type_loser_rank in the breakdown."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py"
                "::test_AC4_6_3_candidate_tie_breaker_prefers_higher_source_trust"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.source-type-transfer.4",
            statement=(
                "execute_matching's conflict resolution assigns a source_type_winner_rank of 4.0 to a "
                "MANUAL entry and source_type_loser_rank of 1.0 to a same-score AUTO_PARSED entry, so "
                "the manual entry wins the match end to end."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_source_type.py"
                "::test_manual_wins_conflict_resolution"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.source-type-transfer.5",
            statement=(
                "The Stage-1 duplicate guard does NOT flag two transactions identical in "
                "date/description/amount/direction as duplicate candidates when their balance_after "
                "(running balance) values differ."
            ),
            test=(
                "apps/backend/tests/review/test_statement_validation.py"
                "::test_duplicate_guard_distinguishes_by_balance_after"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.source-type-transfer.6",
            statement=(
                "The Stage-1 duplicate guard still flags two transactions identical in "
                "date/description/amount/direction as duplicate candidates when balance_after is "
                "equal on both or absent on both (ambiguous, needs review)."
            ),
            test=(
                "apps/backend/tests/review/test_statement_validation.py"
                "::test_duplicate_guard_flags_when_balance_after_equal_or_absent"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.source-type-transfer.7",
            statement=(
                "execute_matching's layer-2 matching path stamps atomic_txn_id on the resulting "
                "ReconciliationMatch when a many-to-one group is auto-accepted."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_execute_matching_many_to_one_layer2_sets_atomic_txn_id"
            ),
            priority="P1",
            status="done",
        ),
        # ============================= recovered-coverage (AC4.7) =============================
        ACRecord(
            id="AC-reconciliation.recovered-coverage.1",
            statement=(
                "POST /corrections persists a category correction for a transaction and GET "
                "/corrections/stats subsequently reports it in total_corrections and top_corrections."
            ),
            test="apps/backend/tests/api/test_corrections_router.py::test_post_create_correction_and_stats",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.recovered-coverage.2",
            statement=(
                "execute_matching's phase-2 combination search skips a 3-entry combination when one "
                "of the candidate entries is unbalanced, so no match is produced."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_execute_matching_three_entry_combination_skips_unbalanced_member"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.recovered-coverage.3",
            statement=(
                "execute_matching's layer-2 path records an atomic match for a single-entry candidate "
                "and supports transfer-pair logging within the same phase."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_engine.py"
                "::test_execute_matching_layer2_atomic_match_and_transfer_pair_logging"
            ),
            priority="P1",
            status="done",
        ),
        # ============================= bank-side-amount (AC4.9) =============================
        ACRecord(
            id="AC-reconciliation.bank-side-amount.1",
            statement=(
                "calculate_match_score computes the 'amount' score dimension from the bank/cash "
                "account's line amount (not the total of all entry debits) so a split entry with "
                "clearing/payable lines still yields a 100.0 amount score for a matching outflow."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_financial_logic.py"
                "::test_AC4_9_1_entry_total_uses_bank_side_line_for_outflow"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.bank-side-amount.2",
            statement=(
                "Retrying accept_match_service on an already-ACCEPTED match returns the same version "
                "and the same journal_entry_ids without creating a duplicate journal entry."
            ),
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_accept_match_retry_is_idempotent_after_success"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.bank-side-amount.3",
            statement=(
                "create_entry_from_txn with auto_post=True raises ValueError('... not active ...') "
                "and creates no journal entry when the statement's linked account is inactive."
            ),
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_create_entry_from_txn_auto_post_rejects_inactive_statement_account"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.bank-side-amount.4",
            statement=(
                "get_stage2_review_queue returns a pending PENDING_REVIEW match with a "
                "confidence_tier of MEDIUM derived from its match_score (75)."
            ),
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_get_stage2_review_queue_with_pending_match"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.bank-side-amount.5",
            statement=(
                "derive_reconciliation_score_tier maps a reconciliation match_score to LOW (<60 or "
                "None), MEDIUM (60-84), or HIGH (>=85)."
            ),
            test=(
                "apps/backend/tests/services/test_confidence_tier.py"
                "::test_ac4_9_4_derive_reconciliation_score_tier"
            ),
            priority="P1",
            status="done",
        ),
        # ============================= audit-harness (AC4.10) =============================
        # NB: old AC4.10.3 is NOT here -- its test asserts a literal substring of
        # EPIC-004's own markdown text, so it stays EPIC-owned (same category as
        # AC12.25.1 in EPIC-012).
        ACRecord(
            id="AC-reconciliation.audit-harness.1",
            statement=(
                "The reconciliation audit harness's build_report/write_report emit a JSON report "
                "(with metadata, summary accuracy/false-positive-rate fields, and pass/fail targets) "
                "and a companion Markdown report."
            ),
            test=(
                "tests/tooling/test_reconciliation_audit.py"
                "::test_AC4_10_1_reconciliation_audit_report_schema_and_outputs"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.audit-harness.2",
            statement=(
                "The reconciliation audit harness's diagnostics report an intentionally-seeded "
                "false-positive scenario, identifying it by scenario id in the audit output."
            ),
            test=(
                "tests/tooling/test_reconciliation_audit.py"
                "::test_AC4_10_2_reconciliation_audit_reports_intentional_false_positive"
            ),
            priority="P1",
            status="done",
        ),
        # ============================= uuid-path-params (AC4.12) =============================
        ACRecord(
            id="AC-reconciliation.uuid-path-params.1",
            statement=(
                "POST /reconciliation/matches/{match_id}/accept with a non-UUID match_id returns 422 "
                "at the FastAPI path-param boundary rather than reaching the query layer."
            ),
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC4_12_1_accept_match_malformed_uuid_returns_422"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.uuid-path-params.2",
            statement=(
                "POST /reconciliation/unmatched/{txn_id}/create-entry with a non-UUID txn_id returns "
                "422 at the FastAPI path-param boundary rather than reaching the query layer."
            ),
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC4_12_2_create_entry_malformed_uuid_returns_422"
            ),
            priority="P2",
            status="done",
        ),
        # ============================= per-currency-balance (AC4.13) =============================
        ACRecord(
            id="AC-reconciliation.per-currency-balance.1",
            statement=(
                "validate_balance_per_currency reconciles a multi-currency statement's SGD and USD "
                "buckets independently (each via its own open+in-out=close check) and never produces "
                "a cross-currency summed total."
            ),
            test="apps/backend/tests/accounting/test_validation.py::test_AC1_per_currency_reconcile_does_not_cross_sum",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.per-currency-balance.2",
            statement=(
                "validate_balance_per_currency flags only the offending currency (USD short by 50) "
                "as invalid while the correctly-balanced SGD bucket stays valid, never collapsing "
                "both into one aggregate flag."
            ),
            test=(
                "apps/backend/tests/accounting/test_validation.py"
                "::test_AC1_per_currency_reconcile_flags_only_offending_currency"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.per-currency-balance.3",
            statement=(
                "validate_balance_per_currency falls back to a single synthetic currency bucket and "
                "reproduces the legacy scalar balance check when the payload has no balances array, "
                "only opening_balance/closing_balance."
            ),
            test=(
                "apps/backend/tests/accounting/test_validation.py"
                "::test_AC1_single_currency_degenerate_path_still_passes"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.per-currency-balance.4",
            statement=(
                "The degenerate single-currency validation path still detects and flags a balance "
                "mismatch when opening+transactions doesn't equal closing."
            ),
            test=(
                "apps/backend/tests/accounting/test_validation.py"
                "::test_AC1_single_currency_degenerate_path_detects_mismatch"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.per-currency-balance.5",
            statement=(
                "The CurrencyBalance schema normalizes a lower-case currency code to upper-case ISO "
                "and round-trips opening/closing as Decimal."
            ),
            test=(
                "apps/backend/tests/accounting/test_validation.py"
                "::test_AC1_currency_balance_schema_round_trips_decimals"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.per-currency-balance.6",
            statement=(
                "validate_balance_per_currency surfaces a transaction in a currency with no declared "
                "balance bucket (e.g. EUR) as its own per-currency result flagged declared_balance=False "
                "and forces the overall result invalid, instead of silently dropping that currency's money."
            ),
            test=(
                "apps/backend/tests/accounting/test_validation.py"
                "::test_AC1_orphan_currency_transaction_is_surfaced_not_dropped"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.per-currency-balance.7",
            statement=(
                "validate_balance_per_currency rejects a balances array containing two buckets for "
                "the same currency (balance_computable=False, empty per_currency) instead of silently "
                "collapsing them into one arbitrary bucket."
            ),
            test=(
                "apps/backend/tests/accounting/test_validation.py"
                "::test_AC1_duplicate_currency_in_balances_is_rejected"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.per-currency-balance.8",
            statement=(
                "bank_currency_balances returns the per-currency array (as JSONB-ready string "
                "amounts) only when a bank statement payload declares more than one currency, and "
                "returns None for a single-currency or scalar-only payload so the existing scalar "
                "path is unchanged."
            ),
            test=(
                "apps/backend/tests/accounting/test_validation.py"
                "::test_AC4_13_9_bank_currency_balances_emitted_only_when_multi_currency"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.per-currency-balance.9",
            statement=(
                "ExtractionService.parse_document persists a multi-currency bank statement's "
                "per-currency currency_balances (not collapsed to one scalar currency) and sets "
                "balance_validated True because each currency independently reconciles."
            ),
            test=(
                "apps/backend/tests/extraction/test_bank_multi_currency_balances.py"
                "::test_AC4_13_9_bank_multi_currency_statement_persists_balances_and_per_currency_governs"
            ),
            priority="P0",
            status="done",
        ),
        # ============================= fx-transfer (AC4.14) =============================
        ACRecord(
            id="AC-reconciliation.fx-transfer.1",
            statement=(
                "pair_fx_legs pairs an out-leg in one currency with an in-leg in another for the same "
                "owner when the implied rate (out_amount/in_amount) is within tolerance of the market "
                "rate, regardless of argument order."
            ),
            test=(
                "apps/backend/tests/accounting/test_fx_transfer.py"
                "::test_AC2_pairs_out_ccyA_with_in_ccyB_within_rate_tolerance"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.2",
            statement=(
                "pair_fx_legs returns None when the implied rate deviates from the market rate beyond "
                "tolerance (~10% off) and still pairs when the market rate is close to the implied rate."
            ),
            test=(
                "apps/backend/tests/accounting/test_fx_transfer.py"
                "::test_AC2_implied_rate_outside_tolerance_does_not_pair"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.3",
            statement=(
                "pair_fx_legs refuses to pair legs that fall outside the configured time window, "
                "share the same direction, or belong to different owners."
            ),
            test="apps/backend/tests/accounting/test_fx_transfer.py::test_AC2_non_candidate_legs_do_not_pair",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.4",
            statement=(
                "classify_internal_transfer marks a paired FX transfer as an internal transfer with "
                "zero income_amount and zero expense_amount, while an unpaired leg keeps normal "
                "(non-netted) classification."
            ),
            test="apps/backend/tests/accounting/test_fx_transfer.py::test_AC3_internal_transfer_classified_net_zero",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.5",
            statement=(
                "classify_internal_transfer's net_worth_delta is exactly zero for a fee-less paired "
                "transfer and exactly -fee when a fee is present, with no other net-worth impact."
            ),
            test=(
                "apps/backend/tests/accounting/test_fx_transfer.py"
                "::test_AC3_net_worth_unchanged_by_internal_transfer_minus_fee"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.6",
            statement=(
                "round_trip_realized_pnl returns exactly 0.00 for a same-day round trip at an "
                "unchanged rate with no fee, and exactly -fee when a fee is charged."
            ),
            test=(
                "apps/backend/tests/accounting/test_fx_transfer.py"
                "::test_AC4_same_day_round_trip_nets_zero_pnl_minus_fee"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.7",
            statement=(
                "round_trip_realized_pnl yields zero P&L for an unchanged-rate conversion event, and "
                "any rate-move gain/loss is routed through the JournalEntrySourceType.FX_REVALUATION "
                "source type rather than a conversion-event income/expense line."
            ),
            test=(
                "apps/backend/tests/accounting/test_fx_transfer.py"
                "::test_AC4_revaluation_pnl_routed_through_fx_revaluation_source_type"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.8",
            statement=(
                "build_fx_conversion constructs an FxConversion record from a paired leg whose "
                "amount_from/amount_to round-trip as Decimal with normalized ISO currency codes."
            ),
            test="apps/backend/tests/accounting/test_fx_transfer.py::test_AC2_fx_conversion_model_round_trips_decimals",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.9",
            statement=(
                "generate_income_statement excludes a recorded internal transfer's income/expense "
                "legs entirely and includes only the transfer's fee as an expense line, so net_income "
                "reflects salary income minus the fee only, with the fee visible as a single "
                "drill-downable expense line and in the monthly trend bucket."
            ),
            test=(
                "apps/backend/tests/reporting/test_internal_transfer_e2e.py"
                "::test_AC3_internal_transfer_excluded_from_income_statement_e2e"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.10",
            statement=(
                "generate_balance_sheet's cumulative net_income excludes a recorded internal "
                "transfer's legs and reflects only the fee, matching the income statement's net "
                "contribution."
            ),
            test=(
                "apps/backend/tests/reporting/test_internal_transfer_e2e.py"
                "::test_AC3_internal_transfer_net_income_fee_only_e2e"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.11",
            statement=(
                "discover_fx_conversions auto-discovers an unambiguous out-leg/in-leg cross-currency "
                "conversion directly from raw asset-account journal lines (no recorded fx_conversions "
                "row), recovering the correct accounts, amounts, currencies, and implied rate."
            ),
            test=(
                "apps/backend/tests/accounting/test_fx_transfer_discovery.py"
                "::test_AC2_discover_pairs_unambiguous_cross_currency_legs_from_ledger"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.12",
            statement=(
                "discover_fx_conversions refuses to pair an out-leg that matches two candidate "
                "in-legs on the same day, leaving all of them unpaired rather than guessing."
            ),
            test=(
                "apps/backend/tests/accounting/test_fx_transfer_discovery.py"
                "::test_AC2_discover_skips_ambiguous_candidate_legs"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.13",
            statement=(
                "generate_income_statement and generate_balance_sheet, with no recorded "
                "fx_conversions row at all, still auto-discover a cross-currency transfer from raw "
                "ledger lines and exclude it end to end so net income equals salary income only "
                "(no fee on this transfer)."
            ),
            test=(
                "apps/backend/tests/reporting/test_fx_ledger_autodiscovery_e2e.py"
                "::test_AC2_raw_ledger_internal_transfer_autodiscovered_e2e"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fx-transfer.14",
            statement=(
                "For a same-day round-trip cross-currency conversion (both legs mis-booked as "
                "income/expense, no recorded fx_conversions), auto-discovery nets both conversions "
                "through the live income statement so net income shows ~zero P&L from the round trip."
            ),
            test=(
                "apps/backend/tests/reporting/test_fx_ledger_autodiscovery_e2e.py"
                "::test_AC4_same_day_round_trip_nets_zero_pnl_through_live_report"
            ),
            priority="P0",
            status="done",
        ),
        # ── group reconciliation-engine: end-to-end run/stats/match E2E (was
        # EPIC-008 AC8.5, migration closeout continuation, #1663 / #1711) ──
        ACRecord(
            id="AC-reconciliation.reconciliation-engine.1",
            statement="The reconciliation engine runs end to end through the API.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_reconciliation_engine_runs",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.reconciliation-engine.2",
            statement="The reconciliation stats endpoint returns run statistics.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_reconciliation_stats",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.reconciliation-engine.3",
            statement="A reconciliation match can be accepted through the API.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_reconciliation_match_acceptance",
            priority="P1",
            status="done",
        ),
        # ── group consistency-checks: detect_duplicates/detect_transfer_pairs/
        # resolve_check/get_pending_checks edge-case behavior (was EPIC-016
        # AC16.4, migration closeout continuation, #1663 / #1711) ──
        ACRecord(
            id="AC-reconciliation.consistency-checks.1",
            statement="detect_duplicates runs a global scan across all of the user's transactions when no statement_id is provided.",
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_global_scan_no_statement_id"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.consistency-checks.2",
            statement="detect_duplicates is idempotent — it does not create duplicate checks on re-run.",
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_idempotent_duplicate_detection"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.consistency-checks.3",
            statement="detect_transfer_pairs runs a global scan across all of the user's transactions when no statement_id is provided.",
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_global_scan_no_statement_id"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.consistency-checks.4",
            statement="resolve_check raises ValueError on an invalid resolution action.",
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_resolve_check_invalid_action_raises"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.consistency-checks.5",
            statement="resolve_check raises ValueError when the check is not found.",
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_resolve_check_not_found_raises"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.consistency-checks.6",
            statement="resolve_check sets FLAGGED status when action=flag.",
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_resolve_check_sets_flagged"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.consistency-checks.7",
            statement="get_pending_checks filters results by severity.",
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_get_pending_filters_by_severity"
            ),
            priority="P1",
            status="done",
        ),
        # ── group stage2-batch: Stage-2 batch approve blocking + typed contract
        # (was EPIC-016 AC16.22.3-4/AC16.35, migration closeout continuation,
        # #1663 / #1711) ──
        ACRecord(
            id="AC-reconciliation.stage2-batch.1",
            statement="A Stage-2 pending_review -> accepted transition is blocked while unresolved consistency checks exist.",
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_batch_approve_matches_blocked_by_unresolved_checks"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.stage2-batch.2",
            statement="A batch approve creates the missing journal entry exactly once on the accepted transition, never on pending_review.",
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_batch_approve_matches_creates_missing_entry_once"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.stage2-batch.3",
            statement="An empty batch approve returns the typed counters with no success field.",
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC16_35_1_batch_approve_empty_returns_typed_response"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.stage2-batch.4",
            statement="Unresolved consistency checks block batch approve with a 409 structured error.",
            test=(
                "apps/backend/tests/api/test_typed_contract_sweep.py"
                "::test_AC16_35_2_batch_approve_blocked_returns_409"
            ),
            priority="P1",
            status="done",
        ),
        # ── group review-hardening: Stage-2 queue requests the full unresolved
        # blocker set instead of truncating (was EPIC-016 AC16.32.3, migration
        # closeout continuation, #1663 / #1711) ──
        ACRecord(
            id="AC-reconciliation.review-hardening.1",
            statement="Stage-2 review check lists request the full unresolved blocker set needed to unblock batch approval, instead of silently truncating at the backend default page size.",
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC16_32_3_stage2_queue_returns_all_pending_checks"
            ),
            priority="P0",
            status="done",
        ),
        # ── group audit-anchors: reconciliation-to-ledger anchor referential
        # integrity (was EPIC-018 AC18.11.1, migration closeout continuation,
        # #1663 / #1711) ──
        ACRecord(
            id="AC-reconciliation.audit-anchors.1",
            statement="Reconciliation match journal-entry anchors are represented by a normalized link table that rejects missing or cross-user journal entries.",
            test=(
                "apps/backend/tests/infra/test_audit_anchor_schema_invariants.py"
                "::test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries"
            ),
            priority="P0",
            status="done",
        ),
        # ── group layer2-dedup: balance-aware Layer 2 dedup keeps many-to-one
        # matching correct (was EPIC-011 AC11.16.2, migration closeout
        # continuation, #1663 / #1711) ──
        ACRecord(
            id="AC-reconciliation.layer2-dedup.1",
            statement="Many-to-one matching works on Layer 2 when running balances keep batch transactions distinct.",
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py"
                "::test_execute_matching_many_to_one_batch"
            ),
            priority="P0",
            status="done",
        ),
        # ── group dwd-cutover: PR-B DWD (Layer 2) read cutover for transfer
        # detection (was EPIC-011 AC11.17, migration closeout continuation,
        # #1663 / #1711) ──
        ACRecord(
            id="AC-reconciliation.dwd-cutover.1",
            statement="Transfer OUT/IN detection resolves the custody account from the DWD (Layer 2) conform and creates the Processing entry under the Layer-2 read path.",
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py"
                "::test_transfer_out_creates_match"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.dwd-cutover.2",
            statement="Mixed transfer and normal transactions both reconcile correctly under the Layer-2 read path.",
            test=(
                "apps/backend/tests/reconciliation/test_transfer_integration.py"
                "::test_mixed_transactions_both_phases_execute"
            ),
            priority="P0",
            status="done",
        ),
        # ── group run-scoped-review: Stage-2 run-scoped review queue filtering
        # (was EPIC-019 AC19.11.1, migration closeout continuation, #1663 /
        # #1711) ──
        ACRecord(
            id="AC-reconciliation.run-scoped-review.1",
            statement="/review/run/{runId} uses a run-scoped Stage-2 queue and batch-approval API, so approving a run cannot approve pending matches from another workflow session or batch.",
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC19_11_1_stage2_run_queue_filters_by_run_id"
            ),
            priority="P0",
            status="done",
        ),
    ],
)
