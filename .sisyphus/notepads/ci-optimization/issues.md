# CI Optimization - Issues & Gotchas

## Known Problems

### Issue 1: Global Schema Drop in Parallel Tests
**Symptom**: When running `pytest -n auto`, tests fail with "relation does not exist" errors.

**Root Cause**: Line 177 in `conftest.py`:
```python
await conn.execute(text("DROP SCHEMA public CASCADE"))
```
All workers drop the same schema simultaneously → race conditions.

**Solution**: Create worker-specific databases using `worker_id` fixture.

### Issue 2: localhost vs 127.0.0.1 Inconsistency
**Context**: Tests normalize "localhost" to "127.0.0.1" for consistency (line 49-52).

**Gotcha**: When building worker-specific DB URLs, must preserve this normalization.

### Issue 3: Moon.yml Already Modified But Not Committed
**Current State**: `apps/backend/moon.yml` has `-n auto --dist loadfile` flags added in previous session.

**Action Required**: Include this file in commit after conftest.py changes complete.

## Migration Risks

### Risk 1: Database Creation Overhead
**Concern**: Creating multiple test databases (one per worker) might slow down initial setup.

**Mitigation**: 
- Database creation is one-time per test session (not per test)
- `ensure_database()` checks existence first
- Expected overhead: <5 seconds total

### Risk 2: CI Environment Compatibility
**Concern**: GitHub Actions might not support parallel test execution.

**Mitigation**:
- GitHub Actions runners have multiple cores (4+ typical)
- pytest-xdist auto-detects available cores
- Fallback: Serial execution still works (worker_id='master')
