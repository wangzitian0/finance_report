# Unified Test Coverage

> **SSOT Key**: `coverage`
> **Version**: 1.0.0
> **Last Updated**: 2026-02-26

This document defines the **Unified Test Coverage System** for the Finance Report project.

---

## Overview

### Philosophy

We coverage system uses a **blacklist approach**: all `.py`, `.ts`, `.tsx`, `.sh` files count as code, EXCEPT:
- Files in `/test/`, `/tests/`, `__tests__/` directories
- Files starting with `test_` or ending with `_test.py`, `.test.ts`, `.spec.ts`
- Configuration files (`*.config.*`, `conftest.py`)

### Unified Metric

```
unified_coverage = covered_lines / (backend_lines + frontend_lines + scripts_lines)
```

**Target**: 80% unified coverage

---

## Components

### Backend Coverage

- **Tool**: pytest + pytest-cov
- **Config**: `apps/backend/pyproject.toml`
- **Output**: `coverage-backend-{shard}.lcov`
- **Blacklist patterns**:
  - `tests/**`
  - `migrations/**`
  - `__init__.py` files

### Frontend Coverage

- **Tool**: vitest with v8 coverage provider
- **Config**: `apps/frontend/vitest.config.ts`
- **Output**: `coverage/lcov.info`
- **Blacklist patterns**:
  - `**/tests/**`
  - `**/__tests__/**`
  - `**/*.test.ts`
  - `**/*.spec.ts`
  - `**/*.config.*`

### Scripts Coverage

- **Tool**: pytest-cov (for scripts with tests)
- **Config**: N/A (scripts are tested via backend test runner)
- **Output**: `coverage-scripts.lcov`
- **Note**: Most scripts are utilities without dedicated tests

---

## CI Integration

### Workflow

```yaml
jobs:
  backend:
    # Runs 4 shards of backend tests
    # Each shard produces coverage-backend-{n}.lcov

  frontend:
    # Runs frontend tests with coverage
    # Produces coverage/lcov.info

  unified-coverage:
    needs: [backend, frontend]
    # Downloads all coverage artifacts
    # Merges into coverage/backend.lcov and coverage/frontend.lcov
    # Runs scripts/calculate_unified_coverage.py
    # Fails if unified coverage < 80%

  finish:
    # Checks all jobs passed
    # Reports final status
```

### Coverage Calculation

The `scripts/calculate_unified_coverage.py` script:

1. Parses lcov files from backend and frontend
2. Counts total lines of code (excluding test files)
3. Calculates covered lines from coverage data
4. Reports unified coverage percentage
5. Exits with code 0 if >= threshold, 1 otherwise

---

## Local Development

### Running Tests with Coverage

```bash
# Backend tests with coverage
moon run :test

# Frontend tests with coverage
cd apps/frontend && npm run test:coverage

# Calculate unified coverage (requires coverage files)
python scripts/calculate_unified_coverage.py
```

### Coverage Thresholds

| Mode | Backend | Frontend | Unified |
|------|---------|----------|---------|
| CI | 99% | 80% | 80% |
| Local | 99% | 80% | N/A |

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
  exclude: [
    'node_modules/',
    '.next/',
    'coverage/',
    '**/tests/**',
    '**/__tests__/**',
    '**/*.test.ts',
    '**/*.test.tsx',
    '**/*.spec.ts',
    '**/*.spec.tsx',
    '**/vitest.setup.ts',
    '**/*.config.*',
    '**/types/**',
  ],
  thresholds: {
    lines: 80,
    functions: 80,
    branches: 80,
    statements: 80,
    autoUpdate: true,
  },
}
```

---

## Blacklist Patterns

### What's Excluded

| Pattern | Reason |
|---------|--------|
| `/test/`, `/tests/`, `__tests__/` | Test directories |
| `test_`, `_test.py`, `.test.ts`, `.spec.ts` | Test files |
| `conftest.py`, `vitest.setup.ts` | Test configuration |
| `*.config.*` | Build/tool configuration |
| `__init__.py` | Package init files (no logic) |
| `migrations/**` | Database migrations |
| `types/**` | Type definition files |

### What's Included

All other `.py`, `.ts`, `.tsx`, `.sh` files are including:
- Source code (`src/`)
- Services
- Routers
- Models
- Schemas
- Components
- Pages
- Utilities
- Scripts

---

## Troubleshooting

### Coverage seems low

1. Check if coverage files exist:
   ```bash
   ls -la apps/backend/coverage*.lcov
   ls -la apps/frontend/coverage/lcov.info
   ```

2. Run unified coverage calculator with debug output:
   ```bash
   COVERAGE_THRESHOLD=0 python scripts/calculate_unified_coverage.py
   ```

3. Check what files are counted:
   ```bash
   # The script outputs file counts and line counts
   ```

### CI fails with coverage error

1. Download coverage artifacts locally:
   ```bash
   gh run download -R <run-id>
   ```

2. Run the unified coverage script locally:
   ```bash
   python scripts/calculate_unified_coverage.py
   ```

3. Check the unified-coverage.json output

---

## Future Improvements

1. **Scripts Testing**: Add tests for `scripts/` directory to improve scripts coverage
2. **Coverage Trends**: Track coverage over time with historical data
3. **Per-PR Coverage**: Calculate coverage for each PR independently
4. **Coverage Comments**: Add coverage ignore comments for specific lines
