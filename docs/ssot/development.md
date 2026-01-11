# Development Environment SSOT

> **SSOT Key**: `development`
> **Source of Truth** for local development, testing, CI, and deployment.

## Source Files

| File | Purpose |
|------|---------|
| `moon.yml` | Root workspace tasks |
| `apps/*/moon.yml` | Per-project tasks |
| `scripts/test_backend.sh` | Database lifecycle (reference counting) |
| `scripts/smoke_test.sh` | Unified smoke tests (local + CI) |
| `docker-compose.ci.yml` | Development service containers |
| `.github/workflows/ci.yml` | GitHub Actions CI |
| `.github/workflows/docker-build.yml` | Build, Deploy, Smoke Test |

---

## Moon Commands (Primary Interface)

All development commands go through `moon run`:

```bash
# Setup
moon run :setup             # Install all dependencies

# Development
moon run backend:dev        # FastAPI on :8000
moon run frontend:dev       # Next.js on :3000

# Testing
moon run :test              # All tests (auto-manages DB)
moon run backend:test       # Backend tests only
moon run frontend:test      # Frontend tests only
moon run :smoke             # Smoke tests (needs running server)

# Code Quality
moon run :lint              # Lint all
moon run backend:lint       # Lint Python
moon run frontend:lint      # Lint TypeScript
moon run backend:format     # Format Python

# Build
moon run :build             # Build all
moon run frontend:build     # Build frontend
```

---

## Five Scenarios

| Scenario | Command | Database | Details |
|----------|---------|----------|---------|
| **1. Dev Start** | `moon run backend:dev` | docker-compose.ci.yml | Persistent container |
| **2. Local Test** | `moon run backend:test` | Reference counting | scripts/test_backend.sh |
| **3. Remote CI** | `moon run backend:test` | GitHub services | Ephemeral |
| **4. Staging** | (manual) | Dokploy | TODO |
| **5. Prod Deploy** | Push to main | Dokploy | Auto via docker-build.yml |

---

## Database Lifecycle (scripts/test_backend.sh)

### Design: Reference Counting

Multiple test runners share one container:

```
Terminal 1: moon run backend:test  → refcount=1 (start container)
Terminal 2: moon run backend:test  → refcount=2
Terminal 2 exits                   → refcount=1
Terminal 1 exits                   → refcount=0 (stop container)
```

### Key Features

1. **Auto-detect runtime**: podman compose / docker compose
2. **Lock file**: `~/.cache/finance_report/db.lock`
3. **Auto-cleanup**: Last runner stops container

---

## Smoke Tests (scripts/smoke_test.sh)

Shared script for local and CI:

```bash
# Local (after starting servers)
moon run :smoke

# Or with custom URL
BASE_URL=https://report.zitian.party bash scripts/smoke_test.sh
```

### Endpoints Tested

- Homepage (`/`)
- API Health (`/api/health`)
- API Docs (`/api/docs`)
- Ping-Pong Page (`/ping-pong`)
- Reconciliation Page (`/reconciliation`)
- Ping API (`/api/ping`)

---

## CI Workflows

### ci.yml (PR/Push)

```yaml
# Uses moon for consistency with local
- moon run backend:install
- moon run backend:lint
- moon run backend:test
```

### docker-build.yml (Deploy)

1. Build images → GHCR
2. Deploy to Dokploy
3. Run `scripts/smoke_test.sh` against production

---

## Environment Variables

| Scenario | DATABASE_URL |
|----------|--------------|
| Local Dev | `postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report` |
| Local Test | `postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report_test` |
| CI | Same as Local Test (GitHub services) |
| Prod | External PostgreSQL (Dokploy env) |

---

## Verification

```bash
# Test moon commands work
moon run backend:install
moon run backend:test

# Test smoke tests
moon run backend:dev &
moon run frontend:dev &
sleep 10
moon run :smoke

# Check no orphan containers
podman ps | grep finance_report
```
