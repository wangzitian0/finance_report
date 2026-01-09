# GitHub Copilot Instructions for Finance Report

> Project-level instructions to enhance GitHub Copilot behavior for this repository.

## Project Overview

Finance Report is a personal financial management system built with:
- **Backend**: FastAPI + SQLAlchemy 2 + PostgreSQL 15
- **Frontend**: Next.js 14 + React + TypeScript + shadcn/ui
- **Authentication**: FastAPI Users
- **AI**: Gemini 3 Flash (document parsing + financial advisor)
- **Monorepo**: Moonrepo

## Core Domain Concepts

### Double-Entry Bookkeeping
All financial transactions follow the accounting equation:
```
Assets = Liabilities + Equity + (Income - Expenses)
```

Key models:
- `JournalEntry`: Transaction header (date, memo, status)
- `JournalLine`: Individual debit/credit entries (must balance)
- `Account`: Chart of accounts (5 types: Asset, Liability, Equity, Income, Expense)

### Bank Reconciliation
Matching bank statements to journal entries with confidence scoring:
- **≥85**: Auto-accept
- **60-84**: Review queue
- **<60**: Unmatched

## Coding Standards

### Python (FastAPI Backend)
- Use `Decimal` for all monetary amounts (never `float`)
- Use `datetime.now(timezone.utc)` for timestamps
- Pydantic v2 for request/response validation
- Async SQLAlchemy 2 patterns
- Type hints required for all functions

```python
# ✅ Correct
from decimal import Decimal
amount = Decimal("100.50")

# ❌ Wrong
amount = 100.50  # Float precision issues
```

### TypeScript (Next.js Frontend)
- Strict TypeScript (no `any` types)
- React Server Components by default
- Client components only when necessary (`'use client'`)
- TanStack Query for data fetching
- Zustand for client state

### SQL (PostgreSQL)
- Use `DECIMAL(18,2)` for monetary columns
- UUID primary keys
- Always include `created_at`, `updated_at` audit fields
- Foreign key constraints required

## File Patterns

### Backend
- `apps/backend/src/models/*.py` - SQLAlchemy models
- `apps/backend/src/schemas/*.py` - Pydantic schemas
- `apps/backend/src/routers/*.py` - API endpoints
- `apps/backend/src/services/*.py` - Business logic

### Frontend
- `apps/frontend/app/**/page.tsx` - Page components
- `apps/frontend/components/*.tsx` - Reusable components
- `apps/frontend/lib/*.ts` - Utilities and API clients

## Testing Requirements

- Journal entries must always balance (debit = credit)
- Accounting equation must hold at all times
- Reconciliation tolerance: 0.1 USD
- Statistics tolerance: 1%

## Documentation

- All code documentation in English
- Use JSDoc/docstrings for public APIs
- Update AGENTS.md for significant changes
