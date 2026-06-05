# Double-Entry Bookkeeping Domain Model SSOT

> **SSOT Key**: `accounting`
> **Core Definition**: Accounting equation, account classification, and entry rules for double-entry bookkeeping.

---

## 1. Source of Truth

| Dimension | Physical Location (SSOT) | Description |
|-----------|--------------------------|-------------|
| **Bookkeeping Logic** | `apps/backend/src/services/accounting.py` | Core business |
| **Model Definition** | `apps/backend/src/models/journal.py` | ORM |
| **Validation Rules** | `apps/backend/src/schemas/journal.py` | Pydantic |

---

## 2. Architecture Model

### Accounting Equation

```
Assets = Liabilities + Equity + (Income - Expenses)
```

**At any moment, all `posted` entries must satisfy this equation.**

### Account Classification and Debit/Credit Rules

| Type | Debit Increases | Credit Increases | Normal Balance |
|------|-----------------|------------------|----------------|
| Asset | ✓ | | Debit |
| Liability | | ✓ | Credit |
| Equity | | ✓ | Credit |
| Income | | ✓ | Credit |
| Expense | ✓ | | Debit |

### Entry Structure

```mermaid
flowchart LR
    JE[JournalEntry<br/>Entry Header] --> JL1[JournalLine<br/>Debit: Bank 1000]
    JE --> JL2[JournalLine<br/>Credit: Income 1000]
```

### Multi-Currency Journal Balance

Journal entry balance is measured in the configured base currency (`SGD` by default), not by raw nominal line amounts. A non-base-currency line must carry `fx_rate`, where:

```
base_amount = line.amount * line.fx_rate
```

Debit and credit totals are valid only when their converted base amounts differ by no more than `0.01`.

---

## 3. Design Constraints (Dos & Don'ts)

> **SSOT**: The rules in this section are the single authoritative definitions.
> Other files that mention these rules should reference:
> `See: docs/ssot/accounting.md#<anchor>`

### ✅ Recommended Patterns

- **Pattern A**: Each entry has at least 2 lines, debit/credit balanced
- **Pattern B**: Use Decimal for precise calculations, tolerance < 0.01
- **Pattern C**: Posted entries can only be voided, not directly modified
- **Pattern D**: Multi-currency entries validate debit/credit balance after base-currency conversion.
- **Pattern E**: Journal line account authorization is a domain invariant. Accounting services must validate that every `JournalLine.account_id` belongs to the same `user_id` as the `JournalEntry`; HTTP middleware is not sufficient because service calls and background tasks can write ledger records without a request object.

### ⛔ Prohibited Patterns

<a id="decimal-rule"></a>

- **Anti-pattern A**: **NEVER** use FLOAT to store, calculate, or transfer monetary amounts.
    -   **Reason**: IEEE 754 floating point arithmetic causes precision errors (e.g., `0.1 + 0.2 != 0.3`).
    -   **Enforcement**: All Pydantic models use `Decimal`. API clients parse JSON numbers as strings or Decimals, never floats.
    -   **Guardrail**: `apps/backend/tests/accounting/test_decimal_safety.py` fuzzes models with float inputs to ensure strictness.

<a id="entry-balance"></a>

- **Anti-pattern B**: **NEVER** allow unbalanced debit/credit entries. See: `apps/backend/tests/accounting/test_accounting_integration.py::test_post_unbalanced_entry_rejected`
- **Anti-pattern C**: **NEVER** skip validation when writing posted status. See: `apps/backend/tests/accounting/test_accounting_integration.py::test_post_journal_entry_already_posted_fails`
- **Anti-pattern E**: **NEVER** validate a multi-currency journal entry by comparing raw original-currency nominal amounts.
- **Anti-pattern F**: **NEVER** create, post, or aggregate journal lines across user boundaries. Balance queries must require both `Account.user_id == user_id` and `JournalEntry.user_id == user_id`.

<a id="async-tx-boundary"></a>

- **Anti-pattern D**: **NEVER** call `db.commit()` in service-layer methods that receive a `db: AsyncSession` from a router.
    -   **Rule**: Services use `flush()` to assign IDs and validate constraints. Routers call `commit()` to finalize the transaction.
    -   **Documented Exceptions**:
        1. **Background tasks** with own sessions (via `session_maker()`/`session_factory()`): These create their own `AsyncSession` and ARE the transaction boundary. Example: `statement_parsing.py::parse_statement_background()`, `statement_parsing_supervisor.py::reset_stale_parsing_jobs()`, `market_data_scheduler.py::run_daily_market_data_sync()`.
        2. **Streaming generators** that outlive the router response: When a router returns `StreamingResponse`, the async generator runs after the router has returned. The generator must own the final `commit()` for data written during streaming. Example: `ai_advisor.py::_stream_and_store()` commits the assistant message after streaming completes.
    -   **Enforcement**: `apps/backend/tests/ai/test_commit_boundary.py` verifies flush-only behavior in AI advisor service methods.

---

## 4. Standard Operating Procedures (Playbooks)

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

---

## 5. Verification & Testing (The Proof)

| Behavior | Verification Method | Status |
|----------|---------------------|--------|
| Entry debit/credit balance | Unit test `test_journal_balance` | ⏳ Pending |
| Accounting equation | Integration test `test_accounting_equation` | ⏳ Pending |
| Multi-currency base balance | Unit test `test_AC2_12_1_multicurrency_entry_balances_in_base_currency` | ✅ Implemented |
| Accounting equation base conversion | Integration test `test_AC2_12_2_accounting_equation_uses_base_currency_balances` | ✅ Implemented |
| User-scoped line ownership | Integration tests `test_AC2_13_1_*`, `test_AC2_13_2_*`, `test_AC2_13_3_*` | ✅ Implemented |
| Void logic | Unit test `test_void_entry` | ⏳ Pending |

---

## Used by

- [schema.md](./schema.md)
- [reconciliation.md](./reconciliation.md)
