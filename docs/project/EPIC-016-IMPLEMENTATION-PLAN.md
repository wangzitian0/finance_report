# EPIC-016 Implementation Plan: Two-Stage Review & Data Validation UI

> **Created**: 2026-02-25
> **Status**: 🟡 Planning Complete
> **Branch**: `epic-016/two-stage-review-ui`

---

## Executive Summary

This document provides a detailed implementation plan for EPIC-016 Two-Stage Review UI, based on codebase exploration and SSOT analysis.

### Design Decisions (Confirmed)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Q3: Duplicate Resolution | Choose canonical | Simpler UX, user picks one to keep |
| Q4: Transfer Pair Auto-link | Manual review first | Prevents incorrect auto-entries |
| Q5: First Statement Opening Balance | Manual entry | Most flexible, user knows actual balance |
| Tolerance | **0.001 USD** | Per user requirement (not 0.10 USD) |

---

## Architecture Overview

### Two-Stage Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Statement Import                               │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: Record-Level Review (New)                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐     │
│  │  PDF Viewer     │    │  Transaction    │    │  Balance        │     │
│  │  (Left Panel)   │◄──►│  List (Right)   │◄──►│  Validation     │     │
│  │                 │    │  (Editable)     │    │  (0.001 USD)    │     │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘     │
│                                                                          │
│  Actions: Approve | Reject | Edit & Approve                             │
│  Status: pending_review → approved | rejected                           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Stage 1 Approved)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: Run-Level Review (Enhanced)                                    │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐     │
│  │  Consistency    │    │  Reconciliation │    │  Batch          │     │
│  │  Checks         │    │  Match Queue    │    │  Operations     │     │
│  │  • Dedup        │    │  (Score 60-84)  │    │  • Approve      │     │
│  │  • Transfer     │    │                 │    │  • Reject       │     │
│  │  • Anomaly      │    │                 │    │  • Export CSV   │     │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘     │
│                                                                          │
│  Constraint: Batch approve blocked if unresolved consistency checks     │
│  Actions: Resolve Check | Batch Approve | Batch Reject                  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Stage 2 Approved)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Reconciliation Complete → Journal Entries Created                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Stage 1 (Record-Level Review)

### 1.1 Data Model Changes

#### New Enum: Stage1Status

```python
# apps/backend/src/models/statement.py

class Stage1Status(str, Enum):
    """Stage 1 review status for statements."""
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"  # User made edits before approving
```

#### Extend BankStatement Model

```python
# apps/backend/src/models/statement.py

class BankStatement(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    # ... existing fields ...
    
    # NEW: Stage 1 review fields
    stage1_status: Mapped[Stage1Status | None] = mapped_column(
        SQLEnum(Stage1Status, name="stage1_status_enum"),
        nullable=True,
        default=None,  # NULL for statements before EPIC-016
    )
    
    balance_validation_result: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        # Structure:
        # {
        #   "opening_match": bool,
        #   "closing_match": bool,
        #   "opening_delta": "0.000",
        #   "closing_delta": "0.000",
        #   "calculated_closing": "1234.56",
        #   "validated_at": "2026-02-25T10:00:00Z"
        # }
    )
    
    stage1_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Manual opening balance entry for first statement
    manual_opening_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
```

#### Alembic Migration

```bash
# Create migration
alembic revision -m "add_stage1_review_fields"
```

Migration content:
- Add `stage1_status` enum
- Add `balance_validation_result` JSONB column
- Add `stage1_reviewed_at` timestamp
- Add `manual_opening_balance` decimal

### 1.2 Backend Service: statement_validation.py

```python
# apps/backend/src/services/statement_validation.py

from decimal import Decimal
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import BankStatement, BankStatementTransaction, BankStatementStatus
from src.models.statement import Stage1Status

BALANCE_TOLERANCE = Decimal("0.001")  # Per user requirement

async def validate_balance_chain(
    db: AsyncSession,
    statement_id: UUID,
) -> dict:
    """
    Validate opening and closing balance chain.
    
    Logic:
    1. Opening balance = previous statement's closing balance OR manual entry
    2. Calculated closing = opening + sum(transactions)
    3. Compare with statement's closing_balance
    4. Tolerance: 0.001 USD
    """
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()
    if not statement:
        raise ValueError("Statement not found")
    
    # Get opening balance
    opening_balance = await _get_opening_balance(db, statement)
    
    # Calculate expected closing balance
    txn_sum = Decimal("0")
    for txn in statement.transactions:
        if txn.direction == "IN":
            txn_sum += txn.amount
        else:
            txn_sum -= txn.amount
    
    calculated_closing = opening_balance + txn_sum
    
    # Compare with stated closing balance
    closing_delta = abs((statement.closing_balance or Decimal("0")) - calculated_closing)
    
    validation_result = {
        "opening_balance": str(opening_balance),
        "closing_balance": str(statement.closing_balance),
        "calculated_closing": str(calculated_closing),
        "opening_delta": "0.000",  # Will be set by previous statement check
        "closing_delta": str(closing_delta),
        "opening_match": True,  # Will be set by previous statement check
        "closing_match": closing_delta <= BALANCE_TOLERANCE,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    return validation_result


async def approve_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> BankStatement:
    """Approve statement after validation passes."""
    # Validate balance
    result = await validate_balance_chain(db, statement_id)
    
    if not result["closing_match"]:
        raise ValueError(
            f"Balance mismatch: delta={result['closing_delta']} exceeds tolerance {BALANCE_TOLERANCE}"
        )
    
    # Update statement
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_status = Stage1Status.APPROVED
    statement.stage1_reviewed_at = datetime.now(timezone.utc)
    statement.balance_validation_result = result
    statement.status = BankStatementStatus.APPROVED
    
    await db.flush()
    return statement


async def reject_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    reason: str | None,
) -> BankStatement:
    """Reject statement - trigger re-parsing."""
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_status = Stage1Status.REJECTED
    statement.stage1_reviewed_at = datetime.now(timezone.utc)
    statement.status = BankStatementStatus.REJECTED
    if reason:
        statement.validation_error = reason
    
    await db.flush()
    return statement


async def edit_and_approve(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    edits: list[dict],  # [{txn_id, amount, description, ...}]
) -> BankStatement:
    """Edit transactions and approve if balance validates."""
    statement = await _get_statement_for_update(db, statement_id, user_id)
    
    # Apply edits
    for edit in edits:
        txn = next((t for t in statement.transactions if str(t.id) == edit.get("txn_id")), None)
        if txn:
            if "amount" in edit:
                txn.amount = Decimal(str(edit["amount"]))
            if "description" in edit:
                txn.description = edit["description"]
            if "txn_date" in edit:
                txn.txn_date = edit["txn_date"]
    
    # Validate and approve
    result = await validate_balance_chain(db, statement_id)
    
    if not result["closing_match"]:
        raise ValueError("Balance still invalid after edits")
    
    statement.stage1_status = Stage1Status.EDITED
    statement.stage1_reviewed_at = datetime.now(timezone.utc)
    statement.balance_validation_result = result
    statement.status = BankStatementStatus.APPROVED
    
    await db.flush()
    return statement
```

### 1.3 API Endpoints

```python
# apps/backend/src/routers/statements.py (extend existing)

@router.get("/{statement_id}/review")
async def get_statement_for_review(
    statement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> StatementReviewResponse:
    """
    Get statement with parsed data and validation results for Stage 1 review.
    
    Returns:
    - Statement metadata
    - Parsed transactions
    - Balance validation result
    - PDF URL (MinIO presigned URL)
    """
    ...

@router.post("/{statement_id}/approve")
async def approve_statement_stage1(
    statement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Approve statement (Stage 1). Validates balance chain first."""
    ...

@router.post("/{statement_id}/reject")
async def reject_statement_stage1(
    statement_id: UUID,
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Reject statement - trigger re-parsing."""
    ...

@router.post("/{statement_id}/edit")
async def edit_and_approve_statement(
    statement_id: UUID,
    body: EditTransactionsRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Edit transactions and approve if balance validates."""
    ...

@router.post("/{statement_id}/opening-balance")
async def set_opening_balance(
    statement_id: UUID,
    body: OpeningBalanceRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Set manual opening balance for first statement."""
    ...
```

### 1.4 Frontend: Stage 1 Review Page

**Route**: `/statements/[id]/review`

**Components**:
- `PdfViewer.tsx` - Left panel, MinIO presigned URL
- `TransactionList.tsx` - Right panel, editable rows
- `BalanceIndicator.tsx` - Green/Red/Warning status
- `ReviewActions.tsx` - Approve/Reject/Edit buttons

**Key Features**:
1. Split-view layout (PDF left, transactions right)
2. Inline editing for transaction corrections
3. Real-time balance validation preview
4. Approve disabled if balance invalid
5. Navigation to next pending statement

### 1.5 Tests

```python
# apps/backend/tests/review/test_statement_validation.py

async def test_validate_balance_chain_exact_match():
    """Exact balance match passes."""
    
async def test_validate_balance_chain_within_tolerance():
    """Delta = 0.0009 USD passes."""
    
async def test_validate_balance_chain_exceeds_tolerance():
    """Delta = 0.0011 USD fails."""
    
async def test_approve_statement_success():
    """Approve with valid balance."""
    
async def test_approve_statement_invalid_balance_fails():
    """Reject invalid balance."""
    
async def test_edit_and_approve():
    """Edit transaction amount, recalculate, approve."""
    
async def test_reject_statement_triggers_reparse():
    """Rejection flow."""
    
async def test_first_statement_manual_opening_balance():
    """First statement requires manual opening balance entry."""
```

---

## Phase 2: Stage 2 (Run-Level Review)

### 2.1 Data Model: ConsistencyCheck

```python
# apps/backend/src/models/consistency_check.py

class CheckType(str, Enum):
    DUPLICATE = "duplicate"
    TRANSFER_PAIR = "transfer_pair"
    ANOMALY = "anomaly"

class CheckStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"  # User acknowledged, ignore
    REJECTED = "rejected"  # Flagged for fix
    FLAGGED = "flagged"    # Needs manual review

class ConsistencyCheck(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "consistency_checks"
    
    check_type: Mapped[CheckType] = mapped_column(
        SQLEnum(CheckType, name="check_type_enum"),
        nullable=False,
    )
    status: Mapped[CheckStatus] = mapped_column(
        SQLEnum(CheckStatus, name="check_status_enum"),
        default=CheckStatus.PENDING,
    )
    
    # Related transactions (JSON array of IDs)
    related_txn_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    
    # Check details (varies by type)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Duplicate: {"group_id": "hash", "count": 2, "amount": "100.00"}
    # Transfer: {"from_account": "xxx", "to_account": "yyy", "amount": "500.00"}
    # Anomaly: {"type": "LARGE_AMOUNT", "severity": "high", "message": "..."}
    
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    # high, medium, low
    
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
```

### 2.2 Backend Service: consistency_checks.py

```python
# apps/backend/src/services/consistency_checks.py

async def detect_duplicates(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
) -> list[ConsistencyCheck]:
    """
    Find transactions with same amount, date (±1 day), similar description.
    Uses existing dedup_hash logic from atomic_transactions.
    """
    ...

async def detect_transfer_pairs(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
) -> list[ConsistencyCheck]:
    """
    Find matching OUT/IN transactions across accounts.
    Amount match (tolerance 0.001 USD), date proximity (±3 days).
    """
    ...

async def detect_anomalies_batch(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
) -> list[ConsistencyCheck]:
    """
    Run anomaly detection for all transactions.
    Reuses services/anomaly.py.
    """
    ...

async def run_all_consistency_checks(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID,
) -> list[ConsistencyCheck]:
    """Run all checks for a statement."""
    checks = []
    checks.extend(await detect_duplicates(db, user_id, statement_id))
    checks.extend(await detect_transfer_pairs(db, user_id, statement_id))
    checks.extend(await detect_anomalies_batch(db, user_id, statement_id))
    return checks

async def resolve_check(
    db: AsyncSession,
    check_id: UUID,
    action: str,  # "approve", "reject", "flag"
    user_id: UUID,
    note: str | None = None,
) -> ConsistencyCheck:
    """Resolve a consistency check."""
    ...
```

### 2.3 API Endpoints

```python
# apps/backend/src/routers/review_queue.py (extend)

@router.get("/stage2")
async def get_stage2_review_queue(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
    check_type: CheckType | None = None,
    severity: str | None = None,
) -> Stage2ReviewQueueResponse:
    """Get Stage 2 review queue with pending matches and checks."""
    ...

@router.post("/batch-approve")
async def batch_approve_matches(
    body: BatchApproveRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BatchApproveResponse:
    """
    Batch approve matches.
    BLOCKED if any unresolved consistency checks exist.
    """
    ...

@router.post("/batch-reject")
async def batch_reject_matches(
    body: BatchRejectRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BatchRejectResponse:
    ...

@router.post("/consistency-checks/{check_id}/resolve")
async def resolve_consistency_check(
    check_id: UUID,
    body: ResolveCheckRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> ConsistencyCheckResponse:
    """Resolve a consistency check."""
    ...

@router.get("/consistency-checks")
async def list_consistency_checks(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
    status: CheckStatus | None = None,
) -> list[ConsistencyCheckResponse]:
    ...
```

### 2.4 Frontend: Stage 2 Review Queue

**Route**: `/reconciliation/review-queue`

**Components**:
- `ConsistencyCheckCard.tsx` - Card for each check type
- `ReconciliationMatchList.tsx` - Table with batch select
- `BatchActions.tsx` - Approve/Reject/Export toolbar
- `CheckDetailModal.tsx` - Resolve individual checks

**Key Features**:
1. Consistency check summary panel (top)
2. Match list with batch checkboxes
3. Batch approve blocked if unresolved checks
4. Check resolution modal with approve/reject/flag actions
5. Export to CSV

### 2.5 Tests

```python
# apps/backend/tests/review/test_consistency_checks.py

async def test_detect_duplicates_same_statement():
    """Duplicate in single statement."""
    
async def test_detect_duplicates_cross_statement():
    """Duplicate across statements."""
    
async def test_detect_transfer_pairs_exact_match():
    """Exact amount match."""
    
async def test_detect_transfer_pairs_within_tolerance():
    """Amount delta < 0.001 USD."""
    
async def test_detect_anomalies_balance_jump():
    """Sudden balance increase."""
    
async def test_batch_approve_requires_checks_resolved():
    """Approval blocked by unresolved checks."""
    
async def test_batch_approve_creates_journal_entries():
    """Journal entry generation."""
    
async def test_resolve_check_approve():
    """Approve check (ignore)."""
    
async def test_resolve_check_reject():
    """Reject check (flag for fix)."""
```

---

## File Structure

### Backend (New Files)

```
apps/backend/src/
├── models/
│   ├── statement.py          # Extended with Stage1Status, new fields
│   └── consistency_check.py  # NEW: ConsistencyCheck model
├── services/
│   ├── statement_validation.py  # NEW: Balance chain validation
│   └── consistency_checks.py    # NEW: Dedup, transfer, anomaly
├── routers/
│   ├── statements.py         # Extended with review endpoints
│   └── review_queue.py       # NEW: Stage 2 review endpoints
├── schemas/
│   └── review.py             # NEW: Review request/response schemas
└── migrations/
    └── versions/
        └── xxxx_add_stage1_review_fields.py  # NEW

apps/backend/tests/
└── review/
    ├── test_statement_validation.py  # NEW
    └── test_consistency_checks.py    # NEW
```

### Frontend (New Files)

```
apps/frontend/src/
├── app/(main)/
│   ├── statements/
│   │   └── [id]/
│   │       └── review/
│   │           └── page.tsx      # NEW: Stage 1 review page
│   └── reconciliation/
│       └── review-queue/
│           └── page.tsx          # NEW: Stage 2 review page
└── components/
    └── review/
        ├── PdfViewer.tsx           # NEW
        ├── TransactionList.tsx     # NEW (editable)
        ├── BalanceIndicator.tsx    # NEW
        ├── ReviewActions.tsx       # NEW
        ├── ConsistencyCheckCard.tsx # NEW
        ├── BatchActions.tsx        # NEW
        └── CheckDetailModal.tsx    # NEW
```

---

## Timeline

| Week | Tasks |
|------|-------|
| **Week 1** | Data model + Backend validation service + Migration |
| **Week 2** | API endpoints + Frontend split-view UI (Stage 1) |
| **Week 3** | Testing + Balance chain validation |
| **Week 4** | Consistency check service (dedup, transfer, anomaly) |
| **Week 5** | Review queue UI + Batch operations (Stage 2) |
| **Week 6** | Testing + Conflict resolution + Documentation |

---

## Dependencies

- **EPIC-003** (Statement Parsing) → Generates Stage 1 input ✅
- **EPIC-004** (Reconciliation Engine) → Consumes Stage 2 output ✅
- **EPIC-015** (Processing Account) → Transfer detection overlap (reuse logic)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| PDF viewer performance | Use MinIO presigned URLs, lazy load |
| 0.001 USD tolerance too strict | Configurable in config.py (default 0.001) |
| Batch approval race conditions | Row-level locking, version increment |
| Duplicate detection false positives | Confidence scoring, manual review queue |

---

*Document created: 2026-02-25*
*Last updated: 2026-02-25*
