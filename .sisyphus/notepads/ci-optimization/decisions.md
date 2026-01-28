# CI Optimization - Decisions

## Architectural Choices

### Decision 1: Worker-Specific Database Names
**Context**: pytest-xdist runs tests in parallel, but `db_engine` fixture drops entire schema globally.

**Choice**: Use `worker_id` from pytest-xdist to create isolated databases per worker.

**Rationale**:
- Avoids race conditions when multiple workers drop/create schema simultaneously
- Preserves existing test logic (no major refactor needed)
- Gracefully handles serial execution (worker_id='master')

**Implementation**:
```python
def get_test_db_url(worker_id: str) -> str:
    base_url = normalize_url(os.environ.get("DATABASE_URL", ...))
    if worker_id != 'master':
        url_obj = make_url(base_url)
        return str(url_obj.set(database=f"{url_obj.database}_{worker_id}"))
    return base_url
```

### Decision 2: Remove CI Verification from Staging Deploy
**Context**: `staging-deploy.yml` runs full CI suite (`moon run :ci`) even though main branch already passed CI checks.

**Choice**: Remove "Verify Codebase" step from workflow.

**Rationale**:
- Redundant: Main branch must pass CI to merge
- Saves 5-7 minutes per deploy
- CI verification still runs on all PRs before merge

### Decision 3: Keep `--dist loadfile` Flag
**Context**: pytest-xdist offers multiple distribution strategies.

**Choice**: Use `loadfile` distribution mode.

**Rationale**:
- Groups tests from same file together (preserves locality)
- Better for tests with shared fixtures/setup
- Avoids overhead of shipping fixtures across workers
