# Environment Smoke Test (Source of Truth)

> **SSOT Key**: `env_smoke_test`
> **Purpose**: Environment validation across lifecycle stages using the Three Gates architecture.

---

## 1. Source of Truth

### Physical File Locations

| File | Purpose |
|------|---------|
| `apps/backend/src/boot.py` | Unified validation engine (Three Gates) |
| `apps/backend/src/config.py` | Environment variable definitions |
| `scripts/smoke_test.sh` | External E2E smoke tests |
| `.env.example` | Environment variable documentation |

### Core Philosophy: "One Codebase, One Standard"

We solve the "42 combinations" problem (Local vs CI vs Staging...) by using a **single** validation engine (`src/boot.py`) across all environments.

---

## 2. Architecture Model

### The Three Gates

| Gate | Name | Mode | When? | Validation Scope | Failure Consequence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Static** | `dry-run` | **Build / CI** | ✅ Config Integrity (Keys present) <br> ✅ Code Importable | **Build Fail** / **CI Fail** <br> (Prevent bad code merge) |
| **2** | **Startup** | `critical` | **App Start** | ✅ **Database Connectivity** <br> ✅ Schema/Migration Sync | **CrashLoopBackOff** <br> (Fail Fast, refuse to serve) |
| **3** | **Health** | `full` | **Runtime** | ✅ **Full Stack** (Redis, S3, AI) <br> ✅ Latency & Integration | **Alert / 503** <br> (Traffic draining / PagerDuty) |

### Unified Implementation (`src/boot.py`)

This file is the **Sole Authority** for validation.

```python
# Pseudo-code logic of src/boot.py
class Bootloader:
    def validate(mode):
        check_config()                  # Always run (Gate 1)
        if mode == DRY_RUN: return      # Stop here for CI

        check_database()                # Always run (Gate 2)
        if mode == CRITICAL: return     # Stop here for App Start

        check_redis()                   # Run only for Full/Health (Gate 3)
        check_s3()
        check_ai()
```

### Environment Mapping

Every environment maps to one of the 3 Gates using the exact same code.

#### 💻 Local Development

- **Gate 2 (Startup)**: `moon run backend:dev` calls `Bootloader(CRITICAL)`.
  - Effect: If DB is down, uvicorn refuses to start.
- **Gate 3 (Verification)**: Developer runs `python -m src.boot --mode full`.
  - Effect: Validates local MinIO/Redis setup.

#### 🤖 CI (GitHub Actions)

- **Gate 1 (Static)**: CI pipeline runs `python -m src.boot --mode dry-run`.
  - Effect: Fails if `.env.example` or `config.py` are broken.
- **Gate 2 (Test)**: `pytest` fixture implicitly verifies DB connectivity.
  - Effect: Tests fail fast if service container is missing.

#### 🚀 Production / Staging

- **Gate 2 (Startup)**: Container entrypoint uses `Bootloader(CRITICAL)` (via `main.py`).
  - Effect: Pod crashes if DB params are wrong (visible to K8s).
- **Gate 3 (Runtime)**: Load Balancer calls `/health`.
  - Effect: Endpoint internally calls `Bootloader` methods. Returns 200 OK only if full stack is healthy.

### Relationship to Other Tests

| Test Type | Tool | Purpose |
| :--- | :--- | :--- |
| **Environment Check** | `src.boot` | **Internal Connectivity**. "Can the App talk to DB?" |
| **E2E Smoke Test** | `scripts/smoke_test.sh` | **External Availability**. "Can the User talk to the App?" |

Both are required for a healthy system. `src.boot` is the foundation; `smoke_test.sh` is the acceptance.

---

## 3. Design Constraints

### Hard Rules

| Rule | Description |
|------|-------------|
| **Single Validation Engine** | All environments MUST use `src/boot.py` — no custom scripts per environment |
| **Gate Progression** | Gate 1 < Gate 2 < Gate 3 — each gate includes all previous checks |
| **Fail Fast** | Gate 2 failures MUST crash the app — never serve traffic with broken DB |
| **No Secrets in Logs** | Validation output MUST NOT log sensitive values |

### Mode Selection

| Mode | Gate | Use Case |
|------|------|----------|
| `dry-run` | 1 | CI builds, config validation |
| `critical` | 2 | App startup, database-required operations |
| `full` | 3 | Health checks, full stack verification |

---

## 4. Playbooks (SOP)

### Standard Verification Command

Run this in any environment (Local, Pod shell, CI runner):

```bash
# Check everything (Gate 3)
moon run backend:env-check

# Or directly:
uv run python -m src.boot --mode full
```

### Gate-Specific Checks

```bash
# Gate 1: Static validation only
uv run python -m src.boot --mode dry-run

# Gate 2: Database connectivity
uv run python -m src.boot --mode critical

# Gate 3: Full stack (Redis, S3, AI)
uv run python -m src.boot --mode full
```

### Debugging Guide

#### "Gate 2 Failed: Startup Crash"

- **Symptom**: App exits immediately with exit code 1.
- **Cause**: Database unreachable or `DATABASE_URL` invalid.
- **Fix**: Check `docker/podman ps` for database container.

```bash
# Check database container
docker ps | grep finance-report-db
# Or
podman ps | grep finance-report-db

# Verify connection
psql $DATABASE_URL -c "SELECT 1"
```

#### "Gate 3 Failed: 503 Service Unavailable"

- **Symptom**: `/health` returns 503.
- **Cause**: Optional dependency (Redis/S3) missing or misconfigured.
- **Fix**:
  - Local: Ensure `dev_backend.py` started the full stack (Redis/MinIO).
  - Prod: Check AWS/Cloud credentials or Security Groups.

```bash
# Check all services
docker ps | grep finance-report

# Test Redis
redis-cli ping

# Test MinIO
curl http://localhost:9000/minio/health/live
```

---

## 5. Verification (The Proof)

### Expected Output (Success)

```text
Bootloader: Running validation cycle (mode=full)
✅ Dry-run configuration check passed.
[info] Service check passed service=database
[info] Service check passed service=redis
[info] Service check passed service=minio
✅ Validation check passed.
```

### Expected Output (Failure)

```text
Bootloader: Running validation cycle (mode=full)
✅ Dry-run configuration check passed.
[error] Service check failed service=database error="Connection refused"
❌ Validation failed at Gate 2
```

### Verification Commands

```bash
# Quick check
moon run backend:env-check

# Full verification with verbose output
uv run python -m src.boot --mode full --verbose

# CI-style check (exit code only)
uv run python -m src.boot --mode dry-run && echo "Gate 1 passed"
```

---

*Last updated: 2026-01-27*
