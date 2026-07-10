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
    ],
)

# Test roots this package owns (aggregated into the execution matrix's
# generated ownership view; see common/testing/matrix.py, issue #1558).
TEST_ROOTS: tuple[str, ...] = ("apps/backend/tests/infra/test_main.py",)
