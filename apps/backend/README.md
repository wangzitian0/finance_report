# Finance Report Backend

FastAPI backend for Finance Report.

## Local Commands

```bash
uv sync
uv run uvicorn src.main:app --reload
moon run :dev -- --backend
moon run :test
```

## SSOT Links

| Need | Source |
|---|---|
| API endpoints and schemas | [Generated API reference](../../docs/reference/api.md), `/api/docs` |
| Development workflow | [development.md](../../docs/ssot/development.md) |
| Environment contract | [environments.md](../../docs/ssot/environments.md), [.env.example](../../.env.example) |
| Database model | [schema.md](../../docs/ssot/schema.md), [Generated DB schema reference](../../docs/reference/db-schema.md) |
| Test policy | [tdd.md](../../docs/ssot/tdd.md), [coverage.md](../../docs/ssot/coverage.md) |

## Router notes

- `users` (the `identity` package — `src/identity/extension/api/users.py`) is
  intentionally self-scoped; a multi-user admin panel is **deliberately deferred**
  (no multi-tenant need). See #1010 / EPIC-022 AC22.15. Only `/users/me/settings`
  is consumed (the AI Settings editor).
- `GET /auth/me` backs the frontend session bootstrap (`hooks/useSessionBootstrap.ts`).
