# EPIC-016: Two-Stage Review & Data Validation UI

> **Status**: 🟡 Planned  
> **Phase**: 3 (Reconciliation Enhancement)  
> **Duration**: 4-6 weeks  
> **Priority**: P0 (Critical - Foundation for User Adoption)  
> **Dependencies**: EPIC-003 (Statement Parsing), EPIC-004 (Reconciliation Engine)

---

## 🎯 Objective

Implement a **two-stage review workflow** with dedicated UI to ensure data accuracy before reconciliation. This addresses the critical gap between statement import and reconciliation that causes user abandonment in personal finance apps.

**Core Workflow**:
```
Stage 1: Record-Level Review (PDF vs Parsed)
  → Is this statement parsed correctly?
  → Balance validation with 0.001 USD tolerance
  
Stage 2: Run-Level Review (Consistency Checks)
  → Is the whole batch consistent?
  → Deduplication, transfer pairing, anomaly detection
```

**Success Criteria**:
- Users can visually verify parsed data against original PDFs
- Balance discrepancies (> 0.001 USD) block approval
- Duplicate transactions flagged before reconciliation
- Transfer pairs detected across accounts
- Time-series anomalies surfaced for manual review

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🏗️ **Architect** | System Design | Two-stage separation ensures data quality before reconciliation. Stage 1 UI = trust anchor. |
| 📊 **Accountant** | Data Integrity | 0.001 USD tolerance is critical for multi-currency precision. Balance chain validation prevents cascading errors. |
| 💻 **Developer** | Implementation | Reuse `review_queue.py` backend, add frontend split-view component. Consistency checks extend reconciliation service. |
| 🧪 **Tester** | Validation | Test: balance validation, dedup detection, transfer pairing, boundary cases (0.001 tolerance edge). |
| 📋 **PM** | User Experience | Stage 1 UI is **adoption blocker**. Users won't trust auto-reconciliation without visual verification. Industry best practice (GnuCash, Firefly III). |
| 🎨 **Designer** | UI/UX | Split-view pattern (PDF left, parsed right). Visual diff for balance mismatches. Batch operations in Stage 2. |

---

## ✅ Task Checklist

### Phase 1: Stage 1 (Record-Level Review) — 2-3 weeks

#### Data Model (Backend)
- [ ] Extend `BankStatement` model with `stage1_status` field
  - Values: `pending_review`, `approved`, `rejected`, `edited`
  - Add `reviewed_at`, `reviewed_by` audit fields
- [ ] Add `balance_validation_result` JSONB field
  - Store opening/closing balance validation results
  - Include tolerance delta, validation timestamp
- [ ] Update Alembic migration script

#### Backend Services
- [ ] `services/statement_validation.py` — Statement validation service
  - [ ] `validate_balance_chain(statement_id)` — Opening/closing balance chain validation
    - Starting balance = previous closing balance (or manual entry for first statement)
    - Ending balance = starting balance + sum(transactions)
    - Tolerance: **0.001 USD** (not 0.10 USD)
  - [ ] `calculate_balance_delta()` — Calculate actual vs expected balance
  - [ ] `approve_statement(statement_id, user_id)` — Approve statement (Stage 1 → Stage 2)
  - [ ] `reject_statement(statement_id, user_id, reason)` — Reject statement (trigger re-parsing)
  - [ ] `edit_and_approve(statement_id, edits, user_id)` — Edit transactions and approve
- [ ] Extend `services/review_queue.py` to support Stage 1 items
  - [ ] `get_stage1_pending()` — Get statements pending Stage 1 review
  - [ ] `mark_stage1_complete(statement_id)` — Move statement to Stage 2 queue

#### API Endpoints
- [ ] `GET /api/statements/{id}/review` — Get statement with parsed data and validation results
  - Return: statement metadata, parsed transactions, balance validation, PDF URL (MinIO)
- [ ] `POST /api/statements/{id}/approve` — Approve statement (Stage 1)
  - Validate balance chain with 0.001 USD tolerance
  - Update `stage1_status` to `approved`
  - Trigger Stage 2 queue addition
- [ ] `POST /api/statements/{id}/reject` — Reject statement
  - Update `stage1_status` to `rejected`
  - Trigger re-parsing with manual fallback flag
- [ ] `POST /api/statements/{id}/edit` — Edit transactions and approve
  - Update transactions, recalculate balance
  - If balance valid (tolerance 0.001 USD) → approve
- [ ] `GET /api/statements/pending-review` — List statements pending Stage 1 review

#### Frontend UI
- [ ] `/statements/{id}/review` — Stage 1 Review Page
  - [ ] Left panel: PDF viewer (MinIO URL)
    - Highlight current page (statement period)
    - Page navigation controls
  - [ ] Right panel: Parsed transaction list
    - Table: Date, Description, Amount, Currency
    - Editable rows (inline edit for corrections)
    - Balance summary (opening, closing, calculated)
  - [ ] Balance validation indicator
    - Green: Balance matches (delta < 0.001 USD)
    - Red: Balance mismatch (show delta)
    - Warning: Manual review required
  - [ ] Action buttons
    - Approve (disabled if balance invalid)
    - Reject (with reason dropdown)
    - Edit & Approve (enable inline editing)
  - [ ] Navigation: Previous/Next pending statement

#### Tests
- [ ] `test_validate_balance_chain_exact_match()` — Exact balance match
- [ ] `test_validate_balance_chain_within_tolerance()` — Delta = 0.0009 USD (pass)
- [ ] `test_validate_balance_chain_exceeds_tolerance()` — Delta = 0.0011 USD (fail)
- [ ] `test_approve_statement_success()` — Approve with valid balance
- [ ] `test_approve_statement_invalid_balance_fails()` — Reject invalid balance
- [ ] `test_edit_and_approve()` — Edit transaction amount, recalculate, approve
- [ ] `test_reject_statement_triggers_reparse()` — Rejection flow

---

### Phase 2: Stage 2 (Run-Level Review + Consistency Checks) — 2-3 weeks

#### Data Model (Backend)
- [ ] Create `ConsistencyCheck` model
  - Fields: `id`, `user_id`, `check_type` (dedup/transfer/anomaly), `status`, `details` (JSONB)
  - Link to `atomic_transactions` or `BankStatement`
- [ ] Add `stage2_status` to `ReconciliationMatch` model
  - Values: `pending_review`, `approved`, `rejected`

#### Backend Services
- [ ] `services/consistency_checks.py` — Consistency check service
  - [ ] `detect_duplicates(user_id, date_range)` — Deduplication detection
    - Find transactions with same amount, date (±1 day), similar description
    - Use existing `dedup_hash` logic from `atomic_transactions`
    - Return: list of duplicate groups with confidence scores
  - [ ] `detect_transfer_pairs(user_id, date_range)` — Transfer pair detection
    - Find matching OUT/IN transactions across accounts
    - Amount match (tolerance 0.001 USD), date proximity (±3 days)
    - Return: list of transfer pairs with confidence scores
  - [ ] `detect_anomalies(user_id, date_range)` — Time-series anomaly detection
    - Reuse `services/anomaly.py` from EPIC-004
    - Detect: sudden balance jumps, frequency spikes, large amounts
    - Return: list of anomalies with severity
  - [ ] `run_consistency_checks(statement_id)` — Run all checks for statement
  - [ ] `resolve_check(check_id, action, user_id)` — Resolve check (approve/reject/flag)

#### API Endpoints
- [ ] `GET /api/reconciliation/review-queue` — Get Stage 2 review queue
  - Return: pending reconciliation matches, consistency check results
  - Support pagination, filtering (by check type, severity)
- [ ] `POST /api/reconciliation/review-queue/batch-approve` — Batch approve matches
  - Accept list of match IDs
  - Validate all consistency checks resolved
  - Create journal entries for approved matches
- [ ] `POST /api/reconciliation/review-queue/batch-reject` — Batch reject matches
- [ ] `POST /api/consistency-checks/{id}/resolve` — Resolve consistency check
  - Actions: `approve` (ignore), `reject` (fix), `flag` (manual review)
- [ ] `GET /api/consistency-checks` — List consistency checks for user

#### Frontend UI
- [ ] `/reconciliation/review-queue` — Stage 2 Review Page
  - [ ] Consistency check panel (top)
    - Card for each check type (dedup, transfer, anomaly)
    - Show count, severity, quick actions
  - [ ] Reconciliation match list (bottom)
    - Table: Bank txn, Matched entry, Score, Status
    - Batch select checkboxes
    - Filter: by score range, status, date
  - [ ] Batch actions
    - Approve selected (disabled if unresolved checks)
    - Reject selected
    - Export to CSV
  - [ ] Consistency check detail modal
    - Show duplicate group or transfer pair details
    - Actions: Approve (ignore), Reject (mark for fix), Flag (manual)
  - [ ] Conflict resolution UI
    - If duplicate detected: Choose canonical transaction
    - If transfer pair: Link transactions, create transfer entry

#### Tests
- [ ] `test_detect_duplicates_same_statement()` — Duplicate in single statement
- [ ] `test_detect_duplicates_cross_statement()` — Duplicate across statements
- [ ] `test_detect_transfer_pairs_exact_match()` — Exact amount match
- [ ] `test_detect_transfer_pairs_within_tolerance()` — Amount delta < 0.001 USD
- [ ] `test_detect_anomalies_balance_jump()` — Sudden balance increase
- [ ] `test_batch_approve_requires_checks_resolved()` — Approval blocked by unresolved checks
- [ ] `test_batch_approve_creates_journal_entries()` — Journal entry generation
- [ ] `test_resolve_check_approve()` — Approve check (ignore)
- [ ] `test_resolve_check_reject()` — Reject check (flag for fix)

---

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Balance validation tolerance = 0.001 USD** | `test_validate_balance_chain_within_tolerance()` | 🔴 Critical |
| **Stage 1 UI shows PDF + parsed split view** | Manual UI test | 🔴 Critical |
| **Approve button disabled if balance invalid** | Frontend unit test | Required |
| **Deduplication detection accuracy ≥ 95%** | `test_detect_duplicates_*()` | Required |
| **Transfer pair detection accuracy ≥ 90%** | `test_detect_transfer_pairs_*()` | Required |
| **Batch approve blocked if unresolved checks** | `test_batch_approve_requires_checks_resolved()` | Required |
| **Stage 2 UI supports batch operations** | Manual UI test | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| **Visual diff for edited transactions** | Frontend feature | ⏳ |
| **Keyboard shortcuts for approve/reject** | Frontend feature | ⏳ |
| **Mobile-responsive review UI** | Responsive design | ⏳ |
| **Export review queue to CSV** | API endpoint | ⏳ |

### 🚫 Not Acceptable

- Balance tolerance > 0.01 USD (too loose)
- Stage 1 UI without PDF preview (user can't verify)
- Batch approve without consistency checks (data corruption risk)
- Unresolved duplicates approved (accounting equation violation)
- Transfer pairs not linked (missing contra entries)

---

## 📚 SSOT References

- [reconciliation.md](../ssot/reconciliation.md) — Reconciliation workflow, confidence thresholds
- [schema.md](../ssot/schema.md) — BankStatement, ReconciliationMatch, atomic_transactions models
- [accounting.md](../ssot/accounting.md) — Journal entry creation from approved matches
- [extraction.md](../ssot/extraction.md) — Statement parsing logic (Stage 1 input)

---

## 🔗 Deliverables

### Backend
- [ ] `apps/backend/src/models/statement.py` — Extend BankStatement model
- [ ] `apps/backend/src/models/consistency_check.py` — ConsistencyCheck model
- [ ] `apps/backend/src/services/statement_validation.py` — Balance chain validation
- [ ] `apps/backend/src/services/consistency_checks.py` — Dedup, transfer, anomaly detection
- [ ] `apps/backend/src/routers/statements.py` — Extend with review endpoints
- [ ] `apps/backend/src/routers/review_queue.py` — Stage 2 review endpoints
- [ ] `apps/backend/tests/review/` — Test suite
  - `test_statement_validation.py`
  - `test_consistency_checks.py`
  - `test_review_workflow.py`

### Frontend
- [ ] `apps/frontend/src/app/(main)/statements/[id]/review/page.tsx` — Stage 1 review page
- [ ] `apps/frontend/src/app/(main)/reconciliation/review-queue/page.tsx` — Stage 2 review page
- [ ] `apps/frontend/src/components/review/PdfViewer.tsx` — PDF viewer component
- [ ] `apps/frontend/src/components/review/TransactionList.tsx` — Editable transaction list
- [ ] `apps/frontend/src/components/review/BalanceIndicator.tsx` — Balance validation UI
- [ ] `apps/frontend/src/components/review/ConsistencyCheckCard.tsx` — Consistency check card
- [ ] `apps/frontend/src/components/review/BatchActions.tsx` — Batch action toolbar

### Documentation
- [ ] Update `docs/ssot/reconciliation.md` — Add two-stage workflow section
- [ ] Update `vision.md` Decision 4 — Reference EPIC-016 implementation
- [ ] Create `docs/ssot/confirmation.md` — Document confirmation/review workflow (pending_review status definition)

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| Manual balance entry for first statement | P2 | Phase 1 extension (user enters opening balance) |
| Multi-currency balance validation | P2 | After EPIC-005 (FX rate integration) |
| ML-based duplicate detection | P3 | v2.0 (embeddings, fuzzy matching) |
| Real-time balance preview in edit mode | P3 | Frontend enhancement |

---

## 🐛 Known Issues & Gaps

- [ ] **SSOT Gap**: `pending_review` status used in 7 files but no SSOT document defines confirmation workflow. Need to create `docs/ssot/confirmation.md` or extend `reconciliation.md`.
- [ ] **Balance Chain Gap**: First statement requires manual opening balance entry (no previous closing balance).
- [ ] **Tolerance Mismatch**: Current code uses 0.10 USD tolerance (EPIC-004), this EPIC requires 0.001 USD. Need to update reconciliation service.
- [ ] **Transfer Detection**: Processing account integration (EPIC-015) already handles some transfer detection. Need to merge/dedup logic.

---

## ❓ Q&A (Clarification Required)

### Q1: Balance tolerance strictness — Design decision confirmed
> **Question**: 0.001 USD tolerance is very strict. Should we allow user-configurable tolerance?  
> **Impact**: Balance validation service API design  
> **User Answer**: "精度要求0.001 usd" (0.001 USD precision required)  
> **Decision**: ✅ Use fixed 0.001 USD tolerance in v1. User configuration deferred to v2.

### Q2: Stage 2 consistency check scope — Confirmed by user
> **Question**: Should Stage 2 include dedup, transfer pairing, and anomaly detection?  
> **Impact**: Consistency check service scope  
> **User Answer**: "Option B: Stage 2 包含一致性检查" (Stage 2 includes consistency checks)  
> **Decision**: ✅ Full scope: dedup detection, transfer pairing, time-series anomaly detection.

### Q3: Duplicate resolution strategy
> **Question**: When duplicates detected, how should user resolve? (1) Choose canonical, (2) Merge, (3) Flag both  
> **Impact**: Consistency check resolution UI  
> **Status**: ⏳ Pending user clarification

### Q4: Transfer pair auto-linking
> **Question**: Should system auto-create transfer journal entries for detected pairs, or require manual review?  
> **Impact**: Batch approval logic  
> **Status**: ⏳ Pending user clarification

### Q5: First statement opening balance
> **Question**: How should user enter opening balance for first statement? (1) Manual entry field, (2) Assume 0, (3) Infer from first transaction  
> **Impact**: Statement validation service  
> **Status**: ⏳ Pending user clarification

---

## 📅 Timeline

| Phase | Content | Duration | Status |
|------|------|----------|--------|
| **Phase 1** | Stage 1 (Record-Level Review) | 2-3 weeks | ⏳ Planned |
| Week 1 | Data model + Backend validation service | | |
| Week 2 | API endpoints + Frontend split-view UI | | |
| Week 3 | Testing + Balance chain validation | | |
| **Phase 2** | Stage 2 (Run-Level Review + Consistency Checks) | 2-3 weeks | ⏳ Planned |
| Week 4 | Consistency check service (dedup, transfer, anomaly) | | |
| Week 5 | Review queue UI + Batch operations | | |
| Week 6 | Testing + Conflict resolution | | |

**Total Estimate**: 4-6 weeks (depends on clarification response time)

---

## 🔄 Related EPICs

- **EPIC-003**: Statement Parsing → Generates Stage 1 input
- **EPIC-004**: Reconciliation Engine → Consumes Stage 2 output
- **EPIC-015**: Processing Account → Transfer detection logic overlap
- **EPIC-013**: Statement Parsing V2 → Balance chain validation, institution auto-detect

---

## 📊 Success Metrics (Post-Launch)

- **Stage 1 Approval Rate**: ≥ 95% (indicates parsing quality)
- **Stage 2 Auto-Accept Rate**: ≥ 70% (indicates consistency check accuracy)
- **Time to Review**: < 5 min per statement (Stage 1), < 10 min per batch (Stage 2)
- **Duplicate Detection Recall**: ≥ 95%
- **Transfer Pair Detection Recall**: ≥ 90%
- **Balance Validation False Positive Rate**: < 1%

---

*Last updated: February 2026*
