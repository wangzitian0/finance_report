# Test Coverage Improvement Plan
**Created**: 2026-02-25  
**Target**: 99% coverage (from current 21.58%)  
**Total Missing**: 3,643 lines  

---

## Executive Summary

### Current State
- **Overall Coverage**: 21.58%
- **Target Coverage**: 99%
- **Gap**: 77.42% (3,643 lines)

### Category Breakdown
| Category | Current | Missing Lines | Status |
|----------|---------|---------------|--------|
| **Models** | 97.8% | 9L | ✅ Near complete |
| **Schemas** | 90.0% | 24L | ✅ Good |
| **Constants** | 100% | 0L | ✅ Complete |
| **Services** | 18.7% | 2,214L | ❌ Critical gap |
| **Routers** | 0.0% | 929L | ❌ No coverage |
| **Utils** | 0.0% | 23L | ❌ No coverage |
| **Infrastructure** | 25.4% | 444L | ❌ Low coverage |

---

## Strategy: 4-Phase Rollout

### Phase 1: Core Business Logic (P0)
**Goal**: Reach 50% overall coverage  
**Focus**: Services layer - business logic  
**Estimated Effort**: 2-3 weeks  
**Impact**: Highest (covers critical business rules)

#### Targets (8 files, 1,748 lines)
| File | Missing | AC | Priority | Est. Tests |
|------|---------|-----|----------|------------|
| `services/reporting.py` | 410L | AC5.x | 🔴 Critical | 40-50 |
| `services/reconciliation.py` | 408L | AC4.x | 🔴 Critical | 50-60 |
| `services/fx_revaluation.py` | 134L | AC5.1.2 | 🔴 Critical | 15-20 |
| `services/assets.py` | 132L | AC11.x | 🔴 Critical | 15-20 |
| `services/review_queue.py` | 128L | AC4.3.x | 🔴 Critical | 15-20 |
| `services/processing_account.py` | 127L | AC2.3.x | 🔴 Critical | 15-20 |
| `services/accounting.py` | 106L | AC2.x | 🔴 Critical | 12-15 |
| `services/validation.py` | 102L | AC4.2.x | 🔴 Critical | 12-15 |

**Success Criteria**:
- ✅ All critical business logic paths covered
- ✅ Error handling tested
- ✅ Edge cases validated
- ✅ Accounting equation holds in all scenarios

---

### Phase 2: API Layer (P1)
**Goal**: Reach 70% overall coverage  
**Focus**: Router layer - HTTP endpoints  
**Estimated Effort**: 1-2 weeks  
**Impact**: High (ensures API contracts)

#### Targets (9 files, 929 lines)
| File | Missing | Endpoints | Est. Tests |
|------|---------|-----------|------------|
| `routers/statements.py` | 268L | 10+ | 25-30 |
| `routers/reconciliation.py` | 166L | 8+ | 20-25 |
| `routers/reports.py` | 108L | 6+ | 15-20 |
| `routers/chat.py` | 88L | 5+ | 12-15 |
| `routers/journal.py` | 72L | 5+ | 10-12 |
| `routers/auth.py` | 69L | 4+ | 8-10 |
| `routers/accounts.py` | 67L | 5+ | 8-10 |
| `routers/assets.py` | 61L | 4+ | 8-10 |
| `routers/ai_models.py` | 30L | 2+ | 4-5 |

**Test Strategy**:
- Use FastAPI TestClient for integration tests
- Test request validation (Pydantic schemas)
- Test response formatting
- Test authentication/authorization
- Test error responses (4xx, 5xx)

**Success Criteria**:
- ✅ All endpoints have happy path tests
- ✅ Error paths tested (400, 401, 403, 404, 500)
- ✅ Request validation tested
- ✅ Authentication tested

---

### Phase 3: AI & Advanced Features (P2)
**Goal**: Reach 85% overall coverage  
**Focus**: AI services and supporting features  
**Estimated Effort**: 1 week  
**Impact**: Medium (optional features)

#### Targets (3 files, 373 lines)
| File | Missing | Feature | Est. Tests |
|------|---------|---------|------------|
| `services/ai_advisor.py` | 224L | AI chat advisor | 25-30 |
| `services/openrouter_streaming.py` | 72L | Streaming API | 10-12 |
| `services/openrouter_models.py` | 77L | Model management | 10-12 |

**Test Strategy**:
- Mock OpenRouter API calls
- Test streaming response handling
- Test model selection logic
- Test fallback mechanisms
- Test error handling (API failures)

**Success Criteria**:
- ✅ All AI service paths covered
- ✅ API mocking verified
- ✅ Streaming logic tested
- ✅ Fallback tested

---

### Phase 4: Infrastructure & Utils (P3)
**Goal**: Reach 99% overall coverage  
**Focus**: Infrastructure, utilities, and edge cases  
**Estimated Effort**: 1 week  
**Impact**: Low (infrastructure, mostly tested via integration)

#### Targets (10 files, 467 lines)
| File | Missing | Category | Est. Tests |
|------|---------|----------|------------|
| `boot.py` | 135L | App startup | 10-12 |
| `logger.py` | 127L | Logging | 10-12 |
| `rate_limit.py` | 85L | Rate limiting | 8-10 |
| `auth.py` | 24L | Auth middleware | 5-6 |
| `security.py` | 24L | Security utils | 5-6 |
| `utils/exceptions.py` | 21L | Custom exceptions | 5-6 |
| `config.py` | 20L | Config loading | 4-5 |
| `database.py` | 20L | DB connections | 4-5 |
| `deps.py` | 9L | FastAPI deps | 3-4 |
| `utils/__init__.py` | 2L | Utils init | 1 |

**Test Strategy**:
- Unit tests for pure functions
- Integration tests for middleware
- Mock external dependencies (DB, Redis)
- Test configuration variations
- Test error conditions

**Success Criteria**:
- ✅ 99% overall coverage reached
- ✅ All utility functions tested
- ✅ Infrastructure edge cases covered

---

## Testing Best Practices

### 1. Test Organization
```
tests/
├── services/         # Service layer tests
├── routers/          # API endpoint tests
├── models/           # Model tests (already good)
├── schemas/          # Schema tests (already good)
├── utils/            # Utility tests
└── integration/      # End-to-end tests
```

### 2. Naming Convention
- **Unit tests**: `test_<function_name>_<scenario>.py`
- **Integration tests**: `test_<feature>_integration.py`
- **Example**: `test_generate_income_statement_with_zero_transactions.py`

### 3. Test Patterns

#### Service Tests (Unit)
```python
"""AC5.1.1: Income statement generation.

This test file verifies income statement generation:
- Revenue and expense aggregation
- Period filtering (YTD, MTD, custom)
- Multi-currency handling
"""

@pytest.mark.asyncio
async def test_generate_income_statement_basic(db_session, mock_accounts):
    """Generate income statement with basic transactions."""
    # Arrange
    service = ReportingService(db_session)
    
    # Act
    result = await service.generate_income_statement(
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31)
    )
    
    # Assert
    assert result.total_revenue == Decimal("100000.00")
    assert result.total_expenses == Decimal("60000.00")
    assert result.net_income == Decimal("40000.00")
```

#### Router Tests (Integration)
```python
"""Test /reports/income-statement endpoint.

Covers:
- Request validation
- Response format
- Authentication
- Error handling
"""

@pytest.mark.asyncio
async def test_income_statement_endpoint_success(client, auth_headers):
    """GET /reports/income-statement returns 200 with valid data."""
    response = await client.get(
        "/reports/income-statement",
        params={"start_date": "2024-01-01", "end_date": "2024-12-31"},
        headers=auth_headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "total_revenue" in data
    assert "total_expenses" in data
```

### 4. Coverage Measurement
```bash
# Run tests with coverage
moon run :test

# Generate HTML report
pytest --cov=src --cov-report=html

# View report
open htmlcov/index.html
```

---

## Implementation Timeline

### Week 1-2: Phase 1 (Core Services)
- Day 1-2: `services/reporting.py` (410L) - 40-50 tests
- Day 3-4: `services/reconciliation.py` (408L) - 50-60 tests
- Day 5-6: `services/fx_revaluation.py` (134L) - 15-20 tests
- Day 7-8: `services/assets.py` (132L) - 15-20 tests
- Day 9-10: Remaining P0 services (463L) - 54-70 tests

**Checkpoint**: 50% coverage reached

### Week 3: Phase 2 (Routers)
- Day 1-2: `routers/statements.py` (268L) - 25-30 tests
- Day 3: `routers/reconciliation.py` (166L) - 20-25 tests
- Day 4: `routers/reports.py` (108L) - 15-20 tests
- Day 5: Remaining large routers (229L) - 30-35 tests
- Day 6: Small routers (158L) - 20-25 tests

**Checkpoint**: 70% coverage reached

### Week 4: Phase 3 & 4 (AI + Infrastructure)
- Day 1-2: AI services (373L) - 45-54 tests
- Day 3-4: Infrastructure (467L) - 55-65 tests
- Day 5: Integration testing and edge cases
- Day 6-7: Coverage verification and gap filling

**Final Goal**: 99% coverage reached

---

## Risks & Mitigations

### Risk 1: Time Estimates Too Optimistic
**Mitigation**: 
- Start with one file as pilot (e.g., `services/reporting.py`)
- Adjust timeline based on actual velocity
- Prioritize by business impact

### Risk 2: Complex Business Logic Hard to Test
**Mitigation**:
- Load relevant skills: `domain/accounting`, `domain/reconciliation`, `domain/reporting`
- Consult oracle for complex scenarios
- Use existing test patterns as reference

### Risk 3: External Dependencies (OpenRouter, S3)
**Mitigation**:
- Use mocks for external services
- Test with `pytest-mock` or `unittest.mock`
- Verify mock behavior matches real API contracts

### Risk 4: Coverage Goal Too Ambitious (99%)
**Mitigation**:
- Accept 95%+ as success
- Document rationale for untested code
- Focus on business-critical paths first

---

## Success Metrics

### Quantitative
- [ ] Overall coverage: 99%
- [ ] Services coverage: 95%+
- [ ] Routers coverage: 95%+
- [ ] No critical business logic uncovered

### Qualitative
- [ ] All AC requirements have test coverage
- [ ] All error paths tested
- [ ] All edge cases documented
- [ ] Test execution time < 5 minutes

---

## Appendix A: Quick Start Guide

### Running Tests Locally
```bash
# Run all tests with coverage
moon run :test

# Run specific test file
pytest tests/services/test_reporting.py -v

# Run with coverage report
pytest --cov=src --cov-report=term-missing

# Run tests in parallel (faster)
pytest -n auto
```

### Writing New Tests
1. **Copy template** from existing test file
2. **Add AC reference** in docstring
3. **Follow AAA pattern**: Arrange → Act → Assert
4. **Use factories** for test data (see `tests/test_factories.py`)
5. **Mock external services** (OpenRouter, S3)

### Test Data Setup
```python
# Use async factories
account = await AccountFactory.create_async(
    db=db_session,
    type=AccountType.INCOME,
    currency="USD"
)

entry = await JournalEntryFactory.create_balanced_async(
    db=db_session,
    account=account,
    amount=Decimal("1000.00")
)
```

---

## Appendix B: Files by Priority

### Phase 1 - P0 Core Services (1,748L)
1. services/reporting.py (410L) - AC5.x
2. services/reconciliation.py (408L) - AC4.x
3. services/ai_advisor.py (224L) - AC13.x
4. services/fx_revaluation.py (134L) - AC5.1.2
5. services/assets.py (132L) - AC11.x
6. services/review_queue.py (128L) - AC4.3.x
7. services/processing_account.py (127L) - AC2.3.x
8. services/accounting.py (106L) - AC2.x
9. services/validation.py (102L) - AC4.2.x
10. services/openrouter_models.py (77L) - AI
11. services/openrouter_streaming.py (72L) - AI

### Phase 2 - P1 Routers (929L)
1. routers/statements.py (268L)
2. routers/reconciliation.py (166L)
3. routers/reports.py (108L)
4. routers/chat.py (88L)
5. routers/journal.py (72L)
6. routers/auth.py (69L)
7. routers/accounts.py (67L)
8. routers/assets.py (61L)
9. routers/ai_models.py (30L)

### Phase 3 - P3 Infrastructure (467L)
1. boot.py (135L)
2. logger.py (127L)
3. rate_limit.py (85L)
4. auth.py (24L)
5. security.py (24L)
6. utils/exceptions.py (21L)
7. config.py (20L)
8. database.py (20L)
9. deps.py (9L)
10. utils/__init__.py (2L)

### Already Good (33L)
- models/* (9L) - 97.8% coverage ✅
- schemas/* (24L) - 90.0% coverage ✅
- constants.py (0L) - 100% coverage ✅

---

**Total Estimated Tests**: 600-750 new test cases  
**Total Estimated LOC**: 12,000-15,000 lines of test code  
**Estimated Duration**: 4 weeks (1 engineer full-time)  

---

**Status**: ✅ Plan Complete  
**Next Step**: Begin Phase 1 with `services/reporting.py` (410L missing)
