# Unified Test Coverage

> **SSOT Key**: `coverage`
> **Version**: 2.0.0
> **Last Updated**: 2026-03-02

This document defines the **Unified Test Coverage System** for the Finance Report project.

---

## Overview

### Philosophy

Coverage is measured using **LCOV executable lines** (`LF:` field) as the denominator — the same standard used by all industry-standard coverage tools (Istanbul, pytest-cov, gcov). This measures only executable statements, not blank lines, comments, or type declarations.

### Unified Metric

```
unified_coverage = total_covered_lines / total_executable_lines
                 = (backend_covered + frontend_covered + scripts_covered) /
                   (backend_executable + frontend_executable + scripts_executable)
```

**CI Gate**: No-regression baseline comparison (zero tolerance for drops). No fixed minimum threshold enforced.

**Current state** (as of this branch):

| Component | Covered | Executable | Coverage |
|-----------|---------|------------|----------|
| Backend   | 5,808   | 6,180      | 94.48%   |
| Frontend  | 1,420   | 1,669      | 85.08%   |
| Scripts   | 1,402   | 2,061      | 68.02%   |
| **Unified** | **8,630** | **9,910** | **87.08%** |

---

## Components

### Backend Coverage

- **Tool**: pytest + pytest-cov
- **Config**: `apps/backend/pyproject.toml`
- **Output**: `coverage-backend-{shard}.lcov` (4 shards, merged into `coverage/backend.lcov`)
- **Excluded**:
  - `tests/**`
  - `migrations/**`
  - `__init__.py` files

### Frontend Coverage

- **Tool**: vitest with v8 coverage provider
- **Config**: `apps/frontend/vitest.config.ts`
- **Output**: `apps/frontend/coverage/lcov.info` (copied to `coverage/frontend.lcov` in CI)
- **LCOV paths**: `SF:` entries are relative to `apps/frontend` (for example, `src/app/page.tsx`); Coveralls uploads must use `base-path: apps/frontend`.
- **Key config**: `all: true` — ensures ALL source files appear in LCOV, not just those imported by tests
- **Excluded**:
  - `**/tests/**`, `**/__tests__/**`
  - `**/*.test.ts`, `**/*.spec.ts`
  - `**/*.config.*`, `**/types/**`

### Scripts Coverage

- **Tool**: pytest-cov
- **Output**: `coverage-scripts.lcov`

---

## CI Integration

### Workflow

```yaml
jobs:
  backend:
    # 4 shards → coverage-backend-{0..3}.lcov

  frontend:
    # vitest --coverage → lcov.info
    # copies to coverage/frontend.lcov artifact

  unified-coverage:
    needs: [backend, frontend]
    # Downloads all artifacts
    # Merges backend shards → coverage/backend.lcov
    # Runs: python scripts/calculate_unified_coverage.py
    # Fails if coverage drops below baseline (no-regression gate); no fixed minimum threshold
```

### Coverage Calculation

`scripts/calculate_unified_coverage.py`:

1. Parses LCOV files (`LF:` = total executable lines, `LH:` = covered lines)
2. Uses LCOV `LF:` as denominator (NOT filesystem line counts)
3. Aggregates backend + frontend + scripts covered/executable counts
4. Reports unified percentage and exits 1 if coverage dropped below baseline

---

### Coverage Gate

The CI workflow uses baseline comparison to prevent coverage regressions. There is no fixed minimum threshold.

- **Rationale**: No-regression is the primary gate; coverage must not drop from the committed baseline.

#### How It Works
1. **Primary gate**: Baseline comparison (zero tolerance for drops)
   - Compares current coverage against `unified-coverage.json` baseline
   - Fails CI if ANY component drops below baseline
   - See [No-Regression Coverage Gate](./development.md#no-regression-coverage-gate) for details
2. **Safety net**: Threshold check (optional)
   - `COVERAGE_THRESHOLD` defaults to `0` (disabled)
   - Set explicitly in CI if a minimum floor is desired
   - Acts as fallback when baseline file doesn't exist
#### Adjusting the Threshold

The threshold may be adjusted based on project needs:

- **Raise threshold**: When a minimum floor is desired (e.g., set to 80 for a hard floor)
- **Lower threshold**: Set to 0 to disable (default)
- **Update process**:
  1. Update `COVERAGE_THRESHOLD` in `.github/workflows/ci.yml`
  2. Update this documentation
  3. Ensure current coverage exceeds new threshold
**Note**: If no threshold is set (`COVERAGE_THRESHOLD=0` or unset), only the no-regression baseline gate applies.

---

## Local Development

### Running Tests with Coverage

```bash
# Backend tests with coverage (recommended via moon)
moon run :test

# Frontend tests with coverage
cd apps/frontend && npx vitest run --coverage

# Calculate unified coverage locally
cp apps/frontend/coverage/lcov.info coverage/frontend.lcov
python scripts/calculate_unified_coverage.py
```

### Coverage Thresholds

| Mode    | Backend | Frontend (vitest) | Unified (CI) |
|---------|---------|-------------------|--------------|
| CI      | 90%     | ~85% lines        | 96%          |
| Local   | 90%     | ~85% lines        | 96% (unified)|

> **Note**: Frontend vitest thresholds are auto-updated by `autoUpdate: true` in `vitest.config.ts`. They reflect actual measured coverage across all 50 source files (including untested pages that score 0%), so the threshold is intentionally low while overall quality is tracked at the unified level.

---

## Configuration Files

### Backend: `apps/backend/pyproject.toml`

```toml
[tool.coverage.run]
source = ["src"]
omit = [
    "__init__.py",
    "models/__init__.py",
    "schemas/__init__.py",
    "schemas/user.py",
    "services/__init__.py",
    "routers/__init__.py",
    "routers/users.py",
    "main.py",
    "tests/**",
    "migrations/**",
]
```

### Frontend: `apps/frontend/vitest.config.ts`

```typescript
coverage: {
  provider: 'v8',
  reporter: ['text', 'json', 'html', 'lcov'],
  all: true,                        // Include ALL src files, even untested ones
  include: ['src/**/*.{ts,tsx}'],   // Scope to source only
  exclude: [
    'node_modules/', '.next/', 'coverage/',
    '**/tests/**', '**/__tests__/**',
    '**/*.test.ts', '**/*.test.tsx',
    '**/*.spec.ts', '**/*.spec.tsx',
    '**/vitest.setup.ts', '**/*.config.*', '**/types/**',
  ],
  thresholds: {
    lines: 14,       // auto-updated by autoUpdate:true
    functions: 9,
    branches: 9,
    statements: 13,
    autoUpdate: true,
  },
}
```

---

## Excluded Patterns

| Pattern | Reason |
|---------|--------|
| `/test/`, `/tests/`, `__tests__/` | Test directories |
| `test_`, `_test.py`, `.test.ts`, `.spec.ts` | Test files |
| `conftest.py`, `vitest.setup.ts` | Test configuration |
| `*.config.*` | Build/tool configuration |
| `__init__.py` | Package init files (no logic) |
| `migrations/**` | Database migrations |
| `types/**` | Type-only declaration files |

---

## Troubleshooting

### Unified coverage appears wrong locally

The unified calculator reads `coverage/frontend.lcov`. After running vitest, copy:

```bash
cp apps/frontend/coverage/lcov.info coverage/frontend.lcov
python scripts/calculate_unified_coverage.py
```

### Frontend vitest thresholds fail after adding `all: true`

With `all: true`, all 50 source files appear in coverage including untested pages (score 0%). This lowers the threshold from the old "tested files only" number (~66%) to the true "all files" number (~14%). This is **correct and expected** — the old number was misleading.

### CI fails with coverage error

```bash
# Download and inspect artifacts
gh run download <run-id>
python scripts/calculate_unified_coverage.py
cat unified-coverage.json
```

---

## Future Improvements

1. **Frontend page tests**: Add tests for Next.js page components to raise frontend coverage
2. **Coverage trends**: Track coverage over time with historical data
3. **Per-PR coverage delta**: Report coverage change per PR (not just absolute)

---

## Coverage Metrics Verification

> *Merged from coverage-verification.md. Consolidated per SSOT deduplication policy.*

## Current Coverage Configuration

### Coverage Tool Configuration

| Component | Setting | Location |
|-----------|---------|---------|
| **Tool** | pytest-cov (built into pytest) | `apps/backend/pyproject.toml` |
| **Current Threshold** | 90% backend (enforced by CI); 96% unified | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Target Threshold** | 96% unified (backend + frontend + scripts) | `calculate_unified_coverage.py` |
| **Branch Coverage** | Enabled via `--cov-branch` | `pyproject.toml` |
| **Source Scope** | `src/` directory | `pyproject.toml` `[tool.coverage.run]` |
| **Output Formats** | XML, terminal, LCOV | `pyproject.toml` |

### Coverage Threshold Update History

| Date | Threshold | Reason | Status |
|-------|-----------|---------|--------|
| 2026-01-29 (Initial) | 95% → 97% | TDD transformation goal | Reverted to 95% (pending coverage improvement) |
| 2026-01-29 | 97% → 95% | Allow current PRs to pass | Temporary |
| 2026-03 (Current) | 90% backend; 96% unified | TDD transformation + unified coverage system | ✅ Active |

**Note**: Branch coverage (`--cov-branch`) remains enabled for stricter quality control regardless of threshold.

### Coverage Threshold Update (2026-01-29)

**Before**:
```toml
addopts = "--cov=src --cov-report=term-missing --cov-report=xml --cov-fail-under=95 -m 'not slow'"
```
**After**:
```toml
addopts = "--cov=src --cov-report=term-missing --cov-report=xml --cov-branch --cov-fail-under=90 -m 'not slow' -n 4"
```

**Changes**:
1. Threshold: 95% → **90%** backend (unified system handles overall quality at 96%)
2. Added `--cov-branch`: Now tracks branch coverage (stricter)
3. Applies to: All test runs (local, CI, PR tests)

---

## Coverage Metrics Accuracy

### Line vs. Branch Coverage

| Metric | Description | Requirement |
|---------|-------------|-------------|
| **Line Coverage** | Percentage of executable lines executed | ≥ 90% backend / 96% unified |
| **Branch Coverage** | Percentage of conditional branches taken | ≥ 95% (implied by line) |

**Why Branch Coverage Matters**:
```python
# Line coverage: 100% (both lines execute)
if condition:
    do_a()
else:
    do_b()

# Branch coverage: 50% (only tested one path)
```

With `--cov-branch`, we ensure all logical paths are tested.

### Exclusions Review

**Current exclusions** (from `pyproject.toml`):

| File/Pattern | Reason | Status |
|---------------|--------|--------|
| `src/__init__.py` | Package init, no logic | ✅ Correct |
| `src/models/__init__.py` | Model exports | ✅ Correct |
| `src/schemas/__init__.py` | Schema exports | ✅ Correct |
| `src/prompts/*` | AI prompt templates (non-code) | ✅ Correct |
| `src/main.py` | Application entry point | ✅ Correct |
| `src/env_smoke_test.py` | Environment check script | ✅ Correct |
| `src/env_check.py` | Environment validation script | ✅ Correct |
| `src/services/extraction.py` | Covered by integration tests only | ⚠️ Verify |

**Assessment**: Exclusions are appropriate. All production code paths should be tested via other files or integration tests.

### Coverage Exclusion Lines

**Patterns that are not counted against coverage** (from `[tool.coverage.report]`):

```toml
exclude_lines = [
    "pragma: no cover",        # Explicitly marked as non-testable
    "if TYPE_CHECKING:",        # Type checking imports only
    "if __name__ == .__main__.:",  # Script entry points
]
```

**Verification**: These are standard pytest-cov exclusions and appropriate.

---

## Coverage Analysis Tools

### Coverage Analyzer Script

**Location**: `scripts/coverage_analyzer.py`

**Purpose**: Automated coverage gap analysis and recommendation generation.

**Usage**:
```bash
# Generate coverage report
python scripts/coverage_analyzer.py --format term

# Generate HTML report for detailed analysis
python scripts/coverage_analyzer.py --format html

# Generate recommendations
python scripts/coverage_analyzer.py --suggest
```

**Features**:
1. Parses missing lines from coverage report
2. Identifies common patterns (exceptions, edge cases, async paths)
3. Generates targeted recommendations
4. Estimates module-level coverage

### Manual Coverage Report

**Generate detailed HTML report**:
```bash
cd apps/backend
uv run pytest --cov=src --cov-report=html
# Open: htmlcov/index.html
```

**Generate XML report** (for CI):
```bash
uv run pytest --cov=src --cov-report=xml --cov-report=lcov
```

---

## Coverage Reporting Pipeline

### Local Development

1. **Run tests**: `moon run :test`
2. **View terminal output**: See missing lines in real-time
3. **Generate HTML**: `uv run pytest --cov=src --cov-report=html`
4. **Open in browser**: `open htmlcov/index.html`

### Continuous Integration (GitHub Actions)

**Workflow**: `.github/workflows/ci.yml`

```yaml
- name: Run Tests
  run: moon run :lint && moon run :test

- name: Upload Coverage
  uses: coverallsapp/github-action@v2
  with:
    file: apps/backend/coverage.lcov
    flag-name: backend
    parallel: true
```

**Enforcement**: pytest-cov exits with error code if backend coverage < 90%; unified coverage gate enforces 96% across all components.

### Coveralls Integration

**Badge**: README shows real-time coverage from Coveralls
**Update frequency**: After every CI run
**Comparison**: CI coverage should match Coveralls badge

---

## Coverage Quality Metrics

### Beyond Line Coverage

**96% unified coverage is the minimum threshold**. For true quality, consider:

| Metric | Tool | Target |
|---------|-------|--------|
| **Mutation Testing** | `mutmut`, `cosmic-ray` | Kill > 80% of mutants |
| **Cyclomatic Complexity** | `radon`, `lizard` | Average < 10 per function |
| **Test Execution Time** | pytest `-durations` | Unit tests < 0.5s, Integration < 2s |
| **Flaky Tests** | `pytest-xdist` | Zero flaky tests |

### Code Review Checklist

When reviewing coverage gaps:

```markdown
## Coverage Assessment
 [ ] Unified coverage ≥ 96% (run `python scripts/calculate_unified_coverage.py`)
- [ ] Branch coverage verified with `--cov-branch`
- [ ] No `pragma: no cover` without justification
- [ ] Missing lines are truly non-testable (not just untested)

## Test Quality
- [ ] Tests document expected behavior (not just cover lines)
- [ ] Edge cases covered (null, empty, boundary values)
- [ ] Error handling tested
- [ ] No test-only code (logic in production)
```

---

## Troubleshooting

### Coverage Not Increasing

**Symptom**: Coverage stuck at same percentage despite adding tests.

**Checks**:
1. **Verify test files are discovered**: `uv run pytest --collect-only`
2. **Check for duplicates**: Ensure new tests aren't masked by existing ones
3. **Verify test markers**: `-m 'not slow'` might be excluding new tests
4. **Check fixtures**: Tests might be using wrong fixtures or session scope

### Coverage Over-Reported

**Symptom**: Coverage shows > 100% or inconsistent numbers.

**Causes**:
1. **Cached data**: Delete `apps/backend/.coverage` and re-run
2. **Source path mismatch**: Verify `source = ["src"]` in config
3. **Parallel test execution**: Ensure `pytest-xdist` doesn't duplicate coverage data

### False Positives

**Symptom**: Coverage says 100% but code has bugs.

**Solutions**:
1. **Enable branch coverage**: `--cov-branch` flag
2. **Mutation testing**: Test that tests actually validate logic
3. **Integration tests**: Add end-to-end tests beyond unit tests

---

## Success Criteria

**Quantitative**:
 [ ] All PRs maintain ≥ 96% unified coverage (no-regression gate)
 [ ] CI fails if unified coverage drops below baseline
- [ ] Branch coverage tracked via `--cov-branch`
- [ ] Coveralls badge reflects actual coverage

**Qualitative**:
- [ ] Missing coverage gaps are addressed within 24 hours
- [ ] CoverageAnalyzer script identifies actionable improvements
- [ ] Code reviews include coverage quality assessment
- [ ] New features follow TDD workflow (tests written first)

---

## References

### Internal
- [tdd.md](./tdd.md) - TDD transformation plan
- [development.md](./development.md) - Development workflow

### External
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [coverage.py documentation](https://coverage.readthedocs.io/)
- [Coveralls documentation](https://coveralls.io/docs/)

---

> **Last Updated**: 2026-02-23
> **Owner**: Development Team
> **Review Cycle**: Monthly
