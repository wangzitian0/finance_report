# Finance Report

<div align="center">

### 📚 **[View Full Documentation →](https://wangzitian0.github.io/finance_report/)**

*Complete user guides, API reference, and technical documentation*

---

[![Documentation](https://img.shields.io/badge/docs-wangzitian0.github.io%2Ffinance__report-blue.svg?logo=readthedocs)](https://wangzitian0.github.io/finance_report/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109.0-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14-black.svg?logo=next.js)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-316192.svg?logo=postgresql)](https://www.postgresql.org/)
[![Coverage Status](https://coveralls.io/repos/github/wangzitian0/finance_report/badge.svg?branch=main)](https://coveralls.io/github/wangzitian0/finance_report?branch=main)
[![Powered by Gemini](https://img.shields.io/badge/AI-Gemini%203%20Flash%20Preview-4285F4.svg?logo=google)](https://ai.google.dev/)

</div>

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

# Backend (Terminal 1)
moon run backend:dev

# Frontend (Terminal 2)
moon run frontend:dev
```

Open [http://localhost:3000](http://localhost:3000)

Optional: run dependencies manually (e.g., MinIO for statement uploads):

```bash
docker compose up -d postgres minio
```

## 🛠️ Development

This project uses [Moonrepo](https://moonrepo.dev/) for task orchestration:

```bash
# Development
moon run backend:dev        # Start backend
moon run frontend:dev       # Start frontend

# Local CI / Verification (Recommended)
moon run :ci                # One-button check (Lint + Format + Test + Check)
                             # Matches GitHub CI exactly.

# Testing
moon run :test              # All tests
moon run backend:test       # Run tests (auto-manages DB)
moon run backend:env-check  # Smoke test environment variables

# Code Quality
moon run :lint              # Lint all
moon run backend:format     # Format Python (auto-fix)

# Build
moon run :build             # Build all
```
Backend tests enforce **>= 97%** line coverage with branch coverage; see `docs/ssot/tdd.md` for TDD workflow and `docs/ssot/development.md` for details.
For isolated local test DBs, set `BRANCH_NAME=<branch_name>` (and optionally `WORKSPACE_ID=<id>`) before running `backend:test`.
See [development.md](docs/ssot/development.md) for detailed workflows.

## API Auth (MVP)

User-scoped endpoints require an `X-User-Id` header (UUID). See
[authentication.md](docs/ssot/authentication.md) for details.

## 📚 Documentation

| Resource | Description |
|----------|-------------|
| [📖 **Documentation Site**](https://wangzitian0.github.io/finance_report/) | **Complete documentation** — User guides, API reference, and technical docs |
| [target.md](./target.md) | Project target and decision criteria |
| [docs/ssot/](./docs/ssot/) | Technical SSOT (Single Source of Truth) |
| [AGENTS.md](./AGENTS.md) | AI agent guidelines |

> 💡 **Documentation is automatically deployed** to [wangzitian0.github.io/finance_report](https://wangzitian0.github.io/finance_report/) via GitHub Pages on every push to `main`.

### Build Documentation Locally

The project uses [MkDocs](https://www.mkdocs.org/) with Material theme for documentation:

```bash
# Install dependencies
pip install -r docs/requirements.txt

# Serve docs locally with live reload (http://127.0.0.1:8000)
mkdocs serve

# Build static site (output: site/)
mkdocs build
```

The generated documentation is output to the `site/` directory.

## 🏗️ Architecture

```
apps/
├── backend/     # FastAPI + SQLAlchemy + PostgreSQL
└── frontend/    # Next.js 14 + TypeScript
```

## 📄 License

MIT
