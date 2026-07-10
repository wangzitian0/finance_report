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

from common.meta.package_contract import ACRecord, Invariant, PackageContract

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
        "DEPENDENCY_MANIFEST",
        "NON_DEPENDENCY_ENV_FIELDS",
        "VPS_TIERS",
        "AnalyticsCheck",
        "DatabaseCheck",
        "Dependency",
        "DependencyCheck",
        "DependencyKind",
        "DependencyManifest",
        "DependencyStatus",
        "EnvTier",
        "LlmCheck",
        "MarketDataCheck",
        "ObjectStorageCheck",
        "ProbeResult",
        "RedisCheck",
        "StorageError",
        "StorageService",
        "TelemetryCheck",
        "WorkflowEngineCheck",
        "check_env_classification",
        "redact_presigned_url",
        "resolve_env_tier",
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
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_primary_model_format"
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
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_config_sync_with_env_example"
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
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_base_currency_format"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.18.4",
            statement=(
                "S3_BUCKET follows S3 naming conventions (lowercase, 3-63 chars, "
                "hyphen-safe). Was EPIC-012 AC12.18.4."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_s3_bucket_format"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.18.5",
            statement=(
                "JWT_ALGORITHM is one of the allowed secure algorithms "
                "(HS256/RS256). Was EPIC-012 AC12.18.5."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_jwt_algorithm_allowed"
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
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_database_url_format"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.1",
            statement=(
                "DB_POOL_SIZE config field exists with the expected default. "
                "Was EPIC-012 AC12.20.1."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_db_pool_size_config_default"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.2",
            statement=(
                "DB_POOL_MAX_OVERFLOW config field exists with the expected "
                "default. Was EPIC-012 AC12.20.2."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_db_pool_max_overflow_config_default"
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
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_db_pool_config_valid_range"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.4",
            statement=(
                "The DB_POOL_SIZE env var overrides the pool-size setting. "
                "Was EPIC-012 AC12.20.4."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_db_pool_size_env_override"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.20.5",
            statement=(
                "The DB_POOL_MAX_OVERFLOW env var overrides the max-overflow "
                "setting. Was EPIC-012 AC12.20.5."
            ),
            test=(
                "apps/backend/tests/infra/test_config_contract.py"
                "::test_db_pool_size_env_override"
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
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC1_10_1_static_config_rejects_short_secret_key_in_staging"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.21.3",
            statement=(
                "Bootloader._check_static_config rejects the local-"
                "development DB default in a protected environment."
            ),
            test=(
                "apps/backend/tests/infra/test_boot.py"
                "::test_AC1_10_1_static_config_rejects_default_db_in_protected_env"
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
                "The scheduled GHCR retention workflow prunes only backend/"
                "frontend :<sha> package versions older than 28 days, never "
                "prunes vX.Y.Z release tags, preserves live staging/"
                "production deploy SHAs resolved from health git_sha/"
                "version, and fails closed when no live SHA exemption is "
                "available."
            ),
            test=(
                "tests/tooling/test_ghcr_sha_retention.py"
                "::test_AC7_19_1_retention_selects_only_stale_sha_tags"
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
                "tests/tooling/test_debug.py"
                "::test_AC16_11_2_detect_environment_local_when_docker_ok"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.3",
            statement="debug.detect_environment falls back to PRODUCTION on docker failure.",
            test=(
                "tests/tooling/test_debug.py"
                "::test_AC16_11_3_detect_environment_fallback_production"
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
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_8_extract_namespace_variants"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.9",
            statement="cleanup_orphaned_dbs.load_active_namespaces returns [] when the file is missing or corrupt.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_9_load_active_namespaces_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.10",
            statement="cleanup_orphaned_dbs.get_container_runtime returns the first available runtime.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_10_get_container_runtime_prefers_podman"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.11",
            statement="cleanup_orphaned_dbs.list_test_databases parses psql output and handles subprocess errors.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_11_list_test_databases_parses_rows"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.12",
            statement="cleanup_orphaned_dbs.cleanup_orphaned returns an error when the container runtime is missing.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_12_cleanup_orphaned_runtime_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.13",
            statement="cleanup_orphaned_dbs.cleanup_orphaned returns success when no test databases are found.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_13_cleanup_orphaned_no_databases"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.14",
            statement="cleanup_orphaned_dbs.cleanup_orphaned skips active-namespace databases.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_14_cleanup_orphaned_skips_active"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.15",
            statement="cleanup_orphaned_dbs.cleanup_orphaned cleans all databases in --all mode.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_15_cleanup_orphaned_clean_all"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.16",
            statement="cli.get_compose_cmd honors CONTAINER_RUNTIME, otherwise prefers podman then docker, and exits when neither is available.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC16_11_16_get_compose_cmd_prefers_podman"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.17",
            statement="cli.cmd_test routes frontend/e2e/perf/tests and lifecycle modes correctly.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC16_11_17_cmd_test_frontend_route"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.18",
            statement="cli.cmd_clean routes db/containers/default cleanup targets correctly.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC16_11_18_cmd_clean_routes"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.19",
            statement="dev_backend.check_database_ready returns false on migration subprocess errors.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC16_11_19_check_database_ready_failure"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.20",
            statement="dev_frontend.cleanup terminates the tracked process and exits cleanly.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC16_11_20_dev_frontend_cleanup_terminates_and_exits"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.21",
            statement="debug.view_remote_logs_docker exits when VPS_HOST is missing.",
            test=(
                "tests/tooling/test_debug.py"
                "::test_AC16_11_21_view_remote_logs_docker_exits_when_vps_host_missing"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.22",
            statement="debug.view_remote_logs_docker exits on invalid VPS hostnames.",
            test=(
                "tests/tooling/test_debug.py"
                "::test_AC16_11_22_view_remote_logs_docker_exits_on_invalid_host"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.23",
            statement="debug.view_remote_logs_docker exits on invalid VPS usernames.",
            test=(
                "tests/tooling/test_debug.py"
                "::test_AC16_11_23_view_remote_logs_docker_exits_on_invalid_user"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.24",
            statement="debug.view_local_logs builds the docker logs command with tail and follow.",
            test=(
                "tests/tooling/test_debug.py"
                "::test_AC16_11_24_view_local_logs_builds_docker_command"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.25",
            statement="debug.main routes the logs command to the observability handler when method=observability.",
            test=(
                "tests/tooling/test_debug.py"
                "::test_AC16_11_25_main_logs_observability_path"
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
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC16_11_28_check_database_ready_success"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.29",
            statement="dev_backend.cleanup terminates the tracked process and exits cleanly.",
            test=(
                "tests/tooling/test_cli_and_dev_servers.py"
                "::test_AC16_11_29_dev_backend_cleanup_terminates_and_exits"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.30",
            statement="cleanup_orphaned_dbs.drop_database returns true in dry-run mode.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_30_drop_database_dry_run_returns_true"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-runtime.24.31",
            statement="cleanup_orphaned_dbs.main forwards parsed flags to cleanup_orphaned.",
            test=(
                "tests/tooling/test_cleanup_orphaned_dbs.py"
                "::test_AC16_11_31_main_calls_cleanup_orphaned"
            ),
            priority="P1",
            status="done",
        ),
    ],
)

# Test roots this package owns (aggregated into the execution matrix's
# generated ownership view; see common/testing/matrix.py, issue #1558).
TEST_ROOTS: tuple[str, ...] = ("apps/backend/tests/infra/test_main.py",)
