"""The ``config`` package's machine-checkable :class:`PackageContract`.

``config`` is internal tooling — env-key + schema-validation helpers
(``env_keys``, ``schema_validation``) — not a domain bounded context, so it
publishes no curated symbol language (``interface=[]``); callers import its
modules directly. The contract governs it as a ``kernel`` leaf (``depends_on=[]``)
with an invariant pinned to its test. (The DAG import-scan only inspects
``src.<pkg>`` imports, so for a ``common/``-implemented package leaf-purity is a
declared, not a scanned, property.)
A curated published-language surface is a future cleanup.
"""

from __future__ import annotations

from common.meta.package_contract import ACRecord, Invariant, PackageContract

CONTRACT = PackageContract(
    name="config",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    roles=["env_keys", "schema_validation"],
    implementations={"be": "common/config", "fe": None},
    interface=[],
    events=[],
    invariants=[
        Invariant(
            id="env-key-extraction-robust",
            statement="Parsing env keys from a missing source file yields an empty set, not an error, so the consistency check degrades gracefully.",
            test="tests/tooling/test_check_env_keys.py::test_returns_empty_set_for_missing_file",
        ),
    ],
    roadmap=[
        # AC roadmap — EPIC-012 (foundation-libs) config-contract ACs homed here.
        # Migrated from the EPIC-012 table: the leading "12" is dropped and the
        # group/seq preserved, so AC12.<g>.<s> becomes AC-config.<g>.<s> (numeric
        # AC-<pkg>.<n>.<n> grammar; the live AC_PATTERN rejects word entities).
        # Only the config assertions proven by test_config_contract.py are homed:
        # the BASE_CURRENCY/model/db-url/jwt/s3 config-format checks (was AC12.18.*)
        # and the DB connection-pool config fields (was AC12.20.*). The AC12.18.7
        # "stub" row (a reconciliation [AC12.18.7.2] tag, not a config assertion)
        # stays defined in EPIC-012. Each test= resolves to a real path::func that
        # proves the statement; the package tier (CODE-ONLY) gives proof_kind=exact.
        # ── group 18: Config — environment-variable format contract (was AC12.18.*) ──
        ACRecord(
            id="AC-config.18.1",
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
            id="AC-config.18.2",
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
            id="AC-config.18.3",
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
            id="AC-config.18.4",
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
            id="AC-config.18.5",
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
            id="AC-config.18.6",
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
        # ── group 20: Config — DB connection-pool config fields (was AC12.20.*) ──
        ACRecord(
            id="AC-config.20.1",
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
            id="AC-config.20.2",
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
            id="AC-config.20.3",
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
            id="AC-config.20.4",
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
            id="AC-config.20.5",
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
    ],
)
