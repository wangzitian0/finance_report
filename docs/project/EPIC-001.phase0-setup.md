# EPIC-001: Infrastructure & Authentication

> **Status**: 🟢 Complete  
> **Phase**: 0  
> **Duration**: 2 weeks  
> **Dependencies**: None  

---

## 🎯 Objective

Set up a runnable Monorepo development environment, complete user authentication and basic project skeleton.

**From [init.md Section 7](../../init.md) - Phase 0**

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
- [ ] Configure `infra/moon.yml` tasks (deferred)

### Backend Skeleton
- [x] FastAPI project structure (`apps/backend/src/`)
- [x] FastAPI Users authentication integration (registration/login/JWT)
- [x] SQLAlchemy 2 + Alembic configuration
- [x] Health check endpoint `/api/health`
- [x] structlog structured logging
- [ ] pre-commit hooks (black, ruff) → Technical debt

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

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Status |
|------|----------|------|
| `docker compose up -d` successfully starts database | Manual verification | ✅ |
| `moon run backend:dev` starts FastAPI | Console without errors | ✅ |
| `moon run frontend:dev` starts Next.js | Access localhost:3000 | ✅ |
| `/api/health` returns 200 OK | curl test | ✅ |
| Frontend-backend ping-pong communication | Page displays "pong" | ✅ |
| User registration/login API available | Postman test | ✅ |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| GitHub Actions CI configuration | Automatic PR checks | ⏳ |
| pre-commit hooks configuration | Auto-formatting on commit | ⏳ |
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
| infra/moon.yml | P3 | Deployment phase |

---

## Issues & Gaps

- [ ] Status is marked "Complete" while the checklist still has deferred items (infra/moon.yml, pre-commit hooks, Zustand), which makes Phase 0 exit criteria ambiguous.
- [ ] Phase 0 in `init.md` references `infra:docker:up`; without infra/moon.yml tasks, the Moon workflow is incomplete for local docker.

---

## ❓ Q&A (Clarification Required)

> This EPIC is complete. No pending questions.

---

## 📅 Timeline

- **Start**: 2026-01-06
- **Completion**: 2026-01-09
- **Actual Hours**: ~12 hours
