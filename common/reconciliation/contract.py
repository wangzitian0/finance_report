"""The ``reconciliation`` package's machine-checkable :class:`PackageContract`."""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    ConceptRecord,
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
    # llm added #1670; ai_semantic_score itself relocated OUT of this package
    # and into llm (AC-llm.semantic-scoring.1, #1859 flagged the CODE-ONLY
    # violation — a genuine LLM call cannot live in a CODE-ONLY module per
    # common/meta/readme.md's Cross-tier MUST rule 2). extension/matching.py's
    # calculate_match_score still CONSUMES llm.ai_semantic_score as an
    # external advisory signal over its own build_reconciliation_prompt()
    # output (graceful fallback to a neutral 50 on any error — never a hard
    # dependency on model correctness); the llm edge stays declared here.
    # pricing re-added #1675: extension/fx_transfer.py + fx_transfer_discovery.py
    # read the FxConversion model, now published on pricing's root.
    # platform re-added #1675 D6: orm/reconciliation.py + orm/consistency_check.py
    # use the base ORM mixins (UUIDMixin/UserOwnedMixin/TimestampMixin), moved
    # from src/models/base.py to platform.orm.base.
    depends_on=[
        "audit",
        "extraction",
        "ledger",
        "llm",
        "observability",
        "platform",
        "pricing",
    ],
    roles=["base", "extension", "data"],
    units=[
        # ── taxonomy-only ORM units (module unset — the gate skips placement,
        # the #1675 idiom). The mapped classes live in orm/reconciliation.py
        # (#1675 D5): ledger's journal_entries is a bare FK column (the unused
        # journal_entry relationship() was removed per the 2026-07-11 ruling);
        # the atomic_transaction relationship survives until D4 moves
        # AtomicTransaction into extraction and de-navigates it. ──
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
        "AmountMismatchError",
        "CheckResolutionAction",
        "CheckStatus",
        "CheckType",
        "ConsistencyCheck",
        "ConsistencyCheckNotFoundError",
        "DEFAULT_CONFIG",
        "DEFAULT_RATE_TOLERANCE",
        "DEFAULT_TIME_WINDOW",
        "EntryCreationError",
        "FxTransferError",
        "InvalidCheckActionError",
        "MAX_COMBINATION_CANDIDATES",
        "MatchCandidate",
        "MatchNotFoundError",
        "MatchingContext",
        "RECONCILIATION_SEMANTIC_PROMPT",
        "ReconciliationConfig",
        "ReconciliationError",
        "ReconciliationMatch",
        "ReconciliationMatchJournalEntry",
        "ReconciliationStats",
        "ReconciliationStatus",
        "TransferLeg",
        "_candidate_is_better",
        "_find_many_to_one_candidates",
        "_find_normal_candidates",
        "_find_transfer_candidates",
        "_get_existing_active_match",
        "_get_pending_layer2_transactions",
        "_within_combination_tolerance",
        "accept_match",
        "accepted_transfer_txn_ids",
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
        "score_group",
        "score_single",
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
                "score_group adds a many_to_one_bonus (10 points) when scoring a "
                "batch-payment total against a single matching journal entry, pushing the "
                "composite score above the auto-accept threshold without coupled boolean flags."
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
                "apps/backend/tests/reporting/test_confidence_tier.py"
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
        # resolve_check/list_checks edge-case behavior (was EPIC-016
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
            statement="list_checks filters pending results by severity.",
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
        ACRecord(
            id="AC-reconciliation.review-hardening.2",
            statement=(
                "``accept_match`` validates journal-entry amounts against the "
                "transaction unconditionally: the public signature carries no "
                "bypass flag, and accepting a match whose entry total "
                "mismatches the transaction amount raises (entry balance "
                "validation is never skippable — red line, #1864 S1)."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_review_queue.py"
                "::test_AC_review_hardening_2_accept_match_validation_unconditional"
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
        # ── group consistency-checks (continued): Stage 2 dedup/transfer-pair
        # detection (was EPIC-016 AC16.2.1/AC16.2.2, #1821 Wave A
        # pending-package move; AC16.2.3 "batch approve blocked if unresolved
        # checks" was a duplicate of the already-migrated
        # AC-reconciliation.stage2-batch.1 citing the identical test and is
        # deleted without a new roadmap entry) ──
        ACRecord(
            id="AC-reconciliation.consistency-checks.8",
            statement="Deduplication detection accuracy is >= 95% on the consistency-check corpus.",
            # was AC16.2.1
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_detect_duplicates"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.consistency-checks.9",
            statement="Transfer-pair detection accuracy is >= 90% on the consistency-check corpus.",
            # was AC16.2.2
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_detect_transfer_pairs"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.consistency-checks.10",
            statement=(
                "``GET /statements/consistency-checks/list`` enforces a bounded "
                "page size: ``limit`` is declared with ``ge=1, le=200`` and an "
                "over-limit request is rejected with 422 instead of being "
                "accepted unbounded (#1864 S1)."
            ),
            test=(
                "apps/backend/tests/review/test_consistency_checks.py"
                "::test_AC_consistency_checks_10_list_endpoint_rejects_unbounded_limit"
            ),
            priority="P1",
            status="done",
        ),
        # ── group stage2-batch (continued): reconcile-referenced-entry /
        # idempotent-retry half not yet covered by .1-.4 (was EPIC-016
        # AC16.24.4, #1821 Wave A pending-package move) ──
        ACRecord(
            id="AC-reconciliation.stage2-batch.5",
            statement=(
                "Stage 2 batch approval reconciles a match against an "
                "existing referenced journal entry rather than creating a "
                "duplicate (the create-missing-entry-once half is already "
                "AC-reconciliation.stage2-batch.2)."
            ),
            # was AC16.24.4
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_batch_approve_matches_reconciles_referenced_entry"
            ),
            priority="P1",
            status="done",
        ),
        # ── group conflict-resolution: Stage 1 duplicate/transfer-pair
        # conflict gate + resolution endpoint (was EPIC-016 AC16.32.1,
        # AC16.34.1, AC16.34.2 backend halves, #1821 Wave A pending-package
        # move; each row also cites a frontend test that stays untracked by
        # this Python-only roadmap) ──
        ACRecord(
            id="AC-reconciliation.conflict-resolution.1",
            statement=(
                "Stage 1 approval and edit-approval are blocked while "
                "duplicate or transfer-pair conflict candidates remain "
                "unresolved."
            ),
            # was AC16.32.1
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.conflict-resolution.2",
            statement=(
                "POST /api/review/conflicts/{statement_id}/resolve records "
                "the reviewer's resolution; the Stage-1 approval guard "
                "honors it so a previously-blocked statement with duplicate/"
                "transfer-pair candidates can be approved, and an unknown "
                "statement returns 404 (also proven by "
                "test_AC16_34_1_resolve_conflicts_404_for_unknown_statement "
                "in the same file)."
            ),
            # was AC16.34.1
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC16_34_1_resolve_unblocks_stage1_approval"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.conflict-resolution.3",
            statement=(
                "A reject/reparse clears a prior conflict resolution so the "
                "fresh transaction set must be re-reviewed."
            ),
            # was AC16.34.2
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC16_34_2_reject_clears_conflict_resolution"
            ),
            priority="P0",
            status="done",
        ),
        # ── group candidate-matching: transfer/candidate-matching helper
        # unit tests (was EPIC-012 AC12.18.7 stub, #1821 Wave A
        # pending-package move) ──
        ACRecord(
            id="AC-reconciliation.candidate-matching.1",
            statement=(
                "_find_transfer_candidates, _find_normal_candidates, and "
                "_find_many_to_one_candidates (transfer/candidate-matching "
                "helpers) are covered by pure unit tests."
            ),
            # was AC12.18.7
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_scoring_helpers.py"
                "::test_find_transfer_candidates_returns_pair"
            ),
            priority="P2",
            status="done",
        ),
        # ── group conflict-resolution (continued): the conflicts endpoint's
        # response contract (was EPIC-016 AC16.13.13/AC16.13.14, #1821 Wave
        # A horizontal move) ──
        ACRecord(
            id="AC-reconciliation.conflict-resolution.4",
            statement=(
                "GET /api/review/conflicts/{statement_id} returns "
                "{duplicates: [...], transfer_pairs: [...]}, consumed by "
                "ConflictResolutionDialog."
            ),
            # was AC16.13.13
            test=(
                "apps/backend/tests/review/test_review_conflicts_router.py"
                "::test_review_conflicts_returns_duplicate_and_transfer_candidates"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.conflict-resolution.5",
            statement=(
                "The conflicts endpoint returns 404 when the statement_id is not found."
            ),
            # was AC16.13.14
            test=(
                "apps/backend/tests/review/test_review_conflicts_router.py"
                "::test_review_conflicts_returns_404_for_missing_statement"
            ),
            priority="P0",
            status="done",
        ),
        # NOTE: AC4.10.3 (CI hard-gates the reconciliation audit thresholds)
        # was evaluated for the #1821 Wave A horizontal move and REJECTED,
        # per EPIC-004's own pre-existing "Retained" note: its proving test
        # asserts a literal substring of the EPIC file's own text
        # ("10,000-transaction runtime targets"), making it a doc-governance
        # self-check, not reconciliation package behavior. Left as
        # `horizontal` in EPIC-004.
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-016
        # (two-stage-review-ui) ──
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.1",
            statement="Stage 2 UI supports batch operations",
            # was AC16.2.4
            test="apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.2.4/AC16.17.3 approves selected matches through the batch approval API",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.2",
            statement="Reconciliation entry pages render workbench and unmatched board components",
            # was AC16.16.4
            test="apps/frontend/src/__tests__/reconciliationEntryPages.test.tsx::AC16.16.4 renders workbench in reconciliation page",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.3",
            # Anchor corrected (#1821 Wave B CR fix): was pointing at the
            # loading-state test; the real error-fallback+retry proof is a
            # separate, more specific test in the same file.
            statement="Stage 2 review queue shows failure fallback and supports retry",
            # was AC16.17.1
            test="apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.17.1 shows an error fallback and retries the Stage 2 queue fetch",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.4",
            # Anchor corrected (#1821 Wave B CR fix): was pointing at the
            # empty-states test; the real unresolved-checks-disable-approval
            # proof is a separate, more specific test in the same file.
            statement="Stage 2 review queue indicates unresolved checks and disables batch approval",
            # was AC16.17.2
            test="apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.2.3/AC16.17.2 disables batch approval while unresolved checks remain",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.5",
            # Anchor + statement corrected (#1821 Wave B CR fix): the original
            # statement claimed both reject and approve, but the anchored test
            # only proved approve (and duplicated the exact test already cited
            # by AC-reconciliation.fe-stage2-review.1 / was AC16.2.4). Narrowed
            # to the reject half, proven by its own distinct test; the approve
            # half stays proven by fe-stage2-review.1.
            statement=(
                "Stage 2 review queue rejects selected matches through the "
                "batch rejection API (the batch approve half of this "
                "workflow is proven by AC-reconciliation.fe-stage2-review.1)"
            ),
            # was AC16.17.3
            test="apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.17.3 rejects selected matches through the batch rejection API",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.6",
            statement="Stage 2 review queue resolves consistency checks through dialog actions",
            # was AC16.17.4
            test="apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.17.4 resolves a consistency check from the dialog actions",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.7",
            statement="Reconciliation workbench loads stats and pending queue with default selection",
            # was AC16.20.1
            test="apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx::AC16.20.1 loads stats and pending queue with default selection",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.8",
            statement="Reconciliation workbench triggers run, accept, reject, and batch accept APIs",
            # was AC16.20.2
            test="apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx::AC16.20.2 triggers run, batch, accept, and reject APIs",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.9",
            statement="Unmatched board loads transactions and creates journal entry for selected item",
            # was AC16.20.3
            test="apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC16.20.3 loads unmatched items and creates entry",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.10",
            statement="Unmatched board flag and ignore actions update list and local state",
            # was AC16.20.4
            test="apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC16.20.4 AC16.31.4 supports local flag and hide actions",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.11",
            statement="Score distribution renders 0% height for buckets with value 0",
            # was AC16.20.6
            test="apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx::AC16.20.6 score distribution renders 0% height for buckets with value 0",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.12",
            statement="Review, journal details, and mobile navigation surfaces do not create document-level horizontal scrolling at phone widths",
            # was AC16.25.1
            test="apps/frontend/playwright/mobile-ux.spec.ts::AC16.25.1 mobile review routes avoid document horizontal scrolling",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.13",
            statement="AI suggestion review queue exposes accept, reject, correction, and edit-accept actions directly in a mobile card layout",
            # was AC16.25.2
            test="apps/frontend/playwright/mobile-ux.spec.ts::AC16.25.2 AI suggestions mobile cards expose feedback actions",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.14",
            statement="Stage 2 pending matches use selectable mobile cards with direct reject and approve selected actions visible without horizontal dragging",
            # was AC16.26.2
            test="apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC8.13.76/AC16.26.2 mobile queue renders selectable match cards and batch actions",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.15",
            statement="Stage 2 run review keeps the run approval gate and pending match workflow usable at phone widths without document-level horizontal scrolling",
            # was AC16.26.3
            test="apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC16.26.3 mobile run review preserves approval gate and pending match workflow",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.16",
            statement="Stage 1 and Stage 2 mobile review lists render without JavaScript breakpoint gating that can create first-paint blank content",
            # was AC16.27.1
            test="apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC16.27.1 keeps mobile pending-match cards in the DOM without matchMedia gating",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.17",
            statement="Stage 2 desktop review keeps pending match rows readable at 1440px with the sidebar visible without local horizontal clipping",
            # was AC16.27.3
            test="apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC8.13.82/AC16.27.3 exposes a fixed desktop pending-match region for responsive UX proofs",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.18",
            statement="Conflict resolution dialog `<ConflictResolutionDialog />` opens when backend returns duplicate or transfer-pair candidates; user can pick canonical row or link the pair",
            # was AC16.23.3
            test="apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.19",
            statement="Stage 2 listing exposes severity filter, check-type filter, and score-range slider; filters persist in URL query string",
            # was AC16.23.4
            test="apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC16.23.4/AC8.13.48 persists Stage 2 filters in the URL while approving after filter changes",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.20",
            statement="Stage 2 run-level page at `/review/run/[runId]` summarizes duplicate, transfer-pair, and anomaly checks for a batch",
            # was AC16.24.1
            test="apps/frontend/src/__tests__/reviewRunPage.test.tsx::AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.21",
            statement="Stage 2 run-level page shows unresolved transfer and Processing pending counts, then disables run approval while either remains unresolved",
            # was AC16.24.2
            test="apps/frontend/src/__tests__/reviewRunPage.test.tsx::AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.22",
            statement="Stage 2 run-level approval submits all pending matches through the batch approval API after checks are resolved",
            # was AC16.24.3
            test="apps/frontend/src/__tests__/reviewRunPage.test.tsx::AC16.24.3 approves all pending matches through the batch approval API",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.23",
            statement="Stage 1 conflict dialog loads duplicate and transfer-pair candidates from `GET /api/review/conflicts/{statement_id}` instead of fake review payload fields",
            # was AC16.31.1
            test="apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.24",
            statement="Stage 2 run review page states that it uses the shared Stage 2 queue endpoint when no run-scoped queue API exists",
            # was AC16.31.3
            test="apps/frontend/src/__tests__/reviewRunPage.test.tsx::AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.25",
            statement="Unmatched transaction local flag/hide actions are labeled as local-only triage and batch create requires confirmation",
            # was AC16.31.4
            test="apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC16.20.4 AC16.31.4 supports local flag and hide actions",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.26",
            statement="Stage 2 review check lists request the full unresolved blocker set needed to unblock batch approval instead of silently truncating at the backend default page size. Backend half (`test_AC16_32_3_stage2_queue_returns_all_pending_checks`) migrated to the `reconciliation` package roadmap as `AC-reconciliation.review-hardening.1` (migration closeout continuation, #1663 / #1711); the frontend half stays here.",
            # was AC16.32.3
            test="apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.32.3 requests an expanded consistency-check limit for unblockable queues",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.27",
            statement="The ConflictResolutionDialog `Resolve` / `Link Pair` buttons call the resolve endpoint with the matching action and disable while a resolution is in flight (previously dead, no-op buttons)",
            # was AC16.34.3
            test="apps/frontend/src/__tests__/ConflictResolutionDialog.test.tsx::AC16.34.3 Resolve and Link Pair buttons call onResolve with the matching action",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.28",
            statement="The dedicated `/review` route renders the Stage-2 review queue standalone",
            # was AC16.36.1
            test="apps/frontend/src/__tests__/reviewLandingPage.test.tsx::AC16.36.1 renders the Stage-2 review queue as a standalone page",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-stage2-review.29",
            statement="The dedicated route loads the global queue (no run filter)",
            # was AC16.36.2
            test="apps/frontend/src/__tests__/reviewLandingPage.test.tsx::AC16.36.2 loads the global queue (no run filter) on the dedicated route",
            priority="P2",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-022
        # (everyday-user-ia) and EPIC-005 (reporting-visualization) ──
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.1",
            statement="`/review/ai-suggestions` is reachable from AI Settings, so the AI-suggestion review surface is not orphaned",
            # was AC22.4.3
            test="apps/frontend/src/__tests__/aiSettingsPage.test.tsx::AC22.4.3 links to the AI suggestion review surface so it is not orphaned",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.2",
            statement="E2E: a user with Stage 1 and Stage 2 attention sees both in the notification center and can open each detail surface",
            # was AC22.4.5
            test="apps/frontend/playwright/epic022-attention-journey.spec.ts::${label}: both Stage 1 and Stage 2 attention surface in the notification center with deep links",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.3",
            statement="The `/attention` page folds the open attention sources (Stage 1 statement review, reconciliation review, unmatched transactions, stalled processing transfers) into a single list sorted by ascending confidence, each row deep-linking to its action surface, with an all-clear empty state when nothing needs attention",
            # was AC22.6.1
            test="apps/frontend/src/__tests__/attention.test.ts::AC22.6.1 folds the open attention sources into one list sorted by ascending confidence",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.4",
            statement="The Home renders a trust meter (trusted / needs-confirmation / low-confidence counts) derived from the same attention model and linking to `/attention`, and stays silent when nothing needs attention",
            # was AC22.6.2
            test="apps/frontend/src/__tests__/attention.test.ts::AC22.6.2 summarizes trust into trusted / needs-confirmation / low-confidence buckets",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.5",
            statement="Desktop and mobile smoke covers the `/attention` queue and the Home trust meter without layout overflow",
            # was AC22.6.4
            test="apps/frontend/playwright/attention-surface.spec.ts::${label} renders the attention queue ranked by confidence without overflow",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.6",
            statement="Each attention-queue item surfaces a plain-language reason it was flagged — distinct per cause — alongside its confidence score",
            # was AC22.11.2
            test="apps/frontend/src/__tests__/attention.test.ts::AC22.11.2 every item explains why it was flagged",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.7",
            statement="Attention-origin action links preserve `from=attention`, and the linked review/processing destinations render a return link to `/attention` while direct-entry notification/statement fallbacks remain unchanged",
            # was AC22.11.3
            test="apps/frontend/src/__tests__/attentionQueue.test.tsx::AC22.6.1 AC22.11.3 AC22.12.4 renders the open attention items with readable reasons and action links",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.8",
            statement="Attention-queue reason text uses the normal muted content token, not a lower-opacity muted variant, so low-confidence explanations keep readable contrast",
            # was AC22.12.4
            test="apps/frontend/src/__tests__/attentionQueue.test.tsx::AC22.6.1 AC22.11.3 AC22.12.4 renders the open attention items with readable reasons and action links",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-ia-reconciliation.9",
            statement="The Stage 2 review queue is composed from extracted sub-components (the match row/card and the queue controls) with unchanged review behavior",
            # was AC22.17.2
            test="apps/frontend/src/__tests__/stage2ReviewQueueParts.test.tsx::AC22.17.2 PendingMatchesPanel renders mobile + desktop rows and wires selection/batch callbacks",
            priority="P1",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ACRecord(
            id="AC-reconciliation.fe-remainder-reconciliation.1",
            statement="The unmatched transaction board models unmatched amounts as shared `MoneyValue` payloads and renders queue/detail/created-entry amounts through Decimal-safe currency formatting, not JavaScript number locale formatting",
            # was AC4.11.1
            test="apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC4.11.1 renders unmatched monetary amounts with Decimal-safe currency formatting",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-remainder-reconciliation.2",
            statement="AI Suggestion Review Queue page `/review/ai-suggestions` lists pending AI classifications and AI reconciliation matches in score band 60-84 with `{transaction, suggested_category_or_match, ai_score, ai_reasoning}`",
            # was AC18.5.3
            test="apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.3 — AI Suggestion Review Queue page renders suggestions",
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.fe-remainder-reconciliation.3",
            statement="Queue actions: `Accept`, `Reject`, `Edit-then-Accept`; each action calls `POST /api/ai/feedback` with `{suggestion_id, action, corrected_value?}` to feed the feedback loop",
            # was AC18.5.4
            test="apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.4 — feedback POST on accept/reject/edit",
            priority="P2",
            status="done",
        ),
        # ── closing the two remaining EPIC-018 AC18.3.x "Untested"
        # pending-package rows now that a real test exercises calculate_match_score's
        # hybrid-AI branch directly (AC18.3.1's separate tier-boundary blocker is
        # unrelated and untouched — see docs/project/EPIC-018.ai-driven-pipeline.md) ──
        ACRecord(
            id="AC-reconciliation.1803.1",
            statement="Hybrid scoring: calculate_match_score blends 0.7 * algorithmic + 0.3 * AI semantic score, applied only when the pre-AI weighted total is in the 60-84 review band.",
            # was AC18.3.2
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_hybrid_scoring.py"
                "::test_calculate_match_score_applies_hybrid_ai_scoring"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.1803.2",
            statement="Feature flag ENABLE_AI_RECONCILIATION gates the hybrid-AI branch: when off, calculate_match_score never calls the AI semantic scorer, even for a pre-AI total in the 60-84 band.",
            # was AC18.3.3
            test=(
                "apps/backend/tests/reconciliation/test_reconciliation_hybrid_scoring.py"
                "::test_calculate_match_score_flag_off_skips_ai_scoring"
            ),
            priority="P1",
            status="done",
        ),
        # #1866 PR-A: reconciliation/ledger signature surgery.  The split is
        # intentionally package-local: reconciliation owns orchestration,
        # errors, and the similarity policy; ledger separately owns posting
        # and balance-space guarantees in AC-ledger.signature.*.
        ACRecord(
            id="AC-reconciliation.signature-surgery.1",
            statement=(
                "Public reconciliation extension functions have fully annotated signatures "
                "and no more than eight parameters; matching phases receive a typed context."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_signature_surgery.py"
                "::test_public_reconciliation_signatures_are_typed_and_bounded"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.signature-surgery.2",
            statement=(
                "execute_matching drives the ReconciliationRepository port and each phase "
                "returns its created matches instead of mutating an output list."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_signature_surgery.py"
                "::test_matching_phases_return_created_matches"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.signature-surgery.3",
            statement=(
                "Normal single-/multi-entry scoring and many-to-one group scoring use distinct typed entry points; "
                "normal multi-entry candidates retain widened amount tolerance, and the AI switch is supplied "
                "through ReconciliationConfig rather than read in scoring."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_signature_surgery.py"
                "::test_scoring_has_explicit_modes_and_no_hidden_environment_switch"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.signature-surgery.4",
            statement=(
                "Reconciliation failures use typed domain errors, router status mapping does "
                "not inspect exception text, and consistency-check actions are enum-typed."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_signature_surgery.py"
                "::test_reconciliation_errors_and_resolve_actions_are_typed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.signature-surgery.5",
            statement=(
                "Reconciliation owns the sole SequenceMatcher description-similarity kernel; "
                "ledger transfer pairing consumes that score while retaining ledger weights."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_signature_surgery.py"
                "::test_description_similarity_has_one_owner_and_both_consumers_agree"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-reconciliation.signature-surgery.6",
            statement=(
                "Transfer detection propagates processing-account currency "
                "conflicts instead of reporting a successful no-op run."
            ),
            test=(
                "apps/backend/tests/reconciliation/test_signature_surgery.py"
                "::test_transfer_detection_surfaces_processing_currency_conflicts"
            ),
            priority="P0",
            status="done",
        ),
    ],
    concepts=[
        ConceptRecord(
            key="reconciliation_state_machine",
            owner="common/reconciliation/readme.md#state-machine",
            description="pending → auto_accepted | pending_review → accepted | rejected.",
            cross_refs=[
                "common/reconciliation/confirmation-workflow.md",
                "common/reconciliation/reconciliation.md",
            ],
        ),
        ConceptRecord(
            key="reconciliation_thresholds",
            owner="common/reconciliation/readme.md#thresholds",
            description="Score ≥85 auto-accept; 60-84 review; <60 unmatched.",
            cross_refs=[
                "docs/agents/red-lines.md",
                "common/reconciliation/reconciliation.md",
            ],
        ),
    ],
)
