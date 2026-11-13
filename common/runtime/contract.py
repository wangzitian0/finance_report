"""PackageContract for ``runtime``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    concepts,
    invs,
    rels,
)

CONTRACT = PackageContract(
    name="runtime",
    status="active",
    tier="CODE-ONLY",
    depends_on="observability".split(),
    implementations={"be": "apps/backend/src/runtime", "fe": None},
    context=ContextScope(
        purpose="Own the app-to-external-world dependency contract.",
        in_scope=[
            "Dependency manifest and environment-tier vocabulary.",
            "Dependency probes, smoke checks, and release evidence transport.",
            "External service substitution and presence assertions.",
        ],
        out_of_scope=[
            "Telemetry emission, logging policy, or observability query ownership.",
            "Business-domain state, financial policy, and domain events.",
            "In-process workflow or cross-domain application orchestration.",
        ],
    ),
    relationships=rels(
        "runtime",
        """
observability|published-language|Uses observability's published logger and health-status language.
""",
    ),
    interface="""
APP_OWNED_TIERS AnalyticsCheck DEPENDENCY_MANIFEST DatabaseCheck Dependency
DependencyKind DependencyManifest EnvTier LlmCheck MarketDataCheck
NON_DEPENDENCY_ENV_FIELDS ObjectStorageCheck RedisCheck StorageError StorageService
TelemetryCheck VPS_TIERS WorkflowEngineCheck check_env_classification
redact_presigned_url register_known_storage_paths_provider resolve_env_tier
run_storage_sweep runtime_system_router
""".split(),
    events=[],
    invariants=invs(
        """
env-key-extraction-robust|Parsing env keys from a missing .env.example yields an empty set with a warning, not an exception.|$t/test_check_env_keys.py::test_main_exits_1_when_the_example_is_missing
"""
    ),
    roadmap=acs(
        "runtime",
        """
@$be/runtime/test_runtime_and_ci_contracts.py
1.1|The API health endpoint is reachable and returns 200.|test_api_health_endpoint_contract
1.2|The backend service is reachable and returns a structured health JSON.|^
1.3||test_frontend_api_proxy_routing_contract
1.4||test_database_environment_isolation_contract
@$be/infra/test_boot.py
3.1||test_AC_runtime_3_1_required_checks_cover_the_tier_declaration|P1
21.1||test_AC1_10_1_static_config_rejects_default_secret_key_in_production
21.2||test_AC1_10_1_static_config_rejects_short_secret_key_in_staging
21.3||test_AC1_10_1_static_config_rejects_default_db_in_protected_env
21.4||test_AC1_10_1_static_config_rejects_default_s3_secret_in_production_like_url
21.5||test_AC1_10_1_static_config_rejects_blank_secret_key_in_production
21.6||test_AC1_10_1_static_config_allows_development_default_secret_key|P1
guard-proofs.1||test_AC_runtime_guard_proofs_1_every_default_is_rejected_under_every_protected_trigger
guard-proofs.2||test_AC_runtime_guard_proofs_2_development_defaults_accepted_in_local_environments
guard-proofs.3||test_AC_runtime_guard_proofs_3_protected_runtime_classification
@$be/runtime/test_health_parity.py|P1
6.1||test_AC_runtime_6_1_full_health_asserts_the_declared_set
7.3||test_AC_runtime_7_3_plain_health_is_fast_liveness_without_external_io
@$be/infra/test_main.py
7.1||test_health_when_all_services_healthy
7.2||test_health_returns_503_on_database_failure
@$be/infra/test_config_contract.py
18.1||test_small_model_format
18.2||test_config_sync_with_env_example
18.3||test_base_currency_format
18.4||test_s3_bucket_format
18.5||test_jwt_algorithm_allowed
18.6||test_database_url_format
20.1||test_db_pool_size_config_default|P1
20.2||test_db_pool_max_overflow_config_default|P1
20.3||test_db_pool_config_valid_range|P1
20.4|The DB_POOL_SIZE env var overrides the pool-size setting.|test_db_pool_size_env_override|P1
20.5|The DB_POOL_MAX_OVERFLOW env var overrides the max-overflow setting.|^|P1
@$be/api/test_real_storage_pipeline.py
23.1||test_AC8_26_1_upload_parses_through_real_storage_round_trip
23.2||test_AC8_26_2_retry_loads_source_back_through_real_storage
@$t/test_debug.py|P1
24.1||test_AC16_11_1_detect_environment_ci
24.2||test_AC16_11_2_detect_environment_local_when_docker_ok
24.3||test_AC16_11_3_detect_environment_fallback_production
24.4||test_AC16_11_4_validate_hostname_cases
24.5||test_AC16_11_5_validate_username_cases
24.6||test_AC16_11_6_get_container_name_mapping
24.7||test_AC16_11_7_list_containers_prints_all
24.21||test_AC16_11_21_view_remote_logs_docker_exits_when_vps_host_missing
24.22||test_AC16_11_22_view_remote_logs_docker_exits_on_invalid_host
24.23||test_AC16_11_23_view_remote_logs_docker_exits_on_invalid_user
24.24||test_AC16_11_24_view_local_logs_builds_docker_command
24.25||test_AC16_11_25_main_logs_observability_path
24.26||test_AC16_11_26_main_status_local_path
24.27||test_AC16_11_27_main_containers_path
@$t/test_cleanup_orphaned_dbs.py|P1
24.8||test_AC16_11_8_extract_namespace_variants
24.9||test_AC16_11_9_load_active_namespaces_missing
24.10||test_AC16_11_10_get_container_runtime_prefers_podman
24.11||test_AC16_11_11_list_test_databases_parses_rows
24.12||test_AC16_11_12_cleanup_orphaned_runtime_missing
24.13||test_AC16_11_13_cleanup_orphaned_no_databases
24.14||test_AC16_11_14_cleanup_orphaned_skips_active
24.15||test_AC16_11_15_cleanup_orphaned_clean_all
24.30||test_AC16_11_30_drop_database_dry_run_returns_true
24.31||test_AC16_11_31_main_calls_cleanup_orphaned
@$t/test_cli_and_dev_servers.py|P1
24.16||test_AC16_11_16_get_compose_cmd_prefers_podman
24.17||test_AC16_11_17_cmd_test_frontend_route
24.18||test_AC16_11_18_cmd_clean_routes
24.19||test_AC16_11_19_check_database_ready_failure
24.20||test_AC16_11_20_dev_frontend_cleanup_is_process_pure
24.28||test_AC16_11_28_check_database_ready_success
24.29||test_AC16_11_29_dev_backend_cleanup_is_process_pure
@$t/test_verify_release_images.py|P1
release-images.1||test_AC_runtime_release_images_1_first_attempt_success_no_retry
release-images.2||test_AC_runtime_release_images_2_transient_miss_then_success_retries
release-images.3||test_AC_runtime_release_images_3_exhausted_retries_fails_closed
release-images.4||test_AC_runtime_release_images_4_max_attempts_and_delay_are_configurable|P2
release-images.5||test_AC_runtime_release_images_5_max_attempts_below_1_is_rejected|P2
release-images.6||test_AC_runtime_release_images_6_negative_delay_is_rejected|P2
@$be/integration/test_bootloader_real_checks.py
guard-proofs.4||test_AC_runtime_guard_proofs_4_real_database_check_passes_against_live_service
guard-proofs.5||test_AC_runtime_guard_proofs_5_real_s3_check_passes_against_live_service
guard-proofs.6||test_AC_runtime_guard_proofs_6_real_database_check_reds_on_dead_port
@$be/infra/test_observability_contract.py
guard-proofs.7||test_AC_runtime_guard_proofs_7_telemetry_tag_value_mismatch_fails_boot
guard-proofs.8||test_AC_runtime_guard_proofs_8_telemetry_tag_value_match_boots
@$t/test_required_env_manifest.py|P1
guard-proofs.11||test_AC_runtime_guard_proofs_11_manifest_matches_live_config_bidirectionally
guard-proofs.12||test_AC_runtime_guard_proofs_12_every_vault_field_reaches_manifest_and_env_example
guard-proofs.13||test_AC_runtime_guard_proofs_13_every_field_names_its_producer_and_the_offline_gate_is_green
guard-proofs.14||test_AC_runtime_guard_proofs_14_sensitive_credentials_and_filtered_consumer_validation
@$t/test_sla_manifest.py|P1
sla-manifest.1||test_AC_runtime_sla_manifest_1_committed_manifest_matches_live_dependency_manifest
sla-manifest.2||test_AC_runtime_sla_manifest_2_production_entries_are_sla_bearing_and_complete
@$t/test_s4_tool_homing.py|P1
http-probes.1||test_AC_runtime_http_probes_1_runtime_checks_share_hardened_http_primitives
extension-tools.1||test_AC_runtime_extension_tools_1_backend_gates_share_project_root|P2
@$be/runtime/test_env_guardrail.py|P1
2.1||test_every_config_env_var_is_classified
@$be/runtime/test_probe_adapters.py|P1
4.1||test_AC_runtime_4_1_every_declared_dependency_has_a_probe_adapter
@$t/test_sdk_pin.py|P1
sdk-pin.1||test_AC_runtime_sdk_pin_1_lock_and_declaration_must_agree
@$t/test_workflow_runner_pin.py|P1
runner-pin.1||test_AC_runtime_runner_pin_1_no_workflow_uses_a_floating_runner_label
@$fe/__tests__/frontendVersionRoute.test.ts
fe-deploy.1||AC8.13.90 returns deployed frontend version metadata for deploy readiness
@$t/test_s4_runtime_github_api.py|P1
github-api.1||test_AC_runtime_github_api_1_runtime_and_testing_share_github_helpers
@$t/test_workflow_sdk_install.py|P1
sdk-install.1||test_AC_runtime_sdk_install_1_every_job_installs_the_sdk_before_it_runs_a_tool_that_needs_it
@$t/test_reusable_workflow_permissions.py|P1
reusable-permissions.1||test_AC_runtime_reusable_permissions_1_every_call_grants_what_the_called_jobs_request
@$t/test_env_empty_value_producers.py|P1
env-empty-values.1||test_AC_runtime_env_empty_values_1_no_artifact_ships_an_empty_alias_chain_value
@$be/infra/test_config.py|P1
env-empty-values.2||test_AC_runtime_env_empty_values_2_settings_empty_env_resolution
@$be/infra/test_ai_key_alias.py|P1
env-ai-key-alias.1||test_AC_runtime_env_ai_key_alias_1_the_old_name_sets_the_key
""",
    ),
    concepts=concepts(
        """
runtime_http_probe|common/runtime/http_probe.py|Shared deployed-runtime HTTP response, fetch, report, and empty-safe abbreviated-SHA matching primitives.|common/runtime/tier2_http_e2e.py,common/runtime/readme.md|tests/tooling/test_s4_tool_homing.py|runtime|concept
runtime_extension_project_root|apps/backend/src/runtime/extension/project_root.py|Repository-root lookup shared by backend-owned runtime extension gates.|apps/backend/src/runtime/extension/env_keys.py,apps/backend/src/runtime/extension/schema_validation.py|tests/tooling/test_s4_tool_homing.py|development|concept
container_naming|common/runtime/environments.md#container-naming-patterns|Container name patterns per environment (hyphens vs underscores).|common/runtime/deployment.md,AGENTS.md|tests/tooling/test_issue_489_deployment_contracts.py|platform|concept
deployment_architecture|common/runtime/deployment.md|Dual-repo model, Vault secret injection, staging/production flow.|common/meta/development.md,common/runtime/environments.md|tests/tooling/test_issue_489_deployment_contracts.py,tests/tooling/test_post_merge_e2e_gates.py|runtime|concept
env_reference_generated|common/runtime/env-reference.generated.md|Generated backend env reference (rendered from config.py Settings metadata.|apps/backend/src/config.py,tools/generate_env_reference.py,.env.example|tests/tooling/test_env_reference.py|development|registry
env_smoke_test|common/runtime/readme.md#environment-verification-the-three-gates|Environment smoke testing via real boot operations.|common/meta/development.md|tests/tooling/test_runtime_incident_response_ssot.py,tests/tooling/test_runtime_ssot_internalized.py|runtime|playbook
required_env_manifest_generated|common/runtime/required-env.generated.json|Generated machine-readable required-env manifest (same config.py source of truth as .env.example.|apps/backend/src/config.py,tools/generate_env_reference.py,.env.example|tests/tooling/test_required_env_manifest.py|development|registry
runtime_incident_response|common/runtime/runtime-incident-response.md|App-side runtime incident triage and stability-proof routing.|common/runtime/deployment.md,common/observability/observability.md,common/testing/ci-cd.md,common/runtime/ci-cd.md,common/runtime/readme.md,docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md|tests/tooling/test_runtime_incident_response_ssot.py|runtime|playbook
environments|common/runtime/environments.md#environment-overview|Local Dev / Local CI / GitHub CI / Staging / Production.|common/meta/development.md,common/testing/ci-cd.md,common/runtime/deployment.md|tests/tooling/test_issue_489_deployment_contracts.py|environments|concept
"""
    ),
)

TEST_ROOTS: tuple[str, ...] = ("apps/backend/tests/infra/test_main.py",)
