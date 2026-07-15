"""The ``runtime`` package's machine-checkable :class:`PackageContract`.

``runtime`` is the app↔external-world dependency boundary: it owns the *contract*
for the external backends the application depends on (object storage, the LLM
provider, cache, telemetry, …), how each of the six environments substitutes
them, and the invariant that a *declared* dependency must be *asserted present*
(no silent ``skipped``/``warning``/fallback).

An ``infra`` leaf (L1, ``depends_on=[]``), now ``active``. The *construct* phase
shipped the ``base`` value language + dependency manifest + the
``DependencyCheck`` port; the *switch* phase added the ``extension`` probe
adapters (``DatabaseCheck`` / ``ObjectStorageCheck`` / ``LlmCheck``, published
below) that ``boot.Bootloader`` delegates to; the *cleanup* phase dropped the
silent ``skipped`` status. The *migrate* phase homes the smoke-test / health
ACs here: EPIC-008 AC8.1.1–.4 → ``AC-runtime.1.*`` (smoke / service reachability /
DB connectivity) and EPIC-007 AC7.7.1–.2 → ``AC-runtime.7.*`` (``/health``
dependency-presence), each ``test=`` resolving to its existing proof; the package
tier (CODE-ONLY) gives ``proof_kind=exact``; the model-dominant substitute
proofs live with their owning packages (AC-llm.6.2, EPIC-008 AC8.26.*). (Step 3 / cleanup absorbs the
env-smoke-test SSOT prose into ``readme.md`` and retires the doc.) Remaining as a
future feature (not this migration): manifest-driven
``validate`` for *all* declared dependencies per env tier + smoke↔declaration
parity — see ``todo.md``.
"""

from __future__ import annotations

from common.meta.package_contract import (
    ACRecord,
    ConceptRecord,
    Invariant,
    PackageContract,
)

CONTRACT = PackageContract(
    name="runtime",
    status="active",
    tier="CODE-ONLY",
    # #1674: "config" was declared but its only import was src.config (the app
    # Settings singleton) — not the registered config package (common/config,
    # env_keys/schema_validation), which runtime never actually imports.
    depends_on=["observability"],
    roles=[],
    implementations={"be": "apps/backend/src/runtime", "fe": None},
    interface=[
        "APP_OWNED_TIERS",
        "AnalyticsCheck",
        "DEPENDENCY_MANIFEST",
        "DatabaseCheck",
        "Dependency",
        "DependencyCheck",
        "DependencyKind",
        "DependencyManifest",
        "DependencyStatus",
        "EnvTier",
        "LlmCheck",
        "MarketDataCheck",
        "NON_DEPENDENCY_ENV_FIELDS",
        "ObjectStorageCheck",
        "ProbeResult",
        "RedisCheck",
        "StorageError",
        "StorageService",
        "TelemetryCheck",
        "VPS_TIERS",
        "WorkflowEngineCheck",
        "check_env_classification",
        "redact_presigned_url",
        "register_known_storage_paths_provider",
        "resolve_env_tier",
        "run_storage_sweep",
    ],
    events=[],
    invariants=[
        # ── folded in from the retired config package (#1669) ──
        Invariant(
            id="env-key-extraction-robust",
            statement="Parsing env keys from a missing source file yields an empty set, not an error, so the consistency check degrades gracefully.",
            test="tests/tooling/test_check_env_keys.py::test_returns_empty_set_for_missing_file",
        ),
    ],
    roadmap=[
        # ── Smoke tests / service reachability (was EPIC-008 AC8.1.1–.4) ──
        ACRecord(
            id="AC-runtime.1.1",
            statement="The API health endpoint is reachable and returns 200. Was EPIC-008 AC8.1.1.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_api_health_check",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.1.2",
            statement="The backend service is reachable and returns a structured health JSON. Was EPIC-008 AC8.1.2.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_backend_service_reachable",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.1.3",
            statement="The frontend API proxy is reachable, validating API availability through the proxy. Was EPIC-008 AC8.1.3.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_frontend_api_proxy_reachable",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.1.4",
            statement="Database connectivity is proven through a create+read cycle. Was EPIC-008 AC8.1.4.",
            test="apps/backend/tests/e2e/test_core_journeys.py::test_database_connectivity",
            priority="P0",
            status="done",
        ),
        # ── config↔manifest env-var guardrail (#1579) ──
        ACRecord(
            id="AC-runtime.2.1",
            statement=(
                "Every config.py env var is classified: a declared dependency env var in the "
                "DependencyManifest, or a reasoned NON_DEPENDENCY_ENV_FIELDS entry — an "
                "unclassified new env var fails CI (fail-closed guardrail, #1579)."
            ),
            test="apps/backend/tests/runtime/test_env_guardrail.py::test_every_config_env_var_is_classified",
            priority="P1",
            status="done",
        ),
        # ── manifest-driven validate (#1577) ──
        ACRecord(
            id="AC-runtime.3.1",
            statement=(
                "boot.validate FULL derives its dependency set from "
                "DEPENDENCY_MANIFEST.required_for(resolve_env_tier(...)) — a declared-required "
                "probed dependency that is absent fails validate; a declared-required dependency "
                "without a probe adapter is a visible warning (#1580), never a silent skip (#1577)."
            ),
            test="apps/backend/tests/infra/test_boot.py::test_AC_runtime_3_1_required_checks_cover_the_tier_declaration",
            priority="P1",
            status="done",
        ),
        # ── probes for every declared dependency (#1580) ──
        ACRecord(
            id="AC-runtime.4.1",
            statement=(
                "Every declared dependency has a DependencyCheck probe adapter — "
                "Bootloader._required_checks finds a probe for every dependency of every tier, "
                "so invariant 2 (absent ⇒ fail) is enforceable across the whole manifest (#1580)."
            ),
            test="apps/backend/tests/runtime/test_probe_adapters.py::test_AC_runtime_4_1_every_declared_dependency_has_a_probe_adapter",
            priority="P1",
            status="done",
        ),
        # ── smoke ↔ declaration parity (invariant 6, #1578) ──
        ACRecord(
            id="AC-runtime.6.1",
            statement=(
                "The smoke's dependency-presence assertion covers exactly the manifest-declared set: "
                "GET /health?full=1 (called by tools/smoke_test.sh) probes every dependency in "
                "DEPENDENCY_MANIFEST.required_for(tier) and returns 503 on any absence "
                "(invariant 6, #1578; the tag→production gate already requires the staging smoke)."
            ),
            test="apps/backend/tests/runtime/test_health_parity.py::test_AC_runtime_6_1_full_health_asserts_the_declared_set",
            priority="P1",
            status="done",
        ),
        # ── /health dependency-presence (was EPIC-007 AC7.7.1–.2) ──
        ACRecord(
            id="AC-runtime.7.1",
            statement="/health returns 200 when all declared dependencies are present. Was EPIC-007 AC7.7.1.",
            test="apps/backend/tests/infra/test_main.py::test_health_when_all_services_healthy",
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.7.2",
            statement="/health returns 503 when a declared dependency is absent (invariant 2). Was EPIC-007 AC7.7.2.",
            test="apps/backend/tests/infra/test_main.py::test_health_returns_503_on_database_failure",
            priority="P0",
            status="done",
        ),
        # ── folded in from the retired config package (#1669) — group numbers
        # preserved from the original EPIC-012 lineage (AC12.18.* / AC12.20.*
        # -> AC-config.18.*/.20.* -> AC-runtime.18.*/.20.*) so the history stays
        # traceable; they don't collide with runtime's own groups 1-7. ──
        ACRecord(
            id="AC-runtime.18.1",
            statement=(
                "PRIMARY_MODEL follows the expected provider pattern (the zai "
                "GLM model-id form). Was EPIC-012 AC12.18.1."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_primary_model_format"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.18.2",
            statement=(
                "The config.py default for PRIMARY_MODEL matches the .env.example "
                "documentation (config↔docs sync). Was EPIC-012 AC12.18.2."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_config_sync_with_env_example"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.18.3",
            statement=(
                "BASE_CURRENCY is a valid ISO 4217 currency code (3 uppercase "
                "alphabetic chars). Was EPIC-012 AC12.18.3."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_base_currency_format"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.18.4",
            statement=(
                "S3_BUCKET follows S3 naming conventions (lowercase, 3-63 chars, hyphen-safe). Was EPIC-012 AC12.18.4."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_s3_bucket_format"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.18.5",
            statement=(
                "JWT_ALGORITHM is one of the allowed secure algorithms (HS256/RS256). Was EPIC-012 AC12.18.5."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_jwt_algorithm_allowed"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.18.6",
            statement=(
                "DATABASE_URL follows the expected async driver format "
                "(postgresql+asyncpg, or sqlite for tests). Was EPIC-012 AC12.18.6."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_database_url_format"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.1",
            statement=(
                "DB_POOL_SIZE config field exists with the expected default. Was EPIC-012 AC12.20.1."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_db_pool_size_config_default"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.2",
            statement=(
                "DB_POOL_MAX_OVERFLOW config field exists with the expected default. Was EPIC-012 AC12.20.2."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_db_pool_max_overflow_config_default"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.3",
            statement=(
                "Pool config values are within a valid range (pool_size >= 1, "
                "max_overflow >= 0). Was EPIC-012 AC12.20.3."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_db_pool_config_valid_range"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.4",
            statement=(
                "The DB_POOL_SIZE env var overrides the pool-size setting. Was EPIC-012 AC12.20.4."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_db_pool_size_env_override"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.5",
            statement=(
                "The DB_POOL_MAX_OVERFLOW env var overrides the max-overflow setting. Was EPIC-012 AC12.20.5."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py::test_db_pool_size_env_override"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 21: Bootloader static-config boot gate (was EPIC-001
        # AC1.10.1, migration closeout wave 3, #1663) — each branch of
        # Bootloader._check_static_config is a distinct rejection reason ──
        ACRecord(
            id="AC-runtime.21.1",
            statement="Bootloader._check_static_config rejects the default development JWT secret in production.",
            test=(
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC1_10_1_static_config_rejects_default_secret_key_in_production"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.21.2",
            statement="Bootloader._check_static_config rejects a short (low-entropy) JWT secret in staging.",
            test=(
                "apps/backend/tests/infra/test_boot.py::test_AC1_10_1_static_config_rejects_short_secret_key_in_staging"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.21.3",
            statement=(
                "Bootloader._check_static_config rejects the local-development DB default in a protected environment."
            ),
            test=(
                "apps/backend/tests/infra/test_boot.py::test_AC1_10_1_static_config_rejects_default_db_in_protected_env"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.21.4",
            statement=(
                "Bootloader._check_static_config treats a public app URL as "
                "protected even when ENVIRONMENT is misnamed (e.g. "
                "'preview'), rejecting a default S3 secret under it."
            ),
            test=(
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC1_10_1_static_config_rejects_default_s3_secret_in_production_like_url"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.21.5",
            statement="Bootloader._check_static_config rejects a blank/whitespace-only JWT secret in production.",
            test=(
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC1_10_1_static_config_rejects_blank_secret_key_in_production"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.21.6",
            statement=(
                "Bootloader._check_static_config allows the convenient "
                "development-default JWT secret in the development "
                "environment."
            ),
            test=(
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC1_10_1_static_config_allows_development_default_secret_key"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 22: GHCR SHA image retention (was EPIC-007 AC7.19.1,
        # migration closeout continuation, #1663 / #1714) ──
        ACRecord(
            id="AC-runtime.22.1",
            statement=(
                "The scheduled GHCR retention workflow selects backend/"
                "frontend :<sha> package versions for deletion only once "
                "they are past the 28-day retention window, while release "
                "tags and the live staging/production deploy SHA are always "
                "preserved (the fail-closed behavior when no live SHA "
                "exemption is available is proven separately by "
                "test_AC7_19_1_pruner_requires_live_sha_exemptions)."
            ),
            test=(
                "tests/tooling/test_ghcr_sha_retention.py::test_AC7_19_1_retention_selects_only_stale_sha_tags"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 23: real StorageService pipeline substitute (was EPIC-008
        # AC8.26, migration closeout continuation, #1663 / #1714) ──
        ACRecord(
            id="AC-runtime.23.1",
            statement=(
                "A CSV fixture uploads through /statements/upload with the "
                "real StorageService into in-memory S3 (env-level config "
                "only, never stubbed or patched); the pipeline parses it, "
                "the stored object read back via the real get_object is "
                "byte-identical to the fixture, and the resolved "
                "transactions carry the fixture's known business values."
            ),
            test=(
                "apps/backend/tests/api/test_real_storage_pipeline.py"
                "::test_AC8_26_1_upload_parses_through_real_storage_round_trip"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.23.2",
            statement=(
                "The retry path re-fetches the source document through the "
                "real get_object (the load-back leg the in-process first "
                "parse skips), and deleting the stored object makes retry "
                "fail instead of parsing a cached copy — proving the "
                "pipeline truly reads storage."
            ),
            test=(
                "apps/backend/tests/api/test_real_storage_pipeline.py"
                "::test_AC8_26_2_retry_loads_source_back_through_real_storage"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 24: dev-tooling / infra CLI commands (was EPIC-016
        # AC16.11.1-31, migration closeout continuation, #1663 / #1714) ──
        ACRecord(
            id="AC-runtime.24.1",
            statement="debug.detect_environment returns CI when GITHUB_ACTIONS is true.",
            test="tests/tooling/test_debug.py::test_AC16_11_1_detect_environment_ci",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.2",
            statement="debug.detect_environment returns LOCAL when docker ps succeeds.",
            test=(
                "tests/tooling/test_debug.py::test_AC16_11_2_detect_environment_local_when_docker_ok"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.3",
            statement="debug.detect_environment falls back to PRODUCTION on docker failure.",
            test=(
                "tests/tooling/test_debug.py::test_AC16_11_3_detect_environment_fallback_production"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.4",
            statement="debug.validate_hostname rejects empty and leading-hyphen hostnames.",
            test="tests/tooling/test_debug.py::test_AC16_11_4_validate_hostname_cases",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.5",
            statement="debug.validate_username enforces a unix-safe pattern.",
            test="tests/tooling/test_debug.py::test_AC16_11_5_validate_username_cases",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.6",
            statement="debug.get_container_name maps known service names by environment.",
            test="tests/tooling/test_debug.py::test_AC16_11_6_get_container_name_mapping",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.7",
            statement="debug.list_containers prints all mapped containers for an environment.",
            test="tests/tooling/test_debug.py::test_AC16_11_7_list_containers_prints_all",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.8",
            statement="cleanup_orphaned_dbs.extract_namespace handles worker suffixes and invalid names.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_8_extract_namespace_variants"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.9",
            statement="cleanup_orphaned_dbs.load_active_namespaces returns [] when the file is missing or corrupt.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_9_load_active_namespaces_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.10",
            statement="cleanup_orphaned_dbs.get_container_runtime returns the first available runtime.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_10_get_container_runtime_prefers_podman"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.11",
            statement="cleanup_orphaned_dbs.list_test_databases parses psql output and handles subprocess errors.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_11_list_test_databases_parses_rows"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.12",
            statement="cleanup_orphaned_dbs.cleanup_orphaned returns an error when the container runtime is missing.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_12_cleanup_orphaned_runtime_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.13",
            statement="cleanup_orphaned_dbs.cleanup_orphaned returns success when no test databases are found.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_13_cleanup_orphaned_no_databases"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.14",
            statement="cleanup_orphaned_dbs.cleanup_orphaned skips active-namespace databases.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_14_cleanup_orphaned_skips_active"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.15",
            statement="cleanup_orphaned_dbs.cleanup_orphaned cleans all databases in --all mode.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_15_cleanup_orphaned_clean_all"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.16",
            statement="cli.get_compose_cmd honors CONTAINER_RUNTIME, otherwise prefers podman then docker, and exits when neither is available.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py::test_AC16_11_16_get_compose_cmd_prefers_podman"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.17",
            statement="cli.cmd_test routes frontend/e2e/perf/tests and lifecycle modes correctly.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py::test_AC16_11_17_cmd_test_frontend_route"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.18",
            statement="cli.cmd_clean routes db/containers/default cleanup targets correctly.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py::test_AC16_11_18_cmd_clean_routes"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.19",
            statement="dev_backend.check_database_ready returns false on migration subprocess errors.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py::test_AC16_11_19_check_database_ready_failure"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.20",
            statement="dev_frontend.cleanup terminates the tracked process and exits cleanly.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py::test_AC16_11_20_dev_frontend_cleanup_terminates_and_exits"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.21",
            statement="debug.view_remote_logs_docker exits when VPS_HOST is missing.",
            test=(
                "tests/tooling/test_debug.py::test_AC16_11_21_view_remote_logs_docker_exits_when_vps_host_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.22",
            statement="debug.view_remote_logs_docker exits on invalid VPS hostnames.",
            test=(
                "tests/tooling/test_debug.py::test_AC16_11_22_view_remote_logs_docker_exits_on_invalid_host"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.23",
            statement="debug.view_remote_logs_docker exits on invalid VPS usernames.",
            test=(
                "tests/tooling/test_debug.py::test_AC16_11_23_view_remote_logs_docker_exits_on_invalid_user"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.24",
            statement="debug.view_local_logs builds the docker logs command with tail and follow.",
            test=(
                "tests/tooling/test_debug.py::test_AC16_11_24_view_local_logs_builds_docker_command"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.25",
            statement="debug.main routes the logs command to the observability handler when method=observability.",
            test=(
                "tests/tooling/test_debug.py::test_AC16_11_25_main_logs_observability_path"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.26",
            statement="debug.main routes the status command to the local log view with a status tail.",
            test="tests/tooling/test_debug.py::test_AC16_11_26_main_status_local_path",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.27",
            statement="debug.main routes the containers command to list_containers.",
            test="tests/tooling/test_debug.py::test_AC16_11_27_main_containers_path",
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.28",
            statement="dev_backend.check_database_ready returns true when the migration subprocess succeeds.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py::test_AC16_11_28_check_database_ready_success"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.29",
            statement="dev_backend.cleanup terminates the tracked process and exits cleanly.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py::test_AC16_11_29_dev_backend_cleanup_terminates_and_exits"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.30",
            statement="cleanup_orphaned_dbs.drop_database returns true in dry-run mode.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_30_drop_database_dry_run_returns_true"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.31",
            statement="cleanup_orphaned_dbs.main forwards parsed flags to cleanup_orphaned.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py::test_AC16_11_31_main_calls_cleanup_orphaned"
            ),
            priority="P1",
            status="done",
        ),
        # ── deploy-request: versioned App -> Infra boundary (#876) ──
        ACRecord(
            id="AC-runtime.deploy-request.1",
            statement=(
                "Finance Report pins an immutable infra2-sdk release and renders a canonical "
                "DeployRequest v1 for its exact release tag, commit SHA, and GitHub Actions "
                "evidence without importing or reading infra2 source."
            ),
            test=(
                "tests/tooling/test_app_deploy_request.py"
                "::test_AC_runtime_deploy_request_1_sdk_and_wire_contract_are_exactly_pinned"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.deploy-request.2",
            statement=(
                "The app-side renderer is side-effect-free and fail-closed: it can emit only "
                "a staging deploy request for finance_report/app from this repository; "
                "production, alternate services, repositories, refs, SHAs, or evidence are rejected."
            ),
            test=(
                "tests/tooling/test_app_deploy_request.py"
                "::test_AC_runtime_deploy_request_2_sender_authority_is_fail_closed"
            ),
            priority="P0",
            status="done",
        ),
        # ── group snapshot-anonymizer (#893, RL-DATA-2) — the data boundary of
        # deploy(env, code, data): a prod snapshot is rewritten on a scratch
        # copy (money scaled by one secret integer, identities pseudonymized,
        # free-form JSON redacted) and residual-scanned before it may reach
        # staging/rehearsal. Blob storage is never synced (RL-DATA-3). ──
        ACRecord(
            id="AC-runtime.snapshot-anonymizer.1",
            statement=(
                "Every column of the live model metadata is explicitly "
                "classified (keep / scale / pseudonym / redact); an "
                "unclassified column aborts the run before any data is read, "
                "so a migration cannot silently leak a new column into a "
                "snapshot (fail closed, RL-DATA-2)."
            ),
            test=(
                "apps/backend/tests/infra/test_snapshot_anonymizer.py"
                "::test_AC_runtime_snapshot_anonymizer_1_every_live_column_is_classified"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.snapshot-anonymizer.2",
            statement=(
                "All monetary values scale by one secret integer factor — "
                "exactly, with no rounding — so double-entry balance, "
                "statement open+movement=close arithmetic, and "
                "price-times-quantity derivations hold in the anonymized "
                "copy; quantities, FX rates, and ratios are untouched."
            ),
            test=(
                "apps/backend/tests/infra/test_snapshot_anonymizer.py"
                "::test_AC_runtime_snapshot_anonymizer_2_money_scales_and_books_still_balance"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.snapshot-anonymizer.3",
            statement=(
                "Identity/content-bearing strings are replaced with "
                "deterministic HMAC pseudonyms (same original, same "
                "pseudonym — cross-table join keys stay aligned), free-form "
                "JSON is redacted, and the residual scan proves no original "
                "sensitive value survives; a planted residual fails the "
                "scan, which rolls the snapshot back."
            ),
            test=(
                "apps/backend/tests/infra/test_snapshot_anonymizer.py"
                "::test_AC_runtime_snapshot_anonymizer_3_pseudonyms_consistent_and_no_residuals"
            ),
            priority="P0",
            status="done",
        ),
        # ── group real-corpus-eval (#1764 G-enforcement) — the release-evidence
        # check for #1764's real-document accuracy/calibration eval. Fails
        # closed (never a silent pass) when the eval has never run, failed, or
        # gone stale — but is NOT yet wired into release.yml as a blocking
        # step: that requires an operator-supplied real-document corpus to
        # exist first (RL-6 — real PDFs are never committed) and is a
        # deliberate release-behavior change needing explicit sign-off, not
        # something to flip on unilaterally. See #1764 ──
        ACRecord(
            id="AC-runtime.real-corpus-eval.1",
            statement=(
                "verify_real_corpus_eval returns the run id of the most "
                "recent completed, successful real-corpus-eval run when it "
                "is within max_age_hours."
            ),
            test=(
                "tests/tooling/test_real_corpus_eval_evidence.py"
                "::test_AC_runtime_real_corpus_eval_1_fresh_success_run_passes"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.real-corpus-eval.2",
            statement=(
                "verify_real_corpus_eval raises when no completed run exists "
                "— an eval that has never run proves nothing and must never "
                "read as a silent pass."
            ),
            test=(
                "tests/tooling/test_real_corpus_eval_evidence.py"
                "::test_AC_runtime_real_corpus_eval_2_no_completed_run_fails_closed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.real-corpus-eval.3",
            statement=(
                "verify_real_corpus_eval raises when the most recent "
                "completed run did not succeed — a real accuracy or "
                "calibration regression blocks release."
            ),
            test=(
                "tests/tooling/test_real_corpus_eval_evidence.py"
                "::test_AC_runtime_real_corpus_eval_3_failed_run_fails_closed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.real-corpus-eval.4",
            statement=(
                "verify_real_corpus_eval raises when the most recent "
                "successful run is older than max_age_hours — staleness is "
                "exactly as untrustworthy as never having run."
            ),
            test=(
                "tests/tooling/test_real_corpus_eval_evidence.py"
                "::test_AC_runtime_real_corpus_eval_4_stale_run_fails_closed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.real-corpus-eval.5",
            statement=(
                "verify_real_corpus_eval is governed by the most recent "
                "completed run when several exist, so a fixed-then-passing "
                "re-run supersedes an old failure."
            ),
            test=(
                "tests/tooling/test_real_corpus_eval_evidence.py"
                "::test_AC_runtime_real_corpus_eval_5_picks_the_most_recent_completed_run"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.real-corpus-eval.6",
            statement=(
                "verify_real_corpus_eval raises a clear RuntimeError when the "
                "latest completed run is missing or malformed createdAt, "
                "instead of crashing on an unhandled KeyError/TypeError or "
                "silently treating the run as fresh."
            ),
            test=(
                "tests/tooling/test_real_corpus_eval_evidence.py"
                "::test_AC_runtime_real_corpus_eval_6_missing_created_at_fails_closed"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.real-corpus-eval.7",
            statement=(
                "main --check real-corpus-eval reaches verify_real_corpus_eval "
                "end-to-end through argparse (choice registration and "
                "--max-age-hours wiring), not only through direct calls to the "
                "underlying function."
            ),
            test=(
                "tests/tooling/test_real_corpus_eval_evidence.py"
                "::test_AC_runtime_real_corpus_eval_7_cli_dispatch_reaches_the_check"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.real-corpus-eval.8",
            statement=(
                "A completed run with a malformed/missing createdAt among "
                "OTHER completed runs fails closed rather than being "
                "silently outranked -- it might be the true latest run with "
                "bad timestamp data, and picking an older, "
                "valid-timestamped run in its place would quietly violate "
                "'the most recent completed run governs' (2026-07-13 CR "
                "follow-up on the .5 fix)."
            ),
            test=(
                "tests/tooling/test_real_corpus_eval_evidence.py"
                "::test_AC_runtime_real_corpus_eval_8_malformed_timestamp_among_others_fails_closed"
            ),
            priority="P1",
            status="done",
        ),
        # ── group release-images (#1759 CR follow-up): retry a transient
        # registry-visibility miss instead of failing the gate outright ──
        ACRecord(
            id="AC-runtime.release-images.1",
            statement=(
                "verify_release_images finds a digest on the first inspect "
                "attempt with no retry/sleep — the retry path never runs on "
                "the (expected-common) success case."
            ),
            test=(
                "tests/tooling/test_verify_release_images.py"
                "::test_AC_runtime_release_images_1_first_attempt_success_no_retry"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.release-images.2",
            statement=(
                "verify_release_images retries a not-yet-visible digest (e.g. "
                "registry propagation lag right after container-images pushes "
                "a :<sha> tag) instead of treating the first miss as a hard "
                "failure, as long as it succeeds within max_attempts."
            ),
            test=(
                "tests/tooling/test_verify_release_images.py"
                "::test_AC_runtime_release_images_2_transient_miss_then_success_retries"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.release-images.3",
            statement=(
                "verify_release_images still fails closed when an image never "
                "becomes visible — retrying bounds flake tolerance, it does "
                "not remove the guarantee that a truly missing image fails "
                "the gate."
            ),
            test=(
                "tests/tooling/test_verify_release_images.py"
                "::test_AC_runtime_release_images_3_exhausted_retries_fails_closed"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.release-images.4",
            statement=(
                "verify_release_images' max_attempts/retry_delay_seconds are "
                "caller-configurable, not hardcoded, so a caller with a "
                "tighter time budget can tune the retry envelope -- and the "
                "configured delay value itself, not just attempt count, "
                "actually reaches sleep()."
            ),
            test=(
                "tests/tooling/test_verify_release_images.py"
                "::test_AC_runtime_release_images_4_max_attempts_and_delay_are_configurable"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.release-images.5",
            statement=(
                "verify_release_images rejects max_attempts < 1 with a clear "
                "ValueError instead of silently performing zero inspect "
                "attempts and raising a confusing 'not found after 0 "
                "attempts'."
            ),
            test=(
                "tests/tooling/test_verify_release_images.py"
                "::test_AC_runtime_release_images_5_max_attempts_below_1_is_rejected"
            ),
            priority="P2",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.release-images.6",
            statement=(
                "verify_release_images rejects a negative retry_delay_seconds "
                "with a clear ValueError instead of reaching sleep() and "
                "raising there."
            ),
            test=(
                "tests/tooling/test_verify_release_images.py"
                "::test_AC_runtime_release_images_6_negative_delay_is_rejected"
            ),
            priority="P2",
            status="done",
        ),
        # ── guard-layer proofs (#1828): the code between CI-green and users
        # being served — boot fail-closed, honest health, telemetry identity,
        # config injection — gets executed proof instead of production-first
        # execution. G-entrypoint-preprod-contact lands via #1809, not here. ──
        ACRecord(
            id="AC-runtime.guard-proofs.1",
            statement=(
                "G-reject-path-proven: every development default (dev SECRET_KEY, "
                "default DATABASE_URL, default S3 secret) is rejected by "
                "_check_static_config under every protected-runtime trigger "
                "(staging env, production env, unknown env fails closed, public "
                "https URL) — the full reject matrix, not sampled cells."
            ),
            test=(
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC_runtime_guard_proofs_1_every_default_is_rejected_under_every_protected_trigger"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.2",
            statement=(
                "G-reject-path-proven accept branch: all development defaults "
                "together remain bootable in every local environment "
                "(development/test/ci) with a localhost app URL — the gate "
                "rejects protected-runtime defaults, not local development."
            ),
            test=(
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC_runtime_guard_proofs_2_development_defaults_accepted_in_local_environments"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.3",
            statement=(
                "G-reject-path-proven: the protected-runtime classifier itself is "
                "proven cell-by-cell — protected envs, unknown envs (fail closed) "
                "and public https app URLs classify as protected; local envs and "
                "localhost URLs do not."
            ),
            test=(
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC_runtime_guard_proofs_3_protected_runtime_classification"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.4",
            statement=(
                "G-health-honest-somewhere: the blocking backend-integration lane "
                "runs the REAL _check_database (re-patched over the suite-wide "
                "autouse mock) against the lane's live Postgres and it reports ok "
                "— structure-locked: the returned message must not be the autouse "
                "stub's 'Mocked for tests', so a leaked mock reds the lane."
            ),
            test=(
                "apps/backend/tests/integration/test_bootloader_real_checks.py"
                "::test_AC_runtime_guard_proofs_4_real_database_check_passes_against_live_service"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.5",
            statement=(
                "G-health-honest-somewhere: the same lane runs the REAL _check_s3 "
                "(HEAD bucket) against the lane's live MinIO and it reports ok, "
                "with the same anti-mock structure lock."
            ),
            test=(
                "apps/backend/tests/integration/test_bootloader_real_checks.py"
                "::test_AC_runtime_guard_proofs_5_real_s3_check_passes_against_live_service"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.6",
            statement=(
                "G-health-honest-somewhere red-team canary: pointed at a dead "
                "port, the REAL _check_database reports error — the autouse stub "
                "would report ok here, so this test failing-closed proves the "
                "real code path is exercised (permanent mock-leak detector)."
            ),
            test=(
                "apps/backend/tests/integration/test_bootloader_real_checks.py"
                "::test_AC_runtime_guard_proofs_6_real_database_check_reds_on_dead_port"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.7",
            statement=(
                "G-telemetry-tag-consistent: when OTEL export is enabled in a "
                "protected env, a deployment.environment resource attribute whose "
                "value differs from settings.environment fails config load "
                "(ValueError at boot) — presence alone no longer passes, closing "
                "the 'prod telemetry tagged as staging' case."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC_runtime_guard_proofs_7_telemetry_tag_value_mismatch_fails_boot"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.8",
            statement=(
                "G-telemetry-tag-consistent accept branch: a matching "
                "deployment.environment value loads cleanly in protected envs "
                "(normalized comparison), and non-protected envs stay exempt "
                "from the value check."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC_runtime_guard_proofs_8_telemetry_tag_value_match_boots"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.9",
            statement=(
                "G-staleness-watchdog-visible (operator-decided 2026-07-14: "
                "detection only): a stale vault secrets file flips the "
                "informational vault_secrets.stale signal in /health?full=1 "
                "while the verdict and the checks parity set stay unchanged — "
                "boot semantics untouched; the #1653 watchdog axis consumes it."
            ),
            test=(
                "apps/backend/tests/runtime/test_health_parity.py"
                "::test_AC_runtime_guard_proofs_9_full_health_exposes_stale_vault_secrets_signal"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.10",
            statement=(
                "G-staleness-watchdog-visible: a missing secrets file is exposed "
                "as present=False (age/stale null) in /health?full=1, still "
                "without affecting the verdict — absence is a watchdog signal, "
                "not a health failure."
            ),
            test=(
                "apps/backend/tests/runtime/test_health_parity.py"
                "::test_AC_runtime_guard_proofs_10_full_health_reports_absent_vault_secrets_file"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.11",
            statement=(
                "G-injection-drift-gate: the committed required-env manifest "
                "(common/runtime/required-env.generated.json, emitted by "
                "tools/generate_env_reference.py from config.py) equals the "
                "manifest rendered from live Settings metadata — exact equality "
                "reds both drift directions (unregenerated new field, stale "
                "entry for a removed field)."
            ),
            test=(
                "tests/tooling/test_required_env_manifest.py"
                "::test_AC_runtime_guard_proofs_11_manifest_matches_live_config_bidirectionally"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.guard-proofs.12",
            statement=(
                "G-injection-drift-gate: every vault-tagged config field appears "
                "in the committed manifest (vault=true) AND as a key in "
                ".env.example, and every manifest entry maps back to a live "
                "config field — the app-side half of the #876 artifact boundary "
                "that infra2's secrets.ctmpl check consumes."
            ),
            test=(
                "tests/tooling/test_required_env_manifest.py"
                "::test_AC_runtime_guard_proofs_12_every_vault_field_reaches_manifest_and_env_example"
            ),
            priority="P1",
            status="done",
        ),
        # ── Wave B (#1821): frontend-proof rows migrated from the
        # remaining EPIC files (EPIC-001/002/004/008/011/012/015/017/018/019/021/024/025) ──
        ACRecord(
            id="AC-runtime.fe-deploy.1",
            statement="Frontend exposes `/frontend-version.json` with deployed `git_sha`/`version` metadata for PR preview readiness checks",
            # was AC8.13.90
            test="apps/frontend/src/__tests__/frontendVersionRoute.test.ts::AC8.13.90 returns deployed frontend version metadata for PR preview readiness",
            priority="P0",
            status="done",
        ),
        # ── group sla-manifest: prod-required = SLA-bearing, machine-readably
        # exposed for infra2's periodic report (2026-07-07 decision, #1654,
        # finance_report#1851 G2) ──
        ACRecord(
            id="AC-runtime.sla-manifest.1",
            statement=(
                "`tools/generate_sla_manifest.py` derives "
                "`common/runtime/sla-manifest.generated.json` from "
                "`DEPENDENCY_MANIFEST.required_for(tier)` for every tier; the "
                "committed artifact is byte-identical to the live manifest "
                "rendering — no second hand-maintained service list for infra2 "
                "to drift against."
            ),
            test=(
                "tests/tooling/test_sla_manifest.py"
                "::test_AC_runtime_sla_manifest_1_committed_manifest_matches_live_dependency_manifest"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.sla-manifest.2",
            statement=(
                "Every dependency `required_in(production)` has exactly one "
                "production SLA entry (name, testing kind, human-readable "
                "summary) in the generated manifest — prod-required means "
                "SLA-bearing regardless of whether the app feature consuming "
                "it has shipped (resolves the manifest ↔ EPIC-019 AC19.13 "
                "contradiction: platform availability != feature adoption)."
            ),
            test=(
                "tests/tooling/test_sla_manifest.py"
                "::test_AC_runtime_sla_manifest_2_production_entries_are_sla_bearing_and_complete"
            ),
            priority="P1",
            status="done",
        ),
        # ── Shared GitHub Actions transport (#1867 S4 PR-A) ──
        ACRecord(
            id="AC-runtime.github-api.1",
            statement=(
                "Runtime release checks and testing CI waits use one GitHub Actions "
                "client, UTC timestamp parser, and GITHUB_OUTPUT writer, preserving "
                "the API request and output-file behavior at every existing entry point."
            ),
            test=(
                "tests/tooling/test_s4_shared_gate_infrastructure.py"
                "::test_AC_runtime_github_api_1_runtime_and_testing_share_github_helpers"
            ),
            priority="P1",
            status="done",
        ),
    ],
    concepts=[
        ConceptRecord(
            key="container_naming",
            owner="common/runtime/environments.md#container-naming-patterns",
            description="Container name patterns per environment (hyphens vs underscores).",
            cross_refs=["common/runtime/deployment.md", "AGENTS.md"],
            proofs=["tests/tooling/test_issue_489_deployment_contracts.py"],
            family="platform",
            kind="concept",
        ),
        ConceptRecord(
            key="deployment_architecture",
            owner="common/runtime/deployment.md",
            description="Dual-repo model, Vault secret injection, staging/production flow.",
            cross_refs=["common/meta/development.md", "common/runtime/environments.md"],
            proofs=[
                "tests/tooling/test_issue_489_deployment_contracts.py",
                "tests/tooling/test_post_merge_e2e_gates.py",
            ],
        ),
        ConceptRecord(
            key="env_reference_generated",
            owner="common/runtime/env-reference.generated.md",
            description=(
                "Generated backend env reference (rendered from config.py Settings metadata; "
                "do not edit by hand)."
            ),
            cross_refs=[
                "apps/backend/src/config.py",
                "tools/generate_env_reference.py",
                ".env.example",
            ],
            proofs=["tests/tooling/test_env_reference.py"],
            family="development",
            kind="registry",
        ),
        ConceptRecord(
            key="env_smoke_test",
            owner="common/runtime/readme.md#environment-verification-the-three-gates",
            description=(
                "Environment smoke testing via real boot operations — runtime's deployed-env "
                "dependency-presence verification (the Three Gates). Owned by the runtime "
                "package (common/runtime/readme.md)."
            ),
            cross_refs=["common/meta/development.md"],
            proofs=[
                "tests/tooling/test_runtime_incident_response_ssot.py",
                "tests/tooling/test_runtime_ssot_internalized.py",
            ],
        ),
        ConceptRecord(
            key="required_env_manifest_generated",
            owner="common/runtime/required-env.generated.json",
            description=(
                "Generated machine-readable required-env manifest (same config.py source of "
                "truth as .env.example; infra2 CI consumes it against secrets.ctmpl — #1828 "
                "G-injection-drift-gate over the #876 artifact boundary; do not edit by "
                "hand)."
            ),
            cross_refs=[
                "apps/backend/src/config.py",
                "tools/generate_env_reference.py",
                ".env.example",
                "repo/finance_report/finance_report/10.app/secrets.ctmpl",
            ],
            proofs=["tests/tooling/test_required_env_manifest.py"],
            family="development",
            kind="registry",
        ),
        ConceptRecord(
            key="runtime_incident_response",
            owner="common/runtime/runtime-incident-response.md",
            description="App-side runtime incident triage and stability-proof routing.",
            cross_refs=[
                "common/runtime/deployment.md",
                "common/observability/observability.md",
                "common/testing/ci-cd.md",
                "common/runtime/ci-cd.md",
                "common/runtime/readme.md",
                "docs/project/DELIVERY_ENGINE_RECOMMENDATIONS.md",
                "repo/docs/ssot/ops.alerting.md",
                "repo/docs/ssot/ops.availability-ledger.md",
                "repo/docs/ssot/ops.recovery.md",
            ],
            proofs=["tests/tooling/test_runtime_incident_response_ssot.py"],
            family="runtime",
            kind="playbook",
        ),
        ConceptRecord(
            key="six_environments",
            owner="common/runtime/environments.md#environment-overview",
            description="Local Dev / Local CI / GitHub CI / PR Preview / Staging / Production.",
            cross_refs=[
                "common/meta/development.md",
                "common/testing/ci-cd.md",
                "common/runtime/deployment.md",
            ],
            proofs=["tests/tooling/test_issue_489_deployment_contracts.py"],
            family="environments",
        ),
    ],
)

# Test roots this package owns (aggregated into the execution matrix's
# generated ownership view; see common/testing/matrix.py, issue #1558).
TEST_ROOTS: tuple[str, ...] = ("apps/backend/tests/infra/test_main.py",)
