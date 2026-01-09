# EPIC-002 Architectural Decisions

## Overview

This document records key architectural and design decisions made during EPIC-002 implementation.

## 1. Journal Entry Structure

### Decision: JournalEntry + JournalLine Pattern

**Chosen**: Header-Line pattern (one JournalEntry → many JournalLines)

**Alternatives Considered**:
- Single flat table with debit_account, credit_account, amount
- Separate Debit and Credit tables

**Rationale**:
- Supports complex transactions (split entries, multi-leg transactions)
- Standard accounting pattern used in professional systems
- Allows flexible n:m relationships (e.g., salary with multiple deductions)
- Better for audit trail and reporting

**Implementation**:
```python
JournalEntry:
  - id, user_id, entry_date, memo, status
  
JournalLine:
  - id, journal_entry_id, account_id, direction, amount
```

## 2. Monetary Precision

### Decision: Decimal Type with (18,2) Precision

**Chosen**: PostgreSQL DECIMAL(18,2) + Python Decimal

**Alternatives Considered**:
- float (REJECTED - precision loss)
- INTEGER with cents (too rigid)
- NUMERIC without precision limit

**Rationale**:
- Eliminates floating-point precision errors
- Standard for financial systems
- 18 digits supports up to 999,999,999,999,999.99
- 2 decimal places sufficient for most currencies

**Code Example**:
```python
from decimal import Decimal
amount = Decimal("100.50")  # ✅ Correct
amount = 100.50             # ❌ Wrong
```

## 3. Entry Status Flow

### Decision: draft → posted → (optional) void

**Chosen**: Immutable after posting, void creates reversal

**Alternatives Considered**:
- Allow direct editing of posted entries (REJECTED - audit risk)
- Soft delete with is_deleted flag (REJECTED - violates GAAP)

**Rationale**:
- GAAP compliant
- Maintains complete audit trail
- Prevents accidental data loss
- Reversal entries clearly show corrections

**Status Flow**:
```
draft → posted → reconciled
        ↓
       void (linked to reversal entry)
```

## 4. Balance Calculation Strategy

### Decision: On-demand calculation from journal lines

**Chosen**: Calculate balance by summing journal lines at query time

**Alternatives Considered**:
- Maintain balance field on Account (eventual consistency risk)
- Separate AccountBalance table (complexity)

**Rationale**:
- Source of truth is journal lines
- No risk of balance drift
- Simpler concurrency handling
- Can rebuild balances from audit trail

**Performance Consideration**:
- Cache for frequently accessed accounts (future optimization)
- Indexed queries on journal_entry_id, account_id, status

## 5. Multi-Currency Approach

### Decision: Currency on JournalLine + fx_rate field

**Chosen**: Each line stores original currency and optional FX rate

**Alternatives Considered**:
- Single base currency only (too restrictive)
- Automatic conversion at entry time (loses original data)

**Rationale**:
- Preserves original transaction currency
- Allows retrospective recalculation with different rates
- Supports multi-currency reporting
- Flexible for future FX rate sources

**Example**:
```python
JournalLine:
  amount: Decimal("100.00")
  currency: "USD"
  fx_rate: Decimal("1.35")  # 1 USD = 1.35 SGD
```

## 6. Account Type Classification

### Decision: Five-type GAAP standard

**Chosen**: ASSET, LIABILITY, EQUITY, INCOME, EXPENSE

**Alternatives Considered**:
- Flexible user-defined types (too complex)
- Simplified 3-type (insufficient for reporting)

**Rationale**:
- Standard accounting classification
- Supports proper financial statement generation
- Clear debit/credit rules
- Internationally recognized

**Balance Rules**:
| Type | Debit | Credit | Normal Balance |
|------|-------|--------|----------------|
| ASSET | + | - | Debit |
| LIABILITY | - | + | Credit |
| EQUITY | - | + | Credit |
| INCOME | - | + | Credit |
| EXPENSE | + | - | Debit |

## 7. Validation Timing

### Decision: Validate at multiple layers

**Chosen**: Pydantic schema validation + service layer validation

**Layers**:
1. **Pydantic Schema** - Input validation
2. **Service Layer** - Business rules
3. **Database** - Constraints

**Rationale**:
- Defense in depth
- Fast fail at API boundary
- Business logic encapsulated in service
- Database as final safeguard

**Example**:
```python
# Layer 1: Pydantic
class JournalEntryCreate(BaseModel):
    lines: Annotated[list[JournalLineCreate], Field(min_length=2)]
    
    @model_validator
    def validate_balanced(self):
        # Check debit = credit

# Layer 2: Service
async def post_journal_entry():
    validate_journal_balance(entry.lines)
    # Check accounts active

# Layer 3: Database
CHECK constraint: amount > 0
```

## 8. Error Handling Strategy

### Decision: HTTPException with specific status codes

**Chosen**: FastAPI HTTPException with semantic HTTP codes

**Status Codes Used**:
- 400 Bad Request - Validation errors
- 404 Not Found - Resource missing
- 422 Unprocessable Entity - Business logic errors

**Rationale**:
- Standard HTTP semantics
- Client can distinguish error types
- FastAPI automatic documentation
- Consistent error format

## 9. Testing Strategy

### Decision: Unit tests for core logic, integration tests deferred

**Phase 1 (Completed)**:
- Unit tests for validation logic
- Decimal precision tests
- Balance calculation tests

**Phase 2 (Future)**:
- Database integration tests
- Full API endpoint tests
- Concurrency tests

**Rationale**:
- Validate core accounting logic first
- Integration tests require more setup
- Focus on critical path (balance validation)

## 10. Authentication Approach

### Decision: Mock user_id for Phase 1, real auth in Phase 2

**Current**: `MOCK_USER_ID = UUID("00000000-0000-0000-0000-000000000001")`

**Future**: FastAPI Users or similar

**Rationale**:
- Unblock implementation
- Easy to replace later
- All endpoints already filter by user_id
- Security boundaries in place

## Trade-offs & Limitations

### Current Limitations

1. **No Alembic migrations yet** - Using SQLAlchemy metadata.create_all()
   - **Impact**: Manual schema management
   - **Mitigation**: Add Alembic in next phase

2. **No pagination on balance calculation** - Could be slow with many entries
   - **Impact**: Performance on accounts with thousands of entries
   - **Mitigation**: Add date range filters, caching

3. **Mock user authentication** - Single user mode
   - **Impact**: Not production-ready
   - **Mitigation**: Replace with FastAPI Users

4. **No soft delete** - Deleted accounts cascade delete
   - **Impact**: Data loss risk
   - **Mitigation**: Add is_deleted flag + constraints

### Deliberate Trade-offs

1. **Simplicity over optimization** - On-demand balance calculation
   - Chosen: Correctness and simplicity
   - Deferred: Balance caching

2. **GAAP compliance over flexibility** - Immutable posted entries
   - Chosen: Audit trail integrity
   - Trade-off: Cannot edit mistakes (must void)

3. **Type safety over convenience** - Strict Pydantic validation
   - Chosen: Runtime type checking
   - Trade-off: More verbose schemas

## References

- GAAP Standards: https://www.fasb.org/
- Double-Entry Bookkeeping: Wikipedia
- SQLAlchemy Best Practices: docs.sqlalchemy.org
- FastAPI Patterns: fastapi.tiangolo.com

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-10 | 1.0 | Initial documentation |
