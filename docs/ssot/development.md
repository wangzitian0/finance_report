# Development Environment SSOT

> **SSOT Key**: `development`
> **Source of Truth** for local development, Moon commands, database lifecycle, and isolation.

## Source Files

### Prerequisites
- **Node.js**: v20+ (Managed by system, not moon)
- **pnpm/npm**: Required for frontend dependencies
- **Python**: v3.12+ (Managed by uv)

| File | Purpose |
|------|---------|
| `moon.yml` | Root workspace tasks |
| `apps/*/moon.yml` | Per-project tasks |
| `scripts/test_lifecycle.py` | Database lifecycle (Python Context Manager) |
| `scripts/smoke_test.sh` | Unified smoke tests |
| `docker-compose.yml` | Development service containers |
| `.github/workflows/ci.yml` | GitHub Actions CI |
| `.github/workflows/staging-deploy.yml` | Staging Build & Deploy |
| `.github/workflows/production-release.yml` | Production Release |

---

## Moon Commands (Primary Interface)

```bash
# Development
moon run :dev -- --backend        # Full Stack (App + DB + Redis + MinIO)
moon run :dev -- --frontend       # Next.js on :3000

# Local CI / Verification (Recommended)
moon run :lint && moon run :test  # One-button check (matches GitHub CI exactly)

# Testing
moon run :test                    # All tests (default, 90% backend coverage)
moon run :test -- --fast          # TDD mode (no coverage, fastest)
moon run :test -- --smart         # Coverage on changed files only
moon run :test -- --e2e           # E2E tests (Playwright)
moon run :test -- tests/accounting/  # Run specific module
moon run :test -- tests/accounting/test_journal_service.py  # Run specific file

# Environment Verification (See docs/ssot/env_smoke_test.md for full details)
uv run python -m src.boot --mode full  # Full Stack Check (Gate 3)

# Code Quality
moon run :lint              # Lint all
moon run :lint -- --fix     # Format Python (auto-fix)

# Build
moon run :build             # Build all
```

---

## Documentation

The project uses [MkDocs](https://www.mkdocs.org/) with Material theme.

```bash
pip install -r docs/requirements.txt  # Install dependencies
mkdocs serve                          # Serve locally → http://127.0.0.1:8000
mkdocs build                          # Build static site → site/
```

Live docs: [wangzitian0.github.io/finance_report](https://wangzitian0.github.io/finance_report/)

---

## Six Environments

> **See dedicated file** → **[docs/ssot/environments.md](./environments.md)**
>
> Covers: Local Dev / Local CI / GitHub CI / PR Preview / Staging / Production,
> container naming patterns, and isolation details.

---

## Database Lifecycle

### Database Management (Python Context Manager)

`scripts/test_lifecycle.py` uses `@contextmanager` to handle the database lifecycle:

1. **Setup**: Starts the `postgres` service via Docker Compose; ensures DB is ready.
2. **Isolation**: Creates `finance_report_test` database and runs migrations.
3. **Teardown**: Stops the database container after tests complete.
4. **Signal Handling**: Catches `SIGINT`/`SIGTERM` to clean up on interruption.

### Local Test Isolation (Namespace-Based)

**Purpose**: Multiple repo copies / branches can run tests in parallel without conflicts.

**Namespace Generation** (priority order):
- `BRANCH_NAME` (explicit) + `WORKSPACE_ID` (optional) → e.g., `feature_auth_abc123`
- Git branch + repo path hash → e.g., `feature_payments_beeba6ed`
- `"default"` (with warning if neither is set)

**Isolated Resources**:
- Test Database: `finance_report_test_{namespace}`
- Worker Databases: `finance_report_test_{namespace}_gw0`, `gw1`, etc. (pytest-xdist)
- S3 Buckets: `statements-{namespace}`

Long branch/workspace namespaces are shortened deterministically with an 8-character hash suffix before resource creation. This keeps PostgreSQL identifiers and S3-compatible bucket names within their 63-character limits while preserving stable local/CI isolation.

**Usage**:
```bash
BRANCH_NAME=feature-auth moon run :test                    # Explicit namespace
BRANCH_NAME=feature-auth WORKSPACE_ID=alice moon run :test # With workspace ID
moon run :test                                             # Auto-detect from git branch
```

### Key Features

1. **Auto-detect runtime**: podman compose / docker compose
2. **Lock file**: `~/.cache/finance_report/db.lock`
3. **Auto-cleanup**: Last runner stops container; worker DBs cleaned post-run

---

## Isolation Utilities (`scripts/isolation_utils.py`)

**Purpose**: Namespace-aware resource naming for parallel test execution.

| Function | Input | Output | Purpose |
|----------|-------|--------|---------|
| `get_test_db_name(namespace)` | `"feature_auth"` | `"finance_report_test_feature_auth"` | Test database |
| `get_s3_bucket(namespace)` | `"feature_auth"` | `"statements-feature-auth"` | S3 bucket |
| `get_env_suffix(namespace)` | `"feature_auth"` | `"-feature_auth"` | Compose suffix |
| `sanitize_namespace(name)` | `"feature/auth-v2"` | `"feature_auth_v2"` | Safe identifier |

Integration points:
- `scripts/test_lifecycle.py` — generates namespace, creates DB, overrides `S3_BUCKET`
- `apps/backend/tests/conftest.py` — reads `TEST_NAMESPACE`, generates worker URLs
- Contract tests: `apps/backend/tests/infra/test_isolation.py` (15 tests)

---

## Test Optimization

> **See dedicated file** → **[docs/ssot/ci-cd.md](./ci-cd.md)**
>
> Covers: smart/fast/full test modes, 4-way CI sharding, no-regression coverage gate,
> CI job structure, and performance metrics.

---

## Resource Lifecycle Management

All resources are bound to either **dev server lifecycle** (Ctrl+C) or **test lifecycle**.

| Script | Resources Started | Cleaned up on Ctrl+C |
|--------|-------------------|---------------------|
| `dev_backend.py` | uvicorn (PID), **Full Stack Containers** | ✓ uvicorn only (Containers stay) |
| `dev_frontend.py` | Next.js (PID tracked) | ✓ Only ours |

**Test lifecycle resources:**

| Resource | Start | Stop |
|----------|-------|------|
| Test DB container | Before tests | After last test runner exits |
| Playwright driver | By pytest | Cleanup on test end |
| Child processes | By pytest | on exit |

---

## Smoke Tests

```bash
bash scripts/smoke_test.sh                              # Local
BASE_URL=https://report.zitian.party bash scripts/smoke_test.sh  # Staging/prod
```

Endpoints tested: `/`, `/api/health`, `/api/docs`, `/ping-pong`, `/reconciliation`, `/api/ping`

---

## CI Workflows & Deployment

> **See dedicated files** →
> - **[docs/ssot/ci-cd.md](./ci-cd.md)** — CI job structure, coverage gate
> - **[docs/ssot/deployment.md](./deployment.md)** — Vault, staging/production workflows

---

## Environment Variables

| Scenario | DATABASE_URL | Hostname Strategy |
|----------|--------------|-------------------|
| Local Dev | `postgresql+asyncpg://...` | `localhost` or `postgres` |
| Local Test | `postgresql+asyncpg://...` | `localhost:5432` |
| PR Test | `postgresql+asyncpg://...` | **Unique**: `finance-report-db-pr-XX` |
| CI | Same as Local Test | `localhost:5433` (services) |
| Staging/Prod | External PostgreSQL | Dokploy Managed |

---

## Verification

```bash
# Verify moon commands work
moon run :test

# Test smoke tests locally
nohup moon run :dev -- --backend > /dev/null 2>&1 &
sleep 10
export BASE_URL="http://localhost:8000"
bash scripts/smoke_test.sh

# Check no orphan containers after tests
podman ps | grep finance_report
```

---

## Resource Cleanup

### Automatic Cleanup (Recommended)

```bash
./scripts/install_git_hooks.sh  # Install post-push hook for auto-cleanup
```

Cleans: Test databases from interrupted runs, worker DBs from pytest-xdist crashes.
Does NOT touch: Development data, running tests.

### Manual Cleanup

```bash
# Orphaned test databases (after interrupted runs)
python scripts/cleanup_orphaned_dbs.py --dry-run  # Preview
python scripts/cleanup_orphaned_dbs.py            # Clean orphaned
python scripts/cleanup_orphaned_dbs.py --all      # Clean ALL test DBs

# All development resources (WARNING: data loss!)
./scripts/cleanup_dev_resources.sh        # Containers + locks only
./scripts/cleanup_dev_resources.sh --all  # EVERYTHING (volumes, MinIO)

# Resource leak monitoring (run weekly)
./scripts/check_resource_leaks.sh
./scripts/check_resource_leaks.sh --verbose
VPS_HOST=cloud.zitian.party ./scripts/check_resource_leaks.sh
```

### PR Preview Cleanup (Automated)

When a PR is closed, GitHub Actions automatically cleans:
- ✅ Dokploy stack on VPS
- ✅ Docker volumes (`postgres_data`, `redis_data`, `minio_data`)
- ✅ GHCR container images (`backend:pr-{number}`, `frontend:pr-{number}`)

The scheduled `PR Preview Cleanup` workflow is the fallback cleanup path for
missed PR close events or failed Dokploy/SSH cleanup. Every six hours it:
- Lists live VPS preview containers matching `finance-report-*-pr-{number}`.
- Compares them with currently open GitHub PRs.
- Removes only closed/missing PR preview containers and their compose-scoped volumes.
- Runs bounded Docker build-cache and unused-image pruning with age filters.

Manual dry run:

```bash
gh workflow run pr-preview-cleanup.yml -f dry_run=true
```

---

## Related Documents

| Document | Content |
|----------|---------|
| [environments.md](./environments.md) | Six environments, container naming, isolation |
| [ci-cd.md](./ci-cd.md) | CI job structure, coverage gate, test modes |
| [deployment.md](./deployment.md) | Deployment workflows, Vault, release process |
| [coverage.md](./coverage.md) | Unified coverage system |
| [tdd.md](./tdd.md) | TDD workflow |
| [MANIFEST.yaml](./MANIFEST.yaml) | Concept ownership registry |
