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

*Last updated: March 2026*

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

### AC16.11 — Dev Tooling / Infra Scripts (Infra)

> These ACs cover `scripts/debug.py`, `scripts/cleanup_orphaned_dbs.py`, `scripts/cli.py`, `scripts/dev_backend.py`, and `scripts/dev_frontend.py`.

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
| AC16.11.16 | `cli` — `get_compose_cmd` prefers podman then docker and exits when unavailable | ⏳ |
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
| AC16.12.5 | Login page submits login payload and redirects on success | ⏳ |
| AC16.12.6 | Login page toggles register mode and switches endpoint for submit | ⏳ |
| AC16.12.7 | Login page shows API error messages and resets loading state on failure | ⏳ |
| AC16.12.8 | Ping-pong page loads initial state and displays current ping/pong value | ⏳ |
| AC16.12.9 | Ping-pong page toggles state and updates toggle count on button click | ⏳ |
| AC16.12.10 | Ping-pong page renders retry flow when initial load fails | ⏳ |
| AC16.12.11 | Reports page renders all report cards with links for available reports | ⏳ |
| AC16.12.12 | Reports page displays accounting equation section content | ⏳ |

### AC16.13 — Test Lifecycle Infrastructure (Infra)

> These ACs cover `scripts/test_backend.py` / `scripts/test_lifecycle.py` and test infrastructure helpers.

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.13.1 | `test_lifecycle` — `sanitize_namespace` normalizes branch/workspace names | ⏳ |
| AC16.13.2 | `test_lifecycle` — `get_namespace` honors `BRANCH_NAME` and optional `WORKSPACE_ID` | ⏳ |
| AC16.13.3 | `test_lifecycle` — `get_namespace` falls back to git branch plus path hash when env vars absent | ⏳ |
| AC16.13.4 | `test_lifecycle` — `get_test_db_name` and `get_s3_bucket` format names deterministically | ⏳ |
| AC16.13.5 | `test_lifecycle` — `load_active_namespaces` returns `[]` on missing or corrupted tracker file | ⏳ |
| AC16.13.6 | `test_lifecycle` — `register_namespace` and `unregister_namespace` update active namespace tracker | ⏳ |
| AC16.13.7 | `test_lifecycle` — `get_container_runtime` detects podman/docker and returns `None` when absent | ⏳ |
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
| AC16.22.2 | Stage 1 `pending_review → rejected` transition triggers re-parse | `test_reject_statement_triggers_reparse` | `review/test_statement_validation.py` | P0 |
| AC16.22.3 | Stage 2 `pending_review → accepted` transition blocked when unresolved checks exist | `test_batch_approve_requires_checks_resolved` | `review/test_review_workflow.py` | P0 |
| AC16.22.4 | Journal entry created only on `accepted` transition, never on `pending_review` | `test_journal_entry_created_on_accept` | `review/test_review_workflow.py` | P0 |
| AC16.22.5 | Stage 1 tolerance is 0.001 USD (not 0.10 USD from Stage 2) | `test_validate_balance_chain_within_tolerance` | `review/test_statement_validation.py` | P0 |
| AC16.22.6 | All service methods mutating `pending_review` enforce `user_id` ownership | `test_wrong_user_id_rejected` | `review/test_review_workflow.py` | P1 |
