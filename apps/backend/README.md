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

## Tests (with DB auto-cleanup)

Use the workspace script to start Postgres via compose and clean up when tests finish:

```bash
moon run backend:test
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/ping` | Get current ping/pong state |
| POST | `/ping/toggle` | Toggle between ping and pong |
| POST | `/statements/upload` | Upload and parse statement |
| GET | `/statements/{id}` | Statement details |
| GET | `/statements/pending-review` | Statements pending review |
| POST | `/statements/{id}/approve` | Approve/reject statement |
| POST | `/api/reconciliation/run` | Run reconciliation matching |
| GET | `/api/reconciliation/pending` | Pending review queue |
| GET | `/api/reconciliation/stats` | Reconciliation stats |
| GET | `/api/reconciliation/unmatched` | Unmatched transactions |

## Environment Variables

See [.env.example](../../.env.example) for the complete list of environment variables and their documentation.

To start local development:
```bash
cp ../../.env.example .env
# Edit .env and fill in required values (see comments in file)
```
