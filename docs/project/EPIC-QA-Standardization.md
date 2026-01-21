# EPIC: Quality Assurance & Standardization Plan

**Owner**: Sisyphus
**Status**: Planning
**Date**: 2026-01-21

## 1. Overview
This plan addresses the "pitfalls" identified in recent PRs regarding environment variables, routing inconsistencies, database schema fragility, and data type integrity.

## 2. Action Items

### 2.1 ☠️ Environment Variables & Secrets (The "Triangle of Death")
**Problem**: Desynchronization between `.env`, `config.py`, `secrets.ctmpl`, and Docker `ARG`.
- [ ] **Doc**: Update `docs/ssot/development.md` with a "Variable Lifecycle" flowchart.
  - Define exactly where each variable must live based on its type (Build-time vs Runtime vs Secret).
- [ ] **Test**: Enhance `scripts/check_env_keys.py` (or create `tests/infra/test_env_consistency.py`).
  - Verify strict 1:1 mapping between `config.py` fields and `.env.example`.
  - Warn if `secrets.ctmpl` contains keys not in `config.py`.

### 2.2 🕸️ Routing & API Prefix (Local vs Staging)
**Problem**: Inconsistent `BASE_URL` handling causes 404s on Staging (double `/api` prefix).
- [ ] **Doc**: Update `apps/frontend/README.md` and `docs/ssot/development.md`.
  - Explicitly document `NEXT_PUBLIC_API_URL` usage: "Must NOT end with slash".
- [ ] **Refactor**: Review `apps/frontend/src/lib/api.ts`.
  - Ensure it strips trailing slashes from base URL or handles double slashes.
- [ ] **Test**: Add `apps/frontend/src/lib/api.test.ts` (Unit Test).
  - Test cases: `http://localhost:8000`, `https://api.example.com/api`, `https://api.example.com/api/` (trailing slash).

### 2.3 🐘 Database Migrations & Schema (The "Silent Killers")
**Problem**: `sa.Enum` without explicit names cause migration conflicts; Alembic revision IDs too long.
- [ ] **Doc**: Update `docs/ssot/schema.md`.
  - Add "Migration Rules": "Enums must have `name='...'`", "Rev IDs max 12 chars".
- [ ] **Test**: Create `apps/backend/tests/test_schema_guardrails.py`.
  - Inspect all SQLAlchemy models via inspection API.
  - Fail if any `sa.Enum` lacks `name`.
  - Fail if any Alembic revision file name > threshold.

### 2.4 💸 Data Integrity (Float vs Decimal)
**Problem**: AI extraction returns floats, Pydantic might accept them if not strict, leading to precision loss.
- [ ] **Doc**: Update `docs/ssot/accounting.md` and `docs/ssot/extraction.md`.
  - "The Float Ban": Strict standard for parsing AI output.
- [ ] **Test**: Create `apps/backend/tests/test_decimal_safety.py`.
  - Fuzz testing: Feed `{ amount: 100.50 }` (float) to all financial Pydantic models.
  - Ensure they convert to `Decimal` strictly or raise error (depending on policy).

## 3. Implementation Order
1. **SSOT Updates** (Docs) - Define the rules first.
2. **Backend Tests** (Schema & Decimal) - High impact, high risk.
3. **Infra Tests** (Env vars) - Prevent deployment failures.
4. **Frontend Fixes** (Routing) - Fix staging issues.
