"""Machine-checkable PackageContract for ``observability``."""

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
@$be/infra/test_observability_contract.py|P0
1.1|OTEL settings are explicit, environment-backed config fields owned by the backend config singleton.|test_otel_settings_are_explicit_and_environment_backed
4.3|FastAPI request instrumentation binds the running app instance.|test_AC10_4_3_main_instruments_fastapi_app_instance
4.4|The OTEL resource carries the deploy commit for run-to-trace correlation.|test_AC10_4_4_otel_resource_includes_commit_version
5.4|OTEL settings are documented as explicit backend config fields in config.py.|test_otel_settings_are_explicit_and_environment_backed
7.1|The backend starts without an observability backend.|test_backend_otel_absence_is_startup_safe
7.3|No sensitive data appears in logs.|test_AC10_11_1_security_warning_redacts_credentials
7.4|OTLP export is optional by default.|test_backend_otel_absence_is_startup_safe
7.7|Non-debug mode emits structured, parseable JSON logs.|test_production_renderer_outputs_structured_json
8.4|High-volume staging audit noise is reduced for SQL echo and repeated FX/portfolio valuation detail logs.|test_AC10_8_4_high_volume_fx_audit_noise_uses_debug_level|P1
9.1|The backend exposes a stable redacted, vendor-neutral OTEL observability status.|test_AC10_9_1_observability_status_is_redacted_and_vendor_neutral
9.2|Startup logs emit one structured observability runtime event capturing OTEL runtime readiness.|test_AC10_9_2_observability_startup_log_uses_runtime_contract
9.3|/health includes the same redacted observability status.|test_AC10_9_3_health_response_includes_redacted_observability_status
11.2|Financial mutations emit stable audit logs for journal post/void and reconciliation accept operations.|test_AC10_11_2_financial_mutation_audit_helpers_and_callsites
11.3|Provider/error-body logging uses bounded safe summaries and rejects raw risky payload fields.|test_AC10_11_3_provider_error_body_logging_is_redacted
17.1|Common/observability/observability.md exists as the observability SSOT page.|test_observability_ssot_and_env_docs_are_linked
17.2|Common/observability/observability.md is anchored as the concept owner in common/meta/data/MANIFEST.yaml.|test_observability_ssot_and_env_docs_are_linked
17.3|The three OTEL environment variables are documented in .env.example.|test_observability_ssot_and_env_docs_are_linked
17.4|The three OTEL environment variables are documented in common/observability/observability.md alongside the SSOT page.|test_observability_ssot_and_env_docs_are_linked
6.1|OTEL keys are present in the versioned required-env artifact.|test_required_env_manifest_exports_observability_contract|P1
6.2|OTEL keys are documented in the generated app env reference.|test_required_env_manifest_exports_observability_contract|P1
6.3|The app publishes its deploy-time env requirements.|test_required_env_manifest_exports_observability_contract|P1
6.4|Vault-owned observability fields are marked explicitly in required-env.|test_required_env_manifest_exports_observability_contract|P1
@$be/infra/test_logger.py|P0
1.2|Optional OTLP log export is configured.|test_configure_otel_logging_with_fake_exporter|P1
1.3|Logging falls back to a structured stdout JSON renderer.|test_select_renderer_uses_json_in_production
2.2|Building the OTLP logs endpoint preserves an explicit /v1/logs path.|test_build_otlp_logs_endpoint_preserves_logs_path
4.1|Configuring OTEL logging warns.|test_configure_otel_logging_missing_dependency_warns
4.2|Configuring OTEL logging wires the OTLP exporter, resource.|test_configure_otel_logging_with_fake_exporter|P1
7.2|Logs export over OTLP through the configured exporter.|test_configure_otel_logging_with_fake_exporter
1.4|In debug mode, _select_renderer returns structlog's ConsoleRenderer for human-readable local output.|test_select_renderer_uses_console_in_debug
1.5|Configure_logging wires a working structlog configuration in debug mode.|test_configure_logging_basic
1.6|Configure_logging wires a working structlog configuration in production mode.|test_configure_logging_production_mode
2.1|Building the OTLP logs endpoint appends /v1/logs.|test_build_otlp_logs_endpoint_adds_suffix|P1
4.5|Configuring OTEL tracing warns.|test_configure_otel_tracing_missing_dependency_warns
4.6|Configuring OTEL logging returns early.|test_configure_otel_logging_no_endpoint
4.7|Building the OTEL resource sets service.name from the configured OTEL service name and merges additional key=value pairs parsed from OTEL_RESOURCE_ATTRIBUTES into the resource attributes.|test_build_otel_resource
4.8|Configuring OTEL tracing returns early.|test_configure_otel_tracing_no_endpoint
4.9|Configuring OTEL tracing wires a TracerProvider carrying the resource and registers a batch span processor pointed at the OTLP span exporter.|test_configure_otel_tracing_with_fake_exporter
4.10|Configuring OTEL tracing appends /v1/traces to the configured OTLP endpoint.|test_configure_otel_tracing_appends_traces_path
16.1|_build_processors returns a list of at least five structlog processors.|test_build_processors_returns_list
16.2|The trace-context processor injects hex-formatted trace_id and span_id into the event dict.|test_add_trace_context_with_valid_span
16.3|The trace-context processor leaves trace_id/span_id out of the event dict.|test_add_trace_context_with_invalid_span
16.4|The trace-context processor returns the event dict unchanged.|test_add_trace_context_handles_import_error
@$be/api/test_statements_router.py|P0
8.1|Statement upload audit logs include non-sensitive input provenance, correlation IDs.|test_AC10_8_1_upload_audit_logs_include_statement_input_provenance
8.3|Brokerage import and reconciliation emit start/complete/failure audit checkpoints with result counts.|test_AC10_8_3_statement_scoped_brokerage_import_audit_logs
@$be/extraction/test_statement_parsing_audit_logging.py|P0
8.2|Async statement parsing emits structured 5/10/20/70/80/90/100 checkpoints and safe failure context.|test_AC10_8_2_parse_checkpoints_and_failure_logs_are_structured
11.4|Telemetry↔alerting ownership contract.|test_AC_observability_11_4_expected_parse_failure_never_logs_at_error
@$be/infra/test_telemetry_metrics.py|P0
10.1|The MeterProvider and OTLP metric exporter are endpoint-gated and no-op safe.|test_AC10_10_1_configure_metrics_is_noop_without_endpoint
10.2|RED request-count and request-duration metrics use low-cardinality route/status labels.|test_AC10_10_2_red_metrics_record_low_cardinality_labels
10.3|DB pool and async parse in-flight gauges expose current saturation values.|test_AC10_10_3_saturation_gauges_observe_current_values
10.4|Business metric helpers cover parse, AI-provider.|test_AC10_10_4_business_metric_helpers_record_outcomes
12.1|Failed async statement parse tasks emit a low-cardinality failure metric and safe structured log context.|test_AC10_12_1_async_parse_tracking_records_failures
12.2|In-process fallback and Prefect flow wrappers pass statement/request context into async parse tracking.|test_AC10_12_2_async_parse_tracking_receives_statement_context
12.3|Parse failure handling rejects invalid sources, retains identity ambiguity for human review.|test_AC10_12_3_parse_failure_state_and_log_contract_are_preserved
@$fe/__tests__/otel.test.ts|P1
fe-telemetry.2|The PII scrub strips query strings and fragments from captured URLs and drops sensitive attributes.|AC24.1.2 strips query string and fragment from an absolute URL
fe-telemetry.3|Uncaught errors and unhandled promise rejections are captured as span exceptions with a scrubbed page URL.|AC24.1.3 keeps the error type but redacts the message/stack
@$fe/__tests__/telemetryEmission.test.ts|P1
fe-telemetry.4|With the OTLP endpoint configured, the real browser OTel exporter emits a span.|emits a finished browser OTel span to the real OTLP exporter's export() (AC24.2.1)
fe-telemetry.5|With the OpenPanel client id configured, the analytics layer actually dispatches an OpenPanel event/page-view (`window.op` invoked).|dispatches an OpenPanel event via window.op when configured (AC24.2.2)
@$be/infra/test_request_log_probe_filter.py|P0
19.1|A 2xx request to a liveness or readiness probe path writes no `HTTP Request` log line.|test_AC_observability_19_1_successful_health_probe_writes_no_request_log_line
19.2|A failed probe request still writes its log line.|test_AC_observability_19_2_failed_health_probe_still_writes_request_log_line
19.3|A request to a non-probe path keeps its `HTTP Request` line with the same event name and fields.|test_AC_observability_19_3_non_probe_request_keeps_its_request_log_line
@-|P1
11.1|Authenticated requests bind user_id into structured log context.|$be/identity/test_auth.py::test_AC10_11_1_get_current_user_id_binds_user_context|P0
12.4|A Prefect flow-run process configures OTEL metrics, logs and traces under its own service name and flushes them.|$be/infra/test_worker_telemetry.py::test_flow_run_exports_parse_outcome_point_before_exit
18.1|Financial-invariant violations emit a WARNING-level structured log plus a finance.invariant.violation counter labelled by kind and an anonymized institution_class, independent of routing.|$be/extraction/test_invariant_observability.py::test_AC26_8_1_balance_invalid_parse_quarantines_and_emits_metric|P0:property
9.4|Deploy failure snapshots are infra2-owned end to end.|$t/test_env_contract_boundary.py::test_AC10_9_5_app_side_snapshot_is_retired|P0:property
openpanel-query.1|The OpenPanel query CLI exists, reads its API key from OPENPANEL_API_KEY.|$t/test_openpanel_query.py::test_AC23_1_4_api_key_read_from_env_not_args
fe-ia-analytics.1|A typed `track` analytics wrapper dispatches.|$fe/__tests__/analyticsTrack.test.ts::AC22.18.2 exposes a typed taxonomy of at least six named product events
fe-ia-analytics.2|The core product funnel is instrumented.|$fe/__tests__/StatementUploader.test.tsx::AC22.18.3 tracks UPLOAD_STARTED and UPLOAD_SUCCEEDED with non-PII props on success
fe-telemetry.1|The browser OTel module is config-gated, non-blocking, idempotent.|$fe/__tests__/frontendTelemetry.test.tsx::AC24.1.1 renders nothing and forwards runtime props to initOtel as the env map
safe-error-ssot.1|Exactly one error-text sanitizer exists.|$t/test_safe_error_message_ssot.py::test_AC_safe_error_ssot_1_single_sanitizer_definition|P0
safe-error-ssot.2|Parse-failure text is PII-redacted and bounded.|$be/extraction/test_parse_failure_redaction.py::test_AC_safe_error_ssot_2_handle_parse_failure_redacts_pii|P0
""",
    ),
    concepts=concepts(
        """
observability_logging|common/observability/observability.md|Structured logging, OTLP export configuration.|common/meta/development.md|-|observability|concept
statement_parsing_model_selection_logging|common/observability/observability-logging.md|Statement parsing model-selection and staging audit replay logging contract.|common/observability/observability.md,common/extraction/readme.md,common/llm/ai.md,docs/project/EPIC-010.observability-logging.md,apps/backend/tests/api/test_statements_router.py,apps/backend/tests/extraction/test_statement_parsing_audit_logging.py,apps/backend/tests/reconciliation/test_reconciliation_router_additional.py,tests/tooling/test_post_merge_e2e_gates.py,runtime-hooks.manifest.json|-|observability|playbook|documented_contract|observability_logging
"""
    ),
)
