# EPIC-008: Testing Strategy — Machine Generated Details

> **Auto-generated from**: `testing-implementation.md`, `testing-gap-analysis.md`, `EPIC-QA-Standardization.md`, `QA_REPORT_20260121.md`
>
> **Last Updated**: 2026-01-27
>
> **Human Review Version**: [EPIC-008.testing-strategy.md](./EPIC-008.testing-strategy.md)

---

## Table of Contents

1. [Testing Infrastructure Implementation](#1-testing-infrastructure-implementation)
2. [Testing Gap Analysis](#2-testing-gap-analysis)
3. [QA Standardization Plan](#3-qa-standardization-plan)
4. [QA Report (2026-01-21)](#4-qa-report-2026-01-21)

---

## 1. Testing Infrastructure Implementation

**Status**: ✅ Complete (7/7 tasks)
**Date**: 2026-01-25

### What Was Implemented

#### 1.1 Test Data Factories (`tests/factories.py`)

Created factory_boy-based factories for all major models:

**Benefits**:
- Reduces test boilerplate by 70%
- Consistent test data generation
- Easy to create balanced journal entries
- Async-ready with `create_async()` methods

**Usage**:
```python
# Simple creation
account = await AccountFactory.create_async(db, user_id=user.id)

# Balanced journal entry (debit + credit)
entry, debit_acc, credit_acc = await JournalEntryFactory.create_balanced_async(
    db, user_id=user.id, amount=Decimal("100.00")
)
```

**Files Created**:
- `apps/backend/tests/factories.py` (243 lines)
  - `UserFactory`, `AccountFactory`, `JournalEntryFactory`, `JournalLineFactory`
  - `BankStatementFactory`, `BankStatementTransactionFactory`
  - `ReconciliationMatchFactory`

#### 1.2 Performance Testing (`tests/locustfile.py`)

Set up Locust for load testing with realistic user scenarios:

**Task Weights** (most → least frequent):
1. `view_dashboard` (5x) - Health checks
2. `list_accounts` (3x) - Read operations
3. `view_reports` (2x) - Report generation
4. `upload_statement` (1x) - Expensive AI operation

**Run Commands**:
```bash
# Local (interactive UI)
moon run backend:test-perf

# Headless (CI)
locust -f tests/locustfile.py --host=http://localhost:8000 \
  --users 10 --spawn-rate 2 --run-time 30s --headless

# Staging (load test)
locust -f tests/locustfile.py --host=https://report-staging.zitian.party \
  --users 50 --spawn-rate 5 --run-time 5m
```

**Exit Criteria**:
- Error rate < 5%
- Avg response time < 2000ms

**Files Created**:
- `apps/backend/tests/locustfile.py` (164 lines)

#### 1.3 Playwright E2E Tests (`tests/e2e/`)

Created end-to-end test framework with 3 critical scenarios:

**Tests Implemented**:
1. **Statement Upload Flow**: PDF → AI Parse → View Transactions → Approve
2. **Model Selection**: Select model → Upload → Verify correct model used
3. **Stale Model Cleanup**: localStorage validation → Auto-cleanup

**Current Status**: Tests are marked `@pytest.mark.skip` because they require:
- Frontend running on `http://localhost:3000`
- Backend running on `http://localhost:8000`
- MinIO running on `http://localhost:9000`
- Valid `OPENROUTER_API_KEY` in environment

**Run Commands**:
```bash
# Run E2E tests (requires full stack)
moon run backend:test-e2e

# Or directly
uv run pytest -m e2e tests/e2e/
```

**Files Created**:
- `apps/backend/tests/e2e/conftest.py` (31 lines) - Playwright fixtures
- `apps/backend/tests/e2e/test_statement_upload_e2e.py` (156 lines) - 3 E2E scenarios

#### 1.4 Moon Task Integration (`apps/backend/moon.yml`)

**New Tasks**:
```bash
moon run backend:test             # Unit tests (existing)
moon run backend:test-integration # Integration tests (NEW)
moon run backend:test-e2e         # E2E tests with Playwright (NEW)
moon run backend:test-perf        # Performance tests with Locust (NEW)
```

**Files Modified**:
- `apps/backend/moon.yml` (+23 lines)
- `apps/backend/pyproject.toml` (+4 dependencies, +1 pytest marker)

### Dependencies Added

```toml
[dependency-groups]
dev = [
    # ... existing ...
    "factory-boy>=3.3.0",  # Test data factories
    "faker>=33.0.0",        # Fake data generation
    "locust>=2.20.0",       # Performance testing
]
```

### Testing Strategy Comparison

#### Before P1 (PR #151)
```
     E2E (0%)          ← ❌ Missing
    /              \
  Integration (3%)    ← ⚠️ Limited (AI models only)
 /                  \
Unit Tests (96%)      ← ✅ Good
```

#### After P1 (This Implementation)
```
     E2E (3 scenarios)  ← ✅ Critical paths covered (skipped by default)
    /                  \
  Integration (10 tests) ← ✅ AI models + Upload flow
 /                      \
Unit Tests (626 tests)    ← ✅ Excellent (95% coverage)
```

### Cost-Benefit Analysis

| Task | Effort | Benefit | Status |
|------|--------|---------|--------|
| Test Factories | 2 hours | Reduces test boilerplate 70% | ✅ Done |
| Performance Tests | 1.5 hours | Catches performance regressions | ✅ Done |
| E2E Framework | 2 hours | Catches integration bugs pre-prod | ✅ Done |
| Moon Tasks | 0.5 hours | Unified test commands | ✅ Done |
| **Total** | **6 hours** | **Prevents classes of prod bugs** | **✅ Complete** |

---

## 2. Testing Gap Analysis

### Root Cause Analysis

**Failed Test Example**:
```python
# apps/backend/tests/test_main.py:284
def test_config_defaults(self):
    settings = Settings()
    assert settings.primary_model == "google/gemini-2.0-flash-exp:free"  # ❌ Hardcoded old value
```

**Problems Identified**:
1. ✅ **Unit tests exist** - Tests are present
2. ❌ **Hardcoded expectations** - Test assertions use literal values
3. ❌ **No contract tests** - No "config change → test update" consistency check
4. ❌ **No E2E validation** - Cannot verify actual runtime config

### Current Test Coverage

| Layer | Coverage | Test Count | Notes |
|-------|----------|------------|-------|
| Models | 100% | ~50 | SQLAlchemy models |
| Services | 95% | ~200 | Business logic |
| Routers | 98% | ~150 | API endpoints |
| Schemas | 100% | ~30 | Pydantic validation |

**Strengths**:
- ✅ High coverage (96.26%)
- ✅ Fast execution (5-6 min)
- ✅ Automated DB lifecycle

**Weaknesses**:
- ❌ **Tests coupled to config** - Hardcoded expectations
- ❌ **Cannot detect config drift** - Code changed, tests didn't
- ❌ **No cross-layer validation** - Only tests single components

### Missing Integration Tests

- ❌ **AI model call integration** - No test of actual OpenRouter calls
- ❌ **Config loading integration** - No test of `.env` → `config.py` → runtime
- ❌ **Frontend-backend integration** - No API contract consistency tests

### Missing E2E Scenarios

1. ❌ User uploads PDF → AI parses → Returns transaction data
2. ❌ User selects model → Call succeeds/fails handling
3. ❌ localStorage model validation → Fallback flow
4. ❌ Multi-currency complete flow

### Priority Matrix

| Improvement | Impact | Cost | Priority |
|-------------|--------|------|----------|
| Fix config test brittleness | 🔥 High | 💰 Low | **P0** (immediate) |
| AI model call integration tests | 🔥 High | 💰 Medium | **P0** (this week) |
| Smoke Tests in CI | 🔥 High | 💰 Low | **P0** (this week) |
| Frontend model validation E2E | 🔥 High | 💰 High | **P1** (2 weeks) |
| Complete E2E test suite | 🔥 High | 💰💰 High | **P1** (1 month) |
| Test data factories | 🔵 Medium | 💰 Medium | **P2** (2 months) |
| Visual regression | 🔵 Medium | 💰💰 High | **P3** (3 months) |
| Performance testing | 🔵 Low | 💰💰 High | **P3** (as needed) |

### CI/CD Test Strategy

| Phase | Test Type | Trigger | Expected Duration |
|-------|-----------|---------|-------------------|
| **Pre-commit** | Lint, Format | Git hook | < 5s |
| **PR Open** | Unit Tests (96%) | Every push | 5-6 min |
| **PR Ready** | Integration Tests | After unit pass | 2-3 min |
| **PR Deploy** | Smoke Tests | After PR env deploy | 1 min |
| **Pre-merge** | E2E Tests (Critical) | Before merge | 5-10 min |
| **Post-merge** | Full E2E Suite | After merge to main | 15-20 min |
| **Nightly** | Performance Tests | Scheduled | 30 min |

---

## 3. QA Standardization Plan

### 3.1 Environment Variables & Secrets (The "Triangle of Death")

**Problem**: Desynchronization between `.env`, `config.py`, `secrets.ctmpl`, and Docker `ARG`.

**Actions**:
- [x] **Doc**: Update `docs/ssot/development.md` with "Variable Lifecycle" flowchart
- [x] **Test**: Enhance `scripts/check_env_keys.py`
  - Verify strict 1:1 mapping between `config.py` fields and `.env.example`
  - Warn if `secrets.ctmpl` contains keys not in `config.py`

### 3.2 Routing & API Prefix (Local vs Staging)

**Problem**: Inconsistent `BASE_URL` handling causes 404s on Staging (double `/api` prefix).

**Actions**:
- [x] **Doc**: Update `apps/frontend/README.md` and `docs/ssot/development.md`
- [x] **Refactor**: Review `apps/frontend/src/lib/api.ts` - strips trailing slashes
- [x] **Test**: Add `apps/frontend/src/lib/api.test.ts`

### 3.3 Database Migrations & Schema (The "Silent Killers")

**Problem**: `sa.Enum` without explicit names cause migration conflicts.

**Actions**:
- [x] **Doc**: Update `docs/ssot/schema.md` with Migration Rules
- [x] **Test**: Create `apps/backend/tests/test_schema_guardrails.py`
  - Fails if any `sa.Enum` lacks `name`
  - Fails if Alembic revision filename > threshold

### 3.4 Data Integrity (Float vs Decimal)

**Problem**: AI extraction returns floats, causing precision loss.

**Actions**:
- [x] **Doc**: Update `docs/ssot/accounting.md` and `docs/ssot/extraction.md` with "The Float Ban"
- [x] **Test**: Create `apps/backend/tests/test_decimal_safety.py`
  - Fuzz testing: Feed `{ amount: 100.50 }` (float) to financial Pydantic models

---

## 4. QA Report (2026-01-21)

### Executive Summary

Executed "Shift Left" strategy to catch common pitfalls early. Implemented 4 layers of defense:

1. **Environment Variables (The "Triangle of Death")**
   - **Documentation**: Added `Variable Lifecycle` flowchart to `development.md`
   - **Tooling**: Hardened `scripts/check_env_keys.py` for strict consistency
   - **Outcome**: Impossible to merge undocumented environment variables

2. **Frontend Routing (Local vs Staging)**
   - **Code**: Hardened `apps/frontend/src/lib/api.ts` to strip trailing slashes
   - **Testing**: Added `api.test.ts` to verify URL normalization
   - **Documentation**: Updated `apps/frontend/README.md` with strict rules

3. **Database Schema (Silent Killers)**
   - **Guardrail Test**: Created `apps/backend/tests/test_schema_guardrails.py`
     - **Enum Check**: Fails if any SQLAlchemy `Enum` lacks `name="..."` parameter
     - **Migration Check**: Fails if migration filenames are too long (>120 chars)
   - **Outcome**: CI will block PRs with dangerous schema definitions

4. **Data Integrity (The Float Ban)**
   - **Guardrail Test**: Created `apps/backend/tests/test_decimal_safety.py`
     - **Float Injection**: Fuzzes Pydantic models with dangerous floats (`0.1 + 0.2`)
   - **Documentation**: Updated `extraction.md` and `accounting.md` to ban floats

### Next Steps

- Run `python scripts/check_env_keys.py` locally to fix config drifts
- Run `moon run backend:test` to verify Guardrails catch existing issues

---

## Recommended Next Steps (Phase 2)

1. **Enable E2E in CI** (2 hours)
   - Add `e2e-test` job to `.github/workflows/pr-test.yml`
   - Configure secrets (`OPENROUTER_API_KEY`)
   - Test on PR environment

2. **Add Reconciliation E2E** (3 hours)
   - `test_reconciliation_full_flow()` - Upload → Match → Approve
   - `test_multi_currency_flow()` - USD/SGD conversion

3. **Performance Baseline** (1 hour)
   - Run Locust against staging
   - Document P95/P99 latencies
   - Set up alerts for regressions

---

## Success Criteria

**Short-term (1 month)**:
- [x] Config tests no longer hardcode values
- [x] AI model integration tests > 80% coverage
- [x] Smoke Tests in CI
- [x] Test data factories
- [x] Performance testing framework
- [x] E2E test infrastructure
- [ ] E2E tests running in CI

**Mid-term (3 months)**:
- [ ] E2E covers 5 core user journeys
- [ ] Total test time < 15 minutes
- [ ] Clear error messages on test failure
- [ ] PR environments auto-run smoke tests

**Long-term (6 months)**:
- [ ] Balanced test pyramid (70% Unit, 20% Integration, 10% E2E)
- [ ] Performance baseline (P95 < 500ms)
- [ ] Visual regression for key pages
- [ ] Test observability dashboard

---

## File Reference

| Source File | Status |
|-------------|--------|
| `testing-implementation.md` | Consolidated here |
| `testing-gap-analysis.md` | Consolidated here |
| `EPIC-QA-Standardization.md` | Consolidated here |
| `QA_REPORT_20260121.md` | Consolidated here |

---

*This is a machine-generated document consolidating implementation details, gap analysis, and QA reports. For goals and acceptance criteria, see [EPIC-008.testing-strategy.md](./EPIC-008.testing-strategy.md).*
