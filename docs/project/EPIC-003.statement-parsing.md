# EPIC-003: Smart Statement Parsing

> **Status**: ✅ Complete (TDD Aligned)
> **Vision Anchor**: `decision-2-event-middle-layer`
> **Phase**: 2
> **Duration**: 4 weeks
> **Dependencies**: EPIC-002

---

## 🎯 Objective

Upload → Free LLM (NVIDIA, etc) → JSON → Validation → BankStatementTransaction → Candidate JournalEntry

---

## Macro Proof Ownership

- `source-ledger-report-traceability`

## Framework Boundary

EPIC-003 owns source capture. It extracts settlement, statement, PDF, and CSV
facts with source metadata, period boundaries, currencies, balances, and raw
line anchors needed by downstream evidence checks. It does not decide US-like
or HK-like report classification, measurement, presentation, or disclosure.

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | Decoupled Design | AI only handles parsing, does not write directly to ledger, errors filtered through validation layer |
| 💻 **Developer** | API Integration | Parsing uses the configured AI provider and model from `apps/backend/src/config.py`; user retry may select a different model |
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

### AI Provider Integration (Backend)

- [x] `src/extraction/extension/service.py` - Document parsing service (package home since #1421)
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

- [x] `src/extraction/base/validation.py` - Validation service (package home since #1421)
  - [x] `validate_balance()` - Opening + Transactions ≈ Closing (tolerance 0.1 USD)
  - [x] `validate_completeness()` - Required field validation
  - [x] `compute_confidence_score()` - Score 0-100 based on SSOT factors
  - [x] `route_by_threshold()` - Auto-accept / review queue / manual entry
- [x] Duplicate import detection (file_hash) in upload endpoint
- [x] Validation failure handling
  - [x] Mark as "Requires Manual Review"
  - [x] Log failure reason
  - [x] Notify user
  - [x] Sweep orphaned storage objects that do not have DB records

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

## 🧪 Test Cases / Acceptance Criteria

> **Migrated (2026-07-03, #1421 Stage-2 cutover):** all 73 ACs moved to
> the `extraction` package roadmap in
> [`common/extraction/contract.py`](../../common/extraction/contract.py) as
> `AC-extraction.<group>.<seq>` — this EPIC's rows occupy the reserved
> groups 1–12 (leading epic number dropped), per Decision A (standard-preserving move — every AC kept its
> statement, anchored test, and priority; the package tier is LLM-LED with
> per-AC `proof_kind`). This section intentionally holds no rows; the contract
> roadmap is the single source.



### Retained rows (human-authority: not migratable into the LLM-LED package roadmap)

The tier→proof matrix forbids `evidence` proofs under an LLM-LED package, so
these {tier:HU} rows keep their EPIC home (the ledger cutover's frontend-row
precedent). Extraction's failed-case audit trail stays registered in
[`extraction_failed_case_registry`](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/audit-failed-cases.yaml).

| AC ID | Description | Test Function | Test File | Priority |
|-------|-------------|---------------|-----------|----------|
| AC3.3.2 | Medium Confidence (Review) {tier:HU} {proof:evidence} | `test_medium_confidence` | `extraction/test_extraction.py` | P0 |
| AC3.5.10 | Review queue includes reviewable parsed statements and supports approve/reject. {tier:HU} {proof:evidence} | `test_pending_review_and_decisions` | `api/test_statements_router.py` | P1 |
| AC3.6.4 | Explicit First-Upload Account Creation {tier:HU} {proof:evidence} | `test_approve_statement_stage1_creates_account_with_explicit_confirmation` | `api/test_statements_router.py` | P0 |

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - data-layer and migration guardrails
- [Generated DB Schema Reference](../reference/db-schema.md) - current uploaded document, statement summary, and atomic fact tables
- [common/extraction/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/readme.md) - Parsing rules and Prompt design (internalized into the `extraction` package)

---

## 🔗 Deliverables

- [x] `apps/backend/src/models/statement.py`
- [x] `apps/backend/src/extraction/extension/service.py`
- [x] `apps/backend/src/extraction/base/validation.py`
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
- [x] Align model/config with `apps/backend/src/config.py` and `docs/ssot/ai.md`.
- [x] Add confidence scoring and review queue routing.
- [x] Enforce balance validation routing.

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../user-guide/reconciliation.md](../user-guide/reconciliation.md) — statement upload and AI extraction portions of the reconciliation workflow.

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

## Acceptance Criteria

> **Migrated (2026-07-03, #1421 Stage-2 cutover):** all 73 ACs moved to
> the `extraction` package roadmap in
> [`common/extraction/contract.py`](../../common/extraction/contract.py) as
> `AC-extraction.<group>.<seq>` — this EPIC's rows occupy the reserved
> groups 1–12 (leading epic number dropped), per Decision A (standard-preserving move — every AC kept its
> statement, anchored test, and priority; the package tier is LLM-LED with
> per-AC `proof_kind`). This table intentionally holds no rows; the contract
> roadmap is the single source.
