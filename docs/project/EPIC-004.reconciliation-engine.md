# EPIC-004: Reconciliation Engine & Matching

> **Status**: ✅ Complete (TDD Aligned)
> **Vision Anchor**: `decision-4-two-stage-review`
> **Phase**: 3
> **Duration**: 5 weeks
> **Dependencies**: EPIC-003

---

## 🎯 Objective

Automatically match bank transactions with journal entries, implementing intelligent reconciliation and review queue, achieving ≥95% automatic matching accuracy.

**Core Rules**:
```
≥ 85 points  → Auto-accept
60-84 points → Review queue
< 60 points  → Unmatched
```

---

## Macro Proof Ownership

- `source-ledger-report-traceability`

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🔗 **Reconciler** | Matching algorithm | Multi-dimensional weighted scoring, adjustable thresholds, supports one-to-many/many-to-one |
| 🏗️ **Architect** | System design | Independent matching engine service, supports batch processing and incremental matching |
| 📊 **Accountant** | Business logic | Account type combinations must follow accounting logic (e.g., salary = Bank + Income) |
| 💻 **Developer** | Performance requirements | 10,000 transactions matched in < 10s, supports parallel processing |
| 🧪 **Tester** | Accuracy verification | False positive rate < 0.5%, false negative rate < 2% |
| 📋 **PM** | User experience | Efficient and user-friendly review queue, batch operation support |

---

## ✅ Task Checklist

### Data Model (Backend)

- [x] `ReconciliationMatch` model
- [x] Alembic migration script
- [x] Status update trigger

### Matching Algorithm (Backend)

- [x] `services/reconciliation.py` - Reconciliation engine
  - [x] `calculate_match_score()` - Composite scoring
  - [x] `find_candidates()` - Find candidate journal entries
  - [x] `execute_matching()` - Batch matching execution
  - [x] `auto_accept()` - Auto-accept logic
- [x] Scoring dimension implementation
  - [x] `score_amount()` - Amount matching (40%)
  - [x] `score_date()` - Date proximity (25%)
  - [x] `score_description()` - Description similarity (20%)
  - [x] `score_business_logic()` - Business logic validation (10%)
  - [x] `score_pattern()` - Historical pattern (5%)
- [x] Special scenario handling
  - [x] One-to-many matching (1 bank txn → multiple journal entries)
  - [x] Many-to-one matching (multiple bank txns → 1 journal entry)
  - [x] Cross-period matching (month-end/month-start)
  - [x] Fee splitting

### Review Queue (Backend)

- [x] `services/review_queue.py` - Review queue management
  - [x] `get_pending_items()` - Get pending items (pagination, sorting)
  - [x] `accept_match()` - Accept match
  - [x] `reject_match()` - Reject match
  - [x] `batch_accept()` - Batch accept

### Anomaly Detection (Backend)

- [x] `services/anomaly.py` - Anomaly detection
  - [x] Amount anomaly (> 10x monthly average)
  - [x] Frequency anomaly (same merchant > 5 transactions/day)
  - [x] Time anomaly (large amounts during non-business hours)
  - [x] New merchant flagging

### API Endpoints (Backend)

- [x] `POST /reconciliation/run` - Execute matching
- [x] `GET /reconciliation/matches` - Match results
- [x] `GET /reconciliation/pending` - Pending queue
- [x] `POST /reconciliation/matches/{id}/accept` - Accept
- [x] `POST /reconciliation/matches/{id}/reject` - Reject

### Frontend UI (Frontend)

- [x] `/reconciliation` - Reconciliation workbench
- [x] `/reconciliation/unmatched` - Unmatched handling
- [x] Visualization (progress bar, score distribution)

---

## 🧪 Test Cases

> **Test Organization**: Tests organized by feature blocks using ACx.y.z numbering.
> **Coverage**: See `apps/backend/tests/reconciliation/`

### AC4.1: Matching Core

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.1.1 | Exact Matching | `test_score_amount_branches` | `reconciliation/test_reconciliation_scoring.py` | P0 |
| AC4.1.2 | Fuzzy Date Matching | `test_score_date_branches` | `reconciliation/test_reconciliation_scoring.py` | P0 |
| AC4.1.3 | Amount Tolerance | `test_score_amount_tiers` | `reconciliation/test_reconciliation_coverage_boost.py` | P0 |
| AC4.1.4 | Description Similarity | `test_normalize_and_description_scoring` | `reconciliation/test_reconciliation_scoring.py` | P1 |

### AC4.2: Group Matching (Many-to-One / One-to-Many)

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.2.1 | Many-to-One (Batch Payment) | `test_execute_matching_many_to_one_group` | `reconciliation/test_reconciliation_engine.py` | P0 |
| AC4.2.2 | Many-to-One Bonus | `test_calculate_match_score_many_to_one_bonus` | `reconciliation/test_reconciliation_scoring.py` | P1 |
| AC4.2.3 | One-to-Many (Split) | `test_execute_matching_multi_entry_combinations` | `reconciliation/test_reconciliation_engine.py` | P1 |

### AC4.3: Review Queue & Status

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.3.1 | Auto-Accept Logic | `test_auto_accept_threshold` | `reconciliation/test_reconciliation_engine.py` | P0 |
| AC4.3.2 | Review Queue Logic | `test_review_queue_actions_and_entry_creation` | `reconciliation/test_reconciliation_engine.py` | P0 |
| AC4.3.3 | Batch Accept | `test_accept_reject_batch_accept` | `reconciliation/test_reconciliation_router_additional.py` | P1 |
| AC4.3.4 | Test accepting a reconciliation match. | `test_accept_match_success` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.5 | Test accepting non-existent match. | `test_accept_match_not_found` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.6 | Test rejecting a reconciliation match. | `test_reject_match_success` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.7 | Test rejecting non-existent match. | `test_reject_match_not_found` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.8 | Test getting reconciliation statistics. | `test_reconciliation_stats_success` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.9 | Test listing unmatched transactions. | `test_list_unmatched_success` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.10 | Test creating journal entry from unmatched transaction. | `test_create_entry_from_unmatched_success` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.11 | Test creating entry from non-existent transaction. | `test_create_entry_from_unmatched_not_found` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.12 | Test that unauthenticated clients cannot access reconciliation endpoints. | `test_unauthenticated_access` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.13 | Test that users can only access their own reconciliation data. | `test_user_isolation` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.14 | Test batch creating entries for all unmatched transactions. | `test_batch_create_entries_for_all_unmatched` | `api/test_reconciliation_router.py` | P1 |
| AC4.3.15 | Test batch create returns 400 without all/txn_ids filter. | `test_batch_create_entries_requires_filter` | `api/test_reconciliation_router.py` | P1 |

### AC4.4: Performance & Edge Cases

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.4.1 | Large Batch Performance (1,000 txns) | `test_batch_1000_transactions_reasonable_time` | `reconciliation/test_performance.py` | P1 |
| AC4.4.2 | Cross-Period Matching | `test_month_end_to_month_start_match` | `reconciliation/test_performance.py` | P1 |

### AC4.5: Anomaly Detection

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.5.1 | Anomaly Detection Core | `test_detect_anomalies_flags_expected_patterns` | `reconciliation/test_reconciliation_engine.py` | P2 |
| AC4.5.2 | Test listing anomalies for non-existent transaction. | `test_list_anomalies_not_found` | `api/test_reconciliation_router.py` | P1 |

### AC4.6: Source Type Conflict & Transfer Detection

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.6.1 | 0.1 USD boundary: amount delta = 0.10 USD passes, 0.11 USD fails | `test_amount_tolerance_0_10_boundary` | `reconciliation/test_reconciliation_scoring.py` | P0 |
| AC4.6.2 | Transfer detection: matching OUT/IN within ±3 days not mis-reconciled | `test_transfer_pair_not_double_counted` | `reconciliation/test_reconciliation_engine.py` | P0 |
| AC4.6.3 | source_type=manual wins over auto_matched in conflict | `test_manual_source_wins_reconciliation` | `reconciliation/test_source_type.py` | P0 |
| AC4.6.4 | Stage 2 batch approve blocked when duplicate flags unresolved | `test_batch_approve_blocked_by_duplicate` | `reconciliation/test_review_workflow.py` | P1 |
| AC4.6.5 | Reconciliation score considers source_type weight (manual > auto) | `test_source_type_weight_in_scoring` | `reconciliation/test_reconciliation_scoring.py` | P1 |
| AC4.6.6 | Duplicate guard respects running balance: same date/description/amount/direction with different `balance_after` are NOT flagged as duplicate candidates | `test_duplicate_guard_distinguishes_by_balance_after` | `review/test_statement_validation.py` | P1 |
| AC4.6.7 | Duplicate guard still flags same date/description/amount/direction when `balance_after` is equal or absent (ambiguous, needs review) | `test_duplicate_guard_flags_when_balance_after_equal_or_absent` | `review/test_statement_validation.py` | P1 |
| AC4.6.8 | `AtomicTransaction` persists the extracted `balance_after` so the conflict guard can disambiguate distinct-but-identical transactions | `test_upsert_persists_balance_after` | `extraction/test_deduplication.py` | P1 |
| AC4.6.9 | Layer-2 reconciliation writes atomic_txn_id and supports transfer-pair logging. | `test_execute_matching_many_to_one_layer2_sets_atomic_txn_id` | `reconciliation/test_reconciliation_engine.py` | P1 |

### AC4.8: Archive Baseline Benchmark Ownership

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.8.1 | Archive baseline benchmark residual is explicitly owned by EPIC-004 until synthetic accuracy and performance proof exists | `test_AC4_8_1_reconciliation_benchmark_residual_is_epic_owned` | `tests/tooling/test_archive_residual_epic_ownership.py` | P1 |

### AC4.9: Bank-Side Amount Matching

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.9.1 | Reconciliation amount scoring uses the bank/cash account line, not total entry debits | `test_AC4_9_1_entry_total_uses_bank_side_line_for_outflow()` | `reconciliation/test_reconciliation_financial_logic.py` | P0 |
| AC4.9.2 | Retrying an accepted match is idempotent and does not mutate version or duplicate posting side effects | `test_accept_match_retry_is_idempotent_after_success` | `api/test_statements_router.py` | P0 |
| AC4.9.3 | Auto-posted statement entries satisfy the same posting invariants as regular journal posting | `test_create_entry_from_txn_auto_post_rejects_inactive_statement_account` | `api/test_statements_router.py` | P0 |
| AC4.9.4 | Stage 2 review queue confidence tier is derived from the actual reconciliation score | `test_get_stage2_review_queue_with_pending_match`, `test_ac4_9_4_derive_reconciliation_score_tier` | `api/test_statements_router.py`, `services/test_confidence_tier.py` | P1 |

### AC4.10: Reconciliation Accuracy Audit Harness

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.10.1 | Deterministic reconciliation audit harness emits JSON and Markdown reports with accuracy, false-positive, false-negative, review-routing, unmatched, and runtime metrics | `test_AC4_10_1_reconciliation_audit_report_schema_and_outputs` | `tests/tooling/test_reconciliation_audit.py` | P0 |
| AC4.10.2 | Audit diagnostics list intentional false positives or wrong auto-accepts with expected-vs-actual route, entry IDs, score, and failure type | `test_AC4_10_2_reconciliation_audit_reports_intentional_false_positive` | `tests/tooling/test_reconciliation_audit.py` | P0 |
| AC4.10.3 | CI treats reconciliation audit JSON/Markdown as a hard gate for the EPIC-004 accuracy, false-positive, false-negative, and 10,000-transaction runtime targets | `test_AC4_10_3_ci_gates_reconciliation_audit_thresholds` | `tests/tooling/test_reconciliation_audit.py` | P0 |

### AC4.11: Decimal-Safe Unmatched Review UI

Unmatched transaction triage may create ledger entries, so monetary values shown
in the queue and created-entry confirmation must use the same Decimal-safe
frontend formatting contract as other accounting surfaces.
See: docs/ssot/accounting.md#decimal-rule

| AC | Acceptance Criteria | Test(s) | File(s) | Priority |
|----|--------------------|---------|---------|----------|
| AC4.11.1 | The unmatched transaction board models unmatched amounts as shared `MoneyValue` payloads and renders queue/detail/created-entry amounts through Decimal-safe currency formatting, not JavaScript number locale formatting | `AC4.11.1 renders unmatched monetary amounts with Decimal-safe currency formatting` | `frontend/src/__tests__/unmatchedBoardComponent.test.tsx` | P0 |

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Auto-match accuracy ≥ 95%** | `test_performance.py` | 🔴 Critical |
| **False positive rate < 0.5%** | `test_reconciliation_scoring.py` | 🔴 Critical |
| **False negative rate < 2%** | `test_reconciliation_scoring.py` | 🔴 Critical |
| Configurable thresholds | `test_auto_accept_threshold` | Required |
| Many-to-one matching support | `test_many_to_one_grouping` | Required |
| Batch process 10,000 txns < 10s | `test_batch_1000_transactions_reasonable_time` (1,000 txns verified) | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| Auto-match rate > 70% | (Real data) | ⏳ |
| Review queue avg processing < 30s/txn | (Real data) | ⏳ |
| Anomaly detection recall > 95% | `test_anomaly.py` (Planned) | ⏳ |

### 🚫 Not Acceptable Signals

- False positive rate > 2%
- Accuracy < 90%
- Performance timeout (batch > 60s)
- Severe review queue backlog

---

## 📚 SSOT References

- [schema.md](../ssot/schema.md) - ReconciliationMatch table
- [reconciliation.md](../ssot/reconciliation.md) - Reconciliation rules

---

## 🔗 Deliverables

- [x] `apps/backend/src/models/reconciliation.py`
- [x] `apps/backend/src/services/reconciliation.py`
- [x] `apps/backend/src/services/review_queue.py`
- [x] `apps/backend/src/services/anomaly.py`
- [x] `apps/backend/src/routers/reconciliation.py`
- [x] `apps/frontend/app/reconciliation/page.tsx`
- [x] `apps/backend/tests/reconciliation/` - Test suite

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| **0.1 USD Threshold** | ✅ Done (AC4.6.1) | Boundary test is registered in `reconciliation/test_reconciliation_scoring.py` |
| ML-based weight auto-tuning | P2 | v2.0 |
| Multi-currency matching | P2 | After EPIC-005 |

---

## Issues & Gaps

- [x] Explicit 0.1 USD tolerance check is covered by AC4.6.1 and
      `test_amount_tolerance_0_10_boundary`.
- [x] Archive baseline benchmark residual is explicitly owned by EPIC-004 and
      now closed through AC4.10.3. The hard-gated audit runs
      `python tools/reconciliation_audit.py --stdout`, includes a
      100-transaction manual false-positive audit plus 10,000-transaction
      benchmark evidence, and fails CI when the `>=95%`, `<0.5%`, `<2%`, or
      `<10s` targets are missed. Current traceability review also uses
      `python tools/analyze_test_ac_coverage.py --stdout` and
      `python tools/check_ac_index.py`.

## 🗄️ Archive Integration Notes

The removed `EPIC-004.reconciliation-accuracy-report.md` archive snapshot is
folded into this EPIC as a historical baseline; the removed inventory is
retained in [#548](https://github.com/wangzitian0/finance_report/issues/548).
Scoring dimensions, threshold routing, review queue flow, and anomaly handling
were implemented, but the old archive had pending accuracy and performance
measurements. Current work should add AC or test evidence rather than
hand-maintained accuracy prose.

## 📄 Owned Documentation Surfaces

These non-EPIC docs are part of this EPIC's maintained surface:

- [../user-guide/reconciliation.md](../user-guide/reconciliation.md) — matching, review, and unmatched transaction workflow.
- [../reference/api.md](../reference/api.md) — generated reconciliation API reference.

---

## ❓ Q&A (Clarification Required)

### Q1: Are matching thresholds adjustable?
> **Decision**: Use fixed thresholds in v1.0 (Auto > 85, Review 60-84).

### Q2: Unmatched transaction handling workflow
> **Decision**: AI-driven journal entry recommendations + time-aware rules.

### Q3: Duplicate matching detection
> **Decision**: Dual-layer event model - Immutable raw layer + Mutable analysis layer.

### Q4: Batch operation safety restrictions
> **Decision**: Tiered batch operation strategy (High score batch, Low score manual).

### Q5: Historical pattern learning
> **Decision**: Embedding-driven intelligent matching (simple and efficient).

---

## 📅 Timeline

| Phase | Content | Status |
|------|------|----------|
| Week 1 | Data model + Basic matching algorithm | ✅ Done |
| Week 2 | Scoring dimensions + Special scenarios | ✅ Done |
| Week 3 | Review queue + Anomaly detection | ✅ Done |
| Week 4 | Frontend UI + Algorithm tuning + Testing | ✅ Done |
| Week 5 | Embedding integration + Time-aware rules | ✅ Done |

### AC4.7: Recovered Coverage

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.7.1 | POST /corrections persists a correction and /corrections/stats reflects it. | `test_post_create_correction_and_stats` | `api/test_corrections_router.py` | P1 |
| AC4.7.2 | get_few_shot_examples respects default limit and caches results. | `test_get_few_shot_examples_cache_hit_and_limit` | `extraction/test_correction_service_cache.py` | P1 |
| AC4.7.3 | Reconciliation phase-2 – 3-entry combo exceeding tolerance is skipped. | `test_execute_matching_three_entry_combination_skips_unbalanced_member` | `reconciliation/test_reconciliation_engine.py` | P1 |
| AC4.7.4 | Reconciliation phase-2 – atomic match and transfer pair logging in layer-2. | `test_execute_matching_layer2_atomic_match_and_transfer_pair_logging` | `reconciliation/test_reconciliation_engine.py` | P1 |

### AC4.12: Reconciliation UUID-Typed Path Params ([#1008](https://github.com/wangzitian0/finance_report/issues/1008))

Tier 2 of #1000. The `match_id` and `txn_id` path params in
`apps/backend/src/routers/reconciliation.py` are typed as `UUID`, so a malformed
id is rejected with 422 at the boundary instead of reaching the query layer as an
arbitrary string.

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.12.1 | A non-UUID `match_id` on accept returns 422 | `test_AC4_12_1_accept_match_malformed_uuid_returns_422` | `api/test_typed_contract_sweep.py` | P2 |
| AC4.12.2 | A non-UUID `txn_id` on create-entry returns 422 | `test_AC4_12_2_create_entry_malformed_uuid_returns_422` | `api/test_typed_contract_sweep.py` | P2 |
