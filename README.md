# Finance Report

Personal financial management system with double-entry bookkeeping.

## Quick Start

```bash
# 1. Start database
docker compose up -d

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

## Project Structure

```
finance_report/
├── .moon/              # Moonrepo config
├── apps/
│   ├── backend/        # FastAPI + SQLAlchemy
│   └── frontend/       # Next.js 14
├── docs/
│   ├── ssot/           # Single Source of Truth
│   └── project/        # EPIC tracking
├── docker-compose.yml  # Local dev database
└── AGENTS.md           # AI agent guidelines
```

## Commands

| Command | Description |
|---------|-------------|
| `docker compose up -d` | Start Postgres + Redis |
| `moon run backend:dev` | Start backend |
| `moon run frontend:dev` | Start frontend |
| `moon run backend:test` | Run backend tests |
| `moon run frontend:build` | Build frontend |

## Documentation

- [AGENTS.md](./AGENTS.md) - Development guidelines
- [init.md](./init.md) - Project specification
- [docs/ssot/](./docs/ssot/) - Technical truth
