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

### Posted Ledger Database Floor

Application services validate drafts before posting, but the database is the
final boundary for posted/reconciled ledger facts. Direct writes that bypass
services must still be rejected when they would create a posted or reconciled
entry with fewer than two lines, unbalanced base-currency debit/credit totals,
or non-base lines without a positive `fx_rate`.

Posted and reconciled entries are immutable ledger facts. They must not be
updated or deleted directly; the only supported correction is a void transition
that preserves an immutable reversal relationship. Draft entries remain editable
and deletable until posting.

Ledger immutability protects accounting facts: entry ownership/date/memo/source
identity, status correction path, and all journal-line amounts, directions,
accounts, currencies, and FX rates. The only non-fact metadata update allowed on
a posted/reconciled entry is the source-type-priority promotion from
`auto_parsed` or `auto_matched` to `user_confirmed`, with `source_id` and every
accounting fact unchanged. The same promotion is allowed when the entry moves
from `posted` to `reconciled`. (The immutability trigger's text guard also
retains the retired legacy value `bank_statement` — see migration 0040 / #896 —
so any historical row in that state can still be promoted, though no write path
produces it anymore.)

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
- **Pattern F**: Posted/reconciled ledger invariants are enforced at both service and database boundaries.
- **Pattern G**: Posted/reconciled source-type promotion may only increase trust from auto/statement-derived provenance to `user_confirmed`; it must not change source identity or accounting facts.

### ⛔ Prohibited Patterns

<a id="decimal-rule"></a>

- **Anti-pattern A**: **NEVER** use FLOAT to store, calculate, or transfer monetary amounts.
    -   **Reason**: IEEE 754 floating point arithmetic causes precision errors (e.g., `0.1 + 0.2 != 0.3`).
    -   **Enforcement**: All Pydantic models use `Decimal`. API clients parse JSON numbers as strings or Decimals, never floats.
    -   **Guardrail**: `apps/backend/tests/accounting/test_decimal_safety.py` fuzzes models with float inputs to ensure strictness.

- **Rule A2 — Canonical money rounding**: Currency amounts are quantized to **2 decimal places using banker's rounding (`ROUND_HALF_EVEN`)**. This is the single project-wide rounding mode for money.
    -   **Enforcement**: round money through the one helper `src.money.to_money()` (the backend money module; mirrored from `common/money`). Do not hand-roll `quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` for currency.
    -   **Scope**: currency amounts only. Intentionally **out of scope** (they keep their own quantization/rounding): typed `ExchangeRate` values, security prices (6 dp), `Quantity` values (6 dp), and percentages / performance ratios (XIRR, TWR, MWR, allocation %).
    -   **Guardrail**: `apps/backend/tests/money/test_money.py`.

<a id="money-type"></a>

- **Rule A3 — Money value types (narrow waist)**: The application-layer money
  primitives live in **`common/money/`** (the shared waist). They sit *above* the
  DB double-entry invariant floor (`fr_validate_journal_entry_invariants`,
  [schema.md](schema.md)) and make bad money states unrepresentable rather than
  merely tested-against (#1167). Dependency-light (stdlib + `Decimal` only) so
  backend, e2e, frontend helpers and tooling can share one definition. The
  backend ships its own self-contained copy at **`apps/backend/src/money/`** (the
  backend's "end"; `common/` is not shipped into the image), kept in lockstep
  with the reference impl by the shared conformance vectors (#1171). Backend
  call-sites import `src.money` directly (the former `src/utils/money.py`
  re-export shim was retired).
    -   **`Money(amount, currency)`** — immutable, `Decimal`-backed; construction
        **rejects `float`/`bool`** (the decimal red line, type-enforced) and stores
        the *exact* `Decimal` (round explicitly via `Money.quantize()` / the FX
        boundary, never force-quantized on construction).
    -   **`Currency`** — a validated ISO-4217 alphabetic code (not a bare `str`);
        normalises case and rejects unknown codes at construction.
    -   **`ExchangeRate(base, quote, rate)`** — the typed directed FX conversion
        parameter. `base` / `quote` are validated currencies; `rate` is finite,
        positive Decimal; **`float`/`bool` are rejected**.
    -   **Arithmetic** — same-currency `+`/`-`/comparison only; any cross-currency
        operation raises `CurrencyMismatchError`. No implicit conversion, no
        implicit `float`.
    -   **`convert(money, exchange_rate, rounding=ROUND_HALF_EVEN)`** — the
        **single** FX conversion primitive: `exchange_rate.base` must equal
        `money.currency`; the result currency is `exchange_rate.quote`; banker's
        rounding applies at the 2-dp boundary; used for base-currency restatement.
    -   **`CurrencyBalances`** — per-currency opening/closing container with **no
        scalar accessor**, so a multi-currency statement cannot collapse onto one
        currency (closes the #1139/#1123 representation gap); round-trips the
        `StatementSummary.currency_balances` JSONB shape.
    -   **Cross-language standard**: money behaviour is consistent across **every
        end** via a language-neutral conformance suite —
        `common/money/conformance/vectors.json` (rounding/convert/currency cases)
        plus the interface in `common/money/contract/money.contract.md`. The
        Python impl and the frontend TS impl (`apps/frontend/src/lib/money/`) both
        load the **same** vectors and must reproduce every value, so the two ends
        cannot diverge (e.g. banker's rounding vs `decimal.js` HALF_UP). The suite
        is **dev/test-time only** — it is never shipped into a runtime image, which
        is why no app needs `common/` packaged into its container.
    -   **Guardrail (AC2.19–AC2.21)**: `tests/tooling/test_money_value_type.py`,
        `tests/tooling/test_money_conformance.py`.

<a id="entry-balance"></a>

- **Anti-pattern B**: **NEVER** allow unbalanced debit/credit entries. See: `apps/backend/tests/accounting/test_accounting_integration.py::test_post_unbalanced_entry_rejected`
- **Anti-pattern C**: **NEVER** skip validation when writing posted status. See: `apps/backend/tests/accounting/test_accounting_integration.py::test_post_journal_entry_already_posted_fails`
- **Anti-pattern E**: **NEVER** validate a multi-currency journal entry by comparing raw original-currency nominal amounts.
- **Anti-pattern F**: **NEVER** create, post, or aggregate journal lines across user boundaries. Balance queries must require both `Account.user_id == user_id` and `JournalEntry.user_id == user_id`.
- **Anti-pattern G**: **NEVER** directly update or delete posted/reconciled/void ledger facts. Use the void/reversal workflow.
- **Anti-pattern H**: **NEVER** downgrade `source_type` or change `source_id` after posting/reconciliation. Provenance corrections must use the explicit source-type promotion path only.

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
| Database ledger invariant floor | Direct DB-bypass tests `test_AC2_14_*` | ✅ Implemented |
| Void logic | Unit test `test_void_entry` | ⏳ Pending |

---

## Used by

- [schema.md](./schema.md)
- [reconciliation.md](./reconciliation.md)
