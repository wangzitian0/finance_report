# Development Environment SSOT

> **SSOT Key**: `development`
> **Source of Truth** for local development, testing, and CI environments.

## Source Files

| File | Purpose |
|------|---------|
| `moon.yml` | Root workspace tasks |
| `apps/*/moon.yml` | Per-project tasks |
| `scripts/test_backend.sh` | **Database lifecycle** (reference count, auto-cleanup) |
| `docker-compose.ci.yml` | Development/CI service containers |
| `.github/workflows/ci.yml` | GitHub Actions CI |

---

## Moon Commands (Primary Interface)

All development commands should go through `moon run`:

```bash
# Install dependencies
moon run :setup                 # All projects
moon run backend:install        # Backend only
moon run frontend:install       # Frontend only

# Development servers
moon run backend:dev            # FastAPI on :8000
moon run frontend:dev           # Next.js on :3000

# Testing
moon run :test                  # All tests
moon run backend:test           # Backend tests (auto-starts DB)
moon run frontend:test          # Frontend tests

# Code quality
moon run :lint                  # Lint all
moon run backend:format         # Format Python
```

---

## Database Lifecycle (scripts/test_backend.sh)

### Design: Reference Counting

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Terminal 1  │     │  Terminal 2  │     │  Terminal 3  │
│ moon test    │     │ moon test    │     │ moon test    │
└──────┬───────┘     └──────┬───────┘     └──────┬───────┘
       │                    │                    │
       │  refcount=1        │                    │
       ├───────────────────►│  refcount=2        │
       │                    ├───────────────────►│  refcount=3
       │                    │                    │
       │                    │ exit               │
       │                    │  refcount=2        │
       │ exit               │                    │
       │  refcount=1        │                    │
       │                    │                    │ exit
       │                    │                    │  refcount=0
       │                    │                    │  ▶ Container stopped
```

### Key Features

1. **Auto-detect runtime**: podman compose → podman-compose → docker compose → docker-compose
2. **Lock file**: `~/.cache/finance_report/db.lock` prevents race conditions
3. **State file**: `~/.cache/finance_report/db.state` tracks refcount and container ID
4. **Auto-cleanup**: Last test runner stops the container

### Why Not Manual Start/Stop?

| Approach | Pros | Cons |
|----------|------|------|
| ~~Manual `docker compose up/down`~~ | Simple | Forgot to stop = hot laptop |
| ~~Per-test ephemeral container~~ | No conflicts | Slow cold starts |
| **Reference counting** ✓ | Shared DB, auto-cleanup | Slightly complex script |

---

## Environment Configurations

### Local Development
```bash
# Uses docker-compose.ci.yml services
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report
```

### Local Testing (via moon run backend:test)
```bash
# Managed by scripts/test_backend.sh
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report_test
```

### GitHub CI
```yaml
# Uses GitHub Actions services
services:
  postgres:
    image: postgres:15
    env:
      POSTGRES_DB: finance_report_test
```

---

## Verification

### Check DB Script Works
```bash
# Start two terminals, run tests in each
# Terminal 1:
moon run backend:test

# Terminal 2 (while 1 is running):
moon run backend:test

# Both should share same container
podman ps | grep finance_report_db

# After both exit, container should be gone
podman ps | grep finance_report_db  # No output
```

### Check Moon Tasks
```bash
moon query tasks --affected
moon run backend:test --log debug
```
