"""The ``observability`` package's machine-checkable :class:`PackageContract`.

``observability`` owns two cohesive surfaces. Its **BE implementation**
(``apps/backend/src/observability``) publishes the backend's observability
language: the vendor-neutral OpenTelemetry runtime contract plus the shared
structured audit/security logging helpers (PII + secret redaction) — this is the
home #1428 relocates the shared logging helpers into. The stdlib OpenPanel query
CLI (``openpanel_query``) stays here in ``common/observability`` as a triage tool
run via ``tools/`` wrappers (its invariant is pinned below).

``depends_on=["config"]``: the OTEL runtime reads the backend config singleton via
its bare published root (``import src.config``), the one registered-package edge it
declares (a same-class ``kernel`` -> ``kernel`` edge, acyclic). The formerly flat
``src.logger`` / ``src.telemetry_metrics`` / ``src.analytics`` modules and the
``ErrorIds`` vocabulary now live inside this package; its one remaining import of
unregistered backend infrastructure is ``src.services.pii_redaction``.
"""

from __future__ import annotations

from common.meta.package_contract import ACRecord, Invariant, PackageContract

CONTRACT = PackageContract(
    name="observability",
    klass="kernel",
    status="active",
    tier="CODE-ONLY",
    depends_on=["config"],
    implementations={"be": "apps/backend/src/observability", "fe": None},
    interface=[
        "INVARIANT_VIOLATION_KINDS",
        "ErrorIds",
        "configure_database_pool_metrics",
        "configure_logging",
        "configure_otel_metrics",
        "current_request_id",
        "get_logger",
        "get_observability_status",
        "http_route_label_from_scope",
        "is_fastapi_instrumentation_active",
        "is_metrics_export_active",
        "log_financial_mutation",
        "log_observability_startup",
        "log_security_warning",
        "mark_fastapi_instrumentation_active",
        "record_ai_provider_call",
        "record_financial_invariant_violation",
        "record_http_request",
        "record_rate_limit_rejected",
        "record_reconciliation_match_outcome",
        "record_statement_parse_outcome",
        "run_with_async_parse_tracking",
        "safe_error_message",
        "safe_log_fields",
        "track",
    ],
    events=[],
    invariants=[
        Invariant(
            id="api-key-from-env-not-argv",
            statement="The OpenPanel query CLI reads its API key from the environment, never from command-line args (no secret in argv).",
            test="tests/tooling/test_openpanel_query.py::test_AC23_1_4_api_key_read_from_env_not_args",
        ),
    ],
    roadmap=[
        # AC roadmap — EPIC-010 (observability-logging) backend ACs homed here.
        # Migrated from the EPIC-010 table (#1524 follow-up): the leading "10" is
        # dropped and the group/seq preserved, so AC10.<g>.<s> becomes
        # AC-observability.<g>.<s> (numeric AC-<pkg>.<n>.<n> grammar). Only the
        # backend observability runtime/logging/metrics/redaction/audit ACs are
        # homed; the EPIC-010 doc/SSOT-linkage rows (AC10.5.1-5.3, 7.5), the
        # infra2 deploy-template rows (AC10.6.*, 7.6), and the Dokploy deploy-
        # tooling row (AC10.9.5) stay defined in EPIC-010 (cross-cutting infra
        # governance, not backend observability). Each test= resolves to a real
        # path::func anchor that proves the statement.
        # ── group 1: Backend logging configuration (was EPIC-010 AC10.1.*) ──
        ACRecord(
            id="AC-observability.1.1",
            statement=(
                "OTEL settings are explicit, environment-backed config fields owned "
                "by the backend config singleton. Was EPIC-010 AC10.1.1."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_otel_settings_are_explicit_and_environment_backed"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.1.2",
            statement=(
                "Optional OTLP log export is configured through an OTLP exporter "
                "when an endpoint is set. Was EPIC-010 AC10.1.2."
            ),
            test=(
                "apps/backend/tests/infra/test_logger.py"
                "::test_configure_otel_logging_with_fake_exporter"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-observability.1.3",
            statement=(
                "Logging falls back to a structured stdout JSON renderer when OTEL "
                "vars are absent. Was EPIC-010 AC10.1.3."
            ),
            test=(
                "apps/backend/tests/infra/test_logger.py"
                "::test_select_renderer_uses_json_in_production"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 2: OTLP endpoint construction (was EPIC-010 AC10.2.*) ──
        ACRecord(
            id="AC-observability.2.2",
            statement=(
                "Building the OTLP logs endpoint preserves an explicit /v1/logs "
                "path. Was EPIC-010 AC10.2.2."
            ),
            test=(
                "apps/backend/tests/infra/test_logger.py"
                "::test_build_otlp_logs_endpoint_preserves_logs_path"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 4: OTEL configuration & error handling (was EPIC-010 AC10.4.*) ──
        ACRecord(
            id="AC-observability.4.1",
            statement=(
                "Configuring OTEL logging warns (and stays no-op) when the "
                "opentelemetry dependency is missing. Was EPIC-010 AC10.4.1."
            ),
            test=(
                "apps/backend/tests/infra/test_logger.py"
                "::test_configure_otel_logging_missing_dependency_warns"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.4.2",
            statement=(
                "Configuring OTEL logging wires the OTLP exporter, resource, and "
                "handler when the endpoint is set. Was EPIC-010 AC10.4.2."
            ),
            test=(
                "apps/backend/tests/infra/test_logger.py"
                "::test_configure_otel_logging_with_fake_exporter"
            ),
            priority="P1",
            status="done",
        ),
        ACRecord(
            id="AC-observability.4.3",
            statement=(
                "FastAPI request instrumentation binds the running app instance "
                "(not the no-op classmethod). Was EPIC-010 AC10.4.3."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC10_4_3_main_instruments_fastapi_app_instance"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.4.4",
            statement=(
                "The OTEL resource carries the deploy commit for run-to-trace "
                "correlation. Was EPIC-010 AC10.4.4."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC10_4_4_otel_resource_includes_commit_version"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 5: OTEL config ownership (was the backend-config row AC10.5.4; doc-linkage AC10.5.1-5.3 stay in EPIC-010) ──
        ACRecord(
            id="AC-observability.5.4",
            statement=(
                "OTEL settings are documented as explicit backend config fields in "
                "config.py. Was EPIC-010 AC10.5.4."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_otel_settings_are_explicit_and_environment_backed"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 7: Must-have runtime traceability (was the runtime rows of AC10.7.*; doc/infra rows 7.5/7.6 stay in EPIC-010) ──
        ACRecord(
            id="AC-observability.7.1",
            statement=(
                "The backend starts without an observability backend (missing OTEL "
                "endpoint keeps the startup path local). Was EPIC-010 AC10.7.1."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_backend_otel_absence_is_startup_safe"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.7.2",
            statement=(
                "Logs export over OTLP through the configured exporter. Was "
                "EPIC-010 AC10.7.2."
            ),
            test=(
                "apps/backend/tests/infra/test_logger.py"
                "::test_configure_otel_logging_with_fake_exporter"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.7.3",
            statement=(
                "No sensitive data appears in logs (external API logging omits "
                "credentials by default). Was EPIC-010 AC10.7.3."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_external_api_logging_omits_sensitive_arguments_by_default"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.7.4",
            statement=(
                "OTLP export is optional by default (no endpoint keeps the local "
                "path). Was EPIC-010 AC10.7.4."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_backend_otel_absence_is_startup_safe"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.7.7",
            statement=(
                "Non-debug mode emits structured, parseable JSON logs. Was EPIC-010 "
                "AC10.7.7."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_production_renderer_outputs_structured_json"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 8: Staging audit replay logging (was EPIC-010 AC10.8.*) ──
        ACRecord(
            id="AC-observability.8.1",
            statement=(
                "Statement upload audit logs include non-sensitive input "
                "provenance, correlation IDs, and storage failure context. Was "
                "EPIC-010 AC10.8.1."
            ),
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC10_8_1_upload_audit_logs_include_statement_input_provenance"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.8.2",
            statement=(
                "Async statement parsing emits structured 5/10/20/70/80/90/100 "
                "checkpoints and safe failure context. Was EPIC-010 AC10.8.2."
            ),
            test=(
                "apps/backend/tests/extraction/test_statement_parsing_audit_logging.py"
                "::test_AC10_8_2_parse_checkpoints_and_failure_logs_are_structured"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.8.3",
            statement=(
                "Brokerage import and reconciliation emit start/complete/failure "
                "audit checkpoints with result counts. Was EPIC-010 AC10.8.3."
            ),
            test=(
                "apps/backend/tests/api/test_statements_router.py"
                "::test_AC10_8_3_statement_scoped_brokerage_import_audit_logs"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.8.4",
            statement=(
                "High-volume staging audit noise is reduced for SQL echo and "
                "repeated FX/portfolio valuation detail logs. Was EPIC-010 "
                "AC10.8.4."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC10_8_4_high_volume_fx_audit_noise_uses_debug_level"
            ),
            priority="P1",
            status="done",
        ),
        # ── group 9: Production observability runtime contract (was the app-owned rows of AC10.9.*; deploy-tooling AC10.9.5 stays in EPIC-010) ──
        ACRecord(
            id="AC-observability.9.1",
            statement=(
                "The backend exposes a stable redacted, vendor-neutral OTEL "
                "observability status (service name, deployment environment, "
                "resource attributes, exporter flags) without exposing the OTLP "
                "endpoint or any backend-specific alert metadata. Was EPIC-010 "
                "AC10.9.1."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC10_9_1_observability_status_is_redacted_and_vendor_neutral"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.9.2",
            statement=(
                "Startup logs emit one structured observability runtime event "
                "capturing OTEL runtime readiness. Was EPIC-010 AC10.9.2."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC10_9_2_observability_startup_log_uses_runtime_contract"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.9.3",
            statement=(
                "/health includes the same redacted observability status so deploy "
                "checks can prove app-side OTEL readiness. Was EPIC-010 AC10.9.3."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC10_9_3_health_response_includes_redacted_observability_status"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 10: Backend OTEL metrics pillar (was EPIC-010 AC10.10.*) ──
        ACRecord(
            id="AC-observability.10.1",
            statement=(
                "The MeterProvider and OTLP metric exporter are endpoint-gated and "
                "no-op safe when unset. Was EPIC-010 AC10.10.1."
            ),
            test=(
                "apps/backend/tests/infra/test_telemetry_metrics.py"
                "::test_AC10_10_1_configure_metrics_is_noop_without_endpoint"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.10.2",
            statement=(
                "RED request-count and request-duration metrics use low-cardinality "
                "route/status labels. Was EPIC-010 AC10.10.2."
            ),
            test=(
                "apps/backend/tests/infra/test_telemetry_metrics.py"
                "::test_AC10_10_2_red_metrics_record_low_cardinality_labels"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.10.3",
            statement=(
                "DB pool and async parse in-flight gauges expose current saturation "
                "values. Was EPIC-010 AC10.10.3."
            ),
            test=(
                "apps/backend/tests/infra/test_telemetry_metrics.py"
                "::test_AC10_10_3_saturation_gauges_observe_current_values"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.10.4",
            statement=(
                "Business metric helpers cover parse, AI-provider, reconciliation, "
                "and confidence signals and are emitted from their production call- "
                "sites (parse completion success + failure, the AI provider stream "
                "latency + outcome, and reconciliation match resolution) through "
                "the real code path with low-cardinality labels only. Was EPIC-010 "
                "AC10.10.4."
            ),
            test=(
                "apps/backend/tests/infra/test_telemetry_metrics.py"
                "::test_AC10_10_4_business_metric_helpers_record_outcomes"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 11: Logging content hardening (was EPIC-010 AC10.11.*) ──
        ACRecord(
            id="AC-observability.11.1",
            statement=(
                "Authenticated requests bind user_id into structured log context, "
                "and authentication/rate-limit failures emit warning events plus "
                "the rate-limit rejection metric without credentials. Was EPIC-010 "
                "AC10.11.1."
            ),
            test=(
                "apps/backend/tests/identity/test_auth.py"
                "::test_AC10_11_1_get_current_user_id_binds_user_context"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.11.2",
            statement=(
                "Financial mutations emit stable audit logs for journal post/void "
                "and reconciliation accept operations. Was EPIC-010 AC10.11.2."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC10_11_2_financial_mutation_audit_helpers_and_callsites"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.11.3",
            statement=(
                "Provider/error-body logging uses bounded safe summaries and "
                "rejects raw risky payload fields. Was EPIC-010 AC10.11.3."
            ),
            test=(
                "apps/backend/tests/infra/test_observability_contract.py"
                "::test_AC10_11_3_provider_error_body_logging_is_redacted"
            ),
            priority="P0",
            status="done",
        ),
        # ── group 12: Async parse failure visibility (was EPIC-010 AC10.12.*) ──
        ACRecord(
            id="AC-observability.12.1",
            statement=(
                "Failed async statement parse tasks emit a low-cardinality failure "
                "metric and safe structured log context. Was EPIC-010 AC10.12.1."
            ),
            test=(
                "apps/backend/tests/infra/test_telemetry_metrics.py"
                "::test_AC10_12_1_async_parse_tracking_records_failures"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.12.2",
            statement=(
                "In-process fallback and Prefect flow wrappers pass "
                "statement/request context into async parse tracking. Was EPIC-010 "
                "AC10.12.2."
            ),
            test=(
                "apps/backend/tests/infra/test_telemetry_metrics.py"
                "::test_AC10_12_2_async_parse_tracking_receives_statement_context"
            ),
            priority="P0",
            status="done",
        ),
        ACRecord(
            id="AC-observability.12.3",
            statement=(
                "Parse failure handling still marks statements rejected and emits "
                "the existing safe statement.parse.failed contract. Was EPIC-010 "
                "AC10.12.3."
            ),
            test=(
                "apps/backend/tests/infra/test_telemetry_metrics.py"
                "::test_AC10_12_3_parse_failure_state_and_log_contract_are_preserved"
            ),
            priority="P0",
            status="done",
        ),
    ],
)
