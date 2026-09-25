# EPIC-001: Infrastructure & Authentication

> **Status**: 🟢 Complete  
> **Vision Anchor**: `decision-7-tech-stack`  
> **Phase**: 0  
> **Duration**: 2 weeks  
> **Dependencies**: None  

---

## 🎯 Objective

Set up a runnable Monorepo development environment, complete user authentication and basic project skeleton.

**From the project plan — Phase 0 alignment**

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

## 🧪 Test Cases / Acceptance Criteria

> **Migrated (#1821 Waves A/B, #1663/#1706/#1714 closeout):** every former
> AC1.x.y row now lives in its owning package's `contract.py` `roadmap` —
> `AC-meta.phase0.*` (meta), `AC-runtime.7.1`/`AC-runtime.21.*` (runtime),
> `AC-identity.*` (identity), `AC-ledger.77.1` (ledger),
> `AC-observability.1.5` (observability). The package contracts are the
> single definition source; this section intentionally holds only the one
> genuinely horizontal residue row below.

### AC1.10: Auth & Browser Security Hardening

| ID | Requirement | Test Function | File |
|----|-------------|---------------|------|
| AC1.10.4 | Frontend production dependency audits fail CI and CSP forbids `unsafe-eval` in shipped responses | `AC1.10.4 configures browser security headers without unsafe eval` / `npm run audit:prod` | `src/__tests__/api-urls.test.ts`, `.github/workflows/ci.yml` | <!-- epic-owned: horizontal -->

---

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

- [schema.md](../../common/meta/schema.md) - Database structure
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
- [../ssot/frontend-patterns.md](../../apps/frontend/frontend-patterns.md) — frontend integration, API-client, and browser-auth/session patterns.

---

## 📅 Timeline

- **Start**: 2026-01-06
- **Completion**: 2026-01-09
- **Actual Hours**: ~12 hours
