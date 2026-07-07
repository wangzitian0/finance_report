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
  - See: `common/ledger/readme.md#async-tx-boundary`
- [x] Connection pool size configurable via environment

### Should Have (P1)
- [x] Unified `BaseAppException` with error IDs
- [x] API-wide rate limiting (not just auth endpoints)
- [~] Metrics endpoint — deferred: project uses OTLP, not Prometheus pull scraping (see EPIC-010)

### Nice to Have (P2)
- [ ] UUID auto-serialization structlog processor (P2 backlog, AC12.25.1)

---

## 📁 Affected Components

| Component | File(s) | Changes |
|-----------|---------|---------|
| Logging | `src/observability/logger.py` | Add tracing, trace_id processor |
| Database | `src/database.py`, `src/config.py` | Pool config, transaction patterns |
| Exceptions | `src/platform/extension/http_errors.py` | BaseAppException class |
| Rate Limiting | `src/platform` (generic limiter) · `src/identity/extension/rate_limit.py` (auth-endpoint limiters) | Generic limiter in the platform package; auth-specific limiters in the identity package (#1428) |
| Debugging | `tools/debug.py` | vendor-neutral OTEL resource-filter pointer |
| Schemas | `src/schemas/*.py` | Consistent BaseResponse inheritance |

---

## 🔴 High Priority Issues

### H1: Distributed Tracing Missing
**Problem**: No `opentelemetry-instrumentation-*` packages installed. Logs lack `trace_id`/`span_id`, making it impossible to correlate logs with traces in the observability backend.

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

### AC12.9: Ratio / percent value type — migrated to the `audit` package ([#1167](https://github.com/wangzitian0/finance_report/issues/1167))

The second base-element value type after `money` (see
[base-packages](https://github.com/wangzitian0/finance_report/blob/main/common/audit/readme.md#base-packages)): a dimensionless `Ratio` with ONE
percent-display policy (2 dp, **ROUND_HALF_UP**), shared FE/BE via conformance
vectors, so performance ratios / allocation shares / confidence proportions stop
diverging across the codebase and across ends.

> **The Ratio value-type/conformance/adoption ACs of this group are no longer
> defined here.** The float-rejection/percent-policy, cross-language-
> conformance, and adoption rows (were AC12.9.* rows .1–.3) migrated into the
> `audit` package and are owned by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.9.<s>` becomes
> `AC-audit.9.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.9.<s>` ids (homed in the package roadmap):
> `AC-audit.9.1` · `AC-audit.9.2` · `AC-audit.9.3`

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

### AC12.18: Config - Environment-Variable Format Contract — migrated to the `config` package

> **The config-format assertion ACs of this group are no longer defined here.**
> The PRIMARY_MODEL / config-sync / BASE_CURRENCY / S3_BUCKET / JWT_ALGORITHM /
> DATABASE_URL config-contract rows (were AC12.18.* rows .1–.6) migrated into the
> `config` package and are owned by, and sourced directly from,
> [`common/config/contract.py`](../../common/config/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-config.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.18.<s>` becomes
> `AC-config.18.<s>`). `common/testing/generate_ac_registry.py` reads package-contract
> roadmaps additively, so the AC index counts them without an EPIC-table mirror.
> This note references the new ids (keeping the registry↔EPIC link intact) but
> defines none of them — the contract is the single definition source.
>
> Migrated `AC-config.18.<s>` ids (homed in the package roadmap):
> `AC-config.18.1` · `AC-config.18.2` · `AC-config.18.3` · `AC-config.18.4` · `AC-config.18.5` · `AC-config.18.6`

The non-migrated **AC12.18.7** stub stays defined here: it is not a config-format
assertion (its only live anchor is the reconciliation `[AC12.18.7.2]` tag on
`apps/backend/tests/reconciliation/test_reconciliation_scoring_helpers.py`, a
transfer/candidate-matching unit test — a reconciliation concern, not config).

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.18.7 | stub | — | — | — |

### AC12.19: Infrastructure - Epic 001 Contracts — migrated to the `platform` package

> **The moon/infra contract AC of this group is no longer defined here.** The
> moon-workspace-config-exists row (was the AC12.19.* row) migrated into the `platform`
> package and is owned by, and sourced directly from,
> [`common/platform/contract.py`](../../common/platform/contract.py)'s `roadmap`
> as `AC-platform.19.1` (the leading "12" is dropped and the group/seq preserved).
> This note references the new id (keeping the registry↔EPIC link intact) but
> defines none of them — the contract is the single definition source.
>
> Migrated `AC-platform.19.<s>` ids (homed in the package roadmap):
> `AC-platform.19.1`

### AC12.20: Database - Connection Pool Configuration — migrated to the `config` package

> **The DB connection-pool config-field ACs of this group are no longer defined
> here.** The DB_POOL_SIZE / DB_POOL_MAX_OVERFLOW / range / env-override rows
> (were AC12.20.* rows .1–.5) migrated into the `config` package and are owned by,
> and sourced directly from,
> [`common/config/contract.py`](../../common/config/contract.py)'s `roadmap`
> under the numeric `AC-config.20.<seq>` scheme (the leading "12" is dropped and
> the group/seq preserved). This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-config.20.<s>` ids (homed in the package roadmap):
> `AC-config.20.1` · `AC-config.20.2` · `AC-config.20.3` · `AC-config.20.4` · `AC-config.20.5`

### AC12.21: Exceptions - BaseAppException — migrated to the `platform` package

> **The BaseAppException-hierarchy ACs of this group are no longer defined here.**
> The error_id / status_code / subclass / raise-and-catch / structured-handler
> rows (were AC12.21.* rows .1–.5) migrated into the `platform` package and are
> owned by, and sourced directly from,
> [`common/platform/contract.py`](../../common/platform/contract.py)'s `roadmap`
> under the numeric `AC-platform.21.<seq>` scheme (the leading "12" is dropped and
> the group/seq preserved). This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-platform.21.<s>` ids (homed in the package roadmap):
> `AC-platform.21.1` · `AC-platform.21.2` · `AC-platform.21.3` · `AC-platform.21.4` · `AC-platform.21.5`

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
**Problem**: ~~No `/metrics` endpoint for Prometheus.~~ → Architecture uses OTLP, not Prometheus pull.

**Solution**: ~~Add prometheus-fastapi-instrumentator~~ → **Deferred** (OTLP is the observability path)

**Tracking**: [#187](https://github.com/wangzitian0/finance_report/issues/187)
> ⚠️ **Deferred**: This project uses the observability backend via OTLP (see EPIC-010) for observability.
> Prometheus pull-based `/metrics` has zero consumers in this architecture.
> Metrics via OTLP to the observability backend is a future task tracked separately.

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

### AC12.23: Rate Limiting - Global API Middleware (M3) — migrated to the `platform` package

> **The global rate-limit middleware ACs of this group are no longer defined
> here.** The /health-exempt / 429-after-limit / allows-normal / /docs-exempt
> rows (were AC12.23.* rows .1–.4) migrated into the `platform` package (the
> rate-limiter is a platform-substrate middleware) and are owned by, and sourced
> directly from, [`common/platform/contract.py`](../../common/platform/contract.py)'s
> `roadmap` under the numeric `AC-platform.23.<seq>` scheme (the leading "12" is
> dropped and the group/seq preserved). This note references the new ids (keeping
> the registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-platform.23.<s>` ids (homed in the package roadmap):
> `AC-platform.23.1` · `AC-platform.23.2` · `AC-platform.23.3` · `AC-platform.23.4`

### AC12.24: Metrics - Prometheus Endpoint (M4)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.24.1 | ~~`/metrics` endpoint returns 200 OK~~ | Removed | Deferred: OTLP path, no Prometheus scrape config | P1 |
| AC12.24.2 | ~~`/metrics` endpoint returns text/plain~~ | Removed | Deferred: OTLP path | P1 |
| AC12.24.3 | ~~`/metrics` response contains Prometheus data~~ | Removed | Deferred: OTLP path | P1 |

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
| 6 | Metrics Endpoint (M4) | ❌ Deferred | Removed — OTLP used instead of Prometheus pull |
| 7 | UUID Logging Serialization (L3) | ⏳ P2 Backlog | AC12.25.1 |

---

## 🔗 Related Documents

- [Observability SSOT](../ssot/observability.md)
- [Development Guide](../ssot/development.md)
- [EPIC-010: Observability Logging](./EPIC-010.observability-logging.md)

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
  observability flows through OTLP.
- UUID auto-serialization for structlog is retained as EPIC-012 P2 backlog
  under AC12.25.1, not as archive-only prose.

---

## 📝 Audit Summary

### Current Foundation Libraries

| Library | File | Status |
|---------|------|--------|
| Logging | `src/observability/logger.py` | ✅ Structlog + OTEL export |
| Config | `src/config.py` | ✅ Pydantic Settings |
| Database | `src/database.py` | ⚠️ Needs pool config |
| Storage | `src/runtime/extension/storage.py` | ✅ S3/MinIO abstraction |
| Rate Limit | `src/identity/extension/rate_limit.py` | ⚠️ Auth-only (identity package, #1428) |
| Dependencies | `src/deps.py` | ✅ DbSession, CurrentUserId |
| Boot | `src/boot.py` | ✅ Health checks |
| Debug | `tools/debug.py` | prints OTEL attribute filters (no backend API) |
| Error IDs | `src/observability/error_ids.py` | ✅ Centralized constants |

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

> **The backend error-contract ACs of this group migrated to the `platform`
> package.** The structured-404-error and OpenAPI-ErrorResponse rows (were
> the AC12.27.* rows .1–.2) are owned by, and sourced directly from,
> [`common/platform/contract.py`](../../common/platform/contract.py)'s `roadmap`
> as `AC-platform.27.1`–`AC-platform.27.2` (the leading "12" is dropped and the
> group/seq preserved). The **frontend** row AC12.27.3 stays defined below: its
> anchor is a `.test.ts` (a vitest `it()`, not a Python `path::func`) and the
> `platform` package is `fe=None`, so it cannot be homed in the package roadmap
> (same precedent as the ledger cutover leaving EPIC-002's frontend rows defined).

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.27.3 | Frontend `apiFetch` throws `ApiError` carrying the parsed `errorId` | `test_AC12_27_3_api_error_carries_error_id` | `__tests__/apiErrorStructured.test.ts` | P1 |

### AC12.28: Generated Frontend API Types from OpenAPI ([#1004](https://github.com/wangzitian0/finance_report/issues/1004))

Tier 2 of #1000. The backend OpenAPI schema is serialized to a checked-in spec
(`apps/frontend/openapi.json`), and a staleness gate
(`tools/generate_openapi_spec.py --check`) fails when that committed spec drifts
from the live FastAPI schema. `api-types.ts` is regenerated from the spec
(`npm run gen:api-types`), and high-traffic call sites consume the generated
`Schemas[...]` aliases (via `lib/api-schema.ts`) so a backend response-shape
change that isn't regenerated is caught at compile time (`npm run build`) —
enforcing the FE↔BE contract instead of leaving the generated client as dead code.

> **The backend OpenAPI-spec ACs of this group migrated to the `platform`
> package.** The generator-emits-spec and staleness-gate rows (were
> the AC12.28.* rows .1–.2) are owned by, and sourced directly from,
> [`common/platform/contract.py`](../../common/platform/contract.py)'s `roadmap`
> as `AC-platform.28.1`–`AC-platform.28.2` (the leading "12" is dropped and the
> group/seq preserved). The **frontend** row AC12.28.3 stays defined below: its
> anchor is a `.test.ts` (a vitest `it()`, not a Python `path::func`) and the
> `platform` package is `fe=None`, so it cannot be homed in the package roadmap.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.28.3 | High-traffic call sites type responses against the generated schema | `test_AC12_28_3_types_stage2_batch_responses_against_generated_schema` | `__tests__/apiTypedClient.test.ts` | P2 |

### AC12.29: API-Surface Consistency Sweep ([#1099](https://github.com/wangzitian0/finance_report/issues/1099))

Tier-2 follow-up of #1000/#1074: the audit found the API surface mostly good
(centralized error model, all-`UUID` path params, ~120/125 `response_model`
coverage) but with consistency gaps that would leak into the generated FE client
(#1004/AC12.28). This sweep flattens those gaps **without breaking the live
frontend**. Landed as three stacked PRs (tags+deprecations, pagination, status
codes), then a follow-up PR completed the verb-in-path URL renames atomically across
backend + frontend (`/reconciliation/run`→`/runs`, `/market-data/sync/{fx,stocks}`→
`/market-data/{fx,stocks}/syncs`, `journal /post`→`/postings` / `/void`→`/voidings`).

> **The API-surface-consistency ACs of this group migrated to the `platform`
> package.** All six rows (were the AC12.29.* rows .1–.6: status-code constants /
> bounded list endpoints / pagination convention / route+tag uniqueness /
> deprecated-endpoint removal / verb-in-path rename) are owned by, and sourced
> directly from, [`common/platform/contract.py`](../../common/platform/contract.py)'s
> `roadmap` under the numeric `AC-platform.29.<seq>` scheme (the leading "12" is
> dropped and the group/seq preserved). This note references the new ids (keeping
> the registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-platform.29.<s>` ids (homed in the package roadmap):
> `AC-platform.29.1` · `AC-platform.29.2` · `AC-platform.29.3` · `AC-platform.29.4` · `AC-platform.29.5` · `AC-platform.29.6`

### AC12.30: Base Element Completion — Money / Ratio / Quantity — migrated to the `audit` package

The base-element family is intentionally MECE: `Money` owns amounts and
currency-aware arithmetic, `Ratio` owns dimensionless percentages/proportions,
and `Quantity` owns shares/units/contracts. `ExchangeRate` is not a fourth base
element; it is the typed conversion parameter inside `money.convert`, replacing
the previous naked-`Decimal` rate boundary.

> **The Quantity value-type/conformance/ExchangeRate-adoption/adoption ACs of
> this group are no longer defined here.** The float-rejection/quantization,
> cross-language-conformance, typed-ExchangeRate-adoption, and quantity-
> adoption rows (were AC12.30.* rows .1–.4) migrated into the `audit` package
> and are owned by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.30.<s>` becomes
> `AC-audit.30.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.30.<s>` ids (homed in the package roadmap):
> `AC-audit.30.1` · `AC-audit.30.2` · `AC-audit.30.3` · `AC-audit.30.4`

### AC12.31: Decimal Boundary Policy and Migration — migrated to the `audit` package

Raw `Decimal` remains the storage/interchange substrate, but it is no longer a
domain concept by itself. The base-element narrow waists own business semantics:
`Money` for currency amounts, `Ratio` for dimensionless proportions, and
`Quantity` for shares/units/contracts. New service code must either cross an
explicit boundary or use the typed value package.

> **The ACs of this group are no longer defined here.** The rows (were
> AC12.31.* rows .1–.7) migrated into the `audit` package and are owned
> by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.31.<s>`
> becomes `AC-audit.31.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.31.<s>` ids (homed in the package roadmap):
> `AC-audit.31.1` · `AC-audit.31.2` · `AC-audit.31.3` · `AC-audit.31.4` · `AC-audit.31.5` · `AC-audit.31.6` · `AC-audit.31.7`

### AC12.32: UnitPrice — money-per-quantity composite value type — migrated to the `audit` package ([#1253](https://github.com/wangzitian0/finance_report/issues/1253))

The composite base element after `money`/`ratio`/`quantity` (see
[base-packages](https://github.com/wangzitian0/finance_report/blob/main/common/audit/readme.md#base-packages)): a `UnitPrice` (rate + `Currency` +
`Unit`) that owns money-per-quantity semantics — `unit_price * quantity -> Money`,
`UnitPrice.from_total(money, quantity)` (`Money / Quantity`), and the 6-dp
price/unit-rate quantum — so portfolio/market-data services stop re-deriving the
`quantity.value * price` extension, the `amount / quantity.value` rate, and a
duplicated local `quantize` helper as raw `Decimal` glue.

> **The UnitPrice value-type/conformance/adoption ACs of this group are no
> longer defined here.** The float-rejection/quantization, cross-language-
> conformance, and adoption rows (were AC12.32.* rows .1–.3) migrated into the
> `audit` package and are owned by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.32.<s>` becomes
> `AC-audit.32.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.32.<s>` ids (homed in the package roadmap):
> `AC-audit.32.1` · `AC-audit.32.2` · `AC-audit.32.3`

### AC12.33: Composite value operations — Money predicates/sum, Ratio fallback, MoneyTolerance — migrated to the `audit` package ([#1253](https://github.com/wangzitian0/finance_report/issues/1253))

Reusable composite operations on the existing base elements so business code
stays typed instead of re-deriving them as raw `Decimal` glue: `Money` gains
`is_zero`/`is_positive`/`is_negative` and a typed `Money.sum`; `Ratio` gains the
zero-denominator fallbacks `fraction_or_zero`/`fraction_or_none`; and a new
`MoneyTolerance` owns the absolute+relative amount-matching band (`max(absolute,
relative*|expected|)`). These are added cross-language-ready (shared conformance
vectors) but adopted on the backend first.

> **The composite value-operations ACs of this group are no longer defined
> here.** The Money predicates/sum + Ratio fallback + MoneyTolerance rows, the
> cross-language conformance row, and the adoption row (were AC12.33.* rows
> .1–.3) migrated into the `audit` package and are owned by, and sourced
> directly from, [`common/audit/contract.py`](../../common/audit/contract.py)'s
> `roadmap` under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme
> (the leading "12" is dropped and the group/seq preserved, so `AC12.33.<s>`
> becomes `AC-audit.33.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.33.<s>` ids (homed in the package roadmap):
> `AC-audit.33.1` · `AC-audit.33.2` · `AC-audit.33.3`

### AC12.34: Ledger module — `Entry` value object + vertical-slice template — migrated to the `ledger` package ([#1253](https://github.com/wangzitian0/finance_report/issues/1253))

The first **vertical domain module** (`src/ledger`) as the template every other
domain followed: files converged into the then-role folders (`types/` nouns,
`ops/` verbs; since re-layered into `base/extension`), and the
project's layer-DAG rule is enforced (model layer never imports a service). Its
core noun `Entry` makes the double-entry balance invariant a **type** — an
unbalanced entry is unconstructable (`UnbalancedEntryError`), replacing scattered
runtime `abs(debit-credit) < 0.01` checks.

> **The ACs of this group are no longer defined here.** The rows (were
> AC12.34.* rows .1–.6) migrated into the `ledger` package and are owned
> by, and sourced directly from,
> [`common/ledger/contract.py`](../../common/ledger/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-ledger.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.34.<s>`
> becomes `AC-ledger.34.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-ledger.34.<s>` ids (homed in the package roadmap):
> `AC-ledger.34.1` · `AC-ledger.34.2` · `AC-ledger.34.3` · `AC-ledger.34.4` · `AC-ledger.34.5` · `AC-ledger.34.6`

### AC12.35: ORM read layer returns value types — boundary push — migrated to the `audit` package ([#1253](https://github.com/wangzitian0/finance_report/issues/1253))

The read/model layer hands business code typed values (`Money`/`Quantity`) so
services stop pulling raw `Decimal` off rows and wrapping it ad-hoc with
`to_money(...)`. Raw columns stay the storage/write boundary; business reads typed
accessors. API response shapes are unchanged (serialized from the value at the
edge). Pilot: `ManagedPosition` + `investment_accounting` (single-currency, no FX);
other models/services follow incrementally.

> **The ACs of this group are no longer defined here.** The rows (were
> AC12.35.* rows .1–.4) migrated into the `audit` package and are owned
> by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.35.<s>`
> becomes `AC-audit.35.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.35.<s>` ids (homed in the package roadmap):
> `AC-audit.35.1` · `AC-audit.35.2` · `AC-audit.35.3` · `AC-audit.35.4`

### AC12.36: Shared Decimal-scalar codec — one SSOT per layer — migrated to the `audit` package ([#1253](https://github.com/wangzitian0/finance_report/issues/1253))

The raw-`Decimal` boundary codec required by `common/audit/readme.md#base-packages` §3 was re-implemented
in every base package — a byte-identical `_decimal_to_wire`, a `_decimal_from_wire` /
`_payload_mapping` / `_field` triad, and a construction-time `_coerce` — differing only
by which typed error it raised. That codec is now factored once into a single
`decimal_scalar` module per layer (`decimal_to_wire` / `coerce_decimal` / `WireCodec`);
each package supplies its own error classes, so the per-domain error hierarchy is
preserved while the duplicated bodies disappear. The module is dependency-light (it
imports no base package, so the family stays bounded — not a fifth base package).

> **The shared Decimal-scalar codec ACs of this group are no longer defined
> here.** The common-layer and backend-mirror codec-SSOT rows (were AC12.36.*
> rows .1–.2) migrated into the `audit` package and are owned by, and sourced
> directly from, [`common/audit/contract.py`](../../common/audit/contract.py)'s
> `roadmap` under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme
> (the leading "12" is dropped and the group/seq preserved, so `AC12.36.<s>`
> becomes `AC-audit.36.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.36.<s>` ids (homed in the package roadmap):
> `AC-audit.36.1` · `AC-audit.36.2`

### AC12.37: `JournalLine.money` accessor — boundary push Phase 2 — migrated to the `audit` package ([#1253](https://github.com/wangzitian0/finance_report/issues/1253))

After the `ManagedPosition` pilot (AC12.35), the next-largest raw-`Decimal` read
surface is `JournalLine.amount` (~40 service reads). Journal lines are immutable
(`amount > 0`), so a read-only `money` accessor is the boundary; business sums/reads
lines as `Money` (currency-checked) instead of raw currency-blind `Decimal`. Migrated
incrementally by area; the forbid-ratchet follows once the surface is covered.

> **The ACs of this group are no longer defined here.** The rows (were
> AC12.37.* rows .1–.3) migrated into the `audit` package and are owned
> by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.37.<s>`
> becomes `AC-audit.37.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.37.<s>` ids (homed in the package roadmap):
> `AC-audit.37.1` · `AC-audit.37.2` · `AC-audit.37.3`

### AC12.38: Currency as a single base SSOT + typed balance core (Phase C) — migrated to the `audit` package ([#1339](https://github.com/wangzitian0/finance_report/issues/1339))

Currency was resolved ad-hoc in ≥3 divergent ways (`or "SGD"`, `or settings.base_currency`, `or account.currency or target`). Phase C consolidates to **one** resolution — `settings.base_currency`, read only via `line.money` — and migrates the journal balance core + the remaining currency-blind line sums to `Money.sum`, so cross-currency addition becomes a typed error instead of a silent bug. A ratchet forbids new currency-blind `sum(line.amount)`.

> **The ACs of this group are no longer defined here.** The rows (were
> AC12.38.* rows .1–.4) migrated into the `audit` package and are owned
> by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme (the
> leading "12" is dropped and the group/seq preserved, so `AC12.38.<s>`
> becomes `AC-audit.38.<s>`). `common/testing/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.38.<s>` ids (homed in the package roadmap):
> `AC-audit.38.1` · `AC-audit.38.2` · `AC-audit.38.3` · `AC-audit.38.4`

### AC12.39: Editable base reporting currency — DB-backed app config (Phase D) ([#1340](https://github.com/wangzitian0/finance_report/issues/1340))

`settings.base_currency` was env-only (default `"SGD"`), so the base reporting currency could only change via a redeploy. Phase D persists an app-level override in a single key/value `app_config` table and reads it dynamically through one accessor, so an operator can edit the base currency at runtime on the config page. The override is ISO 4217 validated (reusing the `src.audit.money.Currency` value type) at the request boundary, so an invalid code returns HTTP 422 and is never persisted.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.39.1 | The backend exposes `GET`/`PUT /app-config/base-currency` to read and update the effective base currency; the code is ISO 4217 validated via `src.audit.money.Currency` and persisted in the DB-backed `app_config` row, and an invalid code returns HTTP 422 without persisting {tier:CODE-ONLY} | `test_AC12_39_1_get_returns_env_default_when_unset`, `test_AC12_39_1_invalid_currency_returns_422_and_is_not_persisted` | `apps/backend/tests/api/test_app_config_router.py` | P1 |
| AC12.39.2 | A single accessor `get_effective_base_currency` returns the effective base currency — the persisted `app_config` override if present, else `settings.base_currency` {tier:CODE-ONLY} | `test_AC12_39_2_effective_accessor_falls_back_to_env_default` | `apps/backend/tests/api/test_app_config_router.py` | P1 |
| AC12.39.3 | The frontend General Settings page exposes a "Base currency" control that reads + updates the effective value via `lib/api.ts` (`fetchBaseCurrency`/`updateBaseCurrency`, never raw `fetch`) {tier:CODE-ONLY} | `AC12.39.3 renders the effective base currency`, `AC12.39.3 submits the edited currency via updateBaseCurrency` | `apps/frontend/src/__tests__/generalSettingsPage.test.tsx` | P1 |
| AC12.39.4 | Updating the base currency persists the override and the effective accessor returns the new value on a subsequent read {tier:CODE-ONLY} | `test_AC12_39_4_update_persists_and_effective_accessor_returns_new_value` | `apps/backend/tests/api/test_app_config_router.py` | P1 |

### AC12.40: Currency established at ingest, never silent-defaulted — Phase E ([#1341](https://github.com/wangzitian0/finance_report/issues/1341))

A transaction's currency must be established **at the ingest boundary**: attached
explicitly when determinable, and otherwise flagged `currency_unresolved` and routed
to human review rather than silently defaulted to a base currency. An unresolved
transaction cannot be promoted to a `JournalLine` until a reviewer specifies an
ISO-4217 currency (validated via `src.audit.money.Currency`), with the resolution audited
(who/when/value). This makes the downstream `JournalLine.currency` human-confirmed by
construction — closing the input-selection seam where currency was previously assumed.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC12.40.1 | Ingest resolution attaches the first valid ISO-4217 candidate (parsed transaction currency, then statement currency), normalized, when the currency is determinable {tier:CODE-ONLY} | `test_AC12_40_1_attaches_explicit_currency` | `apps/backend/tests/services/test_currency_resolution.py` | P0 |
| AC12.40.2 | When no candidate is a valid ISO-4217 code the row is flagged `currency_unresolved` with a non-trusted placeholder and is NOT silently defaulted to a base currency {tier:CODE-ONLY} | `test_AC12_40_2_flags_unresolved_instead_of_silent_default` | `apps/backend/tests/services/test_currency_resolution.py` | P0 |
| AC12.40.3 | A reviewer specifies the currency (ISO-4217 validated via `src.audit.money.Currency`; an invalid code is rejected and nothing is written); the resolution records who/when/value {tier:CODE-ONLY} | `test_AC12_40_3_reviewer_resolves_currency_with_audit` | `apps/backend/tests/services/test_currency_resolution.py` | P0 |
| AC12.40.4 | The promotion gate (`create_entry_from_txn`) blocks a `currency_unresolved` transaction from becoming a `JournalLine` {tier:CODE-ONLY} | `test_AC12_40_4_promotion_gate_blocks_unresolved_currency` | `apps/backend/tests/services/test_currency_resolution.py` | P0 |

---

*Planning snapshot captured: January 2026*
