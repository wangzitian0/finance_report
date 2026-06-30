# EPIC-015: Processing Account Integration

> **Status**: ✅ Complete (TDD Aligned)
> **Vision Anchor**: `decision-5-processing-account`
> **Phase**: 3
> **Duration**: 2 weeks
> **Dependencies**: EPIC-002, EPIC-004

---

## 🎯 Objective

Implement Processing virtual account for tracking in-transit transfers between accounts, achieving zero-balance pairing validation and automatic transfer detection, maintaining accounting equation integrity at all times.

**Core Rules**:
```
sum(all accounts) + Processing = constant
Balance = 0  → Auto-Accept Transfer Pair ✅
Balance ≠ 0  → Pending Review ⚠️
```

---

## 👥 Multi-Role Review

| Role | Focus | Review Opinion |
|------|--------|----------|
| 🔗 **Reconciler** | Transfer detection | Keyword-based pattern matching with confidence scoring (≥85 auto-accept), handles unpaired transfers |
| 🏗️ **Architect** | System design | Processing account as system account (is_system=true), 3-phase reconciliation flow integration |
| 📊 **Accountant** | Business logic | Double-entry compliance (DEBIT Processing on OUT, CREDIT Processing on IN), equation holds at all times |
| 💻 **Developer** | Performance requirements | Single-query transfer pairing with confidence scoring, O(n²) pairing acceptable for MVP |
| 🧪 **Tester** | Coverage verification | 97% line coverage (processing_account.py), 40 tests (33 unit + 7 integration), all pass |
| 📋 **PM** | User experience | Unpaired transfers visible via Processing balance ≠ 0, supports manual confirmation |

---

## ✅ Task Checklist

### Task 1.1: Documentation
- [x] Create `docs/ssot/processing_account.md` (485 lines)
  - [x] §1: Concept & Purpose
  - [x] §2: Accounting Rules
  - [x] §3: Data Model Design
  - [x] §4: Transfer Detection SOP-001
  - [x] §5: Service API
  - [x] §6: Test Requirements
  - [x] §7: Integration Points (3-phase flow spec)

### Task 1.2: Data Model Design
- [x] Add `is_system` column to `accounts` table
- [x] Alembic migration `c955c65dcc1f_add_is_system_to_accounts.py`
- [x] Update `Account` model and schema
- [x] Update `account_service.py` to handle system accounts

### Task 1.3: Backend Logic
- [x] `services/processing_account.py` (487 lines) - Core service
  - [x] `get_or_create_processing_account()` - Idempotent account creation
  - [x] `detect_transfer_pattern()` - Keyword matching (SOP-001)
  - [x] `create_transfer_out_entry()` - DEBIT Processing, CREDIT source
  - [x] `create_transfer_in_entry()` - DEBIT destination, CREDIT Processing
  - [x] `find_transfer_pairs()` - Confidence scoring (amount 40%, description 30%, date 20%)
  - [x] `get_processing_balance()` - Current balance query
  - [x] `get_unpaired_transfers()` - List unmatched transfers
- [x] Scoring functions implementation
  - [x] `_score_amount_match()` - Amount similarity (exact ≤0.01, close ≤0.10, moderate ≤1.00)
  - [x] `_score_description_match()` - SequenceMatcher (60%) + token overlap (40%)
  - [x] `_score_date_proximity()` - Same day=100%, 7-day window
  - [x] `_calculate_pair_confidence()` - Weighted formula application
- [x] Test coverage: 33 tests, 97% line coverage

### Task 1.4: Reconciliation Integration
- [x] Modified `services/reconciliation.py` (128 lines added)
  - [x] Phase 1: Transfer Detection (lines 766-866) - BEFORE normal matching
  - [x] Phase 2: Normal Matching (lines 867-989) - Existing logic preserved
  - [x] Phase 3: Auto-Pairing (lines 990-1020) - AFTER all matching
- [x] Integration test coverage: 7 tests in `test_transfer_integration.py`
- [x] Bug fixes:
  - [x] Lazy loading issue (added `selectinload(JournalEntry.lines)`)
  - [x] Status filter expansion (`POSTED` → `[POSTED, RECONCILED]` in 2 queries)
  - [x] Duplicate join clause removal
- [x] All 171 tests passing (33 processing + 138 reconciliation)

---

## 🧪 Test Cases

> **The processing-account backend ACs (the former AC15.1–AC15.6 tables) are no
> longer defined here.** They migrated into the `ledger` package (#1420 slice 3c-i)
> and are owned by, and sourced directly from,
> [`common/ledger/contract.py`](../../common/ledger/contract.py)'s `roadmap` under
> the package-scoped `AC-ledger.<group>.<seq>` id scheme (groups 71–76 are the
> reserved processing block; groups 1–70 are held for the EPIC-002/012 double-entry
> ACs that land in slices 3c-ii/iii). `common/ssot/generate_ac_registry.py` reads
> package-contract roadmaps additively, so the AC index counts them without an
> EPIC-table mirror. This note references the new ids (keeping the registry↔EPIC
> link intact) but defines none of them — the contract is the single definition
> source.
>
> **Processing Account Creation**:
> `AC-ledger.71.1` · `AC-ledger.71.2` ·
> `AC-ledger.71.3` · `AC-ledger.71.4`
>
> **Transfer Entry Creation**:
> `AC-ledger.72.1` · `AC-ledger.72.2` ·
> `AC-ledger.72.3`
>
> **Accounting Integrity**:
> `AC-ledger.73.1` · `AC-ledger.73.2`
>
> **Transfer Detection**:
> `AC-ledger.74.1` · `AC-ledger.74.2` ·
> `AC-ledger.74.3`
>
> **Scoring Functions**:
> `AC-ledger.75.1` · `AC-ledger.75.2` ·
> `AC-ledger.75.3` · `AC-ledger.75.4`
>
> **Reconciliation Integration**:
> `AC-ledger.76.1` · `AC-ledger.76.2` ·
> `AC-ledger.76.3` · `AC-ledger.76.4` ·
> `AC-ledger.76.5` · `AC-ledger.76.6` ·
> `AC-ledger.76.7`
>
> The **frontend** UI-gap ACs (AC15.7.*, the Processing-visibility surface) remain
> defined below — `ledger` is a backend-only package, so its roadmap does not home
> them (mirroring how EPIC-001 kept its frontend rows when the `identity` backend
> ACs migrated).

## 📏 Acceptance Criteria

### 🟢 Must Have

| Standard | Verification | Weight |
|------|----------|------|
| **Double-entry compliance** | All transfers create balanced entries (DEBIT = CREDIT) | 🔴 Critical |
| **Accounting equation holds** | `test_processing_account_maintains_equation` | 🔴 Critical |
| **Transfer detection accuracy** | Keyword matching per SOP-001 | Required |
| **Auto-pair threshold ≥85** | `test_find_transfer_pairs_above_threshold` | Required |
| **Zero-balance validation** | Processing balance = 0 for matched pairs | 🔴 Critical |
| **Line coverage ≥97%** | `processing_account.py` coverage report | Required |

### 🌟 Nice to Have

| Standard | Verification | Status |
|------|----------|------|
| **ML-based pattern learning** | History score (currently 0.0) | ⏳ Future |
| **Multi-currency transfer support** | After EPIC-005 (Multi-Currency) | ⏳ Future |
| **Real-time transfer monitoring** | WebSocket alerts for unpaired transfers | ⏳ Future |

### 🚫 Not Acceptable Signals

- Float usage for monetary amounts (MUST use Decimal)
- Unbalanced entries (debit ≠ credit)
- Accounting equation violations (sum ≠ constant)
- Processing balance ≠ 0 for confirmed pairs
- Coverage < 95%

---

## 📚 SSOT References

- [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) - Full specification (processing account folded into ledger)
- [schema.md](../ssot/schema.md) - Account model with is_system flag
- [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) - Double-entry rules
- [reconciliation.md](../ssot/reconciliation.md) - Matching thresholds

---

## 🔗 Deliverables

- [x] `docs/ssot/processing_account.md` (485 lines) - SSOT specification
- [x] `apps/backend/migrations/versions/c955c65dcc1f_add_is_system_to_accounts.py` - Migration
- [x] `apps/backend/src/models/account.py` - is_system flag added
- [x] `apps/backend/src/schemas/account.py` - is_system schema field
- [x] `apps/backend/src/services/account_service.py` - System account handling (31 lines)
- [x] `apps/backend/src/services/processing_account.py` (487 lines) - Core service
- [x] `apps/backend/src/services/reconciliation.py` - 3-phase flow integration (128 lines added)
- [x] `apps/backend/src/services/accounting.py` - Import/export updates (9 lines)
- [x] `apps/backend/tests/accounting/test_processing_account.py` (811 lines) - Unit tests (33 tests)
- [x] `apps/backend/tests/reconciliation/test_transfer_integration.py` (569 lines) - Integration tests (7 tests)

**Git Commit**: SHA `16ee6e9` - "feat: integrate Processing account with reconciliation engine (Task 1.4)"

---

## 📝 Technical Debt

| Item | Priority | Planned Resolution |
|------|--------|--------------|
| **Over-matching risk** | P1 | Track matched IN entries to prevent multiple OUT entries pairing with same IN |
| **Input validation** | P2 | Add positive amount, valid UUID checks to public functions |
| **Zero-amount transfers** | P2 | Add test coverage for zero-amount edge case |
| **Concurrent operations** | P2 | Add transaction isolation tests (DB integrity risk) |
| **History score placeholder** | P3 | ML-based pattern learning (v2.0) |

---

## Issues & Gaps

### Code Review Findings (from background agents)

**Architecture** ✅:
- 3-phase flow correctly follows SSOT §7
- Phase 1 runs BEFORE Phase 2, Phase 3 runs AFTER
- Existing reconciliation logic unchanged (backward compatible)
- Error handling prevents reconciliation breakdown

**Code Quality** ⚠️:
1. **Over-matching risk**: Multiple OUT entries could pair with same IN entry (low probability)
   - Impact: Medium (rare edge case)
   - Fix: Track matched IN entries in `find_transfer_pairs()`
2. **Missing input validation**: No checks for positive amounts, valid UUIDs
   - Impact: Low (caught by DB constraints)
   - Fix: Add validation to public functions
3. **History score**: Hardcoded to 0.0 (acceptable, noted in comments)

**Test Coverage** ⚠️:
1. **Zero-amount transfers**: Not tested (source handles it, but no test)
   - Impact: Medium (edge case)
   - Fix: Add test in `test_processing_account.py`
2. **Concurrent operations**: Not tested
   - Impact: High (DB integrity risk)
   - Fix: Add transaction isolation tests
3. **Empty string descriptions**: Partially tested
   - Impact: Low (code handles it)
   - Fix: Add explicit test

**Conclusion**: Code is production-ready with 97% coverage, 40 passing tests. Issues are non-blocking for MVP (all tests pass, accounting equation holds). Address technical debt before scaling to production volume.

---

## ❓ Q&A (Clarification Required)

### Q1: What happens to unpaired transfers?
> **Decision**: Visible via `get_unpaired_transfers()` and Processing balance ≠ 0. User confirms manually, creating regular journal entry to close Processing account.

### Q2: Auto-pairing threshold rationale?
> **Decision**: Use 85 (same as reconciliation auto-accept) to maintain consistent confidence bar across system.

### Q3: Multi-currency transfer support?
> **Decision**: Out of scope for EPIC-015. Process transfers in base currency only. Multi-currency handled in EPIC-005 (Reporting).

### Q4: History score implementation?
> **Decision**: Hardcoded to 0.0 in MVP. ML-based pattern learning deferred to v2.0 (requires transaction history dataset).

### Q5: Processing account visibility?
> **Decision**: Hidden from `list_accounts()` (is_system=true), but balance and transfers visible via dedicated endpoints (`get_processing_balance()`, `get_unpaired_transfers()`).

---

## 📅 Timeline

| Phase | Content | Status |
|------|------|----------|
| Week 1 | Task 1.1-1.2 (Documentation + Data Model) | ✅ Done |
| Week 1-2 | Task 1.3 (Backend Logic + Tests) | ✅ Done |
| Week 2 | Task 1.4 (Reconciliation Integration + Bug Fixes) | ✅ Done |

**Total Duration**: 2 weeks (Jan 2026 - Feb 2026)

---

## 🔍 Related EPICs

- **EPIC-002** (Double-Entry Core) - Foundation for Processing account entries
- **EPIC-004** (Reconciliation Engine) - Extended with 3-phase transfer detection
- **EPIC-005** (Reporting) - Multi-currency support for future transfer handling

---

## 📊 Test Evidence

### Coverage Report
```
processing_account.py:  97% coverage (472/487 statements)
reconciliation.py:      90% coverage (925/1028 statements)
Total:                  171 tests passing (33 + 138)
```

### Integration Test Results
```
test_transfer_integration.py::TestTransferDetectionDuringReconciliation   PASSED (3 tests)
test_transfer_integration.py::TestTransferAutoPairingPhase                PASSED (2 tests)
test_transfer_integration.py::TestNormalMatchingPhaseIntegration          PASSED (2 tests)
```

### Accounting Equation Validation
```python
# From test_processing_account_maintains_equation
assets = db_assets + processing_balance
liabilities_equity = db_liabilities + db_equity
assert abs(assets - liabilities_equity) < Decimal("0.01")  # ✅ PASSED
```

---

*Completed: February 2026*
*Agent: Sisyphus (primary development agent)*
*Review: Code review completed by 3 background explore agents*

---

## 🆕 UI Gap Audit (April 2026) — Processing Account Visibility

**Origin**: UI gap audit against [Project Vision](../target.md) decision 5 (in-flight transfers must be visible). Backend processing-account flow is complete but the dashboard does not show pending in-transit balance, so users cannot see "money on the road".

### Acceptance Criteria

- [x] **AC15.7.1** API endpoint `GET /api/accounts/processing/summary` returns `{pending_count, pending_total, current_balance, currency, oldest_pending_date}`
- [x] **AC15.7.2** Dashboard "Processing / In-Transit" card renders the four fields with currency code
- [x] **AC15.7.3** Card click-through navigates to `/processing` listing pending transfers (existing or new page) with line items `{from_account, to_account, amount, initiated_date, days_outstanding}`
- [x] **AC15.7.4** Pending entries older than 7 days render a warning badge on the listing row
- [x] **AC15.7.5** Frontend test mounts ProcessingSummaryCard and asserts `pending_count` + `pending_total` labels render
- [x] **AC15.7.6** Processing is discoverable as a card in the Audit hub at `/audit` (superseded the old sidebar entry per EPIC-022 AC22.21.3)
- [x] **AC15.7.7** The Processing Account non-zero-balance warning surfaces on the Home Processing card (AC15.7.8) and the attention inbox; the old sidebar badge was removed with the Advanced drawer (EPIC-022 AC22.21)
- [x] **AC15.7.8** Dashboard Processing card shows the signed current balance and a non-zero balance warning

> **AC15.7.6/AC15.7.7 superseded by EPIC-022 AC22.21**: the Advanced sidebar drawer
> was removed, so Processing discoverability moved to the `/audit` hub and its
> balance warning is carried by the Home Processing card (AC15.7.8) and the
> attention inbox. Rows kept for history with Verification updated to current tests.

| AC ID | Description | Test | Path | Priority |
|-------|-------------|------|------|----------|
| AC15.7.6 | Processing is discoverable as a card in the Audit hub (`/audit`), superseding the old sidebar entry | `AC15.7.6 aggregates the verify-on-demand machinery (incl. Processing) as deep-linking cards` | `apps/frontend/src/__tests__/auditHub.test.tsx` | P1 |
| AC15.7.7 | The sidebar Processing badge was removed with the Advanced drawer; the non-zero-balance warning is carried by the Home Processing card and attention inbox | `AC15.7.7 AC16.19.12 AC19.6.3 AC19.6.4 AC19.6.5 AC22.21.1 keeps the accounting machinery, sidebar badges and settings out of the sidebar (supersedes the Advanced drawer)` | `apps/frontend/src/__tests__/sidebarAndTabs.test.tsx` | P1 |
| AC15.7.8 | Dashboard Processing card shows the signed current balance and a non-zero balance warning | `shows the current Processing Account balance when transfers are unresolved` | `apps/frontend/src/components/__tests__/ProcessingSummaryCard.test.tsx` | P1 |

**Priority**: P0-quick-win — small UI surface; backend already exposes processing-account state.
**Estimated effort**: 1-2 days backend (summary endpoint) + 2-3 days frontend (card + listing).
