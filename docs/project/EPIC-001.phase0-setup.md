# EPIC-001: Infrastructure & Authentication

> **Status**: Complete
> **Vision Anchor**: `decision-7-tech-stack`

Monorepo environment, FastAPI authentication, SQLAlchemy + Alembic schema setup, Next.js frontend shell, and local container stack.

## Acceptance Criteria

All former `AC1.x.y` package-owned rows live in `common/{meta,runtime,identity,ledger,observability}/contract.py`. Only horizontal browser security remains here:

| ID | Requirement | Test Function | File |
|---|---|---|---|
| AC1.10.4 | Frontend production dependency audits fail CI and CSP forbids `unsafe-eval` in shipped responses | `AC1.10.4 configures browser security headers without unsafe eval` / `npm run audit:prod` | `src/__tests__/api-urls.test.ts`, `.github/workflows/ci.yml` | <!-- epic-owned: horizontal -->

## Owned Surfaces

- [Root README](https://github.com/wangzitian0/finance_report/blob/main/README.md) · [docs/index.md](../index.md) · [getting-started.md](../user-guide/getting-started.md)
- [apps/backend/README.md](https://github.com/wangzitian0/finance_report/blob/main/apps/backend/README.md) · [apps/frontend/README.md](https://github.com/wangzitian0/finance_report/blob/main/apps/frontend/README.md) · [api-overview.md](../reference/api-overview.md)
- [common/identity/readme.md](../../common/identity/readme.md) · [common/meta/schema.md](../../common/meta/schema.md) · [common/ledger/readme.md](../../common/ledger/readme.md) · [apps/frontend/frontend-patterns.md](../../apps/frontend/frontend-patterns.md)
