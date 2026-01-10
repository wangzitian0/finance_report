# Finance Report

[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-black.svg?logo=next.js)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-316192.svg?logo=postgresql)](https://www.postgresql.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.3-3178C6.svg?logo=typescript)](https://www.typescriptlang.org/)
[![Powered by Gemini](https://img.shields.io/badge/Powered%20by-Gemini%203%20Flash-4285F4.svg?logo=google)](https://ai.google.dev/)
[![Coffee](https://img.shields.io/badge/Powered%20by-Coffee%20☕-brown.svg)](https://www.buymeacoffee.com/)
[![Made in Singapore](https://img.shields.io/badge/Made%20in-🇸🇬%20Singapore-red.svg)](https://github.com/wangzitian0/finance_report)
[![Coverage Status](https://coveralls.io/repos/github/wangzitian0/finance_report/badge.svg?branch=main)](https://coveralls.io/github/wangzitian0/finance_report?branch=main)

Personal financial management system with double-entry bookkeeping.

## Quick Start

```bash
# 1. Start database (use podman on macOS, docker on Linux)
podman machine start  # macOS only
podman compose -f docker-compose.ci.yml up -d postgres

# Or with docker:
# docker compose -f docker-compose.ci.yml up -d postgres

# 2. Copy environment file
cp .env.example .env

# 3. Install backend deps & start
cd apps/backend
uv sync
uv run uvicorn src.main:app --reload

# 4. Install frontend deps & start (open new terminal)
# Note: Navigate from project root
cd ../../apps/frontend
npm install
npm run dev
```

Open http://localhost:3000 to see the ping-pong demo.

## API Documentation

Once the backend is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

### Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/accounts` | GET/POST | List/create accounts |
| `/api/accounts/{id}` | GET/PUT | Get/update account |
| `/api/journal-entries` | GET/POST | List/create entries |
| `/api/journal-entries/{id}/post` | POST | Post draft entry |
| `/api/journal-entries/{id}/void` | POST | Void posted entry |
| `/api/statements/upload` | POST | Upload and parse statement |
| `/api/statements/pending-review` | GET | List statements needing review |

## Reconciliation

Backend endpoints:

- `POST /api/reconciliation/run` - Run matching
- `GET /api/reconciliation/pending` - Review queue
- `POST /api/reconciliation/matches/{id}/accept` - Accept match
- `POST /api/reconciliation/matches/{id}/reject` - Reject match
- `POST /api/reconciliation/batch-accept` - Batch accept (≥ 80)
- `GET /api/reconciliation/stats` - Reconciliation stats
- `GET /api/reconciliation/unmatched` - Unmatched transactions

Frontend pages:

- `/reconciliation` - Reconciliation workbench
- `/reconciliation/unmatched` - Unmatched triage

## Project Structure

```
finance_report/
├── .moon/              # Moonrepo config
├── apps/
│   ├── backend/        # FastAPI + SQLAlchemy
│   │   ├── src/
│   │   │   ├── models/     # Account, JournalEntry, JournalLine
│   │   │   ├── schemas/    # Pydantic validation
│   │   │   ├── services/   # Accounting logic
│   │   │   └── routers/    # API endpoints
│   │   └── tests/      # 75%+ coverage
│   └── frontend/       # Next.js 14
├── docs/
│   ├── ssot/           # Single Source of Truth
│   └── project/        # EPIC tracking
├── docker-compose.ci.yml  # Local dev services
└── AGENTS.md           # AI agent guidelines
```

## Commands

| Command | Description |
|---------|-------------|
| `podman compose -f docker-compose.ci.yml up -d` | Start Postgres + Redis + MinIO |
| `moon run infra:docker:up` | Start local docker-compose services |
| `moon run backend:dev` | Start backend |
| `moon run frontend:dev` | Start frontend |
| `moon run backend:test` | Run backend tests |
| `moon run frontend:build` | Build frontend |

## Testing

```bash
cd apps/backend

# Run all tests
uv run pytest -v

# Run with coverage
uv run pytest --cov=src --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_accounting.py -v
```

**Current Coverage**: 76%+ (target: 75%)

## Documentation

- [AGENTS.md](./AGENTS.md) - Development guidelines
- [init.md](./init.md) - Project specification
- [docs/ssot/](./docs/ssot/) - Technical truth
- [docs/project/](./docs/project/) - EPIC tracking
