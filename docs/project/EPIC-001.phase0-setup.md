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
> **Coverage**: See `apps/backend/tests/identity/`, `apps/backend/tests/infra/`, `apps/backend/tests/api/`

### AC1.1: Moon Workspace Requirements

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.1.1 | Root `moon.yml` exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |
| AC1.1.2 | `apps/backend/moon.yml` exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |
| AC1.1.3 | `apps/frontend/moon.yml` exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |
| AC1.1.4 | `tools/infra.sh` local infrastructure command exists | `test_epic_001_moon_workspace_configs_exist()` | `infra/test_epic_001_contracts.py` |

### AC1.2: Backend Skeleton Requirements

> This group's second row removed as a stale duplicate — the cited tests
> already prove `AC-identity.2.1`/`.2.2` in `common/identity/contract.py`'s
> roadmap (migration closeout continuation, #1663 / #1706).

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.2.1 | FastAPI project structure exists | `test_epic_001_backend_skeleton_exists()` | `infra/test_epic_001_contracts.py` |
| AC1.2.3 | SQLAlchemy + Alembic config valid | `test_missing_migrations_check()`, `test_single_head()` | `infra/test_schema_drift.py`, `infra/test_migrations.py` |
| AC1.2.4 | Health endpoint returns success | `test_health_when_all_services_healthy()` | `infra/test_main.py` |

> (AC1.2.2 removed, canonical: "Auth integration works" cited three tests —
> `test_register_success` and `test_login_success` were already migrated to
> [`common/identity/contract.py`](../../common/identity/contract.py) as
> `AC-identity.2.1`/`.2.2`; the third, `test_auth_valid_user`, migrated to
> `AC-identity.2.4`, migration closeout wave 3, #1663.)
>
> (AC1.2.5 removed, duplicate: "structlog logging configured"
> (`test_configure_logging_basic`) was already fully migrated to
> `AC-observability.1.5` — this row was a stale duplicate, no new migration
> needed.)

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

> **The former "User registration/login API available" criterion (AC1.5.x.5) is
> no longer defined here.** It migrated into the `identity` package as
> **`AC-identity.2.1`** / **`AC-identity.2.2`** — owned by, and sourced
> directly from, [`common/identity/contract.py`](../../common/identity/contract.py)'s
> `roadmap` (#1428). `common/meta/extension/generate_ac_registry.py` reads package-contract
> roadmaps additively, so the AC index counts them without an EPIC-table mirror.
> This note references the new ids (keeping the registry↔EPIC link intact) but
> defines none of them — the contract is the single definition source.

### AC1.6: Deferred Item Tracking (Now Test-Tracked)

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.6.1 | Pre-commit hooks configuration present | `test_epic_001_pre_commit_config_exists()` | `infra/test_epic_001_contracts.py` |

> (AC1.6.2 removed, canonical: "`get_pending_stage1_review` returns empty when
> no pending statements" migrated into the `extraction` package as
> **`AC-extraction.stage1-review.1`** — owned by, and sourced directly from,
> [`common/extraction/contract.py`](../../common/extraction/contract.py)'s
> `roadmap`, migration closeout wave 3, #1663.)

### AC1.7: Auth Endpoint Behavioral Coverage

> **The former auth-endpoint behavioral-coverage criteria (the AC1.7 register/login
> rows) are no longer defined here.** They migrated into the `identity` package
> (#1428) and are owned by, and sourced directly from,
> [`common/identity/contract.py`](../../common/identity/contract.py)'s `roadmap`:
> - register accepts a valid payload → **`AC-identity.2.1`**
> - register rejects a duplicate email → **`AC-identity.1.1`**
> - login accepts valid credentials → **`AC-identity.2.2`**
> - register handles the duplicate-email IntegrityError race → **`AC-identity.2.3`**
>
> `common/meta/extension/generate_ac_registry.py` reads package roadmaps additively, so the
> index counts them without an EPIC-table mirror. This note references the new ids
> but defines none of them — the contract is the single definition source.

### AC1.8: User Management Endpoint Coverage

> **The former user-management endpoint-coverage criterion (the AC1.8 row) is no
> longer defined here.** It migrated into the `identity` package (#1428) as
> **`AC-identity.1.3`** — owned by, and sourced directly from,
> [`common/identity/contract.py`](../../common/identity/contract.py)'s `roadmap`
> (user management exposes authenticated current-user operations without
> cross-user leakage). This note references the new id but defines it elsewhere —
> the contract is the single definition source.

### AC1.9: First-Run Ledger Journey Coverage

> (AC1.9.1 removed, canonical: "a new user can register, log in, create first
> ledger accounts, post a first manual entry, and preserve the accounting
> equation" migrated into the `ledger` package as **`AC-ledger.77.1`** — owned
> by, and sourced directly from,
> [`common/ledger/contract.py`](../../common/ledger/contract.py)'s `roadmap`,
> migration closeout wave 3, #1663; the journey's defining assertion is the
> ledger's accounting equation, so ledger is the home package even though the
> journey starts through identity's register/login endpoints.)

### AC1.10: Auth & Browser Security Hardening

> (AC1.10.1 removed, canonical: "protected runtime startup rejects
> missing/default/short/local-development config" migrated into the `runtime`
> package as **`AC-runtime.21.1`** through **`.6`** (one record per
> `Bootloader._check_static_config` rejection branch) — owned by, and sourced
> directly from,
> [`common/runtime/contract.py`](../../common/runtime/contract.py)'s
> `roadmap`, migration closeout wave 3, #1663.)
>
> **AC1.10.3**'s backend half (`test_AC1_10_3_get_me_accepts_httponly_cookie`)
> migrated to [`common/identity/contract.py`](../../common/identity/contract.py)'s
> `roadmap` as **`AC-identity.2.5`** (migration closeout wave 3, #1663). The
> row's frontend-storage half stays here (no backend package home):

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.10.3 | Frontend storage keeps only non-secret user metadata, relying on the HttpOnly session cookie rather than localStorage for the bearer token | `AC1.10.3 sends HttpOnly auth cookies by default` / `auth.test.ts` session tests | `src/__tests__/apiFunctions.test.ts`, `src/__tests__/auth.test.ts` |

> **The former email-normalization criterion (the AC1.10 normalize-email row) is
> no longer defined here.** It migrated into the `identity` package (#1428) as
> **`AC-identity.1.2`** — owned by, and sourced directly from,
> [`common/identity/contract.py`](../../common/identity/contract.py)'s `roadmap`.
> This note references the new id but defines it elsewhere — the contract is the
> single definition source. (The config-hardening and frontend/browser-security
> rows above stay — they are cross-cutting, not identity-owned.)
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
- [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) - Accounting model

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
- [../../common/identity/readme.md](../../common/identity/readme.md) — backend authentication architecture (the `identity` package, #1428).
- [../ssot/frontend-patterns.md](../ssot/frontend-patterns.md) — frontend integration, API-client, and browser-auth/session patterns.

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
