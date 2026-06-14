# EPIC-001: Infrastructure & Authentication

> **Status**: 🟢 Complete (Deferred items tracked below)  
> **Vision Anchor**: `decision-7-tech-stack`  
> **Phase**: 0  
> **Duration**: 2 weeks  
> **Dependencies**: None  

---

## 🎯 Objective

Set up a runnable Monorepo development environment, complete user authentication and basic project skeleton.

**From the project plan — Phase 0 alignment**

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Technology Stack | Moonrepo + FastAPI + Next.js combination validated, meets multi-language monorepo requirements |
| 💻 **Developer** | Developer Experience | Hot reload, type hints, debugging toolchain complete |
| 📋 **PM** | MVP Value | Minimal demo version (ping-pong demo) validates end-to-end connectivity |
| 🧪 **Tester** | Testing Foundation | pytest + vitest frameworks configured, CI ready |

---

## ✅ Task Checklist

### Moonrepo Workspace
- [x] Create `moon.yml` workspace configuration
- [x] Configure `apps/backend/moon.yml` tasks
- [x] Configure `apps/frontend/moon.yml` tasks
- [x] Configure local infrastructure commands through `tools/infra.sh`

### Backend Skeleton
- [x] FastAPI project structure (`apps/backend/src/`)
- [x] FastAPI Users authentication integration (registration/login/JWT)
- [x] SQLAlchemy 2 + Alembic configuration
- [x] Health check endpoint `/health`
- [x] structlog structured logging
- [x] pre-commit hooks (ruff + hygiene checks)

### Frontend Skeleton
- [x] Next.js 14 App Router initialization
- [x] shadcn/ui component library configuration
- [x] TailwindCSS setup
- [x] Minimal homepage (ping-pong demo)
- [x] TanStack Query configuration
- [ ] Zustand state management → EPIC-002

### Docker Environment
- [x] `docker-compose.yml` for local development
- [x] PostgreSQL 15 container
- [x] Redis 7 container (optional)
- [x] Data volume configuration

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/auth/`, `apps/backend/tests/infra/`, `apps/backend/tests/api/`

### AC1.1: Moon Workspace Requirements

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.1.1 | Root `moon.yml` exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |
| AC1.1.2 | `apps/backend/moon.yml` exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |
| AC1.1.3 | `apps/frontend/moon.yml` exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |
| AC1.1.4 | `tools/infra.sh` local infrastructure command exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |

### AC1.2: Backend Skeleton Requirements

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.2.1 | FastAPI project structure exists | `test_epic_001_backend_skeleton_exists()` | `infra/test_epic_001_contracts.py` |
| AC1.2.2 | Auth integration works (register/login/JWT) | `test_register_success()`, `test_login_success()`, `test_auth_valid_user()` | `auth/test_auth_router.py`, `auth/test_auth.py` |
| AC1.2.3 | SQLAlchemy + Alembic config valid | `test_missing_migrations_check()`, `test_single_head()` | `infra/test_schema_drift.py`, `infra/test_migrations.py` |
| AC1.2.4 | Health endpoint returns success | `test_health_when_all_services_healthy()` | `infra/test_main.py` |
| AC1.2.5 | structlog logging configured | `test_configure_logging_basic()` | `infra/test_logger.py` |

### AC1.3: Frontend Skeleton Requirements

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.3.1 | Next.js App Router files exist | `test_epic_001_frontend_skeleton_exists()` | `infra/test_epic_001_contracts.py` |
| AC1.3.2 | TailwindCSS configuration exists | `test_epic_001_frontend_skeleton_exists()` | `infra/test_epic_001_contracts.py` |
| AC1.3.3 | Ping-pong page exists | `test_epic_001_frontend_skeleton_exists()` | `infra/test_epic_001_contracts.py` |
| AC1.3.4 | TanStack Query dependency configured | `test_epic_001_frontend_uses_react_query()` | `infra/test_epic_001_contracts.py` |

### AC1.4: Docker Environment Requirements

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.4.1 | `docker-compose.yml` integrity valid | `test_docker_compose_integrity()` | `infra/test_ci_config.py` |
| AC1.4.2 | PostgreSQL 15 container defined | `test_epic_001_docker_compose_contract()` | `infra/test_epic_001_contracts.py` |
| AC1.4.3 | Redis 7 container defined | `test_epic_001_docker_compose_contract()` | `infra/test_epic_001_contracts.py` |
| AC1.4.4 | Data volumes configured | `test_epic_001_docker_compose_contract()` | `infra/test_epic_001_contracts.py` |

### AC1.5: Must-Have Acceptance Criteria Coverage

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.5.1 | Backend startup command path is valid | `test_moon_project_graph_static_contract()` | `infra/test_ci_config.py` |
| AC1.5.2 | Frontend startup command path is valid | `test_epic_001_frontend_moon_tasks_configured()` | `infra/test_epic_001_contracts.py` |
| AC1.5.3 | Health endpoint returns 200 | `test_health_when_all_services_healthy()` | `infra/test_main.py` |
| AC1.5.4 | Backend ping-pong endpoint toggles state correctly | `test_ping_toggle()` | `infra/test_main.py` |
| AC1.5.5 | User registration/login API available | `test_register_success()`, `test_login_success()` | `auth/test_auth_router.py` |

### AC1.6: Deferred Item Tracking (Now Test-Tracked)

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.6.1 | Pre-commit hooks configuration present | `test_epic_001_pre_commit_config_exists()` | `infra/test_epic_001_contracts.py` |
| AC1.6.2 | get_pending_stage1_review returns empty when no pending statements. | `test_returns_empty_when_none_pending` | `review/test_statement_validation.py` | P1 |

### AC1.7: Auth Endpoint Behavioral Coverage

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.7.1 | Register endpoint accepts valid user payload | `test_register_success()` | `auth/test_auth_router.py` |
| AC1.7.2 | Register endpoint rejects duplicate email | `test_register_duplicate_email()` | `auth/test_auth_router.py` |
| AC1.7.3 | Login endpoint accepts valid credentials | `test_login_success()` | `auth/test_auth_router.py` |
| AC1.7.4 | Register endpoint handles IntegrityError race on duplicate email. | `test_register_integrity_error_race_condition` | `auth/test_auth_router.py` | P1 |

### AC1.8: User Management Endpoint Coverage

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.8.1 | User management endpoints expose authenticated user operations without cross-user leakage | `test_users_router.py` suite | `auth/test_users_router.py` |

### AC1.9: First-Run Ledger Journey Coverage

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.9.1 | A new user can register, log in, create first ledger accounts, post a first manual entry, and preserve the accounting equation | `test_AC1_9_1_first_run_registration_account_entry_journey` | `integration/test_onboarding_e2e.py` |

### AC1.10: Auth & Browser Security Hardening

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.10.1 | Protected runtime startup rejects missing, default, short, or local-development secret/database/storage configuration | `test_AC1_10_1_static_config_*` | `infra/test_boot.py` |
| AC1.10.2 | Email identity is normalized for registration and login so case variants cannot create duplicate users | `test_AC1_10_2_*` | `auth/test_auth_router.py` |
| AC1.10.3 | Browser authentication uses an HttpOnly session cookie by default while frontend storage keeps only non-secret user metadata | `test_AC1_10_3_get_me_accepts_httponly_cookie` / `AC1.10.3 sends HttpOnly auth cookies by default` / `auth.test.ts` session tests | `auth/test_auth_router.py`, `src/__tests__/apiFunctions.test.ts`, `src/__tests__/auth.test.ts` |
| AC1.10.4 | Frontend production dependency audits fail CI and CSP forbids `unsafe-eval` in shipped responses | `AC1.10.4 configures browser security headers without unsafe eval` / `npm run audit:prod` | `src/__tests__/api-urls.test.ts`, `.github/workflows/ci.yml` |

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|------|----------|------|
| `bash tools/infra.sh up` successfully starts database | Manual verification | ✅ |
| `moon run :dev -- --backend` starts FastAPI | Console without errors | ✅ |
| `moon run :dev -- --frontend` starts Next.js | Access localhost:3000 | ✅ |
| `/api/health` returns 200 OK | curl test | ✅ |
| Frontend-backend ping-pong communication | Page displays "pong" | ✅ |
| User registration/login API available | Postman test | ✅ |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| GitHub Actions CI configuration | Automatic PR checks | ⏳ |
| pre-commit hooks configuration | Auto-formatting on commit | ✅ |
| Complete README documentation | New developers onboarded in 10 minutes | ✅ |
| Test coverage > 50% | coverage report | ⏳ |

### 🚫 Not Acceptable

- Startup commands fail with errors
- Database connection failure
- Authentication endpoint returns 500 errors
- Frontend cannot access backend API

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - Database structure
- [accounting.md](../ssot/accounting.md) - Accounting model

---

## 🔗 Deliverables

- [x] Runnable `apps/backend/` project
- [x] Runnable `apps/frontend/` project
- [x] `docker-compose.yml` local environment
- [x] `README.md` quick start guide

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [Root README](https://github.com/wangzitian0/finance_report/blob/main/README.md) — root project entry point.
- [../index.md](../index.md) — documentation site navigation.
- [../user-guide/getting-started.md](../user-guide/getting-started.md) — first-use guide and onboarding route.
- [Backend README](https://github.com/wangzitian0/finance_report/blob/main/apps/backend/README.md) — backend module entry point.
- [Frontend README](https://github.com/wangzitian0/finance_report/blob/main/apps/frontend/README.md) — frontend module entry point.
- [../reference/api-overview.md](../reference/api-overview.md) — API conventions and auth entry point.
- [../ssot/auth.md](../ssot/auth.md) — authentication architecture rationale.
- [../ssot/frontend-patterns.md](../ssot/frontend-patterns.md) — frontend integration and API-client patterns.

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| pre-commit hooks | P2 | During EPIC-002 |
| GitHub Actions CI | P1 | Before EPIC-002 completion |

---

## Issues & Gaps

- [x] Status is marked "Complete" while the checklist still has deferred items (pre-commit hooks, Zustand), which makes Phase 0 exit criteria ambiguous.
- [x] Legacy Moon Docker project command migrated to `tools/infra.sh up`; root `infra/` project removed.
- [x] Ping demo API/Frontend field mismatch (`updated_at` vs `last_toggled`) fixed for consistency.

---

## ❓ Q&A (Clarification Required)

> This EPIC is complete. No pending questions.

---

## 📅 Timeline

- **Start**: 2026-01-06
- **Completion**: 2026-01-09
- **Actual Hours**: ~12 hours
