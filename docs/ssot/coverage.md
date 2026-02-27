# Unified Test Coverage

> **SSOT Key**: `coverage`
> **Version**: 2.0.0
> **Last Updated**: 2026-02-27

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

**CI Threshold**: ≥ **40%** unified coverage (enforced via `COVERAGE_THRESHOLD` env var in CI)

**Current state** (as of this branch):

| Component | Covered | Executable | Coverage |
|-----------|---------|------------|----------|
| Backend   | 5,808   | 6,180      | 93.98%   |
| Frontend  | 238     | 1,669      | 14.26%   |
| Scripts   | 937     | 2,061      | 45.46%   |
| **Unified** | **6,983** | **9,910** | **70.46%** |

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
    # Fails if unified coverage < COVERAGE_THRESHOLD (default: 40)
```

### Coverage Calculation

`scripts/calculate_unified_coverage.py`:

1. Parses LCOV files (`LF:` = total executable lines, `LH:` = covered lines)
2. Uses LCOV `LF:` as denominator (NOT filesystem line counts)
3. Aggregates backend + frontend + scripts covered/executable counts
4. Reports unified percentage and exits 1 if below threshold

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
| CI      | 99%     | ~14% lines        | 40%          |
| Local   | 99%     | ~14% lines        | N/A          |

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
