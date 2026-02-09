# EPIC-013: Statement Parsing V2

> Status: 🟡 In Progress
> Owner: Backend + Frontend
> Scope: Statement extraction quality and review workflow visibility

## Goal

Upgrade statement parsing from V1 to V2 with richer transaction-level data and improved confidence scoring so review routing is more accurate and auditable.

## Objectives

1. Per-transaction currency support
2. Running balance (`balance_after`) per transaction
3. Institution auto-detection for PDF/image uploads when `institution` is omitted
4. Confidence scoring V2 with additional quality factors
5. Human review workflow visibility improvements in statement detail UI

## Deliverables

### 1) Per-Transaction Currency
- Add nullable `currency` on `BankStatementTransaction` model
- Add DB migration for `bank_statement_transactions.currency`
- Populate from AI extraction payload when present
- Expose through API schemas and frontend types
- Display in transactions table

### 2) Running Balance Per Transaction
- Add nullable `balance_after` on `BankStatementTransaction` model
- Add DB migration for `bank_statement_transactions.balance_after`
- Parse and persist from extraction payload
- Expose through API schemas and frontend types
- Display in transactions table

### 3) Institution Auto-Detection
- Make upload request `institution` optional for PDF/image flows
- Keep CSV path requiring institution
- Prompt requires model to infer institution from document header/logo

### 4) Confidence Scoring V2

Weights:
- Balance validation: 35%
- Field completeness: 25%
- Format consistency: 15%
- Transaction count: 10%
- Balance progression: 10%
- Currency consistency: 5%

New scoring helpers:
- `_score_balance_progression(transactions)`
- `_score_currency_consistency(transactions, header_currency)`

Expected routing behavior remains threshold-based:
- >= 85: auto-accept candidate
- 60-84: review queue
- < 60: manual handling path

### 5) Human Review Workflow Visibility
- Add `Currency` and `Balance` columns in statement detail transaction table
- Keep confidence and status columns visible for reviewer triage context

## Test Plan

- Update extraction unit tests for `_safe_decimal(None)` nullable behavior
- Add explicit required-mode test for `_safe_decimal(None, required=True)`
- Add confidence scoring V2 coverage tests:
  - balance progression scoring
  - currency consistency scoring
  - full-score with all factors
  - cap behavior without new factors

## Risks and Mitigations

- Risk: AI responses omit `currency`/`balance_after`
  - Mitigation: fields are nullable and scoring functions degrade gracefully
- Risk: scoring drift against SSOT
  - Mitigation: SSOT updates and dedicated V2 tests

## Progress Checklist

- [x] Model changes for transaction currency and running balance
- [x] Alembic migration for new columns
- [x] Extraction schema updates
- [x] Prompt updates for V2 output expectations
- [x] Extraction service updates (`_safe_decimal`, transaction mapping)
- [x] Confidence scoring V2 implementation
- [x] Frontend type and table updates
- [x] Test updates and V2 scoring coverage
- [x] SSOT documentation sync (`extraction.md`, `schema.md`)

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using AC13.x.y numbering.
> **Coverage**: See `apps/backend/tests/extraction/`

### AC13.1: Balance Validation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.1.1 | Test that valid balances pass validation | `test_balance_valid()` | `extraction/test_extraction.py` | P0 |
| AC13.1.2 | Test that invalid balances fail validation | `test_balance_invalid()` | `extraction/test_extraction.py` | P0 |
| AC13.1.3 | Test that small differences are tolerated | `test_balance_tolerance()` | `extraction/test_extraction.py` | P0 |

### AC13.2: Confidence Scoring V1

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.2.1 | Test that complete data gets high confidence (Auto-Accept) | `test_high_confidence()` | `extraction/test_extraction.py` | P0 |
| AC13.2.2 | Test that partial data gets medium confidence (Review) | `test_medium_confidence()` | `extraction/test_extraction.py` | P0 |
| AC13.2.3 | Test that no transactions lowers confidence (Manual) | `test_low_confidence_empty_transactions()` | `extraction/test_extraction.py` | P0 |

### AC13.3: Fixture Data

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.3.1 | Test DBS fixture has correct structure | `test_dbs_fixture_structure()` | `extraction/test_extraction.py` | P0 |
| AC13.3.2 | Test DBS fixture balances reconcile | `test_dbs_balance_reconciliation()` | `extraction/test_extraction.py` | P0 |
| AC13.3.3 | Test MariBank fixture has sanitized merchant names | `test_maribank_fixture_merchants_sanitized()` | `extraction/test_extraction.py` | P0 |
| AC13.3.4 | Test GXS fixture has daily interest entries | `test_gxs_fixture_daily_interest()` | `extraction/test_extraction.py` | P0 |
| AC13.3.5 | Test all fixtures have valid dates | `test_all_fixtures_have_dates()` | `extraction/test_extraction.py` | P0 |

### AC13.4: Prompt Generation

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.4.1 | Test default parsing prompt | `test_get_parsing_prompt_default()` | `extraction/test_extraction.py` | P0 |
| AC13.4.2 | Test DBS-specific prompt | `test_get_parsing_prompt_dbs()` | `extraction/test_extraction.py` | P0 |
| AC13.4.3 | Test CMB-specific prompt | `test_get_parsing_prompt_cmb()` | `extraction/test_extraction.py` | P0 |
| AC13.4.4 | Test with unknown institution returns base prompt | `test_get_parsing_prompt_unknown_institution()` | `extraction/test_extraction.py` | P0 |
| AC13.4.5 | Test Futu-specific prompt | `test_get_parsing_prompt_futu()` | `extraction/test_extraction.py` | P0 |
| AC13.4.6 | Test GXS-specific prompt | `test_get_parsing_prompt_gxs()` | `extraction/test_extraction.py` | P0 |
| AC13.4.7 | Test MariBank-specific prompt | `test_get_parsing_prompt_maribank()` | `extraction/test_extraction.py` | P0 |

### AC13.5: Media Payload Builder

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.5.1 | Test that PDFs use OpenRouter 'file' type | `test_pdf_uses_file_type()` | `extraction/test_extraction.py` | P0 |
| AC13.5.2 | Test that PNG images use 'image_url' type | `test_png_uses_image_url_type()` | `extraction/test_extraction.py` | P0 |
| AC13.5.3 | Test that JPG images use 'image_url' type | `test_jpg_uses_image_url_type()` | `extraction/test_extraction.py` | P0 |
| AC13.5.4 | Test that JPEG images use 'image_url' type | `test_jpeg_uses_image_url_type()` | `extraction/test_extraction.py` | P0 |

### AC13.6: Institution Detection

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.6.1 | Test that CSV parsing raises error when institution is None | `test_csv_requires_institution()` | `extraction/test_extraction.py` | P0 |
| AC13.6.2 | Test that parse_document accepts institution=None for PDFs (AI auto-detect) | `test_parse_document_accepts_none_institution_for_pdf()` | `extraction/test_extraction.py` | P0 |

### AC13.7: Extraction Service Helpers

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.7.1 | Test event confidence with complete data | `test_compute_event_confidence_complete()` | `extraction/test_extraction.py` | P0 |
| AC13.7.2 | Test event confidence with missing fields | `test_compute_event_confidence_missing_fields()` | `extraction/test_extraction.py` | P0 |
| AC13.7.3 | Test event confidence with invalid date format | `test_compute_event_confidence_invalid_date()` | `extraction/test_extraction.py` | P0 |
| AC13.7.4 | Test event confidence with null date | `test_compute_event_confidence_null_date()` | `extraction/test_extraction.py` | P0 |
| AC13.7.5 | Test _safe_date with valid input | `test_safe_date_valid()` | `extraction/test_extraction.py` | P0 |
| AC13.7.6 | Test _safe_date with invalid format | `test_safe_date_invalid_format()` | `extraction/test_extraction.py` | P0 |
| AC13.7.7 | Test _safe_date with empty input | `test_safe_date_empty()` | `extraction/test_extraction.py` | P0 |
| AC13.7.8 | Test _safe_decimal with valid input | `test_safe_decimal_valid()` | `extraction/test_extraction.py` | P0 |
| AC13.7.9 | Test _safe_decimal with invalid input | `test_safe_decimal_invalid()` | `extraction/test_extraction.py` | P0 |
| AC13.7.10 | Test _safe_decimal with None | `test_safe_decimal_none()` | `extraction/test_extraction.py` | P0 |
| AC13.7.11 | Test _safe_decimal None required | `test_safe_decimal_none_required()` | `extraction/test_extraction.py` | P0 |
| AC13.7.12 | Test compute_confidence with missing transactions key | `test_compute_confidence_missing_transactions()` | `extraction/test_extraction.py` | P0 |

### AC13.8: Balance Progression

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.8.1 | Test consistent chain scores 10 | `test_consistent_chain()` | `extraction/test_extraction.py` | P0 |
| AC13.8.2 | Test inconsistent chain scores 0 | `test_inconsistent_chain()` | `extraction/test_extraction.py` | P0 |
| AC13.8.3 | Test single transaction | `test_single_txn()` | `extraction/test_extraction.py` | P0 |
| AC13.8.4 | Test no balance after | `test_no_balance_after()` | `extraction/test_extraction.py` | P0 |
| AC13.8.5 | Test empty list | `test_empty_list()` | `extraction/test_extraction.py` | P0 |
| AC13.8.6 | Test partial consistency | `test_partial_consistency()` | `extraction/test_extraction.py` | P0 |
| AC13.8.7 | Test none currencies partial | `test_mixed_currencies_partial()` | `extraction/test_extraction.py` | P0 |
| AC13.8.8 | Test none currencies | `test_no_currencies()` | `extraction/test_extraction.py` | P0 |
| AC13.8.9 | Test missing currencies penalized | `test_missing_currencies_penalized()` | `extraction/test_extraction.py` | P0 |

### AC13.9: Confidence Scoring V2

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.9.1 | Test full score with all factors | `test_full_score_with_all_factors()` | `extraction/test_extraction.py` | P0 |
| AC13.9.2 | Test no new factors caps at 85 | `test_no_new_factors_caps_at_85()` | `extraction/test_extraction.py` | P0 |

**Test Coverage Summary**:
- Total AC IDs: 36
- Requirements converted to AC IDs: 100% (EPIC-013 P0 implementation)
- Requirements with test references: 100%
- Test files: 3
- Overall coverage: EPIC-013 implementation in progress

---

## 📏 Acceptance Criteria

- All extraction tests pass
- Lint/type checks pass
- PR is ready for review with SSOT + project docs updated
