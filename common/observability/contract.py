"""PackageContract for ``observability``."""

from __future__ import annotations

from common.meta.package_contract import (
    ContextScope,
    PackageContract,
    acs,
    concepts,
    invs,
)

CONTRACT = PackageContract(
    name="observability",
    status="active",
    tier="CODE-ONLY",
    depends_on=[],
    implementations={"be": "apps/backend/src/observability", "fe": None},
    context=ContextScope(
        purpose="Own the cross-cutting observability language that makes runtime behavior and safe operational evidence visible.",
        in_scope=[
            "Vendor-neutral telemetry, metrics, and request identifiers.",
            "Structured audit and security logging with PII-safe error summaries.",
            "Operator-facing OpenPanel query tooling.",
        ],
        out_of_scope=[
            "Business-domain state, financial policy, or domain-event ownership.",
            "Application workflow, transaction, or lifecycle orchestration.",
            "Product analytics interpretation or user-facing application decisions.",
        ],
    ),
    interface="""
INVARIANT_VIOLATION_KINDS ErrorIds configure_database_pool_metrics configure_logging
configure_otel_metrics current_request_id ensure_request_id flow_run_telemetry
detect_pii get_logger get_observability_status http_route_label_from_scope
is_fastapi_instrumentation_active is_metrics_export_active log_financial_mutation
log_observability_startup log_security_warning mark_fastapi_instrumentation_active
record_ai_provider_call record_financial_invariant_violation record_http_request
record_rate_limit_rejected record_reconciliation_match_outcome
record_statement_classification_outcome record_statement_parse_outcome
run_with_async_parse_tracking safe_error_message safe_log_fields track
""".split(),
    events=[],
    invariants=invs(
        """
api-key-from-env-not-argv|The OpenPanel query CLI reads its API key from the environment, never from command-line args.|$t/test_openpanel_query.py::test_AC23_1_4_api_key_read_from_env_not_args
"""
    ),
    roadmap=acs(
        "observability",
        """
@$be/infra/test_observability_contract.py
1.1|OTEL settings are explicit, environment-backed config fields owned by the backend config singleton.|test_otel_settings_are_explicit_and_environment_backed
5.4|OTEL settings are documented as explicit backend config fields in config.py.|^
4.3||test_AC10_4_3_main_instruments_fastapi_app_instance
4.4||test_AC10_4_4_otel_resource_includes_commit_version
7.1|The backend starts without an observability backend.|test_backend_otel_absence_is_startup_safe
7.4|OTLP export is optional by default.|^
7.3||test_AC10_11_1_security_warning_redacts_credentials
7.7||test_production_renderer_outputs_structured_json
8.4||test_AC10_8_4_high_volume_fx_audit_noise_uses_debug_level|P1
9.1||test_AC10_9_1_observability_status_is_redacted_and_vendor_neutral
9.2||test_AC10_9_2_observability_startup_log_uses_runtime_contract
9.3||test_AC10_9_3_health_response_includes_redacted_observability_status
11.2||test_AC10_11_2_financial_mutation_audit_helpers_and_callsites
11.3||test_AC10_11_3_provider_error_body_logging_is_redacted
17.1|Common/observability/observability.md exists as the observability SSOT page.|test_observability_ssot_and_env_docs_are_linked
17.2|Common/observability/observability.md is anchored as the concept owner in common/meta/data/MANIFEST.yaml.|^
17.3|The three OTEL environment variables are documented in .env.example.|^
17.4|The three OTEL environment variables are documented in common/observability/observability.md alongside the SSOT page.|^
6.1|OTEL keys are present in the versioned required-env artifact.|test_required_env_manifest_exports_observability_contract|P1
6.2|OTEL keys are documented in the generated app env reference.|^|P1
6.3|The app publishes its deploy-time env requirements.|^|P1
6.4|Vault-owned observability fields are marked explicitly in required-env.|^|P1
@$be/infra/test_logger.py
1.2|Optional OTLP log export is configured.|test_configure_otel_logging_with_fake_exporter|P1
4.2|Configuring OTEL logging wires the OTLP exporter, resource.|^|P1
7.2|Logs export over OTLP through the configured exporter.|^
1.3||test_select_renderer_uses_json_in_production
2.2||test_build_otlp_logs_endpoint_preserves_logs_path
4.1||test_configure_otel_logging_missing_dependency_warns
1.4||test_select_renderer_uses_console_in_debug
1.5||test_configure_logging_basic
1.6||test_configure_logging_production_mode
2.1||test_build_otlp_logs_endpoint_adds_suffix|P1
4.5||test_configure_otel_tracing_missing_dependency_warns
4.6||test_configure_otel_logging_no_endpoint
4.7||test_build_otel_resource
4.8||test_configure_otel_tracing_no_endpoint
4.9||test_configure_otel_tracing_with_fake_exporter
4.10||test_configure_otel_tracing_appends_traces_path
16.1||test_build_processors_returns_list
16.2||test_add_trace_context_with_valid_span
16.3||test_add_trace_context_with_invalid_span
16.4||test_add_trace_context_handles_import_error
@$be/api/test_statements_router.py
8.1||test_AC10_8_1_upload_audit_logs_include_statement_input_provenance
8.3||test_AC10_8_3_statement_scoped_brokerage_import_audit_logs
@$be/extraction/test_statement_parsing_audit_logging.py
8.2||test_AC10_8_2_parse_checkpoints_and_failure_logs_are_structured
11.4||test_AC_observability_11_4_expected_parse_failure_never_logs_at_error
@$be/infra/test_telemetry_metrics.py
10.1||test_AC10_10_1_configure_metrics_is_noop_without_endpoint
10.2||test_AC10_10_2_red_metrics_record_low_cardinality_labels
10.3||test_AC10_10_3_saturation_gauges_observe_current_values
10.4||test_AC10_10_4_business_metric_helpers_record_outcomes
12.1||test_AC10_12_1_async_parse_tracking_records_failures
12.2||test_AC10_12_2_async_parse_tracking_receives_statement_context
12.3||test_AC10_12_3_parse_failure_state_and_log_contract_are_preserved
@$fe/__tests__/otel.test.ts|P1
fe-telemetry.2||AC24.1.2 strips query string and fragment from an absolute URL
fe-telemetry.3||AC24.1.3 keeps the error type but redacts the message/stack
@$fe/__tests__/telemetryEmission.test.ts|P1
fe-telemetry.4||emits a finished browser OTel span to the real OTLP exporter's export() (AC24.2.1)
fe-telemetry.5||dispatches an OpenPanel event via window.op when configured (AC24.2.2)
@$be/infra/test_request_log_probe_filter.py
19.1||test_AC_observability_19_1_successful_health_probe_writes_no_request_log_line
19.2||test_AC_observability_19_2_failed_health_probe_still_writes_request_log_line
19.3||test_AC_observability_19_3_non_probe_request_keeps_its_request_log_line
@$be/identity/test_auth.py
11.1||test_AC10_11_1_get_current_user_id_binds_user_context
@$be/infra/test_worker_telemetry.py|P1
12.4||test_flow_run_exports_parse_outcome_point_before_exit
@$be/extraction/test_invariant_observability.py|P0|done|property
18.1||test_AC26_8_1_balance_invalid_parse_quarantines_and_emits_metric
@$t/test_env_contract_boundary.py|P0|done|property
9.4||test_AC10_9_5_app_side_snapshot_is_retired
@$t/test_openpanel_query.py|P1
openpanel-query.1||test_AC23_1_4_api_key_read_from_env_not_args
@$fe/__tests__/analyticsTrack.test.ts|P1
fe-ia-analytics.1||AC22.18.2 exposes a typed taxonomy of at least six named product events
@$fe/__tests__/StatementUploader.test.tsx|P1
fe-ia-analytics.2||AC22.18.3 tracks UPLOAD_STARTED and UPLOAD_SUCCEEDED with non-PII props on success
@$fe/__tests__/frontendTelemetry.test.tsx|P1
fe-telemetry.1||AC24.1.1 renders nothing and forwards runtime props to initOtel as the env map
@$t/test_safe_error_message_ssot.py
safe-error-ssot.1||test_AC_safe_error_ssot_1_single_sanitizer_definition
@$be/extraction/test_parse_failure_redaction.py
safe-error-ssot.2||test_AC_safe_error_ssot_2_handle_parse_failure_redacts_pii
""",
    ),
    concepts=concepts(
        """
observability_logging|common/observability/observability.md|Structured logging, OTLP export configuration.|common/meta/development.md|-|observability|concept
statement_parsing_model_selection_logging|common/observability/observability-logging.md|Statement parsing model-selection and staging audit replay logging contract.|common/observability/observability.md,common/extraction/readme.md,common/llm/ai.md,docs/project/EPIC-010.observability-logging.md,apps/backend/tests/api/test_statements_router.py,apps/backend/tests/extraction/test_statement_parsing_audit_logging.py,apps/backend/tests/reconciliation/test_reconciliation_router_additional.py,tests/tooling/test_post_merge_e2e_gates.py,runtime-hooks.manifest.json|-|observability|playbook|documented_contract|observability_logging
"""
    ),
)
