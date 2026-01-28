# CI Optimization - Learnings

## Conventions & Patterns

### pytest-xdist Worker Isolation
- Each worker needs a unique database to avoid race conditions
- Use `worker_id` fixture to differentiate workers
- Pattern: `{base_db_name}_{worker_id}` (e.g., `finance_report_test_gw0`)
- Master worker (serial execution) uses base name without suffix

### Database Fixture Architecture
- `db_engine` (function scope): Creates test DB, drops schema globally after each test
- `db` (function scope): Session tied to specific engine
- `ensure_database()`: Helper to create DB if missing (runs in AUTOCOMMIT mode)

### Moon Test Configuration
- `test-execution` task: Direct pytest invocation with flags
- `-n auto`: Use all CPU cores
- `--dist loadfile`: Distribute by file (keeps related tests together)
- `-m "not slow and not e2e"`: Exclude long-running tests from main suite

## Implementation Success (2026-01-27)

### conftest.py Worker Isolation - WORKING
**File**: `apps/backend/tests/conftest.py`

**Changes Made**:
1. Added `worker_id` fixture (session scope) - extracts pytest-xdist worker identifier
2. Created `get_test_db_url(worker_id)` helper function
3. Added `test_database_url` fixture (session scope) - returns worker-specific URL
4. Modified `db_engine` fixture to accept `test_database_url` parameter
5. Updated `ensure_database(db_url)` to accept database URL parameter

**Critical Fix**: Used `url_obj.render_as_string(hide_password=False)` instead of `str(url_obj)` to preserve database credentials in worker-specific URLs.

**Verification Result**:
- **All 806 tests passed** with parallel execution
- **Coverage**: 96.61% (exceeds 95% requirement)
- **Execution Time**: 75.64 seconds with `-n auto` (uses all CPU cores)
- **Workers Created**: Multiple (auto-detected based on CPU count)

**Database Isolation Confirmed**:
- Each worker gets unique database: `finance_report_test_gw0`, `finance_report_test_gw1`, etc.
- No race conditions observed
- Serial execution (`worker_id='master'`) continues to use base database name

### Performance Impact
- **Previous** (serial): ~7 minutes (427 seconds) estimated
- **Current** (parallel): 75.64 seconds
- **Speedup**: ~5.6x faster (82% reduction in time)

### moon.yml Configuration - VERIFIED
**File**: `apps/backend/moon.yml`

**Change**: Line 53 updated from:
```yaml
command: 'uv run pytest -v -m "not slow and not e2e" --cov=src --cov-report=lcov --cov-report=term-missing'
```

To:
```yaml
command: 'uv run pytest -n auto -v -m "not slow and not e2e" --cov=src --cov-report=lcov --cov-report=term-missing --dist loadfile'
```

**Flags Added**:
- `-n auto`: Enable parallel execution, auto-detect CPU cores
- `--dist loadfile`: Distribute tests by file (preserves test locality)

**Verification**: `moon run backend:test-execution` successfully runs tests in parallel.

### staging-deploy.yml Optimization - COMPLETE
**File**: `.github/workflows/staging-deploy.yml`

**Change**: Removed redundant "Verify Codebase" step (lines 65-78).

**Rationale**:
- Main branch already passed full CI verification before merge
- Running `moon run :ci` again wastes 5-7 minutes
- CI still runs on all PRs before merge, ensuring code quality

**Steps Removed**:
1. Verify Codebase step
2. Associated S3_* environment variables (used only for verification)

**Workflow Now**: Install moon → Install uv → Set up Python → Build & Push images → Deploy

**Time Saved**: ~5-7 minutes per staging deployment

**Verification**: YAML syntax validated successfully.
