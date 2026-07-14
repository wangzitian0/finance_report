# EPIC-016: Two-Stage Review & Data Validation UI

> **Status ownership**: Scope owner only; live delivery status is tracked by
> GitHub issues, AC registries, and executable tests.
> **Vision Anchor**: `decision-4-two-stage-review`
> **Phase**: 3 (Reconciliation Enhancement)
> **Planning estimate**: 4-6 weeks
> **Priority**: P0 (Critical - Foundation for User Adoption)
> **Dependencies**: EPIC-003 (Statement Parsing), EPIC-004 (Reconciliation Engine)
> **Usable milestone**: 🎯 gating (G3). Real-data parse errors must be fixable in two-stage review — a year of real statements will contain mistakes the user has to correct before the numbers are trustworthy. See the [Usable cut](https://github.com/wangzitian0/finance_report/milestone/1).

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

## Source of Truth Ownership

This EPIC owns the AC16.x requirement IDs. Live implementation shape, current
status, and detailed contracts are owned by SSOT docs, code, tests, and issue
state rather than a duplicated phase checklist.

| Fact | Owner |
|---|---|
| `pending_review` state machine and 0.001 USD Stage 1 tolerance | [confirmation-workflow.md](../../common/extraction/confirmation-workflow.md) |
| Reconciliation thresholds, Stage 2 checks, and match lifecycle | [reconciliation.md](../../common/reconciliation/reconciliation.md) |
| Statement, transaction, and match models | [schema.md](../../common/meta/schema.md) |
| Parsing input contract for Stage 1 review | [common/extraction/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/readme.md) |
| Journal entry creation from accepted matches | [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) |
| Backend behavior proof | `apps/backend/tests/review/`, `apps/backend/tests/api/` |
| Frontend and responsive workflow proof | `apps/frontend/src/__tests__/`, `apps/frontend/playwright/` |

Residual review workflow questions that are not yet code-owned must be tracked
as GitHub issues before implementation: duplicate canonical selection,
transfer auto-link policy, first-statement opening balance UX, multi-currency
balance validation, visual diff, keyboard shortcuts, and CSV export.

---

## 📏 Acceptance Criteria
### 🟢 Must Have

> **Partially migrated.** The extraction-owned rows (were AC16.22.* rows
> .8/.9/.10) are homed in the `extraction` package roadmap as
> `AC-extraction.1622.8` · `AC-extraction.1622.9` · `AC-extraction.1622.10`
> ([`common/extraction/contract.py`](../../common/extraction/contract.py));
> the remaining rows below stay with their own owners.

| AC ID | Standard | Verification | Weight |
|------|------|----------|------|
> (AC16.1.1 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.stage1-validation.1`, merged with AC16.22.5 removed, #1821 Wave A)
> **Documented exception (#1821 Wave B):** no automated split-view assertion exists for
> this row's own standard. The nearest evidence (`epic016Components.test.tsx`'s
> `PdfPreviewPane` mount test, migrated as `AC-extraction.fe-stage1-review.12`) only
> asserts the pane mounts in isolation, not that PDF+parsed panes render side by side —
> not real proof of this specific claim, so this row stays `fe-only` residue rather than
> migrating on weak evidence.
| AC16.1.2 | **Stage 1 UI shows PDF + parsed split view** | Manual UI test | 🔴 Critical | <!-- epic-owned: fe-only -->
> (AC16.1.3 removed with no new roadmap entry — a duplicate of `AC16.18.5` ("disables approve when balance validation fails"), migrated under extraction as `AC-extraction.fe-stage1-review.8`, #1821 Wave B)
> (AC16.2.1 removed and AC16.2.2 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.consistency-checks.8` and `.9`, #1821 Wave A. AC16.2.3 removed with no new roadmap entry — a duplicate of the already-migrated `AC-reconciliation.stage2-batch.1`, which cites the identical test test_batch_approve_matches_blocked_by_unresolved_checks.)
> (AC16.2.4 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.1`, #1821 Wave B)

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

- [reconciliation.md](../../common/reconciliation/reconciliation.md) — Reconciliation workflow, confidence thresholds
- [schema.md](../../common/meta/schema.md) — data-layer and migration guardrails
- [Generated DB Schema Reference](../reference/db-schema.md) — current statement, match, consistency-check, and atomic fact inventory
- [common/ledger/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/ledger/readme.md) — Journal entry creation from approved matches
- [common/extraction/readme.md](https://github.com/wangzitian0/finance_report/blob/main/common/extraction/readme.md) — Statement parsing logic (Stage 1 input)

---

## 🔄 Related EPICs

- **EPIC-003**: Statement Parsing → Generates Stage 1 input
- **EPIC-004**: Reconciliation Engine → Consumes Stage 2 output
- **EPIC-015**: Processing Account → Transfer detection logic overlap
- **EPIC-013**: Statement Parsing V2 → Balance chain validation, institution auto-detect

---

## 📋 Acceptance Criteria — Coverage Registry

> The following sections canonicalize all AC16.x.x IDs that extend beyond the Must Have / Nice to Have tables above. Generated registry indexes materialize these EPIC definitions for tooling.

### AC16.3 — Statement Validation Service (Extended Coverage)

> (AC16.3.1 removed and AC16.3.2 removed and AC16.3.3 removed and AC16.3.4 removed and AC16.3.5 removed and AC16.3.6 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.stage1-validation.2` through `.7` (AC16.3.6 merged with AC16.22.6 into `.7`; AC16.3.5's description was stale — edit_and_approve is now unconditionally unsupported, not conditionally balance-checked — `.6`'s statement reflects the current behavior), #1821 Wave A)

### AC16.4 — Consistency Checks Service (Extended Coverage)

> This group's rows removed — migrated to the `reconciliation` package
> roadmap as `AC-reconciliation.consistency-checks.1-7` (migration closeout
> continuation, #1663 / #1711).

### AC16.5 — Frontend Auth Utility (`lib/auth`)

> (AC16.5.1 removed and AC16.5.2 removed and AC16.5.3 removed and AC16.5.4 removed and AC16.5.5 removed, canonical: migrated to the `identity` package roadmap as `AC-identity.fe-auth.1` through `.5`, #1821 Wave B)

### AC16.6 — Frontend Date Utility (`lib/date`)

> (AC16.6.1 removed and AC16.6.2 removed and AC16.6.3 removed and AC16.6.4 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-utils.1` through `.4`, #1821 Wave B)

### AC16.7 — Frontend Theme Utility (`lib/theme`)

> (AC16.7.1 removed and AC16.7.2 removed and AC16.7.3 removed and AC16.7.4 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-utils.5` through `.8`, #1821 Wave B)

### AC16.8 — Frontend AI Models Utility (`lib/aiModels`)

> (AC16.8.1 removed and AC16.8.2 removed and AC16.8.3 removed, canonical: migrated to the `llm` package roadmap as `AC-llm.fe-ai-models-catalog.1` through `.3`, #1821 Wave B)

### AC16.9 — Frontend Currencies Hook (`hooks/useCurrencies`)

> (AC16.9.1 removed and AC16.9.2 removed and AC16.9.3 removed, canonical: migrated to the `pricing` package roadmap as `AC-pricing.fe-currencies.1` through `.3`, #1821 Wave B)

### AC16.10 — Frontend API Client (`lib/api`)

> (AC16.10.1 removed and AC16.10.2 removed and AC16.10.3 removed and AC16.10.4 removed and AC16.10.5 removed and AC16.10.6 removed and AC16.10.7 removed and AC16.10.8 removed and AC16.10.9 removed and AC16.10.10 removed and AC16.10.11 removed and AC16.10.12 removed and AC16.10.13 removed and AC16.10.14 removed and AC16.10.15 removed and AC16.10.16 removed and AC16.10.17 removed and AC16.10.18 removed and AC16.10.19 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-http-client.1` through `.19`, #1821 Wave B (`.20` comes from AC16.17.7 below, same group))

### AC16.11 — Dev Tooling / Infra Commands (Infra)

> This group's rows removed — migrated to the `runtime` package roadmap as
> `AC-runtime.24.1-31` (migration closeout continuation, #1663 / #1714). The
> "⏳" status markers were stale: every row already had a real, passing test
> (`tests/tooling/test_debug.py`, `test_cleanup_orphaned_dbs.py`,
> `test_cli_and_dev_servers.py`) — the EPIC doc just never linked them.

### AC16.12 — Frontend Pages (Core Pages Coverage)

> (AC16.12.1 removed and AC16.12.2 removed and AC16.12.3 removed and AC16.12.4 removed and AC16.12.17 removed and AC16.12.18 removed and AC16.12.19 removed and AC16.12.11 removed and AC16.12.12 removed, canonical: migrated (Dashboard + Reports pages) to the `reporting` package roadmap as `AC-reporting.fe-report-surfaces.1` through `.9`, #1821 Wave B)
> (AC16.12.5 removed and AC16.12.6 removed and AC16.12.7 removed and AC16.12.13 removed and AC16.12.14 removed and AC16.12.15 removed and AC16.12.16 removed, canonical: migrated (Login page) to the `identity` package roadmap as `AC-identity.fe-auth.6` through `.12`, #1821 Wave B)
> (AC16.12.8 removed and AC16.12.9 removed and AC16.12.10 removed, canonical: migrated (Ping-pong demo page) to the `meta` package roadmap as `AC-meta.fe-app-shell.1` through `.3`, #1821 Wave B)

### AC16.13 — Test Lifecycle Infrastructure (Infra)

> These ACs covered `tools/test_lifecycle.py` and test infrastructure
> helpers. The group migrated into the `testing` package roadmap
> (`common/testing/contract.py`, `AC-testing.lifecycle.*`) — the
> namespace/DB-lifecycle mechanism itself already lives in
> `common/testing/test_isolation.py` (migration closeout, #1663 / #1718).

> (AC16.13.1 removed, canonical: migrated to `AC-testing.lifecycle.2`.)
> (AC16.13.2 removed, canonical: migrated to `AC-testing.lifecycle.3`.)
> (AC16.13.3 removed, canonical: migrated to `AC-testing.lifecycle.4`.)
> (AC16.13.4 removed, canonical: migrated to `AC-testing.lifecycle.5`.)
> (AC16.13.5 removed, canonical: migrated to `AC-testing.lifecycle.6`.)
> (AC16.13.6 removed, canonical: migrated to `AC-testing.lifecycle.7`.)
> (AC16.13.7 removed, canonical: migrated to `AC-testing.lifecycle.8`.)
> (AC16.13.8 removed, canonical: migrated to `AC-testing.lifecycle.9`.)
> (AC16.13.9 removed, canonical: migrated to `AC-testing.lifecycle.10`.)
> (AC16.13.10 removed, canonical: migrated to `AC-testing.lifecycle.11`.)
> (AC16.13.11 removed, canonical: migrated to `AC-testing.lifecycle.12`.)
> (AC16.13.12 removed, canonical: migrated to `AC-testing.lifecycle.13`.)

### AC16.14 — Frontend Report Pages and Statements Page

> (AC16.14.1 removed and AC16.14.2 removed and AC16.14.3 removed and AC16.14.4 removed and AC16.14.5 removed and AC16.14.6 removed and AC16.14.7 removed and AC16.14.8 removed and AC16.14.9 removed, canonical: migrated (Balance-sheet, Income-statement, Cash-flow pages) to the `reporting` package roadmap as `AC-reporting.fe-report-surfaces.10` through `.18`, #1821 Wave B)
> (AC16.14.10 removed and AC16.14.11 removed and AC16.14.12 removed, canonical: migrated (Statements page) to the `extraction` package roadmap as `AC-extraction.fe-stage1-review.1` through `.3`, #1821 Wave B)

### AC16.15 — Frontend Accounts and Assets Pages

> (AC16.15.1 removed and AC16.15.2 removed and AC16.15.3 removed and AC16.15.7 removed and AC16.15.8 removed and AC16.15.9 removed and AC16.15.10 removed, canonical: migrated (Accounts page — the `.7-10` rows were undocumented "stub" placeholders; their real proof is `accountsPage.test.tsx`'s edit/add/modal-lifecycle tests) to the `ledger` package roadmap as `AC-ledger.fe-accounts-journal.1` through `.7`, #1821 Wave B)
> (AC16.15.4 removed and AC16.15.5 removed and AC16.15.6 removed, canonical: migrated (Assets page) to the `portfolio` package roadmap as `AC-portfolio.fe-assets.1` through `.3`, #1821 Wave B)

### AC16.16 — Frontend App Structure (Root, Layout, Journal Page)

> (AC16.16.1 removed and AC16.16.2 removed, canonical: migrated (Root/Main layout, app-shell chrome) to the `meta` package roadmap as `AC-meta.fe-app-shell.4` and `.5`, #1821 Wave B)
> (AC16.16.3 removed, canonical: migrated (Chat page) to the `advisor` package roadmap as `AC-advisor.fe-chat.1`, #1821 Wave B)
> (AC16.16.4 removed, canonical: migrated (Reconciliation entry pages) to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.2`, #1821 Wave B)
> (AC16.16.5 removed and AC16.16.6 removed and AC16.16.7 removed and AC16.16.8 removed, canonical: migrated (Journal page) to the `ledger` package roadmap as `AC-ledger.fe-accounts-journal.8` through `.11`, #1821 Wave B)

### AC16.17 — Stage 2 Review Queue Page and Root Layout

> (AC16.17.1 removed and AC16.17.2 removed and AC16.17.3 removed and AC16.17.4 removed, canonical: migrated (Stage 2 review queue) to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.3` through `.6`, #1821 Wave B)
> (AC16.17.5 removed and AC16.17.6 removed, canonical: migrated (Root layout composition) to the `meta` package roadmap as `AC-meta.fe-app-shell.6` and `.7`, #1821 Wave B)
> (AC16.17.7 removed, canonical: migrated (API catch-all route) to the `meta` package roadmap as `AC-meta.fe-http-client.20`, #1821 Wave B)

### AC16.18 — Statement Detail and Stage 1 Review Pages

> (AC16.18.1 removed and AC16.18.2 removed and AC16.18.3 removed and AC16.18.4 removed and AC16.18.5 removed and AC16.18.6 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.fe-stage1-review.4` through `.9`, #1821 Wave B)

### AC16.19 — App Shell, Auth, Shared Components, and Chat

> (AC16.19.1 removed and AC16.19.2 removed, canonical: migrated (auth guard / auth-aware session) to the `identity` package roadmap as `AC-identity.fe-auth.13` through `.14`, #1821 Wave B)
> (AC16.19.3 removed and AC16.19.4 removed and AC16.19.7 removed and AC16.19.8 removed and AC16.19.9 removed and AC16.19.12 removed and AC16.19.13 removed and AC16.19.14 removed and AC16.19.15 removed and AC16.19.16 removed and AC16.19.17 removed, canonical: migrated (sidebar/workspace-tabs/confirm-dialog/toast app-shell chrome) to the `meta` package roadmap as `AC-meta.fe-app-shell.8` through `.18`, #1821 Wave B)
> (AC16.19.5 removed and AC16.19.6 removed, canonical: migrated (chat) to the `advisor` package roadmap as `AC-advisor.fe-chat.2` through `.3`, #1821 Wave B)
> (AC16.19.10 removed and AC16.19.11 removed, canonical: migrated (bar/pie/trend charts) to the `reporting` package roadmap as `AC-reporting.fe-report-surfaces.19` through `.20`, #1821 Wave B)

### AC16.20 — Reconciliation Workbench and Chat Panel Components

> (AC16.20.1 removed and AC16.20.2 removed and AC16.20.3 removed and AC16.20.4 removed and AC16.20.6 removed, canonical: migrated (reconciliation workbench / unmatched board) to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.7` through `.11`, #1821 Wave B)
> (AC16.20.5 removed and AC16.20.7 removed, canonical: migrated (chat panel) to the `advisor` package roadmap as `AC-advisor.fe-chat.4` through `.5`, #1821 Wave B)

### AC16.21 — Account Form, Journal Entry Form, Sankey Chart, Workspace Provider

> (AC16.21.1 removed and AC16.21.2 removed and AC16.21.3 removed and AC16.21.4 removed and AC16.21.5 removed and AC16.21.6 removed, canonical: migrated (account/journal entry forms) to the `ledger` package roadmap as `AC-ledger.fe-accounts-journal.12` through `.17`, #1821 Wave B)
> (AC16.21.7 removed and AC16.21.8 removed, canonical: migrated (sankey chart) to the `reporting` package roadmap as `AC-reporting.fe-report-surfaces.21` through `.22`, #1821 Wave B)
> (AC16.21.9 removed and AC16.21.10 removed, canonical: migrated (workspace provider) to the `meta` package roadmap as `AC-meta.fe-app-shell.19` through `.20`, #1821 Wave B)

### AC16.22 — Confirmation Workflow (cross-cutting `pending_review` state machine)

> See authoritative definition: [common/extraction/confirmation-workflow.md](../../common/extraction/confirmation-workflow.md)

> **Partially migrated.** *(AC16.22.3 removed and AC16.22.4 removed — this
> group's Stage-2 rows migrated to the `reconciliation` package roadmap as
> `AC-reconciliation.stage2-batch.1-2`, migration closeout continuation,
> #1663 / #1711)*. The Stage-1 statement-validation rows below stay with
> their own owner.

> (AC16.22.1 removed and AC16.22.2 removed and AC16.22.5 removed and AC16.22.6 removed and AC16.22.7 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.stage1-validation.8`, `.9`, `.1` (AC16.22.5 merged with AC16.1.1), `.7` (AC16.22.6 merged with AC16.3.6), `.10`, #1821 Wave A)

### AC16.25 — Mobile Review UX Hardening

> (AC16.25.1 removed and AC16.25.2 removed, canonical: migrated (mobile review navigation, AI suggestion queue) to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.12` through `.13`, #1821 Wave B)
> (AC16.25.3 removed, canonical: migrated (journal entry mobile cards) to the `ledger` package roadmap as `AC-ledger.fe-accounts-journal.18`, #1821 Wave B)
> (AC16.25.4 removed, canonical: migrated (root layout theme color) to the `meta` package roadmap as `AC-meta.fe-app-shell.21`, #1821 Wave B)

### AC16.26 — Mobile Review Workflow Completion

> (AC16.26.1 removed, canonical: migrated (Stage 1 mobile review) to the `extraction` package roadmap as `AC-extraction.fe-stage1-review.10`, #1821 Wave B)
> (AC16.26.2 removed and AC16.26.3 removed, canonical: migrated (Stage 2 mobile queue/run review) to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.14` through `.15`, #1821 Wave B)

### AC16.27 — Responsive Review Layout Completion

> (AC16.27.1 removed and AC16.27.3 removed, canonical: migrated (Stage 2 mobile/ desktop review) to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.16` through `.17` (`.1`'s real proof is `stage2ReviewQueueCoverage99.test.tsx`, not the stale `TransactionTable.test.tsx` citation this row previously carried), #1821 Wave B)
> (AC16.27.2 removed, canonical: migrated (Stage 1 desktop review) to the `extraction` package roadmap as `AC-extraction.fe-stage1-review.11`, #1821 Wave B)


---

## Historical Audit Notes

The April 2026 FE/UI audit snapshot was removed from this EPIC. Current review UI scope is represented by the AC groups below and executable frontend/E2E tests.

---

## 🆕 UI Gap Audit (April 2026) — Stage 1 Refactor, Inline Edit, Conflict Resolution & Mobile Nav

**Origin**: UI gap audit against [Project Vision](../target.md) decision 4 (two-stage review must be production-grade). Stage 1 page is monolithic, has no inline edit, no conflict resolution UI, no mobile navigation. These block real-user adoption of the review flow.

### Acceptance Criteria — Feature (group 23)

> **Documented exceptions (#1821 Wave B):** the `AC16.23.1`, `AC16.23.2`, and
> `AC16.23.5` ids below are each coincidentally reused by an unrelated later test
> (dashboardPage.test.tsx's "This Month KPI" tests for `.1`/`.2`; reportsPage.test.tsx's
> "renders SVG icons for report cards" for `.5`) that does not verify this row's own
> stated standard. No real test proves the original claim, so these three stay
> `fe-only` residue rather than migrating on a false anchor.
- [x] **AC16.23.1** Stage 1 page split into `<PdfPreviewPane />`, `<TransactionTable />`, `<ReviewActionBar />`, `<BalanceIndicator />` components, each independently mountable <!-- epic-owned: fe-only -->
- [x] **AC16.23.2** TransactionTable supports inline edit of `amount`, `description`, `date` with optimistic update + server confirm; failed write reverts row and shows error toast <!-- epic-owned: fe-only -->
> (AC16.23.3 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.18`, #1821 Wave B)
> (AC16.23.4 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.19`, #1821 Wave B)
- [x] **AC16.23.5** Mobile navigation renders below 768 px (originally the `<MobileNav />` drawer; replaced by the `<BottomTabBar />` bottom tab bar per EPIC-022 AC22.21); the desktop sidebar is hidden on mobile <!-- epic-owned: fe-only -->
> (AC16.23.6 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.fe-stage1-review.12`, #1821 Wave B)

### Acceptance Criteria — Feature (group 24, run-level Stage 2)

> (AC16.24.1 removed, AC16.24.2 removed, and AC16.24.3 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.20` through `.22`, #1821 Wave B)
*(AC16.24.4 removed, canonical: migrated to the `reconciliation` package
roadmap as `AC-reconciliation.stage2-batch.5`, #1821 Wave A)*

### Acceptance Criteria — Feature (group 31, review contract hardening)

The June 2026 UI audit found several high-line-coverage review tests that
validated mocked UI-only state rather than backend-owned review contracts.
These ACs close those gaps without changing the underlying reconciliation data
model.

> (AC16.31.1 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.23`, #1821 Wave B)
> (AC16.31.2 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.fe-stage1-review.13`, #1821 Wave B)
> (AC16.31.3 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.24`, #1821 Wave B)
> (AC16.31.4 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.25`, #1821 Wave B)
> (AC16.33.4 removed and AC16.33.5 removed — backend halves migrated to the `extraction` package roadmap as `AC-extraction.document-delivery.1-2`, #1821 Wave A. The frontend embedding assertions in apps/frontend/src/__tests__/reviewPages.test.tsx are not tracked by this Python-only roadmap.)

### AC16.32 — Review Workflow Hardening

| AC ID | Description | Tests | Files | Priority |
|-------|-------------|-------|-------|----------|
> (AC16.32.1 removed — backend half migrated to the `reconciliation` package roadmap as `AC-reconciliation.conflict-resolution.1`, #1821 Wave A. The frontend assertion in apps/frontend/src/__tests__/statementReviewPage.test.tsx is not tracked by this Python-only roadmap.)
> (AC16.32.2 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.fe-stage1-review.14`, #1821 Wave B)
> (AC16.32.3 removed — frontend half migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.26` (backend half already `AC-reconciliation.review-hardening.1`), #1821 Wave B)

### AC16.34 — Stage-1 Conflict Resolution ([#962](https://github.com/wangzitian0/finance_report/issues/962))

A statement with an inherent (legitimate) duplicate or transfer-pair candidate
was permanently stuck in `parsed`: the conflict guard blocked approval and there
was no way to record the reviewer's decision. These ACs add a resolution path so
the reviewer can confirm the rows are genuinely distinct (or a real transfer
pair) and unblock approval.

| AC ID | Description | Tests | Files | Priority |
|-------|-------------|-------|-------|----------|
> (AC16.34.1 removed and AC16.34.2 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.conflict-resolution.2` and `.3`, #1821 Wave A)
> (AC16.34.3 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.27`, #1821 Wave B)

### Acceptance Criteria — Feature (group 28, frontend UI system primitives)

Issue [#612](https://github.com/wangzitian0/finance_report/issues/612)
tracks the first frontend UI-system hardening slice. EPIC-016 owns this
because the review workflow depends on consistent dense application controls,
status states, and accessible icon actions across the authenticated frontend.
This group is intentionally conservative: it creates a React-level primitive
layer while preserving the existing visual language and leaving the deeper token
and visual-regression follow-ups to issues #613 and #614.

> (AC16.28.1 removed, AC16.28.2 removed, AC16.28.3 removed, and AC16.28.4 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-app-shell.22` through `.25`, #1821 Wave B)

### Acceptance Criteria — Feature (group 29, frontend design tokens)

Issue [#613](https://github.com/wangzitian0/finance_report/issues/613)
tracks the second frontend UI-system hardening slice. It expands the existing
CSS-variable theme into an explicit design-token contract so authenticated
review, account, report, and AI surfaces can share semantic colors, spacing,
radius, elevation, z-index, motion, and chart palette decisions without
hardcoded Tailwind palette drift.

> (AC16.29.1 removed, AC16.29.2 removed, AC16.29.3 removed, and AC16.29.4 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-app-shell.26` through `.29`, #1821 Wave B)

### Acceptance Criteria — Feature (group 30, frontend verification hardening)

Issue [#614](https://github.com/wangzitian0/finance_report/issues/614)
tracks the final frontend UI-system hardening slice for EPIC-016. It closes
the actionable follow-ups from issues #612 and #613, strengthens semantic
navigation and accessibility coverage, and adds representative visual smoke
coverage so future review, account, statement, and shell changes cannot bypass
the shared UI-system contract.

> (AC16.30.1 removed, AC16.30.2 removed, AC16.30.3 removed, AC16.30.4 removed, AC16.30.5 removed, and AC16.30.6 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-app-shell.30` through `.35`, #1821 Wave B)

### Acceptance Criteria — Infra (group 11, test infra extension)

- [x] **AC16.11.32** Vitest harness for Stage 1 split components — shared `renderReviewComponent()` helper in `apps/frontend/src/__tests__/helpers/` <!-- epic-owned: horizontal -->
- ~~Playwright smoke covers inline-edit happy path on Stage 1~~ — **retired**: inline transaction editing was removed in EPIC-011 Stage 3 (parsed transactions are immutable; the correction path is reject + re-parse), so the inline-edit acceptance criterion and its Playwright smoke are removed.

### Acceptance Criteria — Infra (group 13, conflict resolution backend contract)

> (AC16.13.13 removed and AC16.13.14 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.conflict-resolution.4` and `.5`, #1821 Wave A)

**Priority**: P0 — Stage 1 monolith is the #1 reported UX blocker.
**Estimated effort**: 6-8 days frontend (component split + inline edit + conflict dialog + mobile nav) + 2-3 days backend (conflicts endpoint) + 1-2 days test infra.

### AC16.35: Stage-2 Batch Endpoints Typed Contract ([#1001](https://github.com/wangzitian0/finance_report/issues/1001))

Tier 1 of #1000. The Stage-2 batch endpoints in `apps/backend/src/routers/review.py`
replace `response_model=dict` + `{"success": false}`-in-body with typed
`BatchApproveResponse`/`BatchRejectResponse`, and unresolved consistency checks
surface as a proper 409 structured error. `Stage2ReviewQueueResponse.pending_matches`
is a typed `Stage2PendingMatch`, not `list[dict]`.

> This group's rows removed — migrated to the `reconciliation` package
> roadmap as `AC-reconciliation.stage2-batch.3-4` (migration closeout
> continuation, #1663 / #1711).

### AC16.36: Dedicated Stage-2 Review Surface ([#1001](https://github.com/wangzitian0/finance_report/issues/1001))

Tier 1 of #1000. Stage-2 review gets a first-class `/review` route instead of being
reachable only via `/reconciliation/review-queue` (nested under the reconciliation
workbench — "parasitic on statements"). The Attention center and the home Risk-radar
deep-link to `/review`; the run-scoped variant stays at `/review/run/[runId]`. Per the
EPIC-022 IA (AC22.2.4) review stays out of the sidebar — it is reached from the
attention/notification flow, not a standalone nav peer.

> (AC16.36.1 removed and AC16.36.2 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-stage2-review.28` and `.29`, #1821 Wave B)

---

## Historical Implementation Notes

The merged implementation plan was removed from this EPIC. Current delivery proof is represented by AC definitions, tests, SSOT docs, and issue state.
