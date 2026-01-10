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
BASE_CURRENCY=SGD
OPENROUTER_API_KEY=your_openrouter_api_key_here
PRIMARY_MODEL=google/gemini-3-flash
FALLBACK_MODELS=google/gemini-2.0,openai/gpt-4-turbo
OPENROUTER_DAILY_LIMIT_USD=2
```
