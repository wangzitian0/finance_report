"""Machine-checkable PackageContract for ``llm``."""

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
    name="llm",
    status="active",
    tier="LLM-LED",
    depends_on="observability platform".split(),
    roles="base extension data".split(),
    implementations={"be": "apps/backend/src/llm", "fe": None},
    context=ContextScope(
        purpose="Own model-provider interaction.",
        in_scope=[
            "Protocol-family, model, scene, and scene-binding language.",
            "Provider-secret handling, routing, catalogues, and usage measurement.",
            "Input-keyed cassette record/replay and model-call evaluation mechanisms.",
        ],
        out_of_scope=[
            "Extraction, advisor, or reconciliation business prompts and decisions.",
            "Runtime dependency presence, environment substitution, or deployment policy.",
            "Generic telemetry policy or persistence-substrate ownership.",
        ],
    ),
    relationships=rels(
        "llm",
        """
observability|published-language|Uses published safe logging and AI-provider-call telemetry.
platform|composition|Uses platform persistence mixins for LLM configuration rows.
""",
    ),
    units=units(
        """
@vo|base/types.py|Scene ProtocolFamily ModelSpec SceneBinding Encrypted DecodeParams
LlmUsageMeter|ent|base/usage.py
LitellmClient|svc|extension/scene_client.py
build_call|svc|extension/routing.py
ai_semantic_score|svc|extension/semantic_scoring.py
CassetteStore|svc|extension/cassette.py
LayeredConfigSource|svc|extension/factory.py
@ent|-|LlmProvider LlmSceneBinding
UsageRepository|repo
UsageRecorded|ev
UsageRollup|proj
ConfigSource|repo|base/config_source.py|extension/db_config.py
LLMClient|repo|base/protocols.py|extension/client.py
"""
    ),
    interface="""
AIStreamError CASSETTE_DIR Cassette CassetteMiss CassetteRecorder CassetteStore
CassetteTag CassetteValidationError ConfigSource DecodeParams DbConfigSource
Encrypted EnvConfigSource FernetCipher LLMBudgetExceeded LLMClient LLMConfigError
LLMError LayeredConfigSource LitellmCall LitellmCatalog LitellmClient LlmProvider
LlmSceneBinding LlmUsageMeter Message Modality ModelCatalogError ModelSpec
ProtocolFamily ProviderRef ReasoningEffort Scene SceneBinding SecretCipher
accumulate_stream ai_semantic_score build_call build_cipher cassette_completion
estimate_tokens estimate_tokens_from_chars fingerprint get_config_source
get_llm_client get_usage_meter litellm_stream miss_summary protocol_for
resolve_provider_and_model stream_ai_chat stream_ai_json
""".split(),
    events=[],
    invariants=invs(
        """
@$t/test_llm_package.py
interface-equals-published-language|The published language (contract.interface) equals __init__.__all__.|test_AC_llm_1_1_only_all_is_the_published_language
converges-by-layer|The package converges into base/ + extension/ + data/.|test_AC_llm_1_2_converges_by_layer
base-layer-pure|Base/ never imports the package's own extension/, the ORM, or litellm.|test_AC_llm_1_3_base_layer_is_pure
no-litellm-at-root|Importing the package root never imports litellm.|test_AC_llm_1_4_root_import_is_litellm_free
runtime-classifies-llm-implements|The cassette record/replay mechanism lives in this package only.|test_AC_llm_1_5_cassette_mechanism_only_in_llm
passes-own-governance-gate|Check_package_contract validates llm with no violations.|test_AC_llm_1_6_package_contract_gate_passes_for_llm
"""
    ),
    roadmap=acs(
        "llm",
        """
@$be/llm/test_signature_contract.py|P1|done|property
typed-client.1|The published LLMClient scene-keyed protocol has a production LitellmClient implementation.|test_AC_llm_typed_client_1_scene_client_is_implemented_and_consumed
decode-contract.1|Provider decode knobs travel as one immutable DecodeParams value and cassette record/replay wraps the live stream as a decorator.|test_AC_llm_decode_contract_1_groups_decode_and_decorates_cassettes
token-estimate.1|Token estimation has one definition in llm, returns zero for empty input.|test_AC_llm_token_estimate_1_is_single_homed
@$be/llm/test_secrets.py|P1|done|property
1.2|`FernetCipher` round-trips a provider secret and never persists plaintext.|test_AC23_1_2_round_trips_a_provider_secret_without_storing_plaintext
1.3|Key rotation is single-pass.|test_AC23_1_3_rotation_is_single_pass_old_ciphertext_still_decrypts
1.4|`build_cipher` raises `LLMConfigError`.|test_AC23_1_4_build_cipher_fails_closed_without_a_key
@$be/llm/test_client.py|P1|done|property
2.2|The litellm transport streams.|test_AC23_2_2_stream_yields_only_nonempty_deltas
2.3|Provider failures are normalised to `LLMError` with a retryable verdict.|test_AC23_2_3_provider_error_is_normalised_to_llmerror
2.7|Glm-5.3-flash text and vision calls use enabled thinking and a supported low/high reasoning effort even.|test_glm53_stream_uses_supported_reasoning_parameters
5.4|`record` performs the provider call and persists the cassette.|test_AC23_5_4_cassette_completion_off_mode_does_a_live_litellm_call
9.1|Importing the litellm client disables litellm's aiohttp transport.|test_AC23_9_1_litellm_aiohttp_transport_disabled_prevents_session_leak
provider-error-code.1|A failed provider call raises an LLMError whose text names the exception class, the integer HTTP status and a numeric provider error code.|test_AC_llm_provider_error_code_1_text_names_status_and_code_and_nothing_else|:-
@$be/llm/test_env_config.py|P1|done|property
2.4|`EnvConfigSource` projects the existing env settings onto scene bindings and reports `is_configured == False`.|test_AC23_2_4_unconfigured_when_no_api_key
2.8|Default text scenes select the SDK primary model and its fallbacks.|test_default_glm_models_reach_scene_bindings
@$be/llm/test_llm_db_config.py|P1|done|property
3.1|`DbConfigSource` reads provider instances and scene bindings from `llm_providers` / `llm_scene_bindings`.|test_AC23_3_1_db_config_reads_providers_and_bindings
3.2|Config resolves DB-first with an env fallback.|test_AC23_3_2_layered_uses_db_first_then_env
4.8|`DbConfigSource.get_provider` is scoped to the caller's scope.|test_AC23_4_8_get_provider_is_user_scoped_no_cross_tenant_key_disclosure
@$be/llm/test_llm_api.py|P1|done|property
4.1|`GET /llm/config/status` reports `{configured}` for the current user from the layered config source, driving the first-run modal.|test_AC23_4_1_config_status_flips_when_user_configures
4.2|`GET/POST/DELETE /llm/providers` is scoped to the current user.|test_AC23_4_2_provider_create_encrypts_and_never_returns_key
4.3|`GET /llm/catalog` lists models.|test_AC23_4_3_catalog_lists_models_with_filters
4.4|`GET/PUT /llm/scenes` round-trips the current user's scene→model bindings, validated against their providers.|test_AC23_4_4_scenes_round_trip
4.5|Per-user config resolves.|test_AC23_4_5_user_binding_drives_resolution
4.6|The legacy `services/ai_models.py` + `routers/ai_models.py` are removed.|test_AC23_4_6_legacy_ai_models_endpoint_removed
4.9|`api_base` rejects loopback/private/link-local/reserved IPs and local-only names at the schema boundary, closing the obvious SSRF foot-guns.|test_AC23_4_9_provider_rejects_ssrf_api_base
4.10|Provider creation is capped per user.|test_AC23_4_10_provider_count_capped
2624.1|Scene bindings in EnvConfigSource, DbConfigSource.|test_AC_llm_2624_1_scenes_enforce_three_roles_and_reject_retired_models
@$be/llm/test_cassette.py|P1|done|property
5.1|No process-level mode env exists.|test_AC23_5_4_off_mode_is_plain_live_call
5.2|`replay` returns the recorded response with **zero network calls and no API key**.|test_AC23_5_2_replay_returns_recorded_response_without_network
5.3|A request with no matching cassette is a **hard failure** in `replay` that never falls back to the network.|test_AC23_5_3_replay_miss_is_a_hard_failure_no_network
5.5|Fingerprint integrity: a change to an output-affecting field → different key.|test_AC23_5_5_output_affecting_change_misses
5.6|Normalisation strips only the intended volatile fields.|test_AC23_5_6_normalization_strips_only_volatile_fields
5.7|A `correctness` cassette MUST refuse to record.|test_AC23_5_7_correctness_cassette_refuses_to_record_when_validation_fails
@$be/llm/test_streaming_cassette.py|P1|done|property
6.1|`litellm_stream` in `replay` serves a committed frozen-text cassette by synthesising a stream with **zero network and no API key**.|test_AC23_6_1_replay_synthesises_stream_from_frozen_text_cassette
6.2|A streamed request with no matching cassette is a **hard failure** in `replay` that never falls back to the network.|test_AC23_6_2_replay_miss_is_hard_failure
6.3|`record` performs the real streaming call, accumulates the full text, freezes a cassette idempotently and yields the text.|test_AC23_6_3_record_accumulates_and_writes_cassette
6.4|`off` mode is an EXACT passthrough of the live stream.|test_AC23_6_4_off_mode_passes_stream_through_untouched
6.5|The fingerprint role is derived from the messages.|test_AC23_6_5_role_derivation_text_vs_vision_distinct_keys
@$t/test_cassette_graded_eval.py|P1|done|eval
8.1|The eval set covers a documented **modality × institution-class × edge-condition** matrix to a stated minimum case count.|test_AC23_8_1_eval_set_covers_documented_matrix_to_min_count
8.2|Each case scores **per-field accuracy** against the case's known-correct ground-truth values, producing a numeric `[0,1]` score.|test_AC23_8_2_normalizers_are_exact_value_aware
8.3|A per-case score floor is persisted in a ratcheted JSONL baseline and may only go **UP**.|test_AC23_8_3_committed_cassettes_meet_their_floors
8.4|A deliberately-regressed cassette is CAUGHT and fails the gate.|test_AC23_8_4_injected_regression_fails_the_gate
8.5|The graded eval distinguishes "balance invariant passes but field-accuracy regressed" from "invariant fails".|test_AC23_8_5_balance_passes_but_field_accuracy_regresses
8.6|The eval runs deterministically in CI on committed cassettes with **NO network and NO API key**.|test_AC23_8_6_runs_on_committed_cassettes_without_network_or_key
8.7|Reliability scoring aggregates over **N≥2 samples** per case.|test_AC23_8_7_reliability_aggregates_over_n_samples
8.8|The graded-eval corpus carries an independently-persisted, raise-only minimum-case-count floor that fails the gate.|test_AC_corpus_count_floor_blocks_the_gate_when_corpus_is_below_it|:property
@$be/llm/test_transparent_cassette.py|P0|done|property
10.1|A cassette HIT serves the frozen response.|test_hit_serves_frozen_without_credentials
10.2|A cassette MISS is a hard failure, never a skip or silent network call.|test_miss_in_ci_is_hard_red_even_with_key
10.3|A local MISS with a usable key performs the real call and auto-records exactly one new cassette.|test_miss_with_key_records_locally|P1
10.4|The layer-owned refresh knob re-records a HIT locally and is refused in CI.|test_refresh_is_refused_in_ci
10.5|Explicit LLM_LIVE and the not-engaged default are exact live passthrough with the store untouched.|test_live_bypasses_the_store_entirely
10.8|The transparent auto-record path enforces the same correctness red line as explicit recording.|test_auto_record_enforces_the_correctness_red_line
10.6|The store tracks which cassettes were served.|test_served_keys_are_tracked_for_orphan_detection|P1
@$be/integration/test_statement_corpus_journeys.py|P0|done|property
11.1|The seeded extraction corpus is a committed 10-fingerprint manifest whose diversity invariants are asserted in code.|test_corpus_manifest_is_diverse
11.2|Every corpus cassette's frozen extraction output seeds a parsed statement whose rows receive explicit, non-reusable reviewer-confirmed semantic anchors.|test_corpus_statement_full_journey
11.3|The zero-transaction corpus statement is deterministic end-to-end.|test_corpus_zero_transaction_statement_approves_empty|P1
11.4|Every non-empty corpus statement's income statement reports total_income minus total_expenses.|test_corpus_statement_full_journey
11.5|Every non-empty corpus statement's cash-flow report accounts for the posting account's net movement exactly once.|test_corpus_statement_full_journey|P1
11.6|Three real corpus statements seeded and approved for the SAME user produce combined-period balance sheet assets equal to opening stocks plus net movements and income equal to net movements.|test_corpus_multi_statement_acceptance_same_user
@$e2e/test_institution_statement_journeys.py|P1|done|eval
12.1|A CMB generated statement completes upload -> live extraction -> approve -> balanced balance sheet on the deployed staging environment.|test_cmb_statement_journey
12.2|A MariBank generated statement completes upload -> live extraction -> approve -> balanced balance sheet on the deployed staging environment.|test_maribank_statement_journey
12.3|A Pingan generated statement completes upload -> live extraction -> approve -> balanced balance sheet on the deployed staging environment.|test_pingan_statement_journey
12.4|The committed GXS PDF + expected-JSON pair grades live extraction on staging.|test_gxs_statement_journey_matches_expected_balances
@$be/ai/test_model_catalog.py|P1
13.1|LitellmCatalog.list_models lists the configured models, each carrying pricing/capability fields.|test_AC6_11_1_catalog_lists_configured_models
13.2|LitellmCatalog.get resolves a known configured model and returns None for an unknown model id.|test_AC6_11_2_unknown_model_rejected
13.3|LitellmCatalog.list_models is local and deterministic.|test_AC6_11_3_catalog_is_local_deterministic
13.4|LitellmCatalog.list_models composes its modality and free_only filters.|test_AC6_11_4_catalog_modality_and_free_filters
13.5|LitellmCatalog.get's per-model modality lookup confirms the vision/OCR model accepts image input.|test_AC6_11_5_model_modality_lookup
13.6|LitellmCatalog.get resolves the same model spec whether given a bare model id or a provider-qualified one.|test_AC6_11_6_catalog_get_bare_or_qualified
@$be/extraction/test_extraction_cassette_replay.py|P1|done|property
14.1|A cassette-delivered extraction with no period_start/period_end preserves that absence as a review-required result.|test_AC_llm_14_1_missing_period_remains_review_only_via_replay
14.2|A cassette-delivered extraction with no period fields AND no parseable transaction dates anywhere still rejects cleanly.|test_AC_llm_14_2_no_recoverable_date_anywhere_rejects_cleanly_via_replay
14.3|A cassette-delivered extraction whose balance chain does not reconcile quarantines to the terminal rejected status with zero persisted Layer-2 rows.|test_AC_llm_14_3_unreconciled_balance_quarantines_to_rejected_via_replay
@$t/test_evidence_bundle.py|P1|done|property
evidence-bundle.1|Common.testing.evidence_bundle.build_evidence_bundle assembles ONE evidence bundle from already-computed CI artifacts.|test_AC8_13_164_bundle_assembles_the_four_ratchet_water_lines_and_gate_map
evidence-bundle.2|Main-branch CI generates the evidence bundle.|test_AC8_13_165_both_producers_wire_the_same_generator_into_their_workflow
@$fe/__tests__/aiModels.test.ts|P2
fe-ai-models-catalog.1|`fetchAiModels` calls `/api/llm/catalog` with no params.|AC16.8.1 calls /api/llm/catalog with no query when no options provided
fe-ai-models-catalog.2|`fetchAiModels` appends `modality` query param when provided.|AC16.8.2 appends modality query param when provided
fe-ai-models-catalog.3|`fetchAiModels` appends `free_only=true` when `freeOnly` is set.|AC16.8.3 appends free_only=true when freeOnly is set
@$fe/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx|P2
fe-ai-settings2.1|Settings page `/settings/ai` exposes toggles for `enable_ai_reconciliation`, `enable_ai_classification`, persisted.|AC18.5.5 — Settings AI toggles persist
fe-ai-settings2.2|Frontend tests: mount ConfidenceBadge for each tier.|AC18.5.7 — AI settings mount reflects saved toggles
@$t/test_sdk_model_defaults_surfaces.py|P0|done|property
sdk-model-defaults.2|App source names no model id.|test_AC_llm_sdk_model_defaults_2_ci_preview_staging_assign_no_model
sdk-model-defaults.4|Runtime hooks manifest pins no model variable across any hook slot.|test_AC_llm_sdk_model_defaults_4_production_release_only_reports_the_catalog|P1
@-|P1|done|property
1.1|The three axes are typed.|$be/llm/test_types.py::test_AC23_1_1_protocol_family_enumerates_the_supported_families
1.5|The seam protocols are runtime-checkable and a conforming implementation satisfies `isinstance`.|$be/llm/test_contract.py::test_AC23_1_5_conforming_implementations_satisfy_the_protocols
2.1|Provider routing maps each protocol family onto the correct litellm call.|$be/llm/test_routing.py::test_AC23_2_1_openai_compatible_prefixes_and_keeps_api_base
2.5|The dynamic catalogue lists configured models enriched with litellm pricing, flags the free tier.|$be/llm/test_catalog.py::test_AC23_2_5_lists_configured_models_with_pricing
2.6|The usage meter counts requests and tokens per UTC day and rolls over at the day boundary.|$be/llm/test_usage.py::test_AC23_2_6_counts_requests_and_tokens
4.7|The usage meter is a process-wide singleton.|$be/ai/test_ai_streaming.py::test_AC23_4_7_records_request_and_token_usage
7.1|The LLM cassette integrity gate fails.|$t/test_llm_cassette_integrity.py::test_AC23_7_1_committed_cassettes_satisfy_balance_chain
10.7|Downstream must not know whether the LLM is real or frozen.|$t/test_llm_cassette_boundary.py::test_AC_llm_10_7_no_cassette_knowledge_outside_the_layer|P0
14.4|Common.testing.reverify_real_corpus.compare_scores correctly distinguishes a field-accuracy regression, an improvement.|$t/test_reverify_real_corpus.py::test_reverify_case_never_mutates_the_committed_cassette|P2
semantic-scoring.1|Ai_semantic_score streams a caller-built prompt.|$be/llm/test_semantic_scoring.py::test_ai_semantic_score_returns_score
fe-ia-ai-settings.1|The AI Settings page renders an editable form with explicit Save and Reset controls that submits the edited flags.|$fe/__tests__/aiSettingsPage.test.tsx::AC22.15.2 renders the loaded flags and keeps Save disabled until edited|:-
sdk-model-defaults.1|With no model variable set, each of the three app model roles equals the infra2 SDK LlmSettings default.|$be/llm/test_sdk_model_defaults.py::test_AC_llm_sdk_model_defaults_1_app_defaults_equal_the_sdk_defaults|P0
sdk-model-defaults.3|Staging serves exactly the SDK default models.|$e2e/test_ai_provider_connectivity.py::test_staging_catalog_serves_the_sdk_default_models|P0
roles-only.1|The app has exactly three model environment keys.|$t/test_llm_roles_only.py::test_AC_llm_roles_only_1_the_model_env_keys_are_exactly_the_three_roles|P0
banned-models.1|The retired z.ai vision model of the GLM 4 generation is never used.|$t/test_banned_models.py::test_AC_llm_banned_models_1_no_tracked_file_names_glm_4_6v|:-
""",
    ),
    concepts=concepts(
        """
cassette_graded_eval|common/llm/readme.md#cassette-graded-eval|Graded per-field accuracy eval over committed cassettes with a ratcheted per-case score floor (EPIC-023 AC23.8) — the accuracy oracle complementing the AC23.7 balance-chain consistency gate. Internalized into the llm package.|common/llm/readme.md#cassettes,docs/project/EPIC-023.llm-provider-abstraction.md,common/testing/cassette_graded_eval.py,common/testing/check_cassette_graded_eval.py,common/testing/fixtures/cassette-eval-baseline.jsonl,common/testing/fixtures/llm_cassettes/|tests/tooling/test_cassette_graded_eval.py|llm|concept
llm_provider_abstraction|common/llm/readme.md#axes|LLM layer's three orthogonal axes (protocol family x model x scene), scene->model binding, and at-rest provider-secret encryption.|common/extraction/readme.md,docs/project/EPIC-023.llm-provider-abstraction.md,apps/backend/src/llm/base/types.py,apps/backend/src/llm/base/secrets.py,apps/backend/src/llm/extension/cassette.py|apps/backend/tests/llm/test_secrets.py,apps/backend/tests/llm/test_types.py,apps/backend/tests/llm/test_cassette.py|llm|concept
"""
    ),
)
