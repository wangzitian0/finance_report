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
- [ ] Distributed tracing with trace_id in all logs
- [ ] Service-layer uses `flush()`, router-layer owns `commit()`
- [ ] Connection pool size configurable via environment

### Should Have (P1)
- [ ] Unified `BaseAppException` with error IDs
- [ ] API-wide rate limiting (not just auth endpoints)
- [ ] Metrics endpoint for Prometheus

### Nice to Have (P2)
- [ ] SigNoz API integration in debug.py
- [ ] UUID auto-serialization structlog processor
- [ ] Frontend global loading indicator

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

**Tracking**: [#181](https://github.com/wangzitian0/finance_report/issues/181)

### H2: Service-Layer Transaction Boundaries
**Problem**: Services call `db.commit()` directly, making it impossible to compose multiple service calls into a single atomic transaction.

**Solution**:
1. Change services to use `db.flush()` for getting IDs
2. Move `commit()` responsibility to routers
3. Consider `@transactional` decorator for complex cases

**Tracking**: [#182](https://github.com/wangzitian0/finance_report/issues/182)

### H3: Vault Token Lifecycle
**Problem**: `VAULT_APP_TOKEN` requires manual regeneration via `invoke vault.setup-tokens`. If it expires, staging/production services fail to start.

**Solution**:
1. Document token TTL monitoring
2. Add token expiry check to bootloader
3. Consider automating renewal in CI/CD

**Tracking**: [#183](https://github.com/wangzitian0/finance_report/issues/183)

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

### M5: Frontend Global Loading
**Problem**: No unified loading indicator. Each component handles loading locally.

**Solution**: Add NProgress or similar top progress bar

**Tracking**: [#188](https://github.com/wangzitian0/finance_report/issues/188)

---

## 🟢 Low Priority Issues

### L1: S3 Lifecycle Policies
**Problem**: No automated cleanup of expired/rejected statement files.

**Solution**: Configure MinIO lifecycle rules

### L2: SigNoz API Integration
**Problem**: `debug.py` only prints SigNoz URL hints, doesn't query logs directly.

**Solution**: Add SigNoz API client to fetch logs via CLI

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
| 1 | Distributed Tracing (H1) | ⏳ Pending | - |
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
