"""PackageContract for ``testing``."""

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
    name="testing",
    status="active",
    tier="CODE-ONLY",
    depends_on="meta".split(),
    implementations={"be": "common/testing", "fe": None},
    context=ContextScope(
        purpose="Execute and prove package guarantees through reusable test selection, fixtures, evidence aggregation, and CI-quality gates.",
        in_scope=[
            "test selection and execution evidence.",
            "shared fixtures and deterministic test helpers.",
            "test and gate quality governance.",
        ],
        out_of_scope=[
            "business-domain acceptance semantics.",
            "runtime environment and deployment ownership.",
            "product prioritization and policy.",
        ],
    ),
    relationships=rels(
        "testing",
        """
meta|published-language|Testing consumes meta's published contract and registry language to project, select, and validate package-owned proofs.
""",
    ),
    units=units(
        """
@vo|-|Cassette FixtureDocument
TrustedYearScenario|ent
"""
    ),
    interface=["money_amount"],
    events=[],
    invariants=invs(
        """
passes-own-governance-gate|check_package_contract validates testing with no violations.|$t/test_testing_package.py::test_AC_testing_1_1_package_contract_gate_passes_for_testing
"""
    ),
    roadmap=acs(
        "testing",
        """
@$t/test_pdf_fixture_tooling_coverage.py|P2
1.1||test_AC9_1_1_analyzer_extracts_page_table_and_text_positions
1.3||test_AC9_1_3_template_extractor_emits_source_table_schema
2.5||test_AC9_2_5_font_helpers_choose_safe_fonts
2.6||test_AC9_2_6_fake_data_generators_keep_running_balances
7.1||test_AC9_7_1_AC9_7_2_main_generates_selected_source
7.2||test_AC9_7_1_AC9_7_2_main_generates_all_sources_with_default_output
7.3||test_AC9_1_3_analyzer_cli_writes_template_yaml
@$t/test_pdf_fixture_epic009_behavior.py|P2
1.2||test_AC9_1_2_template_extractor_writes_sanitized_format_yaml
1.4|DBS template exists.|test_AC9_1_4_AC9_1_5_AC9_1_6_committed_templates_define_source_schemas
1.5|CMB template exists.|^
1.6|Mari Bank template exists.|^
2.1||test_AC9_2_1_base_generator_loads_template_and_applies_layout
2.2|DBS generator exists.|test_AC9_2_2_AC9_2_3_AC9_2_4_generators_load_committed_templates
2.3|CMB generator exists.|^
2.4|Mari Bank generator exists.|^
2.7||test_AC9_2_7_main_script_registers_all_supported_generators
4.1|Format analysis README.|test_AC9_4_readmes_document_analysis_generation_templates_and_examples
4.2|Generation README.|^
4.3|Template format specification.|^
4.4|Usage examples.|^
5.1|.gitignore excludes real PDFs.|test_AC9_5_git_contract_tracks_safe_sources_only
5.2|Format templates committed.|^
5.3|Generators committed.|^
5.4|Analyzers committed.|^
6.1|DBS generator loads template.|test_AC9_6_1_AC9_6_2_generators_preserve_template_source_identity
6.2|CMB generator loads template.|^
6.3||test_AC9_6_3_cmb_generator_uses_registered_chinese_font
6.4||test_AC9_6_4_mari_generator_renders_interest_details_section
6.5||test_AC9_6_5_generators_use_masked_accounts_and_fictional_data
@$t/test_pdf_fixture_parseable.py|P2
3.2||test_ac9_3_2_dbs_generated_pdf_parseable
3.3||test_ac9_3_3_cmb_generated_pdf_parseable
3.4||test_ac9_3_4_mari_generated_pdf_parseable
3.5||test_ac9_3_5_balance_calculations_correct
3.6||test_ac9_3_6_date_formats_correct_per_source
@$t/test_pdf_fixture_real_format_contract.py|P2
8.1||test_AC9_8_1_templates_define_sanitized_real_format_contract
8.3||test_AC9_8_3_generated_dbs_pdf_matches_template_real_format_contract
@$be/runtime/test_runtime_and_ci_contracts.py
journeys.1|API health check.|test_api_health_endpoint_contract
must-have.1|Health endpoint reachable.|^
journeys.2||test_accounts_schema_contract
ci-integration.1|PR workflow runs E2E tests.|test_ci_workflow_contracts
ci-integration.3|Critical test check.|^
ci-integration.2||test_smoke_test_script_contract
ci-integration.4||test_database_environment_isolation_contract
@$be/ledger/test_ledger_shift_left.py
journeys.3||test_journal_entry_post_and_void_reversal
must-have.2||test_account_creation_cash_and_bank
must-have.3|User can create journal entry.|test_journal_entry_balancing_and_validation
must-have.6|Unbalanced entry rejected.|^
@$be/reporting/test_reporting_shift_left.py
journeys.4|Reports API.|test_balance_sheet_accounting_equation_articulation
must-have.7|Reports API accessible.|^
@$be/reconciliation/test_reconciliation_shift_left.py
journeys.5|Reconciliation API.|test_reconciliation_scoring_engine_algorithms
must-have.5|Reconciliation engine runs.|^
@$t/test_e2e_rate_limit_guard.py|P1
journeys.6||test_AC_testing_journeys_6_rate_limit_hits_fail_the_test_report
@$be/extraction/test_statements_shift_left.py
must-have.4||test_statement_upload_csv_direct_parsing
seeded-journey.1||test_seeded_statement_materializes_without_llm
seeded-journey.2||test_seeded_statement_list_and_details_query
seeded-journey.3||test_seeded_statement_transactions_and_reconciliation
@$be/identity/test_auth_shift_left.py
must-have.8||test_password_hashing_and_verification
must-have.9||test_invalid_token_rejected_with_401
@$t/test_check_critical_proof_matrix.py
trust-mirrors.1||test_valid_behavioral_static_and_manual_entries_pass
trust-mirrors.2||test_AC8_14_2_llm_ocr_proof_requires_deterministic_pr_mirror
acgates.5||test_AC8_14_1_critical_proof_matrix_reports_duplicate_proof_ids
acgates.6||test_AC8_13_50_macro_outcome_contract_rejects_drift
acgates.7||test_AC8_13_54_macro_contract_requires_owner_epic_reverse_declarations
@$t/test_personal_report_package_fixture_contract.py
trust-mirrors.3||test_AC8_14_3_personal_package_has_deterministic_package_document_mirror
product-gates.8||test_AC8_13_83_representative_package_fixture_contract_defines_exact_outputs
product-gates.9||test_AC8_13_84_personal_package_e2e_consumes_representative_fixture_contract
product-gates.10||test_AC8_13_85_personal_package_macro_proof_is_promoted_after_fixture_contract
product-gates.11||test_AC8_13_87_personal_package_fixture_pins_brokerage_dividend_and_market_price_outputs
product-gates.12||test_AC8_13_88_personal_package_e2e_consumes_audit_grade_expected_outputs
@$be/integration/test_reporting_e2e.py
trust-mirrors.4||test_AC5_15_1_multicurrency_reporting_cycle_reconciles_bs_is_cf
@$t/test_tier2_http_e2e.py
tier2.1||test_AC8_18_1_tier2_http_command_fails_closed_without_deployed_inputs
tier2.2||test_AC8_18_2_tier2_http_report_is_proof_tiered_and_skip_ineligible
tier2.3||test_AC8_18_3_staging_workflow_runs_tier2_http_before_tier3_browser_e2e
@$t/test_check_pr_review_threads.py|P1
review-threads.1||test_AC8_20_1_unresolved_p0_blocks
review-threads.2||test_AC8_20_2_resolved_p0_passes
review-threads.3||test_AC8_20_3_severity_rule_documented_in_ssot
review-threads.4||test_copilot_thread_real_login_without_bot_suffix_is_blocking|P0
@$t/test_execution_matrix_contract.py
matrix.1||test_AC8_22_1_generated_matrix_matches_checked_in_yaml
matrix.2||test_AC8_22_2_staging_workflow_derives_selection_from_matrix
matrix.3||test_AC8_22_3_staging_selection_is_audited_and_dependency_free
matrix.4||test_AC8_22_4_every_root_e2e_spec_has_a_named_row|P1
matrix.5||test_AC8_22_5_shell_emission_round_trips|P1
matrix.6||test_AC8_22_6_charter_and_manifest_ownership|P1
@$t/test_workflow_selection_conformance.py
conformance.1||test_AC8_23_1_every_workflow_pytest_invocation_is_registered
conformance.2||test_AC8_23_2_registered_invocations_match_matrix_selection
conformance.3||test_AC8_23_3_staging_ai_ocr_corpus_aligns_with_matrix_llm_rows|P1
conformance.4||test_AC8_23_4_pr_ci_evidence_reconciliation_gate
@$t/test_package_declaration_and_ratchet.py
declarations.1||test_AC8_24_1_seed_packages_declare_owned_test_roots
declarations.2||test_AC8_24_2_e2e_stages_run_their_environment_precondition_first
@$e2e/test_production_readonly_smoke.py
deploy-gates.1||test_AC8_13_9_production_public_runtime_contract
@$t/test_post_merge_e2e_gates.py
deploy-gates.2||test_AC8_13_11_health_check_diagnoses_staging_api_route_404
deploy-gates.3||test_AC8_13_12_ai_ocr_gate_failure_includes_statement_context
deploy-gates.4|Staging deploy uses workflow-level singleton concurrency to prevent duplicate concurrent staging mutation and bounds E2E gate duration with phase timing logs.|test_AC8_13_13_staging_deploy_fast_fail_guardrails
deploy-gates.21|Staging classification and deploy run in one runner job, with no separate classify job, to avoid a second GitHub Actions scheduling gap before staging mutation.|^
deploy-gates.5||test_AC8_13_14_staging_ai_ocr_gate_is_separate_deploy_job
deploy-gates.6||test_AC8_13_21_staging_ai_ocr_gate_runs_under_manual_dispatch
deploy-gates.7||test_AC8_13_22_staging_deploys_manually_dispatched_version_ref
deploy-gates.8||test_AC8_13_23_post_merge_deploy_and_ai_ocr_are_one_serial_unit
deploy-gates.9||test_AC8_13_36_post_merge_reuses_sha_tagged_staging_images
deploy-gates.10||test_AC8_13_40_pr_ci_dry_runs_staging_image_builds_before_merge
deploy-gates.11||test_AC8_13_49_staging_ai_ocr_gate_publishes_audit_inventory_and_summary
deploy-gates.12||test_AC8_13_51_staging_deploy_is_manual_dispatch_only
deploy-gates.13|Production release dry-run validates release prerequisites and image builds through shared release evidence/image digest tools.|test_AC8_13_52_production_release_dry_run_does_not_mutate_production
deploy-gates.17|Production release reuses successful main CI proof instead of rerunning container-backed tests in the release lane.|^
deploy-gates.15||test_AC8_13_60_deploy_workflows_have_no_nonblocking_noop_gates
deploy-gates.18||test_AC8_13_67_production_release_preserves_version_metadata
deploy-gates.19|Staging is mutated only by an explicit manual workflow_dispatch with a required release version_ref input.|test_AC8_13_93_staging_promotion_requires_manual_dispatch
deploy-gates.22|Main post-merge staging deploy failures publish structured failure domain, failed step, and failure summary in the deploy context artifact and Post-merge Delivery summary so deploy_v2 dependency setup, Dokploy rollout, route health, E2E setup, and application E2E failures can be separated.|^
deploy-gates.20||test_AC8_13_103_post_merge_delivery_summary_check_aggregates_staging_gates
deploy-gates.24|Record sparse-matrix evidence for three newest successful and three newest failed runs covering delivery-speed balance, end-to-end consistency, quality fallback, and resource leak candidates.|test_AC8_13_113_sparse_matrix_evidence_and_resource_leak_audit_are_recorded
deploy-gates.25||test_AC8_13_116_skip_heavy_ci_on_main_push
deploy-gates.26|Harden delivery against GHCR PR tag accumulation, stale staging or production routes, provider-backed external-state residue, and Docker build cache and stopped containers.|test_AC8_13_119_delivery_resource_leak_hardening_is_contracted
deploy-gates.27||test_AC8_13_120_staging_runs_lightweight_provider_connectivity_smoke
deploy-gates.29||test_AC8_13_144_production_release_rolls_back_with_deploy_v2_after_post_deploy_failure
deploy-gates.32||test_AC8_13_157_audit_replay_workflow_is_weekly_and_blocks_nothing|P1:property
deploy-gates.33||test_AC8_13_158_canary_transient_classification_owned_by_provider_gate|P1:property
deploy-gates.35||test_AC8_13_160_ci_cd_distinguishes_canary_from_audit_replay|P1:property
deploy-gates.36||test_AC_testing_deploy_gates_36_every_main_commit_image_is_independently_verified|P1:property
deploy-gates.41||test_AC8_13_166_gate_timeout_fallback_alerts_when_corpus_step_dies_without_output|:property
deploy-gates.42||test_AC8_13_167_timeout_budget_is_sized_per_corpus_worst_case|:property
preview.2||test_AC8_13_46_staging_non_llm_gate_uses_strict_parallelism|P1
preview.14||test_AC8_13_115_readiness_fail_fast
classifier.1||test_AC8_13_16_ci_change_classification_and_frontend_cache|P1
classifier.8||test_AC8_13_112_sparse_matrix_recommendation_tracks_simplification_path
classifier.9||test_AC8_13_152_workflow_consumers_keep_classification_single_owned|P1:property
ci-structure.1||test_AC8_13_25_full_ci_aggregates_static_traceability_and_test_gates|P1
ci-structure.3||test_AC8_13_33_e2e_setup_caches_virtualenv_and_playwright_browsers|P1
ci-structure.5||test_AC8_13_86_fast_feedback_jobs_do_not_wait_for_behavior_gates|P1
ci-structure.6||test_AC8_13_145_backend_tier1_pr_fail_fast_but_main_reports_all_failures|P1
ci-structure.7||test_AC8_13_147_frontend_ci_split_preserves_merge_authority|P1
ci-structure.8||test_AC8_13_148_backend_shards_use_seeded_least_duration_split|P1
ci-structure.10||test_AC8_13_162_frontend_telemetry_e2e_is_right_moved_and_skip_is_a_pass|P1:property
ci-structure.11||test_AC_testing_ci_structure_11_frontend_build_and_playwright_are_right_moved_and_skip_is_a_pass|P1:property
ci-structure.12||test_AC_testing_ci_structure_12_setup_uv_retries_once_via_one_composite_action|P1:property
ci-structure.14||test_AC_testing_ci_structure_14_tier1_runs_as_seeded_matrix_legs|P1:property
governance.1||test_AC8_13_47_delivery_engine_recommendations_are_tracked|P1
governance.3||test_AC8_13_94_env_and_pipeline_stage_contract_is_documented
governance.4||test_AC8_13_95_local_fast_gate_and_escalation_policy_are_documented
governance.5||test_AC8_13_118_timeouts_and_retries_documented
@$t/test_ci_change_classifier.py
deploy-gates.14||test_AC8_13_55_staging_only_runs_for_runtime_deploy_or_e2e_changes
classifier.2||test_AC8_13_20_ci_workflow_changes_are_heavy_except_docs_workflow|P1
classifier.4||test_AC8_13_97_staging_classifier_includes_common_deploy_runtime_paths
classifier.5||test_AC8_13_104_staging_ai_ocr_runs_only_for_provider_risk_paths
classifier.6||test_AC8_13_110_github_outputs_include_structured_env_stage_matrix
classifier.7||test_AC8_13_111_static_stage_rejects_non_static_environments
classifier.10||test_AC8_13_161_component_changed_isolates_a_single_component|P1:property
@$t/test_staging_ai_ocr_gate_contract.py|P1|done|property
deploy-gates.23||test_AC8_13_109_ai_ocr_gate_tests_use_isolated_users|P0:exact
deploy-gates.28||test_AC8_13_137_summarize_junit_reports_per_doc_failures|:exact
deploy-gates.31||test_AC8_13_156_canary_corpus_is_minimal_liveness
deploy-gates.34||test_AC8_13_159_blocking_path_excludes_heavy_audit_journeys
deploy-gates.37||test_AC_testing_deploy_gates_37_gate_preflights_before_corpus_spend
deploy-gates.38||test_AC_testing_deploy_gates_38_gate_retries_transients_once_then_escalates
deploy-gates.39||test_AC_testing_deploy_gates_39_alert_body_carries_machine_attribution
deploy-gates.40||test_AC_testing_deploy_gates_40_green_run_closes_standing_alerts
deploy-gates.44||test_AC_testing_deploy_gates_44_existing_alert_is_refreshed|P0
deploy-gates.45||test_AC_testing_deploy_gates_45_canonical_trace_observation_and_matching_corpus_close|P0
@$t/test_smoke_routes_contract.py|P0|done|property
deploy-gates.43||test_AC7_17_1_smoke_asserts_only_existing_public_frontend_routes
@$t/test_hook_manifest.py|P0|done|property
deploy-gates.46||test_AC_testing_deploy_gates_46_hook_steps_are_posix_strict_gates
hook-main.1||test_AC_testing_hook_main_1_module_prints_each_node_of_the_matrix_selection
hook-main.2||test_AC_testing_hook_main_2_each_manifest_module_check_prints_help
hook-main.3||test_AC_testing_hook_main_3_the_scan_covers_every_hook_slot_with_a_module
@$t/test_critical_skip_gate.py
product-gates.1||test_AC8_13_6_strict_gates_off_never_converts
@$e2e/test_vision_upload_to_dashboard_hard_gate.py
product-gates.2||test_statement_upload_to_dashboard_vision_hard_gate
@$e2e/test_four_asset_net_worth_golden_path.py|P0|done|property
product-gates.7||test_four_asset_as_of_net_worth_golden_path
@$t/test_provider_journey_review_contract.py|P0|done|property
product-gates.13||test_AC_testing_product_gates_13_retries_after_reviewed_dispositions
@$t/test_e2e_institution_fixture_contracts.py|P1
product-gates.14||test_AC_testing_product_gates_14_each_fixture_row_has_a_disposition_that_fits_its_direction
@$t/test_ci_metrics_contract.py
ci-structure.2||test_AC8_13_26_ci_workflow_runs_metrics_contract_and_defines_metric_semantics
coverage.1||test_AC8_13_26_future_app_source_roots_must_be_in_coverage_policy
@$t/test_github_workflow_timing_summary.py|P1
ci-structure.4||test_AC8_13_34_format_duration_uses_compact_minutes
@$t/test_backend_shard.py|P1|done|property
ci-structure.13||test_AC_testing_ci_structure_13_real_split_is_exhaustive_disjoint_and_balanced
@$t/test_workflow_contract.py
ci-structure.15||test_AC_testing_ci_structure_15_main_only_jobs_declare_rehearsal_or_isolation|P1:property
governance.11||test_AC7_15_1_real_repo_passes_the_workflow_contract
governance.12||test_AC7_15_2_stale_or_missing_contract_inputs_fail
governance.13||test_AC7_15_3_stale_ci_classifier_job_name_fails
@$t/test_ac_index_consistency.py|P1
acgates.1|In-memory AC registry loader (common/meta/extension/generate_ac_registry.py) extracts entries from package roadmaps and marked EPIC residue.|test_AC8_13_139_no_committed_materialized_index_files|P0
acgates.15|The historical AC-score ratchet baseline (common/testing/data/ac-score-baseline.jsonl) and its one-consumer scoring machinery are retired alongside the materialized proof/vision/status views.|^
acgates.14||test_AC8_13_135_protection_dashboard_separates_reference_from_behavioral|P0
acgates.16||test_AC8_13_139_gate_passes_on_consistent_tree
acgates.17||test_AC8_13_140_every_ac_managed_with_empty_protection_passes
@$t/test_check_ac_traceability.py
acgates.3||test_classifies_placeholder_assertion
acgates.4||test_placeholder_and_stub_refs_do_not_count_as_real_coverage
acgates.11||test_AC8_13_78_ci_required_real_refs_cover_mandatory_gate
@$t/test_lint_doc_consistency.py
acgates.10||test_AC8_13_77_active_stub_orphan_fails
governance.2||test_AC8_13_81_doc_can_reference_code_owned_threshold_without_number|P1
@$t/test_schema_quality_contract.py
acgates.13||test_AC8_13_124_traceability_gate_and_audit_builder_share_test_surface|P1
schema.1||test_AC8_13_121_pr_ci_runs_schema_migration_contract
schema.2||test_AC8_13_122_schema_drift_guard_does_not_accept_outdated_targets
schema.3||test_AC8_13_123_schema_guardrails_scan_real_migration_directory
@$t/test_two_gate_consolidation.py|P1
acgates.18||test_AC8_13_141_green_tree_old_gates_and_consolidated_agree
@$t/test_ac_proof_execution_model.py|P1|done|property
gate-inventory.2||test_AC8_13_150_ac_proof_execution_model_is_ac_keyed_and_backward_compatible
@$t/test_runtime_incident_response_ssot.py
governance.6||test_AC8_13_126_runtime_incident_response_ssot_centralizes_triage
@$t/test_governance_exceptions_registry.py|P1
governance.7||test_AC8_13_131_every_classified_entry_links_an_owner_and_issue
@$t/test_no_ac_test_classification.py|P1
governance.8||test_AC8_13_132_no_unclassified_no_ac_test_files
@$t/test_ssot_cross_document_anchors.py|P1
governance.9||test_AC8_13_133_concepts_registered_in_manifest_with_anchored_owner
@$t/test_stale_docs_consolidation.py|P1
governance.10||test_AC8_13_134_mkdocs_nav_links_resolve
@$t/test_secret_scan_gate.py
secret-scan.1||test_AC8_13_136_gitleaks_runs_in_precommit_and_ci
@$t/test_build_secret_scan_contract.py
secret-scan.2||test_AC7_18_1_container_images_job_has_build_context_secret_scan
@$t/test_toolchain_contract.py
toolchain.1||test_AC8_13_39_cli_accepts_explicit_repo_root
@$t/test_bootstrap_local.py
toolchain.2||test_AC8_13_44_bootstrap_reports_container_runtime_prerequisite
@$t/test_preflight.py|P1
toolchain.3||test_AC_testing_toolchain_3_backend_format_uses_invoking_python_environment|P0
preflight.1||test_AC_testing_preflight_1_static_tier_composes_with_glob_selection
preflight.2||test_AC_testing_preflight_2_frontend_static_gate_parity
preflight.3||test_AC_testing_preflight_3_list_all_inventory_discovery
@$t/test_common_tooling_modules.py
toolchain.4||test_AC8_13_53_common_coverage_component_is_a_governed_source_root
toolchain.5||test_AC8_13_56_coverage_tools_delegate_to_common_implementations
toolchain.6||test_AC8_13_57_ssot_tools_delegate_to_common_implementations
toolchain.7||test_AC8_13_58_ci_tools_delegate_to_common_implementations
toolchain.8||test_AC8_13_59_config_validation_tools_delegate_to_common_implementations
@$t/test_cli_and_dev_servers.py
toolchain.9||test_AC8_13_79_cmd_test_backend_e2e_route
@$t/test_frontend_typecheck_contract.py
toolchain.10||test_AC8_13_99_frontend_typecheck_is_a_required_gate
@$t/test_staging_toolchain_retry.py
toolchain.11||test_AC7_16_1_setup_e2e_composite_retries_toolchain_downloads
@$be/integration/test_production_faithful_business_persistence.py
schema.4||test_AC8_13_127_alembic_business_persistence_keeps_user_fk_contract
@$t/test_detached_owner_guard.py
schema.5||test_AC8_13_128_budget_fails_on_growth
schema.6||test_AC8_13_129_schema_docs_distinguish_fast_fixture_and_production_faithful_lane
schema.7||test_AC8_13_130_counts_only_persisted_detached_owners|P1
@$be/unit/infra/test_test_lifecycle.py
lifecycle.1||test_namespaced_infra_uses_ephemeral_host_ports
@$t/test_lifecycle_and_pdf_scripts.py|P1
lifecycle.2||test_AC16_13_1_sanitize_namespace_normalization
lifecycle.3||test_AC16_13_2_get_namespace_from_branch_and_workspace
lifecycle.4||test_AC16_13_3_get_namespace_from_git_and_path_hash
lifecycle.5||test_AC16_13_4_name_helpers
lifecycle.6||test_AC16_13_5_load_active_namespaces_missing_and_corrupt
lifecycle.7||test_AC16_13_6_register_unregister_namespace
lifecycle.8||test_AC16_13_7_get_container_runtime
lifecycle.9||test_AC16_13_8_is_db_ready_handles_failure
lifecycle.10||test_AC16_13_9_cleanup_worker_databases_skips_invalid_namespace
lifecycle.11||test_AC16_13_10_cleanup_worker_databases_drops_valid_and_skips_invalid
lifecycle.12||test_AC16_13_11_get_changed_files_maps_backend_modules
lifecycle.13||test_AC16_13_12_generate_statement_builds_pdf_rows
@$t/test_worktree_doctor.py|P1
preflight.4||test_AC_testing_preflight_4_worktree_doctor_audit_and_prune
preflight.5||test_AC_testing_preflight_5_worktree_doctor_recognizes_squash_merged_prs
@$fe/__tests__/playwrightMobileLane.test.ts|P1
fe-lane.1||AC-testing.fe-lane.1 the blocking Playwright config declares a true mobile device project
@$fe/__tests__/useApiQuery.test.tsx|P1
fe-async.1||AC-testing.fe-async.1 fetches the given operation through apiOperation and exposes the data
@$fe/__tests__/accountsPage.test.tsx|P1
fe-async.2||AC-testing.fe-async.2 delete flow invalidates the matrix-declared query keys against a real QueryClient
@$fe/__tests__/mutationInvalidationLock.test.ts|P1
fe-async.3||AC-testing.fe-async.3 every useMutation call site in src/ has a matrix row
@$fe/__tests__/stage2ReviewQueueCoverage99.test.tsx
fe-coverage.1||AC16.23.4/AC8.13.48 persists Stage 2 filters in the URL while approving after filter changes
@apps/frontend/playwright/mobile-ux.spec.ts
fe-coverage.2||AC8.13.76 stage 1 and stage 2 review routes remain usable at 375px
fe-coverage.3||AC8.13.82/AC16.27.2 desktop stage 1 review keeps transaction table readable at 1440px
@$fe/__tests__/coverageBaseline.test.ts
fe-coverage.4||AC8.13.92 keeps the frontend Vitest threshold baseline code-owned
@$t/test_s4_testing_gate_infrastructure.py|P1
governance.14||test_AC_testing_governance_14_jsonl_baseline_bindings_share_parameterized_behavior
governance.15||test_AC_testing_governance_15_traceability_tools_share_scanner_and_canonical_sort
@$t/test_s4_tool_homing.py|P1
governance.19||test_AC_testing_governance_19_ai_ocr_gate_and_data_are_package_owned
governance.20||test_AC_testing_governance_20_fat_tool_ratchet_rejects_new_and_stale_debt
toolchain.13||test_AC_testing_toolchain_13_dev_commands_share_env_aware_toolchain|P2
@$t/test_executed_proof.py
capability-proof.1||test_AC_testing_capability_proof_1_pytest_junit_binds_exact_ci_coordinates
capability-proof.3||test_AC_testing_capability_proof_3_post_call_consumer_is_single_and_fail_closed
capability-proof.4||test_AC_testing_capability_proof_4_partial_rerun_accepts_earlier_attempt_of_same_run
@$t/test_trusted_year_scenario.py
capability-proof.2||test_AC_testing_capability_proof_2_binding_rejects_stitching
trusted-year.1||test_AC_testing_trusted_year_1_scenario_is_small_exact_and_closed
@$t/test_source_capability_proof.py
source-capability-proof.1||test_AC_testing_source_capability_proof_1_real_registry_resolves_to_required_proofs
source-capability-proof.2||test_AC_testing_source_capability_proof_2_static_matrix_is_retired
@$be/integration/test_trusted_year_scenario.py
trusted-year.2|The v0 scenario deterministically traverses reviewed source authority, ledger posting, valuation, and every report section to exact oracle values.|test_AC_testing_trusted_year_2_deterministic_executor_proves_package_lifecycle
trusted-year.3|Cross-scope and target-mismatched authority mutations are rejected, and superseding every authority parent in the selected manifest makes the next package candidate draft/unproven.|^
package-lifecycle.1|A trusted package can be generated, listed, reopened, and exported.|^
@$e2e/test_institution_statement_journeys.py
package-lifecycle.2|A generated supported GXS monthly PDF traverses live extraction, explicit source/economic review, one posted effect per transaction, and trusted package generation, list, reopen, and JSON/CSV export with independent Decimal totals and unchanged frozen input decisions after a separately posted income changes the live report.|test_gxs_statement_journey_matches_expected_balances
package-lifecycle.3|A fresh ordinary user uploads a generated supported GXS PDF, creates required accounts directly from classification review.|^
@$be/integration/test_pdf_report_checkpoint.py
pdf-checkpoint.1||test_pdf_checkpoint_persists_source_and_fact_identity
pdf-checkpoint.2||test_pdf_checkpoint_report_lineage_reaches_source
pdf-checkpoint.3||test_pdf_checkpoint_three_statements_and_saved_package
@$t/test_benchmark_runner_selection.py|P1
benchmarks.1||test_domain_alone_selects_only_the_cases_of_that_domain
benchmarks.2||test_a_run_with_only_skipped_cases_never_succeeds
benchmarks.5||test_case_1_replay_mode_uploads_generated_csv_for_all_four_months
@$t/test_benchmark_browser_oracle.py|P1
benchmarks.3||test_every_route_failing_to_load_fails_the_check
@$t/test_benchmark_flow_registry.py|P1
benchmarks.4||test_benchmark_mapping_ssot_bijection_and_coverage
@$t/test_benchmark_scenario_suite.py|P1
benchmarks.6||test_benchmark_oracle_triple_accounting_articulation_pass_and_fail
benchmarks.7||test_benchmark_manifest_v2_fixtures_verified
benchmarks.8||test_benchmark_reporter_summary_extraction_v2
@$t/test_benchmark_runner_review_path.py|P1
benchmarks.9||test_AC_testing_benchmarks_9_ephemeral_user_pins_explicit_review_path
@$t/test_benchmark_advisor_oracle.py|P1
benchmarks.10||test_AC_testing_benchmarks_10_a_heading_that_reports_a_finding_fails
@$t/test_benchmark_runner_source_facts.py|P1
benchmarks.11||test_AC_testing_benchmarks_11_a_missing_statement_fact_is_never_replaced_by_a_default
benchmarks.12||test_AC_testing_benchmarks_12_a_manifest_entry_without_a_hash_fails_verification
@$t/test_benchmark_runner_upload.py|P2
benchmarks.16||test_AC_testing_benchmarks_16_a_csv_without_an_institution_gets_the_default_institution
@$t/test_journey_board.py|P1
journey-board.1||test_AC_testing_journey_board_1_checkpoint_status_follows_reached_order
journey-board.2||test_AC_testing_journey_board_2_retry_skip_and_absence_are_distinct
journey-board.3||test_AC_testing_journey_board_3_missing_evidence_is_shown_not_hidden
journey-board.4||test_AC_testing_journey_board_4_index_and_fragment_are_regenerated_honestly
journey-board.5||test_AC_testing_journey_board_5_checkpoint_map_matches_test_source
journey-board.6||test_AC_testing_journey_board_6_publisher_wiring_keeps_gates_read_only
journey-board.7||test_AC_testing_journey_board_7_core_journey_lane_runs_after_deploy_and_files_no_alert
journey-board.8||test_AC_testing_journey_board_8_release_shows_the_row_and_true_canary_evidence
@$t/test_core_journey_order.py|P2
journey-board.9||test_AC_testing_journey_board_9_the_burst_journeys_run_last
@$t/test_backend_test_timeout.py|P1|done|property
backend-test-timeout.1||test_AC_testing_backend_test_timeout_1_config_sets_a_thread_timeout_that_fits_the_pr_budget
backend-test-timeout.2||test_AC_testing_backend_test_timeout_2_a_hung_test_fails_by_name_with_the_project_method
backend-test-timeout.3||test_AC_testing_backend_test_timeout_3_a_hung_xdist_worker_prints_its_stack_before_the_timeout
@$be/infra/test_planner_statistics.py|P1
backend-test-planner.1||test_AC_testing_backend_test_planner_1_worker_tables_have_autovacuum_disabled
backend-test-planner.2||test_AC_testing_backend_test_planner_2_a_year_load_keeps_true_size_estimates_and_a_fast_cash_flow
backend-test-planner.3||test_AC_testing_backend_test_planner_3_a_recreated_table_has_autovacuum_disabled
backend-test-planner.4||test_AC_testing_backend_test_planner_4_the_guard_passes_in_the_session_after_a_table_was_recreated
@$t/test_e2e_transport_retry.py|P1
e2e-poll-reconnect.1||test_AC_testing_e2e_poll_reconnect_1_the_fourth_closed_connection_in_a_row_fails
e2e-poll-reconnect.2||test_AC_testing_e2e_poll_reconnect_2_the_twelve_month_journey_makes_no_direct_get_call
@$t/test_provider_journey_review_contract.py|P1
e2e-runs-wait.1|The shared approval helper waits until the runs list (GET /statements/{id}/runs) shows no requested or running run, for at most 240 s, before it posts any /review/approve request. At the limit it stops waiting and posts the approval (#2994).|test_AC_testing_e2e_runs_wait_1_no_approval_is_posted_while_a_run_is_active
@$t/test_e2e_path_quality.py|P1
e2e-path-quality.1||test_AC_testing_e2e_path_quality_1_a_second_edge_location_or_one_failure_shows_instability
@$t/test_e2e_description_fidelity.py|P1
e2e-description-fidelity.1||test_AC_testing_e2e_description_fidelity_1_the_journey_rule_counts_two_swapped_interest_rows_and_rejects_a_third
@$t/test_e2e_auth_redaction.py|P1
e2e-auth-redaction.1||test_AC_testing_e2e_auth_redaction_1_makereport_scrubs_string_and_structured_longrepr
@$t/test_e2e_failure_diagnostics.py|P1
e2e-failure-diagnostics.1||test_AC_testing_e2e_failure_diagnostics_1_failed_page_test_writes_screenshot_bounded_redacted_text_and_errors
e2e-failure-diagnostics.2||test_AC_testing_e2e_failure_diagnostics_2_select_touched_e2e_maps_specs_and_frontend_routes_without_llm
""",
    ),
    concepts=concepts(
        """
trusted_year_scenario|common/testing/readme.md#trusted-year-scenario|Small immutable annual input, independent Decimal oracle, and single-proof binding for terminal report-package verification.|common/testing/trusted_year.py,apps/backend/tests/integration/test_trusted_year_scenario.py,tests/tooling/test_trusted_year_scenario.py|tests/tooling/test_trusted_year_scenario.py,apps/backend/tests/integration/test_trusted_year_scenario.py|tdd|concept
journey_board|common/testing/readme.md#journey-board|Per-revision core-journey board.|common/testing/journey_board.py,common/testing/data/core-journey-checkpoints.json,runtime-hooks.manifest.json,docs/board/index.html,tests/e2e/journey_checkpoint.py|tests/tooling/test_journey_board.py|delivery|concept
tool_shim_contract|common/testing/tool_shim_contract.py|Shrink-only line-count ratchet that prevents new top-level tools/*.py implementations over 40 lines.|common/testing/readme.md,tests/tooling/test_s4_tool_homing.py|tests/tooling/test_s4_tool_homing.py|delivery|baseline
staging_ai_ocr_gate_contract|common/testing/staging_ai_ocr_gate_contract.py|Package-owned staging AI-OCR corpus, replay accounting, preflight, and JUnit classification contract.|common/testing/data/staging-ai-ocr-replay-counters.json,runtime-hooks.manifest.json|tests/tooling/test_staging_ai_ocr_gate_contract.py,tests/tooling/test_s4_tool_homing.py|delivery|concept
developer_toolchain|common/runtime/dev/toolchain.py|Shared runtime-version, uv command, and env-aware container runtime selection for local developer commands.|common/runtime/dev/cli.py,common/runtime/dev/dev_backend.py,common/runtime/dev/test_lifecycle.py|tests/tooling/test_s4_tool_homing.py|development|concept
gate_cli|common/meta/base/gate_cli.py|Shared policy-gate command boundary for repository-root parsing, workflow-command-safe annotations, summaries, and integer status codes.|common/testing/readme.md|tests/tooling/test_s4_testing_gate_infrastructure.py|delivery|concept
ac_graph|common/testing/ac_graph.py|The one AC-keyed graph (EPIC -> AC -> Proof -> vision).|common/testing/tdd.md,common/testing/data/critical-proof-outcomes.yaml,common/testing/data/protection-floor.json,common/testing/protection.py,common/testing/ac_proof.py,vision.md,.github/workflows/ci.yml|tests/tooling/test_ac_index_consistency.py,tools/check_ac_index.py|tdd|model
ac_proof_execution_model|common/testing/ci-cd.md#ac-proof-execution-model|AC-keyed proof execution placement model.|common/testing/ac_proof_execution.py,common/testing/ac_proof.py,common/testing/ac_graph.py,docs/project/EPIC-008.testing-strategy.md|tests/tooling/test_ac_proof_execution_model.py|delivery|concept|documented_contract|ci_workflow
ci_workflow|common/testing/ci-cd.md#ci-job-structure|CI job structure (lint → backend shards → frontend → coverage) and the local guardrail tiers (pre-commit → pre-push → CI) that left-move its cheap drift gates.|common/meta/development.md,common/testing/coverage.md,.github/workflows/ci.yml,.pre-commit-config.yaml|-|tdd|playbook
critical_proof_matrix|common/testing/generate_critical_proof_matrix.py|README -> EPIC -> E2E macro outcome guard and core proof-path matrix, a DERIVED (not committed) view of the one AC-keyed graph.|README.md,common/testing/tdd.md,common/testing/ci-cd.md,common/testing/data/critical-proof-outcomes.yaml,common/testing/ac_graph.py,.github/workflows/ci.yml,common/testing/ac_proof.py,tools/check_ac_index.py|-|tdd|matrix|-|ac_graph
critical_proof_outcomes|common/testing/data/critical-proof-outcomes.yaml|Hand-maintained macro-outcome contract source (outcome -> owner EPICs + proof_ids) merged into the derived critical proof matrix view.|common/testing/ac_graph.py,common/testing/generate_critical_proof_matrix.py|-|tdd|registry|human_curated|critical_proof_matrix
github_action_runtime|common/testing/data/github-action-runtime.yaml|External GitHub JavaScript action runtime inventory.|common/testing/ci-cd.md,.github/workflows/ci.yml|tests/tooling/test_workflow_contract.py,tests/tooling/test_post_merge_e2e_gates.py|delivery|matrix|human_curated|ci_workflow
pdf_fixtures|common/testing/readme.md#pdf-fixtures|Synthetic PDF fixture commands, local-only real-PDF handling, committed template policy, and font fallback.|common/testing/fixtures/pdf/README.md,common/testing/fixtures/pdf/FONT_HANDLING.md,common/testing/fixtures/pdf/analyzers/README.md,tests/tooling/test_pdf_fixture_epic009_behavior.py,tests/tooling/test_pdf_fixture_parseable.py|-|pdf|concept
pr_review_thread_merge_gate|common/testing/ci-cd.md#pr-review-thread-merge-gate|Merge-time gate that blocks unresolved P0/P1 (and Copilot-authored) PR review threads, and the documented severity classification rule.|docs/project/EPIC-008.testing-strategy.md,.github/workflows/ci.yml|tests/tooling/test_check_pr_review_threads.py|delivery|concept|documented_contract
protection_count_floor|common/testing/data/protection-floor.json|Per-type PROTECTION COUNT floor (Gate B of tools/check_ac_index.py).|common/testing/tdd.md,common/testing/protection.py,common/testing/check_ac_index.py,tools/check_ac_index.py,tests/tooling/test_ac_index_consistency.py|-|tdd|baseline|machine_generated|tdd_workflow
source_capability_proof_join|common/testing/source_capability_proof.py|Generic fail-closed join from owner-declared source capabilities to the existing AC proof graph.|apps/backend/src/extraction/base/source_capability.py,common/testing/ac_proof.py,common/testing/check_ac_index.py,tools/check_ac_index.py|tests/tooling/test_source_capability_proof.py,tools/check_ac_index.py|source|concept
ssot_governance_gates|common/testing/tdd.md#ssot-governance-gates|Incremental prevent-worse CI gates for changed SSOT files and changed manifest entries.|docs/project/EPIC-014.ttd-transformation.md,common/meta/data/governance-exceptions.yaml,common/meta/extension/governance_report/_gate.py,tools/report_ssot_governance.py,tests/tooling/test_ssot_governance_report.py,.github/workflows/ci.yml|-|tdd|concept
ssot_governance_metrics|common/testing/tdd.md#ssot-governance-metrics|Report-only governance metrics for SSOT ownership, shape, proof coverage, and future gate candidates.|docs/project/EPIC-014.ttd-transformation.md,common/meta/extension/governance_report/_metrics.py,tools/report_ssot_governance.py,tests/tooling/test_ssot_governance_report.py,.github/workflows/ci.yml|-|tdd|baseline
tdd_workflow|common/testing/tdd.md|EPIC → ACx.y.z → Test → Code → Doc mandatory sequence.|AGENTS.md,docs/agents/orchestration.md,.github/workflows/ci.yml,tools/check_ac_index.py|-|tdd|playbook
test_coverage|common/testing/coverage.md|Unified coverage system (backend + frontend + common + tools).|common/testing/tdd.md,common/testing/ci-cd.md|tests/tooling/test_ci_metrics_contract.py|tdd|baseline
test_execution_matrix|common/testing/matrix.py|Test placement and selection SSOT.|common/testing/data/test-execution-matrix.yaml,common/testing/ci-cd.md,common/testing/tdd.md,tools/check_ac_index.py,tools/test_selection.py|tests/tooling/test_execution_matrix_contract.py|tdd|matrix
test_execution_matrix_generated_view|common/testing/data/test-execution-matrix.yaml|Generated view of common/testing/matrix.py kept for AC-traceability consumers.|common/testing/matrix.py,tools/test_selection.py|tests/tooling/test_execution_matrix_contract.py|tdd|matrix|-|test_execution_matrix
test_optimization|common/testing/ci-cd.md#test-optimization|Smart/fast/full test modes and 8-way seeded backend sharding strategy.|common/meta/development.md,common/testing/coverage.md|apps/backend/tests/unit/infra/test_test_lifecycle.py,tests/tooling/test_github_workflow_timing_summary.py|platform|concept
vision_proof_matrix|common/testing/generate_vision_proof_matrix.py|Vision-anchor -> EPIC -> AC -> test proof matrix, a DERIVED (not committed) view of the one AC-keyed graph, built in memory by build_matrix and gated by tools/check_ac_index.py (supersedes #442/#480).|vision.md,common/testing/ac_graph.py,docs/project/EPIC-014.ttd-transformation.md,.github/workflows/ci.yml|tests/tooling/test_generate_vision_proof_matrix.py|tdd|matrix|-|ac_graph
"""
    ),
)

TEST_ROOTS: tuple[str, ...] = (
    "tests/tooling/test_ci_metrics_contract.py",
    "tests/tooling/test_workflow_contract.py",
)
