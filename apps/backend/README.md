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

Create `.env` file:
```bash
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/finance_report
DEBUG=true
BASE_CURRENCY=SGD
OPENROUTER_API_KEY=your_openrouter_api_key_here
PRIMARY_MODEL=google/gemini-3-flash
FALLBACK_MODELS=google/gemini-2.0-flash-exp:free,google/gemini-2.0-flash-thinking-exp:free
OPENROUTER_DAILY_LIMIT_USD=2
S3_ENDPOINT=http://localhost:9000
S3_ACCESS_KEY=minio
S3_SECRET_KEY=minio123
S3_BUCKET=statements
S3_REGION=us-east-1
S3_PRESIGN_EXPIRY_SECONDS=900
```
