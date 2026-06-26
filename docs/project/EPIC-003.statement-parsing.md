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

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/extraction/`, `apps/backend/tests/test_csv_parsing.py`, and `apps/backend/tests/services/test_storage_sweep.py`

### AC3.1: Parsing Core (PDF/CSV)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.1.1 | Parse DBS PDF {tier:LLM-LED} {proof:invariant} | `test_balance_chain_invariant_holds_for_consistent_statements`, `test_balance_chain_tolerance_is_symmetric`, `test_dbs_fixture_has_valid_structure` | `extraction/test_extraction_invariants.py`, `extraction/test_pdf_parsing.py` | P0 |
| AC3.1.2 | Parse CSV (DBS) {tier:CODE-ONLY} | `test_parse_dbs_csv` | `test_csv_parsing.py` | P0 |
| AC3.1.3 | Parse CSV (Wise) {tier:CODE-ONLY} | `test_parse_wise_csv` | `test_csv_parsing.py` | P0 |
| AC3.1.4 | Parse CSV (Generic) {tier:CODE-ONLY} | `test_parse_generic_csv_with_amount_column` | `test_csv_parsing.py` | P0 |
| AC3.1.5 | Parse CSV with BOM {tier:CODE-ONLY} | `test_parse_csv_with_bom` | `test_csv_parsing.py` | P1 |

### AC3.2: Validation Logic

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.2.1 | Balance Validation (Pass) {tier:CODE-ONLY} | `test_balance_valid` | `extraction/test_extraction.py` | P0 |
| AC3.2.2 | Balance Validation (Fail) {tier:CODE-ONLY} | `test_balance_invalid` | `extraction/test_extraction.py` | P0 |
| AC3.2.3 | Completeness Validation {tier:CODE-ONLY} | `test_missing_required_fields_detected` | `extraction/test_pdf_parsing.py` | P1 |
| AC3.2.4 | Bank statement balance mismatches preserve validation_error details {tier:CODE-ONLY} | `test_parse_document_bank_balance_mismatch_records_validation_error` | `extraction/test_pdf_parsing.py` | P0 |
| AC3.2.5 | CSV transaction exports without statement balances remain reviewable {tier:CODE-ONLY} | `test_parse_document_csv_without_statement_balances_remains_reviewable` | `extraction/test_extraction_flow.py` | P0 |

### AC3.3: Confidence & Routing

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.3.1 | High Confidence (Auto-Accept) {tier:CODE-ONLY} | `test_high_confidence`, `test_auto_approve_high_confidence_statement_creates_posted_entries`, `test_auto_approve_guard_failure_preserves_uncommitted_parse_data` | `extraction/test_extraction.py`, `api/test_statements_router.py` | P0 |
| AC3.3.2 | Medium Confidence (Review) {tier:HU} {proof:evidence} | `test_medium_confidence` | `extraction/test_extraction.py` | P0 |
| AC3.3.3 | Low Confidence (Manual) {tier:CODE-ONLY} | `test_low_confidence_empty_transactions` | `extraction/test_extraction.py` | P0 |

### AC3.4: Error Handling

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.4.1 | Invalid Parse Not Persisted {tier:CODE-ONLY} | `test_extraction_error_not_persisted` | `extraction/test_pdf_parsing.py` | P0 |
| AC3.4.2 | Unsupported File Type {tier:CODE-ONLY} | `test_parse_document_unsupported_type` | `extraction/test_extraction_flow.py` | P1 |
| AC3.4.3 | Extraction Timeout {tier:CODE-ONLY} | `test_extraction_timeout_raises_error` | `extraction/test_pdf_parsing.py` | P1 |

### AC3.5: Additional Test Coverage
| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.5.1 | Full Upload Flow {tier:CODE-ONLY} | `test_statement_upload_full_flow` | `e2e/test_statement_upload_e2e.py` | P0 |
| AC3.5.2 | File Size Limit {tier:CODE-ONLY} | `test_upload_file_exceeds_10mb_limit` | `extraction/test_pdf_parsing.py` | P1 |
| AC3.5.3 | Model Selection Flow {tier:CODE-LED} | `test_model_selection_and_upload` | `e2e/test_statement_upload_e2e.py` | P1 |
| AC3.5.4 | Extraction Flow Tests {tier:CODE-ONLY} | `test_extraction_flow` | `extraction/test_extraction_flow.py` | P0 |
| AC3.5.5 | Statement Parsing Supervisor {tier:CODE-ONLY} | `test_statement_parsing_supervisor` | `extraction/test_statement_parsing_supervisor.py` | P1 |
| AC3.5.6 | Invalid file extension should return 400. {tier:CODE-ONLY} | `test_upload_invalid_extension` | `api/test_statements_router.py` | P1 |
| AC3.5.7 | PDF/image uploads may omit model and use the default OCR pipeline. {tier:LLM-LED} {proof:invariant} | `test_balance_chain_invariant_holds_for_consistent_statements`, `test_upload_uses_default_ocr_pipeline_for_pdf` | `extraction/test_extraction_invariants.py`, `api/test_statements_router.py` | P1 |
| AC3.5.8 | Upload rejects models without image modalities. {tier:CODE-ONLY} | `test_upload_rejects_text_only_model` | `api/test_statements_router.py` | P1 |
| AC3.5.9 | Upload then list statements and transactions. {tier:CODE-ONLY} | `test_list_and_transactions_flow` | `api/test_statements_router.py` | P1 |
| AC3.5.10 | Review queue includes reviewable parsed statements and supports approve/reject. {tier:HU} {proof:evidence} | `test_pending_review_and_decisions` | `api/test_statements_router.py` | P1 |
| AC3.5.11 | Missing statement returns 404. {tier:CODE-ONLY} | `test_get_statement_not_found` | `api/test_statements_router.py` | P1 |
| AC3.5.12 | File exceeding 10MB limit returns 413. {tier:CODE-ONLY} | `test_upload_file_too_large` | `api/test_statements_router.py` | P1 |
| AC3.5.13 | Extraction failure marks statement as rejected. {tier:CODE-ONLY} | `test_upload_extraction_failure` | `api/test_statements_router.py` | P1 |
| AC3.5.14 | Retry on missing statement returns 404. {tier:CODE-ONLY} | `test_retry_statement_not_found` | `api/test_statements_router.py` | P1 |
| AC3.5.15 | Retry rejects models without image modalities. {tier:CODE-ONLY} | `test_retry_rejects_text_only_model` | `api/test_statements_router.py` | P1 |
| AC3.5.16 | Retry returns 503 if storage fetch fails. {tier:CODE-ONLY} | `test_retry_statement_storage_failure` | `api/test_statements_router.py` | P1 |
| AC3.5.17 | Retry on statement not in parsed/rejected status returns 400. {tier:CODE-ONLY} | `test_retry_statement_invalid_status` | `api/test_statements_router.py` | P1 |
| AC3.5.18 | Verify that retrying a statement in PARSING status is allowed. {tier:CODE-ONLY} | `test_retry_statement_parsing_allowed` | `api/test_statements_router.py` | P1 |
| AC3.5.19 | Retry parsing with stronger model succeeds. {tier:LLM-LED} {proof:property} | `test_distinct_same_amount_rows_never_collapse`, `test_balance_chain_invariant_detects_broken_chain`, `test_retry_statement_success` | `extraction/test_extraction_invariants.py`, `api/test_statements_router.py` | P1 |
| AC3.5.20 | Retry extraction failure returns 422. {tier:CODE-ONLY} | `test_retry_statement_extraction_failure` | `api/test_statements_router.py` | P1 |
| AC3.5.21 | Upload rejects models not in the OpenRouter catalog. {tier:CODE-ONLY} | `test_upload_statement_rejects_invalid_model` | `api/test_statements_router.py` | P1 |
| AC3.5.22 | Upload rejects a model lacking image/PDF modality (400). _(EPIC-023: model validation now resolves through the local `LitellmCatalog`; the prior remote-catalog 503 path no longer exists.)_ {tier:CODE-ONLY} | `test_upload_statement_rejects_model_without_image_modality` | `api/test_statements_router.py` | P1 |
| AC3.5.23 | Retry rejects a model not in the catalogue (400). _(EPIC-023: model validation now resolves through the local `LitellmCatalog`; the prior remote-catalog 503 path no longer exists.)_ {tier:CODE-ONLY} | `test_retry_statement_rejects_invalid_model` | `api/test_statements_router.py` | P1 |
| AC3.5.24 | Background parse error should be caught and logged. {tier:CODE-ONLY} | `test_background_parse_error_logging` | `api/test_statements_router.py` | P1 |
| AC3.5.25 | Background retry error should be caught and logged. {tier:CODE-ONLY} | `test_background_retry_error_logging` | `api/test_statements_router.py` | P1 |

### AC3.6: Statement-Account Mapping Hardening
| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.6.1 | Unique Prior Mapping {tier:CODE-ONLY} | `test_approve_statement_stage1_auto_maps_unique_prior_confirmed_account` | `api/test_statements_router.py` | P0 |
| AC3.6.2 | No Silent Fallback Posting {tier:CODE-ONLY} | `test_approve_statement_stage1_blocks_unmapped_account_without_fallback`, `test_approve_statement_stage1_blocks_unsafe_explicit_account_mapping`, `test_create_entry_from_txn_auto_post_requires_account_mapping` | `api/test_statements_router.py`, `reconciliation/test_review_queue.py` | P0 |
| AC3.6.3 | Ambiguous Mapping Blocked {tier:CODE-ONLY} | `test_approve_statement_stage1_blocks_ambiguous_account_mapping` | `api/test_statements_router.py` | P0 |
| AC3.6.4 | Explicit First-Upload Account Creation {tier:HU} {proof:evidence} | `test_approve_statement_stage1_creates_account_with_explicit_confirmation` | `api/test_statements_router.py` | P0 |
| AC3.6.5 | Prior Mapping Requires Confirmed Statement {tier:CODE-ONLY} | `test_approve_statement_stage1_blocks_prior_unconfirmed_account_mapping` | `api/test_statements_router.py` | P0 |
| AC3.6.6 | Source Period Unique Before Posting {tier:CODE-ONLY} | `test_approve_statement_stage1_blocks_overlapping_statement_period_before_posting` | `api/test_statements_router.py` | P0 |

### AC3.7: Account Statement Coverage
| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.7.1 | Latest Confirmed Source {tier:CODE-ONLY} | `test_account_coverage_reports_latest_confirmed_balance_and_stale_status` | `accounting/test_account_statement_coverage.py` | P1 |
| AC3.7.2 | Adjacent Opening Continuity {tier:CODE-ONLY} | `test_account_coverage_detects_adjacent_opening_balance_mismatch` | `accounting/test_account_statement_coverage.py` | P1 |
| AC3.7.3 | Missing/Overlapping/Duplicate Periods {tier:CODE-ONLY} | `test_account_coverage_reports_missing_overlapping_and_duplicate_ranges` | `accounting/test_account_statement_coverage.py` | P1 |
| AC3.7.4 | Broker Daily Snapshot Override {tier:CODE-ONLY} | `test_account_coverage_accepts_broker_monthly_cadence_with_daily_snapshot_override` | `accounting/test_account_statement_coverage.py` | P1 |

### AC3.8: Storage Lifecycle Cleanup
| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.8.1 | Delete old orphaned storage objects {tier:CODE-ONLY} | `test_sweep_deletes_orphaned_object` | `services/test_storage_sweep.py` | P1 |
| AC3.8.2 | Preserve objects with DB records {tier:CODE-ONLY} | `test_sweep_skips_known_db_objects` | `services/test_storage_sweep.py` | P1 |
| AC3.8.3 | Skip recent in-flight uploads {tier:CODE-ONLY} | `test_sweep_skips_recent_objects` | `services/test_storage_sweep.py` | P1 |
| AC3.8.4 | No-op without configured S3 bucket {tier:CODE-ONLY} | `test_sweep_skips_when_no_bucket_configured` | `services/test_storage_sweep.py` | P1 |
| AC3.8.5 | Return zero for empty statement prefix {tier:CODE-ONLY} | `test_sweep_returns_zero_when_no_objects` | `services/test_storage_sweep.py` | P1 |
| AC3.8.6 | Handle storage listing errors {tier:CODE-ONLY} | `test_sweep_handles_storage_list_error` | `services/test_storage_sweep.py` | P1 |
| AC3.8.7 | Handle object delete errors {tier:CODE-ONLY} | `test_sweep_handles_delete_error` | `services/test_storage_sweep.py` | P1 |
| AC3.8.8 | Paginate storage keys and normalize timestamps {tier:CODE-ONLY} | `test_list_storage_keys_returns_paginated_keys_and_normalizes_timestamps` | `services/test_storage_sweep.py` | P1 |
| AC3.8.9 | Convert storage client listing errors {tier:CODE-ONLY} | `test_list_storage_keys_raises_on_client_error` | `services/test_storage_sweep.py` | P1 |
| AC3.8.10 | Exit runner on stop event {tier:CODE-ONLY} | `test_run_storage_sweep_exits_on_stop_event` | `services/test_storage_sweep.py` | P1 |
| AC3.8.11 | Log runner deletion counts {tier:CODE-ONLY} | `test_run_storage_sweep_logs_when_objects_deleted` | `services/test_storage_sweep.py` | P1 |
| AC3.8.12 | Continue runner after unexpected sweep exception {tier:CODE-ONLY} | `test_run_storage_sweep_handles_exception` | `services/test_storage_sweep.py` | P1 |
| AC3.8.13 | Disable runner by feature flag {tier:CODE-ONLY} | `test_run_storage_sweep_disabled_by_feature_flag` | `services/test_storage_sweep.py` | P1 |
| AC3.8.14 | Grace period + interval config defaults match issue #356 (24h / daily) {tier:CODE-ONLY} | `test_grace_period_and_interval_defaults_match_issue_356` | `services/test_storage_sweep.py` | P1 |
| AC3.8.15 | Sweep grace-period cutoff is config-driven, not a hardcoded constant {tier:CODE-ONLY} | `test_sweep_reads_grace_period_from_config` | `services/test_storage_sweep.py` | P1 |
| AC3.8.16 | Sweep runner wait interval is read from config {tier:CODE-ONLY} | `test_run_storage_sweep_reads_interval_from_config` | `services/test_storage_sweep.py` | P1 |

### AC3.9: Audit-Failed Case Registry
| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.9.1 | Parsing cases that fail audit are recorded in an SSOT registry without expanding deterministic parser scope or committing real documents {tier:CODE-ONLY} | `test_AC3_9_1_extraction_failed_case_registry_preserves_audit_cases_without_parser_expansion` | `tests/tooling/test_extraction_failed_case_registry.py` | P0 |

### AC3.10: Settlement Evidence Capture Boundary

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.10.1 | Statement parsing owns fact-forward settlement evidence capture and must preserve source metadata needed by framework readiness while leaving US/HK policy decisions to EPIC-020 {tier:CODE-ONLY} | `test_AC3_10_1_statement_parsing_is_source_capture_not_framework_policy` | `tests/tooling/test_framework_reporting_epic_contract.py` | P0 |

### AC3.11: Tolerant Statement-Period Resolution ([#1449](https://github.com/wangzitian0/finance_report/issues/1449))

The model occasionally omits `period_start` (or `period_end`) for a bank statement that plainly has a period and transactions. Passing the missing field straight to `_safe_date` hard-failed the whole parse with "Date is required" — non-deterministically, for the same statement format. The period is now resolved tolerantly: a missing bound falls back to the transaction-date range (which yields a meaningful period), then to the other explicit bound, and only rejects when no date can be recovered at all.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC3.11.1 | A missing `period_start` falls back to `period_end` instead of hard-failing the parse {tier:CODE-ONLY} | `test_AC3_11_1_period_start_falls_back_to_period_end` | `extraction/test_extraction.py` | P1 |
| AC3.11.2 | With no period bounds, the statement period is derived from the transaction-date range {tier:CODE-ONLY} | `test_AC3_11_2_period_derived_from_transaction_dates` | `extraction/test_extraction.py` | P1 |
| AC3.11.3 | A statement with no period and no transaction dates still rejects (no silent zero-date) {tier:CODE-ONLY} | `test_AC3_11_3_no_resolvable_date_still_raises` | `extraction/test_extraction.py` | P1 |

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Parsing success rate ≥ 95%** | `test_dbs_fixture_has_valid_structure`, `test_parse_csv_*` | 🔴 Critical |
| **Balance validation 100% enforced** | `test_balance_valid`, `test_balance_invalid` | 🔴 Critical |
| **Confidence score routing enforced** | `test_high_confidence`, `test_medium_confidence` | 🔴 Critical |
| **Parsing errors not persisted** | `test_extraction_error_not_persisted` | 🔴 Critical |
| **Statement account confirmed before posting** | `test_approve_statement_stage1_blocks_unmapped_account_without_fallback`, `test_approve_statement_stage1_creates_account_with_explicit_confirmation` | 🔴 Critical |
| **Account coverage visible before dashboard completion** | `test_account_coverage_reports_missing_overlapping_and_duplicate_ranges`, `test_account_coverage_detects_adjacent_opening_balance_mismatch` | Required |
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

Audit-failed parsing cases are not parser expansion requirements by default.
LLM/OCR remains the polymorphic extraction layer. Cases that fail schema,
balance, confidence, account-mapping, provider-shape, or user-review audit are
tracked in
[`extraction_failed_case_registry`](../ssot/extraction-audit-failed-cases.yaml)
with sanitized evidence only; follow-up work may tune prompts, models, review
workflow, or parser rules after separate EPIC -> AC registration.

### 🚫 Not Acceptable Signals

- Parsing success rate < 90%
- Balance validation skipped
- Parsing errors persisted to ledger
- Frequent Gemini API timeouts
- Users unable to understand error messages

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - data-layer and migration guardrails
- [Generated DB Schema Reference](../reference/db-schema.md) - current uploaded document, statement summary, and atomic fact tables
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
