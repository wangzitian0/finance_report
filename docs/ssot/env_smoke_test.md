# Environment Architecture & Verification (Three Gates)

> **SSOT Key**: `architecture_env`
> **Source of Truth** for how environments are validated across lifecycle stages.

## Core Philosophy: "One Codebase, One Standard"

We solve the "42 combinations" problem (Local vs CI vs Staging...) by using a **single** validation engine (`src/boot.py`) across all environments.

The architecture enforces "Three Gates" of increasing strictness.

## The Three Gates

| Gate | Name | Mode | When? | Validation Scope | Failure Consequence |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | **Static** | `dry-run` | **Build / CI** | ✅ Config Integrity (Keys present) <br> ✅ Code Importable | **Build Fail** / **CI Fail** <br> (Prevent bad code merge) |
| **2** | **Startup** | `critical` | **App Start** | ✅ **Database Connectivity** <br> ✅ Schema/Migration Sync | **CrashLoopBackOff** <br> (Fail Fast, refuse to serve) |
| **3** | **Health** | `full` | **Runtime** | ✅ **Full Stack** (Redis, S3, AI) <br> ✅ Latency & Integration | **Alert / 503** <br> (Traffic draining / PagerDuty) |

---

## 1. Unified Implementation (`src/boot.py`)

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

## 2. Environment Mapping

Every environment maps to one of the 3 Gates using the exact same code.

### 💻 Local Development
- **Gate 2 (Startup)**: `moon run backend:dev` calls `Bootloader(CRITICAL)`.
  - Effect: If DB is down, uvicorn refuses to start.
- **Gate 3 (Verification)**: Developer runs `python -m src.boot --mode full`.
  - Effect: Validates local MinIO/Redis setup.

### 🤖 CI (GitHub Actions)
- **Gate 1 (Static)**: CI pipeline runs `python -m src.boot --mode dry-run`.
  - Effect: Fails if `.env.example` or `config.py` are broken.
- **Gate 2 (Test)**: `pytest` fixture implicitly verifies DB connectivity.
  - Effect: Tests fail fast if service container is missing.

### 🚀 Production / Staging
- **Gate 2 (Startup)**: Container entrypoint uses `Bootloader(CRITICAL)` (via `main.py`).
  - Effect: Pod crashes if DB params are wrong (visible to K8s).
- **Gate 3 (Runtime)**: Load Balancer calls `/health`.
  - Effect: Endpoint internally calls `Bootloader` methods. Returns 200 OK only if full stack is healthy.

## 3. How to Verify

### Standard Verification Command
Run this in any environment (Local, Pod shell, CI runner):

```bash
# Check everything
uv run python -m src.boot --mode full
```

### Output Reference
```text
Bootloader: Running validation cycle (mode=full)
✅ Dry-run configuration check passed.
[info] Service check passed service=database
[info] Service check passed service=redis
[info] Service check passed service=minio
✅ Validation check passed.
```

## 4. Debugging Guide

### "Gate 2 Failed: Startup Crash"
- **Symptom**: App exits immediately with exit code 1.
- **Cause**: Database unreachable or `DATABASE_URL` invalid.
- **Fix**: Check `docker/podman ps` for database container.

### "Gate 3 Failed: 503 Service Unavailable"
- **Symptom**: `/health` returns 503.
- **Cause**: Optional dependency (Redis/S3) missing or misconfigured.
- **Fix**:
  - Local: Ensure `dev_backend.py` started the full stack (Redis/MinIO).
  - Prod: Check AWS/Cloud credentials or Security Groups.

## 5. Relationship to Other Tests

| Test Type | Tool | Purpose |
| :--- | :--- | :--- |
| **Environment Check** | `src.boot` | **Internal Connectivity**. "Can the App talk to DB?" |
| **E2E Smoke Test** | `scripts/smoke_test.sh` | **External Availability**. "Can the User talk to the App?" |

Both are required for a healthy system. `src.boot` is the foundation; `smoke_test.sh` is the acceptance.
