# EPIC-010: SigNoz Logging Integration

> **Status**: ✅ Complete
> **Vision Anchor**: `decision-7-tech-stack`
> **Owner**: Platform / Backend
> **Phase**: 0
> **Duration**: 1 week
> **Dependencies**: EPIC-007 (Deployment)

---

## 🎯 Objective

Enable production-grade log observability via SigNoz (OTLP), while keeping local/development runs functional without a SigNoz deployment.

---

## 🧭 Plan (STAR)

### Situation
- **Anchor**: Deployment readiness (EPIC-007) and platform observability SSOT.
- **Gap**: Production should ship logs to SigNoz, but local/dev must remain simple.

### Tasks
- **Backend**: Add optional OTLP log export gated by config.
- **Docs**: Define observability SSOT and document env vars.
- **Infra**: Wire Vault templates for OTEL variables.
 - **Ops**: Ensure deployments can refresh Vault templates safely.

### Actions
1. Add OTEL config fields and update logging setup.
2. Add SSOT + `.env.example` documentation.
3. Update Vault templates/README in infra repo.
4. Add restart-safe wiring for Vault template updates.
5. Validate via tests and env consistency check.
6. Add staging audit replay events for statement upload, async parsing, brokerage import, and reconciliation.
7. Expose a redacted runtime observability contract for health checks, startup logs, and alert triage.

### Result
- Optional OTEL export implemented; local/dev remains stdout-only.
- Infra templates updated with safe quoting.
- Production containers restarted successfully.
- Log ingestion still requires a backend image rebuild.
- Finance Report app alerting follows `component -> OTEL -> SigNoz -> Lark`; shared SigNoz/Lark automation remains owned by infra2.

---

## ✅ Scope

- **Backend log shipping** via OTLP HTTP when configured.
- **Optional by default** in local/dev environments.
- **Vault-managed configuration** for staging/production.
- **App-owned runtime contract** for the `FinanceReportBackendErrorLogs` shared alert rule on `finance-report-backend`.

---

## ✅ Must Have

- Logs remain structured JSON in non-debug modes.
- OTEL export is **opt-in** and does not break app startup if SigNoz is unavailable.
- OTEL configuration is documented in SSOT and `.env.example`.
- Vault templates include OTEL keys for production.

---

## 🌟 Nice to Have

- Dashboard or saved view in SigNoz for backend logs.
- Additional domain-specific alerts beyond backend error logs.

---

## 📋 Task Checklist

### Backend
- [x] Add OTEL settings to `apps/backend/src/config.py`.
- [x] Configure optional OTLP log export in `apps/backend/src/logger.py`.
- [x] Keep fallback to stdout when OTEL vars are absent.

### Documentation (SSOT)
- [x] Add `docs/ssot/observability.md` and link in SSOT index.
- [x] Document OTEL vars in `.env.example`.

### Infrastructure
- [x] Add OTEL keys to `repo/finance_report/finance_report/10.app/secrets.ctmpl`.
- [x] Document OTEL keys in `repo/finance_report/finance_report/10.app/README.md`.
- [x] Provide Vault values for staging/production.
- [x] Add `IAC_CONFIG_HASH` to `repo/finance_report/finance_report/10.app/compose.yaml` for restart-safe updates.
- [x] Replace unsupported template helpers (`default`) with `printf`.

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/infra/test_logger.py`, `apps/backend/tests/infra/test_observability_contract.py`, and `docs/ssot/observability.md`

### AC10.1: Backend Logging Configuration

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.1.1 | OTEL settings in config | `test_otel_settings_are_explicit_and_environment_backed()` | `infra/test_observability_contract.py` | P0 |
| AC10.1.2 | Optional OTLP log export configured | `test_configure_otel_logging_with_fake_exporter()` | `infra/test_logger.py` | P0 |
| AC10.1.3 | Fallback to stdout when OTEL vars absent | `test_select_renderer_uses_json_in_production()` | `infra/test_logger.py` | P0 |

### AC10.2: OTLP Endpoint Construction
| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC10.2.2 | Build OTLP endpoint preserves logs path | `test_build_otlp_logs_endpoint_preserves_logs_path()` | `infra/test_logger.py` | P0 |
*(AC10.2.1 removed — canonical copy is AC12.1.1 in EPIC-012)*

### AC10.3: Renderer Selection

*(AC10.3.1 and AC10.3.2 removed — canonical copies are AC12.2.1 and AC12.2.2 in EPIC-012)*

### AC10.4: OTEL Configuration & Error Handling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC10.4.1 | Configure OTEL logging warns on missing dependency | `test_configure_otel_logging_missing_dependency_warns()` | `infra/test_logger.py` | P0 |
| AC10.4.2 | Configure OTEL logging with fake exporter | `test_configure_otel_logging_with_fake_exporter()` | `infra/test_logger.py` | P1 |
| AC10.4.3 | FastAPI request instrumentation binds the app instance (not the no-op classmethod) | `test_AC10_4_3_main_instruments_fastapi_app_instance()` | `infra/test_observability_contract.py` | P0 |
| AC10.4.4 | OTEL resource carries deploy commit for run-to-trace correlation | `test_AC10_4_4_otel_resource_includes_commit_version()` | `infra/test_observability_contract.py` | P0 |

### AC10.5: Documentation (SSOT)

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.5.1 | Observability SSOT exists | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.5.2 | SSOT linked in index | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.5.3 | OTEL vars documented in .env.example | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.5.4 | OTEL vars documented in config.py | `test_otel_settings_are_explicit_and_environment_backed()` | `infra/test_observability_contract.py` | P0 |

### AC10.6: Infrastructure Templates

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.6.1 | OTEL keys in app secrets template | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.2 | OTEL keys documented in app README | `test_app_readme_and_compose_document_observability_rollout()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.3 | IAC_CONFIG_HASH in compose.yaml | `test_app_readme_and_compose_document_observability_rollout()` | `infra/test_observability_contract.py` | P0 |
| AC10.6.4 | Template helpers use printf not default | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |

### AC10.7: Must-Have Acceptance Criteria Traceability

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.7.1 | Backend starts without SigNoz | `test_backend_otel_absence_is_startup_safe()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.2 | Logs export to SigNoz | `test_configure_otel_logging_with_fake_exporter()` | `infra/test_logger.py` | P0 |
| AC10.7.3 | No sensitive data in logs | `test_external_api_logging_omits_sensitive_arguments_by_default()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.4 | OTLP optional by default | `test_backend_otel_absence_is_startup_safe()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.5 | OTEL config documented | `test_observability_ssot_and_env_docs_are_linked()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.6 | Vault templates include OTEL keys | `test_vault_template_exposes_otel_keys_with_safe_quoting()` | `infra/test_observability_contract.py` | P0 |
| AC10.7.7 | Structured JSON logs in non-debug | `test_production_renderer_outputs_structured_json()` | `infra/test_observability_contract.py` | P0 |

### AC10.8: Staging Audit Replay Logging

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.8.1 | Statement upload audit logs include non-sensitive input provenance, correlation IDs, and storage failure context | `test_AC10_8_1_upload_audit_logs_include_statement_input_provenance()`, `test_AC10_8_1_upload_storage_failure_logs_safe_audit_context()` | `api/test_statements_router.py` | P0 |
| AC10.8.2 | Async statement parsing emits structured 5/10/20/70/80/90/100 checkpoints and safe failure context | `test_AC10_8_2_parse_checkpoints_and_failure_logs_are_structured()` | `extraction/test_statement_parsing_audit_logging.py` | P0 |
| AC10.8.3 | Brokerage import and reconciliation emit start/complete/failure audit checkpoints with result counts | `test_AC10_8_3_statement_scoped_brokerage_import_audit_logs()`, `test_AC10_8_3_brokerage_import_audit_checkpoints()`, `test_AC10_8_3_reconciliation_run_audit_checkpoints()` | `api/test_statements_router.py`, `extraction/test_statement_parsing_audit_logging.py`, `reconciliation/test_reconciliation_router_additional.py` | P0 |
| AC10.8.4 | High-volume staging audit noise is reduced for SQL echo and repeated FX/portfolio valuation detail logs | `test_AC10_8_4_high_volume_fx_audit_noise_uses_debug_level()` | `infra/test_observability_contract.py` | P1 |

### AC10.9: Production Alerting Runtime Contract

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC10.9.1 | Backend exposes a stable redacted observability status with service name, deployment environment, resource attributes, and shared alert metadata, without exposing OTLP endpoint or webhook secrets | `test_AC10_9_1_observability_status_is_redacted_and_alert_ready()` | `infra/test_observability_contract.py` | P0 |
| AC10.9.2 | Startup logs emit one structured observability runtime event for SigNoz/Lark alert triage | `test_AC10_9_2_observability_startup_log_uses_runtime_contract()` | `infra/test_observability_contract.py` | P0 |
| AC10.9.3 | `/health` includes the same redacted observability status so deploy checks can prove app-side alert readiness | `test_AC10_9_3_health_response_includes_redacted_observability_status()` | `infra/test_observability_contract.py` | P0 |
| AC10.9.4 | Finance Report docs declare the app-owned alerting contract while infra2 remains the shared SigNoz/Lark automation owner | `test_AC10_9_4_observability_docs_declare_shared_alerting_pipeline()` | `infra/test_observability_contract.py` | P0 |
| AC10.9.5 | Deploy failure snapshots and deploy contexts include non-secret platform health fields plus run-to-SigNoz log/trace query links | `test_AC10_9_5_snapshot_includes_platform_health_and_signoz_links()`, `test_AC10_9_5_main_missing_inputs_still_prints_signoz_links()` | `tests/tooling/test_dokploy_failure_snapshot.py` | P0 |

### AC10.10: Backend OTEL Metrics Pillar

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC10.10.1 | MeterProvider and OTLP metric exporter are endpoint-gated and no-op safe when unset | `test_AC10_10_1_configure_metrics_is_noop_without_endpoint()`, `test_AC10_10_1_configure_metrics_creates_otlp_provider()` | `infra/test_telemetry_metrics.py` | P0 |
| AC10.10.2 | RED request-count and request-duration metrics use low-cardinality route/status labels | `test_AC10_10_2_red_metrics_record_low_cardinality_labels()` | `infra/test_telemetry_metrics.py` | P0 |
| AC10.10.3 | DB pool and async parse in-flight gauges expose current saturation values | `test_AC10_10_3_saturation_gauges_observe_current_values()` | `infra/test_telemetry_metrics.py` | P0 |
| AC10.10.4 | Business metric helpers cover parse, AI-provider, reconciliation, and confidence signals | `test_AC10_10_4_business_metric_helpers_record_outcomes()` | `infra/test_telemetry_metrics.py` | P0 |

### AC10.11: Logging Content Hardening

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC10.11.1 | Authenticated requests bind `user_id` into structured log context and authentication/rate-limit failures emit warning events plus the rate-limit rejection metric without credentials | `test_AC10_11_1_get_current_user_id_binds_user_context()`, `test_AC10_11_1_security_warning_redacts_credentials()`, `test_AC10_11_1_rate_limit_rejections_record_alert_metric()` | `auth/test_auth.py`, `infra/test_observability_contract.py`, `infra/test_telemetry_metrics.py` | P0 |
| AC10.11.2 | Financial mutations emit stable audit logs for journal post/void and reconciliation accept operations | `test_AC10_11_2_financial_mutation_audit_helpers_and_callsites()` | `infra/test_observability_contract.py` | P0 |
| AC10.11.3 | Provider/error-body logging uses bounded safe summaries and rejects raw risky payload fields | `test_AC10_11_3_provider_error_body_logging_is_redacted()` | `infra/test_observability_contract.py` | P0 |

### AC10.12: Async Parse Failure Visibility

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC10.12.1 | Failed async statement parse tasks emit a low-cardinality failure metric and safe structured log context | `test_AC10_12_1_async_parse_tracking_records_failures()` | `infra/test_telemetry_metrics.py` | P0 |
| AC10.12.2 | In-process fallback and Prefect flow wrappers pass statement/request context into async parse tracking | `test_AC10_12_2_async_parse_tracking_receives_statement_context()` | `infra/test_telemetry_metrics.py` | P0 |
| AC10.12.3 | Parse failure handling still marks statements rejected and emits the existing safe `statement.parse.failed` contract | `test_AC10_12_3_parse_failure_state_and_log_contract_are_preserved()` | `infra/test_telemetry_metrics.py` | P0 |

## 📏 Acceptance Criteria

> ℹ️ **Non-contiguous AC numbering**: Gaps in `AC10.x.y` numbers reflect deprecated or merged ACs preserved through generated registry indexes plus explicit overrides. Do **not** renumber. New ACs append to the next available index in this EPIC.

### 🟢 Must Have

| Standard | Verification | Status |
|----------|--------------|--------|
| Backend starts without SigNoz | Run app with no OTEL vars | ✅ |
| Logs export to SigNoz | Set OTEL vars, logs visible in UI | ✅ |
| No sensitive data in logs | Review log payloads | ✅ |
| App alert path is declared | `component -> OTEL -> SigNoz -> Lark`, rule `FinanceReportBackendErrorLogs`, service `finance-report-backend` | ✅ |

### 🚫 Not Acceptable

- App fails to start when SigNoz is down.
- Logs contain secrets or PII.
- OTEL config is undocumented or not in Vault templates.
- App health exposes collector URLs, webhook URLs, bot secrets, or SigNoz API keys.

---

## ✅ Verification Evidence

- `moon run :test`
- `python tools/check_env_keys.py`
- `uv run invoke signoz.status`
- `uv run invoke signoz.shared.test-trace --service-name=finance-report-backend`
- `docker exec finance_report-backend python -c 'import opentelemetry'` (missing in prod image)

---

## 🔗 References

- SSOT Observability: [../ssot/observability.md](../ssot/observability.md)
- Platform Observability: `repo/docs/ssot/ops.observability.md`
- Deployment EPIC: `docs/project/EPIC-007.deployment.md`

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../ssot/observability.md](../ssot/observability.md) — platform observability rationale.
- [../ssot/observability-logging.md](../ssot/observability-logging.md) — structured logging and OTEL trace/log correlation.
