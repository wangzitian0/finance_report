# EPIC-003: Smart Statement Parsing

> **Status**: ✅ Complete (TDD Aligned)
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
| 💻 **Developer** | API Integration | Gemini 2.0 Flash (free) single-model parsing; user retry selects a different model |
| 📊 **Accountant** | Data Integrity | Opening + Transactions ≈ Closing, reject if validation fails |
| 🔗 **Reconciler** | Downstream Dependencies | Parsing results must be structured for matching algorithms |
| 🧪 **Tester** | Parsing Accuracy | Multi-bank, multi-format coverage testing, target ≥ 95% |
| 📋 **PM** | User Experience | Drag-and-drop upload, parsing progress, user-friendly error messages |

---

## ✅ Task Checklist

### Data Model (Backend)

- [x] `BankStatement` model - Statement header (user_id, account_id?, institution, account_last4, currency, period_start/period_end, opening/closing_balance, file_path, file_hash, original_filename, status, confidence_score, balance_validated)
- [x] `BankStatementTransaction` model - Transaction details (txn_date, amount, direction, description, reference, status, confidence, raw_text)
- [x] Alembic migration script
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
- [x] Validation failure handling
  - [x] Mark as "Requires Manual Review"
  - [x] Log failure reason
  - [x] Notify user

### API Endpoints (Backend)

- [x] `POST /statements/upload` - File upload
- [x] `GET /statements` - Statement list
- [x] `GET /statements/{id}` - Statement details (with transactions)
- [x] `GET /statements/pending-review` - Review queue list
- [x] `POST /statements/{id}/approve` - Approve statement
- [x] `POST /statements/{id}/reject` - Reject statement
- [x] `GET /statements/{id}/transactions` - Transaction list

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

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/extraction/` and `apps/backend/tests/test_csv_parsing.py`

### AC3.1: Parsing Core (PDF/CSV)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.1.1 | Parse DBS PDF | `test_dbs_fixture_has_valid_structure` | `extraction/test_pdf_parsing.py` | P0 |
| AC3.1.2 | Parse CSV (DBS) | `test_parse_dbs_csv` | `test_csv_parsing.py` | P0 |
| AC3.1.3 | Parse CSV (Wise) | `test_parse_wise_csv` | `test_csv_parsing.py` | P0 |
| AC3.1.4 | Parse CSV (Generic) | `test_parse_generic_csv_with_amount_column` | `test_csv_parsing.py` | P0 |
| AC3.1.5 | Parse CSV with BOM | `test_parse_csv_with_bom` | `test_csv_parsing.py` | P1 |

### AC3.2: Validation Logic

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.2.1 | Balance Validation (Pass) | `test_balance_valid` | `extraction/test_extraction.py` | P0 |
| AC3.2.2 | Balance Validation (Fail) | `test_balance_invalid` | `extraction/test_extraction.py` | P0 |
| AC3.2.3 | Completeness Validation | `test_missing_required_fields_detected` | `extraction/test_pdf_parsing.py` | P1 |

### AC3.3: Confidence & Routing

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.3.1 | High Confidence (Auto-Accept) | `test_high_confidence` | `extraction/test_extraction.py` | P0 |
| AC3.3.2 | Medium Confidence (Review) | `test_medium_confidence` | `extraction/test_extraction.py` | P0 |
| AC3.3.3 | Low Confidence (Manual) | `test_low_confidence_empty_transactions` | `extraction/test_extraction.py` | P0 |

### AC3.4: Error Handling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.4.1 | Invalid Parse Not Persisted | `test_extraction_error_not_persisted` | `extraction/test_pdf_parsing.py` | P0 |
| AC3.4.2 | Unsupported File Type | `test_parse_document_unsupported_type` | `extraction/test_extraction_flow.py` | P1 |
| AC3.4.3 | Extraction Timeout | `test_extraction_timeout_raises_error` | `extraction/test_pdf_parsing.py` | P1 |

### AC3.5: API & E2E

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.5.1 | Full Upload Flow | `test_statement_upload_full_flow` | `e2e/test_statement_upload_e2e.py` | P0 |
| AC3.5.2 | File Size Limit | `test_upload_file_exceeds_10mb_limit` | `extraction/test_pdf_parsing.py` | P1 |
| AC3.5.3 | Model Selection Flow | `test_model_selection_and_upload` | `e2e/test_statement_upload_e2e.py` | P1 |

**Traceability Result**:
- Total AC IDs: 15
- Requirements converted to AC IDs: 100% (EPIC-003 checklist + must-have standards)
- Requirements with test references: 100%
- Test files: 5

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Parsing success rate ≥ 95%** | `test_dbs_fixture_has_valid_structure`, `test_parse_csv_*` | 🔴 Critical |
| **Balance validation 100% enforced** | `test_balance_valid`, `test_balance_invalid` | 🔴 Critical |
| **Confidence score routing enforced** | `test_high_confidence`, `test_medium_confidence` | 🔴 Critical |
| **Parsing errors not persisted** | `test_extraction_error_not_persisted` | 🔴 Critical |
| Support PDF format (DBS/POSB, CMB, Maybank) | `test_dbs_fixture_has_valid_structure` | Required |
| Support CSV format (Wise/fintech, generic) | `test_csv_parsing.py` suite | Required |
| File size limit 10MB | `test_upload_file_exceeds_10mb_limit` | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Support XLSX format | (Future) | ⏳ |
| Editable parsing results | Frontend implementation | ⏳ |
| Batch upload | Frontend implementation | ⏳ |
| Parsing cache | (Future) | ⏳ |

### 🚫 Not Acceptable Signals

- Parsing success rate < 90%
- Balance validation skipped
- Parsing errors persisted to ledger
- Frequent Gemini API timeouts
- Users unable to understand error messages

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
- [x] `apps/frontend/src/app/(main)/statements/page.tsx`
- [x] `apps/frontend/src/app/(main)/statements/[id]/page.tsx`
- [x] `apps/backend/tests/extraction/` - Test suite
- [x] `apps/backend/tests/test_csv_parsing.py` - CSV test suite

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| Local PDF parsing fallback | P2 | Future iteration |
| Additional bank support (UOB, Citi) | P3 | Future iteration |
| OCR preprocessing (scanned docs) | P3 | Future iteration |

---

## 🛡️ Post-Release Fixes

| Fix | PR | Root Cause |
|-----|-----|------------|
| `account_last4` sanitization — strip non-alphanumeric, take last 4 chars | #269 | AI returned `553-3` (5 chars with hyphen), exceeding VARCHAR(4) → `StringDataRightTruncationError` |
| `_handle_parse_failure` rollback-first — rollback before re-fetching statement | #269 | Secondary `PendingRollbackError` crashed error handler, leaving statement stuck in `PARSING` forever |
| Frontend parsing timeout + rejected alert — 5-min timeout, retry only when stuck | #269 | No UI feedback when parsing got stuck; user had no way to recover |

---

## Issues & Gaps

- [x] Align BankStatement and BankStatementTransaction fields with SSOT.
- [x] Align model/config with SSOT (Gemini 2.0 Flash).
- [x] Add confidence scoring and review queue routing.
- [x] Enforce balance validation routing.

---

## ❓ Q&A (Clarification Required)

### Q5: Bank Priority Support
> **Decision**: Adopt highly extensible statement model (Core fields + Extension JSONB). Supported: DBS, CMB, Maybank, Wise, Generic.

### Q6: Gemini API Cost Control
> **Decision**: Use OpenRouter limits ($2 daily). App handles quota exhaustion gracefully.

### Q7: Parsing Failure Handling
> **Decision**: Manual retry with explicit model selection.

### Q8: Statement-Account Linking
> **Decision**: Parse first, then AI recommends linking, user confirms.

### Q9: Historical Statement Import
> **Decision**: Async ETL task queue architecture (Upload -> Task -> Process -> Result).

---

## 📅 Timeline

| Phase | Content | Status |
|------|------|----------|
| Week 1 | Data Model + Gemini integration | ✅ Done |
| Week 2 | Validation layer + API + Prompt tuning | ✅ Done |
| Week 3 | Frontend UI + Multi-bank testing | ✅ Done |
| Week 4 | ETL queue + Manual retry + Integration | ✅ Done |
