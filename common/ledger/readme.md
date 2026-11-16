# `ledger` — double-entry bookkeeping bounded context

> Owned spec for double-entry bookkeeping and the `1199` Processing virtual account. Conforming implementation: [`apps/backend/src/ledger/`](../../apps/backend/src/ledger/). Money value kernel (`Money`, `Currency`, `ExchangeRate`, `convert`, `to_money`): [`common/audit/money`](../audit/money/readme.md#money-type).

## 1. Source of Truth

| Concern | Location |
|---|---|
| Core bookkeeping & posting | `apps/backend/src/ledger/extension/accounting.py` |
| Processing & transfer legs | `apps/backend/src/ledger/extension/processing.py` |
| Pure processing rules | `apps/backend/src/ledger/base/processing.py` |
| Account & equity resolution | `apps/backend/src/ledger/extension/account_service.py` |
| ORM models | `apps/backend/src/ledger/orm/account.py`, `apps/backend/src/ledger/orm/journal.py` |
| Schemas | `apps/backend/src/schemas/journal.py`, `apps/backend/src/schemas/account.py` |

## 2. Architecture Model

<a id="accounting-equation"></a>
### Accounting Equation

```text
Assets = Liabilities + Equity + (Income - Expenses)
```

Every `posted` / `reconciled` journal set must satisfy this equation. Normal balances: Debit for `ASSET` / `EXPENSE`; Credit for `LIABILITY` / `EQUITY` / `INCOME`.

### Multi-Currency Journal Balance & Immutability

- Journal balance is evaluated in effective `base_currency` (`SGD` by default). Non-base lines require positive `fx_rate` (`base_amount = line.amount * line.fx_rate`), and base debits must equal base credits within `0.01`.
- Nominal balance helper: `calculate_account_balances`; base-converted helper: `calculate_account_balances_in_base_currency`.
- Database triggers and constraints reject posted/reconciled entries with `< 2` lines, unbalanced base totals, or missing FX rates, and forbid direct updates/deletes on posted/reconciled facts.
- Correction uses append-only void/reversal preserving the original entry's historical base currency (`journal_entries.base_currency`), line order (`journal_lines.line_no`), and scale (2dp amounts, 6dp FX rates).
- `JOURNAL_MEMO_MAX_LENGTH` (`500`) is enforced at input schemas and truncated cleanly by `fit_journal_memo` before anchor hashing.
- All financial writes enter through `submit_anchored_journal_entry` (or batch port `submit_anchored_journal_entries`), which verifies tenant-scoped `TraceRecord` authority (`anchored|legacy_unproven`, joined via `current_anchored_journal_entries`).
- Journal lines enforce strict tenant ownership (`Account.user_id == JournalEntry.user_id == user_id`).

### First-Use Setup

- Account create/edit share `AccountFormModal`. Guided opening balances start with a blank as-of date, accept the day before report start or a direct date before period start, and post Decimal strings through `POST /api/accounts/opening-balances` (`AC-ledger.first-use.1`).

## 3. Design Constraints (Dos & Don'ts)

> Cross-references to this section must cite `common/ledger/readme.md#<anchor>`.

### Recommended Patterns

- Balanced `>= 2`-line entries checked in `base_currency` within `0.01`.
- Posted facts are voided, never mutated; every `JournalLine.account_id` belongs to `JournalEntry.user_id`.
- `ResolvedJournalContribution` publishes audit `TraceDecisionRef` (`decision_id`, exact target, exact assertion).

### Prohibited Patterns

<a id="decimal-rule"></a>
- **Monetary `Decimal` rule**: NEVER use `float` for monetary amounts or FX math. All API models, domain math (`src.audit.money.to_money()`), and DB columns (`DECIMAL(18,2)`) use `Decimal` with `ROUND_HALF_EVEN` (out of scope: `ExchangeRate`, 6dp security prices/quantities, ratios). Enforced by `apps/backend/tests/accounting/test_decimal_safety.py` and `apps/backend/tests/audit/money/test_money.py`.

<a id="entry-balance"></a>
- **Entry balance invariant**: NEVER post unbalanced debit/credit entries (`debits = credits`), skip balance checks on posting, aggregate across tenants, or mutate posted/reconciled facts directly.

<a id="async-tx-boundary"></a>
- **Async transaction boundary**: NEVER call `db.commit()` inside service methods taking a router `db: AsyncSession`. Services call `flush()`; routers own `commit()`. Documented exceptions: background workers creating their own session via `session_maker()`, and streaming generators finalizing writes after router return (`tests/ai/test_commit_boundary.py`).

## 4. Standard Operating Procedures (Playbooks)

1. Validate balance (`<= 0.01` in base currency) and tenant ownership before writing `JournalEntry` + `JournalLine`.
2. Require active non-system accounts on manual posts and explicit valid `fx_rate` for foreign-currency lines.
3. Void `posted` entries by creating an opposing reversal entry in the original historical base currency and transitioning the original status to `void`.

## Processing Virtual Account (`1199`)

- **Role**: System-managed `ASSET` account (`code = "1199"`, `is_system = True`), hidden from normal user account lists and manual entries; reserved for in-transit inter-account transfer legs (`Entry.transfer`) created by reconciliation/classification.
- **Acquisition**: `_get_or_create_system_equity_account` handles `3199` / `3198` equity accounts; `account_service.find_or_create_account` creates Processing in a short transaction under `account-creation:<user_id>` so concurrent uploads do not collide. Reads (`find_processing_account`) never auto-create it.
- **Unpaired balance**: Non-zero Processing balance flags unpaired in-transit transfers as a report readiness blocker; pairing both `OUT` and `IN` legs returns Processing balance to zero.

## Account starting stock

- `list_opening_positions` publishes immutable `OpeningPosition` records (`opening_position_records`) with effective date, signed normal-side amount, currency, historical FX, optional journal ID, and current trace decision.
- `initialize_opening_positions(..., allow_supersede=True)` anchors each account's earliest approved statement $S_0$ against `3199 Opening Balance Equity` (`OPENING_BALANCE_EQUITY_CODE`), superseding prior openings when an earlier statement arrives or $S_0$ retires.
- Adjacent approved statement gaps exceeding `CROSS_PERIOD_GAP_PLUG_TOLERANCE` (`0.10`) post `cross_period_gap_plug` entries against `3198 Unexplained Statement Gap Equity` (`UNEXPLAINED_GAP_EQUITY_CODE`), recalculating automatically when missing intermediate statements are approved or retired.
- Foreign-currency openings and gap plugs require historical FX rates; zero positions record trace evidence without a zero-value journal entry.
