# Test Execution Optimization Guide

## 🐌 Current Problem
- 912 tests, execution time too long
- Using `--dist loadfile` strategy may not be efficient enough
- Generating multiple coverage reports (lcov + term-missing) adds overhead

## 🚀 Optimization Solutions

### Solution 1: Use worksteal Distribution Strategy (Applied)
**Improvement**: Change `--dist loadfile` to `--dist worksteal`

```bash
# Original command
pytest -n auto --dist loadfile

# Optimized command
pytest -n auto --dist worksteal
```

**Effect**: `worksteal` dynamically assigns tests to idle workers, more balanced than `loadfile` (assigns by file), **estimated 20-30% speedup**

---

### Solution 2: Add Fast Test Task (Added)
**Purpose**: Quick validation during development, skip detailed coverage reports

```bash
# Original - generates detailed reports
moon run backend:test-execution

# Fast mode - only shows brief coverage
moon run backend:test-execution-fast
```

**Improvements**:
- Remove `--cov-report=lcov` and `--cov-report=term-missing`
- Keep only `--cov-report=term` (brief statistics)
- Add `--tb=short` (simplified error output)

**Estimated speedup**: **10-15%**

---

### Solution 3: Use pytest-xdist Smart Cache
**Configuration**: Enable cache in `pyproject.toml`

```toml
[tool.pytest.ini_options]
addopts = """
    --cov=src 
    --cov-report=term 
    --cov-branch 
    --cov-fail-under=94 
    -m 'not slow' 
    -n auto 
    --dist worksteal
    --maxfail=10
"""
```

**New parameters**:
- `--maxfail=10`: Stop after 10 test failures (fast fail)

---

### Solution 4: Layered Test Execution
**Concept**: Separate tests into multiple levels, execute as needed

```bash
# 1. Ultra-fast smoke test (core features, <30s)
moon run backend:test-smoke

# 2. Fast test (skip slow tests, <2min)
moon run backend:test-execution-fast

# 3. Full test (includes detailed reports, for CI)
moon run backend:test-execution
```

Add `test-smoke` task:
```yaml
test-smoke:
  command: 'uv run pytest -n auto -m smoke -x --tb=short'
  local: true
```

---

### Solution 5: Skip Coverage Check (During Development)
**Scenario**: No coverage needed during rapid iteration

```bash
# Skip coverage, pure test execution
cd apps/backend
uv run pytest -n auto -v -m "not slow and not e2e" --tb=short
```

**Estimated speedup**: **30-40%** (coverage collection has significant overhead)

---

### Solution 6: Increase Parallelism (When Hardware is Sufficient)
**Current**: `-n auto` (auto-detect CPU cores)

**Optimization**: Explicitly specify more workers

```bash
# Check current CPU cores
sysctl -n hw.ncpu

# Assume 8 cores, can try
pytest -n 12 ...  # Use more workers (hyperthreading)
```

⚠️ **Note**: Too many workers may slow down due to database connection competition

---

### Solution 7: Use In-Memory Database (Most Aggressive)
**Improvement**: Use SQLite in-memory database instead of PostgreSQL during testing

```python
# tests/conftest.py
@pytest.fixture
async def db_session():
    # Use SQLite for development
    if os.getenv("FAST_TEST"):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    else:
        # Use real PostgreSQL for CI
        engine = create_async_engine(settings.DATABASE_URL)
```

**Usage**:
```bash
FAST_TEST=1 moon run backend:test-execution-fast
```

**Estimated speedup**: **50-70%** (but may miss PostgreSQL-specific bugs)

---

## 📊 Performance Comparison (Estimated)

| Solution | Execution Time | Coverage | Use Case |
|----------|----------------|----------|----------|
| Original (loadfile) | 100% (baseline) | ✅ Full | CI |
| Worksteal (Solution 1) | **~75%** | ✅ Full | CI |
| Fast mode (Solution 2) | **~65%** | ✅ Brief | Development |
| No coverage (Solution 5) | **~35%** | ❌ None | Quick validation |
| In-memory DB (Solution 7) | **~25%** | ✅ Full | Development |

---

## 🎯 Recommended Strategy

### Daily Development (Fastest)
```bash
# Quick validate changes
moon run backend:test-execution-fast

# Or no coverage
cd apps/backend && uv run pytest -n auto -x --tb=line
```

### Pre-commit Check
```bash
# Full validation
moon run backend:test-execution
```

### CI Pipeline
```bash
# Keep current configuration (worksteal already optimized)
moon run backend:ci
```

---

## 🛠️ Applied Improvements

1. ✅ `test-execution`: Using `--dist worksteal` (replacing loadfile)
2. ✅ `test-execution-fast`: Added fast test task
3. ⏳ `test-smoke`: To be added (need to mark core tests with `@pytest.mark.smoke`)

---

## 📝 Next Steps

### Ready to Use
```bash
# Try new worksteal configuration
moon run backend:test-execution

# Or use fast mode
moon run backend:test-execution-fast
```

### Further Optimization (Optional)
1. Mark core tests with `@pytest.mark.smoke` to create ultra-fast smoke test suite
2. Evaluate if in-memory database should be used during development
3. Analyze which tests are slowest, consider marking as `@pytest.mark.slow`

---

## 🔍 Diagnose Slow Tests

Find slowest 10 tests:
```bash
cd apps/backend
uv run pytest --durations=10 -m "not slow and not e2e"
```

Find all tests >1s:
```bash
uv run pytest --durations=0 -m "not slow and not e2e" | grep -E "^\d+\.\d+s" | sort -rn
```
