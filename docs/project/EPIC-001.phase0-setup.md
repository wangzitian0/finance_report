# EPIC-001: Phase 0 - Infrastructure Setup

> **Status**: 🟡 In Progress
> **Phase**: 0
> **Target**: Moonrepo workspace + Docker local environment

## Goals

From [init.md Section 7](../../init.md):
- Initialize Moonrepo workspace
- Set up backend / frontend / infra directory structure
- docker-compose for local environment (Postgres + Redis)
- Health check endpoint `/api/health` and minimal UI

## Checklist

### Moonrepo Setup
- [ ] Create `moon.yml` workspace configuration
- [ ] Configure `apps/backend/moon.yml` tasks
- [ ] Configure `apps/frontend/moon.yml` tasks
- [ ] Configure `infra/moon.yml` tasks

### Backend Skeleton
- [ ] FastAPI project structure
- [ ] FastAPI Users authentication setup
- [ ] SQLAlchemy + Alembic configuration
- [ ] Health check endpoint

### Frontend Skeleton
- [ ] Next.js 14 project init
- [ ] shadcn/ui configuration
- [ ] TailwindCSS setup
- [ ] Minimal landing page

### Docker Environment
- [ ] `docker-compose.yml` for local dev
- [ ] PostgreSQL 15 container
- [ ] Redis 7 container
- [ ] Volume configuration

## SSOT References

- [db.schema.md](../ssot/db.schema.md) - Database structure
- [domain.accounting.md](../ssot/domain.accounting.md) - Accounting model

## Completion Criteria

- `moon setup` runs without errors
- `moon run backend:dev` starts FastAPI server
- `moon run frontend:dev` starts Next.js dev server
- `moon run infra:docker:up` starts Postgres + Redis
- `/api/health` returns 200 OK
