# Finance Report - Personal Financial Management System

> **Double-Entry Bookkeeping + Smart Reconciliation** - Make personal finance as accurate as a bank

## 🎯 Project Goals

Build a professional-grade personal/family asset and liability management system with a rigorous accounting model at its core, augmented by AI for document extraction and interpretation.

### Core Capabilities

- ✅ **Smart Statement Import** - PDF/CSV/XLSX bank and brokerage statement parsing (Gemini Vision)
- ✅ **Double-Entry System** - General ledger based on accounting equation
- ✅ **Bank Reconciliation Engine** - Multi-dimensional matching algorithm + 0.1 USD precision
- ✅ **Financial Report Generation** - Balance sheet, income statement, cash flow statement
- ✅ **AI Financial Advisor** - Gemini 3 Flash report interpretation and trend analysis
- ✅ **Multi-Source Market Data** - yfinance + Twelve Data (FX rates/stock prices on schedule)
- ✅ **Self-Hosted** - Dokploy deployment, full data sovereignty

## 🛠️ Tech Stack

| Layer | Technology |
|-------|------------|
| **Monorepo** | Moonrepo |
| **Backend** | FastAPI + SQLAlchemy 2 + PostgreSQL 15 |
| **Auth** | FastAPI Users |
| **Frontend** | Next.js 14 + shadcn/ui + TailwindCSS |
| **AI** | Gemini 3 Flash (Vision + Text) |
| **Market Data** | yfinance + Twelve Data |
| **Deployment** | Dokploy + Docker |

## 📁 Directory Structure

```
finance_report/
├── .claude/skills/     # AI Agent role definitions
├── .github/
│   ├── copilot-instructions.md  # GitHub Copilot config
│   └── instructions/   # File-pattern instructions
├── docs/
│   └── ssot/           # Data model SSOT documentation
├── apps/
│   ├── backend/        # FastAPI backend
│   └── frontend/       # Next.js frontend
├── packages/           # Shared packages
├── infra/              # Docker + deployment scripts
├── moon.yml            # Moonrepo configuration
├── AGENTS.md           # Development specification
└── README.md           # This file
```

## 🚀 Quick Start

```bash
# Install dependencies
moon setup

# Start local Docker environment (Postgres + Redis)
moon run infra:docker:up

# Start backend dev server
moon run backend:dev

# Start frontend dev server
moon run frontend:dev
```

## 📖 Documentation Index

| Document | Description |
|----------|-------------|
| [AGENTS.md](./AGENTS.md) | Development specifications and workflows |
| [init.md](./init.md) | Complete project proposal |
| [docs/ssot/](./docs/ssot/) | Data model SSOT |

## 🤖 AI Agent Collaboration

Project supports multi-agent collaboration, role definitions in `.claude/skills/`:

| Role | Responsibility |
|------|----------------|
| 📋 PM | Requirements analysis, task breakdown |
| 🏗️ Architect | System design, technical decisions |
| 💻 Developer | Code implementation |
| 📊 Accountant | Double-entry rules |
| 🔗 Reconciler | Matching algorithm tuning |
| 🧪 Tester | Quality assurance |

## 📅 Phased Delivery

| Phase | Duration | Content |
|-------|----------|---------|
| **0** | 1-2 weeks | Moonrepo + Docker environment |
| **1** | 2-3 weeks | Double-entry core + FastAPI Users |
| **2** | 3-4 weeks | Statement import + Gemini parsing |
| **3** | 3-4 weeks | Reconciliation engine + review queue |
| **4** | 2-3 weeks | Reports + AI interpretation |

## 📊 Key Metrics

| Metric | Target |
|--------|--------|
| Reconciliation precision | 0.1 USD |
| Statistics tolerance | 1% |
| Auto-match accuracy | ≥ 98% |
| API p95 latency | < 500ms |
| Backup frequency | Weekly |
