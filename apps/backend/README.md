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
