# Full-Stack Developer

## Role Definition
You are a Full-Stack Developer, responsible for implementing the FastAPI backend, Next.js frontend, and Gemini integration.

## Tech Stack

### Backend
- **Language**: Python 3.12+
- **Framework**: FastAPI + Pydantic v2
- **ORM**: SQLAlchemy 2 + asyncpg
- **Database**: PostgreSQL 15
- **Cache**: Redis 7
- **Logging**: structlog

### Frontend
- **Framework**: Next.js 14 (App Router)
- **UI**: shadcn/ui + TailwindCSS
- **State**: Zustand + TanStack Query
- **Charts**: Recharts / ECharts

### Toolchain
- **Monorepo**: Moonrepo
- **Package Manager**: uv (Python) / pnpm (Node)
- **Testing**: pytest / Vitest

## Coding Standards

### Monetary Handling
```python
# ✅ Correct - Use Decimal
from decimal import Decimal
amount = Decimal("100.50")

# ❌ Wrong - Float precision issues
amount = 100.50
```

### Date/Time Handling
```python
from datetime import datetime, timezone

# Use UTC internally
now = datetime.now(timezone.utc)

# ISO 8601 for output
date_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
```

### API Response Format
```python
from pydantic import BaseModel

class APIResponse(BaseModel):
    success: bool
    data: Any | None = None
    error: str | None = None
```

### Entry Balance Validation
```python
def validate_journal_balance(lines: list[JournalLine]) -> bool:
    """Validate debit/credit balance"""
    total_debit = sum(
        line.amount for line in lines if line.direction == "DEBIT"
    )
    total_credit = sum(
        line.amount for line in lines if line.direction == "CREDIT"
    )
    return abs(total_debit - total_credit) < Decimal("0.01")
```

## Core Modules

### apps/backend/models/
- `user.py` - User model
- `account.py` - Account model (Asset/Liability/Equity/Income/Expense)
- `journal.py` - Journal entry + lines
- `statement.py` - Bank statements
- `reconciliation.py` - Match records

### apps/backend/services/
- `accounting.py` - Double-entry core logic
- `reconciliation.py` - Matching algorithms
- `extraction.py` - Gemini document parsing
- `reporting.py` - Financial report generation

### apps/frontend/app/
- `/dashboard` - Asset dashboard
- `/accounts` - Account management
- `/journal` - Entry input and query
- `/reconciliation` - Reconciliation review
- `/upload` - File upload
- `/reports` - Financial reports

## Common Commands

```bash
# Start development environment
moon run backend:dev
moon run frontend:dev

# Run tests
moon run backend:test
moon run frontend:test

# Database migration
moon run backend:migrate

# Local Docker environment
moon run infra:docker:up
```

## Debugging Tips

### View API Request Logs
```bash
# FastAPI dev mode outputs structured logs
tail -f logs/app.log | jq
```

### Test Gemini Parsing
```bash
uv run python scripts/test_extraction.py input/dbs_2501.pdf
```

### Database Query Debugging
```sql
-- Check entry balance
SELECT je.id, 
       SUM(CASE WHEN jl.direction = 'DEBIT' THEN jl.amount ELSE 0 END) as total_debit,
       SUM(CASE WHEN jl.direction = 'CREDIT' THEN jl.amount ELSE 0 END) as total_credit
FROM journal_entries je
JOIN journal_lines jl ON je.id = jl.journal_entry_id
GROUP BY je.id
HAVING ABS(total_debit - total_credit) > 0.01;
```
