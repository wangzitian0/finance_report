# EPIC-003: Smart Statement Parsing

> **Status**: ✅ Complete  
> **Phase**: 2  
> **Duration**: 4 weeks  
> **Dependencies**: EPIC-002  

---

## 🎯 Objective

Upload → Free LLM (NVIDIA, etc) → JSON → Validation → BankStatementTransaction → Candidate JournalEntry

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Decoupled Design | AI only handles parsing, does not write directly to ledger, errors filtered through validation layer |
| 💻 **Developer** | API Integration | Gemini 3 Flash call wrapper with retry, fallback, and cost control |
| 📊 **Accountant** | Data Integrity | Opening + Transactions ≈ Closing, reject if validation fails |
| 🔗 **Reconciler** | Downstream Dependencies | Parsing results must be structured for matching algorithms |
| 🧪 **Tester** | Parsing Accuracy | Multi-bank, multi-format coverage testing, target ≥ 95% |
| 📋 **PM** | User Experience | Drag-and-drop upload, parsing progress, user-friendly error messages |

---

## ✅ Task Checklist

### Data Model (Backend)

- [x] `BankStatement` model - Statement header (user_id, account_id?, institution, account_last4, currency, period_start/period_end, opening/closing_balance, file_path, file_hash, original_filename, status, confidence_score, balance_validated)
- [x] `BankStatementTransaction` model - Transaction details (txn_date, amount, direction, description, reference, status, confidence, raw_text)
- [ ] Alembic migration script
- [x] Pydantic Schema

### Gemini Integration (Backend)

- [x] `services/extraction.py` - Document parsing service
  - [x] `parse_pdf()` - PDF parsing (OpenRouter Free Models)
  - [x] `parse_csv()` - CSV parsing (rules + AI assistance)
  - [ ] `parse_xlsx()` - Excel parsing
- [x] Prompt template management
  - [x] DBS/POSB statement template
  - [x] CMB statement template
  - [x] Maybank statement template
  - [x] Wise/fintech generic template
  - [x] Brokerage generic template
  - [x] Insurance generic template
- [x] Structured parsing results
  ```python
  class ParsedStatement:
      institution: str
      account_last4: str
      currency: str
      period_start: date
      period_end: date
      opening_balance: Decimal
      closing_balance: Decimal
      transactions: list[ParsedTransaction]
  ```

### Validation Layer (Backend)

- [x] `services/validation.py` - Validation service
  - [x] `validate_balance()` - Opening + Transactions ≈ Closing (tolerance 0.1 USD)
  - [x] `validate_completeness()` - Required field validation
  - [x] `compute_confidence_score()` - Score 0-100 based on SSOT factors
  - [x] `route_by_threshold()` - Auto-accept / review queue / manual entry
- [x] Duplicate import detection (file_hash) in upload endpoint
- [ ] Validation failure handling
  - [x] Mark as "Requires Manual Review"
  - [x] Log failure reason
  - [ ] Notify user

### API Endpoints (Backend)

- [x] `POST /api/statements/upload` - File upload
- [x] `GET /api/statements` - Statement list
- [x] `GET /api/statements/{id}` - Statement details (with transactions)
- [x] `GET /api/statements/pending-review` - Review queue list
- [x] `POST /api/statements/{id}/approve` - Approve statement
- [x] `POST /api/statements/{id}/reject` - Reject statement
- [x] `GET /api/statements/{id}/transactions` - Transaction list

### Frontend Interface (Frontend)

- [x] `/upload` - Upload page (integrated into /statements)
  - [x] Drag-and-drop upload component
  - [x] File type/size validation
  - [x] Upload progress bar
  - [x] Parsing status polling
- [x] `/statements` - Statement management
  - [x] Statement list (status badges)
  - [x] Statement details (transaction table)
  - [x] Parsing result preview
  - [x] Approve/Reject actions
- [x] Error handling
  - [x] Parsing failure notification
  - [x] Validation failure details
  - [x] Retry entry point

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Parsing success rate ≥ 95%** | Test with 10 real statements | 🔴 Critical |
| **Balance validation 100% enforced** | Opening+Transactions≈Closing check | 🔴 Critical |
| **Confidence score routing enforced** | ≥85 auto-accept, 60-84 review, <60 manual | 🔴 Critical |
| **Parsing errors not persisted** | Validation failure returns error | 🔴 Critical |
| Support PDF format (DBS/POSB, CMB, Maybank) | Bank sample testing | Required |
| Support PDF/CSV format (Wise/fintech, brokerage generic) | Sample testing | Required |
| File size limit 10MB | Upload validation | Required |
| Parsing time < 30s | Performance testing | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Support XLSX format | Excel sample testing | ⏳ |
| Editable parsing results | Frontend table editing | ⏳ |
| Batch upload | Multi-file queue processing | ⏳ |
| Parsing cache | Avoid duplicate API calls for same file | ⏳ |
| Gemini cost reporting | Token usage statistics | ⏳ |

### 🚫 Not Acceptable Signals

- Parsing success rate < 90%
- Balance validation skipped
- Parsing errors persisted to ledger
- Frequent Gemini API timeouts
- Users unable to understand error messages

---

## 🧪 Test Scenarios

### Unit tests (Required)

```python
# Balance validation
def test_balance_validation_passes():
    """Opening 1000 + Transactions 500 - 300 = Closing 1200"""

def test_balance_validation_fails():
    """Opening 1000 + Transactions 500 ≠ Closing 1600"""

# Parsing results
def test_parse_dbs_pdf():
    """DBS statement parsing with complete fields"""

def test_parse_invalid_pdf():
    """Non-statement PDF should return parsing failure"""
```

### Integration tests (Required)

```python
def test_upload_and_parse_flow():
    """Complete upload→parse→validate→persist flow"""

def test_duplicate_upload_detection():
    """Duplicate file upload should trigger warning"""

def test_free_model_retry_on_timeout():
    """AI retry should trigger on failure"""
```

### Sample Coverage (Required)

| Bank | Format | Sample Count | Expected Accuracy |
|------|------|--------|------------|
| DBS/POSB | PDF | 3 | ≥ 95% |
| CMB | PDF | 2 | ≥ 95% |
| Maybank | PDF | 2 | ≥ 95% |
| Wise | PDF/CSV | 2 | ≥ 95% |
| Brokerage (generic) | PDF/CSV | 2 | ≥ 90% |

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - BankStatement/BankStatementTransaction tables
- [extraction.md](../ssot/extraction.md) - Parsing rules and Prompt design

---

## 🔗 Deliverables

- [x] `apps/backend/src/models/statement.py`
- [x] `apps/backend/src/services/extraction.py`
- [x] `apps/backend/src/services/validation.py`
- [x] `apps/backend/src/routers/statements.py`
- [x] `apps/frontend/src/app/(main)/statements/page.tsx` (includes upload)
- [x] `apps/frontend/src/app/(main)/statements/[id]/page.tsx`
- [x] Update `docs/ssot/extraction.md` (Prompt templates)
- [x] Test sample set `apps/backend/tests/fixtures/`

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| Local PDF parsing fallback | P2 | Future iteration |
| Additional bank support (UOB, Citi) | P3 | Future iteration |
| OCR preprocessing (scanned docs) | P3 | Future iteration |

---

## Issues & Gaps

- [x] Align BankStatement and BankStatementTransaction fields with SSOT extraction (file_hash, confidence_score, balance_validated, etc.).
- [x] Align model/config with SSOT (Gemini 3 Flash + fallback models and OpenRouter limits).
- [x] Add confidence scoring and review queue routing (`/api/statements/pending-review`) to tasks and acceptance criteria.
- [x] Standardize institution/template scope across checklist, Q5 decision, and SSOT supported institutions.
- [x] Enforce balance validation routing (invalid balances route to manual entry and capture validation_error).

---

## ❓ Q&A (Clarification Required)

### Q5: Bank Priority Support
> **Question**: Which bank statements should be supported in the first version?

**✅ Your Answer**: DBS + China Merchants Bank + Maybank + Wise, also need support for brokerages, insurance and various institutions. Adopt generic structure + flexible extension field design.

**Decision**: Adopt highly extensible statement model
- **Core fields** (unified for all statements):
  - `period_start`, `period_end`, `opening_balance`, `closing_balance`
  - `transactions[]` with standardized fields: `txn_date`, `amount`, `direction`, `description`
- **Extension fields** (JSONB):
  - `bank_specific_data`: Bank-specific fields (e.g., reference number, transaction code)
  - `institution_type`: Institution type marker (bank, brokerage, insurance, wallet, etc.)
  - `custom_fields`: User-defined custom fields
- **Prompt templates** grouped by institution type:
  - `templates/dbs.yaml`
  - `templates/cmb.yaml`
  - `templates/maybank.yaml`
  - `templates/fintech_generic.yaml` (Wise, Revolut, etc.)
  - `templates/brokerage_generic.yaml`
  - `templates/insurance_generic.yaml`
- **Institution library maintenance**:
  - Frontend provides institution/account type selector
  - Users can configure prompt templates for new institutions
  - Community-contributed template library

### Q6: Gemini API Cost Control
> **Question**: How to control Gemini API call costs?

**✅ Your Answer**: Use OpenRouter, $2 daily limit is enforced at API level, no additional application-layer limits needed

**Decision**: Application layer relies on OpenRouter official limits
- Call Gemini 3 Flash through OpenRouter (not direct Google API)
- OpenRouter has daily quota management, automatically returns 429 error when exceeded
- Application layer does not need to implement call limits, but must gracefully handle API quota exhaustion
- When OpenRouter returns quota exhaustion, fallback to local rule-based parsing or notify user
- Environment variables: `OPENROUTER_API_KEY`, `OPENROUTER_DAILY_LIMIT_USD=2`

### Q7: Parsing Failure Handling
> **Question**: What can users do when parsing fails?

**✅ Your Answer**: C - Support retry + manual editing. Prioritize upgrading to stronger model on retry.

**Decision**: Layered fallback strategy to improve parsing success rate
- **Layer 1**: Gemini 3 Flash (fast, cheap)
- **Layer 2**: Upgrade to Gemini 2.0 or stronger model on retry (available through OpenRouter)
- **Layer 3**: Show partial parsing results, allow user to edit and supplement
- **Layer 4**: Manual entry (complete form)
- Flow:
  ```
  Upload PDF
  ├─ Try Gemini 3 Flash
  │  ├─ ✅ Success → Show results
  │  └─ ❌ Fail → Offer "Retry with stronger model"
  │     ├─ Try Gemini 2.0 / GPT-4
  │     ├─ ✅ Success → Show results
  │     └─ ❌ Fail → Show partial results + Edit form
  └─ User can always manually add/edit transactions
  ```
- Environment variables: `PRIMARY_MODEL=nvidia/llama-3.1-nemotron-70b-instruct:free`, `FALLBACK_MODELS=xiaomi/mimo-v2-flash:free,openai/gpt-oss-120b:free`
- UI displays retry progress and current model in use

### Q8: Statement-Account Linking
> **Question**: How to link statement to specific account on upload?

**✅ Your Answer**: C - Parse first then confirm, AI recommends account linking, user confirms

**Decision**: Two-step flow - Parse + Confirm linking
- User can optionally select account on upload, or leave blank for AI recommendation
- After parsing, extract account information from statement (bank name, last 4 digits of account, currency, etc.)
- Based on extracted info, find matching Account in system
  - Exact match: Last 4 digits + currency completely match
  - Fuzzy match: Bank name + currency match
- Frontend confirmation page displays:
  - Extracted account information (bank, account suffix, account holder, etc.)
  - System-recommended account (with confidence score)
  - User can select recommended account or manually choose
  - "Create New Account" entry point (if recommended account doesn't exist)

### Q9: Historical Statement Import
> **Question**: Do we need to support batch import of historical statements?

**✅ Your Answer**: C - Support batch upload + async queue processing. Each upload corresponds to an independent ETL task.

**Decision**: Async ETL task queue architecture
- **Upload phase**:
  - Support multi-file drag-and-drop (or zip) upload
  - Each file immediately creates a `StatementProcessingTask` record
  - Return task ID list and task queue link to user
- **Task structure**:
  ```python
  class StatementProcessingTask:
      id: UUID
      file_name: str
      file_size: int
      upload_at: datetime
      status: Enum  # pending/processing/completed/failed
      progress: int  # 0-100 percentage
      error_message: Optional[str]
      extracted_data: Optional[dict]
      account_id: Optional[UUID]
  ```
- **Processing flow** (independent tasks):
  1. Upload file to temporary storage
  2. Async worker process pulls task (status=pending)
  3. Call Gemini for parsing (record progress)
  4. Validate balance (opening+transactions≈closing)
  5. Store BankStatementTransaction
  6. Update task status to completed/failed
- **Queue implementation**:
  - Use Redis queue or Celery (depending on deployment environment)
  - Support task priority (single file has highest priority)
  - Task retry strategy (auto-retry 3 times on failure)
- **UI**:
  - Redirect to "Task Queue" page after upload
  - Display progress bar, status, error messages for each task
  - Support canceling pending tasks
  - Auto-refresh statement list when completed

---

## 📅 Timeline

| Phase | Content | Estimated Hours |
|------|------|----------|
| Week 1 | Data Model + Gemini integration | 16h |
| Week 2 | Validation layer + API + Prompt tuning | 20h |
| Week 3 | Frontend UI + Multi-bank testing | 16h |
| Week 4 | ETL queue + Layered retry + Integration | 16h |

**Total estimate**: 68 hours (4 weeks)
