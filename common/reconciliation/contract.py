"""The ``reconciliation`` package's machine-checkable :class:`PackageContract`."""

from __future__ import annotations

from common.meta.package_contract import ACRecord, Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="reconciliation",
    status="active",
    tier="CODE-ONLY",
    depends_on=["audit", "extraction", "portfolio", "ledger", "platform", "pricing", "observability", "config"],
    roles=["base", "extension", "data"],
    units=[
        Unit(name="ReconciliationMatch", kind=Kind.AGGREGATE_ROOT),
        Unit(name="ReconciliationMatchJournalEntry", kind=Kind.ENTITY),
        Unit(name="ReconciliationStatus", kind=Kind.VALUE_OBJECT),
        Unit(name="ReconciliationConfig", kind=Kind.VALUE_OBJECT, module="base/config.py"),
        Unit(name="MatchCandidate", kind=Kind.VALUE_OBJECT, module="base/config.py"),
        Unit(name="ReconciliationStats", kind=Kind.PROJECTION, module="data/stats.py"),
        Unit(name="load_reconciliation_config", kind=Kind.FACTORY, module="base/config.py"),
        Unit(name="ReconciliationRepository", kind=Kind.REPOSITORY, module="base/repository.py", impl="extension/repository.py"),
        Unit(name="execute_matching", kind=Kind.DOMAIN_SERVICE, module="extension/matching.py"),
        Unit(name="calculate_match_score", kind=Kind.DOMAIN_SERVICE, module="extension/matching.py"),
        Unit(name="find_candidates", kind=Kind.DOMAIN_SERVICE, module="extension/matching.py"),
        Unit(name="prune_candidates", kind=Kind.DOMAIN_SERVICE, module="extension/matching.py"),
        Unit(name="build_many_to_one_groups", kind=Kind.DOMAIN_SERVICE, module="extension/matching.py"),
        Unit(name="get_reconciliation_stats", kind=Kind.PROJECTION, module="data/stats.py"),
        Unit(name="score_amount", kind=Kind.DOMAIN_SERVICE, module="extension/scoring.py"),
        Unit(name="score_date", kind=Kind.DOMAIN_SERVICE, module="extension/scoring.py"),
        Unit(name="score_description", kind=Kind.DOMAIN_SERVICE, module="extension/scoring.py"),
        Unit(name="score_business_logic", kind=Kind.DOMAIN_SERVICE, module="extension/scoring.py"),
        Unit(name="score_pattern", kind=Kind.DOMAIN_SERVICE, module="extension/scoring.py"),
        Unit(name="EventBusMatchOutcome", kind=Kind.EVENT_BUS, module="extension/matching.py"),
        Unit(name="ReconciliationStatsProjection", kind=Kind.PROJECTION, module="data/stats.py"),
        Unit(name="ScoreBreakdownProjection", kind=Kind.PROJECTION),
        Unit(name="MatchStatusHistoryProjection", kind=Kind.PROJECTION),
        Unit(name="UnmatchedTransactionsProjection", kind=Kind.PROJECTION),
        Unit(name="TransferLeg", kind=Kind.VALUE_OBJECT),
        Unit(name="pair_fx_legs", kind=Kind.DOMAIN_SERVICE, module="extension/fx_transfer.py"),
        Unit(name="discover_fx_conversions", kind=Kind.DOMAIN_SERVICE, module="extension/fx_transfer_discovery.py"),
        Unit(name="detect_anomalies", kind=Kind.DOMAIN_SERVICE, module="extension/anomaly.py"),
        Unit(name="run_all_consistency_checks", kind=Kind.DOMAIN_SERVICE, module="extension/consistency_checks.py"),
    ],
    implementations={"be": "apps/backend/src/reconciliation", "fe": None},
    interface=[
        "DEFAULT_CONFIG",
        "MAX_COMBINATION_CANDIDATES",
        "MatchCandidate",
        "ReconciliationConfig",
        "ReconciliationStats",
        "DEFAULT_RATE_TOLERANCE",
        "DEFAULT_TIME_WINDOW",
        "FxTransferError",
        "TransferLeg",
        "classify_internal_transfer",
        "discover_fx_conversions",
        "pair_fx_legs",
        "_candidate_is_better",
        "_find_many_to_one_candidates",
        "_find_normal_candidates",
        "_find_transfer_candidates",
        "_get_existing_active_match",
        "_get_pending_layer2_transactions",
        "_within_combination_tolerance",
        "ai_semantic_score",
        "auto_accept",
        "build_many_to_one_groups",
        "calculate_match_score",
        "entry_bank_side_amount",
        "entry_total_amount",
        "execute_matching",
        "extract_merchant_tokens",
        "find_candidates",
        "get_reconciliation_stats",
        "is_cross_period",
        "is_entry_balanced",
        "load_reconciliation_config",
        "normalize_text",
        "prune_candidates",
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
    ],
)
