# Finance Report Backend

FastAPI backend for the Finance Report personal financial management system.

## Quick Start

```bash
# Install dependencies
uv sync

# Start dev server
uv run uvicorn src.main:app --reload

# Or via moon
moon run backend:dev
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/ping` | Get current ping/pong state |
| POST | `/ping/toggle` | Toggle between ping and pong |

## Environment Variables

Create `.env` file:
```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report
DEBUG=true
```
