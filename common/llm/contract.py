"""The ``llm`` package's machine-checkable :class:`PackageContract`.

This is the authoritative spec the governance gate
(``tools/check_package_contract.py``) validates the BE implementation against:
``interface`` must equal the implementation's ``__all__``
(``implementations["be"]`` = ``apps/backend/src/llm``); every
``invariants[].test`` must resolve to a real test function; ``depends_on``
must not introduce a forbidden upward/sideways edge.

## What this package is

The outbound provider abstraction (EPIC-023 → #1426): three orthogonal axes —
protocol family × model × scene — plus the configurable ``scene -> model``
binding, encrypted provider secrets, and the **input-keyed cassette
record/replay mechanism** (cache the model's output by canonicalized input) so
every LLM call is deterministically replayable in CI.

## The two settled boundaries (2026-07-02)

* **runtime classifies, llm implements.** ``runtime`` declares the LLM a
  *model-dominant* external dependency and asserts it is PRESENT (one manifest
  entry + ``LlmCheck``); everything about HOW the app talks to models — scenes,
  bindings, secrets, routing, usage, cassette determinism, and any future
  self-built **evaluation mechanism** — is this package's internal behavior.
  Neither the cassette mechanism nor eval may drift into ``runtime`` or
  ``testing`` (testing owns only fixture DATA + baselines; see
  ``common/testing/contract.py``).
* **Usage statistics are llm-internal.** The ``base`` usage meter emits the
  structured ``llm_usage`` log per call today; the future durable per-user ×
  per-model rollup is a package-internal addition behind the reserved units
  below (``UsageRepository`` port + ``UsageRecorded`` event + the ``data/``
  rollup projection) — never a re-cutover, and never homed in
  ``observability`` (which keeps only the technical OTEL signals).

## No litellm at the package root

The root ``__init__`` exposes the litellm-dependent surface lazily (PEP 562):
``import src.llm`` never imports ``litellm``, so minimal tooling environments
load the package; the dependency is paid on first use of the four lazy names.
"""

from __future__ import annotations

from common.meta.package_contract import Invariant, Kind, PackageContract, Unit

CONTRACT = PackageContract(
    name="llm",
    klass="platform",
    # Draft until the EPIC-023 ACs land in ``roadmap`` (the same PR decides the
    # authority tier from the migrated ACs' proof mix).
    status="draft",
    tier=None,
    # observability: get_logger/structured logs from base+extension; config:
    # bare-root settings binding (env_config/catalog/secrets). The platform
    # event bus becomes an edge only when UsageRecorded is actually published.
    depends_on=["observability", "config"],
    roles=["base", "extension", "data"],
    units=[
        # ── base: the frozen value language (mechanism A) ──
        Unit(name="Scene", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(name="ProtocolFamily", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(name="ModelSpec", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(name="SceneBinding", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(name="Encrypted", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(name="Usage", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        Unit(name="ChatResult", kind=Kind.VALUE_OBJECT, module="base/types.py"),
        # the in-memory daily usage counter (per-process running total; the
        # structured ``llm_usage`` log is the durable record it emits).
        Unit(name="LlmUsageMeter", kind=Kind.ENTITY, module="base/usage.py"),
        # ── the split blocks (mechanism B): port in base/, adapter in extension/ ──
        Unit(
            name="ConfigSource",
            kind=Kind.REPOSITORY,
            module="base/config_source.py",
            impl="extension/db_config.py",
        ),
        Unit(
            name="LLMClient",
            kind=Kind.REPOSITORY,
            module="base/protocols.py",
            impl="extension/client.py",
        ),
        Unit(
            name="CatalogProvider",
            kind=Kind.REPOSITORY,
            module="base/protocols.py",
            impl="extension/catalog.py",
        ),
        # ── extension: domain services + factory ──
        # the single litellm chokepoint's provider routing
        Unit(
            name="build_call", kind=Kind.DOMAIN_SERVICE, module="extension/routing.py"
        ),
        # the input-keyed record/replay mechanism (cache output by input)
        Unit(
            name="CassetteStore",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/cassette.py",
        ),
        # DB-primary + env-fallback composition; impure (holds live adapters),
        # so a domain-service (extension), not a pure base factory.
        Unit(
            name="LayeredConfigSource",
            kind=Kind.DOMAIN_SERVICE,
            module="extension/factory.py",
        ),
        # ── ORM entities: declared taxonomy-only. Their mapped classes stay in
        # the unregistered ``src/models/llm_config.py`` (ledger precedent) —
        # the tables carry a cross-domain FK to identity's ``users.id``, and
        # FK→id-reference surgery is Stage-4 scope (#1416 Decision B), not this
        # cutover's. Re-home into ``extension/sql.py`` when that FK is cut. ──
        Unit(name="LlmProvider", kind=Kind.ENTITY),
        Unit(name="LlmSceneBinding", kind=Kind.ENTITY),
        # ── reserved growth slots for per-model usage statistics (taxonomy-only;
        # the gate skips placement for units with no module, money-VO precedent).
        # Filling these is package-internal work, not a re-cutover. ──
        Unit(name="UsageRepository", kind=Kind.REPOSITORY),
        Unit(name="UsageRecorded", kind=Kind.DOMAIN_EVENT),
        Unit(name="UsageRollup", kind=Kind.PROJECTION),
    ],
    implementations={"be": "apps/backend/src/llm", "fe": None},
    interface=[
        "CASSETTE_DIR",
        "Cassette",
        "CassetteMiss",
        "CassetteMode",
        "CassetteRecorder",
        "CassetteStore",
        "CassetteTag",
        "CassetteValidationError",
        "CatalogProvider",
        "ChatResult",
        "ConfigSource",
        "DbConfigSource",
        "Encrypted",
        "EnvConfigSource",
        "FernetCipher",
        "LLMBudgetExceeded",
        "LLMClient",
        "LLMConfigError",
        "LLMError",
        "LayeredConfigSource",
        "LitellmCall",
        "LitellmCatalog",
        "LlmUsageMeter",
        "Message",
        "Modality",
        "ModelCatalogError",
        "ModelSpec",
        "ProtocolFamily",
        "ProviderRef",
        "ReasoningEffort",
        "Scene",
        "SceneBinding",
        "SecretCipher",
        "Usage",
        "build_call",
        "build_cipher",
        "cassette_completion",
        "current_mode",
        "estimate_tokens",
        "estimate_tokens_from_chars",
        "fingerprint",
        "get_config_source",
        "get_usage_meter",
        "litellm_stream",
        "miss_summary",
        "protocol_for",
        "resolve_provider_and_model",
    ],
    # UsageRecorded is reserved above but not published yet; events lists only
    # what the package actually emits.
    events=[],
    invariants=[
        Invariant(
            id="interface-equals-published-language",
            statement=(
                "The published language (contract.interface) equals __init__.__all__."
            ),
            test=(
                "tests/tooling/test_llm_package.py"
                "::test_AC_llm_1_1_only_all_is_the_published_language"
            ),
        ),
        Invariant(
            id="converges-by-layer",
            statement=(
                "The package converges into base/ (frozen contract + usage entity) "
                "+ extension/ (adapters) + data/ (reserved projections)."
            ),
            test=(
                "tests/tooling/test_llm_package.py::test_AC_llm_1_2_converges_by_layer"
            ),
        ),
        Invariant(
            id="base-layer-pure",
            statement=(
                "base/ never imports the package's own extension/, the ORM, or litellm."
            ),
            test=(
                "tests/tooling/test_llm_package.py::test_AC_llm_1_3_base_layer_is_pure"
            ),
        ),
        Invariant(
            id="no-litellm-at-root",
            statement=(
                "Importing the package root (and its eager submodules) never "
                "imports litellm — the litellm surface is lazy (PEP 562), so "
                "minimal tooling environments can load the package."
            ),
            test=(
                "tests/tooling/test_llm_package.py"
                "::test_AC_llm_1_4_root_import_is_litellm_free"
            ),
        ),
        Invariant(
            id="runtime-classifies-llm-implements",
            statement=(
                "The cassette record/replay mechanism (and any future eval "
                "mechanism) lives in this package only; runtime holds no "
                "cassette/replay implementation — it just declares the LLM "
                "dependency and probes presence."
            ),
            test=(
                "tests/tooling/test_llm_package.py"
                "::test_AC_llm_1_5_cassette_mechanism_only_in_llm"
            ),
        ),
        Invariant(
            id="passes-own-governance-gate",
            statement="check_package_contract validates llm with no violations.",
            test=(
                "tests/tooling/test_llm_package.py"
                "::test_AC_llm_1_6_package_contract_gate_passes_for_llm"
            ),
        ),
    ],
    # Filled by the EPIC-023 AC migration (same PR, later commit); the package
    # goes status="active" with its authority tier decided there.
    roadmap=[],
)
