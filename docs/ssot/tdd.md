# Test-Driven Development (TDD) Transformation Plan

> **SSOT Key**: `tdd-transformation`
> **Objective**: Transform development workflow to Test-Driven Development and maintain CI-enforced coverage quality.

---

## Executive Summary

**Current State**:
- Coverage threshold: No-regression policy (must not decrease from baseline, target 99%)
- Test files: 100
- Source files: 75
- Test-to-source ratio: 1.7:1 (22,655 test LOC / 13,162 source LOC)
- Well-organized test structure aligned with SSOT domains
- **CI Coverage Enforcement**: ✅ NOW ENFORCED (post-merge validation added)

**Target State**:
- Coverage threshold: 99% overall coverage (maintained)
- TDD-first development workflow
- Documented testing patterns and best practices
- Service layer coverage: 80%+ (currently 16.59%)

---

## Current Testing Infrastructure Analysis

### Test Configuration

| Component | Configuration | Location |
|------------|--------------|------------|
| **Test Framework** | pytest + pytest-asyncio + pytest-cov | `apps/backend/pyproject.toml` |
| **Coverage Tool** | pytest-cov with XML + terminal reports | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Local Threshold** | No decrease (baseline check) | `apps/backend/pyproject.toml` |
| **CI Threshold** | No decrease / 99% Target (post-merge validation) | `.github/workflows/ci.yml` |
| **Parallel Execution** | pytest-xdist (4 workers local, auto in CI) | `moon.yml` test-execution |
| **Database Lifecycle** | Auto-create/cleanup via context manager | `scripts/test_lifecycle.py` |

### Test Organization (Domain-Based)

Tests are organized by domain matching the source structure:

```
tests/
├── conftest.py          # Shared fixtures (db, client, test_user)
├── fixtures/            # Factory patterns
├── accounting/          # 20 test files
├── reconciliation/     # 13 test files
├── extraction/          # 18 test files
├── auth/                # 5 test files
├── ai/                  # 8 test files
├── assets/              # 4 test files
├── api/                 # 4 test files
├── reporting/           # 13 test files
├── market_data/         # 1 test file
├── infra/              # 12 test files
├── unit/                # 2 test files
└── e2e/                 # 4 test files (51 test functions)
```

**Total**: ~100 test files, ~675 test functions organized by feature domain

### Test Execution Modes

| Command | Description |
|---------|-------------|
| `moon run :test` | Run all tests (default, 99% coverage) |
| `moon run :test -- --fast` | TDD mode (no coverage, fastest) |
| `moon run :test -- --smart` | Coverage on changed files only |
| `moon run :test -- --e2e` | E2E tests (Playwright) |
| `moon run :test -- tests/accounting/` | Run specific module tests |
| `moon run :test -- tests/accounting/test_journal_service.py` | Run specific file |


## Test Case Numbering System (ACx.y.z)

> **Purpose**: Establish traceability between EPIC acceptance criteria and test implementations.

### Numbering Convention

**Format**: `ACx.y.z`

| Component | Meaning | Example |
|-----------|---------|---------|
| **AC** | Acceptance Criteria prefix | AC (fixed) |
| **x** | EPIC number (no zero padding) | 1, 2, 3 |
| **y** | Feature block within EPIC | 1, 2, 3 |
| **z** | Test case number within block | 1, 2, 3 |

**Examples**:
- `AC1.1.1` → EPIC-1 (EPIC-001), Block 1 (Authentication), Test case 1
- `AC2.3.5` → EPIC-2 (EPIC-002), Block 3 (Journal Entry Posting), Test case 5

### Feature Block Organization

Each EPIC should divide features into logical blocks:

**EPIC-001 Example** (Infrastructure & Authentication):
- **Block 1**: Backend Health Check
- **Block 2**: User Authentication (Registration/Login)
- **Block 3**: Database Connectivity
- **Block 4**: Docker Environment

**EPIC-002 Example** (Double-Entry Bookkeeping):
- **Block 1**: Account Management (CRUD)
- **Block 2**: Journal Entry Creation
- **Block 3**: Journal Entry Posting & Voiding
- **Block 4**: Balance Calculation
- **Block 5**: Accounting Equation Validation

### Test Case Documentation Requirements

#### In EPIC Documents

Each EPIC must include a **Test Cases** section with:

```markdown
## 🧪 Test Cases

### AC2.1: Account Management

| ID | Test Case | Test Function | Priority |
|----|-----------|---------------|----------|
| AC2.1.1 | Create account with valid data | `test_create_account()` | P0 |
| AC2.1.2 | Create account with duplicate code | `test_create_account_duplicate_code()` | P0 |
| AC2.1.3 | List accounts with type filter | `test_list_accounts_with_filters()` | P1 |

### AC2.2: Journal Entry Creation

| ID | Test Case | Test Function | Priority |
|----|-----------|---------------|----------|
| AC2.2.1 | Balanced entry passes validation | `test_balanced_entry_passes()` | P0 |
| AC2.2.2 | Unbalanced entry fails | `test_unbalanced_entry_fails()` | P0 |
```

#### In Test Code

Test functions MUST start with the AC number in docstring:

```python
@pytest.mark.asyncio
async def test_balanced_entry_passes():
    """AC2.2.1: Balanced entry passes validation.
    
    Verify that journal entries with equal debits and credits
    are accepted by the validation logic.
    """
    # Test implementation...
```

### Implementation Guidelines

#### 1. EPIC Document Update Checklist

When creating/updating an EPIC:
- [ ] Define feature blocks (x.y structure)
- [ ] Create test case table for each block
- [ ] Link test functions to AC IDs
- [ ] Reference test file paths

#### 2. Test Code Update Checklist

When writing tests:
- [ ] Add AC number in test docstring first line
- [ ] Follow naming: `test_<feature>_<scenario>()`
- [ ] Group tests by feature block (use pytest marks if needed)
- [ ] Update EPIC document with new test references

#### 3. Code Review Checklist

During PR review:
- [ ] New features have AC numbers assigned in EPIC
- [ ] Test docstrings include AC references
- [ ] EPIC test case table updated
- [ ] Test-to-AC traceability maintained

### Benefits

1. **Traceability**: Easy to find tests for acceptance criteria
2. **Coverage Verification**: Identify missing tests for AC blocks
3. **Communication**: Product/QA can reference test IDs
4. **Maintenance**: Track which tests validate which requirements

### Migration Strategy

**Phase 1**: Apply to EPIC-001 and EPIC-002 (pilot)
**Phase 2**: Apply to new EPICs going forward
**Phase 3**: Backfill existing EPICs (optional)

---

## TDD Transformation Strategy

### Phase 1: Documentation & Standards (Week 1)

**Objective**: Establish clear TDD guidelines and integrate into SSOT.

#### 1.1 Create TDD SSOT Document
**File**: `docs/ssot/tdd.md`

**Contents**:
1. TDD workflow (Red-Green-Refactor cycle)
2. Test organization patterns (unit → integration → e2e)
3. When to write tests first vs. tests after
4. Test naming conventions
5. Mocking guidelines (what to mock vs. what to test)
6. Coverage quality metrics (branch vs. line coverage)

#### 1.2 Update Development.md
**File**: `docs/ssot/development.md`

**Additions**:
- TDD workflow section
- Test-first development checklist
- Coverage requirements (99%)
- Test review process

#### 1.3 Create Testing Standards Checklist

**Checklist for PR reviews**:
```markdown
- [ ] New features have tests written FIRST
- [ ] Edge cases covered (null, empty, boundary values)
- [ ] Error handling tested
- [ ] Coverage maintained ≥ 99%
- [ ] No test-only changes (refactors should have tests updated)
```

---

### Phase 2: Coverage Threshold Upgrade (Week 1-2)

**Objective**: Raise coverage requirement and ensure CI enforcement.

**Status** (2026-02-25):
- Local coverage threshold: **99%** (`--cov-fail-under=99` in pyproject.toml)
- CI coverage threshold: **99%** (post-merge validation in ci.yml)
- Branch coverage tracking: enabled via `--cov-branch`
- **CI now enforces 99%**: Each shard runs ~25% of tests, merged coverage validated post-merge

#### 2.1 Local Configuration

```toml
# apps/backend/pyproject.toml
[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=term-missing --cov-report=xml --cov-branch --cov-fail-under=99 -m 'not slow'"
```

#### 2.2 CI Configuration

```yaml
# .github/workflows/ci.yml
- name: Validate 99% coverage threshold
  run: |
    pip install coverage
    coverage lcov --lcov-file=coverage.lcov --data-file=.coverage
    coverage report --include="src/*" --fail-under=99
```

---

### Phase 3: Coverage Gap Analysis (Week 2)

**Objective**: Identify and fix coverage gaps systematically.

#### 3.1 Current Coverage Status (2026-02-25)

| Layer | Coverage | Status |
|-------|----------|--------|
| **models/** | 97.76% | ✅ Excellent |
| **schemas/** | 97.93% | ✅ Excellent |
| **utils/** | 56.52% | ⚠️ Partial |
| **routers/** | 27.02% | ❌ Low |
| **services/** | 16.59% | ❌ CRITICAL GAP |

#### 3.2 Service Layer Coverage Gaps (CRITICAL)

| Service | Coverage | Risk |
|---------|----------|------|
| services/reporting.py | 9.29% | 🔴 Financial reports |
| services/fx_revaluation.py | 0% | 🔴 Currency gains/losses |
| services/reconciliation.py | 13.76% | 🔴 Matching engine |
| services/review_queue.py | 12.5% | 🔴 Approval workflow |
| services/validation.py | 11.3% | 🔴 Statement validation |
| services/classification.py | 0% | 🔴 Transaction categorization |

#### 3.3 Priority Matrix for Coverage Boost

| Priority | Module | Current Coverage | Target | Action |
|----------|--------|-----------------|--------|--------|
| P0 | **services/reporting** | 9.29% | 80% | Add error path tests |
| P0 | **services/reconciliation** | 13.76% | 80% | Add error path tests |
| P0 | **services/validation** | 11.3% | 80% | Add error path tests |
| P1 | **services/review_queue** | 12.5% | 80% | Add error path tests |
| P1 | **services/fx_revaluation** | 0% | 80% | Add FX tests |
| P2 | **routers/** | 27.02% | 60% | Add router error tests |

---

### Phase 4: Test-First Development Practices (Week 3-4)

**Objective**: Establish TDD workflow in daily development.

#### 4.1 Red-Green-Refactor Cycle

**Template for new features**:

```python
# 1. RED: Write failing test
@pytest.mark.asyncio
async def test_new_feature_expected_behavior():
    """Test that new feature works as expected."""
    # Setup
    # Exercise
    # Assert (will fail initially)
    pass

# 2. GREEN: Implement minimum to pass
# Add production code to make test pass

# 3. REFACTOR: Improve code without breaking tests
# Clean up, optimize, add more tests
```

#### 4.2 Test Organization Guidelines

**Test file structure**:
```python
# tests/domain/test_feature.py

import pytest
from src.services.feature import Feature

# 1. Unit tests (isolated, mocked dependencies)
@pytest.mark.asyncio
async def test_feature_unit_case():
    pass

# 2. Integration tests (real DB, no external APIs)
@pytest.mark.asyncio
async def test_feature_integration(db):
    pass

# 3. Edge cases
@pytest.mark.asyncio
async def test_feature_edge_case_null():
    pass

@pytest.mark.asyncio
async def test_feature_edge_case_empty():
    pass

# 4. Error cases
@pytest.mark.asyncio
async def test_feature_error_invalid_input():
    pass
```

#### 4.3 Mocking Guidelines

**DO mock**:
- External APIs (OpenRouter, S3, FX providers)
- File system operations (in unit tests)
- Time (for deterministic tests)
- Async background tasks (in unit tests)

**DO NOT mock**:
- Database (use test DB fixture)
- Business logic (test real implementation)
- Service layer (test via router endpoints)
- Internal utilities (test actual behavior)

---

### Phase 5: Continuous Improvement (Ongoing)

**Objective**: Maintain coverage quality and prevent regression.

#### 5.1 Pre-Commit Coverage Check

Add to `.pre-commit-config.yaml`:
```yaml
- repo: local
  hooks:
    - id: coverage-check
      name: Coverage check (99%)
      entry: uv run pytest --cov=src --cov-fail-under=99
      language: system
      pass_filenames: false
      always_run: true
```

#### 5.2 Coverage Dashboard

**Actions**:
- Coverage badge in README with threshold: 99%
- Coveralls reports align with local threshold
- Monitor coverage trends over time

#### 5.3 Test Quality Metrics

**Beyond line coverage**:
1. **Branch coverage**: Ensure all if/else branches tested
2. **Mutation testing**: Use `mutmut` to verify test quality
3. **Test complexity**: Keep cyclomatic complexity low
4. **Test execution time**: Identify slow tests for optimization

---

## Coverage Accuracy Verification

### Current Coverage Metrics

**Configuration**:
```toml
[tool.coverage.run]
source = ["src"]
omit = [
    "src/__init__.py",
    "src/models/__init__.py",
    "src/schemas/__init__.py",
    "src/schemas/user.py",
    "src/services/__init__.py",
    "src/routers/__init__.py",
    "src/routers/users.py",
    "src/services/extraction.py",
    "src/prompts/*",
    "src/main.py",
    "src/env_smoke_test.py",
    "src/env_check.py",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "if __name__ == .__main__.:",
]
```

### Accuracy Concerns & Fixes

| Concern | Status | Action |
|---------|--------|--------|
| **Exclusions are appropriate** | ✅ Correct | `__init__.py`, `main.py`, prompts excluded correctly |
| **Exclude external API calls** | ✅ Correct | Integration tests cover extraction.py |
| **Database setup code excluded** | ✅ Correct | Bootloader checks excluded |
| **Branch coverage vs. line coverage** | ✅ Fixed | `--cov-branch` added |
| **CI coverage enforcement** | ✅ Fixed | Post-merge validation added |

---

## TDD Workflow Documentation

### Before Writing Code

1. **Read SSOT** for the domain (e.g., `accounting.md`)
2. **Identify test cases**:
   - Happy path (normal operation)
   - Edge cases (boundary values, null, empty)
   - Error cases (invalid inputs, failures)
3. **Write failing tests** (RED)

### After Tests Pass (GREEN)

1. **Run all tests** to ensure no regressions
2. **Check coverage** meets 99%
3. **Refactor** code for readability and performance
4. **Update documentation** if behavior changed

### Code Review Checklist

```markdown
## Test Coverage
- [ ] Coverage ≥ 99%
- [ ] Branch coverage verified
- [ ] Edge cases tested
- [ ] Error handling tested
- [ ] No pragma: no cover (unless justified)

## TDD Compliance
- [ ] Tests written before implementation
- [ ] Tests organized by domain (SSOT-aligned)
- [ ] Test names describe behavior (not implementation)
- [ ] No test-only commits
```

---

## Migration Timeline

| Week | Milestone | Deliverable |
|-------|------------|-------------|
| **1** | Documentation & Threshold Update | `docs/ssot/tdd.md`, `development.md` updated, 99% threshold |
| **2** | Coverage Gap Analysis | Detailed coverage report, gap identification |
| **3** | Core Domain Coverage Boost | Accounting & reconciliation at 99% |
| **4** | Feature Coverage Boost | Extraction, reporting, auth at 99% |
| **5** | CI Coverage Enforcement | Post-merge validation (COMPLETED) |
| **6+** | Continuous Improvement | Maintain 99%, add quality metrics |

---

## Success Criteria

**Quantitative**:
- [x] Line coverage ≥ 99% (verified by pytest-cov)
- [x] CI coverage enforcement added (post-merge validation)
- [ ] Service layer coverage ≥ 80%
- [ ] Zero regressions in coverage after PRs
- [ ] Test execution time < 30s for unit+integration

**Qualitative**:
- [ ] Developers follow TDD workflow
- [ ] Tests document expected behavior (not just cover lines)
- [ ] Code review includes test quality assessment
- [ ] Coverage gaps are rare and addressed quickly

---

## Resources

### Internal References
- [development.md](./development.md) - Development workflow
- [accounting.md](./accounting.md) - Accounting domain
- [reconciliation.md](./reconciliation.md) - Reconciliation domain
- [extraction.md](./extraction.md) - Statement parsing
- [reporting.md](./reporting.md) - Financial reports

### External References
- [pytest documentation](https://docs.pytest.org/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [mutation testing with mutmut](https://github.com/mutmut/mutmut)
- [Testing best practices](https://docs.pytest.org/en/stable/best-practices.html)

---

> **Last Updated**: 2026-02-25
> **Owner**: Development Team
> **Review Cycle**: Quarterly
