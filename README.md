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
moon run backend:dev        # Start backend
moon run frontend:dev       # Start frontend
moon run backend:test       # Run tests (auto-manages DB)
moon run backend:env-check  # Smoke test environment variables
moon run :lint              # Lint all
```
Backend tests enforce **>= 95%** line coverage; see `docs/ssot/development.md` for details.
For isolated local test DBs, set `BRANCH_NAME=<branch_name>` (and optionally `WORKSPACE_ID=<id>`) before running `backend:test`.
See [development.md](docs/ssot/development.md) for detailed workflows.

## API Auth (MVP)

User-scoped endpoints require an `X-User-Id` header (UUID). See
[authentication.md](docs/ssot/authentication.md) for details.

## 📚 Documentation System

This project uses a **4-category documentation system**. Each category serves a distinct purpose:

| # | Category | Location | Purpose | Audience |
|---|----------|----------|---------|----------|
| **0** | **Project Entry** | Root directory | Project intro, goals, AI guidelines | Everyone |
| **1** | **User Docs (Onboarding)** | `docs/user-guide/`, `docs/reference/` | Product usage, API reference | End Users |
| **2** | **Technical Truth (SSOT)** | `docs/ssot/` | Core concepts, constraints, design decisions | Developers |
| **3** | **Project Tracking** | `docs/project/` | EPIC progress, decisions | Team |

### Category 0: Project Entry (Root Directory)

| File | Purpose |
|------|---------|
| [README.md](./README.md) | Project overview, quick start, **documentation system definition** |
| [target.md](./target.md) | North Star goals, decision criteria, acceptance standards |
| [AGENTS.md](./AGENTS.md) | AI agent behavioral guidelines, red lines, coding standards |

### Category 1: User Documentation (Onboarding)

**Live Site**: [wangzitian0.github.io/finance_report](https://wangzitian0.github.io/finance_report/)

- [User Guide](./docs/user-guide/) — Getting started, accounts, journal entries, reconciliation
- [API Reference](./docs/reference/) — REST API documentation

### Category 2: Technical Truth (SSOT)

**Entry Point**: [docs/ssot/README.md](./docs/ssot/README.md)

Single Source of Truth for all technical and business concepts. Key documents:
- [development.md](./docs/ssot/development.md) — Environment setup, moon commands
- [schema.md](./docs/ssot/schema.md) — Database models, migrations
- [accounting.md](./docs/ssot/accounting.md) — Double-entry bookkeeping rules
- [reconciliation.md](./docs/ssot/reconciliation.md) — Matching algorithm, thresholds

### Category 3: Project Tracking

**Entry Point**: [docs/project/README.md](./docs/project/README.md)

EPIC-based project management. Each feature has two files:
- `EPIC-XXX.<name>.md` — Goals, acceptance criteria (human-authored)
- `EPIC-XXX.<name>-GENERATED.md` — Implementation details (AI-generated)

---

### Meta Rule: Directory READMEs

> **Every directory's `README.md` is the guide for that directory.**
> - **Before modifying**: Read the README first
> - **After modifying**: Keep README consistent with changes

---

> 💡 **Documentation is automatically deployed** to [wangzitian0.github.io/finance_report](https://wangzitian0.github.io/finance_report/) via GitHub Pages on every push to `main`.

## 🏗️ Architecture

```
apps/
├── backend/     # FastAPI + SQLAlchemy + PostgreSQL
└── frontend/    # Next.js 14 + TypeScript
```

## 📄 License

MIT
