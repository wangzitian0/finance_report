# Finance Report

[![Documentation](https://img.shields.io/badge/docs-docs.report.zitian.party-blue.svg?logo=readthedocs)](https://docs.report.zitian.party)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-black.svg?logo=next.js)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-316192.svg?logo=postgresql)](https://www.postgresql.org/)
[![Coverage Status](https://coveralls.io/repos/github/wangzitian0/finance_report/badge.svg?branch=main)](https://coveralls.io/github/wangzitian0/finance_report?branch=main)
[![Powered by Gemini](https://img.shields.io/badge/AI-Gemini%202.0%20Flash-4285F4.svg?logo=google)](https://ai.google.dev/)

> **📖 Full Documentation**: [docs.report.zitian.party](https://docs.report.zitian.party)

Personal financial management system featuring **double-entry bookkeeping**, **AI-powered statement parsing**, and **intelligent bank reconciliation**.

## ✨ Features

- **Double-Entry Bookkeeping** — Proper accounting with enforced balance validation
- **AI Statement Parsing** — Upload bank PDFs, auto-extract transactions via Gemini
- **Smart Reconciliation** — Fuzzy matching engine with 85%+ auto-accept accuracy
- **Financial Reports** — Balance sheet, income statement, trend analysis
- **Multi-Currency** — SGD base with FX rate support

## 🚀 Quick Start

```bash
# Clone and setup
git clone https://github.com/wangzitian0/finance_report.git
cd finance_report

# Start database
podman compose -f docker-compose.ci.yml up -d postgres

# Backend (Terminal 1)
cd apps/backend && uv sync && uv run uvicorn src.main:app --reload

# Frontend (Terminal 2, from project root)
cd apps/frontend && npm install && npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## 🛠️ Development

This project uses [Moonrepo](https://moonrepo.dev/) for task orchestration:

```bash
moon run backend:dev        # Start backend
moon run frontend:dev       # Start frontend
moon run backend:test       # Run tests (auto-manages DB)
moon run :lint              # Lint all
```
See [development.md](docs/ssot/development.md) for detailed workflows.

## 📚 Documentation

| Resource | Description |
|----------|-------------|
| [📖 Docs Site](https://docs.report.zitian.party) | User guide & API reference |
| [AGENTS.md](./AGENTS.md) | AI agent guidelines |
| [docs/ssot/](./docs/ssot/) | Technical SSOT |

## 🏗️ Architecture

```
apps/
├── backend/     # FastAPI + SQLAlchemy + PostgreSQL
└── frontend/    # Next.js 14 + TypeScript
```

## 📄 License

MIT
