# EPIC-001: Infrastructure & Authentication

> **Status**: 🟢 Complete (Deferred items tracked below)  
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
- [x] Configure `infra/moon.yml` tasks

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
| AC1.1.4 | `infra/moon.yml` exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |

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
| AC1.5.1 | Backend startup command path is valid | `test_moon_project_graph()` | `infra/test_ci_config.py` |
| AC1.5.2 | Frontend startup command path is valid | `test_epic_001_frontend_moon_tasks_configured()` | `infra/test_epic_001_contracts.py` |
| AC1.5.3 | Health endpoint returns 200 | `test_health_when_all_services_healthy()` | `infra/test_main.py` |
| AC1.5.4 | Backend ping-pong endpoint toggles state correctly | `test_ping_toggle()` | `infra/test_main.py` |
| AC1.5.5 | User registration/login API available | `test_register_success()`, `test_login_success()` | `auth/test_auth_router.py` |

### AC1.6: Deferred Item Tracking (Now Test-Tracked)

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.6.1 | Pre-commit hooks configuration present | `test_epic_001_pre_commit_config_exists()` | `infra/test_epic_001_contracts.py` |

### AC1.7: Auth Endpoint Behavioral Coverage

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.7.1 | Register endpoint accepts valid user payload | `test_register_success()` | `auth/test_auth_router.py` |
| AC1.7.2 | Register endpoint rejects duplicate email | `test_register_duplicate_email()` | `auth/test_auth_router.py` |
| AC1.7.3 | Login endpoint accepts valid credentials | `test_login_success()` | `auth/test_auth_router.py` |

**Traceability Result**:
- Requirements converted to AC IDs: 100% (EPIC-001 checklist + must-have standards)
- Requirements with automated test references: 100%

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|------|----------|------|
| `docker compose up -d` successfully starts database | Manual verification | ✅ |
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

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| pre-commit hooks | P2 | During EPIC-002 |
| GitHub Actions CI | P1 | Before EPIC-002 completion |

---

## Issues & Gaps

- [x] Status is marked "Complete" while the checklist still has deferred items (infra/moon.yml, pre-commit hooks, Zustand), which makes Phase 0 exit criteria ambiguous.
- [x] Phase 0 plan references `infra:docker:up`; without infra/moon.yml tasks, the Moon workflow is incomplete for local docker.
- [x] Ping demo API/Frontend field mismatch (`updated_at` vs `last_toggled`) fixed for consistency.

---

## ❓ Q&A (Clarification Required)

> This EPIC is complete. No pending questions.

---

## 📅 Timeline

- **Start**: 2026-01-06
- **Completion**: 2026-01-09
- **Actual Hours**: ~12 hours
