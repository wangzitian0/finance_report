# EPIC-004: Reconciliation Engine & Matching

> **Status**: ✅ Complete (TDD Aligned)
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

### AC4.4: Performance & Edge Cases

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.4.1 | Large Batch Performance (1,000 txns) | `test_batch_1000_transactions_reasonable_time` | `reconciliation/test_performance.py` | P1 |
| AC4.4.2 | Cross-Period Matching | `test_month_end_to_month_start_match` | `reconciliation/test_performance.py` | P1 |

### AC4.5: Anomaly Detection

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC4.5.1 | Anomaly Detection Core | `test_detect_anomalies_flags_expected_patterns` | `reconciliation/test_reconciliation_engine.py` | P2 |

**Traceability Result**:
- Total AC IDs: 12
- Requirements converted to AC IDs: 100% (EPIC-004 checklist + must-have standards)
- Requirements with test references: 100%
- Test files: 5

---

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
| **0.1 USD Threshold** | P1 | Add specific boundary test for 0.10 tolerance |
| ML-based weight auto-tuning | P2 | v2.0 |
| Multi-currency matching | P2 | After EPIC-005 |

---

## Issues & Gaps

- [ ] Explicit 0.1 USD tolerance check is implicit in scoring but needs a dedicated boundary test.

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
