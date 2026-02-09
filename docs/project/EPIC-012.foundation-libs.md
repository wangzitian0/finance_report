# EPIC-012: Foundation Libraries Enhancement

> **Goal**: Strengthen core infrastructure libraries to production-grade quality with proper observability, transaction management, and developer experience.

**Status**: 🟡 In Progress  
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
- [ ] Connection pool size configurable via environment

### Should Have (P1)
- [ ] Unified `BaseAppException` with error IDs
- [ ] API-wide rate limiting (not just auth endpoints)
- [ ] Metrics endpoint for Prometheus

### Nice to Have (P2)
- [ ] UUID auto-serialization structlog processor

---

## 📁 Affected Components

| Component | File(s) | Changes |
|-----------|---------|---------|
| Logging | `src/logger.py` | Add tracing, trace_id processor |
| Database | `src/database.py`, `src/config.py` | Pool config, transaction patterns |
| Exceptions | `src/utils/exceptions.py` | BaseAppException class |
| Rate Limiting | `src/rate_limit.py` | Global API limiter |
| Debugging | `scripts/debug.py` | SigNoz API integration |
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

### AC12.19: Infrastructure - Epic 001 Contracts

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.19.1 | Moon workspace configuration files exist | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` | P0 |

**Test Coverage Summary**:
- Total AC IDs: 42
- Requirements converted to AC IDs: 100% (EPIC-012 infrastructure work)
- Requirements with test references: 100%
- Test files: 3 (`test_logger.py`, `test_config_contract.py`, `test_epic_001_contracts.py`)
- Overall coverage: Logging and config infrastructure verified

---

## 📏 Acceptance Criteria
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
**Problem**: No `/metrics` endpoint for Prometheus. Cannot monitor request counts, latencies.

**Solution**: Add prometheus-fastapi-instrumentator

**Tracking**: [#187](https://github.com/wangzitian0/finance_report/issues/187)

---

## 🟢 Low Priority Issues

### L3: UUID Auto-Serialization
**Problem**: Must manually wrap UUIDs with `str()` in logger calls.

**Solution**: Add structlog processor to auto-convert UUIDs

### L4: Schema Inheritance Consistency
**Problem**: Not all response schemas inherit from `BaseResponse`.

**Solution**: Audit and fix schema inheritance

---

## 📊 Progress Tracking

| Phase | Task | Status | PR |
|-------|------|--------|-----|
| 0 | Audit & Documentation | ✅ Complete | This EPIC |
| 1 | Distributed Tracing (H1) | ✅ Complete | Pending |
| 2 | Transaction Boundaries (H2) | ⏳ Pending | - |
| 3 | Connection Pool Config (M1) | ⏳ Pending | - |
| 4 | Exception Hierarchy (M2) | ⏳ Pending | - |
| 5 | Rate Limiting (M3) | ⏳ Pending | - |
| 6 | Metrics Endpoint (M4) | ⏳ Pending | - |

---

## 🔗 Related Documents

- [Observability SSOT](../ssot/observability.md)
- [Development Guide](../ssot/development.md)
- [EPIC-010: SigNoz Logging](./EPIC-010.signoz-logging.md)

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
| Debug | `scripts/debug.py` | ⚠️ Needs SigNoz API |
| Error IDs | `src/constants/error_ids.py` | ✅ Centralized constants |

### Frontend Foundation

| Library | File | Status |
|---------|------|--------|
| API Client | `lib/api.ts` | ✅ Unified fetch wrapper |
| Auth | `lib/auth.ts` | ✅ Token management |
| Currency | `lib/currency.ts` | ✅ Decimal.js |
| Workspace | `hooks/useWorkspace.tsx` | ✅ Tab/sidebar state |

---

*Created: January 2026*  
*Last Updated: January 2026*
