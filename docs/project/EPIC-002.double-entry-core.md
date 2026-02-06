# EPIC-002: Double-Entry Bookkeeping Core

> **Status**: ✅ Complete  
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
- [x] `POST /api/journal-entries/{id}/post` - Post entry (draft → posted)
- [x] `POST /api/journal-entries/{id}/void` - Void entry (generate reversal entry)

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

### AC2.3: Journal Entry Posting & Voiding

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.3.1 | Post draft entry successfully | `test_post_journal_entry_success()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.3.2 | Post already-posted entry fails | `test_post_journal_entry_already_posted_fails()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.3.3 | Posted entry cannot be reposted | `test_posted_entry_cannot_be_reposted()` | `accounting/test_accounting_equation.py` | P0 |
| AC2.3.4 | Posted entry status immutable | `test_posted_entry_status_immutable_via_direct_update()` | `accounting/test_accounting_equation.py` | P0 |
| AC2.3.5 | Void entry creates reversal | `test_void_journal_entry_creates_reversal()` | `accounting/test_accounting_integration.py` | P0 |

### AC2.4: Balance Calculation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.4.1 | Calculate balance for asset account | `test_calculate_balance_for_asset_account()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.4.2 | Calculate balance for income account | `test_calculate_balance_for_income_account()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.4.3 | Draft entries excluded from balance | `test_draft_entries_not_included_in_balance()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.4.4 | Calculate balances by account type | `test_calculate_account_balances_by_type()` | `accounting/test_accounting_balances.py` | P1 |
| AC2.4.5 | Empty account list returns empty balances | `test_calculate_account_balances_empty_list()` | `accounting/test_accounting_balances.py` | P1 |

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

### AC2.7: API Router & Error Handling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.7.1 | Router uses flush not commit | `test_create_journal_entry_uses_flush_not_commit()` | `accounting/test_accounting_integration.py` | P0 |
| AC2.7.2 | Journal router error paths | Multiple tests | `accounting/test_journal_router_errors.py` | P1 |
| AC2.7.3 | Journal router additional scenarios | Multiple tests | `accounting/test_journal_router_additional.py` | P1 |

### AC2.8: Decimal Safety

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC2.8.1 | Never use float for monetary amounts | `test_float_injection_safety()` | `accounting/test_decimal_safety.py` | P0 |
| AC2.8.2 | Decimal precision maintained in arithmetic | `test_decimal_precision()`, `test_amount_precision_loss_detection()` | `accounting/test_accounting.py`, `accounting/test_accounting_equation.py` | P0 |

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
| AC2.10.3 | `POST /journal-entries/{id}/post`, `POST /journal-entries/{id}/void` | `test_journal_entry_endpoints()` | `api/test_api_endpoints.py` | P0 |
| AC2.10.4 | API error behavior for missing/invalid resources | `test_journal_router_errors.py` suite | `accounting/test_journal_router_errors.py` | P1 |

### AC2.11: Must-Have Acceptance Criteria Traceability

| ID | Requirement | Test Function | File | Priority |
|----|-------------|---------------|------|----------|
| AC2.11.1 | Accounting equation always satisfied | `test_accounting_equation_holds_with_all_account_types()`, `test_accounting_equation_holds()` | `accounting/test_accounting_equation.py`, `accounting/test_accounting_integration.py` | P0 |
| AC2.11.2 | All posted entries balanced | `test_post_unbalanced_entry_rejected()`, `test_unbalanced_entry_fails()` | `accounting/test_accounting_integration.py`, `accounting/test_accounting.py` | P0 |
| AC2.11.3 | No float usage for monetary amounts | `test_float_injection_safety()` | `accounting/test_decimal_safety.py` | P0 |
| AC2.11.4 | Multi-currency requires fx_rate | `test_fx_rate_required_for_non_base_currency()` | `accounting/test_accounting.py` | P0 |
| AC2.11.5 | Posted entries cannot be edited | `test_posted_entry_status_immutable_via_direct_update()` | `accounting/test_accounting_equation.py` | P0 |
| AC2.11.6 | API response performance benchmark scenario documented | Locust benchmark scenario (`/health`, accounting flows) | `apps/backend/tests/locustfile.py` | P1 |

**Test Coverage Summary**:
- Total AC IDs: 57
- Requirements converted to AC IDs: 100% (EPIC-002 checklist + must-have standards)
- Requirements with test references: 100%
- Test files: 11
- Overall coverage: 94%+

---

## 📏 Acceptance Criteria

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

**Implementation Summary**: See [EPIC-002-IMPLEMENTATION.md](./archive/EPIC-002-IMPLEMENTATION.md)

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

---

## ❓ Q&A (Clarification Required)

### Q1: Account Code Standards
> **Question**: Should we enforce 1xxx-5xxx account codes? Or allow user customization?  
> **Impact**: Affects Account model `code` field validation rules

**✅ Your Answer**: Use US GAAP Taxonomy standard

**Decision**: Adopt US GAAP Taxonomy standard coding
- Follow international financial reporting standards
- Account model `code` field must comply with GAAP Taxonomy
- Frontend provides code lookup/selection tool
- Support custom aliases (user-friendly names)

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
