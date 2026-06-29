---
name: accounting
description: Double-entry bookkeeping rules, accounting equation validation, entry creation and voiding procedures. Use this skill when working with journal entries, accounts, debits/credits, or any financial transaction recording.
---

# Double-Entry Bookkeeping Domain Model

> **Core Definition**: Accounting equation, account classification, and entry rules for double-entry bookkeeping.
> **SSOT**: [`common/ledger/readme.md`](../../../../common/ledger/readme.md) is authoritative for every rule below.

## Accounting Equation

```
Assets = Liabilities + Equity + (Income - Expenses)
```

**At any moment, all `posted` entries must satisfy this equation.**

## Money Rules (read before touching any amount)

- **Decimal only** — NEVER use `float` to store, calculate, or transfer money.
- **Rule A2 — canonical rounding**: currency amounts are quantized to **2 dp with
  banker's rounding (`ROUND_HALF_EVEN`)**. Always round through the one helper
  `apps/backend/src/utils/money.py::to_money()` (exposed as `src.utils.to_money`).
  Do NOT hand-roll `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` for money.
  Out of scope (keep their own quantization): FX rates & security prices (6 dp),
  share quantities (6 dp), percentages/ratios (XIRR, TWR, MWR, allocation %).
  Guardrail: `apps/backend/tests/money/test_money.py`.

## Multi-Currency Journal Balance

Balance is measured in the configured **base currency** (`SGD` by default), not
raw nominal line amounts. A non-base-currency line MUST carry `fx_rate`:

```
base_amount = line.amount * line.fx_rate
```

Debit and credit totals are valid only when their converted **base** amounts
differ by ≤ `0.01`. NEVER validate by comparing raw original-currency nominals.

## Account Classification and Debit/Credit Rules

| Type | Debit Increases | Credit Increases | Normal Balance |
|------|-----------------|------------------|----------------|
| Asset | ✓ | | Debit |
| Liability | | ✓ | Credit |
| Equity | | ✓ | Credit |
| Income | | ✓ | Credit |
| Expense | ✓ | | Debit |

## Design Constraints

### ✅ Recommended Patterns

- **Pattern A**: Each entry has at least 2 lines, debit/credit balanced.
- **Pattern B**: Use Decimal; round money via `to_money()` (Rule A2 above).
- **Pattern C**: Posted entries can only be voided, not directly modified.
- **Pattern D**: Multi-currency entries validate balance **after** base-currency conversion.
- **Pattern E**: Account authorization is a domain invariant — services must
  validate every `JournalLine.account_id` belongs to the same `user_id` as the
  `JournalEntry`. HTTP middleware is not sufficient (services and background
  tasks write without a request object).
- **Pattern F**: Posted/reconciled invariants are enforced at **both** the
  service and the database boundary (DB triggers reject ledger violations).
- **Pattern G**: The only non-fact update allowed on a posted/reconciled entry is
  source-type promotion from `auto_parsed`/`bank_statement`/`auto_matched` →
  `user_confirmed`, with `source_id` and every accounting fact unchanged.

### ⛔ Prohibited Patterns

- **NEVER** use FLOAT to store, calculate, or transfer monetary amounts.
- **NEVER** allow unbalanced debit/credit entries (base-currency totals).
- **NEVER** skip validation when writing posted status.
- **NEVER** directly update or delete posted/reconciled/void ledger facts — use
  the void/reversal workflow.
- **NEVER** create, post, or aggregate journal lines across user boundaries.
- **NEVER** downgrade `source_type` or change `source_id` after posting.

### Async Transaction Boundary

Services that receive `db: AsyncSession` from a router use `flush()` (assign IDs,
validate constraints); the **router** calls `commit()`. Exceptions that own their
own commit: background tasks with their own session, and streaming generators
that outlive the router response. Enforcement:
`apps/backend/tests/ai/test_commit_boundary.py`.

## Standard Operating Procedures

### SOP-001: Create Manual Entry

```python
def create_manual_entry(user_id, date, memo, lines: list[dict]) -> JournalEntry:
    # 1. Validate debit/credit balance
    total_debit = sum(l["amount"] for l in lines if l["direction"] == "DEBIT")
    total_credit = sum(l["amount"] for l in lines if l["direction"] == "CREDIT")
    if abs(total_debit - total_credit) > Decimal("0.01"):
        raise ValidationError("Debit/credit not balanced")
    
    # 2. Create entry header
    entry = JournalEntry(
        user_id=user_id,
        entry_date=date,
        memo=memo,
        source_type="manual",
        status="draft"
    )
    
    # 3. Create lines
    for line in lines:
        entry.lines.append(JournalLine(**line))
    
    return entry
```

### SOP-002: Post Entry

```python
def post_entry(entry: JournalEntry) -> None:
    # 1. Re-validate balance
    validate_balance(entry)
    
    # 2. Validate accounts are active
    for line in entry.lines:
        if not line.account.is_active:
            raise ValidationError(f"Account {line.account.name} is disabled")
    
    # 3. Update status
    entry.status = "posted"
    entry.updated_at = datetime.utcnow()
```

### SOP-003: Void Entry

```python
def void_entry(entry: JournalEntry, reason: str) -> JournalEntry:
    # 1. Can only void posted entries
    if entry.status != "posted":
        raise ValidationError("Can only void posted entries")
    
    # 2. Create reversal entry
    reverse_entry = JournalEntry(
        user_id=entry.user_id,
        entry_date=date.today(),
        memo=f"Void: {entry.memo} ({reason})",
        source_type="system",
        status="posted"
    )
    
    for line in entry.lines:
        reverse_entry.lines.append(JournalLine(
            account_id=line.account_id,
            direction="CREDIT" if line.direction == "DEBIT" else "DEBIT",
            amount=line.amount,
            currency=line.currency
        ))
    
    # 3. Mark original entry
    entry.status = "void"
    
    return reverse_entry
```

## Source Files

- **Logic**: `apps/backend/src/services/accounting.py`
- **Models**: `apps/backend/src/models/journal.py`
- **Schemas**: `apps/backend/src/schemas/journal.py`
