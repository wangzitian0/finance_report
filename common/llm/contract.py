"""PackageContract for ``llm``."""

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
CassetteTag CassetteValidationError ConfigSource DecodeParams DbConfigSource Encrypted
EnvConfigSource FernetCipher LLMBudgetExceeded LLMClient LLMConfigError LLMError
LayeredConfigSource LitellmCall LitellmCatalog LitellmClient LlmProvider LlmSceneBinding
LlmUsageMeter Message Modality ModelCatalogError ModelSpec ProtocolFamily ProviderRef
ReasoningEffort Scene SceneBinding SecretCipher accumulate_stream ai_semantic_score
build_call build_cipher cassette_completion estimate_tokens estimate_tokens_from_chars
fingerprint get_config_source get_llm_client get_usage_meter litellm_stream miss_summary
protocol_for resolve_provider_and_model stream_ai_chat stream_ai_json
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
@$be/llm/test_signature_contract.py|P1
typed-client.1||test_AC_llm_typed_client_1_scene_client_is_implemented_and_consumed
decode-contract.1||test_AC_llm_decode_contract_1_groups_decode_and_decorates_cassettes
token-estimate.1||test_AC_llm_token_estimate_1_is_single_homed
@$be/llm/test_secrets.py|P1
1.2||test_AC23_1_2_round_trips_a_provider_secret_without_storing_plaintext
1.3||test_AC23_1_3_rotation_is_single_pass_old_ciphertext_still_decrypts
1.4||test_AC23_1_4_build_cipher_fails_closed_without_a_key
@$be/llm/test_client.py|P1
2.2||test_AC23_2_2_stream_yields_only_nonempty_deltas
2.3||test_AC23_2_3_provider_error_is_normalised_to_llmerror
2.7||test_glm53_stream_uses_supported_reasoning_parameters
5.4||test_AC23_5_4_cassette_completion_off_mode_does_a_live_litellm_call
9.1||test_AC23_9_1_litellm_aiohttp_transport_disabled_prevents_session_leak
provider-error-code.1||test_AC_llm_provider_error_code_1_text_names_status_and_code_and_nothing_else
@$be/llm/test_env_config.py|P1
2.4||test_AC23_2_4_unconfigured_when_no_api_key
2.8||test_default_glm_models_reach_scene_bindings
@$be/llm/test_llm_db_config.py|P1
3.1||test_AC23_3_1_db_config_reads_providers_and_bindings
3.2||test_AC23_3_2_layered_uses_db_first_then_env
4.8||test_AC23_4_8_get_provider_is_user_scoped_no_cross_tenant_key_disclosure
@$be/llm/test_llm_api.py|P1
4.1||test_AC23_4_1_config_status_flips_when_user_configures
4.2||test_AC23_4_2_provider_create_encrypts_and_never_returns_key
4.3||test_AC23_4_3_catalog_lists_models_with_filters
4.4||test_AC23_4_4_scenes_round_trip
4.5||test_AC23_4_5_user_binding_drives_resolution
4.6||test_AC23_4_6_legacy_ai_models_endpoint_removed
4.9||test_AC23_4_9_provider_rejects_ssrf_api_base
4.10||test_AC23_4_10_provider_count_capped
2624.1||test_AC_llm_2624_1_scenes_enforce_three_roles_and_reject_retired_models
@$be/llm/test_cassette.py|P1
5.1||test_AC23_5_4_off_mode_is_plain_live_call
5.2||test_AC23_5_2_replay_returns_recorded_response_without_network
5.3||test_AC23_5_3_replay_miss_is_a_hard_failure_no_network
5.5||test_AC23_5_5_output_affecting_change_misses
5.6||test_AC23_5_6_normalization_strips_only_volatile_fields
5.7||test_AC23_5_7_correctness_cassette_refuses_to_record_when_validation_fails
@$be/llm/test_streaming_cassette.py|P1
6.1||test_AC23_6_1_replay_synthesises_stream_from_frozen_text_cassette
6.2||test_AC23_6_2_replay_miss_is_hard_failure
6.3||test_AC23_6_3_record_accumulates_and_writes_cassette
6.4||test_AC23_6_4_off_mode_passes_stream_through_untouched
6.5||test_AC23_6_5_role_derivation_text_vs_vision_distinct_keys
@$t/test_cassette_graded_eval.py|P1|done|eval
8.1||test_AC23_8_1_eval_set_covers_documented_matrix_to_min_count
8.2||test_AC23_8_2_normalizers_are_exact_value_aware
8.3||test_AC23_8_3_committed_cassettes_meet_their_floors
8.4||test_AC23_8_4_injected_regression_fails_the_gate
8.5||test_AC23_8_5_balance_passes_but_field_accuracy_regresses
8.6||test_AC23_8_6_runs_on_committed_cassettes_without_network_or_key
8.7||test_AC23_8_7_reliability_aggregates_over_n_samples
8.8||test_AC_corpus_count_floor_blocks_the_gate_when_corpus_is_below_it|:property
@$be/llm/test_transparent_cassette.py
10.1||test_hit_serves_frozen_without_credentials
10.2||test_miss_in_ci_is_hard_red_even_with_key
10.3||test_miss_with_key_records_locally|P1
10.4||test_refresh_is_refused_in_ci
10.5||test_live_bypasses_the_store_entirely
10.8||test_auto_record_enforces_the_correctness_red_line
10.6||test_served_keys_are_tracked_for_orphan_detection|P1
@$be/integration/test_statement_corpus_journeys.py
11.1||test_corpus_manifest_is_diverse
11.2|Every corpus cassette's frozen extraction output seeds a parsed statement whose rows receive explicit, non-reusable reviewer-confirmed semantic anchors.|test_corpus_statement_full_journey
11.4|Every non-empty corpus statement's income statement reports total_income minus total_expenses.|^
11.5|Every non-empty corpus statement's cash-flow report accounts for the posting account's net movement exactly once.|^|P1
11.3||test_corpus_zero_transaction_statement_approves_empty|P1
11.6||test_corpus_multi_statement_acceptance_same_user
@$e2e/test_institution_statement_journeys.py|P1|done|eval
12.1||test_cmb_statement_journey
12.2||test_maribank_statement_journey
12.3||test_pingan_statement_journey
12.4||test_gxs_statement_journey_matches_expected_balances
@$be/ai/test_model_catalog.py|P1
13.1||test_AC6_11_1_catalog_lists_configured_models
13.2||test_AC6_11_2_unknown_model_rejected
13.3||test_AC6_11_3_catalog_is_local_deterministic
13.4||test_AC6_11_4_catalog_modality_and_free_filters
13.5||test_AC6_11_5_model_modality_lookup
13.6||test_AC6_11_6_catalog_get_bare_or_qualified
@$be/extraction/test_extraction_cassette_replay.py|P1
14.1||test_AC_llm_14_1_missing_period_remains_review_only_via_replay
14.2||test_AC_llm_14_2_no_recoverable_date_anywhere_rejects_cleanly_via_replay
14.3||test_AC_llm_14_3_unreconciled_balance_quarantines_to_rejected_via_replay
@$t/test_evidence_bundle.py|P1
evidence-bundle.1||test_AC8_13_164_bundle_assembles_the_four_ratchet_water_lines_and_gate_map
evidence-bundle.2||test_AC8_13_165_both_producers_wire_the_same_generator_into_their_workflow
@$fe/__tests__/aiModels.test.ts|P2
fe-ai-models-catalog.1||AC16.8.1 calls /api/llm/catalog with no query when no options provided
fe-ai-models-catalog.2||AC16.8.2 appends modality query param when provided
fe-ai-models-catalog.3||AC16.8.3 appends free_only=true when freeOnly is set
@$fe/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx|P2
fe-ai-settings2.1||AC18.5.5 — Settings AI toggles persist
fe-ai-settings2.2||AC18.5.7 — AI settings mount reflects saved toggles
@$t/test_sdk_model_defaults_surfaces.py
sdk-model-defaults.2||test_AC_llm_sdk_model_defaults_2_ci_preview_staging_assign_no_model
sdk-model-defaults.4||test_AC_llm_sdk_model_defaults_4_production_release_only_reports_the_catalog|P1
@$be/llm/test_types.py|P1
1.1||test_AC23_1_1_protocol_family_enumerates_the_supported_families
@$be/llm/test_contract.py|P1
1.5||test_AC23_1_5_conforming_implementations_satisfy_the_protocols
@$be/llm/test_routing.py|P1
2.1||test_AC23_2_1_openai_compatible_prefixes_and_keeps_api_base
@$be/llm/test_catalog.py|P1
2.5||test_AC23_2_5_lists_configured_models_with_pricing
@$be/llm/test_usage.py|P1
2.6||test_AC23_2_6_counts_requests_and_tokens
@$be/ai/test_ai_streaming.py|P1
4.7||test_AC23_4_7_records_request_and_token_usage
@$t/test_llm_cassette_integrity.py|P1
7.1||test_AC23_7_1_committed_cassettes_satisfy_balance_chain
@$t/test_llm_cassette_boundary.py
10.7||test_AC_llm_10_7_no_cassette_knowledge_outside_the_layer
@$t/test_reverify_real_corpus.py|P2
14.4||test_reverify_case_never_mutates_the_committed_cassette
@$be/llm/test_semantic_scoring.py|P1
semantic-scoring.1||test_ai_semantic_score_returns_score
@$fe/__tests__/aiSettingsPage.test.tsx|P1
fe-ia-ai-settings.1||AC22.15.2 renders the loaded flags and keeps Save disabled until edited
@$be/llm/test_sdk_model_defaults.py
sdk-model-defaults.1||test_AC_llm_sdk_model_defaults_1_app_defaults_equal_the_sdk_defaults
@$e2e/test_ai_provider_connectivity.py
sdk-model-defaults.3||test_staging_catalog_serves_the_sdk_default_models
@$t/test_llm_roles_only.py
roles-only.1||test_AC_llm_roles_only_1_the_model_env_keys_are_exactly_the_three_roles
@$t/test_banned_models.py|P1
banned-models.1||test_AC_llm_banned_models_1_no_tracked_file_names_glm_4_6v
""",
    ),
    concepts=concepts(
        """
cassette_graded_eval|common/llm/readme.md#cassette-graded-eval|Graded per-field accuracy eval over committed cassettes with a ratcheted per-case score floor (EPIC-023 AC23.8).|common/llm/readme.md#cassettes,docs/project/EPIC-023.llm-provider-abstraction.md,common/testing/cassette_graded_eval.py,common/testing/check_cassette_graded_eval.py,common/testing/fixtures/cassette-eval-baseline.jsonl,common/testing/fixtures/llm_cassettes/|tests/tooling/test_cassette_graded_eval.py|llm|concept
llm_provider_abstraction|common/llm/readme.md#axes|LLM layer's three orthogonal axes (protocol family x model x scene), scene->model binding, and at-rest provider-secret encryption.|common/extraction/readme.md,docs/project/EPIC-023.llm-provider-abstraction.md,apps/backend/src/llm/base/types.py,apps/backend/src/llm/base/secrets.py,apps/backend/src/llm/extension/cassette.py|apps/backend/tests/llm/test_secrets.py,apps/backend/tests/llm/test_types.py,apps/backend/tests/llm/test_cassette.py|llm|concept
"""
    ),
)
