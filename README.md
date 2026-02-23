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

# Start development
moon run :dev              # Starts infra, shows instructions for backend/frontend
moon run :dev -- --backend # Backend only
moon run :dev -- --frontend # Frontend only
```

Open [http://localhost:3000](http://localhost:3000)

## 🛠️ Development

This project uses [Moonrepo](https://moonrepo.dev/) with **6 unified commands**:

```bash
# Setup
moon run :setup            # Install all dependencies

# Development
moon run :dev              # Start dev environment
moon run :dev -- --backend # Backend only
moon run :dev -- --frontend # Frontend only

# Testing
moon run :test             # Full tests with coverage
moon run :test -- --fast   # Fast mode (no coverage, TDD)
moon run :test -- --smart  # Smart mode (coverage on changed files)
moon run :test -- --e2e    # E2E tests

# Code Quality
moon run :lint             # Check all
moon run :lint -- --fix    # Check + auto-fix

# Build
moon run :build            # Build frontend

# Cleanup
moon run :clean            # Clean resources
```

Backend tests enforce **>= 92%** line coverage. See [TDD workflow](docs/ssot/tdd.md) for testing patterns.

**Multi-Repo Isolation**: Run tests in parallel across multiple repo copies:

```bash
BRANCH_NAME=feature-auth moon run :test           # Explicit namespace
BRANCH_NAME=feature-auth WORKSPACE_ID=alice moon run :test  # Per-developer
moon run :test                                     # Auto-detect from git
```

See [development.md](docs/ssot/development.md) for detailed workflows.

## API Auth (MVP)

User-scoped endpoints require an `X-User-Id` header (UUID). See
[authentication.md](docs/ssot/authentication.md) for details.

## 📚 Documentation

| Resource | Description |
|----------|-------------|
| [📖 **Documentation Site**](https://wangzitian0.github.io/finance_report/) | **Complete documentation** — User guides, API reference, and technical docs |
| [vision.md](./vision.md) | Project vision and decision criteria |
| [docs/ssot/](./docs/ssot/) | Technical SSOT (Single Source of Truth) |
| [AGENTS.md](./AGENTS.md) | AI agent guidelines |

> 💡 **Documentation is automatically deployed** to [wangzitian0.github.io/finance_report](https://wangzitian0.github.io/finance_report/) via GitHub Pages on every push to `main`.

### Build Documentation Locally

```bash
pip install -r docs/requirements.txt
mkdocs serve   # http://127.0.0.1:8000
mkdocs build   # output: site/
```

## 🏗️ Architecture

```
apps/
├── backend/     # FastAPI + SQLAlchemy + PostgreSQL
└── frontend/    # Next.js 14 + TypeScript
```

## 📄 License

MIT
