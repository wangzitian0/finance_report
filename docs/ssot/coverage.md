# Unified Test Coverage

> **SSOT Key**: `coverage`
> **Version**: 2.0.0
> **Version scope**: Coverage policy semantics only; live baseline values are
> owned by `unified-coverage.json` and CI artifacts.

This document defines the **Unified Test Coverage System** for the Finance Report project.

---

## Overview

### Philosophy

Coverage is measured using **LCOV executable lines** (`LF:` field) as the denominator — the same standard used by all industry-standard coverage tools (Istanbul, pytest-cov, gcov). This measures only executable statements, not blank lines, comments, or type declarations.

### Unified Metric

```
unified_coverage = total_covered_lines / total_executable_lines
                 = (backend_covered + frontend_covered + common_covered + tools_covered) /
                   (backend_executable + frontend_executable + common_executable + tools_executable)
```

### Current Coverage Scope (as implemented 2026-05-29)

- Unified coverage is **line-only** and scope-bound: it currently includes backend, frontend, common, and tools LCOV inputs only.
- Backend unified LCOV coverage in CI is generated from fast shard output:
  `pytest ... -m "not slow and not e2e and not integration"`.
- `integration` and Tier-1 `e2e` backend tests are now executed as dedicated CI stages (`backend-integration`, `backend-e2e-tier1`) and run as behavior-only gates.
  They are intentionally excluded from unified coverage merge in this PR; LCOV is not collected in these stages until policy explicitly opts in.
- AC metrics are separate by design: AC pass rate and AC traceability are behavior/reference gates, not line-coverage arithmetic.
- `common/coverage/policy.py` plus policy-aware auditors ensure these exact four scopes remain the unified denominator.

**Unified CI Gate**: No-regression baseline comparison (zero tolerance for drops), plus a source tree vs LCOV policy audit. No fixed minimum unified threshold is enforced.

**Baseline ownership**: Component line counts, coverage percentages, and
committed no-regression floors are generated facts. Read
`unified-coverage.json`, CI artifacts, or Coveralls for current values; do not
copy those numbers into prose docs.

---

## Components

The authoritative component/file policy lives in `common/coverage/policy.py`. Coverage tools must emit LCOV source paths that match that policy:

| Component | Source Root | LCOV Path Prefix | Main Report |
|-----------|-------------|------------------|-------------|
| Backend | `apps/backend/src` | `src/...` relative to `apps/backend` | `coverage/backend.lcov` |
| Frontend | `apps/frontend/src` | `src/...` relative to `apps/frontend` | `coverage/frontend.lcov` |
| Common | `common` | `common/...` relative to repo root | `coverage/common.lcov` |
| Tools | `tools` | `tools/...` relative to repo root | `coverage/tools.lcov` |

`tools/check_coverage_policy.py` compares the source tree against LCOV `SF:` entries in CI. It fails when an eligible source file is missing from LCOV, or when an excluded/nonexistent file appears in LCOV. This is the guardrail that keeps new modules on the same coverage denominator automatically.

`tools/build_unified_lcov.py` rewrites component-relative LCOV paths into repository-root-relative paths before uploading to Coveralls. For example, backend `SF:src/services/example.py` becomes `SF:apps/backend/src/services/example.py`, and frontend `SF:src/app/page.tsx` becomes `SF:apps/frontend/src/app/page.tsx`.

Coveralls upload LCOV files are line-only. CI strips `BRDA:`, `BRF:`, and
`BRH:` records before upload so Coveralls percentages track the same line
coverage metric as `tools/calculate_unified_coverage.py`. Branch coverage may
still be collected by test tools, but it is not part of the unified coverage
gate or Coveralls reporting percentage.

### Backend Coverage

- **Tool**: pytest + pytest-cov
- **Config**: `apps/backend/pyproject.toml`
- **Output**: `coverage-backend-{shard}.lcov` (6 shards, merged into `coverage/backend.lcov`)
- **Excluded**:
  - `tests/**`
  - `migrations/**`
  - `__init__.py` files
  - `src/main.py`

### Frontend Coverage

- **Tool**: vitest with v8 coverage provider
- **Config**: `apps/frontend/vitest.config.ts`
- **Output**: `apps/frontend/coverage/lcov.info` (copied to `coverage/frontend.lcov` in CI)
- **LCOV paths**: `SF:` entries are relative to `apps/frontend` (for example, `src/app/page.tsx`); Coveralls uploads must use `base-path: apps/frontend`.
- **Coveralls upload**: frontend/unified Coveralls uploads run on PRs and `main` pushes for reporting visibility; local deterministic gates remain the only CI pass/fail authority. Coveralls contexts such as `coverage/coveralls`, `coverage/coveralls (push)`, `Coveralls - unified`, and future `coverage/coveralls ...` or `Coveralls...` contexts are external reporting signals only. CI uploads line-only LCOV files so Coveralls does not blend branch counters into the unified percentage, and CI does not require Coveralls contexts for mergeability.
- **Key config**: `include: ['src/**/*.{ts,tsx}']` plus the shared policy audit ensures source files appear in LCOV consistently.
- **Excluded**:
  - `**/tests/**`, `**/__tests__/**`
  - `**/*.test.ts`, `**/*.spec.ts`
  - `**/*.config.*`, `**/types/**`

### Tools Coverage

- **Tool**: pytest-cov from the tooling test suite
- **Output**: `coverage-tools.lcov`
- **CI Output**: `coverage/tools.lcov`
- **Scope**: command entry points only; reusable implementation belongs in `common/`
- **Excluded**:
  - Package `__init__.py` files
  - Python test modules under `tools/`

### Common Coverage

- **Tool**: pytest-cov from the tooling test suite
- **Output**: `coverage-common.lcov`
- **CI Output**: `coverage/common.lcov`
- **Excluded**:
  - Package `__init__.py` files
  - Python test modules under `common/`

---

## CI Integration

### Workflow

```yaml
jobs:
  backend:
    # 6 shards → coverage-backend-{1..6}.lcov

  frontend:
    # vitest --coverage → lcov.info
    # copies to coverage/frontend.lcov artifact

  unified-coverage:
    needs: [backend, frontend]
    # Downloads all artifacts
    # Merges backend shards → coverage/backend.lcov
    # Runs: python tools/calculate_unified_coverage.py
    # Runs: python tools/check_coverage_policy.py
    # Fails if coverage drops below baseline (no-regression gate); no fixed minimum threshold
    # Builds repository-root-relative, line-only backend + frontend + common + tools LCOV for Coveralls
```

### Coverage Calculation

`tools/calculate_unified_coverage.py`:

1. Parses LCOV files (`LF:` = total executable lines, `LH:` = covered lines)
2. Uses LCOV `LF:` as denominator (NOT filesystem line counts)
3. Aggregates backend + frontend + common + tools covered/executable counts
4. Reports unified percentage and exits 1 if coverage dropped below baseline
5. Lists file-level low coverage from the same component LCOV files when run
   with `--list-low-files`

File-level coverage audits must use the same LCOV inputs as the unified gate,
not `coverage.py report` text output or stale component-local artifacts:

```bash
python tools/build_unified_lcov.py coverage/unified.lcov
python tools/strip_lcov_branches.py coverage/unified.lcov coverage/coveralls-unified.lcov
python tools/calculate_unified_coverage.py --list-low-files --threshold 90
```

The `--threshold` flag applies only to the printed file-level low-coverage
report. The CI pass/fail gate remains the no-regression comparison against
`unified-coverage.json`.

---

### Coverage Gate

The CI workflow uses baseline comparison to prevent coverage regressions. There is no fixed minimum threshold.

- **Rationale**: No-regression is the primary gate; coverage must not drop from the committed baseline.
- **External reporting**: Coveralls remains enabled for historical visibility, but local deterministic gates decide whether CI fails. Coveralls status contexts are not required checks and CI does not publish synthetic GitHub statuses for them. External Coveralls failures must not fail CI or block post-merge staging.

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
python tools/calculate_unified_coverage.py
```

### Coverage Thresholds

| Mode    | Backend | Frontend (vitest) | Unified (CI) |
|---------|---------|-------------------|--------------|
| CI      | 90%     | 99% lines         | No regression from baseline |
| Local   | 90%     | 99% lines         | No regression from baseline |

> **Note**: The unified baseline is the primary cross-component gate. Frontend vitest keeps its own local line/function/branch floors, while CI also verifies that frontend LCOV files match the shared policy. Coveralls receives line-only LCOV files so its percentages match the unified line coverage gate.

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
    "services/__init__.py",
    "routers/__init__.py",
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
  include: ['src/**/*.{ts,tsx}'],   // Scope to source only
  exclude: [
    'node_modules/', '.next/', 'coverage/',
    '**/tests/**', '**/__tests__/**',
    '**/*.test.ts', '**/*.test.tsx',
    '**/*.spec.ts', '**/*.spec.tsx',
    '**/vitest.setup.ts', '**/*.config.*', '**/types/**',
  ],
  thresholds: {
    lines: 99,
    functions: 80,
    branches: 70,
    statements: 87,
    autoUpdate: false,
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
python tools/calculate_unified_coverage.py
```

### Coverage policy audit fails after adding a module

The new source file must either appear in the matching LCOV report or be explicitly excluded in `common/coverage/policy.py`. Prefer adding tests/import coverage for real modules. Only exclude generated, type-only, test-only, or entrypoint files.

### CI fails with coverage error

```bash
# Download and inspect artifacts
gh run download <run-id>
python tools/calculate_unified_coverage.py
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
| **Current Threshold** | 90% backend; no-regression unified baseline | `pyproject.toml`, `unified-coverage.json` |
| **Target Threshold** | Ratchet unified baseline upward when coverage improves | `calculate_unified_coverage.py` |
| **Branch Coverage** | Enabled via `--cov-branch` | `pyproject.toml` |
| **Source Scope** | `src/` directory | `pyproject.toml` `[tool.coverage.run]` |
| **Output Formats** | XML, terminal, LCOV | `pyproject.toml` |

### Coverage Threshold Update History

| Date | Threshold | Reason | Status |
|-------|-----------|---------|--------|
| 2026-01-29 (Initial) | 95% → 97% | TDD transformation goal | Reverted to 95% (pending coverage improvement) |
| 2026-01-29 | 97% → 95% | Allow current PRs to pass | Temporary |
| 2026-03 | 90% backend; no-regression unified | TDD transformation + unified coverage system | ✅ Active |
| 2026-05 (Current) | 90% backend; 94.38% unified floor | AC8.13.15 coverage policy unification | ✅ Active |

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
1. Threshold: 95% → **90%** backend (unified no-regression handles overall quality)
2. Added `--cov-branch`: Now tracks branch coverage (stricter)
3. Applies to: All test runs (local, CI, PR tests)

---

## Coverage Metrics Accuracy

### Line vs. Branch Coverage

| Metric | Description | Requirement |
|---------|-------------|-------------|
| **Line Coverage** | Percentage of executable lines executed | ≥ 90% backend / no unified regression |
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

**Location**: `tools/coverage_analyzer.py`

**Purpose**: Automated coverage gap analysis and recommendation generation.

**Usage**:
```bash
# Generate coverage report
python tools/coverage_analyzer.py --format term

# Generate HTML report for detailed analysis
python tools/coverage_analyzer.py --format html

# Generate recommendations
python tools/coverage_analyzer.py --suggest
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

**Enforcement**: pytest-cov exits with error code if backend coverage < 90%; the unified gate prevents regressions against `unified-coverage.json` across all components.

### Coveralls Integration

**Badge**: README shows real-time coverage from Coveralls.
**Update frequency**: After every CI run.
**Reporting-only status**: Coveralls badge and contexts are reporting-only. The
authoritative coverage gate is the local CI calculation against
`unified-coverage.json`, aggregated by `finish`.
**Comparison**: Coveralls receives line-only LCOV files so its coverage
percentage should track the local line metric, but Coveralls may still report a
different external comparison baseline. Branch coverage is collected separately
and stripped from Coveralls upload LCOV files.

---

## Coverage Quality Metrics

### Beyond Line Coverage

**Unified coverage must not regress from the committed baseline**. For true quality, consider:

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
 [ ] Unified coverage has no baseline regression (run `python tools/calculate_unified_coverage.py`)
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
 [ ] All PRs maintain or improve unified coverage from baseline
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

> **Owner**: Development Team
> **Review cycle owner**: Track review cadence outside this prose file; this
> document owns policy semantics, not live review status.
