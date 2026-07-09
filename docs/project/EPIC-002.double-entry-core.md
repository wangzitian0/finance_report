# EPIC-002: Double-Entry Bookkeeping Core

> **Status**: ✅ Complete  
> **Vision Anchor**: `decision-filter-accuracy-auditability`  
> **Phase**: 1  
> **Duration**: 3 weeks  
> **Dependencies**: EPIC-001  
> **Completed**: 2026-01-17

---

## 🎯 Objective

Implement a double-entry bookkeeping system that complies with the accounting equation, supporting manual journal entries and account management.

**Core Constraints**:
```
Assets = Liabilities + Equity + (Income - Expenses)
SUM(DEBIT) = SUM(CREDIT)  // Each journal entry must balance
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 📊 **Accountant** | Accounting Correctness | Must strictly follow double-entry bookkeeping rules, correct debit/credit directions for five account types |
| 🏗️ **Architect** | Data Model | JournalEntry + JournalLine pattern supports one-to-many, many-to-many scenarios |
| 💻 **Developer** | Implementation Difficulty | Use Decimal instead of float, transactions ensure atomicity |
| 🧪 **Tester** | Validation Strategy | 100% coverage of balance validation logic, boundary tests (extreme amounts, multi-currency) |
| 📋 **PM** | User Value | Manual bookkeeping is foundation for future automation, highest priority |

---

## ✅ Task Checklist

### Data Model (Backend) ✅

- [x] `Account` model - Five account types (Asset/Liability/Equity/Income/Expense), plus `code`, `parent_id`, `is_active`
- [x] `JournalEntry` model - Entry header (date, memo, status, source_type/source_id, created_at, updated_at)
- [x] `JournalLine` model - Entry line (account_id, direction, amount, currency, fx_rate, event_type, tags)
- [x] Database initialization (SQLAlchemy metadata)
- [x] Pydantic Schema (request/response)

### API Endpoints (Backend) ✅

- [x] `POST /api/accounts` - Create account
- [x] `GET /api/accounts` - Account list (with type filter)
- [x] `GET /api/accounts/{id}` - Account details (with balance)
- [x] `PUT /api/accounts/{id}` - Update account
- [x] `POST /api/journal-entries` - Create journal entry (with balance validation)
- [x] `GET /api/journal-entries` - Journal entry list (pagination, date filter)
- [x] `GET /api/journal-entries/{id}` - Journal entry details
- [x] `POST /api/journal-entries/{id}/postings` - Post entry (draft → posted)
- [x] `POST /api/journal-entries/{id}/voidings` - Void entry (generate reversal entry)

### Business Logic (Backend) ✅

- [x] `ledger/extension/accounting.py` - Accounting core
  - [x] `validate_journal_balance()` - Debit/credit balance validation
  - [x] `post_journal_entry()` - Posting logic
  - [x] `calculate_account_balance()` - Account balance calculation
  - [x] `verify_accounting_equation()` - Accounting equation verification
  - [x] `void_journal_entry()` - Reversal entry generation
- [x] FX rate handling - Require `fx_rate` when entry currency != base currency (manual input or market_data lookup)
- [x] Database constraints - CHECK constraints ensure amount > 0
- [x] Transaction handling - Journal entry creation atomic

### Tests ✅

- [x] `test_balanced_entry_passes` - Balanced entries validation
- [x] `test_unbalanced_entry_fails` - Unbalanced entries rejection
- [x] `test_single_line_entry_fails` - Minimum 2 lines requirement
- [x] `test_decimal_precision` - Decimal precision tests

### Frontend Interface (Next Phase)

- [x] `/accounts` - Account management page
  - [x] Account list (grouped by type)
  - [x] Create account form
  - [ ] Account details sidebar
- [x] `/journal` - Journal entry management page
  - [x] Journal entry list (searchable, paginated)
  - [x] Create journal entry form (dynamically add multiple lines)
  - [ ] Journal entry details modal
  - [x] Post/void operation buttons

---

## 🧪 Test Cases

> **The EPIC-002 double-entry backend ACs in groups AC2.1–AC2.12 and the genuine
> double-entry rows of AC2.13–AC2.16 are no longer defined here.** They migrated
> into the `ledger` package (#1420 slices 3c-ii and 3c-iii) and are owned by, and
> sourced directly from,
> [`common/ledger/contract.py`](../../common/ledger/contract.py)'s `roadmap` under
> the package-scoped numeric `AC-ledger.<group>.<seq>` id scheme (the leading "2"
> is dropped and the sequence preserved, so `AC2.<g>.<s>` becomes
> `AC-ledger.<g>.<s>`; groups 1–12 are slice 3c-ii, 13–16 are slice 3c-iii, and
> 71–76 are the EPIC-015 processing block from slice 3c-i).
> `common/meta/extension/generate_ac_registry.py` reads package-contract roadmaps additively,
> so the AC index counts them without an EPIC-table mirror. This note references
> the new ids (keeping the registry↔EPIC link intact) but defines none of them —
> the contract is the single definition source. The **non-double-entry** rows of
> the AC2.13–AC2.23 range stay defined below, because they are not ledger ACs: the
> frontend UI ACs `AC2.15.8` / `AC2.16.3` / `AC2.17.1` (the ledger package is
> `fe=None`), the cross-EPIC framework-boundary doc-contract `AC2.18.1`, and the
> Money value-type extension `AC2.19.*`–`AC2.22.*` (owned by the `money` kernel).
> Slice 3c-iii is the final AC batch of the #1420 cutover. *(AC2.16 group's
> reporting-layer row and AC2.12's stream-redaction row removed — migration
> closeout wave 2, #1663 — canonical copies are in the `reporting` and
> `advisor` package roadmaps; see their own notes below.)*
>
> The two Money *leftovers* whose anchor test proves a money-package statement — the
> net-worth restatement via the `convert` primitive and the narrow-waist `float`-ban
> guard — have since migrated into the `money` package roadmap, owned by and sourced
> from [`common/audit/contract.py`](../../common/audit/contract.py); their EPIC-002
> table rows are deleted.
>
> **Money leftovers** (net-worth restatement + narrow-waist `float`-ban guard, was
> AC2.22.* / AC2.23.*): `AC-money.22.3` · `AC-money.23.1`
> *(AC2.22.3 and AC2.23.1 removed — canonical copies are the two `AC-money.*` ids above)*
>
> The pure value-type ACs (was the AC2.19/2.20/2.21/2.22 groups) are
> fully re-homed into the audit package roadmap as `AC-audit.19.*` /
> `AC-audit.20.*` / `AC-audit.21.1` / `AC-audit.22.*` — no value-type rows
> remain in this EPIC.
>
> **Account management** (was AC2.1.*):
> `AC-ledger.1.1` · `AC-ledger.1.2` · `AC-ledger.1.3` · `AC-ledger.1.4` · `AC-ledger.1.5` · `AC-ledger.1.6`
>
> **Journal entry creation & validation** (was AC2.2.*):
> `AC-ledger.2.1` · `AC-ledger.2.2` · `AC-ledger.2.3` · `AC-ledger.2.4` · `AC-ledger.2.5` · `AC-ledger.2.6` · `AC-ledger.2.7`
>
> **Journal entry posting & voiding** (was AC2.3.*):
> `AC-ledger.3.1` · `AC-ledger.3.2` · `AC-ledger.3.3` · `AC-ledger.3.4` · `AC-ledger.3.5` · `AC-ledger.3.6` · `AC-ledger.3.7` · `AC-ledger.3.8` · `AC-ledger.3.9` · `AC-ledger.3.10` · `AC-ledger.3.11`
>
> **Balance calculation** (was AC2.4.*):
> `AC-ledger.4.1` · `AC-ledger.4.2` · `AC-ledger.4.3` · `AC-ledger.4.4` · `AC-ledger.4.5` · `AC-ledger.4.6`
>
> **Accounting equation validation** (was AC2.5.*):
> `AC-ledger.5.1` · `AC-ledger.5.2` · `AC-ledger.5.3`
>
> **Boundary & edge cases** (was AC2.6.*):
> `AC-ledger.6.1` · `AC-ledger.6.2` · `AC-ledger.6.3` · `AC-ledger.6.4`
>
> **API router & error handling** (was AC2.7.*):
> `AC-ledger.7.1` · `AC-ledger.7.2` · `AC-ledger.7.3` · `AC-ledger.7.4` · `AC-ledger.7.5` · `AC-ledger.7.6` · `AC-ledger.7.7`
>
> **Decimal safety** (was AC2.8.*):
> `AC-ledger.8.1` · `AC-ledger.8.2` · `AC-ledger.8.3`
>
> **Data model checklist coverage** (was AC2.9.*):
> `AC-ledger.9.1` · `AC-ledger.9.2` · `AC-ledger.9.3` · `AC-ledger.9.4`
>
> **API endpoint checklist coverage** (was AC2.10.*):
> `AC-ledger.10.1` · `AC-ledger.10.2` · `AC-ledger.10.3` · `AC-ledger.10.4` · `AC-ledger.10.5`
>
> **Must-have traceability** (was AC2.11.*):
> `AC-ledger.11.4`
>
> **Multi-currency ledger integrity** (was AC2.12.*):
> `AC-ledger.12.1` · `AC-ledger.12.2` · `AC-ledger.12.6`
>
> **User-scoped ledger integrity** (was AC2.13.*):
> `AC-ledger.13.1` · `AC-ledger.13.2` · `AC-ledger.13.3`
>
> **Database ledger invariant floor** (was AC2.14.*):
> `AC-ledger.14.1` · `AC-ledger.14.2` · `AC-ledger.14.3` · `AC-ledger.14.4` · `AC-ledger.14.5` · `AC-ledger.14.6`
>
> **Guided opening balances — backend** (was the AC2.15.* backend rows; the frontend `AC2.15.8` stays in EPIC-002):
> `AC-ledger.15.1` · `AC-ledger.15.2` · `AC-ledger.15.3` · `AC-ledger.15.4` · `AC-ledger.15.5` · `AC-ledger.15.6` · `AC-ledger.15.7`
>
> **Opening-balance readiness — backend** (was the AC2.16.* backend detection rows; the frontend `AC2.16.3` stays in EPIC-002; *the AC2.16 group's reporting-layer row removed* — migrated to `reporting`, #1663):
> `AC-ledger.16.1` · `AC-ledger.16.2`

### AC2.17: Account Management UI Responsiveness

> Renumbered from a second `AC2.12` group that collided with AC2.12 (Multi-Currency
> Ledger Integrity); the AC IDs are unique, the namespaces were not.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.17.1 | Accounts page mobile filters and account rows avoid document-level horizontal scroll and content overlap | `AC2.17.1 mobile accounts avoids document horizontal scroll and overlapping row controls` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 |

> The groups AC2.7–AC2.12 (API router & error handling, decimal safety, the data
> model + endpoint checklists, must-have traceability, and multi-currency ledger
> integrity) are part of the same EPIC-002 first-half migration into the `ledger`
> package (#1420 slice 3c-ii); their new `AC-ledger.7.*`–`AC-ledger.12.*` ids are
> listed in the disclaimer above and defined in
> [`common/ledger/contract.py`](../../common/ledger/contract.py)'s `roadmap`.

### Was in AC2.12 (not a ledger AC — since migrated)

*(AC2.12's stream-redaction row removed.)* It was mis-filed in the AC2.12
multi-currency group — it covers stream-redaction (PII chunk buffering), not
double-entry — so it was **not** migrated into `ledger` (which would have
mis-homed a storage AC). `StreamRedactor` is already `advisor`'s own
guardrail unit, so it moved (migration closeout wave 2, #1663) to
[`common/advisor/contract.py`](../../common/advisor/contract.py)'s
`roadmap` as `AC-advisor.guardrail.13`.

> **AC2.13 (User-Scoped Ledger Integrity) and AC2.14 (Database Ledger Invariant
> Floor)** were genuine double-entry groups and migrated wholesale into the
> `ledger` package as `AC-ledger.13.*` and `AC-ledger.14.*` (#1420 slice 3c-iii);
> see the disclaimer above. No EPIC-002 row remains for them.

### AC2.15: Guided Opening Balances ([#949](https://github.com/wangzitian0/finance_report/issues/949)) — frontend AC only

A user with pre-existing assets/liabilities can establish year-start balances via one guided request, so a cross-year balance sheet is complete from the start instead of silently omitting the opening position.

> The backend opening-balance ACs in the `AC2.15.*` range (which post and validate
> the balanced double-entry) migrated into the `ledger` package as
> `AC-ledger.15.*` (#1420 slice 3c-iii). Only the **frontend** guided-flow AC
> `AC2.15.8` stays here, because the ledger package is `fe=None` (the same rule
> that kept EPIC-015's `AC15.7.*` frontend rows in their EPIC).

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.15.8 | The Accounts page offers a guided opening-balance flow: a non-accountant enters an as-of date and a starting balance per eligible (active, non-income/expense) account, and the UI posts the balances map to `POST /api/accounts/opening-balances` — never hand-written journal lines — validating positive two-decimal amounts and surfacing backend errors instead of silently closing | `AC2.15.8 lists only eligible accounts and hides income/expense and inactive ones`, `AC2.15.8 posts a balances map without requiring hand-written journal lines`, `AC2.15.8 blocks submission until at least one positive balance is entered`, `AC2.15.8 rejects non-positive or over-precise amounts before calling the API`, `AC2.15.8 surfaces a backend error instead of closing` | `apps/frontend/src/__tests__/openingBalanceModal.test.tsx` | P1 |

### AC2.16: Opening-Balance Readiness Nudge ([#949](https://github.com/wangzitian0/finance_report/issues/949)) — frontend AC only

The everyday-user persona who already owns assets/liabilities on day one can post
real activity without ever recording a starting position, yielding a balance
sheet that looks right but silently omits the opening balances. These ACs surface
that gap before the numbers are trusted.

> The backend ledger-activity detection ACs in the `AC2.16.*` range migrated into
> the `ledger` package as `AC-ledger.16.*` (#1420 slice 3c-iii). The **frontend**
> nudge `AC2.16.3` stays here (ledger is `fe=None`). *(The AC2.16 group's
> reporting-layer row removed — a report-assembly property, not a
> double-entry posting one; migrated to `reporting`, migration closeout
> wave 2, #1663 — see below.)*

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.16.3 | The Accounts page shows a warning nudge (with a CTA that opens the guided flow) when opening balances are missing, and hides it once they are recorded | `AC2.16.3 shows a readiness nudge and opens the modal when opening balances are missing`, `AC2.16.3 hides the readiness nudge when opening balances are already recorded` | `apps/frontend/src/__tests__/accountsPage.test.tsx` | P1 |

> **Migrated**: the balance sheet and net-worth allocation confidence-tier
> degrade (was the AC2.16 group's reporting-layer row) is report assembly,
> not double-entry posting or frontend UI, so it moved to
> [`common/reporting/contract.py`](../../common/reporting/contract.py)'s
> `roadmap` as `AC-reporting.opening-balance.1` / `.2` / `.3`.

## 📏 Acceptance Criteria

> ℹ️ **Non-contiguous AC numbering**: Gaps in `AC2.x.y` numbers reflect deprecated or merged ACs preserved through generated registry indexes plus explicit overrides. Do **not** renumber. New ACs append to the next available index in this EPIC.

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Accounting equation 100% satisfied** | `verify_accounting_equation()` test | 🔴 Critical |
| **All posted entries balanced** | SQL query verification + Unit tests | 🔴 Critical |
| **No float for monetary amounts** | Code review + grep check | 🔴 Critical |
| **Multi-currency entry support** | `fx_rate` required on non-base currency lines | 🔴 Critical |
| Auto-validate balance when creating entry | Unbalanced returns 400 error | Must Have |
| Correct debit/credit direction by account type | Reference `common/ledger/readme.md` rules | Must Have |
| Posted entries cannot be edited | Can only void and recreate | Must Have |
| API response time p95 < 200ms | Load testing | Must Have |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Unit test coverage > 90% | coverage report | ⏳ |
| Account codes support (1xxx-5xxx) | code field implementation | ⏳ |
| Journal entry templates | One-click common entries | ⏳ |
| Real-time balance validation in frontend | Display debit/credit difference on input | ⏳ |

### 🚫 Not Acceptable

- Posted entries with unbalanced debits/credits
- Accounting equation not satisfied
- Using float for monetary amounts
- Posted entries modified after posting
- API returns 500 errors

---

## 🧪 Test Scenarios

### Unit Tests ✅ (4/4 Passing)

```python
# tests/test_accounting.py
def test_balanced_entry_passes():        # ✅ Passed
def test_unbalanced_entry_fails():       # ✅ Passed
def test_single_line_entry_fails():      # ✅ Passed
def test_decimal_precision():            # ✅ Passed
```

### Integration Tests ✅ (7/7 Passing)

```python
# tests/test_accounting_integration.py
def test_calculate_balance_for_asset_account():       # ✅ Passed
def test_calculate_balance_for_income_account():      # ✅ Passed
def test_post_journal_entry_success():                # ✅ Passed
def test_post_journal_entry_already_posted_fails():   # ✅ Passed
def test_void_journal_entry_creates_reversal():       # ✅ Passed
def test_accounting_equation_holds():                 # ✅ Passed
def test_draft_entries_not_included_in_balance():     # ✅ Passed
```

### Schema Validation Tests ✅ (15/15 Passing)

```python
# tests/test_schemas.py
class TestAccountSchemas:      # 5 tests
class TestJournalLineSchemas:  # 3 tests
class TestJournalEntrySchemas: # 5 tests
class TestVoidRequest:         # 2 tests
```

### Test Coverage: 73%+ ✅

```
src/ledger/extension/accounting.py      91%
src/schemas/account.py         100%
src/schemas/journal.py         100%
src/models/account.py           97%
src/models/journal.py           96%
```

### Running Tests

```bash
cd apps/backend

# Start PostgreSQL first
podman compose -f docker-compose.yml up -d postgres

# Create test database
podman exec finance_report_db psql -U postgres -c "CREATE DATABASE finance_report_test;"

# Run tests
uv run pytest -v
```

### Boundary Tests (Nice to Have)

```python
def test_max_amount():
    """Maximum amount 999,999,999.99"""

def test_min_amount():
    """Minimum amount 0.01"""

def test_many_lines_entry():
    """Multi-line entries (e.g., salary detail breakdown)"""
```

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - Database table structure
- [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) - Accounting rules

---

## 🗄️ Archive Integration Notes

The useful material from the removed `EPIC-002-*` archive snapshots is
consolidated here as current EPIC-owned context. The removed inventory is
retained in [#548](https://github.com/wangzitian0/finance_report/issues/548):

- The durable design is the `JournalEntry` header plus `JournalLine` line-item
  model. Account balances are calculated from posted journal lines rather than
  stored as mutable account state.
- Monetary values use `Decimal`/`DECIMAL(18,2)` paths; float-safety belongs to
  AC2.8 and the decimal safety tests, not to prose-only rules.
- Journal status flow is `draft -> posted -> reconciled|void`; voiding creates a
  reversal entry instead of mutating posted history.
- Multi-currency support lives at journal-line level through `currency` and
  `fx_rate`.
- API walkthroughs from the archive are historical examples. Current endpoint
  behavior is owned by AC2.10 and the API reference docs.

---

## 🔗 Deliverables

- [x] `apps/backend/src/models/account.py` - Account model
- [x] `apps/backend/src/models/journal.py` - JournalEntry & JournalLine models
- [x] `apps/backend/src/ledger/extension/accounting.py` - Accounting service
- [x] `apps/backend/src/routers/accounts.py` - Account API endpoints
- [x] `apps/backend/src/routers/journal.py` - Journal API endpoints
- [x] `apps/backend/src/schemas/account.py` - Account schemas
- [x] `apps/backend/src/schemas/journal.py` - Journal schemas
- [x] `apps/backend/tests/test_accounting.py` - Unit tests
- [x] Update `docs/ssot/schema.md` - ER diagram (implicit via models)
- [x] Update `docs/ssot/accounting.md (retired -> common/ledger/readme.md)` - API documentation (implicit via service)
- [x] `apps/frontend/src/app/(main)/accounts/page.tsx` - Account management
- [x] `apps/frontend/src/app/(main)/journal/page.tsx` - Journal entries

**Implementation Summary**: Current implementation truth is owned by the code paths listed above, [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md), [schema.md](../ssot/schema.md), and the AC2.* tests. Archive implementation notes are historical only and are not part of the active README -> EPIC -> AC -> test chain.

## Framework Boundary

EPIC-002 owns canonical double-entry facts only. Journal entries, account
balances, source links, currency, and Decimal invariants are framework-neutral
inputs to [EPIC-020](EPIC-020.framework-aware-personal-reporting.md). US-like
or HK-like recognition, measurement, classification, presentation, and
disclosure decisions must not be embedded into posting logic.

### AC2.18: Framework-Neutral Ledger Boundary

> Renumbered from a second `AC2.13` group whose first row collided with the
> original User-Scoped Ledger Integrity `AC2.13.*` group (since migrated to
> `AC-ledger.13.*`, #1420 slice 3c-iii); the registry kept the user-scoped row and
> silently dropped this framework-neutral one until the IDs were made unique.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.18.1 | Canonical ledger documentation declares that double-entry posting is framework-neutral and that US/HK policy decisions belong to EPIC-020 | `test_AC2_18_1_canonical_ledger_is_framework_neutral` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

---

## 🧩 Extension: Money value types — narrow waist ([#1167](https://github.com/wangzitian0/finance_report/issues/1167))

> **Status**: 🚧 In Progress (extension; the original EPIC-002 scope above stays ✅ Complete)
> **Tracking**: #1170 (value types + governance), #1171 (adoption), #1172 (narrow-waist CI guard). The L2/L3 score-baseline promotion of the money invariants is tracked in #1103 (descoped from #1172 to avoid destabilizing the behavioral ratchet).

The recent audit cycle showed the arithmetic was never wrong — bugs lived in the
*representation*: a scalar `(opening, closing, currency)` collapsed multi-currency
statements (#1139/#1123), and `float`-for-money was policed only by review. This
extension adds an **application-layer value type** above the DB double-entry
invariant floor (AC2.14): one authoritative `Money` type, a validated `Currency`,
a single `convert()` FX primitive, and a per-currency `CurrencyBalances`
container — so bad money states become *unrepresentable*, not merely
tested-against. Contract: [common/audit/money/readme.md#money-type](https://github.com/wangzitian0/finance_report/blob/main/common/audit/money/readme.md#money-type).

The standard is **cross-language**: `common/audit/money/` holds the language-neutral
**interface** (`contract/money.contract.md`) and **conformance data**
(`conformance/vectors.json`). The Python reference impl (#1170) and the frontend
TS impl (#1171's FE sibling) each load the **same** vectors and must reproduce
every value — so every end stays consistent (this closes the live
banker's-rounding-vs-`decimal.js`-HALF_UP divergence).

> **Dependency note.** `common/` is a repo-root *build-time / test-time* toolkit
> (consumed by `tools/` and tests via the repo root on `sys.path`); it is **not
> packaged into any deployed app image**. The shared artifact is the standard
> (contract + conformance **data**), consumed at test time — not runtime code. So
> each end keeps its own implementation in its own deployable, and backend
> adoption (#1171) needs **no Docker/build-context change**.

### AC2.19: Money / Currency value types — migrated to the `audit` package

> **The Money/Currency value-type ACs of this group are no longer defined
> here.** The float-rejection/Decimal-backing/immutability and cross-currency-
> mismatch rows (were AC2.19.* rows .1–.2) migrated into the `audit` package
> and are owned by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`
> under the package-scoped numeric `AC-audit.<group>.<seq>` id scheme (the
> leading "2" is dropped and the group/seq preserved, so `AC2.19.<s>` becomes
> `AC-audit.19.<s>`). `common/meta/extension/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the
> registry↔EPIC link intact) but defines none of them — the contract is the
> single definition source.
>
> Migrated `AC-audit.19.<s>` ids (homed in the package roadmap):
> `AC-audit.19.1` · `AC-audit.19.2`

### AC2.20: Single FX conversion primitive — migrated to the `audit` package

> **The FX conversion AC of this group is no longer defined here.** The
> `convert()` primitive row (was the AC2.20.* row) migrated into the `audit`
> package and is owned by, and sourced directly from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap` as
> `AC-audit.20.1` (the leading "2" is dropped and the group/seq preserved).

### AC2.21: Per-currency balance container

> **Migrated**: the container's row lives in the audit package roadmap as
> `AC-audit.21.1` — owned by, and sourced from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`.

### AC2.22: Materiality adoption ([#1171](https://github.com/wangzitian0/finance_report/issues/1171))

Route the highest-value call-sites through the value types, behaviour-preserving.
The backend runs its own shippable `src/audit/money` "end" (mirrors `common/audit/money`, kept
in lockstep by the shared conformance vectors + the #1172 guard), because the
backend image does not ship `common/`.

The hot-path arithmetic (reconciliation, reporting net-worth) is routed through
the value types via byte-identical adoption helpers (`src/audit/money/adopt.py`): they
go through `Money`/`convert` when both currencies are valid ISO codes and fall
back to the *identical* Decimal arithmetic for the reconciliation `"*"` sentinel /
non-ISO codes (crypto / withdrawn), so totals are byte-identical for every input
and there is no regression on currencies outside the active ISO set.

> **Migrated**: net-worth restatement via the `convert` primitive moved to the `money`
> package roadmap — its proof is a money-package statement. Owned by, and sourced from,
> [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`.
> *(the remaining 2.21/2.22-group rows migrated to `AC-audit.21.1` / `AC-audit.22.*`; the 22.3 row's canonical copy is `AC-money.22.3` — all in `common/audit/contract.py`)*

> The L2/L3 *score-baseline* promotion of the money invariants stays in #1103.
> The existing reporting net-worth E2E tests (internal-transfer fee / FX ledger)
> double-check the restatement totals end-to-end in CI.

### AC2.23: Narrow-waist CI guard ([#1172](https://github.com/wangzitian0/finance_report/issues/1172))

A CI guard keeps the money standard from eroding: the money modules stay
`float`-free and every stack keeps a conformance suite, so the cross-language
narrow waist cannot silently decay back into ad-hoc money handling.

> **Migrated**: the narrow-waist `float`-ban guard over the money modules moved to the
> `money` package roadmap — its proof is a money-package statement. Owned by, and
> sourced from, [`common/audit/contract.py`](../../common/audit/contract.py)'s `roadmap`.
> *(AC2.23.1 removed — canonical copy is `AC-money.23.1` in `common/audit/contract.py`)*

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| Multi-currency balance conversion | P2 | EPIC-005 |
| Account hierarchy tree | P3 | Future iterations |
| Bulk journal entry import | P3 | Future iterations |

---

## Issues & Gaps

- [x] Data model checklist now matches SSOT fields for `Account`, `JournalEntry`, and `JournalLine` to avoid schema drift.
- [x] Multi-currency clarified: EPIC-002 requires `fx_rate` on non-base currency lines with manual input or market_data lookup; EPIC-005 extends automation.
- [x] JournalLine audit fields aligned with SSOT (added `updated_at`, removed duplicate `updated_at` on JournalEntry).

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../user-guide/accounts.md](../user-guide/accounts.md) — account-management user guide.
- [../user-guide/journal-entries.md](../user-guide/journal-entries.md) — journal-entry user guide.
- [../reference/api.md](../reference/api.md) — generated accounts and journal API reference.

---

## ❓ Q&A (Clarification Required)

### Q1: Account Code Standards
> **Question**: Should we enforce 1xxx-5xxx account codes? Or allow user customization?  
> **Impact**: Affects Account model `code` field validation rules

**✅ Your Answer**: Use canonical framework-neutral account codes, with
framework-specific taxonomy and report-line mapping owned by EPIC-020.

**Current decision**: Account codes are canonical user ledger identifiers, not
the authoritative US GAAP, HKFRS, or CAS taxonomy. Framework-specific report
line mappings are owned by EPIC-020. Frontend lookup can offer familiar code
aliases, but posting and balance validation must remain framework-neutral.

### Q2: Multi-Currency Strategy
> **Question**: Should v1 support multi-currency entries? Or only support single base currency?  
> **Impact**: Affects JournalLine `fx_rate` field usage

**✅ Your Answer**: C - Full multi-currency support, user-configurable base currency

**Decision**: V1 supports full multi-currency from the start
- Account model supports multi-currency configuration
- JournalLine records original currency amount and exchange rate for each line
- User can set personal base currency (default SGD)
- When entry currency != base currency, `fx_rate` is required; API can accept manual input or query `services/market_data/` (automation extended in EPIC-005; rate lookup moves to the `pricing` package under the migration, #1610)
- Reports convert based on user's base currency
- Historical exchange rate records (for retrospective calculations)

### Q3: Draft Entries Balance Counting
> **Question**: Do `draft` status entries affect account balance display?  
> **Impact**: Affects `calculate_account_balance()` logic

**✅ Your Answer**: A - `draft` excluded, only `posted` and `reconciled` counted

**Decision**: Balance calculation only includes posted entries
- `calculate_account_balance()` filter condition: status IN ('posted', 'reconciled')
- Draft entries displayed in frontend as "pending posting", but do not affect balance
- Users can preview draft entries in UI

### Q4: Voided Entry Handling
> **Question**: Void by direct deletion or generate reversal vouchers?  
> **Impact**: Affects audit trail completeness

**✅ Your Answer**: B - Generate reversal vouchers (red entries), automatically generate offsetting entries

**Decision**: Adopt reversal voucher approach (GAAP compliant)
- Calling `void_journal_entry(entry_id)` system automatically generates a reversal voucher
- Reversal voucher all JournalLine opposite direction, same amount
- Original entry status changed to void, linked to reversal voucher ID
- Preserve complete audit trail, comply with financial regulations
- Frontend displays "voided (reversal voucher ID: xxx)"

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Data Model + API skeleton | 16h |
| Week 2 | Business logic + Testing | 20h |
| Week 3 | Frontend UI + Integration | 16h |

**Total Estimate**: 52 hours (3 weeks)
