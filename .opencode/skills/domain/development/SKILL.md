---
name: development
description: Development environment, testing, CI/CD, and deployment procedures. Use this skill when working with moon commands, database lifecycle, GitHub Actions, or deployment workflows.
---

# Development Environment

> **Core Definition**: Local development, testing, CI, and deployment.

## Moon Commands (Primary Interface)

Day-to-day work goes through root tasks (`:dev`, `:test`, `:lint`, `:build`); the
`apps/*` projects declare no tasks of their own, and sub-targets are passed via
`--`. A few helpers run as plain scripts (e.g. smoke tests), noted inline below.

```bash
# Development
moon run :dev -- --infra          # Start local infra
moon run :dev -- --backend        # FastAPI on :8000 (after infra)
moon run :dev -- --frontend       # Next.js on :3000

# Testing (all via :test; auto-manages DB)
moon run :test                    # All tests
moon run :test -- --fast          # Fast TDD loop (no coverage)
moon run :test -- --smart         # Coverage on changed files only
moon run :test -- tests/accounting/   # Specific module/file
bash tools/smoke_test.sh          # Unified smoke tests (no moon task)

# Code Quality
moon run :lint                    # Lint all
moon run :lint -- --fix           # Format/auto-fix

# Build
moon run :build                   # Build all
```

## Database Lifecycle

### Reference Counting

```
Terminal 1: moon run :test  → refcount=1 (start container)
Terminal 2: moon run :test  → refcount=2
Terminal 2 exits                   → refcount=1
Terminal 1 exits                   → refcount=0 (stop container)
```

### Local Test Isolation

- Set `BRANCH_NAME=<branch_name>` to namespace test resources
- Use `WORKSPACE_ID=<id>` to isolate multiple working copies
- Test DB container name includes the branch suffix

## Six Scenarios

| # | Scenario | Trigger | Tests | Goal |
|---|----------|---------|-------|------|
| 1 | Local Dev | Manual | None | Iteration speed |
| 2 | Local Test | `moon run :test` | Unit+Integration | <30s feedback |
| 3 | Remote CI | PR / Push | Unit+Integration | Quality gate |
| 4 | PR Test | PR opened | Health Check | Deployment validation |
| 5 | Staging | Push to main | Smoke + Perf | Full validation |
| 6 | Production | Manual dispatch | Health Check | Minimal validation |

## Coverage Gate

- Backend line coverage must be **>= 95%** (`--cov-fail-under=95`)

## Environment Variable Lifecycle

1. **Frontend (Next.js)**: `NEXT_PUBLIC_` prefix, must be in `Dockerfile` `ARG`
2. **Backend (FastAPI)**: Must have type and default in `config.py`
3. **Production (Vault)**: Secrets in `secrets.ctmpl`, validated by CI

## Source Files

| File | Purpose |
|------|---------|
| `moon.yml` | Root workspace tasks |
| `apps/*/moon.yml` | Per-project tasks |
| `tools/test_lifecycle.py` | Database lifecycle |
| `docker-compose.yml` | Development containers |
| `.github/workflows/ci.yml` | GitHub Actions CI |
