# Development Environment SSOT

> **SSOT Key**: `development`
> **Source of Truth** for local development, Moon commands, database lifecycle, and isolation.

## Source Files

### Prerequisites
- **Node.js**: `20.19.0`
- **npm**: `10.8.2` (bundled with Node.js `20.19.0`)
- **Python**: `3.12.12` (managed by uv)
- **uv**: `0.9.18`
- **Host container runtime**: Docker Desktop with WSL integration or Podman
  for backend/full tests, local infrastructure, and smoke tests
- **Base shell tools**: Bash, Git, and curl

| File | Purpose |
|------|---------|
| `tools/bootstrap.sh` | One-command local bootstrap for runtimes, dependencies, hooks, and container-runtime diagnostics |
| `tools/_lib/shell/` | Shell command implementations used by `tools/*.sh` command entry points |
| `common/runtime/shell/common.sh` | Minimal shared shell helpers used by shell command implementations |
| `toolchain.toml` | Runtime and container image version SSOT |
| `.python-version` / `.node-version` / `.nvmrc` / `.tool-versions` | Local tool manager mirrors checked by CI |
| `.moon/toolchain.yml` | Moon's local Node/npm toolchain mirror |
| `moon.yml` | Root workspace tasks |
| `apps/*/moon.yml` | Per-project tasks |
| `tools/test_lifecycle.py` | Database lifecycle (Python Context Manager) |
| `tools/smoke_test.sh` | Unified smoke tests |
| `docker-compose.yml` | Development service containers |
| `.github/workflows/ci.yml` | GitHub Actions CI |
| `.github/workflows/deploy.yml` | Staging Build & Deploy |
| `.github/workflows/deploy.yml` | Production Release |

### Toolchain Contract

`toolchain.toml` is the authoritative runtime and base-image contract for local
development, GitHub Actions, and Docker/Compose:

| Runtime / Image | Version |
|-----------------|---------|
| Python | `3.12.12` |
| Node.js | `20.19.0` |
| npm | `10.8.2` |
| uv | `0.9.18` |
| Backend base image | `python:3.12.12-slim` |
| Frontend base image | `node:20.19.0-alpine` |
| Postgres test image | `postgres:15.14-alpine` |
| MinIO image | `minio/minio:RELEASE.2025-09-07T16-13-09Z` |
| MinIO client image | `minio/mc:RELEASE.2025-08-13T08-35-41Z` |

Local tool-manager files mirror the same versions for compatibility:
`.python-version`, `.node-version`, `.nvmrc`, and `.tool-versions`.
The frontend sets `engine-strict=true` in `.npmrc` and declares
`engines.node=20.19.0`, so running npm under another Node major/minor fails
early instead of producing a different dependency tree.

CI runs `python tools/check_toolchain_contract.py` in the lint job. The check
fails when workflow runtime declarations, local tool files, Docker base images,
Compose service images, or frontend engine constraints drift from
`toolchain.toml`.

Local bootstrapping is invoked through `tools/bootstrap.sh`; the tool-owned shell
implementation lives under `tools/_lib/shell/` and shared helpers stay in
`common/runtime/shell/common.sh`. It installs or verifies uv, Python,
nvm/Node.js, Moon CLI, project dependencies, and pre-commit hooks, then reports
whether Docker or Podman is available for workflows that need a host container
runtime. Local commands prefer Podman when both runtimes are available, but
`CONTAINER_RUNTIME=docker` or `CONTAINER_RUNTIME=podman` may be set to force a
specific runtime in CI or on hosts where only one daemon is usable.

### Local Host Shell Matrix

The local toolchain belongs to the shell that runs it. PATH entries, Python
packages, Node packages, and CLI installs are not shared across WSL, macOS/Linux
shells, Windows PowerShell, Git Bash, Scoop, or the Codex Windows runner.

| Host shell | Support | Command entry point | Tool install scope |
|---|---|---|---|
| WSL Ubuntu | Primary Windows path | `bash tools/bootstrap.sh` inside WSL | `/usr/bin`, `/usr/local/bin`, `$HOME/.local/bin`, `$HOME/.nvm` in WSL |
| macOS Terminal | Supported POSIX path | `bash tools/bootstrap.sh` | Homebrew/system tools plus `$HOME/.local/bin` and `$HOME/.nvm` |
| Linux shell | Supported POSIX path | `bash tools/bootstrap.sh` | Distro tools plus `$HOME/.local/bin` and `$HOME/.nvm` |
| Windows PowerShell | Not a direct project shell | Use `wsl.exe -d Ubuntu --cd ... --exec /bin/bash -lc "bash tools/bootstrap.sh"` | Windows PATH and Scoop installs only; not visible to WSL |
| Git Bash/MSYS/Cygwin | Not supported for repo bootstrap | Use WSL Ubuntu instead | Windows-mounted POSIX compatibility layer; not the repo target shell |
| Codex Windows runner | Not the repo command runner | Delegate repo commands to WSL | Runner PATH may omit interactive profile entries and WSL-only tools |

Non-interactive shells often skip interactive profile files such as `.zshrc` or
`.bashrc`. Command entry points that need tools must set PATH explicitly or run through
`tools/bootstrap.sh`; do not rely on an interactive terminal having loaded the
right Python, Node, `gh`, `uv`, `op`, `jq`, `yq`, `direnv`, Docker, or Podman.

From Windows PowerShell, run the bootstrap through WSL:

```powershell
wsl.exe -d Ubuntu --cd /home/<user>/workspace/finance_report --exec /bin/bash -lc "bash tools/bootstrap.sh"
```

---

<a id="moon-commands"></a>

## Moon Commands (Primary Interface)

```bash
# First-time local setup
bash tools/bootstrap.sh

# Development
moon run :dev -- --infra          # Start local infra through tools/cli.py
bash tools/infra.sh up            # Start local infra directly
bash tools/infra.sh logs          # Follow local infra logs
bash tools/infra.sh down          # Stop local infra
moon run :dev -- --backend        # FastAPI backend after infra is running
moon run :dev -- --frontend       # Next.js on :3000

# Local verification
moon run :test -- --smart         # Default affected fast gate for ordinary backend changes
moon run :test -- --fast          # Fast TDD loop without coverage
moon run :lint                    # Static checks before committing
moon run :lint && moon run :test  # Full local confidence gate when risk or release timing justifies it

# Testing
moon run :test                    # All tests (backend threshold is code-owned by apps/backend/pyproject.toml)
moon run :test -- --fast          # TDD mode (no coverage, fastest)
moon run :test -- --smart         # Coverage on changed files only
moon run :test -- --e2e           # Root deployment E2E tests under tests/e2e/
moon run :test -- --backend-e2e   # Backend Tier-1 API E2E under apps/backend/tests/e2e/
moon run :test -- tests/accounting/  # Run specific module
moon run :test -- tests/accounting/test_journal_service.py  # Run specific file

# Environment Verification (See docs/ssot/env_smoke_test.md for full details)
uv run python -m src.boot --mode full  # Full Stack Check (Gate 3)

# Code Quality
moon run :lint              # Lint all
moon run :lint -- --fix     # Format Python (auto-fix)
python tools/check_toolchain_contract.py  # Runtime/toolchain drift check

# Build
moon run :build             # Build all
```

Default local verification starts with affected fast tests. Use
`moon run :test -- --smart` for ordinary backend changes, focused Vitest/spec
runs for ordinary frontend changes, and focused tooling checks for docs/tooling
changes. PR CI remains the authoritative merge gate.

The full local confidence gate (`moon run :lint && moon run :test`) remains the
same gate family as GitHub CI, but it is no longer the default local loop for
ordinary low-risk edits.

Risk-triggered local escalation is required for accounting, posting,
reconciliation, money, balance, schema, migrations, API contract, OpenAPI,
shared common/tooling, Docker, workflow, environment, and deploy changes. Use
the focused domain, migration, API, downstream tooling, or static contract gates
listed in [ci-cd.md](./ci-cd.md#path-risk-to-local-gate-matrix), then rely on
PR CI and deployed gates for full consistency proof.

For schema and migration changes, run the same deterministic Alembic proof that
PR CI uses before relying on preview or staging:

```bash
cd apps/backend
uv run alembic upgrade head
uv run alembic check
```

Backend pytest fixtures may rebuild isolated model schemas for fast data
isolation. That is useful for test speed, but it is not the authoritative
migration proof. Alembic `upgrade head` plus `alembic check` against Postgres is
the schema contract for both local escalation and PR CI.

Root Moon tasks are uncached wrappers with explicit workspace inputs, so local
verification runs fresh and never treats the `repo` infra submodule gitlink as a
file input. The `repo/` submodule is verified separately by the agent
orchestration infra sync check.

---

## Documentation

The project uses [MkDocs](https://www.mkdocs.org/) with Material theme.

```bash
pip install -r docs/requirements.txt  # Install dependencies
uv --version                           # Required by MkDocs hooks
mkdocs serve                          # Serve locally → http://127.0.0.1:8000
mkdocs build                          # Build static site → site/
```

MkDocs generates build-time reference pages through [docs/hooks.py](../hooks.py).
`docs/reference/db-schema.md` is intentionally gitignored; it is generated from
SQLAlchemy metadata during `mkdocs serve` / `mkdocs build` and in the GitHub
Pages workflow.

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

`tools/test_lifecycle.py` uses `@contextmanager` to handle the database lifecycle:

1. **Setup**: Starts the `postgres` service via Docker Compose; ensures DB is ready.
2. **Isolation**: Creates `finance_report_test` database and runs migrations.
3. **Teardown**: Stops the database container after tests complete.
4. **Signal Handling**: Catches `SIGINT`/`SIGTERM` to clean up on interruption.

<a id="local-test-isolation"></a>

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
- Namespaced test infra binds Postgres and MinIO to ephemeral localhost ports
  (`127.0.0.1::5432`, `127.0.0.1::9000`, `127.0.0.1::9001`) so parallel
  branch test runs do not collide with persistent local containers.

Long branch/workspace namespaces are shortened deterministically with an 8-character hash suffix before resource creation. This keeps PostgreSQL identifiers and S3-compatible bucket names within their 63-character limits while preserving stable local/CI isolation.

**Usage**:
```bash
BRANCH_NAME=feature-auth moon run :test                    # Explicit namespace
BRANCH_NAME=feature-auth WORKSPACE_ID=alice moon run :test # With workspace ID
moon run :test                                             # Auto-detect from git branch
```

### Key Features

1. **Auto-detect runtime**: `CONTAINER_RUNTIME` override, otherwise podman compose / docker compose
2. **Lock file**: `~/.cache/finance_report/db.lock`
3. **Auto-cleanup**: Last runner stops container; worker DBs cleaned post-run

---

## Isolation Utilities (`common/test_isolation.py`)

**Purpose**: Namespace-aware resource naming for parallel test execution.

| Function | Input | Output | Purpose |
|----------|-------|--------|---------|
| `get_test_db_name(namespace)` | `"feature_auth"` | `"finance_report_test_feature_auth"` | Test database |
| `get_s3_bucket(namespace)` | `"feature_auth"` | `"statements-feature-auth"` | S3 bucket |
| `get_env_suffix(namespace)` | `"feature_auth"` | `"-feature_auth"` | Compose suffix |
| `sanitize_namespace(name)` | `"feature/auth-v2"` | `"feature_auth_v2"` | Safe identifier |

Integration points:
- `common/test_isolation.py` — owns reusable namespace, database, bucket, and suffix helpers
- `tools/test_lifecycle.py` — command entry point that creates DBs and overrides `S3_BUCKET`
- `apps/backend/tests/conftest.py` — reads `TEST_NAMESPACE`, generates worker URLs
- Contract tests: `apps/backend/tests/infra/test_isolation.py` (15 tests)

---

## Test Optimization

> **See dedicated file** → **[docs/ssot/ci-cd.md](./ci-cd.md)**
>
> Covers: smart/fast/full test modes, 4-way local test parallelism,
> GitHub CI sharding, no-regression coverage gate,
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
bash tools/smoke_test.sh                              # Local
BASE_URL=https://report.zitian.party bash tools/smoke_test.sh  # Staging/prod
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
| PR Test | `postgresql+asyncpg://...` | Compose service DNS (`postgres`, `minio`) on the project-scoped internal network |
| CI | Same as Local Test | `localhost:5433` (services) |
| Staging/Prod | External PostgreSQL | Dokploy Managed |

Environment/config validation is shared library logic under `common/config/`.
`common/config/env_keys.py` owns the three-way key comparison across
`secrets.ctmpl`, `apps/backend/src/config.py`, and `.env.example`;
`tools/check_env_keys.py` is the command entry point. Pydantic config/schema
validation is implemented in `common/config/schema_validation.py` and exposed
through `tools/validate_schemas.py`. The root command namespace is `tools/`;
shared implementation belongs in `common/`.

---

## Verification

```bash
# Verify moon commands work
moon run :test

# Test smoke tests locally
nohup moon run :dev -- --backend > /dev/null 2>&1 &
sleep 10
export BASE_URL="http://localhost:8000"
bash tools/smoke_test.sh

# Check no orphan containers after tests
podman ps | grep finance_report
```

---

## Resource Cleanup

### Automatic Cleanup (Recommended)

```bash
./tools/install_git_hooks.sh  # Install post-push hook for auto-cleanup
```

Cleans: Test databases from interrupted runs, worker DBs from pytest-xdist crashes.
Does NOT touch: Development data, running tests.

### Manual Cleanup

```bash
# Orphaned test databases (after interrupted runs)
python tools/cleanup_orphaned_dbs.py --dry-run  # Preview
python tools/cleanup_orphaned_dbs.py            # Clean orphaned
python tools/cleanup_orphaned_dbs.py --all      # Clean ALL test DBs

# All development resources (WARNING: data loss!)
./tools/cleanup_dev_resources.sh        # Containers + locks only
./tools/cleanup_dev_resources.sh --all  # EVERYTHING (volumes, MinIO)

# Resource leak monitoring (run weekly)
./tools/check_resource_leaks.sh
./tools/check_resource_leaks.sh --verbose
VPS_HOST=cloud.zitian.party ./tools/check_resource_leaks.sh
```

### PR Preview Cleanup (Automated)

Current PR preview runs inside the GitHub runner after a successful PR `CI`
workflow and does not create Dokploy deployments, shared VPS containers, or PR
preview GHCR images.

When a PR is closed, merged, or interrupted by failed/cancelled/timed-out CI,
GitHub Actions automatically reconciles historical preview resources:
- ✅ Legacy Dokploy stack on VPS
- ✅ Legacy compose-scoped Docker volumes (`postgres_data`, `redis_data`, `minio_data`)
- ✅ Legacy closed-PR GHCR tags through the scheduled fallback workflow only

The scheduled `PR Preview Cleanup` workflow is the fallback cleanup path for
missed PR close events or old Dokploy cleanup failures. Every six hours it:
- Lists historical preview resources matching PR-scoped naming.
- Compares them with currently open GitHub PRs.
- Removes only closed/missing PR preview resources and their compose-scoped volumes.
- Prunes legacy closed-PR GHCR tags after the retention window.
- Runs bounded Docker build-cache and unused-image pruning with age filters.

The scheduled `GHCR SHA Retention` workflow is separate from PR preview cleanup.
It prunes backend/frontend `:<sha>` GHCR package versions older than 28 days,
preserving live staging/production deploy SHAs and every `vX.Y.Z` release tag.

Manual dry run:

```bash
gh workflow run maintenance.yml -f task=pr-preview-cleanup -f preview_cleanup_dry_run=true
gh workflow run maintenance.yml -f task=ghcr-sha-retention -f ghcr_dry_run=true
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
