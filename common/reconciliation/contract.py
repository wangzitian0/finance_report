"""The ``reconciliation`` package's machine-checkable :class:`PackageContract`."""

from __future__ import annotations

from common.meta.package_contract import (
    ac,
    ConceptRecord,
    ContextRelation,
    ContextScope,
    GovernanceGuarantee,
    GovernanceInitiative,
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
    context=ContextScope(
        purpose="Own the confidence-scored matching and review lifecycle that links independent source transactions to ledger facts without merging either source.",
        in_scope=[
            "ReconciliationMatch lifecycle, candidate generation, scoring, and review decisions",
            "many-to-one and FX transfer matching, anomaly and consistency diagnostics",
            "reconciliation statistics and match-outcome evidence",
        ],
        out_of_scope=[
            "source-document and AtomicTransaction ownership",
            "journal-entry ownership, double-entry posting, and price-observation resolution",
            "shared money, model-provider, telemetry, persistence, and workflow ownership",
        ],
    ),
    relationships=[
        ContextRelation(
            provider="audit",
            consumer="reconciliation",
            mode="published-language",
            reason="Uses audit monetary, ratio, provenance, and promotion language for matching evidence.",
        ),
        ContextRelation(
            provider="extraction",
            consumer="reconciliation",
            mode="projection",
            reason="Reads extraction-owned AtomicTransaction facts and reviewed dispositions as one side of matching without owning source parsing or provenance.",
        ),
        ContextRelation(
            provider="ledger",
            consumer="reconciliation",
            mode="published-language",
            reason="Uses ledger journal/account language as the independent accounting side of a match without posting or owning journal facts.",
        ),
        ContextRelation(
            provider="llm",
            consumer="reconciliation",
            mode="published-language",
            reason="Uses the LLM semantic-score facade as an advisory signal while the match decision and safe fallback remain reconciliation-owned.",
        ),
        ContextRelation(
            provider="observability",
            consumer="reconciliation",
            mode="published-language",
            reason="Uses published safe logging and reconciliation-outcome telemetry language.",
        ),
        ContextRelation(
            provider="platform",
            consumer="reconciliation",
            mode="composition",
            reason="Uses platform persistence mixins without owning generic persistence behavior.",
        ),
        ContextRelation(
            provider="pricing",
            consumer="reconciliation",
            mode="published-language",
            reason="Uses pricing FX-conversion language for cross-currency transfer matching.",
        ),
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
            kind=Kind.DOMAIN_SERVICE,
            module="extension/config.py",
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
            name="persist_transfer_pairs",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/transfer_pairs.py",
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
            module="extension/candidate_policy.py",
        ),
        Unit(
            name="build_many_to_one_groups",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/candidate_policy.py",
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
        Unit(
            name="ReviewedDispositionCommand",
            kind=Kind.VALUE_OBJECT,
            module="base/reviewed_disposition.py",
        ),
        Unit(
            name="ReviewedDispositionDependencies",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/reviewed_disposition.py",
        ),
        Unit(
            name="submit_reviewed_disposition",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/reviewed_disposition.py",
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
        "ReviewedDispositionCommand",
        "ReviewedDispositionDependencies",
        "ReviewedDispositionError",
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
        "count_pending_review_items",
        "derive_reconciliation_score_tier",
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
        "submit_reviewed_disposition",
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
        ac(
            "AC-reconciliation.rejection-recovery.4",
            "Historical retired or superseded source facts cannot reenter unmatched queues, automatic candidates, or direct reviewed posting.",
            "apps/backend/tests/reconciliation/test_rejection_recovery.py::test_historical_source_transactions_are_not_actionable",
        ),
        ac(
            "AC-reconciliation.rejection-recovery.1",
            "Rejected suggestions remain historical evidence while the source transaction becomes manually actionable.",
            "apps/backend/tests/reconciliation/test_rejection_recovery.py::test_rejected_match_can_be_reviewed",
        ),
        ac(
            "AC-reconciliation.rejection-recovery.2",
            "Active matches cannot be bypassed and background reruns honor rejected suggestions.",
            "apps/backend/tests/reconciliation/test_rejection_recovery.py::test_active_match_blocks_and_rerun_honors_rejection",
        ),
        ac(
            "AC-reconciliation.rejection-recovery.3",
            "Concurrent manual recovery creates at most one source journal command.",
            "apps/backend/tests/reconciliation/test_rejection_recovery.py::test_concurrent_review_after_rejection",
        ),
        ac(
            "AC-reconciliation.candidate-policy.1",
            "Live matching and the deterministic accuracy audit share candidate enumeration, rule scoring and source-rank ordering; journal evidence precedes transfer-keyword fallback in both paths.",
            "apps/backend/tests/reconciliation/test_candidate_policy.py::test_live_and_audit_choose_the_same_evidence",
            proof_kind="property",
        ),
        ac(
            "AC-reconciliation.config-boundary.1",
            "Configuration values have no direct runtime or ledger dependency; retired base behaviors have exactly one extension owner.",
            "tests/tooling/test_reconciliation_config_boundary.py::test_configuration_ownership_is_explicit",
            proof_kind="property",
        ),
        ac(
            "AC-reconciliation.config-boundary.2",
            "The runtime loader reads the documented backend configuration file, parses YAML booleans explicitly, preserves defaults/YAML/environment precedence and cache reload semantics, and keeps the published interface.",
            "apps/backend/tests/reconciliation/test_config_boundary.py::test_runtime_configuration_file_precedence_and_cache",
            proof_kind="property",
        ),
        ac(
            "AC-reconciliation.config-boundary.3",
            "Relocated entry readers preserve currency-filtered Money totals, ledger balance validation, and deterministic source-rank tie breaking.",
            "apps/backend/tests/reconciliation/test_config_boundary.py::test_entry_readers_preserve_money_and_candidate_semantics",
            proof_kind="property",
        ),
        ac(
            "AC-reconciliation.match.1",
            "At most one active ReconciliationMatch exists per AtomicTransaction; newer matches supersede prior active rows.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_execute_matching_many_to_one_keeps_same_existing_match",
        ),
        ac(
            "AC-reconciliation.match.2",
            "Reconciliation status follows PENDING_REVIEW→ACCEPTED/AUTO_ACCEPTED/REJECTED→SUPERSEDED and posted entries are immutable.",
            "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py::test_normal_matching_auto_accept_reconciles_entries",
        ),
        ac(
            "AC-reconciliation.score.1",
            "Match score is weighted composite amount/date/description/business/history in [0,100].",
            "apps/backend/tests/reconciliation/test_reconciliation_scoring.py::test_weighted_total_and_balance_helpers",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.score.2",
            "Scores at/above auto-accept threshold auto-accept; review-band scores route to PENDING_REVIEW.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_auto_accept_threshold",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.stats.1",
            "Stats projection match_rate is consistent with active accepted/auto-accepted match states.",
            "apps/backend/tests/reconciliation/test_reconciliation_stats.py::test_get_reconciliation_stats_dedups_multiple_accepted_matches",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.txn.1",
            "ReconciliationMatch references AtomicTransaction and JournalEntry by id only (no cross-domain FK).",
            "apps/backend/tests/infra/test_audit_anchor_schema_invariants.py::test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries",
        ),
        # ============================= matching-core (AC4.1) =============================
        ac(
            "AC-reconciliation.matching-core.1",
            "score_amount returns 100 for an exact amount match and graduated lower scores (90/70/40/0) as the absolute and percentage delta from the target amount widens.",
            "apps/backend/tests/reconciliation/test_reconciliation_scoring.py::test_score_amount_branches",
        ),
        ac(
            "AC-reconciliation.matching-core.2",
            "score_date returns 100 for a same-day match and graduated lower scores (90/75/0) as the day gap widens, with a same-window cross-month bonus over a plain in-month gap of the same size.",
            "apps/backend/tests/reconciliation/test_reconciliation_scoring.py::test_score_date_branches",
        ),
        ac(
            "AC-reconciliation.matching-core.3",
            "score_amount applies tiered tolerance bands (exact, 0.5%-or-tighter, $5 flat, multi-entry tolerance, ratio-based fallback) rather than a single pass/fail cutoff, including scoring a zero-amount transaction as 0.",
            "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py::test_score_amount_tiers",
        ),
        ac(
            "AC-reconciliation.matching-core.4",
            "score_description normalizes text (case/punctuation-insensitive) and returns >=95 for near-identical descriptions differing only by case, while returning 0 for None, blank, or punctuation-only inputs.",
            "apps/backend/tests/reconciliation/test_reconciliation_scoring.py::test_normalize_and_description_scoring",
            priority="P1",
        ),
        # ============================= group-matching (AC4.2) =============================
        ac(
            "AC-reconciliation.group-matching.1",
            "execute_matching groups same-day, same-description bank transactions that sum to one manual journal entry's amount into a many-to-one match and auto-accepts all of them.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_execute_matching_many_to_one_group",
        ),
        ac(
            "AC-reconciliation.group-matching.2",
            "score_group adds a many_to_one_bonus (10 points) when scoring a batch-payment total against a single matching journal entry, pushing the composite score above the auto-accept threshold without coupled boolean flags.",
            "apps/backend/tests/reconciliation/test_reconciliation_scoring.py::test_calculate_match_score_many_to_one_bonus",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.group-matching.3",
            "execute_matching finds the combination of multiple journal entries (one-to-many split) whose lines sum to a single transaction's amount, records a multi_entry count in the score breakdown, and auto-accepts the best combination.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_execute_matching_multi_entry_combinations",
            priority="P1",
        ),
        # ============================= review-queue (AC4.3) =============================
        # NB: old AC4.3.1 is NOT here -- it is a duplicate of the already-migrated
        # AC-reconciliation.score.2 (identical test: test_auto_accept_threshold).
        ac(
            "AC-reconciliation.review-queue.1",
            "accept_match, reject_match, and batch_accept transition PENDING_REVIEW matches to ACCEPTED/REJECTED/ACCEPTED respectively, and accepting a match reconciles its linked journal entry (status -> RECONCILED).",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_review_queue_actions_and_entry_creation",
        ),
        ac(
            "AC-reconciliation.review-queue.2",
            "The reconciliation router's accept_match/reject_match/batch_accept service calls transition matches to ACCEPTED/REJECTED/ACCEPTED and batch_accept reports the accepted count.",
            "apps/backend/tests/reconciliation/test_reconciliation_router_additional.py::test_accept_reject_batch_accept",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.3",
            "POST /reconciliation/matches/{id}/accept returns 200 with the match status set to ACCEPTED.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_accept_match_success",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.4",
            "POST /reconciliation/matches/{id}/accept for a non-existent match id returns 404 with 'Match' in the error detail.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_accept_match_not_found",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.5",
            "POST /reconciliation/matches/{id}/reject returns 200 with the match status set to REJECTED.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_reject_match_success",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.6",
            "POST /reconciliation/matches/{id}/reject for a non-existent match id returns 404 with 'Match' in the error detail.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_reject_match_not_found",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.7",
            "GET /reconciliation/stats returns 200 with a stats payload containing total/matched/unmatched counts, match_rate, and score_distribution.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_reconciliation_stats_success",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.8",
            "GET /reconciliation/unmatched returns 200 with a paginated items/total payload listing unmatched transactions.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_list_unmatched_success",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.9",
            "POST /reconciliation/unmatched/{txn_id}/reviewed-disposition creates one source-anchored journal entry only when the user supplies an explicit economic intent, compatible active counter-account, category where P&L applies, and non-blank review rationale; invalid semantic input fails closed at the API boundary.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_submit_reviewed_disposition_from_unmatched_success",
        ),
        ac(
            "AC-reconciliation.review-queue.10",
            "POST /reconciliation/unmatched/{txn_id}/reviewed-disposition for a non-existent transaction id returns 404 with 'Transaction' in the error detail.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_submit_reviewed_disposition_not_found",
        ),
        ac(
            "AC-reconciliation.review-queue.11",
            "Reconciliation endpoints reject unauthenticated requests with 401 (verified via GET /reconciliation/stats on an unauthenticated client).",
            "apps/backend/tests/api/test_reconciliation_router.py::test_unauthenticated_access",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.12",
            "GET /reconciliation/unmatched scopes results to the authenticated user and never returns another user's transactions.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_user_isolation",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.review-queue.13",
            "The legacy unparameterized create-entry and batch-create endpoints are absent, so an unmatched source transaction cannot become a journal entry through a default account or Uncategorized fallback.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_legacy_unmatched_entry_routes_are_absent",
        ),
        ac(
            "AC-reconciliation.review-queue.14",
            "accept_match reconciles only a pre-existing linked source entry; without one it leaves the match pending and never creates a journal entry or rewrites immutable source provenance.",
            "apps/backend/tests/reconciliation/test_review_queue.py::test_accept_match_without_reviewed_disposition_requires_entry_context",
        ),
        ac(
            "AC-reconciliation.review-queue.15",
            "GET /reconciliation/unmatched accepts an optional statement_id and then returns only unresolved transactions anchored to that user-owned statement; an unknown or foreign statement fails closed without exposing another user's queue.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_AC_reconciliation_review_queue_15_filters_unmatched_by_statement",
        ),
        ac(
            "AC-reconciliation.reviewed-disposition.1",
            "A reviewed-disposition command is idempotent only for the same immutable normalized intent, counter-account, applicable category, and rationale/evidence digest; changing any semantic field after posting conflicts without superseding its TraceRecord decision or entry.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_reviewed_disposition_is_idempotent_and_rejects_account_intent_conflict",
        ),
        ac(
            "AC-reconciliation.reviewed-disposition.2",
            "The unmatched-transaction UI requires intent, a compatible counter account, required P&L category, and rationale, then calls only the reviewed-disposition endpoint; it exposes no raw create-entry or batch-create action.",
            "apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC-reconciliation.reviewed-disposition.2 / AC-reconciliation.fe-stage2-review.9 submits an explicit reviewed command instead of a raw create action",
        ),
        ac(
            "AC-reconciliation.reviewed-disposition.3",
            "A reviewed-disposition command rejects an unmatched transfer or a transaction that already has a current non-rejected reconciliation match, and neither rejection writes a source journal entry.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_reviewed_disposition_rejects_unmatched_bypasses_without_persisting",
        ),
        ac(
            "AC-reconciliation.reviewed-disposition.4",
            "The injected TraceEmitter appends the manual observation and CODE-ONLY disposition/invariant TraceRecord causal set in the same caller-owned transaction as posting; trace or posting failure rolls back the complete causal set and journal entry.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_reviewed_disposition_rolls_back_its_decision_when_posting_fails",
        ),
        ac(
            "AC-reconciliation.reviewed-disposition.5",
            "A capability-level structural lock enumerates reconciliation posting and match side effects: the reviewed-disposition service requires an injected TraceEmitter and DispositionPolicy, while raw posting, match-side source promotion, and fabricated-confidence classification surrogates are absent.",
            "apps/backend/tests/reconciliation/test_signature_surgery.py::test_unmatched_posting_has_one_reviewed_writer_boundary",
        ),
        # ============================= performance (AC4.4) =============================
        ac(
            "AC-reconciliation.performance.1",
            "execute_matching processes 100 transactions against 20 candidate entries in under 5 seconds (representative sample standing in for the 10,000-transaction target).",
            "apps/backend/tests/reconciliation/test_performance.py::test_batch_1000_transactions_reasonable_time",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.performance.2",
            "calculate_match_score still scores a transaction dated one day before month-end against an entry dated the first of the next month at >=70 (cross-month date proximity).",
            "apps/backend/tests/reconciliation/test_performance.py::test_month_end_to_month_start_match",
            priority="P1",
        ),
        # ============================= anomaly-detection (AC4.5) =============================
        ac(
            "AC-reconciliation.anomaly-detection.1",
            "detect_anomalies flags LARGE_AMOUNT and FREQUENCY_SPIKE for an outsized transaction against a merchant with recent history, and flags NEW_MERCHANT and WEEKEND_LARGE for a large transaction on a weekend with no prior merchant history.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_detect_anomalies_flags_expected_patterns",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.anomaly-detection.2",
            "GET /reconciliation/transactions/{txn_id}/anomalies for a non-existent transaction id returns 404 with 'Transaction' in the error detail.",
            "apps/backend/tests/api/test_reconciliation_router.py::test_list_anomalies_not_found",
            priority="P1",
        ),
        # ============================= source-type-transfer (AC4.6) =============================
        # NB: old AC4.6.4 is NOT here -- its test/file were not found under any name (flagged).
        ac(
            "AC-reconciliation.source-type-transfer.1",
            "score_amount's absolute tolerance boundary holds exactly at 0.10: a $0.10 delta still scores 90 while a $0.11 delta scores below 90.",
            "apps/backend/tests/reconciliation/test_reconciliation_scoring.py::test_amount_tolerance_0_10_boundary",
        ),
        ac(
            "AC-reconciliation.source-type-transfer.2",
            "execute_matching matches an OUT transfer transaction and its paired IN transaction (within days, opposite direction, same amount) each to their own generated system Processing entry and auto-accepts both without double-booking one side against the other.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_transfer_pair_not_double_counted",
        ),
        ac(
            "AC-reconciliation.source-type-transfer.3",
            "When two candidate journal entries tie on score, _candidate_is_better deterministically prefers the MANUAL-sourced entry over the AUTO_PARSED one, recording a higher source_type_winner_rank than source_type_loser_rank in the breakdown.",
            "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py::test_AC4_6_3_candidate_tie_breaker_prefers_higher_source_trust",
        ),
        ac(
            "AC-reconciliation.source-type-transfer.4",
            "execute_matching's conflict resolution assigns a source_type_winner_rank of 4.0 to a MANUAL entry and source_type_loser_rank of 1.0 to a same-score AUTO_PARSED entry, so the manual entry wins the match end to end.",
            "apps/backend/tests/reconciliation/test_source_type.py::test_manual_wins_conflict_resolution",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.source-type-transfer.5",
            "The Stage-1 duplicate guard does NOT flag two transactions identical in date/description/amount/direction as duplicate candidates when their balance_after (running balance) values differ.",
            "apps/backend/tests/review/test_statement_validation.py::test_duplicate_guard_distinguishes_by_balance_after",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.source-type-transfer.6",
            "The Stage-1 duplicate guard still flags two transactions identical in date/description/amount/direction as duplicate candidates when balance_after is equal on both or absent on both (ambiguous, needs review).",
            "apps/backend/tests/review/test_statement_validation.py::test_duplicate_guard_flags_when_balance_after_equal_or_absent",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.source-type-transfer.7",
            "execute_matching's layer-2 matching path stamps atomic_txn_id on the resulting ReconciliationMatch when a many-to-one group is auto-accepted.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_execute_matching_many_to_one_layer2_sets_atomic_txn_id",
            priority="P1",
        ),
        # ============================= recovered-coverage (AC4.7) =============================
        ac(
            "AC-reconciliation.recovered-coverage.1",
            "POST /corrections persists a category correction for a transaction and GET /corrections/stats subsequently reports it in total_corrections and top_corrections.",
            "apps/backend/tests/api/test_corrections_router.py::test_post_create_correction_and_stats",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.recovered-coverage.2",
            "execute_matching's phase-2 combination search skips a 3-entry combination when one of the candidate entries is unbalanced, so no match is produced.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_execute_matching_three_entry_combination_skips_unbalanced_member",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.recovered-coverage.3",
            "execute_matching's layer-2 path records an atomic match for a single-entry candidate and supports transfer-pair logging within the same phase.",
            "apps/backend/tests/reconciliation/test_reconciliation_engine.py::test_execute_matching_layer2_atomic_match_and_transfer_pair_logging",
            priority="P1",
        ),
        # ============================= bank-side-amount (AC4.9) =============================
        ac(
            "AC-reconciliation.bank-side-amount.1",
            "calculate_match_score computes the 'amount' score dimension from the bank/cash account's line amount (not the total of all entry debits) so a split entry with clearing/payable lines still yields a 100.0 amount score for a matching outflow.",
            "apps/backend/tests/reconciliation/test_reconciliation_financial_logic.py::test_AC4_9_1_entry_total_uses_bank_side_line_for_outflow",
        ),
        ac(
            "AC-reconciliation.bank-side-amount.2",
            "Retrying accept_match_service on an already-ACCEPTED match returns the same version and the same journal_entry_ids without creating a duplicate journal entry.",
            "apps/backend/tests/api/test_statements_router.py::test_accept_match_retry_is_idempotent_after_success",
        ),
        ac(
            "AC-reconciliation.bank-side-amount.3",
            "create_entry_from_txn with auto_post=True raises ValueError('... not active ...') and creates no journal entry when the statement's linked account is inactive.",
            "apps/backend/tests/api/test_statements_router.py::test_create_entry_from_txn_auto_post_rejects_inactive_statement_account",
        ),
        ac(
            "AC-reconciliation.bank-side-amount.4",
            "get_stage2_review_queue returns a pending PENDING_REVIEW match with a confidence_tier of MEDIUM derived from its match_score (75).",
            "apps/backend/tests/api/test_statements_router.py::test_get_stage2_review_queue_with_pending_match",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.bank-side-amount.5",
            "derive_reconciliation_score_tier maps a reconciliation match_score to LOW (<60 or None), MEDIUM (60-84), or HIGH (>=85).",
            "apps/backend/tests/reconciliation/test_confidence_tier.py::test_ac4_9_4_derive_reconciliation_score_tier",
            priority="P1",
        ),
        # ============================= audit-harness (AC4.10) =============================
        # NB: old AC4.10.3 is NOT here -- its test asserts a literal substring of
        # EPIC-004's own markdown text, so it stays EPIC-owned (same category as
        # AC12.25.1 in EPIC-012).
        ac(
            "AC-reconciliation.audit-harness.1",
            "The reconciliation audit harness's build_report/write_report emit a JSON report (with metadata, summary accuracy/false-positive-rate fields, and pass/fail targets) and a companion Markdown report.",
            "tests/tooling/test_reconciliation_audit.py::test_AC4_10_1_reconciliation_audit_report_schema_and_outputs",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.audit-harness.2",
            "The reconciliation audit harness's diagnostics report an intentionally-seeded false-positive scenario, identifying it by scenario id in the audit output.",
            "tests/tooling/test_reconciliation_audit.py::test_AC4_10_2_reconciliation_audit_reports_intentional_false_positive",
            priority="P1",
        ),
        # ============================= uuid-path-params (AC4.12) =============================
        ac(
            "AC-reconciliation.uuid-path-params.1",
            "POST /reconciliation/matches/{match_id}/accept with a non-UUID match_id returns 422 at the FastAPI path-param boundary rather than reaching the query layer.",
            "apps/backend/tests/api/test_typed_contract_sweep.py::test_AC4_12_1_accept_match_malformed_uuid_returns_422",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.uuid-path-params.2",
            "POST /reconciliation/unmatched/{txn_id}/reviewed-disposition with a non-UUID txn_id returns 422 at the FastAPI path-param boundary rather than reaching the query layer.",
            "apps/backend/tests/api/test_typed_contract_sweep.py::test_AC4_12_2_reviewed_disposition_malformed_uuid_returns_422",
            priority="P2",
        ),
        # ============================= per-currency-balance (AC4.13) =============================
        ac(
            "AC-reconciliation.per-currency-balance.1",
            "validate_balance_per_currency reconciles a multi-currency statement's SGD and USD buckets independently (each via its own open+in-out=close check) and never produces a cross-currency summed total.",
            "apps/backend/tests/accounting/test_validation.py::test_AC1_per_currency_reconcile_does_not_cross_sum",
        ),
        ac(
            "AC-reconciliation.per-currency-balance.2",
            "validate_balance_per_currency flags only the offending currency (USD short by 50) as invalid while the correctly-balanced SGD bucket stays valid, never collapsing both into one aggregate flag.",
            "apps/backend/tests/accounting/test_validation.py::test_AC1_per_currency_reconcile_flags_only_offending_currency",
        ),
        ac(
            "AC-reconciliation.per-currency-balance.3",
            "validate_balance_per_currency falls back to a single synthetic currency bucket and reproduces the legacy scalar balance check when the payload has no balances array, only opening_balance/closing_balance.",
            "apps/backend/tests/accounting/test_validation.py::test_AC1_single_currency_degenerate_path_still_passes",
        ),
        ac(
            "AC-reconciliation.per-currency-balance.4",
            "The degenerate single-currency validation path still detects and flags a balance mismatch when opening+transactions doesn't equal closing.",
            "apps/backend/tests/accounting/test_validation.py::test_AC1_single_currency_degenerate_path_detects_mismatch",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.per-currency-balance.5",
            "The CurrencyBalance schema normalizes a lower-case currency code to upper-case ISO and round-trips opening/closing as Decimal.",
            "apps/backend/tests/accounting/test_validation.py::test_AC1_currency_balance_schema_round_trips_decimals",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.per-currency-balance.6",
            "validate_balance_per_currency surfaces a transaction in a currency with no declared balance bucket (e.g. EUR) as its own per-currency result flagged declared_balance=False and forces the overall result invalid, instead of silently dropping that currency's money.",
            "apps/backend/tests/accounting/test_validation.py::test_AC1_orphan_currency_transaction_is_surfaced_not_dropped",
        ),
        ac(
            "AC-reconciliation.per-currency-balance.7",
            "validate_balance_per_currency rejects a balances array containing two buckets for the same currency (balance_computable=False, empty per_currency) instead of silently collapsing them into one arbitrary bucket.",
            "apps/backend/tests/accounting/test_validation.py::test_AC1_duplicate_currency_in_balances_is_rejected",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.per-currency-balance.8",
            "bank_currency_balances returns the per-currency array (as JSONB-ready string amounts) only when a bank statement payload declares more than one currency, and returns None for a single-currency or scalar-only payload so the existing scalar path is unchanged.",
            "apps/backend/tests/accounting/test_validation.py::test_AC4_13_9_bank_currency_balances_emitted_only_when_multi_currency",
        ),
        ac(
            "AC-reconciliation.per-currency-balance.9",
            "ExtractionService.parse_document persists a multi-currency bank statement's per-currency currency_balances (not collapsed to one scalar currency) and sets balance_validated True because each currency independently reconciles.",
            "apps/backend/tests/extraction/test_bank_multi_currency_balances.py::test_AC4_13_9_bank_multi_currency_statement_persists_balances_and_per_currency_governs",
        ),
        # ============================= fx-transfer (AC4.14) =============================
        ac(
            "AC-reconciliation.fx-transfer.1",
            "pair_fx_legs pairs an out-leg in one currency with an in-leg in another for the same owner when the implied rate (out_amount/in_amount) is within tolerance of the market rate, regardless of argument order.",
            "apps/backend/tests/accounting/test_fx_transfer.py::test_AC2_pairs_out_ccyA_with_in_ccyB_within_rate_tolerance",
        ),
        ac(
            "AC-reconciliation.fx-transfer.2",
            "pair_fx_legs returns None when the implied rate deviates from the market rate beyond tolerance (~10% off) and still pairs when the market rate is close to the implied rate.",
            "apps/backend/tests/accounting/test_fx_transfer.py::test_AC2_implied_rate_outside_tolerance_does_not_pair",
        ),
        ac(
            "AC-reconciliation.fx-transfer.3",
            "pair_fx_legs refuses to pair legs that fall outside the configured time window, share the same direction, or belong to different owners.",
            "apps/backend/tests/accounting/test_fx_transfer.py::test_AC2_non_candidate_legs_do_not_pair",
        ),
        ac(
            "AC-reconciliation.fx-transfer.4",
            "classify_internal_transfer marks a paired FX transfer as an internal transfer with zero income_amount and zero expense_amount, while an unpaired leg keeps normal (non-netted) classification.",
            "apps/backend/tests/accounting/test_fx_transfer.py::test_AC3_internal_transfer_classified_net_zero",
        ),
        ac(
            "AC-reconciliation.fx-transfer.5",
            "classify_internal_transfer's net_worth_delta is exactly zero for a fee-less paired transfer and exactly -fee when a fee is present, with no other net-worth impact.",
            "apps/backend/tests/accounting/test_fx_transfer.py::test_AC3_net_worth_unchanged_by_internal_transfer_minus_fee",
        ),
        ac(
            "AC-reconciliation.fx-transfer.6",
            "round_trip_realized_pnl returns exactly 0.00 for a same-day round trip at an unchanged rate with no fee, and exactly -fee when a fee is charged.",
            "apps/backend/tests/accounting/test_fx_transfer.py::test_AC4_same_day_round_trip_nets_zero_pnl_minus_fee",
        ),
        ac(
            "AC-reconciliation.fx-transfer.7",
            "round_trip_realized_pnl yields zero P&L for an unchanged-rate conversion event, and any rate-move gain/loss is routed through the JournalEntrySourceType.FX_REVALUATION source type rather than a conversion-event income/expense line.",
            "apps/backend/tests/accounting/test_fx_transfer.py::test_AC4_revaluation_pnl_routed_through_fx_revaluation_source_type",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fx-transfer.8",
            "build_fx_conversion constructs an FxConversion record from a paired leg whose amount_from/amount_to round-trip as Decimal with normalized ISO currency codes.",
            "apps/backend/tests/accounting/test_fx_transfer.py::test_AC2_fx_conversion_model_round_trips_decimals",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fx-transfer.9",
            "generate_income_statement excludes a recorded internal transfer's income/expense legs entirely and includes only the transfer's fee as an expense line, so net_income reflects salary income minus the fee only, with the fee visible as a single drill-downable expense line and in the monthly trend bucket.",
            "apps/backend/tests/reporting/test_fx_ledger_autodiscovery_e2e.py::test_AC3_internal_transfer_excluded_from_income_statement_e2e",
        ),
        ac(
            "AC-reconciliation.fx-transfer.10",
            "generate_balance_sheet's cumulative net_income excludes a recorded internal transfer's legs and reflects only the fee, matching the income statement's net contribution.",
            "apps/backend/tests/reporting/test_fx_ledger_autodiscovery_e2e.py::test_AC3_internal_transfer_net_income_fee_only_e2e",
        ),
        ac(
            "AC-reconciliation.fx-transfer.11",
            "discover_fx_conversions auto-discovers an unambiguous out-leg/in-leg cross-currency conversion directly from raw asset-account journal lines (no recorded fx_conversions row), recovering the correct accounts, amounts, currencies, and implied rate.",
            "apps/backend/tests/accounting/test_fx_transfer_discovery.py::test_AC2_discover_pairs_unambiguous_cross_currency_legs_from_ledger",
        ),
        ac(
            "AC-reconciliation.fx-transfer.12",
            "discover_fx_conversions refuses to pair an out-leg that matches two candidate in-legs on the same day, leaving all of them unpaired rather than guessing.",
            "apps/backend/tests/accounting/test_fx_transfer_discovery.py::test_AC2_discover_skips_ambiguous_candidate_legs",
        ),
        ac(
            "AC-reconciliation.fx-transfer.13",
            "generate_income_statement and generate_balance_sheet, with no recorded fx_conversions row at all, still auto-discover a cross-currency transfer from raw ledger lines and exclude it end to end so net income equals salary income only (no fee on this transfer).",
            "apps/backend/tests/reporting/test_fx_ledger_autodiscovery_e2e.py::test_AC2_raw_ledger_internal_transfer_autodiscovered_e2e",
        ),
        ac(
            "AC-reconciliation.fx-transfer.14",
            "For a same-day round-trip cross-currency conversion (both legs mis-booked as income/expense, no recorded fx_conversions), auto-discovery nets both conversions through the live income statement so net income shows ~zero P&L from the round trip.",
            "apps/backend/tests/reporting/test_fx_ledger_autodiscovery_e2e.py::test_AC4_same_day_round_trip_nets_zero_pnl_through_live_report",
        ),
        # ── group reconciliation-engine: end-to-end run/stats/match E2E (was
        # EPIC-008 AC8.5, migration closeout continuation, #1663 / #1711) ──
        ac(
            "AC-reconciliation.reconciliation-engine.1",
            "The reconciliation engine runs end to end through the API.",
            "apps/backend/tests/reconciliation/test_reconciliation_shift_left.py::test_reconciliation_scoring_engine_algorithms",
        ),
        ac(
            "AC-reconciliation.reconciliation-engine.2",
            "The reconciliation stats endpoint returns run statistics.",
            "apps/backend/tests/reconciliation/test_reconciliation_shift_left.py::test_reconciliation_stats_endpoint",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.reconciliation-engine.3",
            "A reconciliation match can be accepted through the API.",
            "apps/backend/tests/reconciliation/test_reconciliation_shift_left.py::test_reconciliation_match_state_and_acceptance",
            priority="P1",
        ),
        # ── group consistency-checks: detect_duplicates/detect_transfer_pairs/
        # resolve_check/list_checks edge-case behavior (was EPIC-016
        # AC16.4, migration closeout continuation, #1663 / #1711) ──
        ac(
            "AC-reconciliation.consistency-checks.1",
            "detect_duplicates runs a global scan across all of the user's transactions when no statement_id is provided.",
            "apps/backend/tests/review/test_consistency_checks.py::test_global_scan_no_statement_id",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.2",
            "detect_duplicates is idempotent — it does not create duplicate checks on re-run.",
            "apps/backend/tests/review/test_consistency_checks.py::test_idempotent_duplicate_detection",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.3",
            "detect_transfer_pairs runs a global scan across all of the user's transactions when no statement_id is provided.",
            "apps/backend/tests/review/test_consistency_checks.py::test_global_scan_no_statement_id",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.4",
            "resolve_check raises ValueError on an invalid resolution action.",
            "apps/backend/tests/review/test_consistency_checks.py::test_resolve_check_invalid_action_raises",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.5",
            "resolve_check raises ValueError when the check is not found.",
            "apps/backend/tests/review/test_consistency_checks.py::test_resolve_check_not_found_raises",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.6",
            "resolve_check sets FLAGGED status when action=flag.",
            "apps/backend/tests/review/test_consistency_checks.py::test_resolve_check_sets_flagged",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.7",
            "list_checks filters pending results by severity.",
            "apps/backend/tests/review/test_consistency_checks.py::test_get_pending_filters_by_severity",
            priority="P1",
        ),
        # ── group stage2-batch: Stage-2 batch approve blocking + typed contract
        # (was EPIC-016 AC16.22.3-4/AC16.35, migration closeout continuation,
        # #1663 / #1711) ──
        ac(
            "AC-reconciliation.stage2-batch.1",
            "A Stage-2 pending_review -> accepted transition is blocked while unresolved consistency checks exist.",
            "apps/backend/tests/api/test_statements_router.py::test_batch_approve_matches_blocked_by_unresolved_checks",
        ),
        ac(
            "AC-reconciliation.stage2-batch.2",
            "A Stage-2 batch approve may reconcile an existing source entry but cannot create a journal entry for a pending match without a reviewed economic disposition; the match remains pending and no entry is written.",
            "apps/backend/tests/api/test_statements_router.py::test_batch_approve_matches_without_entry_requires_review",
        ),
        ac(
            "AC-reconciliation.stage2-batch.3",
            "An empty batch approve returns the typed counters with no success field.",
            "apps/backend/tests/api/test_typed_contract_sweep.py::test_AC16_35_1_batch_approve_empty_returns_typed_response",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.stage2-batch.4",
            "Unresolved consistency checks block batch approve with a 409 structured error.",
            "apps/backend/tests/api/test_typed_contract_sweep.py::test_AC16_35_2_batch_approve_blocked_returns_409",
            priority="P1",
        ),
        # ── group review-hardening: Stage-2 queue requests the full unresolved
        # blocker set instead of truncating (was EPIC-016 AC16.32.3, migration
        # closeout continuation, #1663 / #1711) ──
        ac(
            "AC-reconciliation.review-hardening.1",
            "Stage-2 review check lists request the full unresolved blocker set needed to unblock batch approval, instead of silently truncating at the backend default page size.",
            "apps/backend/tests/api/test_statements_router.py::test_AC16_32_3_stage2_queue_returns_all_pending_checks",
        ),
        ac(
            "AC-reconciliation.review-hardening.2",
            "``accept_match`` validates journal-entry amounts against the transaction unconditionally: the public signature carries no bypass flag, and accepting a match whose entry total mismatches the transaction amount raises (entry balance validation is never skippable — red line, #1864 S1).",
            "apps/backend/tests/reconciliation/test_review_queue.py::test_AC_review_hardening_2_accept_match_validation_unconditional",
        ),
        # ── group audit-anchors: reconciliation-to-ledger anchor referential
        # integrity (was EPIC-018 AC18.11.1, migration closeout continuation,
        # #1663 / #1711) ──
        ac(
            "AC-reconciliation.audit-anchors.1",
            "Reconciliation match journal-entry anchors are represented by a normalized link table that rejects missing or cross-user journal entries.",
            "apps/backend/tests/infra/test_audit_anchor_schema_invariants.py::test_AC18_11_1_reconciliation_links_reject_missing_and_cross_user_entries",
        ),
        # ── group layer2-dedup: balance-aware Layer 2 dedup keeps many-to-one
        # matching correct (was EPIC-011 AC11.16.2, migration closeout
        # continuation, #1663 / #1711) ──
        ac(
            "AC-reconciliation.layer2-dedup.1",
            "Many-to-one matching works on Layer 2 when running balances keep batch transactions distinct.",
            "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py::test_execute_matching_many_to_one_batch",
        ),
        # ── group dwd-cutover: PR-B DWD (Layer 2) read cutover for transfer
        # detection (was EPIC-011 AC11.17, migration closeout continuation,
        # #1663 / #1711) ──
        ac(
            "AC-reconciliation.dwd-cutover.1",
            "Transfer OUT/IN detection resolves the custody account from the DWD (Layer 2) conform and creates the Processing entry under the Layer-2 read path.",
            "apps/backend/tests/reconciliation/test_reconciliation_matching_unit.py::test_transfer_out_creates_match",
        ),
        ac(
            "AC-reconciliation.dwd-cutover.2",
            "Mixed transfer and normal transactions both reconcile correctly under the Layer-2 read path.",
            "apps/backend/tests/reconciliation/test_transfer_integration.py::test_mixed_transactions_both_phases_execute",
        ),
        # ── group run-scoped-review: Stage-2 run-scoped review queue filtering
        # (was EPIC-019 AC19.11.1, migration closeout continuation, #1663 /
        # #1711) ──
        ac(
            "AC-reconciliation.run-scoped-review.1",
            "/review/run/{runId} uses a run-scoped Stage-2 queue and batch-approval API, so approving a run cannot approve pending matches from another workflow session or batch.",
            "apps/backend/tests/api/test_statements_router.py::test_AC19_11_1_stage2_run_queue_filters_by_run_id",
        ),
        # ── group consistency-checks (continued): Stage 2 dedup/transfer-pair
        # detection (was EPIC-016 AC16.2.1/AC16.2.2, #1821 Wave A
        # pending-package move; AC16.2.3 "batch approve blocked if unresolved
        # checks" was a duplicate of the already-migrated
        # AC-reconciliation.stage2-batch.1 citing the identical test and is
        # deleted without a new roadmap entry) ──
        ac(
            "AC-reconciliation.consistency-checks.8",
            "Deduplication detection accuracy is >= 95% on the consistency-check corpus.",
            "apps/backend/tests/review/test_consistency_checks.py::test_detect_duplicates",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.9",
            "Transfer-pair detection accuracy is >= 90% on the consistency-check corpus.",
            "apps/backend/tests/review/test_consistency_checks.py::test_detect_transfer_pairs",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.10",
            "``GET /statements/consistency-checks/list`` enforces a bounded page size: ``limit`` is declared with ``ge=1, le=200`` and an over-limit request is rejected with 422 instead of being accepted unbounded (#1864 S1).",
            "apps/backend/tests/review/test_consistency_checks.py::test_AC_consistency_checks_10_list_endpoint_rejects_unbounded_limit",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.consistency-checks.11",
            "Consistency check detection (detect_duplicates and detect_transfer_pairs) strictly partitions by transaction currency, preventing false duplicate and cross-currency transfer pair collisions.",
            "apps/backend/tests/review/test_falsifiable_consistency.py::test_consistency_checks_strictly_partition_by_currency",
            priority="P1",
        ),
        # ── group stage2-batch (continued): reconcile-referenced-entry /
        # idempotent-retry half not yet covered by .1-.4 (was EPIC-016
        # AC16.24.4, #1821 Wave A pending-package move) ──
        ac(
            "AC-reconciliation.stage2-batch.5",
            "Stage 2 batch approval reconciles a match against an existing referenced journal entry rather than creating a duplicate (the create-missing-entry-once half is already AC-reconciliation.stage2-batch.2).",
            "apps/backend/tests/api/test_statements_router.py::test_batch_approve_matches_reconciles_referenced_entry",
            priority="P1",
        ),
        # ── group conflict-resolution: Stage 1 duplicate/transfer-pair
        # conflict gate + resolution endpoint (was EPIC-016 AC16.32.1,
        # AC16.34.1, AC16.34.2 backend halves, #1821 Wave A pending-package
        # move; each row also cites a frontend test that stays untracked by
        # this Python-only roadmap) ──
        ac(
            "AC-reconciliation.conflict-resolution.1",
            "Stage 1 approval and edit-approval are blocked while duplicate or transfer-pair conflict candidates remain unresolved.",
            "apps/backend/tests/api/test_statements_router.py::test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts",
        ),
        ac(
            "AC-reconciliation.conflict-resolution.2",
            "POST /api/review/conflicts/{statement_id}/resolve records the reviewer's resolution; the Stage-1 approval guard honors it so a previously-blocked statement with duplicate/transfer-pair candidates can be approved, and an unknown statement returns 404 (also proven by test_AC16_34_1_resolve_conflicts_404_for_unknown_statement in the same file).",
            "apps/backend/tests/api/test_statements_router.py::test_AC16_34_1_resolve_unblocks_stage1_approval",
        ),
        ac(
            "AC-reconciliation.conflict-resolution.3",
            "A reject/reparse clears a prior conflict resolution so the fresh transaction set must be re-reviewed.",
            "apps/backend/tests/api/test_statements_router.py::test_AC16_34_2_reject_clears_conflict_resolution",
        ),
        # ── group candidate-matching: transfer/candidate-matching helper
        # unit tests (was EPIC-012 AC12.18.7 stub, #1821 Wave A
        # pending-package move) ──
        ac(
            "AC-reconciliation.candidate-matching.1",
            "_find_transfer_candidates, _find_normal_candidates, and _find_many_to_one_candidates (transfer/candidate-matching helpers) are covered by pure unit tests.",
            "apps/backend/tests/reconciliation/test_reconciliation_scoring_helpers.py::test_find_transfer_candidates_returns_pair",
            priority="P2",
        ),
        # ── group conflict-resolution (continued): the conflicts endpoint's
        # response contract (was EPIC-016 AC16.13.13/AC16.13.14, #1821 Wave
        # A horizontal move) ──
        ac(
            "AC-reconciliation.conflict-resolution.4",
            "GET /api/review/conflicts/{statement_id} returns {duplicates: [...], transfer_pairs: [...]}, consumed by ConflictResolutionDialog.",
            "apps/backend/tests/review/test_review_conflicts_router.py::test_review_conflicts_returns_duplicate_and_transfer_candidates",
        ),
        ac(
            "AC-reconciliation.conflict-resolution.5",
            "The conflicts endpoint returns 404 when the statement_id is not found.",
            "apps/backend/tests/review/test_review_conflicts_router.py::test_review_conflicts_returns_404_for_missing_statement",
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
        ac(
            "AC-reconciliation.fe-stage2-review.1",
            "Stage 2 UI supports batch operations",
            "apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.2.4/AC16.17.3 approves selected matches through the batch approval API",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.2",
            "Reconciliation entry pages render workbench and unmatched board components",
            "apps/frontend/src/__tests__/reconciliationEntryPages.test.tsx::AC16.16.4 renders workbench in reconciliation page",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.3",
            "Stage 2 review queue shows failure fallback and supports retry",
            "apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.17.1 shows an error fallback and retries the Stage 2 queue fetch",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.4",
            "Stage 2 review queue indicates unresolved checks and disables batch approval",
            "apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.2.3/AC16.17.2 disables batch approval while unresolved checks remain",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.5",
            "Stage 2 review queue rejects selected matches through the batch rejection API (the batch approve half of this workflow is proven by AC-reconciliation.fe-stage2-review.1)",
            "apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.17.3 rejects selected matches through the batch rejection API",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.6",
            "Stage 2 review queue resolves consistency checks through dialog actions",
            "apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.17.4 resolves a consistency check from the dialog actions",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.7",
            "Reconciliation workbench loads stats and pending queue with default selection",
            "apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx::AC16.20.1 loads stats and pending queue with default selection",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.8",
            "Reconciliation workbench triggers run, accept, reject, and batch accept APIs",
            "apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx::AC16.20.2 triggers run, batch, accept, and reject APIs",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.9",
            "Unmatched board requires an explicit reviewed disposition and exposes no raw create-entry or batch-create action.",
            "apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC-reconciliation.reviewed-disposition.2 / AC-reconciliation.fe-stage2-review.9 submits an explicit reviewed command instead of a raw create action",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.10",
            "Unmatched board flag and hide actions update local triage state without creating an accounting decision.",
            "apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC-reconciliation.fe-stage2-review.10 / AC-reconciliation.fe-stage2-review.25 keeps local flags and hiding separate from an accounting decision",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.11",
            "Score distribution renders 0% height for buckets with value 0",
            "apps/frontend/src/__tests__/reconciliationWorkbenchComponent.test.tsx::AC16.20.6 score distribution renders 0% height for buckets with value 0",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.12",
            "Review, journal details, and mobile navigation surfaces do not create document-level horizontal scrolling at phone widths",
            "apps/frontend/playwright/mobile-ux.spec.ts::AC16.25.1 mobile review routes avoid document horizontal scrolling",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.13",
            "AI suggestion review queue exposes accept, reject, correction, and edit-accept actions directly in a mobile card layout",
            "apps/frontend/playwright/mobile-ux.spec.ts::AC16.25.2 AI suggestions mobile cards expose feedback actions",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.14",
            "Stage 2 pending matches use selectable mobile cards with direct reject and approve selected actions visible without horizontal dragging",
            "apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC8.13.76/AC16.26.2 mobile queue renders selectable match cards and batch actions",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.15",
            "Stage 2 run review keeps the run approval gate and pending match workflow usable at phone widths without document-level horizontal scrolling",
            "apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC16.26.3 mobile run review preserves approval gate and pending match workflow",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.16",
            "Stage 1 and Stage 2 mobile review lists render without JavaScript breakpoint gating that can create first-paint blank content",
            "apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC16.27.1 keeps mobile pending-match cards in the DOM without matchMedia gating",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.17",
            "Stage 2 desktop review keeps pending match rows readable at 1440px with the sidebar visible without local horizontal clipping",
            "apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC8.13.82/AC16.27.3 exposes a fixed desktop pending-match region for responsive UX proofs",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.18",
            "Conflict resolution dialog `<ConflictResolutionDialog />` opens when backend returns duplicate or transfer-pair candidates; user can pick canonical row or link the pair",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.19",
            "Stage 2 listing exposes severity filter, check-type filter, and score-range slider; filters persist in URL query string",
            "apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx::AC16.23.4/AC8.13.48 persists Stage 2 filters in the URL while approving after filter changes",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.20",
            "Stage 2 run-level page at `/review/run/[runId]` summarizes duplicate, transfer-pair, and anomaly checks for a batch",
            "apps/frontend/src/__tests__/reviewRunPage.test.tsx::AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.21",
            "Stage 2 run-level page shows unresolved transfer and Processing pending counts, then disables run approval while either remains unresolved",
            "apps/frontend/src/__tests__/reviewRunPage.test.tsx::AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.22",
            "Stage 2 run-level approval submits all pending matches through the batch approval API after checks are resolved",
            "apps/frontend/src/__tests__/reviewRunPage.test.tsx::AC16.24.3 approves all pending matches through the batch approval API",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.23",
            "Stage 1 conflict dialog loads duplicate and transfer-pair candidates from `GET /api/review/conflicts/{statement_id}` instead of fake review payload fields",
            "apps/frontend/src/__tests__/statementReviewPage.test.tsx::AC16.23.3 AC16.31.1 opens the conflict dialog when duplicate or transfer-pair candidates exist",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.24",
            "Stage 2 run review page states that it uses the shared Stage 2 queue endpoint when no run-scoped queue API exists",
            "apps/frontend/src/__tests__/reviewRunPage.test.tsx::AC16.24.1 AC16.24.2 AC16.31.3 summarizes unresolved run checks and blocks approval",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.25",
            "Unmatched transaction flag/hide actions are labeled as local-only triage; raw batch-create is not an available action.",
            "apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC-reconciliation.fe-stage2-review.10 / AC-reconciliation.fe-stage2-review.25 keeps local flags and hiding separate from an accounting decision",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.26",
            "Stage 2 review check lists request the full unresolved blocker set needed to unblock batch approval instead of silently truncating at the backend default page size. Backend half (`test_AC16_32_3_stage2_queue_returns_all_pending_checks`) migrated to the `reconciliation` package roadmap as `AC-reconciliation.review-hardening.1` (migration closeout continuation, #1663 / #1711); the frontend half stays here.",
            "apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.32.3 requests an expanded consistency-check limit for unblockable queues",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.27",
            "The ConflictResolutionDialog `Resolve` / `Link Pair` buttons call the resolve endpoint with the matching action and disable while a resolution is in flight (previously dead, no-op buttons)",
            "apps/frontend/src/__tests__/ConflictResolutionDialog.test.tsx::AC16.34.3 Resolve and Link Pair buttons call onResolve with the matching action",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.28",
            "The dedicated `/reconciliation/review-queue` route renders the Stage-2 review queue standalone",
            "apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.36.1 renders the Stage-2 review queue as a standalone page",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.29",
            "The dedicated route loads the global queue (no run filter)",
            "apps/frontend/src/__tests__/reviewQueuePage.test.tsx::AC16.36.2 loads the global queue (no run filter) on the dedicated route",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.30",
            "The unmatched board honors a statement_id scope, preserves the statement-review return target, and shows a clear return action when every scoped transaction has received a reviewed disposition.",
            "apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC-reconciliation.fe-stage2-review.30 scopes the queue and returns to statement review",
        ),
        ac(
            "AC-reconciliation.fe-stage2-review.31",
            "The unmatched board initializes every reviewed disposition as unknown regardless of cash direction and requires the reviewer to select economic intent explicitly before compatible accounts or posting become available.",
            "apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC-reconciliation.fe-stage2-review.31 requires explicit intent instead of deriving it from direction",
        ),
        ac(
            "AC-reconciliation.first-use.1",
            "Missing counter-account setup reuses the ledger account form without losing the selected transaction or reviewed draft; creation alone never selects a disposition or posts an entry.",
            "apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC-reconciliation.first-use.1 creates a missing account and resumes the same explicit review",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from EPIC-022
        # (everyday-user-ia) and EPIC-005 (reporting-visualization) ──
        ac(
            "AC-reconciliation.fe-ia-reconciliation.1",
            "`/review/ai-suggestions` is reachable from AI Settings, so the AI-suggestion review surface is not orphaned",
            "apps/frontend/src/__tests__/aiSettingsPage.test.tsx::AC22.4.3 links to the AI suggestion review surface so it is not orphaned",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-ia-reconciliation.2",
            "E2E: a user with Stage 1 and Stage 2 attention sees both in the notification center and can open each detail surface",
            "apps/frontend/playwright/epic022-attention-journey.spec.ts::${label}: both Stage 1 and Stage 2 attention surface in the notification center with deep links",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-ia-reconciliation.3",
            "The `/attention` page folds the open attention sources (Stage 1 statement review, reconciliation review, unmatched transactions, stalled processing transfers) into a single list sorted by ascending confidence, each row deep-linking to its action surface, with an all-clear empty state when nothing needs attention",
            "apps/frontend/src/__tests__/attention.test.ts::AC22.6.1 folds the open attention sources into one list sorted by ascending confidence",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-ia-reconciliation.4",
            "The Home renders a trust meter (trusted / needs-confirmation / low-confidence counts) derived from the same attention model and linking to `/attention`, and stays silent when nothing needs attention",
            "apps/frontend/src/__tests__/attention.test.ts::AC22.6.2 summarizes trust into trusted / needs-confirmation / low-confidence buckets",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-ia-reconciliation.5",
            "Desktop and mobile smoke covers the `/attention` queue and the Home trust meter without layout overflow",
            "apps/frontend/playwright/attention-surface.spec.ts::${label} renders the attention queue ranked by confidence without overflow",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-ia-reconciliation.6",
            "Each attention-queue item surfaces a plain-language reason it was flagged — distinct per cause — alongside its confidence score",
            "apps/frontend/src/__tests__/attention.test.ts::AC22.11.2 every item explains why it was flagged",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-ia-reconciliation.7",
            "Attention-origin action links preserve `from=attention`, and the linked review/processing destinations render a return link to `/attention` while direct-entry notification/statement fallbacks remain unchanged",
            "apps/frontend/src/__tests__/attentionQueue.test.tsx::AC22.6.1 AC22.11.3 AC22.12.4 renders the open attention items with readable reasons and action links",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-ia-reconciliation.8",
            "Attention-queue reason text uses the normal muted content token, not a lower-opacity muted variant, so low-confidence explanations keep readable contrast",
            "apps/frontend/src/__tests__/attentionQueue.test.tsx::AC22.6.1 AC22.11.3 AC22.12.4 renders the open attention items with readable reasons and action links",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.fe-ia-reconciliation.9",
            "The Stage 2 review queue is composed from extracted sub-components (the match row/card and the queue controls) with unchanged review behavior",
            "apps/frontend/src/__tests__/stage2ReviewQueueParts.test.tsx::AC22.17.2 PendingMatchesPanel renders mobile + desktop rows and wires selection/batch callbacks",
            priority="P1",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ac(
            "AC-reconciliation.fe-remainder-reconciliation.1",
            "The unmatched transaction board models unmatched amounts as shared `MoneyValue` payloads and renders queue/detail/created-entry amounts through Decimal-safe currency formatting, not JavaScript number locale formatting",
            "apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx::AC4.11.1 renders unmatched monetary amounts with Decimal-safe currency formatting",
        ),
        ac(
            "AC-reconciliation.fe-remainder-reconciliation.2",
            "AI Suggestion Review Queue page `/review/ai-suggestions` lists pending AI classifications and AI reconciliation matches in score band 60-84 with `{transaction, suggested_category_or_match, ai_score, ai_reasoning}`",
            "apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.3 — AI Suggestion Review Queue page renders suggestions",
            priority="P2",
        ),
        ac(
            "AC-reconciliation.fe-remainder-reconciliation.3",
            "Queue actions: `Accept`, `Reject`, `Edit-then-Accept`; each action calls `POST /api/ai/feedback` with `{suggestion_id, action, corrected_value?}` to feed the feedback loop",
            "apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx::AC18.5.4 — feedback POST on accept/reject/edit",
            priority="P2",
        ),
        # ── closing the two remaining EPIC-018 AC18.3.x "Untested"
        # pending-package rows now that a real test exercises calculate_match_score's
        # hybrid-AI branch directly (AC18.3.1's separate tier-boundary blocker is
        # unrelated and untouched — see docs/project/EPIC-018.ai-driven-pipeline.md) ──
        ac(
            "AC-reconciliation.1803.1",
            "Hybrid scoring: calculate_match_score blends 0.7 * algorithmic + 0.3 * AI semantic score, applied only when the pre-AI weighted total is in the 60-84 review band.",
            "apps/backend/tests/reconciliation/test_reconciliation_hybrid_scoring.py::test_calculate_match_score_applies_hybrid_ai_scoring",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.1803.2",
            "Feature flag ENABLE_AI_RECONCILIATION gates the hybrid-AI branch: when off, calculate_match_score never calls the AI semantic scorer, even for a pre-AI total in the 60-84 band.",
            "apps/backend/tests/reconciliation/test_reconciliation_hybrid_scoring.py::test_calculate_match_score_flag_off_skips_ai_scoring",
            priority="P1",
        ),
        # #1866 PR-A: reconciliation/ledger signature surgery.  The split is
        # intentionally package-local: reconciliation owns orchestration,
        # errors, and the similarity policy; ledger separately owns posting
        # and balance-space guarantees in AC-ledger.signature.*.
        ac(
            "AC-reconciliation.signature-surgery.1",
            "Public reconciliation extension functions have fully annotated signatures and no more than eight parameters; matching phases receive a typed context.",
            "apps/backend/tests/reconciliation/test_signature_surgery.py::test_public_reconciliation_signatures_are_typed_and_bounded",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.signature-surgery.2",
            "execute_matching drives the ReconciliationRepository port and each phase returns its created matches instead of mutating an output list.",
            "apps/backend/tests/reconciliation/test_signature_surgery.py::test_matching_phases_return_created_matches",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.signature-surgery.3",
            "Normal single-/multi-entry scoring and many-to-one group scoring use distinct typed entry points; normal multi-entry candidates retain widened amount tolerance, and the AI switch is supplied through ReconciliationConfig rather than read in scoring.",
            "apps/backend/tests/reconciliation/test_signature_surgery.py::test_scoring_has_explicit_modes_and_no_hidden_environment_switch",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.signature-surgery.4",
            "Reconciliation failures use typed domain errors, router status mapping does not inspect exception text, and consistency-check actions are enum-typed; the legacy raw-entry routes are the only ValueError handlers and must roll back before returning a bad request.",
            "apps/backend/tests/reconciliation/test_signature_surgery.py::test_reconciliation_errors_and_resolve_actions_are_typed",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.signature-surgery.5",
            "Reconciliation owns the sole SequenceMatcher description-similarity kernel; ledger transfer pairing consumes that score while retaining ledger weights.",
            "apps/backend/tests/reconciliation/test_signature_surgery.py::test_description_similarity_has_one_owner_and_both_consumers_agree",
            priority="P1",
        ),
        ac(
            "AC-reconciliation.signature-surgery.6",
            "Transfer detection propagates processing-account currency conflicts instead of reporting a successful no-op run.",
            "apps/backend/tests/reconciliation/test_signature_surgery.py::test_transfer_detection_surfaces_processing_currency_conflicts",
        ),
        ac(
            "AC-reconciliation.signature-surgery.7",
            "Transfer detection leaves a foreign-account candidate unmatched when it requires an FX-aware posting path, while preserving the typed Processing-account configuration conflict.",
            "apps/backend/tests/reconciliation/test_signature_surgery.py::test_transfer_detection_leaves_foreign_account_candidate_unmatched",
        ),
        # #1969: one canonical disposition head, not a parallel governance
        # mechanism beside ReconciliationMatch.
        ac(
            "AC-reconciliation.economic-disposition.1",
            "An eligible journal candidate wins before transfer fallback, so transfer-shaped descriptions cannot create a Processing entry when normal matching succeeds.",
            "apps/backend/tests/reconciliation/test_economic_disposition.py::test_AC_reconciliation_economic_disposition_1_normal_candidate_precedes_transfer",
        ),
        ac(
            "AC-reconciliation.economic-disposition.2",
            "The database permits at most one active economic-disposition head for each AtomicTransaction while retaining append-only superseded history.",
            "apps/backend/tests/reconciliation/test_economic_disposition.py::test_AC_reconciliation_economic_disposition_2_database_rejects_duplicate_active_heads",
        ),
        ac(
            "AC-reconciliation.economic-disposition.3",
            "Independent sessions racing on one AtomicTransaction converge on one winner, and the loser reuses it without duplicating ledger effects.",
            "apps/backend/tests/reconciliation/test_economic_disposition.py::test_AC_reconciliation_economic_disposition_3_two_sessions_converge",
        ),
        ac(
            "AC-reconciliation.economic-disposition.4",
            "A transfer pair persists both uniquely owned disposition legs, its decision version, and review state, and paired/unpaired queries reflect stored reality.",
            "apps/backend/tests/reconciliation/test_economic_disposition.py::test_AC_reconciliation_economic_disposition_4_transfer_pair_round_trip",
        ),
        ac(
            "AC-reconciliation.economic-disposition.5",
            "Every statement-to-ledger amount comparison names the transaction currency, and lines in another currency never enter its nominal sum.",
            "apps/backend/tests/reconciliation/test_economic_disposition.py::test_AC_reconciliation_economic_disposition_5_currency_is_explicit",
        ),
        ac(
            "AC-reconciliation.economic-disposition.6",
            "Retry, worker restart, and phase permutation preserve disposition, journal, and transfer-pair cardinality after success or a rolled-back partial attempt.",
            "apps/backend/tests/reconciliation/test_economic_disposition.py::test_AC_reconciliation_economic_disposition_6_retry_and_phase_permutation_are_idempotent",
        ),
        ac(
            "AC-reconciliation.economic-disposition.7",
            "Processing effects are invoked only through ledger's typed command after a current reconciliation decision claim; reconciliation owns no alternate posting path.",
            "apps/backend/tests/reconciliation/test_economic_disposition.py::test_AC_reconciliation_economic_disposition_7_processing_uses_typed_ledger_boundary",
        ),
        ac(
            "AC-reconciliation.economic-disposition.8",
            "The governance detail projects exact detector, proof-strength, target-SHA, and enforcement state for every economic-disposition guarantee.",
            "apps/backend/tests/reconciliation/test_economic_disposition_governance.py::test_AC_reconciliation_economic_disposition_8_governance_detail_is_exact",
        ),
    ],
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
    concepts=[
        ConceptRecord(
            key="reconciliation_state_machine",
            owner="common/reconciliation/readme.md#state-machine",
            description="pending → auto_accepted | pending_review → accepted | rejected.",
            cross_refs=[
                "common/reconciliation/confirmation-workflow.md",
                "common/reconciliation/reconciliation.md",
            ],
            family="reconciliation",
            kind="model",
        ),
        ConceptRecord(
            key="reconciliation_thresholds",
            owner="common/reconciliation/readme.md#thresholds",
            description="Score ≥85 auto-accept; 60-84 review; <60 unmatched.",
            cross_refs=[
                "docs/agents/red-lines.md",
                "common/reconciliation/reconciliation.md",
            ],
            family="reconciliation",
            kind="baseline",
        ),
    ],
)
