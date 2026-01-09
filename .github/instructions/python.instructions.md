---
applyTo: "**/*.py"
---

# Python/FastAPI Development Instructions

## Language & Framework
- Python 3.12+
- FastAPI with async patterns
- SQLAlchemy 2 with asyncpg
- Pydantic v2 for validation

## Code Style

### Type Hints
Always use type hints for function parameters and return values:
```python
async def get_account(account_id: UUID, db: AsyncSession) -> Account | None:
    ...
```

### Monetary Values
**CRITICAL**: Never use float for money. Always use Decimal:
```python
from decimal import Decimal

# ✅ Correct
amount = Decimal("100.50")
total = amount + Decimal("50.25")

# ❌ Wrong - precision issues
amount = 100.50
```

### Date/Time Handling
```python
from datetime import datetime, timezone

# Use UTC for all internal timestamps
now = datetime.now(timezone.utc)

# ISO 8601 for API responses
date_str = now.isoformat()
```

### Error Handling
Use HTTPException with appropriate status codes:
```python
from fastapi import HTTPException, status

if not account:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Account {account_id} not found"
    )
```

### Dependency Injection
Use FastAPI's Depends for database sessions and auth:
```python
async def create_entry(
    entry: JournalEntryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_active_user),
) -> JournalEntry:
    ...
```

## SQLAlchemy Patterns

### Async Queries
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

async def get_accounts(db: AsyncSession, user_id: UUID) -> list[Account]:
    result = await db.execute(
        select(Account).where(Account.user_id == user_id)
    )
    return list(result.scalars().all())
```

### Transactions
```python
async with db.begin():
    db.add(journal_entry)
    for line in lines:
        db.add(line)
    # Commit happens automatically
```

## Pydantic Schemas

### Request/Response Models
```python
from pydantic import BaseModel, Field
from decimal import Decimal

class JournalLineCreate(BaseModel):
    account_id: UUID
    direction: Literal["DEBIT", "CREDIT"]
    amount: Decimal = Field(gt=0, decimal_places=2)
    currency: str = Field(min_length=3, max_length=3)
```

## Testing
- Use pytest with pytest-asyncio
- Test database isolation with transactions
- Always verify journal balance after operations
