# EPIC-012: Foundation Libraries Enhancement

> **Goal**: Strengthen core infrastructure libraries to production-grade quality with proper observability, transaction management, and developer experience.

**Status**: 🟡 In Progress  
**Vision Anchor**: `decision-7-tech-stack`  
**Priority**: P1 (Infrastructure Debt)  
**Estimated Duration**: 2-3 weeks  
**Dependencies**: None (cross-cutting infrastructure)

---

## 📋 Overview

This EPIC addresses technical debt in the foundational libraries that all modules depend on. A comprehensive audit identified gaps in:

1. **Observability** - Tracing, log-trace correlation, metrics
2. **Database** - Transaction boundaries, connection pooling
3. **Error Handling** - Unified exception hierarchy
4. **Rate Limiting** - API-wide protection
5. **Developer Experience** - Debugging tools, schema consistency

---

## 🎯 Success Criteria

### Must Have (P0)
- [x] Distributed tracing with trace_id in all logs
- [ ] Service-layer uses `flush()`, router-layer owns `commit()`
  - See: `docs/ssot/accounting.md#async-tx-boundary`
- [x] Connection pool size configurable via environment

### Should Have (P1)
- [x] Unified `BaseAppException` with error IDs
- [x] API-wide rate limiting (not just auth endpoints)
- [~] Metrics endpoint — deferred: project uses SigNoz OTLP, not Prometheus pull scraping (see EPIC-010)

### Nice to Have (P2)
- [ ] UUID auto-serialization structlog processor (P2 backlog, AC12.25.1)

---

## 📁 Affected Components

| Component | File(s) | Changes |
|-----------|---------|---------|
| Logging | `src/logger.py` | Add tracing, trace_id processor |
| Database | `src/database.py`, `src/config.py` | Pool config, transaction patterns |
| Exceptions | `src/utils/exceptions.py` | BaseAppException class |
| Rate Limiting | `src/rate_limit.py` | Global API limiter |
| Debugging | `tools/debug.py` | SigNoz API integration |
| Schemas | `src/schemas/*.py` | Consistent BaseResponse inheritance |

---

## 🔴 High Priority Issues

### H1: Distributed Tracing Missing
**Problem**: No `opentelemetry-instrumentation-*` packages installed. Logs lack `trace_id`/`span_id`, making it impossible to correlate logs with traces in SigNoz.

**Solution**:
1. Add OTEL instrumentation packages to `pyproject.toml`
2. Initialize TracerProvider in `logger.py`
3. Add structlog processor to inject trace context
4. Auto-instrument FastAPI, SQLAlchemy, and HTTPX

**Status**: ✅ Complete (PR pending)

**Tracking**: [#181](https://github.com/wangzitian0/finance_report/issues/181)

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using AC12.x.y numbering.
> **Coverage**: See `apps/backend/tests/infra/`

### AC12.1: Logging - OTEL Endpoint Configuration

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.1.1 | OTEL logs endpoint adds suffix /v1/logs | `test_build_otlp_logs_endpoint_adds_suffix()` | `infra/test_logger.py` | P1 |
| AC12.1.2 | OTEL logs endpoint preserves logs path with /v1/logs | `test_build_otlp_logs_endpoint_preserves_logs_path()` | `infra/test_logger.py` | P1 |

### AC12.2: Logging - Renderer Selection

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.2.1 | Debug mode uses ConsoleRenderer | `test_select_renderer_uses_console_in_debug()` | `infra/test_logger.py` | P0 |
| AC12.2.2 | Production mode uses JSONRenderer | `test_select_renderer_uses_json_in_production()` | `infra/test_logger.py` | P0 |

### AC12.3: Logging - OTEL Missing Dependency / No Endpoint

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.3.1 | OTEL logging not available logs warning | `test_configure_otel_logging_missing_dependency_warns()` | `infra/test_logger.py` | P0 |
| AC12.3.2 | OTEL tracing not available logs warning | `test_configure_otel_tracing_missing_dependency_warns()` | `infra/test_logger.py` | P0 |
| AC12.3.3 | OTEL logging with no endpoint skips setup | `test_configure_otel_logging_no_endpoint()` | `infra/test_logger.py` | P0 |

### AC12.4: Logging - OTEL with Fake Exporter

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.4.1 | OTEL configuration sets up TracerProvider correctly | `test_configure_otel_tracing_with_fake_exporter()` | `infra/test_logger.py` | P0 |

### AC12.5: Logging - OTEL Resource Configuration

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.5.1 | OTEL resource created with correct attributes | `test_build_otel_resource()` | `infra/test_logger.py` | P0 |

### AC12.6: Logging - Timing Utilities

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.6.1 | Sync log_timing logs operation with timing | `test_log_timing_basic()` | `infra/test_logger.py` | P0 |
| AC12.6.2 | Async log_timing includes additional context | `test_log_timing_with_context()` | `infra/test_logger.py` | P0 |
| AC12.6.3 | log_timing yields mutable dict | `test_log_timing_yields_mutable_dict()` | `infra/test_logger.py` | P0 |
| AC12.6.4 | log_timing with custom level | `test_log_timing_with_custom_level()` | `infra/test_logger.py` | P0 |

### AC12.7: Logging - External API Logging

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.7.1 | Sync external API call logs success | `test_log_external_api_sync_success()` | `infra/test_logger.py` | P0 |
| AC12.7.2 | Sync external API call logs failure | `test_log_external_api_sync_failure()` | `infra/test_logger.py` | P0 |
| AC12.7.3 | Async external API call logs success | `test_log_external_api_async_success()` | `infra/test_logger.py` | P0 |
| AC12.7.4 | Async external API call logs failure | `test_log_external_api_async_failure()` | `infra/test_logger.py` | P0 |
| AC12.7.5 | Sync external API with log_args=True logs args count | `test_log_external_api_with_log_args()` | `infra/test_logger.py` | P0 |

### AC12.8: Logging - Exception Logging

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.8.1 | Log exception logs error with context | `test_log_exception_basic()` | `infra/test_logger.py` | P0 |
| AC12.8.2 | Log exception includes extra context fields | `test_log_exception_with_extra_context()` | `infra/test_logger.py` | P0 |
| AC12.8.3 | Log exception without traceback | `test_log_exception_without_traceback()` | `infra/test_logger.py` | P0 |
| AC12.8.4 | Log exception with custom level | `test_log_exception_custom_level()` | `infra/test_logger.py` | P0 |

### AC12.10: Logging - Build Processors

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.10.1 | Build processors returns list | `test_build_processors_returns_list()` | `infra/test_logger.py` | P0 |

### AC12.11: Logging - Trace Context

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.11.1 | Trace context injects trace_id and span_id when span is valid | `test_add_trace_context_with_valid_span()` | `infra/test_logger.py` | P0 |
| AC12.11.2 | Trace context skips injection when span context is invalid | `test_add_trace_context_with_invalid_span()` | `infra/test_logger.py` | P0 |
| AC12.11.3 | Trace context handles missing opentelemetry gracefully | `test_add_trace_context_handles_import_error()` | `infra/test_logger.py` | P0 |

### AC12.12: Logging - OTEL Tracing Configuration

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.12.1 | OTEL tracing skips setup when no endpoint configured | `test_configure_otel_tracing_no_endpoint()` | `infra/test_logger.py` | P0 |
| AC12.12.2 | TracerProvider created and resource attributes set | `test_configure_otel_tracing_with_fake_exporter()` | `infra/test_logger.py` | P0 |
| AC12.12.3 | Traces path appends /v1/traces | `test_configure_otel_tracing_appends_traces_path()` | `infra/test_logger.py` | P0 |

### AC12.15: Logging - Configuration Basics

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.15.1 | Configure logging in debug mode | `test_configure_logging_basic()` | `infra/test_logger.py` | P0 |
| AC12.15.2 | Configure logging in production mode | `test_configure_logging_production_mode()` | `infra/test_logger.py` | P0 |

### AC12.16: Logging - Async Timing

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.16.1 | Async log_timing logs operation with timing | `test_async_log_timing_basic()` | `infra/test_logger.py` | P0 |
| AC12.16.2 | Async log_timing includes additional context | `test_async_log_timing_with_context()` | `infra/test_logger.py` | P0 |

### AC12.17: Logging - External API Async with Args

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.17.1 | External API async with log_args=True logs args count | `test_log_external_api_async_with_log_args()` | `infra/test_logger.py` | P0 |
| AC12.17.2 | External API async failure with log_args=True logs args | `test_log_external_api_async_failure_with_log_args()` | `infra/test_logger.py` | P0 |

### AC12.18: Logging - Configuration - Environment Variables

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.18.1 | Ensure PRIMARY_MODEL follows expected pattern | `test_primary_model_format()` | `infra/test_config_contract.py` | P0 |
| AC12.18.2 | Ensure config.py default matches .env.example documentation | `test_config_sync_with_env_example()` | `infra/test_config_contract.py` | P0 |
| AC12.18.3 | Ensure BASE_CURRENCY is valid ISO 4217 currency code | `test_base_currency_format()` | `infra/test_config_contract.py` | P0 |
| AC12.18.4 | Ensure S3_BUCKET follows naming conventions | `test_s3_bucket_format()` | `infra/test_config_contract.py` | P0 |
| AC12.18.5 | Ensure JWT_ALGORITHM is secure algorithm | `test_jwt_algorithm_allowed()` | `infra/test_config_contract.py` | P0 |
| AC12.18.6 | Ensure DATABASE_URL follows expected format | `test_database_url_format()` | `infra/test_config_contract.py` | P0 |
| AC12.18.7 | stub | — | — | — |

### AC12.19: Infrastructure - Epic 001 Contracts

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.19.1 | Moon workspace configuration files exist | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` | P0 |

### AC12.20: Database - Connection Pool Configuration

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.20.1 | DB_POOL_SIZE config field exists with default | `test_db_pool_size_config_default()` | `infra/test_config_contract.py` | P1 |
| AC12.20.2 | DB_MAX_OVERFLOW config field exists with default | `test_db_max_overflow_config_default()` | `infra/test_config_contract.py` | P1 |
| AC12.20.3 | Pool config is positive integer | `test_db_pool_config_positive_integer()` | `infra/test_config_contract.py` | P1 |
| AC12.20.4 | Ensure DB_POOL_SIZE env var actually overrides the setting. | `test_db_pool_size_env_override` | `infra/test_config_contract.py` | P1 |
| AC12.20.5 | Ensure DB_POOL_MAX_OVERFLOW env var actually overrides the setting. | `test_db_pool_size_env_override` | `infra/test_config_contract.py` | P1 |

### AC12.21: Exceptions - BaseAppException

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.21.1 | BaseAppException has error_id attribute | `test_base_app_exception_has_error_id()` | `infra/test_exceptions.py` | P1 |
| AC12.21.2 | BaseAppException has status_code attribute | `test_base_app_exception_has_status_code()` | `infra/test_exceptions.py` | P1 |
| AC12.21.3 | BaseAppException is subclass of Exception | `test_base_app_exception_is_exception()` | `infra/test_exceptions.py` | P1 |
| AC12.21.4 | BaseAppException can be raised and caught | `test_base_app_exception_raise_and_catch()` | `infra/test_exceptions.py` | P1 |
| AC12.21.5 | BaseAppException handler serializes error_id and status_code into JSON response. | `test_base_app_exception_handler_returns_structured_json` | `infra/test_exceptions.py` | P1 |

## 📏 Acceptance Criteria

> ℹ️ **Non-contiguous AC numbering**: Gaps in `AC12.x.y` numbers reflect deprecated or merged ACs preserved through generated registry indexes plus explicit overrides (e.g., AC12.24.1-3 retained as `~~strikethrough~~`). Do **not** renumber. New ACs append to the next available index in this EPIC.

**Problem**: Services call `db.commit()` directly, making it impossible to compose multiple service calls into a single atomic transaction.

**Solution**:
1. Change services to use `db.flush()` for getting IDs
2. Move `commit()` responsibility to routers
3. Consider `@transactional` decorator for complex cases

**Tracking**: [#182](https://github.com/wangzitian0/finance_report/issues/182)

---

## 🟡 Medium Priority Issues

### M1: Connection Pool Configuration
**Problem**: Using SQLAlchemy defaults for connection pooling. Production may need tuning.

**Solution**: Add `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` to config.py

**Tracking**: [#184](https://github.com/wangzitian0/finance_report/issues/184)

### M2: Unified Exception Hierarchy
**Problem**: Each service defines its own exception class. No unified `BaseAppException` with error IDs for frontend consumption.

**Solution**: Create base exception with `error_id` field, migrate services

**Tracking**: [#185](https://github.com/wangzitian0/finance_report/issues/185)

### M3: API-Wide Rate Limiting
**Problem**: Rate limiting only protects `/auth/*` endpoints. Other endpoints unprotected.

**Solution**: Add configurable global rate limiter middleware

**Tracking**: [#186](https://github.com/wangzitian0/finance_report/issues/186)

### M4: Metrics Endpoint
**Problem**: ~~No `/metrics` endpoint for Prometheus.~~ → Architecture uses SigNoz OTLP, not Prometheus pull.

**Solution**: ~~Add prometheus-fastapi-instrumentator~~ → **Deferred** (SigNoz OTLP is the observability path)

**Tracking**: [#187](https://github.com/wangzitian0/finance_report/issues/187)
> ⚠️ **Deferred**: This project uses SigNoz via OTLP (see EPIC-010) for observability.
> Prometheus pull-based `/metrics` has zero consumers in this architecture.
> Metrics via OTLP to SigNoz is a future task tracked separately.

---

## 🟢 Low Priority Issues

### L3: UUID Auto-Serialization
**Problem**: Must manually wrap UUIDs with `str()` in logger calls.

**Solution**: Add structlog processor to auto-convert UUIDs

### L4: Schema Inheritance Consistency
**Problem**: Not all response schemas inherit from `BaseResponse`.

**Solution**: Audit and fix schema inheritance

---

### AC12.22: Schemas - Move Inline Schemas to Dedicated Modules

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.22.1 | Move 6 inline schemas from statements router to review module | N/A (mechanical) | N/A | P0 |
| AC12.22.2 | Extract background task schemas from inline/background definitions into dedicated modules | N/A (mechanical) | N/A | P0 |

### AC12.23: Rate Limiting - Global API Middleware (M3)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.23.1 | Global rate limit middleware exempts /health | `test_global_rate_limit_middleware_exempts_health()` | `infra/test_rate_limit.py` | P1 |
| AC12.23.2 | Global rate limit middleware returns 429 after limit exceeded | `test_global_rate_limit_middleware_blocks_after_limit()` | `infra/test_rate_limit.py` | P1 |
| AC12.23.3 | Global rate limit middleware allows normal requests | `test_global_rate_limit_middleware_allows_normal_requests()` | `infra/test_rate_limit.py` | P1 |
| AC12.23.4 | Global rate limit middleware exempts /docs | `test_global_rate_limit_middleware_exempts_docs()` | `infra/test_rate_limit.py` | P1 |

### AC12.24: Metrics - Prometheus Endpoint (M4)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.24.1 | ~~`/metrics` endpoint returns 200 OK~~ | Removed | Deferred: SigNoz OTLP path, no Prometheus scrape config | P1 |
| AC12.24.2 | ~~`/metrics` endpoint returns text/plain~~ | Removed | Deferred: SigNoz OTLP path | P1 |
| AC12.24.3 | ~~`/metrics` response contains Prometheus data~~ | Removed | Deferred: SigNoz OTLP path | P1 |

### AC12.25: Logging Developer Experience - UUID Serialization

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.25.1 | UUID auto-serialization structlog processor remains EPIC-012 P2 backlog until implemented | `test_AC12_25_1_uuid_logging_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P2 |

### AC12.26: Transaction Boundary Ownership

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.26.1 | Service modules only call `commit()` in documented background-task or streaming-response transaction-boundary exceptions | `test_service_commit_calls_are_documented_boundary_exceptions` | `infra/test_transaction_boundaries.py` | P0 |
| AC12.26.2 | Market-data persistence helpers use `flush()` so router/report/scheduler boundaries can roll back or commit atomically | `test_market_data_fx_persistence_is_rollbackable_until_boundary_commit` | `infra/test_transaction_boundaries.py` | P0 |
| AC12.26.3 | Market-data HTTP sync endpoints finalize service writes at the router boundary | `test_market_data_sync_endpoint_commits_service_writes_at_router_boundary` | `infra/test_transaction_boundaries.py` | P0 |

## 📊 Progress Tracking

| Phase | Task | Status | PR |
|-------|------|--------|-----|
| 0 | Audit & Documentation | ✅ Complete | This EPIC |
| 1 | Distributed Tracing (H1) | ✅ Complete | Pending |
| 2 | Transaction Boundaries (H2) | ⏳ In progress | AC12.26 |
| 3 | Connection Pool Config (M1) | ✅ Complete | This PR |
| 4 | Exception Hierarchy (M2) | ✅ Complete | This PR |
| 5 | Rate Limiting (M3) | ✅ Complete | This PR |
| 6 | Metrics Endpoint (M4) | ❌ Deferred | Removed — SigNoz OTLP used instead of Prometheus pull |
| 7 | UUID Logging Serialization (L3) | ⏳ P2 Backlog | AC12.25.1 |

---

## 🔗 Related Documents

- [Observability SSOT](../ssot/observability.md)
- [Development Guide](../ssot/development.md)
- [EPIC-010: SigNoz Logging](./EPIC-010.signoz-logging.md)

---

## 🗄️ Archive Integration Notes

Useful foundation-library gaps from the removed `EPIC-ENCODING-SUMMARY.md`,
`EPIC-QA-Standardization.md`, and `QA_REPORT_20260121.md` archive snapshots are
consolidated here. The removed inventory is retained in
[#548](https://github.com/wangzitian0/finance_report/issues/548):

- Service transaction boundaries remain the main open architecture issue:
  service code should use `flush()` while routers own `commit()`. See H2 and
  issue #182.
- Environment variable lifecycle is guarded by config sync tests and
  `tools/check_env_keys.py`; archive prose about config drift is superseded by
  those checks and `docs/ssot/development.md`.
- Frontend API base URL normalization, schema enum naming, Alembic filename
  guardrails, and Decimal safety are current guardrail topics owned by tests and
  SSOT references, not standalone QA reports.
- Prometheus-style `/metrics` was reviewed and deferred because current
  observability flows through SigNoz OTLP.
- UUID auto-serialization for structlog is retained as EPIC-012 P2 backlog
  under AC12.25.1, not as archive-only prose.

---

## 📝 Audit Summary

### Current Foundation Libraries

| Library | File | Status |
|---------|------|--------|
| Logging | `src/logger.py` | ✅ Structlog + OTEL export |
| Config | `src/config.py` | ✅ Pydantic Settings |
| Database | `src/database.py` | ⚠️ Needs pool config |
| Storage | `src/services/storage.py` | ✅ S3/MinIO abstraction |
| Rate Limit | `src/rate_limit.py` | ⚠️ Auth-only |
| Dependencies | `src/deps.py` | ✅ DbSession, CurrentUserId |
| Boot | `src/boot.py` | ✅ Health checks |
| Debug | `tools/debug.py` | ⚠️ Needs SigNoz API |
| Error IDs | `src/constants/error_ids.py` | ✅ Centralized constants |

### Frontend Foundation

| Library | File | Status |
|---------|------|--------|
| API Client | `lib/api.ts` | ✅ Unified fetch wrapper |
| Auth | `lib/auth.ts` | ✅ Token management |
| Currency | `lib/currency.ts` | ✅ Decimal.js |
| Workspace | `hooks/useWorkspace.tsx` | ✅ Tab/sidebar state |

---

### AC12.27: Structured API Error Contract ([#1005](https://github.com/wangzitian0/finance_report/issues/1005))

Tier 2 of #1000. Every exception handler emits the shared `ErrorResponse`
(`error_id` + `detail` + `request_id`), the common 4xx/5xx contract is declared in
OpenAPI, and the frontend `apiFetch` throws a typed `ApiError` carrying `errorId` so
callers branch on a machine-readable code instead of matching `detail` text.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.27.1 | An HTTPException-derived 404 returns a structured body with `error_id` | `test_AC12_27_1_http_error_has_structured_error_id` | `api/test_typed_contract_sweep.py` | P1 |
| AC12.27.2 | OpenAPI declares `ErrorResponse` and references it for common 4xx | `test_AC12_27_2_openapi_declares_error_response_contract` | `api/test_typed_contract_sweep.py` | P1 |
| AC12.27.3 | Frontend `apiFetch` throws `ApiError` carrying the parsed `errorId` | `test_AC12_27_3_api_error_carries_error_id` | `__tests__/apiErrorStructured.test.ts` | P1 |

### AC12.28: Generated Frontend API Types from OpenAPI ([#1004](https://github.com/wangzitian0/finance_report/issues/1004))

Tier 2 of #1000. The backend OpenAPI schema generates a checked-in TypeScript
types module, and a staleness gate (`tools/generate_frontend_types.py --check`)
fails when the generated types drift from the live schema — enforcing the FE↔BE
contract at the boundary.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.28.1 | The generator emits the spec from the live OpenAPI schema | `test_AC12_28_1_generator_emits_types_from_openapi` | `tests/tooling/test_generate_openapi_spec.py` | P2 |
| AC12.28.2 | The `--check` staleness gate fails when the committed spec is stale | `test_AC12_28_2_staleness_gate_detects_drift` | `tests/tooling/test_generate_openapi_spec.py` | P2 |

---

*Planning snapshot captured: January 2026*
