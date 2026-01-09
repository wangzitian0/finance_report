# EPIC-003: Smart Statement Parsing

> **Status**: ⏳ Pending 
> **Phase**: 2 
> **Duration**: 4 weeks 
> **Dependencies**: EPIC-002 

---

## 🎯 Objective

use Gemini 3 Flash Vision parsebank/ for , generatejournal entry. 

**process**:
```
Upload → Gemini Vision → JSON → Validation → BankStatementTransaction → JournalEntry
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | design | AI only parse, not , excessively validate excessively incorrect |
| 💻 **Developer** | API | Gemini 3 Flash Call, containretry, downgrade, |
| 📊 **Accountant** | complete | + transaction ≈ , validate not excessively then reject |
| 🔗 **Reconciler** | Dependencies | parseRequired, matchuse |
| 🧪 **Tester** | parseaccurate | bank, coverage oftest, ≥ 95% |
| 📋 **PM** | use body | upload, parse, incorrectnoticegood |

---

## ✅ Task Checklist

### Data Model (Backend)

- [ ] `BankStatement` model - for header (account_id, period, opening/closing_balance)
- [ ] `BankStatementTransaction` model - (txn_date, amount, direction, description)
- [ ] Alembic migration
- [ ] Pydantic Schema

### Gemini (Backend)

- [ ] `services/extraction.py` - documentparseservice
 - [ ] `parse_pdf()` - PDF parse (Vision API)
 - [ ] `parse_csv()` - CSV parse ( then + AI )
 - [ ] `parse_xlsx()` - Excel parse
- [ ] Prompt 
 - [ ] DBS/POSB for 
 - [ ] OCBC for 
 - [ ] use use 
- [ ] parse
 ```python
 class ParsedStatement:
 bank_name: str
 account_number: str # 4
 period_start: date
 period_end: date
 opening_balance: Decimal
 closing_balance: Decimal
 transactions: list[ParsedTransaction]
 ```

### validate (Backend)

- [ ] `services/validation.py` - validateservice
 - [ ] `validate_balance()` - + transaction ≈ (tolerance 0.1 USD)
 - [ ] `validate_completeness()` - requiredfieldcheck
 - [ ] `detect_duplicates()` - import
- [ ] validatefailureprocess
 - [ ] as/for " need "
 - [ ] failureRationale
 - [ ] notification use 

### API endpoint (Backend)

- [ ] `POST /api/statements/upload` - upload
- [ ] `GET /api/statements` - for table
- [ ] `GET /api/statements/{id}` - for (contain)
- [ ] `POST /api/statements/{id}/approve` - confirmation for 
- [ ] `POST /api/statements/{id}/reject` - reject for 
- [ ] `GET /api/statements/{id}/transactions` - table

### Frontend (Frontend)

- [ ] `/upload` - uploadpage
 - [ ] uploadcomponent
 - [ ] class/validate
 - [ ] upload
 - [ ] parseStatus
- [ ] `/statements` - for 
 - [ ] for table (Statustag)
 - [ ] for (table)
 - [ ] parse
 - [ ] confirmation/reject
- [ ] incorrectprocess
 - [ ] parsefailurenotice
 - [ ] validatefailure
 - [ ] retry

---

## 📏 good not good standard

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **parsesuccess ≥ 95%** | 10 for test | 🔴 critical |
| **balancevalidate 100% ** | +transaction≈check | 🔴 critical |
| **parseincorrect not ** | validatefailureincorrect | 🔴 critical |
| support PDF (DBS, OCBC) | banktest | Required |
| support CSV use | standard CSV test | Required |
| limitation 10MB | uploadvalidate | Required |
| parsetime < 30s | can test | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| support XLSX | Excel test | ⏳ |
| parse can edit | Frontendtableedit | ⏳ |
| upload | queueprocess | ⏳ |
| parsecache | not Call API | ⏳ |
| Gemini | Token usestatistics | ⏳ |

### 🚫 Not Acceptable Signals

- parsesuccess < 90%
- balancevalidate be (passive) excessively 
- parseincorrect
- Gemini API timeout
- use no/none incorrectRationale

---

## 🧪 Test Scenarios

### Unit tests (Required)

```python
# balancevalidate
def test_balance_validation_passes():
 """ 1000 + transaction 500 - 300 = 1200"""

def test_balance_validation_fails():
 """ 1000 + transaction 500 ≠ 1600"""

# parse
def test_parse_dbs_pdf():
 """DBS reconciliationparse, fieldcomplete"""

def test_parse_invalid_pdf():
 """reconciliation PDF parsefailure"""
```

### Integration tests (Required)

```python
def test_upload_and_parse_flow():
 """completeupload→parse→verification→process"""

def test_duplicate_upload_detection():
 """uploadnotice"""

def test_gemini_retry_on_timeout():
 """Gemini timeoutretry"""
```

### coverage of (Required)

| bank | | | accurate |
|------|------|--------|------------|
| DBS/POSB | PDF | 3 | ≥ 95% |
| OCBC | PDF | 2 | ≥ 95% |
| use | PDF | 3 | ≥ 90% |
| use | CSV | 2 | ≥ 98% |

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - BankStatement/BankStatementTransaction table
- [extraction.md](../ssot/extraction.md) - parse then and Prompt design

---

## 🔗 Deliverables

- [ ] `apps/backend/src/models/statement.py`
- [ ] `apps/backend/src/services/extraction.py`
- [ ] `apps/backend/src/services/validation.py`
- [ ] `apps/backend/src/routers/statements.py`
- [ ] `apps/frontend/app/upload/page.tsx`
- [ ] `apps/frontend/app/statements/page.tsx`
- [ ] update `docs/ssot/extraction.md` (Prompt )
- [ ] test `tests/fixtures/statements/`

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| PDF parsedowngrade | P2 | |
| more banksupport (UOB, Citi) | P3 | |
| OCR process () | P3 | |

---

## ❓ Q&A (Clarification Required)

### Q5: support bankPriority
> **Question**: need need to support which bank for ? 

**✅ Your Answer**: DBS + bank + Maybank + Wise, still/also need support, etc. each. use use + extensionfield design. 

**Decision**: use high can extension for model
- **field** ( have/has for ):
 - `period_start`, `period_end`, `opening_balance`, `closing_balance`
 - `transactions[]` containstandardfield: `txn_date`, `amount`, `direction`, `description`
- **extensionfield** (JSONB):
 - `bank_specific_data`: bank have/has field (such as , etc.)
 - `institution_type`: class (bank, brokerage, insurance, wallet etc.)
 - `custom_fields`: use can customfield
- **Prompt **classminutes:
 - `templates/dbs.yaml`
 - `templates/ocbc.yaml`
 - `templates/citic.yaml`
 - `templates/brokerage_generic.yaml`
 - `templates/insurance_generic.yaml`
 - `templates/fintech_generic.yaml` (Wise, Revolut etc.)
- ****:
 - Frontend/accountclass
 - use can as/for configuration Prompt 
 - 

### Q6: Gemini API 
> **Question**: such as Gemini API Call? 

**✅ Your Answer**: use OpenRouter, eachdays $2 limitation already in/at API , should use no/none need limitation

**Decision**: should use Dependencies OpenRouter limitation
- Call Gemini 3 Flash excessively OpenRouter (non- Google API)
- OpenRouter have/has each, 429 incorrect
- should use no/none need implementationCalllimitation, but need goodprocess API 
- OpenRouter not , downgrade to then parseornotice use 
- variable: `OPENROUTER_API_KEY`, `OPENROUTER_DAILY_LIMIT_USD=2`

### Q7: parsefailure process
> **Question**: parsefailure use can with what? 

**✅ Your Answer**: C - supportretry + edit. retrypriorityupgrade to more model. 

**Decision**: minutesdowngradestrategy, parsesuccess
- ** 1 **: Gemini 3 Flash (fast, )
- ** 2 **: retryupgrade to Gemini 2.0 or more model ( excessively OpenRouter can use)
- ** 3 **: partparse, allow use edit
- ** 4 **: (completeform)
- process:
 ```
 Upload PDF
 ├─ Try Gemini 3 Flash
 │ ├─ ✅ Success → Show results
 │ └─ ❌ Fail → Offer "Retry with stronger model"
 │ ├─ Try Gemini 2.0 / GPT-4
 │ ├─ ✅ Success → Show results
 │ └─ ❌ Fail → Show partial results + Edit form
 └─ User can always manually add/edit transactions
 ```
- variable: `PRIMARY_MODEL=gemini-3-flash`, `FALLBACK_MODELS=["gemini-2.0", "gpt-4-turbo"]`
- UI retryanduse model

### Q8: for account
> **Question**: upload for such as to concreteaccount? 

**✅ Your Answer**: C - parse again confirmation, AI Recommendedaccount, use confirmation

**Decision**: process - parse + confirmation
- upload use optionalaccount (optional), or let AI recommendation
- parse, for in account (bank, 4 , etc.)
- in/at , in/at in match Account
 - precisematch: 4 + Complete
 - ambiguousmatch: bank + account
- Frontendconfirmationpage:
 - parse account (bank, , etc.)
 - recommendation account (match)
 - use optionalrecommendationaccountor
 - "createaccount" (such as recommendationaccount not in/at)

### Q9: for import
> **Question**: is no need need to supportimport for ? 

**✅ Your Answer**: C - supportupload + asyncqueueprocess. eachupload for should ETL . 

**Decision**: async ETL queuearchitecture
- **uploadphase**:
 - support (or zip)upload
 - eachthat iscreate `StatementProcessingTask` 
 - ID tableandqueue give use 
- ****:
 ```python
 class StatementProcessingTask:
 id: UUID
 file_name: str
 file_size: int
 upload_at: datetime
 status: Enum # pending/processing/completed/failed
 progress: int # 0-100
 error_message: Optional[str]
 extracted_data: Optional[dict]
 account_id: Optional[UUID]
 ```
- **processprocess** ():
 1. upload to temporary
 2. asyncprocess (status=pending)
 3. Call Gemini parse ()
 4. validatebalance (+transaction≈)
 5. BankStatementTransaction
 6. updateStatus as/for completed/failed
- **queueimplementation**:
 - use Redis queue or Celery ( in/at )
 - supportPriority (Priorityhighest)
 - retrystrategy (failureretry 3 )
- **UI**:
 - upload to "queue"page
 - each , Status, incorrect
 - supportprocess
 - complete for table

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Data Model + Gemini integration | 16h |
| Week 2 | Validation layer + API + Prompt tuning | 20h |
| Week 3 | Frontend UI + Multi-bank testing | 16h |
| Week 4 | ETL queue + Layered retry + Integration | 16h |

**Total estimate**: 68 hours (4 weeks)
