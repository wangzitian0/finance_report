# Test AC Coverage Analysis Report

**Generated:** 2026-02-09  
**Purpose:** Identify all test functions without AC (Acceptance Criteria) numbers for TTD transformation

---

## Executive Summary

### Overall Coverage

- **Total test functions:** 391
- **With AC numbers:** 133 (34.0%)
- **Without AC numbers:** 258 (66.0%)

### Coverage by EPIC

| EPIC | Name | Coverage | With AC | Without AC | Total |
|------|------|----------|---------|------------|-------|
| EPIC-001 | Infrastructure & Authentication | 24.6% | 48 | 147 | 195 |
| EPIC-002 | Double-Entry Bookkeeping Core | 0.0% | 0 | 14 | 14 |
| EPIC-003 | Smart Statement Parsing | 52.6% | 51 | 46 | 97 |
| EPIC-004 | Reconciliation Engine & Matching | 20.0% | 6 | 24 | 30 |
| EPIC-005 | Financial Reports & Visualization | 0.0% | 0 | 18 | 18 |
| EPIC-006 | AI Financial Advisor | 75.7% | 28 | 9 | 37 |

---

## Domain-Level Breakdown

### EPIC-002: Double-Entry Bookkeeping Core (0% coverage)

**Total:** 14 tests | **Missing:** 14 tests

#### Critical Tests Needing AC Numbers

1. **Balance Validation (test_validation.py)**
   - `test_validate_balance_mismatch` → **AC2.2.1**
   - `test_validate_balance_tolerance` → **AC2.2.2**
   - `test_validate_balance_error_path` → **AC2.2.3**
   - `test_validate_balance_incomplete_transaction` → **AC2.2.4**

2. **Decimal Safety (test_decimal_safety.py)**
   - `test_decimal_parsing_from_string` → **AC2.4.1** (Golden Path)
   - `test_float_injection_safety` → **AC2.4.2** (Guardrail)
   - `test_scientific_notation_rejection` → **AC2.4.3** (Guardrail)

3. **Confidence Scoring (test_validation.py)**
   - `test_compute_confidence_score_small_diff` → **AC2.3.1**
   - `test_compute_confidence_score_with_missing_fields` → **AC2.3.2**
   - `test_compute_confidence_score_invalid_difference` → **AC2.3.3**
   - `test_compute_confidence_score_large_transaction_count` → **AC2.3.4**

4. **Routing Logic (test_validation.py)**
   - `test_route_by_threshold` → **AC2.5.1**
   - `test_validate_completeness_missing_fields` → **AC2.5.2**

5. **Equation Tests (test_accounting_equation.py)**
   - `test_user_id` → **AC2.1.1** (User scoping)

---

### EPIC-003: Smart Statement Parsing (52.6% coverage)

**Total:** 97 tests | **Missing:** 46 tests

#### High-Priority Missing AC Numbers

**Balance Validation (13.1.x)**
- Already has good coverage with AC13.1.1-13.1.3
- Missing: Helper function tests (test_extraction_coverage_fix.py)

**Confidence Scoring (13.2.x)**
- `test_compute_event_confidence_missing_fields` → **AC13.2.3**
- `test_all_fixtures_have_high_confidence` → **AC13.2.4** (Critical)

**Statement Parsing (13.3.x)**
- 30+ utility tests in `test_extraction_coverage_fix.py` need categorization
- Suggest: **AC13.3.x** for parsing utilities (sanitize, safe_date, safe_decimal)

**Storage (13.4.x)**
- `test_upload_bytes_*` tests → **AC13.4.1-13.4.5** (File upload & S3)

**Logging (13.5.x)**
- `test_extract_status_code_*` tests → **AC13.5.1-13.5.6** (Status code extraction)

---

### EPIC-004: Reconciliation Engine (20% coverage)

**Total:** 30 tests | **Missing:** 24 tests

#### Critical Missing AC Numbers

**Match Scoring (4.2.x)**
- `test_score_business_logic_combinations` → **AC4.2.1**
- `test_score_business_logic_out_equity` → **AC4.2.2**
- `test_score_business_logic_out_unknown` → **AC4.2.3**
- `test_score_date_proximity` → **AC4.2.4**
- `test_score_business_logic_variants` → **AC4.2.5**

**Auto-Accept/Review Queue (4.3.x)**
- `test_auto_accept_helper` → **AC4.3.3**

**Engine Utilities (4.4.x)**
- `test_normalize_text_and_grouping` → **AC4.4.1**
- `test_extract_merchant_tokens` → **AC4.4.2**
- `test_build_many_to_one_groups_skips_empty_descriptions` → **AC4.4.3**
- `test_prune_candidates*` → **AC4.4.4**

**Configuration (4.5.x)**
- `test_load_reconciliation_config_*` → **AC4.5.1-4.5.4** (YAML + env config)

---

### EPIC-005: Financial Reports (0% coverage)

**Total:** 18 tests | **Missing:** 18 tests

#### All Tests Need AC Numbers

**Balance Sheet (5.1.x)**
- Currently no dedicated tests identified

**Income Statement (5.2.x)**
- Currently no dedicated tests identified

**Multi-Currency (5.3.x)**
- `test_normalize_currency_defaults_to_base` → **AC5.3.1**

**Financial Snapshots (5.4.x)**
- `test_data_setup_reports` → **AC5.4.1**

**Reporting Helpers (5.5.x)**
- `test_iter_periods_*` → **AC5.5.1-5.5.3** (Period iteration)
- `test_add_months_caps_day` → **AC5.5.4**
- `test_month_helpers` → **AC5.5.5**
- `test_quantize_money_handles_ints` → **AC5.5.6**
- `test_signed_amount_respects_account_direction` → **AC5.5.7**

**FX Rate Support (5.6.x)**
- `test_user_id` (test_reporting_fx.py) → **AC5.6.1**
- `test_fx_cache_*` tests → **AC5.6.2-5.6.4**

---

### EPIC-006: AI Financial Advisor (75.7% coverage)

**Total:** 37 tests | **Missing:** 9 tests (lowest priority)

#### Missing AC Numbers

**Model Representation (6.5.x)**
- `test_*_repr` tests (7 tests) → **AC6.5.1-6.5.7**
- These test `__repr__` methods for AI context

**Validation (6.6.x)**
- `test_validation_confidence_with_invalid_amount` → **AC6.6.1**
- `test_validation_route_by_threshold` → **AC6.6.2**

---

### EPIC-001: Infrastructure (24.6% coverage)

**Total:** 195 tests | **Missing:** 147 tests

#### Categorization Needed

**Authentication (1.1.x)**
- Rate limit tests → **AC1.1.4-1.1.9** (10 tests)
- Client IP extraction → **AC1.1.10-1.1.13** (4 tests)

**Configuration (1.2.x)**
- Config parsing tests → **AC1.2.1-1.2.6** (6 tests)
- Boot sequence tests → **AC1.2.7-1.2.15** (9 tests)

**Database Schema (1.3.x)**
- User schema tests → **AC1.3.1-1.3.8** (8 tests)
- Migration tests → **AC1.3.9-1.3.11** (3 tests)
- Schema guardrails → **AC1.3.12-1.3.14** (3 tests)

**API Layer (1.4.x)**
- Schema validation tests → **AC1.4.1-1.4.13** (13 tests in test_schemas.py)
- Router tests → **AC1.4.14-1.4.16** (3 tests in test_routers.py)

**Exception Handling (1.5.x)**
- 27 exception tests → **AC1.5.1-1.5.27**

**Model Metadata (1.6.x)**
- Model table name/relationship tests → **AC1.6.1-1.6.10** (10 tests)

**Utilities (1.7.x)**
- PII redaction → **AC1.7.1-1.7.15** (15 tests)
- Deduplication → **AC1.7.16-1.7.19** (4 tests)
- FX revaluation → **AC1.7.20-1.7.21** (2 tests)
- Security/JWT → **AC1.7.22-1.7.27** (6 tests)

---

## Recommended Action Plan

### Phase 1: Critical Business Logic (Priority 1)

1. **EPIC-002 (Accounting Core)** - 14 tests
   - All tests are critical for financial integrity
   - Suggested timeline: 1-2 hours

2. **EPIC-004 (Reconciliation)** - 24 tests
   - Core matching engine logic
   - Suggested timeline: 2-3 hours

3. **EPIC-005 (Reporting)** - 18 tests
   - Financial report accuracy
   - Suggested timeline: 2 hours

### Phase 2: Feature Completeness (Priority 2)

4. **EPIC-003 (Statement Parsing)** - 46 tests
   - 52.6% already done, finish remaining
   - Suggested timeline: 3-4 hours

5. **EPIC-006 (AI Features)** - 9 tests
   - 75.7% already done, low priority
   - Suggested timeline: 1 hour

### Phase 3: Infrastructure (Priority 3)

6. **EPIC-001 (Infrastructure)** - 147 tests
   - Many are utility/helper tests
   - Can be batched by category
   - Suggested timeline: 8-10 hours

---

## Next Steps

1. **Review this report** with stakeholders
2. **Assign AC numbers** following the suggested categorization
3. **Update test docstrings** with AC numbers
4. **Verify coverage** by re-running `python scripts/analyze_test_ac_coverage.py`
5. **Link to EPIC documents** - Ensure each AC is documented in the corresponding EPIC file

---

## Script Usage

To regenerate this report:

```bash
python scripts/analyze_test_ac_coverage.py
```

The script automatically:
- Scans all test files in `apps/backend/tests/`
- Detects AC pattern `ACx.y.z` or `[ACx.y.z]` in docstrings
- Categorizes tests by domain and suggests AC numbers
- Generates coverage statistics by EPIC

---

*Generated by: `scripts/analyze_test_ac_coverage.py`*
