# EPIC-002: Double-Entry Bookkeeping Core

> **Status**: 🟡 In Progress 
> **Phase**: 1 
> **Duration**: 3 weeks 
> **Dependencies**: EPIC-001 

---

## 🎯 Objective

Implement compliantAccounting equation double-entry bookkeeping system, support manual journal entriesandaccount management. 

**Core Constraints**:
```
Assets = Liabilities + Equity + (Income - Expenses)
SUM(DEBIT) = SUM(CREDIT) // eachjournal entryRequired
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 📊 **Accountant** | Accounting Correctness | Requiredstrictly follow double-entry bookkeeping rules, the five account types must have correct debit/credit directions |
| 🏗️ **Architect** | Data Model | JournalEntry + JournalLine pattern supports one-to-many, many-to-many scenarios |
| 💻 **Developer** | Implementation Difficulty | use Decimal instead of float, transactions ensure atomicity |
| 🧪 **Tester** | Validation Strategy | 100% coverage ofBalance validationlogic, Boundary Tests (extreme amounts, cross-currency) |
| 📋 **PM** | User Value | manual bookkeeping capability is the foundation for subsequent automation foundation, Priorityhighest |

---

## ✅ Task Checklist

### Data Model (Backend)

- [ ] `Account` model - five account types (Asset/Liability/Equity/Income/Expense)
- [ ] `JournalEntry` model - voucherheader (date, memo, status, source_type)
- [ ] `JournalLine` model - journal entry (account_id, direction, amount, currency)
- [ ] Alembic migration
- [ ] Pydantic Schema (request/ should)

### API endpoint (Backend)

- [ ] `POST /api/accounts` - createaccount
- [ ] `GET /api/accounts` - accounttable (support type excessively )
- [ ] `GET /api/accounts/{id}` - account (containbalance)
- [ ] `PUT /api/accounts/{id}` - updateaccount
- [ ] `POST /api/journal-entries` - createjournal entry (containBalance validation)
- [ ] `GET /api/journal-entries` - journal entrytable (pagination, date excessively )
- [ ] `GET /api/journal-entries/{id}` - journal entry
- [ ] `POST /api/journal-entries/{id}/post` - excessively (draft → posted)
- [ ] `POST /api/journal-entries/{id}/void` - (generatejournal entry)

### logic (Backend)

- [ ] `services/accounting.py` - bookkeeping
 - [ ] `validate_journal_balance()` - debitcreditBalance validation
 - [ ] `post_journal_entry()` - excessively logic
 - [ ] `calculate_account_balance()` - accountbalancecalculate
 - [ ] `verify_accounting_equation()` - Accounting equationvalidate
- [ ] databaseconstraint - CHECK constraintensureamount > 0
- [ ] transactionprocess - journal entrycreateRequired

### Frontend (Frontend)

- [ ] `/accounts` - account managementpage
 - [ ] accounttable (classminutes)
 - [ ] createaccountform
 - [ ] account
- [ ] `/journal` - journal entrypage
 - [ ] journal entrytable (can search, pagination)
 - [ ] createjournal entryform (dynamic)
 - [ ] journal entry
 - [ ] excessively /

---

## 📏 good not good standard

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Accounting equation 100% ** | `verify_accounting_equation()` test | 🔴 critical |
| ** have/has posted journal entrydebitcredit** | SQL queryvalidate + Unit tests | 🔴 critical |
| **prohibit float amount** | codereview + grep check | 🔴 critical |
| createjournal entryvalidate | not 400 incorrect | Required |
| accountclassdebitcreditcorrect | accountant.md then | Required |
| excessively not can edit | only can void redo | Required |
| API should time p95 < 200ms | test | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Unit testscoverage of > 90% | coverage report | ⏳ |
| supportjournal entry | fx_rate fieldcorrectuse | ⏳ |
| account codessupport (1xxx-5xxx) | code fieldimplementation | ⏳ |
| journal entry can | use journal entrycreate | ⏳ |
| FrontendBalance validation | inputdebitcredit | ⏳ |

### 🚫 Not Acceptable Signals

- posted journal entry in/at debitcredit not 
- Accounting equation not 
- use float amount
- excessively journal entry be (passive) modify
- API 500 incorrect

---

## 🧪 Test Scenarios

### Unit tests (Required)

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

### Integration tests (Required)

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

### Boundary Tests (Recommended)

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

- [schema.md](../ssot/schema.md) - databasetable
- [accounting.md](../ssot/accounting.md) - will then 
- [accountant.md](../../.claude/skills/accountant.md) - journal entry

---

## 🔗 Deliverables

- [ ] `apps/backend/src/models/account.py`
- [ ] `apps/backend/src/models/journal.py`
- [ ] `apps/backend/src/services/accounting.py`
- [ ] `apps/backend/src/routers/accounts.py`
- [ ] `apps/backend/src/routers/journal.py`
- [ ] `apps/frontend/app/accounts/page.tsx`
- [ ] `apps/frontend/app/journal/page.tsx`
- [ ] update `docs/ssot/schema.md` (ER )
- [ ] update `docs/ssot/accounting.md` (API )

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| balance | P2 | EPIC-005 |
| account codehierarchy | P3 | |
| journal entryimport | P3 | |

---

## ❓ Q&A (Clarification Required)

### Q1: accountspecification
> **Question**: Should we enforce 1xxx-5xxx account codes? or allow user customization? 
> **Impact**: Impact Account model `code` field validate then 

**✅ Your Answer**: use US GAAP Taxonomy standard

**Decision**: Adopt US GAAP Taxonomy standard coding
- Follow international financial reporting standards
- Account model `code` fieldRequiredcomply GAAP Taxonomy
- Frontend provides code lookup/selection tool
- Support custom aliases (user-friendly name)

### Q2: processstrategy
> **Question**: Should v1 support multi-currency entries? or only support single base currency? 
> **Impact**: Impact JournalLine `fx_rate` fielduse

**✅ Your Answer**: C - Full multi-currency support, user-configurable base currency

**Decision**: V1 supports full multi-currency from the start
- Account modelsupportconfiguration
- JournalLine each all amountandexchange rate
- User can set personal base currency (default SGD)
- Reports convert based on user's base currency
- Historical exchange rate records (for retrospective calculations)

### Q3: journal entry is no countedbalance
> **Question**: `draft` Status journal entry is no Impactaccountbalance? 
> **Impact**: Impact `calculate_account_balance()` logic

**✅ Your Answer**: A - `draft` excluded, only `posted` and `reconciled` counted

**Decision**: balancecalculateOnly include posted entries
- `calculate_account_balance()` Filter condition: status IN ('posted', 'reconciled')
- Draft entries displayed in frontend as"pending posting", but not Impactbalance
- use Can preview draft entries in UI

### Q4: journal entry process
> **Question**: Void by direct deletion or generate reversal vouchers? 
> **Impact**: Impactlog complete

**✅ Your Answer**: B - Generate reversal vouchers (red entries), automatically generate offsetting entries

**Decision**: Adopt reversal voucher approach (GAAP compliant)
- Call `void_journal_entry(entry_id)` system automatically generates a reversal voucher
- reversal voucherAll JournalLine opposite direction, same amount
- Original entry status changed to void, linked to reversal voucher ID
- Preserve complete audit trail, comply with financial regulations
- Frontend displays"voided (reversal voucher ID: xxx)"

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Data Model + API | 16h |
| Week 2 | logic + test | 20h |
| Week 3 | Frontend + | 16h |

****: 52 hours (3 weeks)
