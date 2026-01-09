# EPIC-002: Double-Entry Bookkeeping Core

> **Status**: 🟡 In Progress  
> **Phase**: 1  
> **Duration**: 3 weeks  
> **Dependencies**: EPIC-001  

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

### Data Model (Backend)

- [ ] `Account` model - Five account types (Asset/Liability/Equity/Income/Expense)
- [ ] `JournalEntry` model - Entry header (date, memo, status, source_type)
- [ ] `JournalLine` model - Entry line (account_id, direction, amount, currency)
- [ ] Alembic migration scripts
- [ ] Pydantic Schema (request/response)

### API Endpoints (Backend)

- [ ] `POST /api/accounts` - Create account
- [ ] `GET /api/accounts` - Account list (with type filter)
- [ ] `GET /api/accounts/{id}` - Account details (with balance)
- [ ] `PUT /api/accounts/{id}` - Update account
- [ ] `POST /api/journal-entries` - Create journal entry (with balance validation)
- [ ] `GET /api/journal-entries` - Journal entry list (pagination, date filter)
- [ ] `GET /api/journal-entries/{id}` - Journal entry details
- [ ] `POST /api/journal-entries/{id}/post` - Post entry (draft → posted)
- [ ] `POST /api/journal-entries/{id}/void` - Void entry (generate reversal entry)

### Business Logic (Backend)

- [ ] `services/accounting.py` - Accounting core
  - [ ] `validate_journal_balance()` - Debit/credit balance validation
  - [ ] `post_journal_entry()` - Posting logic
  - [ ] `calculate_account_balance()` - Account balance calculation
  - [ ] `verify_accounting_equation()` - Accounting equation verification
- [ ] Database constraints - CHECK constraints ensure amount > 0
- [ ] Transaction handling - Journal entry creation must be atomic

### Frontend Interface (Frontend)

- [ ] `/accounts` - Account management page
  - [ ] Account list (grouped by type)
  - [ ] Create account form
  - [ ] Account details sidebar
- [ ] `/journal` - Journal entry management page
  - [ ] Journal entry list (searchable, paginated)
  - [ ] Create journal entry form (dynamically add multiple lines)
  - [ ] Journal entry details modal
  - [ ] Post/void operation buttons

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Accounting equation 100% satisfied** | `verify_accounting_equation()` test | 🔴 Critical |
| **All posted entries balanced** | SQL query verification + Unit tests | 🔴 Critical |
| **No float for monetary amounts** | Code review + grep check | 🔴 Critical |
| Auto-validate balance when creating entry | Unbalanced returns 400 error | Must Have |
| Correct debit/credit direction by account type | Reference accountant.md rules | Must Have |
| Posted entries cannot be edited | Can only void and recreate | Must Have |
| API response time p95 < 200ms | Load testing | Must Have |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Unit test coverage > 90% | coverage report | ⏳ |
| Multi-currency entry support | fx_rate field correctly used | ⏳ |
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

### Unit Tests (Must Have)

```python
# Balance validation
def test_balanced_entry_passes():
    """Balanced debit/credit entries should pass validation"""

def test_unbalanced_entry_fails():
    """Unbalanced entries should be rejected"""

def test_single_line_entry_fails():
    """Single-line entries should be rejected (minimum 2 lines)"""

# Accounting equation
def test_accounting_equation_after_posting():
    """Accounting equation should be satisfied after posting"""

# Amount precision
def test_decimal_precision():
    """Decimal calculations should not lose precision"""

def test_float_rejected():
    """Float type amounts not accepted"""
```

### Integration Tests (Must Have)

```python
def test_create_salary_entry():
    """Salary deposit scenario: Bank DEBIT 5000 / Income CREDIT 5000"""

def test_create_credit_card_payment():
    """Credit card payment scenario: Liability DEBIT 200 / Bank CREDIT 200"""

def test_void_and_reverse():
    """Voided entries should generate reversal vouchers"""

def test_concurrent_posting():
    """Concurrent posting should not cause data inconsistencies"""
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
- [accountant.md](../../.claude/skills/accountant.md) - Typical journal entry mappings

---

## 🔗 Deliverables

- [ ] `apps/backend/src/models/account.py`
- [ ] `apps/backend/src/models/journal.py`
- [ ] `apps/backend/src/services/accounting.py`
- [ ] `apps/backend/src/routers/accounts.py`
- [ ] `apps/backend/src/routers/journal.py`
- [ ] `apps/frontend/app/accounts/page.tsx`
- [ ] `apps/frontend/app/journal/page.tsx`
- [ ] Update `docs/ssot/schema.md` (ER diagram)
- [ ] Update `docs/ssot/accounting.md` (API documentation)

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| Multi-currency balance conversion | P2 | EPIC-005 |
| Account hierarchy tree | P3 | Future iterations |
| Bulk journal entry import | P3 | Future iterations |

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
