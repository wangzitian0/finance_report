# EPIC-013: Statement Parsing V2

> Status: ✅ Complete
> Vision Anchor: `decision-2-event-middle-layer`
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

Expected routing behavior remains threshold-based (See: `docs/ssot/reconciliation.md#thresholds`):
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
| AC13.5.1 | Test that PDF payloads use provider-compatible `file` or `image_url` shapes | `test_pdf_url_uses_zai_image_url_type()`, `test_pdf_base64_keeps_legacy_file_type()` | `extraction/test_extraction.py` | P0 |
| AC13.5.2 | Test that PNG images use 'image_url' type | `test_png_uses_image_url_type()` | `extraction/test_extraction.py` | P0 |
| AC13.5.3 | Test that JPG images use 'image_url' type | `test_jpg_uses_image_url_type()` | `extraction/test_extraction.py` | P0 |
| AC13.5.4 | Test that JPEG images use 'image_url' type | `test_jpeg_uses_image_url_type()` | `extraction/test_extraction.py` | P0 |

### AC13.6: Institution Detection

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.6.1 | Test that CSV parsing raises error when institution is None | `test_csv_requires_institution()` | `extraction/test_extraction.py` | P0 |
| AC13.6.2 | Test that parse_document accepts institution=None for PDFs (AI auto-detect) | `test_parse_document_accepts_none_institution_for_pdf()` | `extraction/test_extraction.py` | P0 |
| AC13.6.3 | Test that parse_document accepts force_model parameter | `test_parse_document_accepts_force_model()` | `extraction/test_extraction.py` | P0 |

### AC13.7: Extraction Service Helpers

> **Note:** the per-transaction event-confidence helper (`_compute_event_confidence`)
> was removed in EPIC-011 Stage 3 — confidence is now a statement-level score only and
> `AtomicTransaction` has no per-row confidence. The four event-confidence acceptance
> criteria are retired with it.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.7.5 | Test _safe_date with valid input | `test_safe_date_valid()` | `extraction/test_extraction.py` | P0 |
| AC13.7.6 | Test _safe_date with invalid format | `test_safe_date_invalid_format()` | `extraction/test_extraction.py` | P0 |
| AC13.7.7 | Test _safe_date with empty input | `test_safe_date_empty()` | `extraction/test_extraction.py` | P0 |
| AC13.7.8 | Test _safe_decimal with valid input | `test_safe_decimal_valid()` | `extraction/test_extraction.py` | P0 |
| AC13.7.9 | Test _safe_decimal with invalid input | `test_safe_decimal_invalid()` | `extraction/test_extraction.py` | P0 |
| AC13.7.10 | Test _safe_decimal with None | `test_safe_decimal_none()` | `extraction/test_extraction.py` | P0 |
| AC13.7.11 | Test _safe_decimal None required | `test_safe_decimal_none_required()` | `extraction/test_extraction.py` | P0 |
| AC13.7.12 | Test compute_confidence with missing transactions key | `test_compute_confidence_missing_transactions()` | `extraction/test_extraction.py` | P0 |

### AC13.8: Balance Progression & Currency Consistency

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.8.1 | Test consistent chain scores 10 | `test_consistent_chain()` | `extraction/test_extraction.py` | P0 |
| AC13.8.2 | Test inconsistent chain scores 0 | `test_inconsistent_chain()` | `extraction/test_extraction.py` | P0 |
| AC13.8.3 | Test single transaction | `test_single_txn()` | `extraction/test_extraction.py` | P0 |
| AC13.8.4 | Test no balance after | `test_no_balance_after()` | `extraction/test_extraction.py` | P0 |
| AC13.8.5 | Test empty list | `test_empty_list()` | `extraction/test_extraction.py` | P0 |
| AC13.8.6 | Test partial consistency | `test_partial_consistency()` | `extraction/test_extraction.py` | P0 |
| AC13.8.7 | Test all currencies match | `test_all_currencies_match()` | `extraction/test_extraction.py` | P0 |
| AC13.8.8 | Test no currencies match | `test_no_currencies_match()` | `extraction/test_extraction.py` | P0 |
| AC13.8.9 | Test no header currency | `test_no_header_currency()` | `extraction/test_extraction.py` | P0 |
| AC13.8.10 | Test no currencies in transactions | `test_no_currencies()` | `extraction/test_extraction.py` | P0 |
| AC13.8.11 | Test empty list (currency) | `test_empty_list()` | `extraction/test_extraction.py` | P0 |
| AC13.8.12 | Test mixed currencies partial | `test_mixed_currencies_partial()` | `extraction/test_extraction.py` | P0 |
| AC13.8.13 | Test missing currencies penalized | `test_missing_currencies_penalized()` | `extraction/test_extraction.py` | P0 |

### AC13.9: Confidence Scoring V2

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.9.1 | Test full score with all factors | `test_full_score_with_all_factors()` | `extraction/test_extraction.py` | P0 |
| AC13.9.2 | Test no new factors caps at 85 | `test_no_new_factors_caps_at_85()` | `extraction/test_extraction.py` | P0 |

### AC13.15: Under-Extraction Penalty (issue #967)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.15.1 | Brokerage statement with a single transaction is penalized below the review/auto-approve band | `test_brokerage_single_txn_penalized()` | `extraction/test_extraction.py` | P1 |
| AC13.15.2 | Brokerage statement with a plausible transaction count is not penalized | `test_brokerage_sufficient_txns_not_penalized()` | `extraction/test_extraction.py` | P1 |
| AC13.15.3 | Non-brokerage (bank) statement with one transaction keeps its existing score | `test_bank_single_txn_not_penalized()` | `extraction/test_extraction.py` | P1 |
| AC13.15.4 | `is_brokerage` defaults to False so existing callers are unaffected | `test_default_is_not_brokerage()` | `extraction/test_extraction.py` | P1 |
| AC13.15.5 | The cap uses the persisted transaction count (after skipped rows), not the raw extracted count | `test_effective_count_uses_persisted_not_extracted()` | `extraction/test_extraction.py` | P1 |

### AC13.18: Vision Extraction Falls Back to Secondary Models (issue #1034)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.18.1 | The vision model list appends `VISION_FALLBACK_MODELS` after the primary OCR/vision model, deduplicated and order-preserving, so more than one model is attempted on the vision path | `test_ocr_model_selection_helpers_deduplicate_vision_models()`, `test_vision_extraction_models_dedupes_fallback_against_primary()`, `test_vision_extraction_models_without_fallbacks_returns_primary_only()`, `test_extract_financial_data_shared_ocr_vision_skips_layout_parser()`, `test_extract_financial_data_dedicated_ocr_failure_falls_back_to_vision()` | `extraction/test_extraction_error_paths.py` | P1 |
| AC13.18.2 | When the primary vision model raises a non-retryable provider error (e.g. a 400), the vision path attempts the configured vision fallback model and succeeds instead of failing the upload | `test_vision_path_falls_back_to_secondary_model_on_non_retryable_error()` | `extraction/test_extraction_error_paths.py` | P1 |

### AC13.19: Tolerant Statement Date Parsing ([#1086](https://github.com/wangzitian0/finance_report/issues/1086))

A single empty/non-ISO date previously aborted the entire document parse, making
Chinese-format statements (`2025年01月15日`) unparseable and discarding an otherwise-good
multi-month statement on one bad row. A shared `_tolerant_parse_date` accepts common
non-ISO formats, and an unparseable transaction-row date is skip-and-flagged instead
of fatal.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.19.1 | Common non-ISO date formats parse; empty/garbage return None | `test_AC13_19_1_tolerant_parse_date_accepts_non_iso_formats` | `extraction/test_tolerant_date_parsing.py` | P1 |
| AC13.19.2 | A Chinese-format statement parses instead of being rejected | `test_AC13_19_2_chinese_format_statement_parses_instead_of_aborting` | `extraction/test_tolerant_date_parsing.py` | P1 |
| AC13.19.3 | One unparseable row date is non-fatal — the row is skipped, the rest parse | `test_AC13_19_3_one_bad_row_date_is_non_fatal` | `extraction/test_tolerant_date_parsing.py` | P1 |
| AC13.19.4 | The model is the primary date normalizer: the prompt instructs converting any source format to ISO YYYY-MM-DD (parser is only a fallback) | `test_AC13_19_4_parsing_prompt_instructs_iso_date_normalization` | `extraction/test_tolerant_date_parsing.py` | P1 |

### AC13.14: JSON-Repair Retry (issue #982)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.14.1 | A markdown json-fenced object (multi-line and single-line) is recovered | `test_strips_json_code_fence()`, `test_strips_single_line_fence()` | `extraction/test_json_repair.py` | P1 |
| AC13.14.2 | Surrounding prose and a bare fence reduce to the outermost balanced object | `test_strips_bare_code_fence_and_prose()`, `test_extract_financial_data_salvages_extra_text()` | `extraction/test_json_repair.py`, `extraction/test_extraction_flow.py` | P1 |
| AC13.14.3 | An already-clean object round-trips unchanged | `test_clean_object_is_preserved()` | `extraction/test_json_repair.py` | P1 |
| AC13.14.4 | Content with no recoverable JSON object returns None; braces inside strings do not truncate | `test_unrecoverable_returns_none()`, `test_does_not_misread_braces_in_strings()` | `extraction/test_json_repair.py` | P1 |
| AC13.14.5 | The extraction loop salvages a fenced response instead of rejecting the upload | `test_fenced_response_is_salvaged()`, `test_extract_financial_data_markdown_json()`, `test_extract_financial_data_json_markdown_fallback()` | `extraction/test_json_repair.py`, `extraction/test_extraction_flow.py`, `extraction/test_extraction_error_paths.py` | P1 |
| AC13.14.6 | A response with no recoverable JSON still fails through the model-chain path | `test_unrecoverable_response_still_fails()` | `extraction/test_json_repair.py` | P1 |
| AC13.14.7 | When a small example object precedes the real (larger) extraction, the largest object is recovered (not the example) | `test_prefers_largest_object_when_example_precedes_real()` | `extraction/test_json_repair.py` | P1 |
| AC13.14.8 | A complete object followed by trailing unbalanced-brace junk still recovers the complete object | `test_complete_object_then_trailing_unbalanced_brace()` | `extraction/test_json_repair.py` | P1 |
| AC13.14.9 | A leading unmatched brace (junk) before the real object does not stop the scan — the real object is recovered | `test_leading_unbalanced_brace_then_real_object()` | `extraction/test_json_repair.py` | P1 |

### AC13.10: Source Type Priority & Conflict Resolution

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.10.1 | Source type stamped on manual entry creation | `test_source_type_stamped_on_create` | `apps/backend/tests/reconciliation/test_source_type.py` | P0 |
| AC13.10.2 | Auto-match records trusted anchor without mutating posted source_type | `test_auto_match_records_anchor_without_mutating_posted_source_type` | `apps/backend/tests/reconciliation/test_source_type.py` | P0 |
| AC13.10.3 | Stage-1 approve promotes to user_confirmed | `test_stage1_approve_promotes_source_type` | `apps/backend/tests/extraction/test_source_type_promotion.py` | P0 |
| AC13.10.4 | Manual entry wins over auto_parsed in conflict | `test_manual_wins_conflict_resolution` | `apps/backend/tests/reconciliation/test_source_type.py` | P0 |
| AC13.10.5 | source_type cannot be downgraded | `test_source_type_no_downgrade` | `apps/backend/tests/reconciliation/test_source_type.py` | P1 |
| AC13.10.6 | All four source_type values accepted by API | `test_all_four_source_type_values_accepted_by_api` | `apps/backend/tests/reconciliation/test_source_type.py` | P1 |

### AC13.12: Source Coverage Matrix

The authoritative source-class registry is
[`source_coverage_matrix`](../ssot/source-coverage-matrix.yaml).

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.12.1 | Source coverage matrix covers every source class named by vision.md with owner EPICs, proof levels, ingestion path, review requirement, traceability target, and test anchors | `test_AC13_12_1_source_coverage_matrix_covers_vision_source_classes`, `test_AC13_12_1_source_coverage_matrix_rejects_non_list_required_classes_and_proof_levels` | `tests/tooling/test_source_coverage_matrix.py` | P0 |
| AC13.12.2 | Source coverage matrix rejects source classes whose only proof level is post-merge LLM/OCR unless an explicit exception is recorded | `test_AC13_12_2_source_coverage_matrix_rejects_llm_only_sources` | `tests/tooling/test_source_coverage_matrix.py` | P0 |
| AC13.12.3 | Source coverage matrix requires a gap issue for any source class still classified as a gap | `test_AC13_12_3_source_coverage_matrix_requires_gap_issue` | `tests/tooling/test_source_coverage_matrix.py` | P0 |

---

## 📌 Future Work (from Vision Recovery Audit)

The following item was identified during the vision.md recovery audit as a feature designed in vision but not yet tracked in this EPIC:

- **source_type Priority Logic** — Implemented for journal entries in #395. Remaining future source types such as CSV import should map into the same hierarchy instead of adding a parallel priority system.

## 🗄️ Archive Integration Notes

The useful EPIC-013 items from the removed `EPIC-ENCODING-SUMMARY.md` archive
snapshot are consolidated as current proof gaps. The removed inventory is
retained in [#548](https://github.com/wangzitian0/finance_report/issues/548):

- Institution auto-detection accepts omitted `institution` for PDF/image flows,
  but still needs provider-backed integration evidence that real document
  headers/logos produce the expected institution.
- Currency and running-balance display are delivered as V2 objectives, but UI
  tests should continue to prove the transaction table keeps those columns
  visible.
- V1 and V2 confidence scoring tests coexist; production paths should keep
  proving that V2 factors, including balance progression and currency
  consistency, are the active scoring path.

## 📏 Acceptance Criteria

- All extraction tests pass
- Lint/type checks pass
- PR is ready for review with SSOT + project docs updated

### AC13.11: Recovered Coverage

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.11.1 | Dual-write handles duplicate document hash / IntegrityError without failing. | `test_dual_write_layer2_integrity_error_is_non_fatal` | `extraction/test_extraction_error_paths.py` | P1 |
| AC13.11.2 | Dedup upsert sanitizes malformed source_documents payloads (transaction). | `test_upsert_atomic_transaction_handles_non_list_source_documents` | `extraction/test_deduplication.py` | P1 |

### AC13.13: Extraction Determinism (#989)

The AI vision model is not bit-reproducible and cannot be pinned in CI, but
everything *downstream* of the model response must be. Given identical extracted
model output, `confidence_score`, `status` (routing), `validation_error`, and the
resulting transaction set must be identical on every parse. These ACs pin that
seam so a regression that re-introduces non-determinism (dict/set iteration order,
unstable tie-breaking, unseeded randomness) in the scoring/routing pipeline fails
CI. Model-level reproducibility (the same PDF re-sent to the provider) is a
separate concern owned by the extraction-retry / temperature configuration, not
this gate.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.13.1 | Pure scoring + routing functions return identical results across N runs on the same input. | `test_scoring_and_routing_are_deterministic` | `extraction/test_extraction_determinism.py` | P0 |
| AC13.13.2 | Re-parsing identical model output yields identical confidence/status/validation_error across N parses. | `test_repeated_parse_yields_identical_confidence_status_validation` | `extraction/test_extraction_determinism.py` | P0 |
| AC13.13.3 | Each payload class (bank-valid, bank-balance-invalid, brokerage) routes consistently across N parses. | `test_routing_is_consistent_per_payload_class` | `extraction/test_extraction_determinism.py` | P0 |

### AC13.21: Balance-Mismatch Statement Lifecycle (#1141, folds #1085 + #1087)

A bank statement that parses cleanly but whose running balance does not reconcile
must **not** be parked in `uploaded` (a dead-end that the retry endpoint rejects
and the report-readiness query ignores). It must enter the same reviewable resting
state as a brokerage statement: `PARSED` with `stage1_status=PENDING_REVIEW` and a
`validation_error` describing the mismatch. This makes balance-invalid bank
statements retriable (AC13.21.3), visible to readiness (AC13.21.4), and
deterministic (AC13.21.5). CSV intake with a missing institution must fail
synchronously at upload with HTTP 400 instead of accepting (202) and then
rejecting asynchronously (AC13.21.6).

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.21.1 | `route_by_threshold` routes a balance-invalid bank statement to `PARSED` (review), never `uploaded`, regardless of score. | `test_AC13_21_1_balance_invalid_routes_to_parsed_review` | `accounting/test_validation.py` | P0 |
| AC13.21.2 | A parsed bank statement that fails balance reconciliation lands in `PARSED` with `stage1_status=PENDING_REVIEW` and a `validation_error`. | `test_AC13_21_2_balance_invalid_parse_is_pending_review` | `extraction/test_extraction_determinism.py` | P0 |
| AC13.21.3 | The retry endpoint accepts a balance-invalid statement at its `PARSED` resting state. | `test_AC13_21_3_retry_accepts_parsed_resting_state` | `api/test_statements_router.py` | P0 |
| AC13.21.4 | Report readiness counts the balance-invalid `PARSED` statement as an available input. | `test_AC13_21_4_readiness_counts_parsed_balance_invalid` | `accounting/test_validation.py` | P1 |
| AC13.21.5 | The same balance-mismatch payload routes to the same `PARSED` status deterministically across N parses. | `test_routing_is_consistent_per_payload_class` | `extraction/test_extraction_determinism.py` | P0 |
| AC13.21.6 | CSV upload with a missing institution fails synchronously with HTTP 400 and an actionable message. | `test_AC13_21_6_csv_missing_institution_rejected_sync` | `api/test_statements_router.py` | P0 |

### AC13.16: Deterministic Decoding — Request Seed (issue #989)

Complements AC13.13 (downstream determinism). AC13.13 pins everything *after* the
model response; this AC pins the *request* so the model itself decodes
reproducibly: temperature 0 / `do_sample` false, plus an optional fixed `seed`
(`AI_JSON_SEED`) forwarded to the provider. The seed is **off by default**
because Z.AI/GLM validates params strictly and some models (e.g. the default
`glm-4.6v`) reject `seed` with HTTP 400; it is opt-in for seed-supporting models.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.16.1 | A provided seed is forwarded in the streaming request payload | `test_stream_ai_json_includes_seed_when_provided()` | `ai/test_ai_streaming.py` | P1 |
| AC13.16.2 | Extraction forwards the configured `ai_json_seed` to the model call | `test_extraction_forwards_configured_seed()` | `extraction/test_seed_determinism.py` | P1 |
| AC13.16.3 | Extraction pins `temperature=0` / `do_sample=False` alongside the seed | `test_extraction_decoding_is_deterministic_by_default()` | `extraction/test_seed_determinism.py` | P1 |
| AC13.16.4 | Empty `AI_JSON_SEED` parses as None (omitted) instead of raising | `test_empty_seed_env_is_treated_as_none()` | `extraction/test_seed_determinism.py` | P1 |
| AC13.16.5 | The seed is off (None) by default so it is never sent to providers that reject it (e.g. glm-4.6v) | `test_seed_is_off_by_default()` | `extraction/test_seed_determinism.py` | P1 |

### AC13.17: Balance-Aware Self-Consistency Re-extract (issue #989 Step B)

Step A (AC13.16) makes a single decode reproducible; this AC adds the
**self-consistency** half. When a bank statement's running-balance chain fails to
reconcile, `_extract_with_balance_retry` re-extracts up to
`AI_EXTRACT_MAX_ATTEMPTS` times — each attempt with a *varied* seed (configured
seed, then +1, +2 …) so retries are different-but-reproducible samples — and keeps
the first parse that reconciles before the statement would route to `uploaded`.
Brokerage payloads are never retried (they reconcile via Layer-2 positions, not a
running-balance chain); if no attempt reconciles, the smallest-difference result is
kept so routing is unchanged. Only failing parses retry, so average cost is bounded.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.17.1 | A reconciling first parse is returned without retry | `test_reconciles_first_attempt_single_call()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.2 | A failing parse is retried and the reconciling result wins | `test_retries_until_reconciles()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.3 | When no attempt reconciles, the smallest-difference result is kept | `test_keeps_best_when_none_reconcile()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.4 | Brokerage payloads are not retried | `test_brokerage_is_not_retried()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.5 | Attempt 0 uses the configured seed; retries vary it (seed+1, seed+2 …) | `test_seed_varies_per_attempt()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.6 | `AI_EXTRACT_MAX_ATTEMPTS=1` keeps single-shot behavior | `test_max_attempts_one_disables_retry()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.7 | A structurally-invalid parse (balance uncomputable, difference 0) does not win "best" over a numerically-close parse | `test_structurally_invalid_parse_does_not_win_as_best()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.8 | If every attempt is structurally invalid, the last parse is returned so `parse_document` reports the failure | `test_all_invalid_returns_last_parse()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.9 | A transient extraction error on a retry attempt keeps the earlier usable parse (no upload regression) | `test_transient_retry_error_keeps_earlier_usable_parse()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.10 | If every attempt raises, the error propagates so the upload fails as in the single-call path | `test_all_attempts_error_reraises()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.11 | A transient error on the first attempt does not abort; a later reconciling attempt is returned | `test_first_attempt_error_then_success_recovers()` | `extraction/test_self_consistency.py` | P1 |
| AC13.17.12 | An error after an earlier usable parse keeps trying remaining attempts; a later reconciling parse still wins | `test_error_mid_run_does_not_skip_remaining_attempts()` | `extraction/test_self_consistency.py` | P1 |

### AC13.20: Running-Balance Chain-Break Detector + Repair-Pass Hook (root [#1140](https://github.com/wangzitian0/finance_report/issues/1140))

Bank-statement **under-extraction**: the per-currency self-check correctly flags
`opening + ΣIN − ΣOUT ≠ closing` when rows are dropped, but recall is the
underlying problem and recall is probabilistic (LLM) — it cannot be turned into a
hard CI gate. This AC delivers the **deterministic, testable** slice around that
soft metric:

- **AC-C1 (detector)** — a pure, `Decimal`-based function walks the ordered
  transactions' running `balance_after` chain and returns the exact index/region
  where `balance_after[i-1] + signed_amount[i] != balance_after[i]` (within
  `BALANCE_TOLERANCE`), pinpointing where a row was missed/misparsed. No floats,
  no model call, fully reproducible.
- **AC-C2 (repair-pass hook)** — orchestration + decision logic keyed off the
  self-check delta: when the balance self-check fails *and* the detector finds a
  break, a region-targeted re-extract is attempted exactly once before
  finalizing. The actual re-extraction is behind an injectable interface so CI
  exercises the trigger logic without a live model; it is a safe no-op when there
  is no detector signal or no repair backend is wired.
- **AC-C3 (regression fixture)** — a synthetic clean bank-statement shape with a
  deliberately-dropped row, asserting the detector finds the correct break index
  and the repair hook is invoked.

Extraction **recall** stays a **soft metric** (tracked, no hard CI gate); the
self-check balance guard and these deterministic seams stay hard-tested.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC13.20.1 | AC-C1: detector pinpoints the exact break index on a crafted chain with a dropped row | `test_AC13_20_1_detector_finds_break_index_on_dropped_row()` | `extraction/test_chain_break_repair.py` | P1 |
| AC13.20.2 | AC-C1: a clean running-balance chain reports no break | `test_AC13_20_2_clean_chain_reports_no_break()` | `extraction/test_chain_break_repair.py` | P1 |
| AC13.20.3 | AC-C1: detection is Decimal-based and tolerant within `BALANCE_TOLERANCE` (no float drift) | `test_AC13_20_3_detector_is_decimal_tolerant()` | `extraction/test_chain_break_repair.py` | P1 |
| AC13.20.4 | AC-C2: on balance mismatch with a detected break, the repair hook is invoked exactly once | `test_AC13_20_4_repair_hook_invoked_once_on_mismatch()` | `extraction/test_chain_break_repair.py` | P1 |
| AC13.20.5 | AC-C2: a clean/reconciling chain never invokes the repair hook | `test_AC13_20_5_repair_hook_not_invoked_on_clean_chain()` | `extraction/test_chain_break_repair.py` | P1 |
| AC13.20.6 | AC-C2: when no repair backend is injected, the hook is a safe no-op returning the original payload | `test_AC13_20_6_repair_is_safe_noop_without_backend()` | `extraction/test_chain_break_repair.py` | P1 |
| AC13.20.7 | AC-C3: the synthetic dropped-row fixture drives the detector to the correct index and triggers the repair hook | `test_AC13_20_7_regression_fixture_detects_and_repairs()` | `extraction/test_chain_break_repair.py` | P1 |
