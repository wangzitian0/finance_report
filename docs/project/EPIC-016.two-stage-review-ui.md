# EPIC-016: Two-Stage Review & Data Validation UI

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, and executable tests.
> **Vision Anchor**: `decision-4-two-stage-review`
> **Phase**: 3 (Reconciliation Enhancement)
> **Planning estimate**: 4-6 weeks
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

## Macro Proof Ownership

- `source-ledger-report-traceability`

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

## Live Status Ownership

This EPIC defines the two-stage review scope and ACs. Do not use unchecked
boxes, historical audit tables, or planning estimates in this file as current
delivery status. For current proof, use generated registries, tests, and GitHub
issue state.

## ✅ Scope Checklist

The checklist below is retained as scope inventory, not as live completion
status. Current implementation proof must come from AC IDs and tests.

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

| AC ID | Standard | Verification | Weight |
|------|------|----------|------|
| AC16.1.1 | **Balance validation tolerance = 0.001 USD** | `test_validate_balance_chain_within_tolerance()` | 🔴 Critical |
| AC16.1.2 | **Stage 1 UI shows PDF + parsed split view** | Manual UI test | 🔴 Critical |
| AC16.1.3 | **Approve button disabled if balance invalid** | Frontend unit test | Required |
| AC16.2.1 | **Deduplication detection accuracy ≥ 95%** | `test_detect_duplicates_*()` | Required |
| AC16.2.2 | **Transfer pair detection accuracy ≥ 90%** | `test_detect_transfer_pairs_*()` | Required |
| AC16.2.3 | **Batch approve blocked if unresolved checks** | `test_batch_approve_requires_checks_resolved()` | Required |
| AC16.2.4 | **Stage 2 UI supports batch operations** | Manual UI test | Required |

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

## 📅 Roadmap Snapshot

This is the original planning sequence. It is not a live schedule or current
delivery status table.

| Phase | Content | Planning Estimate |
|------|------|----------|
| **Phase 1** | Stage 1 (Record-Level Review) | 2-3 weeks |
| Week 1 | Data model + Backend validation service | |
| Week 2 | API endpoints + Frontend split-view UI | |
| Week 3 | Testing + Balance chain validation | |
| **Phase 2** | Stage 2 (Run-Level Review + Consistency Checks) | 2-3 weeks |
| Week 4 | Consistency check service (dedup, transfer, anomaly) | |
| Week 5 | Review queue UI + Batch operations | |
| Week 6 | Testing + Conflict resolution | |

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

*Planning snapshot captured: March 2026*

---

## 📋 Acceptance Criteria — Coverage Registry

> The following sections canonicalize all AC16.x.x IDs present in `docs/ac_registry.yaml` that extend beyond the Must Have / Nice to Have tables above. They are generated from test docstrings and grouped by functional area.

### AC16.3 — Statement Validation Service (Extended Coverage)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.3.1 | `validate_balance_chain` raises `ValueError` when statement not found | ⏳ |
| AC16.3.2 | `_get_opening_balance` falls back to `opening_balance` when no prev statement exists | ⏳ |
| AC16.3.3 | `_get_opening_balance` uses prev statement `closing_balance` when available | ⏳ |
| AC16.3.4 | `reject_statement` without reason clears `validation_error` | ⏳ |
| AC16.3.5 | `edit_and_approve` raises `ValueError` when balance is still invalid after edits | ⏳ |
| AC16.3.6 | `_get_statement_for_update` raises `ValueError` when wrong `user_id` supplied | ⏳ |

### AC16.4 — Consistency Checks Service (Extended Coverage)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.4.1 | `detect_duplicates` runs global scan when no `statement_id` provided | ⏳ |
| AC16.4.2 | `detect_duplicates` is idempotent — does not create duplicate checks on re-run | ⏳ |
| AC16.4.3 | `detect_transfer_pairs` runs global scan when no `statement_id` provided | ⏳ |
| AC16.4.4 | `resolve_check` raises `ValueError` on invalid action | ⏳ |
| AC16.4.5 | `resolve_check` raises `ValueError` when check not found or belongs to wrong user | ⏳ |
| AC16.4.6 | `resolve_check` sets `FLAGGED` status when `action=flag` | ⏳ |
| AC16.4.7 | `get_pending_checks` filters results by severity | ⏳ |

### AC16.5 — Frontend Auth Utility (`lib/auth`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.5.1 | `getUserId` returns `null` when not set | ⏳ |
| AC16.5.2 | `getUserId` returns stored `userId` from `localStorage` | ⏳ |
| AC16.5.3 | `setUser` stores `userId`, `email`, and optional `token` | ⏳ |
| AC16.5.4 | `clearUser` removes all auth keys from `localStorage` | ⏳ |
| AC16.5.5 | `isAuthenticated` returns `false` when no token, `true` when token exists | ⏳ |

### AC16.6 — Frontend Date Utility (`lib/date`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.6.1 | `formatDateInput` formats `Date` as `YYYY-MM-DD` with zero-padded month and day | ⏳ |

### AC16.7 — Frontend Theme Utility (`lib/theme`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.7.1 | `getTheme` returns stored value or system preference | ⏳ |
| AC16.7.2 | `setTheme` adds/removes `dark` CSS class and saves to `localStorage` | ⏳ |
| AC16.7.3 | `toggleTheme` switches between dark and light | ⏳ |
| AC16.7.4 | `initTheme` applies stored or system theme on load | ⏳ |

### AC16.8 — Frontend AI Models Utility (`lib/aiModels`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.8.1 | `fetchAiModels` calls `/api/ai/models` with no params when no options provided | ⏳ |
| AC16.8.2 | `fetchAiModels` appends `modality` query param when provided | ⏳ |
| AC16.8.3 | `fetchAiModels` appends `free_only=true` when `freeOnly` is set | ⏳ |

### AC16.9 — Frontend Currencies Hook (`hooks/useCurrencies`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.9.1 | `useCurrencies` returns default currencies while loading | ⏳ |
| AC16.9.2 | `useCurrencies` updates currencies from API response | ⏳ |
| AC16.9.3 | `useCurrencies` falls back to defaults on API error | ⏳ |

### AC16.10 — Frontend API Client (`lib/api`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.10.1 | `apiFetch` returns JSON on `200` response | ⏳ |
| AC16.10.2 | `apiFetch` returns `undefined` on `204 No Content` | ⏳ |
| AC16.10.3 | `apiFetch` throws error with `detail` message on non-ok response | ⏳ |
| AC16.10.4 | `apiFetch` throws on non-JSON error text | ⏳ |
| AC16.10.5 | `apiFetch` calls `handle401Redirect` on `401` response | ⏳ |
| AC16.10.6 | `resetRedirectGuard` resets the redirect guard state | ⏳ |
| AC16.10.7 | `apiDelete` succeeds on `200` response | ⏳ |
| AC16.10.8 | `apiDelete` throws on non-ok response | ⏳ |
| AC16.10.9 | `apiStream` returns response and `sessionId` on success | ⏳ |
| AC16.10.10 | `apiStream` throws on non-ok response | ⏳ |
| AC16.10.11 | `apiUpload` returns JSON on `200` response | ⏳ |
| AC16.10.12 | `apiUpload` returns `undefined` on `204 No Content` | ⏳ |
| AC16.10.13 | `apiFetch` normalizes path without leading slash | ⏳ |
| AC16.10.14 | `apiFetch` includes `Authorization` header when token is present | ⏳ |

### AC16.11 — Dev Tooling / Infra Commands (Infra)

> These ACs cover `tools/debug.py`, `tools/cleanup_orphaned_dbs.py`, `tools/cli.py`, `tools/dev_backend.py`, and `tools/dev_frontend.py`.

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.11.1 | `debug` — `detect_environment` returns `CI` when `GITHUB_ACTIONS` is true | ⏳ |
| AC16.11.2 | `debug` — `detect_environment` returns `LOCAL` when `docker ps` succeeds | ⏳ |
| AC16.11.3 | `debug` — `detect_environment` falls back to `PRODUCTION` on docker failure | ⏳ |
| AC16.11.4 | `debug` — `validate_hostname` rejects empty and leading-hyphen hostnames | ⏳ |
| AC16.11.5 | `debug` — `validate_username` enforces unix-safe pattern | ⏳ |
| AC16.11.6 | `debug` — `get_container_name` maps known service names by environment | ⏳ |
| AC16.11.7 | `debug` — `list_containers` prints all mapped containers for an environment | ⏳ |
| AC16.11.8 | `cleanup_orphaned_dbs` — `extract_namespace` handles worker suffix and invalid names | ⏳ |
| AC16.11.9 | `cleanup_orphaned_dbs` — `load_active_namespaces` returns `[]` when file missing or corrupt | ⏳ |
| AC16.11.10 | `cleanup_orphaned_dbs` — `get_container_runtime` returns first available runtime | ⏳ |
| AC16.11.11 | `cleanup_orphaned_dbs` — `list_test_databases` parses psql output and handles subprocess errors | ⏳ |
| AC16.11.12 | `cleanup_orphaned_dbs` — `cleanup_orphaned` returns error when runtime missing | ⏳ |
| AC16.11.13 | `cleanup_orphaned_dbs` — `cleanup_orphaned` returns success when no test databases found | ⏳ |
| AC16.11.14 | `cleanup_orphaned_dbs` — `cleanup_orphaned` skips active namespace databases | ⏳ |
| AC16.11.15 | `cleanup_orphaned_dbs` — `cleanup_orphaned` cleans all databases in `--all` mode | ⏳ |
| AC16.11.16 | `cli` — `get_compose_cmd` honors `CONTAINER_RUNTIME`, otherwise prefers podman then docker and exits when unavailable | ⏳ |
| AC16.11.17 | `cli` — `cmd_test` routes frontend/e2e/perf/tests and lifecycle modes correctly | ⏳ |
| AC16.11.18 | `cli` — `cmd_clean` routes db/containers/default cleanup targets correctly | ⏳ |
| AC16.11.19 | `dev_backend` — `check_database_ready` returns `false` on migration subprocess errors | ⏳ |
| AC16.11.20 | `dev_frontend` — `cleanup` terminates tracked process and exits cleanly | ⏳ |
| AC16.11.21 | `debug` — `view_remote_logs_docker` exits when `VPS_HOST` is missing | ⏳ |
| AC16.11.22 | `debug` — `view_remote_logs_docker` exits on invalid VPS hostnames | ⏳ |
| AC16.11.23 | `debug` — `view_remote_logs_docker` exits on invalid VPS usernames | ⏳ |
| AC16.11.24 | `debug` — `view_local_logs` builds docker logs command with tail and follow | ⏳ |
| AC16.11.25 | `debug` — `main` routes `logs` command to signoz handler when `method=signoz` | ⏳ |
| AC16.11.26 | `debug` — `main` routes `status` command to local log view with status tail | ⏳ |
| AC16.11.27 | `debug` — `main` routes `containers` command to `list_containers` | ⏳ |
| AC16.11.28 | `dev_backend` — `check_database_ready` returns `true` when migration subprocess succeeds | ⏳ |
| AC16.11.29 | `dev_backend` — `cleanup` terminates tracked process and exits cleanly | ⏳ |
| AC16.11.30 | `cleanup_orphaned_dbs` — `drop_database` returns `true` in dry-run mode | ⏳ |
| AC16.11.31 | `cleanup_orphaned_dbs` — `main` forwards parsed flags to `cleanup_orphaned` | ⏳ |

### AC16.12 — Frontend Pages (Core Pages Coverage)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.12.1 | Dashboard page shows loading state before API responses resolve | ⏳ |
| AC16.12.2 | Dashboard page renders error fallback and retry action when API request fails | ⏳ |
| AC16.12.3 | Dashboard page renders KPI, charts, and recent activity when API requests succeed | ⏳ |
| AC16.12.4 | Dashboard page renders empty-state copy when trend or activity datasets are empty | ⏳ |
| AC16.12.17 | Dashboard page renders first-time onboarding when accounts, statements, or posted review output are missing | ⏳ |
| AC16.12.18 | Dashboard onboarding links users to Accounts, Statements upload, and Review in one click | ⏳ |
| AC16.12.19 | Dashboard hides onboarding once an approved statement and posted journal entry exist | ⏳ |
| AC16.12.5 | Login page submits login payload and redirects on success | ⏳ |
| AC16.12.6 | Login page toggles register mode and switches endpoint for submit | ⏳ |
| AC16.12.7 | Login page shows API error messages and resets loading state on failure | ⏳ |
| AC16.12.8 | Ping-pong page loads initial state and displays current ping/pong value | ⏳ |
| AC16.12.9 | Ping-pong page toggles state and updates toggle count on button click | ⏳ |
| AC16.12.10 | Ping-pong page renders retry flow when initial load fails | ⏳ |
| AC16.12.11 | Reports page renders all report cards with links for available reports | ⏳ |
| AC16.12.12 | Reports page displays accounting equation section content | ⏳ |

### AC16.13 — Test Lifecycle Infrastructure (Infra)

> These ACs cover `tools/test_lifecycle.py` and test infrastructure helpers.

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.13.1 | `test_lifecycle` — `sanitize_namespace` normalizes branch/workspace names | ⏳ |
| AC16.13.2 | `test_lifecycle` — `get_namespace` honors `BRANCH_NAME` and optional `WORKSPACE_ID` | ⏳ |
| AC16.13.3 | `test_lifecycle` — `get_namespace` falls back to git branch plus path hash when env vars absent | ⏳ |
| AC16.13.4 | `test_lifecycle` — `get_test_db_name` and `get_s3_bucket` format names deterministically | ⏳ |
| AC16.13.5 | `test_lifecycle` — `load_active_namespaces` returns `[]` on missing or corrupted tracker file | ⏳ |
| AC16.13.6 | `test_lifecycle` — `register_namespace` and `unregister_namespace` update active namespace tracker | ⏳ |
| AC16.13.7 | `test_lifecycle` — `get_container_runtime` honors `CONTAINER_RUNTIME`, otherwise detects podman/docker and returns `None` when absent | ⏳ |
| AC16.13.8 | `test_lifecycle` — `is_db_ready` returns `false` on `pg_isready` subprocess failure | ⏳ |
| AC16.13.9 | `test_lifecycle` — `cleanup_worker_databases` skips invalid namespace values | ⏳ |
| AC16.13.10 | `test_lifecycle` — `cleanup_worker_databases` drops valid worker DB names and skips invalid names | ⏳ |
| AC16.13.11 | `test_lifecycle` — `_get_changed_files` maps backend python paths into module import names | ⏳ |
| AC16.13.12 | `generate_test_pdfs` — `generate_statement` writes table rows and closing balance from `Decimal` transactions | ⏳ |

### AC16.14 — Frontend Report Pages and Statements Page

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.14.1 | Balance-sheet page renders loading and error retry states | ⏳ |
| AC16.14.2 | Balance-sheet page renders totals and account sections on successful fetch | ⏳ |
| AC16.14.3 | Balance-sheet page toggles account tree expansion controls | ⏳ |
| AC16.14.4 | Income-statement page renders loading and error retry states | ⏳ |
| AC16.14.5 | Income-statement page renders KPI cards and category lists on success | ⏳ |
| AC16.14.6 | Income-statement page tag filters can be selected and cleared | ⏳ |
| AC16.14.7 | Cash-flow page renders loading and error retry states | ⏳ |
| AC16.14.8 | Cash-flow page renders summary and section cards on success | ⏳ |
| AC16.14.9 | Cash-flow page renders sankey chart when summary exists | ⏳ |
| AC16.14.10 | Statements page renders loading, error, empty, and populated states | ⏳ |
| AC16.14.11 | Statements page enables polling when parsing status is present | ⏳ |
| AC16.14.12 | Statements page delete action calls delete API and toast on confirm | ⏳ |

### AC16.15 — Frontend Accounts and Assets Pages

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.15.1 | Accounts page renders loading and error retry states | ⏳ |
| AC16.15.2 | Accounts page renders grouped account cards and type filters on successful fetch | ⏳ |
| AC16.15.3 | Accounts page delete action confirms and calls delete API with success toast | ⏳ |
| AC16.15.4 | Assets page renders loading and error retry states | ⏳ |
| AC16.15.5 | Assets page renders grouped positions and status filters on successful fetch | ⏳ |
| AC16.15.6 | Assets page reconcile action calls API and shows toast summary | ⏳ |
| AC16.15.7 | stub | ⏳ |
| AC16.15.8 | stub | ⏳ |
| AC16.15.9 | stub | ⏳ |
| AC16.15.10 | stub | ⏳ |

### AC16.16 — Frontend App Structure (Root, Layout, Journal Page)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.16.1 | Root page redirects to dashboard | ⏳ |
| AC16.16.2 | Main layout renders children through `AppShell` wrapper | ⏳ |
| AC16.16.3 | Chat page renders advisor client within suspense boundary | ⏳ |
| AC16.16.4 | Reconciliation entry pages render workbench and unmatched board components | ⏳ |
| AC16.16.5 | Journal page renders error state and retries loading entries | ⏳ |
| AC16.16.6 | Journal page filters entries by status and renders totals | ⏳ |
| AC16.16.7 | Journal page draft actions post and delete entries with API calls | ⏳ |
| AC16.16.8 | Journal page void flow submits reason and refreshes entries | ⏳ |

### AC16.17 — Stage 2 Review Queue Page and Root Layout

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.17.1 | Stage 2 review queue shows failure fallback and supports retry | ⏳ |
| AC16.17.2 | Stage 2 review queue indicates unresolved checks and disables batch approval | ⏳ |
| AC16.17.3 | Stage 2 review queue performs batch reject and approve API workflows | ⏳ |
| AC16.17.4 | Stage 2 review queue resolves consistency checks through dialog actions | ⏳ |
| AC16.17.5 | Root layout composes `Providers` and `AuthGuard` around children | ⏳ |
| AC16.17.6 | `Providers` wraps children with `QueryClientProvider` | ⏳ |
| AC16.17.7 | API catch-all handlers return JSON `503` for all HTTP methods | ⏳ |

### AC16.18 — Statement Detail and Stage 1 Review Pages

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.18.1 | Statement detail page loads statement data and renders parsed transactions summary | ⏳ |
| AC16.18.2 | Statement detail page approve and reject actions call corresponding APIs | ⏳ |
| AC16.18.3 | Statement detail page retry action posts retry API and refreshes data | ⏳ |
| AC16.18.4 | Statement review page shows error fallback and supports retry | ⏳ |
| AC16.18.5 | Statement review page disables approve when balance validation fails | ⏳ |
| AC16.18.6 | Statement review page approve and reject actions call APIs and navigate back to statements | ⏳ |

### AC16.19 — App Shell, Auth, Shared Components, and Chat

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.19.1 | App shell renders workspace providers and main content with collapse-aware layout | ⏳ |
| AC16.19.2 | Auth guard redirects unauthenticated protected routes and allows public routes | ⏳ |
| AC16.19.3 | Sidebar shows auth-aware actions and logout triggers `clearUser` plus login redirect | ⏳ |
| AC16.19.4 | Workspace tabs derive route labels and invoke add/set/remove tab handlers | ⏳ |
| AC16.19.5 | Chat page client enforces disclaimer consent and passes initial prompt into chat panel | ⏳ |
| AC16.19.6 | Chat widget hides on chat route and toggles panel visibility elsewhere | ⏳ |
| AC16.19.7 | Confirm dialog handles required input, cancel, and confirm interactions | ⏳ |
| AC16.19.8 | Confirm dialog responds to escape key and backdrop click when not loading | ⏳ |
| AC16.19.9 | Toast provider shows, dismisses, and auto-expires notifications | ⏳ |
| AC16.19.10 | Bar and pie chart components render semantic labels and filtered data | ⏳ |
| AC16.19.11 | Trend chart renders line/area paths and point labels for provided series | ⏳ |

### AC16.20 — Reconciliation Workbench and Chat Panel Components

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.20.1 | Reconciliation workbench loads stats and pending queue with default selection | ⏳ |
| AC16.20.2 | Reconciliation workbench triggers run, accept, reject, and batch accept APIs | ⏳ |
| AC16.20.3 | Unmatched board loads transactions and creates journal entry for selected item | ⏳ |
| AC16.20.4 | Unmatched board flag and ignore actions update list and local state | ⏳ |
| AC16.20.5 | Chat panel sends streaming responses, loads suggestions/history, and clears session | ⏳ |

### AC16.21 — Account Form, Journal Entry Form, Sankey Chart, Workspace Provider

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.21.1 | Account form modal create mode submits normalized payload and closes on success | ⏳ |
| AC16.21.2 | Account form modal edit mode pre-fills values and submits update payload | ⏳ |
| AC16.21.3 | Account form modal surfaces API errors and field validation feedback | ⏳ |
| AC16.21.4 | Journal entry form loads account options and enforces balanced double-entry totals | ⏳ |
| AC16.21.5 | Journal entry form creates draft entries with normalized line amounts and optional posting | ⏳ |
| AC16.21.6 | Journal entry form supports dynamic line add/remove and submit-time error handling | ⏳ |
| AC16.21.7 | Sankey chart builds empty-state and data-state options for inflow and outflow links | ⏳ |
| AC16.21.8 | Sankey chart recomputes theme-aware colors when root theme attributes change | ⏳ |
| AC16.21.9 | Workspace provider restores tabs from storage and persists active workspace updates | ⏳ |
| AC16.21.10 | Workspace provider handles tab deduplication, removal, and cross-tab storage sync | ⏳ |

### AC16.22 — Confirmation Workflow (cross-cutting `pending_review` state machine)

> See authoritative definition: [docs/ssot/confirmation-workflow.md](../ssot/confirmation-workflow.md)

| AC ID | Description | Test Function | File | Priority |
|-------|-------------|---------------|------|----------|
| AC16.22.1 | Stage 1 `pending_review → approved` transition requires balance delta ≤ 0.001 USD | `test_approve_statement_invalid_balance_fails` | `review/test_statement_validation.py` | P0 |
| AC16.22.2 | Stage 1 `pending_review → rejected` transition triggers re-parse | `test_stage1_reject_triggers_reparse` | `api/test_statements_router.py` | P0 |
| AC16.22.3 | Stage 2 `pending_review → accepted` transition blocked when unresolved checks exist | `test_batch_approve_matches_blocked_by_unresolved_checks` | `api/test_statements_router.py` | P0 |
| AC16.22.4 | Journal entry created only on `accepted` transition, never on `pending_review` | `test_batch_approve_matches_creates_missing_entry_once` | `api/test_statements_router.py` | P0 |
| AC16.22.5 | Stage 1 tolerance is 0.001 USD (not 0.10 USD from Stage 2) | `test_validate_balance_chain_within_tolerance` | `review/test_statement_validation.py` | P0 |
| AC16.22.6 | All service methods mutating `pending_review` enforce `user_id` ownership | `test_get_statement_for_update_wrong_user_raises` | `review/test_statement_validation.py` | P1 |


---

## 🔍 Historical FE/UI Audit Snapshot (April 2026)

> Audit Date: 2026-04-06 | Auditor: AI Agent (Sisyphus) | Scope: Frontend completeness, UX quality, accessibility
>
> Snapshot note: this audit records findings from April 2026. Treat file and
> implementation inventories as historical context unless re-validated against
> the current tree and generated proof reports.

### Executive Summary

**Backend**: ✅ Fully implemented (554 lines services, 1,439 lines tests across `statement_validation.py`, `consistency_checks.py`, review router)

**Frontend**: ⚠️ Partially implemented — core happy-path flows exist in monolithic page files, but EPIC-specified component decomposition and several key features are missing.

### Inventory: What Exists

| File | Lines | Purpose | Quality |
|------|-------|---------|---------|
| `statements/[id]/review/page.tsx` | 351 | Stage 1 review: PDF left + transactions right | ✅ Loading/error/empty states, responsive grid |
| `reconciliation/review-queue/page.tsx` | 495 | Stage 2 review queue: consistency checks + batch matches | ✅ Focus trap, ESC key, score color coding |
| `statements/[id]/page.tsx` | 513 | Statement detail: approve/reject/retry, parsing progress | ✅ Polling, timeout detection, error handling |
| `statements/page.tsx` | 257 | Statement list: status badges, upload integration | ✅ Auto-polling during parsing |
| `components/statements/StatementUploader.tsx` | 346 | Upload: drag-and-drop, model selection, file validation | ✅ Robust |
| `components/reconciliation/Workbench.tsx` | 290 | Reconciliation matching (Stage 0, pre-EPIC-016) | ✅ TanStack Query |
| `__tests__/reviewQueuePage.test.tsx` | 323 | Stage 2 tests: 13 test cases covering AC16.17.1–AC16.17.4 | ✅ Good coverage |
| `__tests__/statementReviewPage.test.tsx` | 137 | Stage 1 tests: 3 test cases covering AC16.18.4–AC16.18.6 | ⚠️ Minimal |

### Gap Analysis

#### 🔴 Critical Gaps (blocking user adoption)

| # | Gap | EPIC Requirement | Impact |
|---|-----|-----------------|--------|
| G1 | **No component decomposition at audit time** | EPIC specifies `components/review/PdfViewer.tsx`, `TransactionList.tsx`, `BalanceIndicator.tsx`, `ConsistencyCheckCard.tsx`, `BatchActions.tsx` | `components/review/` directory did not exist in the audited tree. All logic was monolithic in page.tsx files (351 + 495 lines). |
| G2 | **No inline transaction editing** | EPIC requires "Editable rows" in Stage 1 review — user corrects OCR mistakes before approving | Zero implementation. grep for `inline.?edit|editable|contentEditable` → 0 matches. Without this, users cannot fix parsing errors, defeating the purpose of human review. |
| G3 | **No conflict resolution UI** | Stage 2 requires "choose canonical transaction" for duplicates and "link transfer pair" for transfers | No UI for resolving duplicate transactions or linking transfer pairs. Backend `consistency_checks.py` detects these, but frontend has no resolution workflow. |

#### 🟡 Important Gaps (degraded experience)

| # | Gap | EPIC Requirement | Impact |
|---|-----|-----------------|--------|
| G4 | **No filtering on Stage 2 review queue** | EPIC requires filters for check type, severity, score range, date | Users with many pending items cannot efficiently triage. Only raw list is shown. |
| G5 | **No Previous/Next navigation** | Stage 1 review should allow navigating between pending statements | Users must go back to list, find next pending statement, click through to review. High friction. |
| G6 | **Confusing approve/reject duplication** | `statements/[id]/page.tsx` (detail) has approve/reject buttons that overlap with `statements/[id]/review/page.tsx` (review) | Users see two different places to approve a statement with unclear distinction. UX confusion between "approve statement" vs "approve review". |
| G7 | **Stage 1 test coverage is thin** | Only 3 tests for Stage 1 review vs 13 for Stage 2 | `statementReviewPage.test.tsx` covers AC16.18.4–AC16.18.6 only. Missing tests for PDF rendering, transaction display, balance indicator edge cases. |
| G8 | **No batch operations on consistency checks** | Only individual resolve per check | Stage 2 allows batch approve/reject on matches but only individual resolve on consistency checks. If many checks share the same root cause, this is tedious. |

#### 🟢 Nice-to-Have Gaps

| # | Gap | Notes |
|---|-----|-------|
| G9 | No CSV export | "Export reviewed data" mentioned as deliverable |
| G10 | No PDF page navigation controls | Left panel shows PDF embed but no page nav for multi-page statements |
| G11 | Limited accessibility | Checkboxes in batch select have minimal labeling; transaction table lacks keyboard navigation; aria coverage limited to progress bar |
| G12 | No direct "Review" link from statement list | Must navigate: List → Detail → Review (2 clicks instead of 1) |

### Positive Findings

- ✅ **Loading/error/empty states**: All 4 pages implement the project's standard pattern (spinner → error card with retry → empty message)
- ✅ **Responsive layout**: All pages use `grid-cols-1 lg:grid-cols-2` for mobile/desktop
- ✅ **Focus trap + keyboard**: Review queue modal implements ESC close and focus trap
- ✅ **Score color coding**: Correct thresholds (green ≥85, yellow 60-84, red <60) matching AGENTS.md
- ✅ **Balance validation gating**: Approve button disabled when balance validation fails (AC16.18.5)
- ✅ **API wrapper**: All pages use `lib/api.ts` wrapper (no direct `fetch()`)
- ✅ **Consistent design tokens**: Pages use project CSS variables (`--accent`, `--success`, `--error`)

### Recommendations (Priority Order)

1. **[P0] Implement inline editing** — Without this, Stage 1 review is view-only, which defeats confidence accumulation. Recommend a `TransactionEditableRow` component.
2. **[P0] Extract reusable components** — Break monolithic pages into `components/review/` directory. This unblocks testing and future feature work.
3. **[P1] Add conflict resolution UI** — Backend detects duplicates and transfers; frontend needs resolution dialogs ("choose canonical", "link pair").
4. **[P1] Add filtering to Stage 2** — At minimum: severity filter, check type filter, score range slider.
5. **[P2] Clarify approve/reject UX** — Either remove approve from detail page or make it clearly distinct from review approve (e.g., detail page only shows "Go to Review").
6. **[P2] Add Previous/Next navigation** — Simple prev/next buttons on review page using statement list order.
7. **[P3] Increase Stage 1 test coverage** — Add tests for PDF rendering fallback, transaction list sorting, balance indicator edge cases.

---

*FE/UI Audit appended: April 2026*

---

## 🆕 UI Gap Audit (April 2026) — Stage 1 Refactor, Inline Edit, Conflict Resolution & Mobile Nav

**Origin**: UI gap audit against [vision.md](../../vision.md) (two-stage review must be production-grade). Stage 1 page is monolithic, has no inline edit, no conflict resolution UI, no mobile navigation. These block real-user adoption of the review flow.

### Acceptance Criteria — Feature (group 23)

- [x] **AC16.23.1** Stage 1 page split into `<PdfPreviewPane />`, `<TransactionTable />`, `<ReviewActionBar />`, `<BalanceIndicator />` components, each independently mountable
- [x] **AC16.23.2** TransactionTable supports inline edit of `amount`, `description`, `date` with optimistic update + server confirm; failed write reverts row and shows error toast
- [x] **AC16.23.3** Conflict resolution dialog `<ConflictResolutionDialog />` opens when backend returns duplicate or transfer-pair candidates; user can pick canonical row or link the pair
- [x] **AC16.23.4** Stage 2 listing exposes severity filter, check-type filter, and score-range slider; filters persist in URL query string
- [x] **AC16.23.5** Mobile navigation drawer (`<MobileNav />`) renders below 768 px with links to Dashboard / Review / Processing / Portfolio; existing desktop sidebar hidden on mobile
- [x] **AC16.23.6** Frontend tests mount each new component (PdfPreviewPane, TransactionTable, ConflictResolutionDialog, MobileNav) and assert primary affordance renders

### Acceptance Criteria — Feature (group 24, run-level Stage 2)

- [x] **AC16.24.1** Stage 2 run-level page at `/review/run/[runId]` summarizes duplicate, transfer-pair, and anomaly checks for a batch
- [x] **AC16.24.2** Stage 2 run-level page shows unresolved transfer and Processing pending counts, then disables run approval while either remains unresolved
- [x] **AC16.24.3** Stage 2 run-level approval submits all pending matches through the batch approval API after checks are resolved
- **AC16.24.4** - Stage 2 batch approval routes accepted matches through the ledger-safe acceptance path, creating missing journal entries or reconciling referenced entries without duplicating entries on retry

### Acceptance Criteria — Infra (group 11, test infra extension)

- [x] **AC16.11.32** Vitest harness for Stage 1 split components — shared `renderReviewComponent()` helper in `apps/frontend/src/__tests__/helpers/`
- [x] **AC16.11.33** Playwright smoke covers inline-edit happy path on Stage 1 (open review → edit amount → save → assert persisted)

### Acceptance Criteria — Infra (group 13, conflict resolution backend contract)

- [x] **AC16.13.13** Backend exposes `GET /api/review/conflicts/{statement_id}` returning `{duplicates: [...], transfer_pairs: [...]}` consumed by ConflictResolutionDialog
- [x] **AC16.13.14** Contract test asserts response schema and 404 when statement_id not found

**Priority**: P0 — Stage 1 monolith is the #1 reported UX blocker.
**Estimated effort**: 6-8 days frontend (component split + inline edit + conflict dialog + mobile nav) + 2-3 days backend (conflicts endpoint) + 1-2 days test infra.
---

## Implementation Plan

> *Merged from EPIC-016-IMPLEMENTATION-PLAN.md (2026-02-25). Consolidated per SSOT deduplication policy.*

## Executive Summary

This document provides a detailed implementation plan for EPIC-016 Two-Stage Review UI, based on codebase exploration and SSOT analysis.

### Design Decisions (Confirmed)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Q3: Duplicate Resolution | Choose canonical | Simpler UX, user picks one to keep |
| Q4: Transfer Pair Auto-link | Manual review first | Prevents incorrect auto-entries |
| Q5: First Statement Opening Balance | Manual entry | Most flexible, user knows actual balance |
| Tolerance | **0.001 USD** | Per user requirement (not 0.10 USD) |

---

## Architecture Overview

### Two-Stage Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Statement Import                               │
└────────────────────────────────────┬────────────────────────────────────┘
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: Record-Level Review (New)                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐     │
│  │  PDF Viewer     │    │  Transaction    │    │  Balance        │     │
│  │  (Left Panel)   │◄──►│  List (Right)   │◄──►│  Validation     │     │
│  │                 │    │  (Editable)     │    │  (0.001 USD)    │     │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘     │
│                                                                          │
│  Actions: Approve | Reject | Edit & Approve                             │
│  Status: pending_review → approved | rejected                           │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Stage 1 Approved)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: Run-Level Review (Enhanced)                                    │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐     │
│  │  Consistency    │    │  Reconciliation │    │  Batch          │     │
│  │  Checks         │    │  Match Queue    │    │  Operations     │     │
│  │  • Dedup        │    │  (Score 60-84)  │    │  • Approve      │     │
│  │  • Transfer     │    │                 │    │  • Reject       │     │
│  │  • Anomaly      │    │                 │    │  • Export CSV   │     │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘     │
│                                                                          │
│  Constraint: Batch approve blocked if unresolved consistency checks     │
│  Actions: Resolve Check | Batch Approve | Batch Reject                  │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │ (Stage 2 Approved)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  Reconciliation Complete → Journal Entries Created                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Phase 1: Stage 1 (Record-Level Review)

### 1.1 Data Model Changes

#### New Enum: Stage1Status

```python
# apps/backend/src/models/statement.py

class Stage1Status(str, Enum):
    """Stage 1 review status for statements."""
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"  # User made edits before approving
```

#### Extend BankStatement Model

```python
# apps/backend/src/models/statement.py

class BankStatement(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    # ... existing fields ...
    
    # NEW: Stage 1 review fields
    stage1_status: Mapped[Stage1Status | None] = mapped_column(
        SQLEnum(Stage1Status, name="stage1_status_enum"),
        nullable=True,
        default=None,  # NULL for statements before EPIC-016
    )
    
    balance_validation_result: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        # Structure:
        # {
        #   "opening_match": bool,
        #   "closing_match": bool,
        #   "opening_delta": "0.000",
        #   "closing_delta": "0.000",
        #   "calculated_closing": "1234.56",
        #   "validated_at": "2026-02-25T10:00:00Z"
        # }
    )
    
    stage1_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    
    # Manual opening balance entry for first statement
    manual_opening_balance: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 2),
        nullable=True,
    )
```

#### Alembic Migration

```bash
# Create migration
alembic revision -m "add_stage1_review_fields"
```

Migration content:
- Add `stage1_status` enum
- Add `balance_validation_result` JSONB column
- Add `stage1_reviewed_at` timestamp
- Add `manual_opening_balance` decimal

### 1.2 Backend Service: statement_validation.py

```python
# apps/backend/src/services/statement_validation.py

from decimal import Decimal
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import BankStatement, BankStatementTransaction, BankStatementStatus
from src.models.statement import Stage1Status

BALANCE_TOLERANCE = Decimal("0.001")  # Per user requirement

async def validate_balance_chain(
    db: AsyncSession,
    statement_id: UUID,
) -> dict:
    """
    Validate opening and closing balance chain.
    
    Logic:
    1. Opening balance = previous statement's closing balance OR manual entry
    2. Calculated closing = opening + sum(transactions)
    3. Compare with statement's closing_balance
    4. Tolerance: 0.001 USD
    """
    result = await db.execute(
        select(BankStatement)
        .where(BankStatement.id == statement_id)
        .options(selectinload(BankStatement.transactions))
    )
    statement = result.scalar_one_or_none()
    if not statement:
        raise ValueError("Statement not found")
    
    # Get opening balance
    opening_balance = await _get_opening_balance(db, statement)
    
    # Calculate expected closing balance
    txn_sum = Decimal("0")
    for txn in statement.transactions:
        if txn.direction == "IN":
            txn_sum += txn.amount
        else:
            txn_sum -= txn.amount
    
    calculated_closing = opening_balance + txn_sum
    
    # Compare with stated closing balance
    closing_delta = abs((statement.closing_balance or Decimal("0")) - calculated_closing)
    
    validation_result = {
        "opening_balance": str(opening_balance),
        "closing_balance": str(statement.closing_balance),
        "calculated_closing": str(calculated_closing),
        "opening_delta": "0.000",  # Will be set by previous statement check
        "closing_delta": str(closing_delta),
        "opening_match": True,  # Will be set by previous statement check
        "closing_match": closing_delta <= BALANCE_TOLERANCE,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
    
    return validation_result


async def approve_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
) -> BankStatement:
    """Approve statement after validation passes."""
    # Validate balance
    result = await validate_balance_chain(db, statement_id)
    
    if not result["closing_match"]:
        raise ValueError(
            f"Balance mismatch: delta={result['closing_delta']} exceeds tolerance {BALANCE_TOLERANCE}"
        )
    
    # Update statement
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_status = Stage1Status.APPROVED
    statement.stage1_reviewed_at = datetime.now(timezone.utc)
    statement.balance_validation_result = result
    statement.status = BankStatementStatus.APPROVED
    
    await db.flush()
    return statement


async def reject_statement(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    reason: str | None,
) -> BankStatement:
    """Reject statement - trigger re-parsing."""
    statement = await _get_statement_for_update(db, statement_id, user_id)
    statement.stage1_status = Stage1Status.REJECTED
    statement.stage1_reviewed_at = datetime.now(timezone.utc)
    statement.status = BankStatementStatus.REJECTED
    if reason:
        statement.validation_error = reason
    
    await db.flush()
    return statement


async def edit_and_approve(
    db: AsyncSession,
    statement_id: UUID,
    user_id: UUID,
    edits: list[dict],  # [{txn_id, amount, description, ...}]
) -> BankStatement:
    """Edit transactions and approve if balance validates."""
    statement = await _get_statement_for_update(db, statement_id, user_id)
    
    # Apply edits
    for edit in edits:
        txn = next((t for t in statement.transactions if str(t.id) == edit.get("txn_id")), None)
        if txn:
            if "amount" in edit:
                txn.amount = Decimal(str(edit["amount"]))
            if "description" in edit:
                txn.description = edit["description"]
            if "txn_date" in edit:
                txn.txn_date = edit["txn_date"]
    
    # Validate and approve
    result = await validate_balance_chain(db, statement_id)
    
    if not result["closing_match"]:
        raise ValueError("Balance still invalid after edits")
    
    statement.stage1_status = Stage1Status.EDITED
    statement.stage1_reviewed_at = datetime.now(timezone.utc)
    statement.balance_validation_result = result
    statement.status = BankStatementStatus.APPROVED
    
    await db.flush()
    return statement
```

### 1.3 API Endpoints

```python
# apps/backend/src/routers/statements.py (extend existing)

@router.get("/{statement_id}/review")
async def get_statement_for_review(
    statement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> StatementReviewResponse:
    """
    Get statement with parsed data and validation results for Stage 1 review.
    
    Returns:
    - Statement metadata
    - Parsed transactions
    - Balance validation result
    - PDF URL (MinIO presigned URL)
    """
    ...

@router.post("/{statement_id}/approve")
async def approve_statement_stage1(
    statement_id: UUID,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Approve statement (Stage 1). Validates balance chain first."""
    ...

@router.post("/{statement_id}/reject")
async def reject_statement_stage1(
    statement_id: UUID,
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Reject statement - trigger re-parsing."""
    ...

@router.post("/{statement_id}/edit")
async def edit_and_approve_statement(
    statement_id: UUID,
    body: EditTransactionsRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Edit transactions and approve if balance validates."""
    ...

@router.post("/{statement_id}/opening-balance")
async def set_opening_balance(
    statement_id: UUID,
    body: OpeningBalanceRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BankStatementResponse:
    """Set manual opening balance for first statement."""
    ...
```

### 1.4 Frontend: Stage 1 Review Page

**Route**: `/statements/[id]/review`

**Components**:
- `PdfViewer.tsx` - Left panel, MinIO presigned URL
- `TransactionList.tsx` - Right panel, editable rows
- `BalanceIndicator.tsx` - Green/Red/Warning status
- `ReviewActions.tsx` - Approve/Reject/Edit buttons

**Key Features**:
1. Split-view layout (PDF left, transactions right)
2. Inline editing for transaction corrections
3. Real-time balance validation preview
4. Approve disabled if balance invalid
5. Navigation to next pending statement

### 1.5 Tests

```python
# apps/backend/tests/review/test_statement_validation.py

async def test_validate_balance_chain_exact_match():
    """Exact balance match passes."""
    
async def test_validate_balance_chain_within_tolerance():
    """Delta = 0.0009 USD passes."""
    
async def test_validate_balance_chain_exceeds_tolerance():
    """Delta = 0.0011 USD fails."""
    
async def test_approve_statement_success():
    """Approve with valid balance."""
    
async def test_approve_statement_invalid_balance_fails():
    """Reject invalid balance."""
    
async def test_edit_and_approve():
    """Edit transaction amount, recalculate, approve."""
    
async def test_reject_statement_triggers_reparse():
    """Rejection flow."""
    
async def test_first_statement_manual_opening_balance():
    """First statement requires manual opening balance entry."""
```

---

## Phase 2: Stage 2 (Run-Level Review)

### 2.1 Data Model: ConsistencyCheck

```python
# apps/backend/src/models/consistency_check.py

class CheckType(str, Enum):
    DUPLICATE = "duplicate"
    TRANSFER_PAIR = "transfer_pair"
    ANOMALY = "anomaly"

class CheckStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"  # User acknowledged, ignore
    REJECTED = "rejected"  # Flagged for fix
    FLAGGED = "flagged"    # Needs manual review

class ConsistencyCheck(Base, UUIDMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "consistency_checks"
    
    check_type: Mapped[CheckType] = mapped_column(
        SQLEnum(CheckType, name="check_type_enum"),
        nullable=False,
    )
    status: Mapped[CheckStatus] = mapped_column(
        SQLEnum(CheckStatus, name="check_status_enum"),
        default=CheckStatus.PENDING,
    )
    
    # Related transactions (JSON array of IDs)
    related_txn_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    
    # Check details (varies by type)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Duplicate: {"group_id": "hash", "count": 2, "amount": "100.00"}
    # Transfer: {"from_account": "xxx", "to_account": "yyy", "amount": "500.00"}
    # Anomaly: {"type": "LARGE_AMOUNT", "severity": "high", "message": "..."}
    
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    # high, medium, low
    
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
```

### 2.2 Backend Service: consistency_checks.py

```python
# apps/backend/src/services/consistency_checks.py

async def detect_duplicates(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
) -> list[ConsistencyCheck]:
    """
    Find transactions with same amount, date (±1 day), similar description.
    Uses existing dedup_hash logic from atomic_transactions.
    """
    ...

async def detect_transfer_pairs(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
) -> list[ConsistencyCheck]:
    """
    Find matching OUT/IN transactions across accounts.
    Amount match (tolerance 0.001 USD), date proximity (±3 days).
    """
    ...

async def detect_anomalies_batch(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID | None = None,
) -> list[ConsistencyCheck]:
    """
    Run anomaly detection for all transactions.
    Reuses services/anomaly.py.
    """
    ...

async def run_all_consistency_checks(
    db: AsyncSession,
    user_id: UUID,
    statement_id: UUID,
) -> list[ConsistencyCheck]:
    """Run all checks for a statement."""
    checks = []
    checks.extend(await detect_duplicates(db, user_id, statement_id))
    checks.extend(await detect_transfer_pairs(db, user_id, statement_id))
    checks.extend(await detect_anomalies_batch(db, user_id, statement_id))
    return checks

async def resolve_check(
    db: AsyncSession,
    check_id: UUID,
    action: str,  # "approve", "reject", "flag"
    user_id: UUID,
    note: str | None = None,
) -> ConsistencyCheck:
    """Resolve a consistency check."""
    ...
```

### 2.3 API Endpoints

```python
# apps/backend/src/routers/review_queue.py (extend)

@router.get("/stage2")
async def get_stage2_review_queue(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
    check_type: CheckType | None = None,
    severity: str | None = None,
) -> Stage2ReviewQueueResponse:
    """Get Stage 2 review queue with pending matches and checks."""
    ...

@router.post("/batch-approve")
async def batch_approve_matches(
    body: BatchApproveRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BatchApproveResponse:
    """
    Batch approve matches.
    BLOCKED if any unresolved consistency checks exist.
    """
    ...

@router.post("/batch-reject")
async def batch_reject_matches(
    body: BatchRejectRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> BatchRejectResponse:
    ...

@router.post("/consistency-checks/{check_id}/resolve")
async def resolve_consistency_check(
    check_id: UUID,
    body: ResolveCheckRequest,
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
) -> ConsistencyCheckResponse:
    """Resolve a consistency check."""
    ...

@router.get("/consistency-checks")
async def list_consistency_checks(
    db: AsyncSession = Depends(get_db),
    user_id: UUID = Depends(get_current_user_id),
    status: CheckStatus | None = None,
) -> list[ConsistencyCheckResponse]:
    ...
```

### 2.4 Frontend: Stage 2 Review Queue

**Route**: `/reconciliation/review-queue`

**Components**:
- `ConsistencyCheckCard.tsx` - Card for each check type
- `ReconciliationMatchList.tsx` - Table with batch select
- `BatchActions.tsx` - Approve/Reject/Export toolbar
- `CheckDetailModal.tsx` - Resolve individual checks

**Key Features**:
1. Consistency check summary panel (top)
2. Match list with batch checkboxes
3. Batch approve blocked if unresolved checks
4. Check resolution modal with approve/reject/flag actions
5. Export to CSV

### 2.5 Tests

```python
# apps/backend/tests/review/test_consistency_checks.py

async def test_detect_duplicates_same_statement():
    """Duplicate in single statement."""
    
async def test_detect_duplicates_cross_statement():
    """Duplicate across statements."""
    
async def test_detect_transfer_pairs_exact_match():
    """Exact amount match."""
    
async def test_detect_transfer_pairs_within_tolerance():
    """Amount delta < 0.001 USD."""
    
async def test_detect_anomalies_balance_jump():
    """Sudden balance increase."""
    
async def test_batch_approve_requires_checks_resolved():
    """Approval blocked by unresolved checks."""
    
async def test_batch_approve_creates_journal_entries():
    """Journal entry generation."""
    
async def test_resolve_check_approve():
    """Approve check (ignore)."""
    
async def test_resolve_check_reject():
    """Reject check (flag for fix)."""
```

---

## File Structure

### Backend (New Files)

```
apps/backend/src/
├── models/
│   ├── statement.py          # Extended with Stage1Status, new fields
│   └── consistency_check.py  # NEW: ConsistencyCheck model
├── services/
│   ├── statement_validation.py  # NEW: Balance chain validation
│   └── consistency_checks.py    # NEW: Dedup, transfer, anomaly
├── routers/
│   ├── statements.py         # Extended with review endpoints
│   └── review_queue.py       # NEW: Stage 2 review endpoints
├── schemas/
│   └── review.py             # NEW: Review request/response schemas
└── migrations/
    └── versions/
        └── xxxx_add_stage1_review_fields.py  # NEW

apps/backend/tests/
└── review/
    ├── test_statement_validation.py  # NEW
    └── test_consistency_checks.py    # NEW
```

### Frontend (New Files)

```
apps/frontend/src/
├── app/(main)/
│   ├── statements/
│   │   └── [id]/
│   │       └── review/
│   │           └── page.tsx      # NEW: Stage 1 review page
│   └── reconciliation/
│       └── review-queue/
│           └── page.tsx          # NEW: Stage 2 review page
└── components/
    └── review/
        ├── PdfViewer.tsx           # NEW
        ├── TransactionList.tsx     # NEW (editable)
        ├── BalanceIndicator.tsx    # NEW
        ├── ReviewActions.tsx       # NEW
        ├── ConsistencyCheckCard.tsx # NEW
        ├── BatchActions.tsx        # NEW
        └── CheckDetailModal.tsx    # NEW
```

---

## Timeline

| Week | Tasks |
|------|-------|
| **Week 1** | Data model + Backend validation service + Migration |
| **Week 2** | API endpoints + Frontend split-view UI (Stage 1) |
| **Week 3** | Testing + Balance chain validation |
| **Week 4** | Consistency check service (dedup, transfer, anomaly) |
| **Week 5** | Review queue UI + Batch operations (Stage 2) |
| **Week 6** | Testing + Conflict resolution + Documentation |

---

## Dependencies

- **EPIC-003** (Statement Parsing) → Generates Stage 1 input ✅
- **EPIC-004** (Reconciliation Engine) → Consumes Stage 2 output ✅
- **EPIC-015** (Processing Account) → Transfer detection overlap (reuse logic)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| PDF viewer performance | Use MinIO presigned URLs, lazy load |
| 0.001 USD tolerance too strict | Configurable in config.py (default 0.001) |
| Batch approval race conditions | Row-level locking, version increment |
| Duplicate detection false positives | Confidence scoring, manual review queue |

---

*Planning snapshot captured: 2026-02-25*
