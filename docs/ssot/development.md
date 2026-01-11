# Development Environment SSOT

> **SSOT Key**: `development`
> **Source of Truth** for local development, testing, CI, and deployment.

## Source Files

| File | Purpose |
|------|---------|
| `moon.yml` | Root workspace tasks |
| `apps/*/moon.yml` | Per-project tasks |
| `scripts/test_backend.sh` | Database lifecycle (reference counting) |
| `scripts/smoke_test.sh` | Unified smoke tests |
| `docker-compose.ci.yml` | Development service containers |
| `.github/workflows/ci.yml` | GitHub Actions CI |
| `.github/workflows/docker-build.yml` | Build, Deploy, Smoke Test |

---

## Moon Commands (Primary Interface)

```bash
# Development
moon run backend:dev        # FastAPI on :8000
moon run frontend:dev       # Next.js on :3000

# Testing
moon run :test              # All tests
moon run backend:test       # Backend tests (auto-manages DB)
moon run :smoke             # Smoke tests

# Code Quality
moon run :lint              # Lint all
moon run backend:format     # Format Python

# Build
moon run :build             # Build all
```

---

## Five Scenarios

| # | Scenario | Command | Smoke Test Timing |
|---|----------|---------|-------------------|
| 1 | **Dev Start** | `moon run backend:dev` + `moon run frontend:dev` | Manual: once both servers up, run `moon run :smoke` (see note below) |
| 2 | **Local Test** | `moon run backend:test` | N/A (unit tests, not smoke) |
| 3 | **Remote CI** | `moon run backend:test` | N/A (unit tests only in CI) |
| 4 | **Staging Deploy** | (manual) | After deploy: `BASE_URL=https://staging.xxx bash scripts/smoke_test.sh` |
| 5 | **Prod Deploy** | Push to main | **After deploy**: docker-build.yml runs `smoke_test.sh` automatically |

> **Note:** The `:smoke` task defaults to `http://localhost:3000`. In local development, either ensure the frontend proxy is configured or set `BASE_URL` (e.g., `BASE_URL=http://localhost:8000` for backend only) before running `moon run :smoke`.

### Smoke Test Timing Detail

```
┌─────────────────────────────────────────────────────────────────┐
│ Scenario 1: Dev Start                                           │
│ ┌─────────┐    ┌─────────┐    ┌─────────┐                      │
│ │ DB up   │ -> │ Servers │ -> │ Smoke   │                      │
│ │ (manual)│    │ (moon)  │    │ (manual)│                      │
│ └─────────┘    └─────────┘    └─────────┘                      │
├─────────────────────────────────────────────────────────────────┤
│ Scenario 2-3: Local/Remote Test                                 │
│ ┌─────────┐    ┌─────────┐                                     │
│ │ DB auto │ -> │ pytest  │  (no smoke, unit tests only)        │
│ └─────────┘    └─────────┘                                     │
├─────────────────────────────────────────────────────────────────┤
│ Scenario 5: Prod Deploy (GitHub Actions)                        │
│ ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐      │
│ │ Build   │ -> │ Push to │ -> │ Deploy  │ -> │ Smoke   │      │
│ │ images  │    │ GHCR    │    │ Dokploy │    │ (auto)  │      │
│ └─────────┘    └─────────┘    └─────────┘    └─────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Lifecycle

### Reference Counting (scripts/test_backend.sh)

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

## Resource Lifecycle Management

All resources are bound to either **dev server lifecycle** (Ctrl+C) or **test lifecycle** (start/end).

### Dev Server Lifecycle (`scripts/dev_*.py`)

```
┌─────────────────────────────────────────────────────────────────┐
│ User runs: moon run backend:dev                                 │
│ ┌─────────┐    ┌─────────┐    ┌─────────┐                      │
│ │ Start   │ -> │ Server  │ -> │ Ctrl+C  │                      │
│ │ DB      │    │ Runs    │    │ Cleanup │                      │
│ └─────────┘    └─────────┘    └─────────┘                      │
│                                    │                            │
│                              Stops: OUR uvicorn, OUR DB only    │
└─────────────────────────────────────────────────────────────────┘
```

**Key safety feature**: Scripts track processes by PID, only kill what THEY started.
Safe for multi-window development - won't kill other sessions' processes.

**Resources managed by dev scripts:**
| Script | Resources Started | Cleaned up on Ctrl+C |
|--------|-------------------|---------------------|
| `dev_backend.py` | uvicorn (PID tracked), dev DB (container ID tracked) | ✓ Only ours |
| `dev_frontend.py` | Next.js (PID tracked) | ✓ Only ours |

### Test Lifecycle (`scripts/test_backend.sh`)

```
┌─────────────────────────────────────────────────────────────────┐
│ User runs: moon run backend:test                                │
│ ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐      │
│ │ Start   │ -> │ Create  │ -> │ pytest  │ -> │ Cleanup │      │
│ │ DB      │    │ test DB │    │ runs    │    │ (trap)  │      │
│ └─────────┘    └─────────┘    └─────────┘    └─────────┘      │
│                                                   │             │
│                          Stops: DB (if refcount=0), playwright  │
└─────────────────────────────────────────────────────────────────┘
```

**Resources managed by test script:**
| Resource | Start | Stop |
|----------|-------|------|
| Test DB container | Before tests | After last test runner exits |
| Playwright driver | By pytest | Cleanup on test end |
| Child processes | By pytest | `pkill -P $$` on exit |


## Smoke Tests (scripts/smoke_test.sh)

### Usage

```bash
# Local (after starting servers)
moon run :smoke

# Against staging/prod
BASE_URL=https://report.zitian.party bash scripts/smoke_test.sh
```

### Endpoints Tested

| Endpoint | Check |
|----------|-------|
| `/` | Homepage loads |
| `/api/health` | Returns "healthy" |
| `/api/docs` | Swagger UI loads |
| `/ping-pong` | Demo page loads |
| `/reconciliation` | Workbench loads |
| `/api/ping` | Ping API responds |

---

## CI Workflows

### ci.yml (on PR/push)

```
Trigger: PR or push to main
Steps:  install → lint → test
DB:     GitHub services (ephemeral)
Smoke:  ❌ Not run (unit tests only)
Note:   Uses moon tasks for install/lint/build (uv/npm invoked via moon)
```

### docker-build.yml (on push to main)

```
Trigger: Push to main (apps/** changed)
Steps:  build → push → deploy → smoke
DB:     Production (Dokploy)
Smoke:  ✅ After deploy completes
```

---

## Environment Variables

| Scenario | DATABASE_URL |
|----------|--------------|
| Local Dev | `postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report` |
| Local Test | `postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report_test` |
| CI | Same as Local Test (GitHub services on :5432) |
| Prod | External PostgreSQL (Dokploy env) |

---

## Verification

```bash
# Verify moon commands work
moon run backend:test

# Test smoke tests
nohup moon run backend:dev > /dev/null 2>&1 &
# nohup moon run frontend:dev > /dev/null 2>&1 &  (optional)
sleep 10
export BASE_URL="http://localhost:8000"  # Test backend directly
moon run :smoke

# Check no orphan containers after tests
podman ps | grep finance_report
```
