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

from common.meta.package_contract import (
    ACRecord,
    Invariant,
    Kind,
    PackageContract,
    Unit,
)

CONTRACT = PackageContract(
    name="llm",
    status="active",
    # LLM-LED: the only tier whose proof set covers the graded-eval ACs
    # (AC-llm.8.*, proof=eval) alongside the deterministic property proofs; the
    # authority classifier also bands cassette-harness tests as LLM by design
    # (see common/testing/contract.py). Non-eval ACs carry proof_kind=property.
    tier="LLM-LED",
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
    # The EPIC-023 ACs, migrated per Decision A (standard-preserving move; the
    # EPIC table rows were deleted in the same commit). Ids follow the numeric
    # AC-<pkg>.<group>.<seq> grammar with the leading epic number dropped
    # (AC23.4.5 -> AC-llm.4.5), the ledger precedent. Original ids are kept as
    # trailing comments; the anchored test functions keep their AC23_* names
    # (the resolvable anchor is the roadmap's test= reference).
    roadmap=[
        ACRecord(
            id="AC-llm.1.1",
            statement="The three axes are typed: `ProtocolFamily` enumerates exactly the three universal protocol families, `Scene` the fixed call sites, and `ModelSpec`/`SceneBinding` carry modality/free/reasoning so model selection is data, not code",  # was AC23.1.1
            test="apps/backend/tests/llm/test_types.py::test_AC23_1_1_protocol_family_enumerates_the_supported_families",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.1.2",
            statement="`FernetCipher` round-trips a provider secret (`encrypt` → `decrypt`) and never persists plaintext",  # was AC23.1.2
            test="apps/backend/tests/llm/test_secrets.py::test_AC23_1_2_round_trips_a_provider_secret_without_storing_plaintext",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.1.3",
            statement="Key rotation is single-pass: a secret sealed by an older key still decrypts after a newer key is prepended, and `rotate()` re-stamps it to the newest `key_version`",  # was AC23.1.3
            test="apps/backend/tests/llm/test_secrets.py::test_AC23_1_3_rotation_is_single_pass_old_ciphertext_still_decrypts",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.1.4",
            statement="`build_cipher()` raises `LLMConfigError` when `LLM_ENCRYPTION_KEYS` is unset, and `FernetCipher` rejects malformed keys — DB-backed secrets fail closed",  # was AC23.1.4
            test="apps/backend/tests/llm/test_secrets.py::test_AC23_1_4_build_cipher_fails_closed_without_a_key",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.1.5",
            statement="The seam protocols (`ConfigSource`, `LLMClient`, `CatalogProvider`, `SecretCipher`) are runtime-checkable and a conforming implementation satisfies `isinstance`, so EPIC A/B can swap implementations behind the contract",  # was AC23.1.5
            test="apps/backend/tests/llm/test_contract.py::test_AC23_1_5_conforming_implementations_satisfy_the_protocols",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.2.1",
            statement="Provider routing maps each protocol family onto the correct litellm call — `openai`/`anthropic`/`openrouter` prefix, custom `api_base` for OpenAI-compatible endpoints, OpenRouter attribution headers — and normalises an already-qualified model id",  # was AC23.2.1
            test="apps/backend/tests/llm/test_routing.py::test_AC23_2_1_openai_compatible_prefixes_and_keeps_api_base",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.2.2",
            statement="The litellm transport streams via litellm with `drop_params` (model-rejected params like `seed` are dropped, not 400'd) and resolves a binding's provider/model through the `ConfigSource` (`resolve_provider_and_model`, honouring the `provider_id/model` qualifier)",  # was AC23.2.2
            test="apps/backend/tests/llm/test_client.py::test_AC23_2_2_stream_yields_only_nonempty_deltas",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.2.3",
            statement="Provider failures are normalised to `LLMError` with a retryable verdict (rate-limit/5xx/timeout → retryable; others not)",  # was AC23.2.3
            test="apps/backend/tests/llm/test_client.py::test_AC23_2_3_provider_error_is_normalised_to_llmerror",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.2.4",
            statement="`EnvConfigSource` projects the existing env settings onto scene bindings (vision/ocr → vision/ocr models, the rest → primary) and reports `is_configured() == False` when no API key, driving the first-run modal",  # was AC23.2.4
            test="apps/backend/tests/llm/test_env_config.py::test_AC23_2_4_unconfigured_when_no_api_key",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.2.5",
            statement="The dynamic catalogue lists configured models enriched with litellm pricing, flags the free tier, and filters by provider/modality/free",  # was AC23.2.5
            test="apps/backend/tests/llm/test_catalog.py::test_AC23_2_5_lists_configured_models_with_pricing",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.2.6",
            statement="The usage meter counts requests and (estimated) tokens per UTC day and rolls over at the day boundary — observability only, no money/cost and no ceiling (per-token pricing is too unreliable across providers to enforce a USD limit; the unenforced `AI_DAILY_LIMIT_USD` is dropped)",  # was AC23.2.6
            test="apps/backend/tests/llm/test_usage.py::test_AC23_2_6_counts_requests_and_tokens",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.3.1",
            statement="`DbConfigSource` reads provider instances (decrypting the at-rest API key) and scene bindings (qualified by provider id) from `llm_providers` / `llm_scene_bindings`",  # was AC23.3.1
            test="apps/backend/tests/llm/test_llm_db_config.py::test_AC23_3_1_db_config_reads_providers_and_bindings",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.3.2",
            statement="Config resolves DB-first with an env fallback; `is_configured()` is true when either has a provider and false when both are empty (driving the first-run modal)",  # was AC23.3.2
            test="apps/backend/tests/llm/test_llm_db_config.py::test_AC23_3_2_layered_uses_db_first_then_env",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.1",
            statement="`GET /llm/config/status` reports `{configured}` for the current user from the layered (user → deployment → env) config source, driving the first-run modal",  # was AC23.4.1
            test="apps/backend/tests/llm/test_llm_api.py::test_AC23_4_1_config_status_flips_when_user_configures",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.2",
            statement="`GET/POST/DELETE /llm/providers` is scoped to the current user; POST encrypts the API key via `build_cipher` before persist and the response **never** returns or logs the plaintext key; with `LLM_ENCRYPTION_KEYS` unset, POST fails closed",  # was AC23.4.2
            test="apps/backend/tests/llm/test_llm_api.py::test_AC23_4_2_provider_create_encrypts_and_never_returns_key",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.3",
            statement="`GET /llm/catalog` lists models via `LitellmCatalog` enriched with pricing/free-tier and filtered by `modality`/`free_only`",  # was AC23.4.3
            test="apps/backend/tests/llm/test_llm_api.py::test_AC23_4_3_catalog_lists_models_with_filters",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.4",
            statement="`GET/PUT /llm/scenes` round-trips the current user's scene→model bindings (model + reasoning + fallbacks), validated against their providers",  # was AC23.4.4
            test="apps/backend/tests/llm/test_llm_api.py::test_AC23_4_4_scenes_round_trip",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.5",
            statement="Per-user config resolves through the scene-keyed seam and is **live for the AI advisor**: `ai_streaming` resolves the provider via `get_config_source(user_id)` (the user's provider, else deployment default, else env) and `advisor.chat` prefers the user's bound model when no per-message model is given; a BYO-provider user is not blocked by a missing deployment `AI_API_KEY`. (Threading `user_id` into the remaining `extraction` OCR/vision/json call sites is the documented follow-up, verified via the post-merge AI/OCR gate.)",  # was AC23.4.5
            test="apps/backend/tests/llm/test_llm_api.py::test_AC23_4_5_user_binding_drives_resolution",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.6",
            statement="The legacy `services/ai_models.py` + `routers/ai_models.py` are removed; remaining model lookups (`statements`, `chat`) resolve through `LitellmCatalog`, and the dead `AI_MODEL_CATALOG_SOURCE` config is dropped",  # was AC23.4.6
            test="apps/backend/tests/llm/test_llm_api.py::test_AC23_4_6_legacy_ai_models_endpoint_removed",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.7",
            statement="The usage meter is a process-wide singleton (`get_usage_meter`), so the live transport accumulates onto one counter and request/token tallies survive across requests (a fresh meter per call would reset the totals); a completed live stream records one request plus estimated prompt/completion tokens, and `stream_options` is never sent (Z.AI rejects unknown params)",  # was AC23.4.7
            test="apps/backend/tests/ai/test_ai_streaming.py::test_AC23_4_7_records_request_and_token_usage",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.8",
            statement="`DbConfigSource.get_provider` is scoped to the caller's scope (own rows, else deployment default); it never resolves or decrypts another tenant's provider by id",  # was AC23.4.8
            test="apps/backend/tests/llm/test_llm_db_config.py::test_AC23_4_8_get_provider_is_user_scoped_no_cross_tenant_key_disclosure",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.9",
            statement="`api_base` rejects loopback/private/link-local/reserved IPs and local-only names (`localhost`, `*.internal`, metadata) at the schema boundary, closing the obvious SSRF foot-guns",  # was AC23.4.9
            test="apps/backend/tests/llm/test_llm_api.py::test_AC23_4_9_provider_rejects_ssrf_api_base",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.4.10",
            statement="Provider creation is capped per user (`MAX_PROVIDERS_PER_USER`); exceeding it returns 409 instead of growing the table unbounded",  # was AC23.4.10
            test="apps/backend/tests/llm/test_llm_api.py::test_AC23_4_10_provider_count_capped",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.5.1",
            statement="`LLM_CASSETTE_MODE` selects `replay` / `record` / `off`; it defaults to `off` (live, local dev) and an unknown value fails closed with `LLMConfigError` rather than silently calling the network",  # was AC23.5.1
            test="apps/backend/tests/llm/test_cassette.py::test_AC23_5_1_mode_defaults_to_off",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.5.2",
            statement="`replay` returns the recorded response with **zero network calls and no API key** (the live call is never invoked); committed synthetic cassettes are keyed by their own fingerprint so the default store resolves them",  # was AC23.5.2
            test="apps/backend/tests/llm/test_cassette.py::test_AC23_5_2_replay_returns_recorded_response_without_network",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.5.3",
            statement="A request with no matching cassette is a **hard failure** in `replay` (`CassetteMiss`) that never falls back to the network, and misses batch into one actionable summary (`N cassette(s) need re-record: …; run make llm-record`)",  # was AC23.5.3
            test="apps/backend/tests/llm/test_cassette.py::test_AC23_5_3_replay_miss_is_a_hard_failure_no_network",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.5.4",
            statement="`record` performs the (here mocked) provider call and persists the cassette; re-recording an unchanged request is idempotent (identical bytes, no diff churn); `off` is a plain live call that writes nothing",  # was AC23.5.4
            test="apps/backend/tests/llm/test_client.py::test_AC23_5_4_cassette_completion_off_mode_does_a_live_litellm_call",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.5.5",
            statement="Fingerprint integrity: a change to an output-affecting field → different key (no stale match); two semantically-different requests → different keys (no false match); the same semantic request under a different model id → the **same** key (model-id-agnostic); image content is keyed by a bytes hash",  # was AC23.5.5
            test="apps/backend/tests/llm/test_cassette.py::test_AC23_5_5_output_affecting_change_misses",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.5.6",
            statement="Normalisation strips only the intended volatile fields (timestamps, random request ids): differing volatile fields keep the key stable, while any output-relevant field changing the key proves nothing else is stripped",  # was AC23.5.6
            test="apps/backend/tests/llm/test_cassette.py::test_AC23_5_6_normalization_strips_only_volatile_fields",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.5.7",
            statement="A `correctness` cassette MUST refuse to record (`CassetteValidationError`) when the response fails ground-truth validation or no validator is supplied; a `flow-only` cassette records freely and never claims LLM correctness",  # was AC23.5.7
            test="apps/backend/tests/llm/test_cassette.py::test_AC23_5_7_correctness_cassette_refuses_to_record_when_validation_fails",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.6.1",
            statement="`litellm_stream` in `replay` serves a committed frozen-text cassette by synthesising a stream (text and image-part/vision requests both resolve their cassette) with **zero network and no API key**; the caller's `accumulate_stream` rebuilds the recorded text",  # was AC23.6.1
            test="apps/backend/tests/llm/test_streaming_cassette.py::test_AC23_6_1_replay_synthesises_stream_from_frozen_text_cassette",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.6.2",
            statement="A streamed request with no matching cassette is a **hard failure** in `replay` (`CassetteMiss`, scene = derived role) that never falls back to the network",  # was AC23.6.2
            test="apps/backend/tests/llm/test_streaming_cassette.py::test_AC23_6_2_replay_miss_is_hard_failure",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.6.3",
            statement="`record` performs the real (here mocked) streaming call, accumulates the full text, freezes a cassette idempotently (no diff churn) and yields the text so the caller still works; a `correctness` streaming cassette refuses to record without a validator; the mode defaults to `LLM_CASSETTE_MODE`",  # was AC23.6.3
            test="apps/backend/tests/llm/test_streaming_cassette.py::test_AC23_6_3_record_accumulates_and_writes_cassette",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.6.4",
            statement="`off` mode is an EXACT passthrough of the live (mocked) stream — deltas arrive unchanged (not collapsed), no cassette is written, and a provider failure is normalised to `LLMError` exactly as before — so prod/staging keep running the live `-m llm` path real",  # was AC23.6.4
            test="apps/backend/tests/llm/test_streaming_cassette.py::test_AC23_6_4_off_mode_passes_stream_through_untouched",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.6.5",
            statement="The fingerprint role is derived from the messages (any image part → `vision`, else `text`), so text and vision get **different** keys, while the same semantic request under a different model id resolves the **same** cassette (model-id-agnostic)",  # was AC23.6.5
            test="apps/backend/tests/llm/test_streaming_cassette.py::test_AC23_6_5_role_derivation_text_vs_vision_distinct_keys",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.7.1",
            statement="The LLM cassette integrity gate (`tools/check_llm_cassettes.py`, lint job) fails when any committed statement-extraction cassette breaks the balance-chain invariant `opening + Σ amounts ≈ closing` (Decimal) — detectable drift for a re-recorded/inconsistent cassette; pure Python, no key/network/DB, so it never perturbs the AC behavioral-score aggregator",  # was AC23.7.1
            test="tests/tooling/test_llm_cassette_integrity.py::test_AC23_7_1_committed_cassettes_satisfy_balance_chain",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.8.1",
            statement="The eval set covers a documented **modality × institution-class × edge-condition** matrix (text & vision modalities; generic & named-institution classes; happy-path & duplicate-row/#1254 edge conditions) to a stated minimum case count, and the doc explicitly states drift-detection power is bounded by that breadth (no overclaiming)",  # was AC23.8.1
            test="tests/tooling/test_cassette_graded_eval.py::test_AC23_8_1_eval_set_covers_documented_matrix_to_min_count",
            priority="P1",
            status="done",
            proof_kind="eval",
        ),
        ACRecord(
            id="AC-llm.8.2",
            statement="Each case scores **per-field accuracy** (exact/normalised match: amounts as `Decimal`, dates ISO-normalised, descriptions case/space-normalised) against the case's known-correct ground-truth values, producing a numeric `[0,1]` score",  # was AC23.8.2
            test="tests/tooling/test_cassette_graded_eval.py::test_AC23_8_2_normalizers_are_exact_value_aware",
            priority="P1",
            status="done",
            proof_kind="eval",
        ),
        ACRecord(
            id="AC-llm.8.3",
            statement="A per-case score floor is persisted in a ratcheted JSONL baseline and may only go **UP** (`--update` raises, never lowers; refuses to cement a regressed run); the gate FAILS when any case scores below its floor",  # was AC23.8.3
            test="tests/tooling/test_cassette_graded_eval.py::test_AC23_8_3_committed_cassettes_meet_their_floors",
            priority="P1",
            status="done",
            proof_kind="eval",
        ),
        ACRecord(
            id="AC-llm.8.4",
            statement="A deliberately-regressed cassette (a field flipped so its score drops below floor) is CAUGHT and fails the gate — proven by a test that injects the regression and asserts the gate returns a violation",  # was AC23.8.4
            test="tests/tooling/test_cassette_graded_eval.py::test_AC23_8_4_injected_regression_fails_the_gate",
            priority="P1",
            status="done",
            proof_kind="eval",
        ),
        ACRecord(
            id="AC-llm.8.5",
            statement='The graded eval distinguishes "balance invariant passes but field-accuracy regressed" from "invariant fails": a cassette whose chain still reconciles but whose amount no longer matches ground truth is flagged by the graded gate while the AC23.7 balance gate stays green',  # was AC23.8.5
            test="tests/tooling/test_cassette_graded_eval.py::test_AC23_8_5_balance_passes_but_field_accuracy_regresses",
            priority="P1",
            status="done",
            proof_kind="eval",
        ),
        ACRecord(
            id="AC-llm.8.6",
            statement="The eval runs deterministically in CI on committed cassettes with **NO network and NO API key**; the refresh path is the local `make llm-record` target (documented), never CI",  # was AC23.8.6
            test="tests/tooling/test_cassette_graded_eval.py::test_AC23_8_6_runs_on_committed_cassettes_without_network_or_key",
            priority="P1",
            status="done",
            proof_kind="eval",
        ),
        ACRecord(
            id="AC-llm.8.7",
            statement="Reliability scoring aggregates over **N≥2 samples** per case when multiple recordings of the same case exist (mean score), and the single-sample limitation (one recording ⇒ point estimate, not a reliability measure) is documented",  # was AC23.8.7
            test="tests/tooling/test_cassette_graded_eval.py::test_AC23_8_7_reliability_aggregates_over_n_samples",
            priority="P1",
            status="done",
            proof_kind="eval",
        ),
        ACRecord(
            id="AC-llm.9.1",
            statement="Importing the litellm client disables litellm's aiohttp transport (so no per-`acompletion` unclosed-session leak); the transport resolver returns httpx | `test_AC23_9_1_litellm_aiohttp_transport_disabled_prevents_session_leak`",  # was AC23.9.1
            test="apps/backend/tests/llm/test_client.py::test_AC23_9_1_litellm_aiohttp_transport_disabled_prevents_session_leak",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        # --- group 10: transparent per-request cassette decision (#1596) ---
        ACRecord(
            id="AC-llm.10.1",
            statement="A cassette HIT serves the frozen response without ever resolving provider credentials — the lazy provider resolver is invoked only when the layer actually needs the network",
            test="apps/backend/tests/llm/test_transparent_cassette.py::test_hit_serves_frozen_without_credentials",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.10.2",
            statement="A cassette MISS is a hard failure, never a skip or silent network call: locally without a usable key, and in CI ALWAYS — even when a key is present in the environment",
            test="apps/backend/tests/llm/test_transparent_cassette.py::test_miss_in_ci_is_hard_red_even_with_key",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.10.3",
            statement="A local MISS with a usable key performs the real call and auto-records exactly one new cassette; a HIT never re-records without the refresh knob",
            test="apps/backend/tests/llm/test_transparent_cassette.py::test_miss_with_key_records_locally",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.10.4",
            statement="The layer-owned refresh knob re-records a HIT locally and is refused in CI — cassettes are only ever written locally and reviewed in the diff",
            test="apps/backend/tests/llm/test_transparent_cassette.py::test_refresh_is_refused_in_ci",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.10.5",
            statement="Explicit LLM_LIVE (workflow/deployment config, e.g. the staging live gates) and the not-engaged default (prod/app runtime) are exact live passthrough with the store untouched",
            test="apps/backend/tests/llm/test_transparent_cassette.py::test_live_bypasses_the_store_entirely",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.10.6",
            statement="The store tracks which cassettes were served — the substrate for orphan detection (a committed cassette no suite run ever serves is a changed-prompt leftover)",
            test="apps/backend/tests/llm/test_transparent_cassette.py::test_served_keys_are_tracked_for_orphan_detection",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
        # ── group 11: extraction-corpus E2E journeys in the merge tier ──
        # The committed cassette corpus (fixtures live in common/testing;
        # the cassette MECHANISM and its ACs live here, see
        # common/testing/contract.py's docstring) is seeded through the
        # provider-free seam into the full downstream statement journey in
        # ci.yml backend-e2e-tier1. Deterministic replay of frozen artifacts:
        # proof_kind=property.
        ACRecord(
            id="AC-llm.11.1",
            statement="The seeded extraction corpus is a committed 10-fingerprint manifest whose diversity invariants are asserted in code — both modalities (text+vision), bank and brokerage institution classes, a duplicate-rows edge case, a zero-transaction statement, and >=3 statements of 150+ transactions — and unpostable-row drops are pinned to an exact allowlist, so the corpus can neither silently shrink nor homogenize",
            test="apps/backend/tests/e2e/test_statement_corpus_journeys.py::test_corpus_manifest_is_diverse",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.11.2",
            statement="Every corpus cassette's frozen extraction output seeds a parsed statement that completes the provider-free downstream journey: transactions endpoint returns the exact cassette row count with Decimal amounts, Stage-1 review reports a validated balance chain, duplicate/transfer-pair candidates are resolved through the reviewer path, approve auto-creates one posted journal entry per transaction, a statement-scoped reconciliation run reaches unmatched=0, and the balance sheet reflects the statement's net movement on the posting account with the accounting equation balanced",
            test="apps/backend/tests/e2e/test_statement_corpus_journeys.py::test_corpus_statement_full_journey",
            priority="P0",
            status="done",
            proof_kind="property",
        ),
        ACRecord(
            id="AC-llm.11.3",
            statement="The zero-transaction corpus statement (a real brokerage month with no activity) is deterministic end-to-end: it seeds, lists, reviews with a trivially-tied balance chain, approves with journal_entries_created == 0, and a statement-scoped reconciliation run reports unmatched=0",
            test="apps/backend/tests/e2e/test_statement_corpus_journeys.py::test_corpus_zero_transaction_statement_approves_empty",
            priority="P1",
            status="done",
            proof_kind="property",
        ),
    ],
)
