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

- [x] `services/accounting.py` - Accounting core
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

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See test files in `apps/backend/tests/accounting/`

### AC2.1: Account Management

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.1.1 | Create account with valid data | `test_create_account()` | `accounting/test_account_service_unit.py` | P0 |
| AC2.1.2 | Get account by ID | `test_get_account_success()` | `accounting/test_account_service_unit.py` | P0 |
| AC2.1.3 | Get non-existent account fails | `test_get_account_not_found()` | `accounting/test_account_service_unit.py` | P0 |
| AC2.1.4 | Update account successfully | `test_update_account_success()` | `accounting/test_account_service_unit.py` | P0 |
| AC2.1.5 | Update non-existent account fails | `test_update_account_not_found()` | `accounting/test_account_service_unit.py` | P0 |
| AC2.1.6 | List accounts with filters | `test_list_accounts_with_filters()` | `accounting/test_account_service_unit.py` | P1 |

### AC2.2: Journal Entry Creation & Validation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.2.1 | Balanced entry passes validation | `test_balanced_entry_passes()` | `accounting/test_accounting.py` | P0 |
| AC2.2.2 | Unbalanced entry fails validation | `test_unbalanced_entry_fails()` | `accounting/test_accounting.py` | P0 |
| AC2.2.3 | Single-line entry fails (minimum 2 lines) | `test_single_line_entry_fails()` | `accounting/test_accounting.py` | P0 |
| AC2.2.4 | Decimal precision maintained | `test_decimal_precision()` | `accounting/test_accounting.py` | P0 |
| AC2.2.5 | FX rate required for non-base currency | `test_fx_rate_required_for_non_base_currency()` | `accounting/test_accounting.py` | P0 |
| AC2.2.6 | Unbalanced post attempt fails | `test_post_unbalanced_entry_rejected()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.2.7 | Balance validation treats omitted currency as base currency | `test_missing_currency_balances_as_base_currency()` | `accounting/test_accounting.py` | P0 |

### AC2.3: Journal Entry Posting & Voiding

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.3.1 | Post draft entry successfully | `test_post_journal_entry_success()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.3.2 | Post already-posted entry fails | `test_post_journal_entry_already_posted_fails()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.3.3 | Posted entry cannot be reposted | `test_posted_entry_cannot_be_reposted()` | `accounting/test_accounting_equation.py` | P0 |
| AC2.3.4 | Posted entry status immutable | `test_posted_entry_status_immutable_via_direct_update()` | `accounting/test_accounting_equation.py` | P0 |
| AC2.3.5 | Void entry creates reversal | `test_void_journal_entry_creates_reversal()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.3.6 | Error handling for non-existent entries | `test_journal_service` | `accounting/test_journal_service.py` | P1 |
| AC2.3.7 | create_entry ValidationError catch (unbalanced, single-line) | `test_journal_delete_and_validation` | `accounting/test_journal_delete_and_validation.py` | P1 |
| AC2.3.8 | post_journal_entry error handling (not found, wrong user, inactive account) | `test_accounting_service_errors` | `accounting/test_accounting_service_errors.py` | P1 |
| AC2.3.9 | void_journal_entry error handling (not found, wrong user, non-posted) | `test_accounting_service_errors` | `accounting/test_accounting_service_errors.py` | P1 |
| AC2.3.10 | post_journal_entry success path | `test_accounting_service_errors` | `accounting/test_accounting_service_errors.py` | P1 |
| AC2.3.11 | void_journal_entry success path with reversal | `test_accounting_service_errors` | `accounting/test_accounting_service_errors.py` | P1 |

### AC2.4: Balance Calculation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.4.1 | Calculate balance for asset account | `test_calculate_balance_for_asset_account()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.4.2 | Calculate balance for income account | `test_calculate_balance_for_income_account()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.4.3 | Draft entries excluded from balance | `test_draft_entries_not_included_in_balance()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.4.4 | Calculate balances by account type | `test_calculate_account_balances_by_type()` | `accounting/test_accounting_balances.py` | P1 |
| AC2.4.5 | Empty account list returns empty balances | `test_calculate_account_balances_empty_list()` | `accounting/test_accounting_balances.py` | P1 |
| AC2.4.6 | Account Balance Calculation Tests | `test_accounting_balances` | `accounting/test_accounting_balances.py` | P1 |

### AC2.5: Accounting Equation Validation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.5.1 | Accounting equation holds with all types | `test_accounting_equation_holds_with_all_account_types()` | `accounting/test_accounting_equation.py` | P0 |
| AC2.5.2 | Equation violation detected | `test_accounting_equation_violation_detected()` | `accounting/test_accounting_equation.py` | P0 |
| AC2.5.3 | Accounting equation holds after transactions | `test_accounting_equation_holds()` | `accounting/test_accounting_integration.py` | P0 |

### AC2.6: Boundary & Edge Cases

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.6.1 | Maximum amount (999,999,999.99) | `test_max_amount_boundary()` | `accounting/test_accounting_equation.py` | P1 |
| AC2.6.2 | Minimum amount (0.01) | `test_min_amount_boundary()` | `accounting/test_accounting_equation.py` | P1 |
| AC2.6.3 | Decimal precision loss detection | `test_amount_precision_loss_detection()` | `accounting/test_accounting_equation.py` | P1 |
| AC2.6.4 | Many-line complex entry (salary breakdown) | `test_many_lines_complex_salary_correct()` | `accounting/test_accounting_equation.py` | P1 |

### AC2.17: Account Management UI Responsiveness

> Renumbered from a second `AC2.12` group that collided with AC2.12 (Multi-Currency
> Ledger Integrity); the AC IDs are unique, the namespaces were not.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.17.1 | Accounts page mobile filters and account rows avoid document-level horizontal scroll and content overlap | `AC2.17.1 mobile accounts avoids document horizontal scroll and overlapping row controls` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 |

### AC2.7: API Router & Error Handling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.7.1 | Router uses flush not commit | `test_create_journal_entry_uses_flush_not_commit()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.7.2 | Journal router error paths | Multiple tests | `accounting/test_journal_router_errors.py` | P1 |
| AC2.7.3 | Journal router additional scenarios | Multiple tests | `accounting/test_journal_router_additional.py` | P1 |
| AC2.7.4 | Validation error (422) for malformed request | `test_journal_router_additional` | `accounting/test_journal_router_additional.py` | P1 |
| AC2.7.5 | DELETE /{entry_id} endpoint (success, not-found, non-draft) | `test_journal_delete_and_validation` | `accounting/test_journal_delete_and_validation.py` | P1 |
| AC2.7.6 | Test voiding a journal entry. | `test_void_journal_entry` | `api/test_journal_router.py` | P1 |
| AC2.7.7 | Test deleting a journal entry (only drafts can be deleted). | `test_delete_journal_entry` | `api/test_journal_router.py` | P1 |

### AC2.8: Decimal Safety

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.8.1 | Never use float for monetary amounts | `test_float_injection_safety()` | `accounting/test_decimal_safety.py` | P0 |
| AC2.8.2 | Decimal precision maintained in arithmetic | `test_decimal_precision()`, `test_amount_precision_loss_detection()` | `accounting/test_accounting.py`, `accounting/test_accounting_equation.py` | P0 |
| AC2.8.3 | Scientific notation handling | `test_decimal_safety` | `accounting/test_decimal_safety.py` | P1 |

### AC2.9: Data Model Checklist Coverage

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC2.9.1 | Account model supports required fields and types | `test_create_account()`, `test_update_account_success()` | `accounting/test_account_service_unit.py` | P0 |
| AC2.9.2 | JournalEntry model supports required fields and status flow | `test_posted_entry_cannot_be_reposted()`, `test_void_journal_entry_creates_reversal()` | `accounting/test_accounting_equation.py`, `accounting/test_accounting_integration.py` | P0 |
| AC2.9.3 | JournalLine enforces debit/credit + amount rules | `test_single_line_entry_fails()`, `test_unbalanced_entry_fails()`, `test_journal_line_amount_must_be_positive()` | `accounting/test_accounting.py`, `api/test_schemas.py` | P0 |
| AC2.9.4 | Pydantic account/journal schemas validated | `TestAccountSchemas`, `TestJournalLineSchemas`, `TestJournalEntrySchemas` | `api/test_schemas.py` | P1 |

### AC2.10: API Endpoint Checklist Coverage

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC2.10.1 | `POST /accounts`, `GET /accounts`, `GET /accounts/{id}`, `PUT /accounts/{id}` | `test_accounts_endpoints()` | `api/test_api_endpoints.py` | P0 |
| AC2.10.2 | `POST /journal-entries`, `GET /journal-entries`, `GET /journal-entries/{id}` | `test_journal_entry_endpoints()` | `api/test_api_endpoints.py` | P0 |
| AC2.10.3 | `POST /journal-entries/{id}/postings`, `POST /journal-entries/{id}/voidings` | `test_journal_entry_endpoints()` | `api/test_api_endpoints.py` | P0 |
| AC2.10.4 | API error behavior for missing/invalid resources | `test_journal_router_errors.py` suite | `accounting/test_journal_router_errors.py` | P1 |
| AC2.10.5 | DELETE /statements/{id} success | `test_delete_endpoints` | `accounting/test_delete_endpoints.py` | P1 |

### AC2.11: Must-Have Acceptance Criteria Traceability
| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC2.11.4 | Multi-currency requires fx_rate | `test_fx_rate_required_for_non_base_currency()` | `accounting/test_accounting.py` | P0 |

### AC2.12: Multi-Currency Ledger Integrity

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.12.1 | Journal entry balance validation uses base-currency converted amounts when line currencies differ | `test_AC2_12_1_multicurrency_entry_balances_in_base_currency()` | `accounting/test_multicurrency_integrity.py` | P0 |
| AC2.12.2 | Accounting equation verification uses base-currency converted account balances | `test_AC2_12_2_accounting_equation_uses_base_currency_balances()` | `accounting/test_multicurrency_integrity.py` | P0 |
| AC2.12.6 | Statement validation logic rejects invalid statement balance and transaction states | `test_validation.py` suite | `accounting/test_validation.py` | P0 |
| AC2.12.5 | Stream redactor accumulates small chunks in buffer | `test_stream_redactor_small_chunks` | `infra/test_infra_edge_cases.py` | P1 |

### AC2.13: User-Scoped Ledger Integrity

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.13.1 | Manual journal creation rejects lines using another user's account | `test_AC2_13_1_create_journal_entry_rejects_cross_user_account()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.13.2 | Posting validates that every line account belongs to the entry owner | `test_AC2_13_2_post_journal_entry_rejects_cross_user_account()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.13.3 | Balance aggregation requires account and entry ownership to match | `test_AC2_13_3_balance_queries_ignore_cross_user_entry_headers()` | `accounting/test_accounting_integration.py` | P0 |

### AC2.14: Database Ledger Invariant Floor

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.14.1 | PostgreSQL rejects posted/reconciled entries with fewer than two lines even when service validation is bypassed | `test_AC2_14_1_posted_entry_requires_two_lines_at_database_boundary()` | `accounting/test_ledger_schema_invariants.py` | P0 |
| AC2.14.2 | PostgreSQL rejects posted/reconciled entries whose debits and credits do not balance after base-currency conversion | `test_AC2_14_2_posted_entry_must_balance_in_base_currency()` | `accounting/test_ledger_schema_invariants.py` | P0 |
| AC2.14.3 | PostgreSQL rejects posted/reconciled non-base-currency lines without a positive FX rate | `test_AC2_14_3_non_base_posted_lines_require_positive_fx_rate()` | `accounting/test_ledger_schema_invariants.py` | P0 |
| AC2.14.4 | PostgreSQL blocks direct update/delete of posted/reconciled entries and lines while draft entries remain editable | `test_AC2_14_4_posted_entries_and_lines_are_immutable_but_drafts_are_editable()` | `accounting/test_ledger_schema_invariants.py` | P0 |
| AC2.14.5 | Voiding a posted entry preserves a non-null immutable reversal relationship instead of deleting or editing posted lines | `test_AC2_14_5_void_transition_requires_reversal_relationship()` | `accounting/test_ledger_schema_invariants.py` | P0 |
| AC2.14.6 | Account deletion blocked by the immutability invariant (posted/reconciled entries) returns a clean HTTP 409, not a leaked 500 | `test_delete_user_with_immutable_entries_returns_409()` | `apps/backend/tests/api/test_users_router.py` | P1 |

### AC2.15: Guided Opening Balances ([#949](https://github.com/wangzitian0/finance_report/issues/949))

A user with pre-existing assets/liabilities can establish year-start balances via one guided request, so a cross-year balance sheet is complete from the start instead of silently omitting the opening position.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.15.1 | `POST /api/accounts/opening-balances` posts one balanced entry that increases each account to its opening balance on its normal side and offsets the net into a system Opening Balance Equity account; the as-of balance sheet reflects the starting position with the accounting equation intact | `test_AC2_15_1_opening_balances_post_balanced_and_reflect_in_balance_sheet` | `accounting/test_opening_balance.py` | P0 |
| AC2.15.2 | A single asset opening balance offsets entirely into Opening Balance Equity, keeping the entry balanced | `test_AC2_15_2_single_asset_opening_balance_offsets_into_equity` | `accounting/test_opening_balance.py` | P0 |
| AC2.15.3 | An opening balance for a non-owned or unknown account is rejected | `test_AC2_15_3_unknown_account_is_rejected` | `accounting/test_opening_balance.py` | P0 |
| AC2.15.4 | An opening balance establishes a starting position, not a delta: it is rejected when an affected account already has posted activity before the opening date | `test_AC2_15_4_opening_balance_rejected_when_prior_activity_exists` | `accounting/test_opening_balance.py` | P0 |
| AC2.15.5 | Opening balances are accepted only in the base currency, with a clear error rather than a confusing FX-rate failure | `test_AC2_15_5_non_base_currency_is_rejected` | `accounting/test_opening_balance.py` | P0 |
| AC2.15.6 | An opening balance into an account whose currency differs from the request currency is rejected, so journal lines cannot be mis-stamped | `test_AC2_15_6_account_currency_mismatch_is_rejected` | `accounting/test_opening_balance.py` | P0 |
| AC2.15.7 | Opening balances may only target user-managed accounts; a system account (e.g. Processing) cannot be set via this endpoint even though the entry is SYSTEM-typed | `test_AC2_15_7_system_account_target_is_rejected` | `accounting/test_opening_balance.py` | P0 |
| AC2.15.8 | The Accounts page offers a guided opening-balance flow: a non-accountant enters an as-of date and a starting balance per eligible (active, non-income/expense) account, and the UI posts the balances map to `POST /api/accounts/opening-balances` — never hand-written journal lines — validating positive two-decimal amounts and surfacing backend errors instead of silently closing | `AC2.15.8 lists only eligible accounts and hides income/expense and inactive ones`, `AC2.15.8 posts a balances map without requiring hand-written journal lines`, `AC2.15.8 blocks submission until at least one positive balance is entered`, `AC2.15.8 rejects non-positive or over-precise amounts before calling the API`, `AC2.15.8 surfaces a backend error instead of closing` | `apps/frontend/src/__tests__/openingBalanceModal.test.tsx` | P1 |

### AC2.16: Opening-Balance Readiness Nudge ([#949](https://github.com/wangzitian0/finance_report/issues/949))

The everyday-user persona who already owns assets/liabilities on day one can post
real activity without ever recording a starting position, yielding a balance
sheet that looks right but silently omits the opening balances. These ACs surface
that gap before the numbers are trusted.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.16.1 | `get_opening_balance_readiness` reports `needs_opening_balance=True` only when the user has posted activity and no opening-balance entry on or before its earliest date (no activity, an opening entry before activity, or a mis-dated opening entry after activity are all distinguished) | `test_AC2_16_1_no_activity_does_not_need_opening_balance`, `test_AC2_16_1_activity_without_opening_entry_needs_opening_balance`, `test_AC2_16_1_opening_entry_before_activity_clears_the_nudge`, `test_AC2_16_1_opening_entry_after_activity_still_needs` | `apps/backend/tests/accounting/test_opening_balance_readiness.py` | P1 |
| AC2.16.2 | `GET /api/accounts/opening-balance-readiness` exposes the readiness signal to the UI | `test_AC2_16_2_readiness_endpoint_returns_status` | `apps/backend/tests/accounting/test_opening_balance_readiness.py` | P1 |
| AC2.16.3 | The Accounts page shows a warning nudge (with a CTA that opens the guided flow) when opening balances are missing, and hides it once they are recorded | `AC2.16.3 shows a readiness nudge and opens the modal when opening balances are missing`, `AC2.16.3 hides the readiness nudge when opening balances are already recorded` | `apps/frontend/src/__tests__/accountsPage.test.tsx` | P1 |

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
| Correct debit/credit direction by account type | Reference `accounting.md` rules | Must Have |
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
src/services/accounting.py      91%
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
- [accounting.md](../ssot/accounting.md) - Accounting rules

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
- [x] `apps/backend/src/services/accounting.py` - Accounting service
- [x] `apps/backend/src/routers/accounts.py` - Account API endpoints
- [x] `apps/backend/src/routers/journal.py` - Journal API endpoints
- [x] `apps/backend/src/schemas/account.py` - Account schemas
- [x] `apps/backend/src/schemas/journal.py` - Journal schemas
- [x] `apps/backend/tests/test_accounting.py` - Unit tests
- [x] Update `docs/ssot/schema.md` - ER diagram (implicit via models)
- [x] Update `docs/ssot/accounting.md` - API documentation (implicit via service)
- [x] `apps/frontend/src/app/(main)/accounts/page.tsx` - Account management
- [x] `apps/frontend/src/app/(main)/journal/page.tsx` - Journal entries

**Implementation Summary**: Current implementation truth is owned by the code paths listed above, [accounting.md](../ssot/accounting.md), [schema.md](../ssot/schema.md), and the AC2.* tests. Archive implementation notes are historical only and are not part of the active README -> EPIC -> AC -> test chain.

## Framework Boundary

EPIC-002 owns canonical double-entry facts only. Journal entries, account
balances, source links, currency, and Decimal invariants are framework-neutral
inputs to [EPIC-020](EPIC-020.framework-aware-personal-reporting.md). US-like
or HK-like recognition, measurement, classification, presentation, and
disclosure decisions must not be embedded into posting logic.

### AC2.18: Framework-Neutral Ledger Boundary

> Renumbered from a second `AC2.13` group whose `AC2.13.1` collided with AC2.13.1
> (User-Scoped Ledger Integrity); the registry kept the user-scoped row and
> silently dropped this framework-neutral one until the IDs were made unique.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.18.1 | Canonical ledger documentation declares that double-entry posting is framework-neutral and that US/HK policy decisions belong to EPIC-020 | `test_AC2_18_1_canonical_ledger_is_framework_neutral` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

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
- When entry currency != base currency, `fx_rate` is required; API can accept manual input or query `services/market_data.py` (automation extended in EPIC-005)
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
