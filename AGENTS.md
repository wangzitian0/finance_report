# Finance Report Development Specification

> Unauthorized modification of this document is prohibited.
> **AI Agent Development Guide** - Understand the project essence, make correct decisions.

## 📌 Current Status

**Phase 0**: Project initialization in progress

## 🎯 Ultimate Goal

**Double-entry accuracy + Smart reconciliation efficiency** → Trustworthy financial reports

Core Constraints:
- **Accounting Equation**: `Assets = Liabilities + Equity + (Income - Expenses)`
- **Reconciliation Precision**: 0.1 USD
- **Statistics Tolerance**: 1%

## 🧠 Design Philosophy

```
Bank Statement (PDF/CSV)
    ↓ Gemini Vision parsing
Structured Transactions (BankStatementTransaction)
    ↓ Balance verification (Opening + Net ≈ Closing)
Candidate Entries (JournalEntry draft)
    ↓ Multi-dimensional match scoring
Reconciliation Match (≥85 auto / 60-84 review / <60 unmatched)
    ↓ Manual confirmation
Posted Entries (JournalEntry posted)
    ↓ Report generation
Financial Reports + AI Interpretation
```

## 📁 Directory Structure

```
finance_report/
├── .claude/skills/     # AI Agent role definitions
│   ├── pm.md           # Product Manager
│   ├── architect.md    # System Architect
│   ├── developer.md    # Full-Stack Developer
│   ├── accountant.md   # Accounting Advisor
│   ├── reconciler.md   # Reconciliation Specialist
│   └── tester.md       # QA Engineer
├── .github/
│   ├── copilot-instructions.md  # Project-level Copilot config
│   └── instructions/   # File-pattern instructions
│       ├── python.instructions.md
│       └── frontend.instructions.md
├── docs/
│   └── ssot/           # Data model SSOT
│       ├── db.schema.md           # Database table structure
│       ├── domain.accounting.md   # Double-entry model
│       └── domain.reconciliation.md # Reconciliation engine model
├── apps/
│   ├── backend/        # FastAPI + SQLAlchemy
│   └── frontend/       # Next.js 14 + shadcn/ui
├── packages/           # Shared types, utilities
└── infra/              # Docker + deployment scripts
```

## 🔑 Core Concepts

### Data Models

| Model | Description |
|-------|-------------|
| `Account` | Chart of accounts (5 types: Asset/Liability/Equity/Income/Expense) |
| `JournalEntry` | Entry header (draft → posted → reconciled) |
| `JournalLine` | Entry line (debit/credit, amount, account) |
| `BankStatement` | Bank statement |
| `BankStatementTransaction` | Bank transaction |
| `ReconciliationMatch` | Reconciliation match record |

### Technology Stack

| Component | Choice | Reason |
|-----------|--------|--------|
| Auth | FastAPI Users | Out-of-box JWT/OAuth2 |
| ORM | SQLAlchemy 2 | Async support, mature |
| Database | PostgreSQL 15 | ACID transactions |
| Market Data | yfinance + Twelve Data | Dual source redundancy |
| AI | Gemini 3 Flash | Vision + Text |

## 📏 Coding Standards

### Monetary Handling
```python
from decimal import Decimal
amount = Decimal("100.50")  # ✅ Correct
# amount = 100.50  # ❌ Float precision issues
```

### Entry Balance Validation
```python
def validate_balance(lines: list[JournalLine]) -> bool:
    debit = sum(l.amount for l in lines if l.direction == "DEBIT")
    credit = sum(l.amount for l in lines if l.direction == "CREDIT")
    return abs(debit - credit) < Decimal("0.01")
```

### Precision Configuration
```python
RECONCILIATION_TOLERANCE = Decimal("0.10")  # 0.1 USD
STATISTICS_TOLERANCE = Decimal("0.01")      # 1%
```

## 🤖 Multi-Role Collaboration

### Team Structure

```
                    👤 User
                       │
            ┌──────────┼──────────┐
            │          │          │
       📋 PM     🏗️ Architect  🎨 Designer
            │          │          │
            └──────────┼──────────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
  💻 Developer   📊 Accountant   🔗 Reconciler
       │               │               │
       └───────┬───────┴───────┬───────┘
               │               │
          🧪 Tester       📈 (AI Advisor)
```

### Usage

```bash
# Start new feature
@.claude/skills/pm.md I want to support parsing CMB bank statements

# Design review
@.claude/skills/architect.md @.claude/skills/accountant.md Please review this entry design

# Reconciliation tuning
@.claude/skills/reconciler.md Match accuracy has dropped, please analyze the cause
```

## 🛠️ Development Workflow

### Common Commands
```bash
moon run backend:dev      # Start backend
moon run frontend:dev     # Start frontend
moon run backend:test     # Run tests
moon run backend:migrate  # Database migration
moon run infra:docker:up  # Start Docker environment
```

### Adding New Statement Types
1. Create parser in `services/extraction/`
2. Configure Gemini prompt
3. Add test cases
4. Update `SUPPORTED_STATEMENT_TYPES`

## 📚 Documentation Index

| Document | Content |
|----------|---------|
| `init.md` | Complete project proposal |
| `docs/ssot/db.schema.md` | Database table structure |
| `docs/ssot/domain.accounting.md` | Double-entry model |
| `docs/ssot/domain.reconciliation.md` | Reconciliation engine model |
| `.claude/skills/*.md` | Agent role definitions |

## ⚙️ Configuration Parameters

### Reconciliation Engine
```yaml
scoring:
  weights:
    amount: 0.40
    date: 0.25
    description: 0.20
    business: 0.10
    history: 0.05
  thresholds:
    auto_accept: 85
    pending_review: 60
  tolerances:
    amount_absolute: 0.10  # 0.1 USD
```

### Market Data
```yaml
market_data:
  sources:
    - yfinance    # Primary source
    - twelve_data # Backup source
  sync_schedule: "0 8 * * *"  # Daily at 08:00
  data_types:
    - fx_rates    # Exchange rates
    - stock_prices # Stock prices
```

### Backup Strategy
```yaml
backup:
  frequency: weekly     # Weekly
  retention_days: 90    # Keep 90 days
  target: s3://backup/finance-report/
```
