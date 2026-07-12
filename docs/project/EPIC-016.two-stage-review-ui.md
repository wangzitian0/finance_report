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
| `pending_review` state machine and 0.001 USD Stage 1 tolerance | [confirmation-workflow.md](../ssot/confirmation-workflow.md) |
| Reconciliation thresholds, Stage 2 checks, and match lifecycle | [reconciliation.md](../ssot/reconciliation.md) |
| Statement, transaction, and match models | [schema.md](../ssot/schema.md) |
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
| AC16.1.1 | **Balance validation tolerance = 0.001 USD** | `test_validate_balance_chain_within_tolerance()` | 🔴 Critical | <!-- epic-owned: pending-package -->
| AC16.1.2 | **Stage 1 UI shows PDF + parsed split view** | Manual UI test | 🔴 Critical | <!-- epic-owned: fe-only -->
| AC16.1.3 | **Approve button disabled if balance invalid** | Frontend unit test | Required | <!-- epic-owned: fe-only -->
| AC16.2.1 | **Deduplication detection accuracy ≥ 95%** | `test_detect_duplicates_*()` | Required | <!-- epic-owned: pending-package -->
| AC16.2.2 | **Transfer pair detection accuracy ≥ 90%** | `test_detect_transfer_pairs_*()` | Required | <!-- epic-owned: pending-package -->
| AC16.2.3 | **Batch approve blocked if unresolved checks** | `test_batch_approve_requires_checks_resolved()` | Required | <!-- epic-owned: pending-package -->
| AC16.2.4 | **Stage 2 UI supports batch operations** | Manual UI test | Required | <!-- epic-owned: fe-only -->

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
- [schema.md](../ssot/schema.md) — data-layer and migration guardrails
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

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.3.1 | `validate_balance_chain` raises `ValueError` when statement not found | ⏳ | <!-- epic-owned: pending-package -->
| AC16.3.2 | `_get_opening_balance` falls back to `opening_balance` when no prev statement exists | ⏳ | <!-- epic-owned: pending-package -->
| AC16.3.3 | `_get_opening_balance` uses prev statement `closing_balance` when available | ⏳ | <!-- epic-owned: pending-package -->
| AC16.3.4 | `reject_statement` without reason clears `validation_error` | ⏳ | <!-- epic-owned: pending-package -->
| AC16.3.5 | `edit_and_approve` raises `ValueError` when balance is still invalid after edits | ⏳ | <!-- epic-owned: pending-package -->
| AC16.3.6 | `_get_statement_for_update` raises `ValueError` when wrong `user_id` supplied | ⏳ | <!-- epic-owned: pending-package -->

### AC16.4 — Consistency Checks Service (Extended Coverage)

> This group's rows removed — migrated to the `reconciliation` package
> roadmap as `AC-reconciliation.consistency-checks.1-7` (migration closeout
> continuation, #1663 / #1711).

### AC16.5 — Frontend Auth Utility (`lib/auth`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.5.1 | `getUserId` returns `null` when not set | ⏳ | <!-- epic-owned: fe-only -->
| AC16.5.2 | `getUserId` returns stored `userId` from `localStorage` | ⏳ | <!-- epic-owned: fe-only -->
| AC16.5.3 | `setUser` stores `userId`, `email`, and optional `token` | ⏳ | <!-- epic-owned: fe-only -->
| AC16.5.4 | `clearUser` removes all auth keys from `localStorage` | ⏳ | <!-- epic-owned: fe-only -->
| AC16.5.5 | `isAuthenticated` returns `false` when no token, `true` when token exists | ⏳ | <!-- epic-owned: fe-only -->

### AC16.6 — Frontend Date Utility (`lib/date`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.6.1 | `formatDateInput` formats `Date` as `YYYY-MM-DD` with zero-padded month and day | ⏳ | <!-- epic-owned: fe-only -->
| AC16.6.2 | formats a Date object to en-US short date", () => { | `date.test` | `__tests__/date.test.ts` | P1 | <!-- epic-owned: fe-only -->
| AC16.6.3 | formats a Date object with date and time", () => { | `date.test` | `__tests__/date.test.ts` | P1 | <!-- epic-owned: fe-only -->
| AC16.6.4 | returns short month name from date string", () => { | `date.test` | `__tests__/date.test.ts` | P1 | <!-- epic-owned: fe-only -->

### AC16.7 — Frontend Theme Utility (`lib/theme`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.7.1 | `getTheme` returns stored value or system preference | ⏳ | <!-- epic-owned: fe-only -->
| AC16.7.2 | `setTheme` adds/removes `dark` CSS class and saves to `localStorage` | ⏳ | <!-- epic-owned: fe-only -->
| AC16.7.3 | `toggleTheme` switches between dark and light | ⏳ | <!-- epic-owned: fe-only -->
| AC16.7.4 | `initTheme` applies stored or system theme on load | ⏳ | <!-- epic-owned: fe-only -->

### AC16.8 — Frontend AI Models Utility (`lib/aiModels`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.8.1 | `fetchAiModels` calls `/api/llm/catalog` with no params when no options provided _(EPIC-023: repointed from the retired `/api/ai/models` to the local catalogue)_ | ⏳ | <!-- epic-owned: fe-only -->
| AC16.8.2 | `fetchAiModels` appends `modality` query param when provided | ⏳ | <!-- epic-owned: fe-only -->
| AC16.8.3 | `fetchAiModels` appends `free_only=true` when `freeOnly` is set | ⏳ | <!-- epic-owned: fe-only -->

### AC16.9 — Frontend Currencies Hook (`hooks/useCurrencies`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.9.1 | `useCurrencies` returns default currencies while loading | ⏳ | <!-- epic-owned: fe-only -->
| AC16.9.2 | `useCurrencies` updates currencies from API response | ⏳ | <!-- epic-owned: fe-only -->
| AC16.9.3 | `useCurrencies` falls back to defaults on API error | ⏳ | <!-- epic-owned: fe-only -->

### AC16.10 — Frontend API Client (`lib/api`)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.10.1 | `apiFetch` returns JSON on `200` response | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.2 | `apiFetch` returns `undefined` on `204 No Content` | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.3 | `apiFetch` throws error with `detail` message on non-ok response | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.4 | `apiFetch` throws on non-JSON error text | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.5 | `apiFetch` calls `handle401Redirect` on `401` response | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.6 | `resetRedirectGuard` resets the redirect guard state | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.7 | `apiDelete` succeeds on `200` response | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.8 | `apiDelete` throws on non-ok response | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.9 | `apiStream` returns response and `sessionId` on success | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.10 | `apiStream` throws on non-ok response | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.11 | `apiUpload` returns JSON on `200` response | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.12 | `apiUpload` returns `undefined` on `204 No Content` | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.13 | `apiFetch` normalizes path without leading slash | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.14 | `apiFetch` includes `Authorization` header when token is present | ⏳ | <!-- epic-owned: fe-only -->
| AC16.10.15 | handles 401 redirect in apiDelete', async () => { | `apiFunctions.test` | `__tests__/apiFunctions.test.ts` | P1 | <!-- epic-owned: fe-only -->
| AC16.10.16 | includes Authorization header when token present', async () => { | `apiFunctions.test` | `__tests__/apiFunctions.test.ts` | P1 | <!-- epic-owned: fe-only -->
| AC16.10.17 | handles 401 redirect in apiUpload', async () => { | `apiFunctions.test` | `__tests__/apiFunctions.test.ts` | P1 | <!-- epic-owned: fe-only -->
| AC16.10.18 | throws with detail message on JSON error response', async () => { | `apiFunctions.test` | `__tests__/apiFunctions.test.ts` | P1 | <!-- epic-owned: fe-only -->
| AC16.10.19 | throws with raw text on non-JSON error response', async () => { | `apiFunctions.test` | `__tests__/apiFunctions.test.ts` | P1 | <!-- epic-owned: fe-only -->

### AC16.11 — Dev Tooling / Infra Commands (Infra)

> This group's rows removed — migrated to the `runtime` package roadmap as
> `AC-runtime.24.1-31` (migration closeout continuation, #1663 / #1714). The
> "⏳" status markers were stale: every row already had a real, passing test
> (`tests/tooling/test_debug.py`, `test_cleanup_orphaned_dbs.py`,
> `test_cli_and_dev_servers.py`) — the EPIC doc just never linked them.

### AC16.12 — Frontend Pages (Core Pages Coverage)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.12.1 | Dashboard page shows loading state before API responses resolve | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.2 | Dashboard page renders error fallback and retry action when API request fails | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.3 | Dashboard page renders KPI, charts, and recent activity when API requests succeed | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.4 | Dashboard page renders empty-state copy when trend or activity datasets are empty | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.17 | Dashboard page renders first-time onboarding when accounts, statements, or posted review output are missing | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.18 | Dashboard onboarding links users to Accounts, Statements upload, and Review in one click | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.19 | Dashboard hides onboarding once an approved statement and posted journal entry exist | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.5 | Login page submits login payload and redirects on success | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.6 | Login page toggles register mode and switches endpoint for submit | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.7 | Login page shows API error messages and resets loading state on failure | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.8 | Ping-pong page loads initial state and displays current ping/pong value | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.9 | Ping-pong page toggles state and updates toggle count on button click | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.10 | Ping-pong page renders retry flow when initial load fails | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.11 | Reports page renders all report cards with links for available reports | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.12 | Reports page displays accounting equation section content | ⏳ | <!-- epic-owned: fe-only -->
| AC16.12.13 | toggles password visibility", () => { | `loginPage.test` | `__tests__/loginPage.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.12.14 | shows error with alert role and aria-live", async () => { | `loginPage.test` | `__tests__/loginPage.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.12.15 | shows mode toggle links", () => { | `loginPage.test` | `__tests__/loginPage.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.12.16 | shows loading spinner during submission", async () => { | `loginPage.test` | `__tests__/loginPage.test.tsx` | P1 | <!-- epic-owned: fe-only -->

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

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.14.1 | Balance-sheet page renders loading and error retry states | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.2 | Balance-sheet page renders totals and account sections on successful fetch | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.3 | Balance-sheet page toggles account tree expansion controls | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.4 | Income-statement page renders loading and error retry states | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.5 | Income-statement page renders KPI cards and category lists on success | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.6 | Income-statement page tag filters can be selected and cleared | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.7 | Cash-flow page renders loading and error retry states | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.8 | Cash-flow page renders summary and section cards on success | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.9 | Cash-flow page renders sankey chart when summary exists | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.10 | Statements page renders loading, error, empty, and populated states | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.11 | Statements page enables polling when parsing status is present | ⏳ | <!-- epic-owned: fe-only -->
| AC16.14.12 | Statements page delete action calls delete API and toast on confirm | ⏳ | <!-- epic-owned: fe-only -->

### AC16.15 — Frontend Accounts and Assets Pages

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.15.1 | Accounts page renders loading and error retry states | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.2 | Accounts page renders grouped account cards and type filters on successful fetch | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.3 | Accounts page delete action confirms and calls delete API with success toast | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.4 | Assets page renders loading and error retry states | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.5 | Assets page renders grouped positions and status filters on successful fetch | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.6 | Assets page reconcile action calls API and shows toast summary | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.7 | stub | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.8 | stub | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.9 | stub | ⏳ | <!-- epic-owned: fe-only -->
| AC16.15.10 | stub | ⏳ | <!-- epic-owned: fe-only -->

### AC16.16 — Frontend App Structure (Root, Layout, Journal Page)

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.16.1 | Root resolves to the authenticated Home entry (superseded by EPIC-022) | ⏳ | <!-- epic-owned: fe-only -->
| AC16.16.2 | Main layout renders children through `AppShell` wrapper | ⏳ | <!-- epic-owned: fe-only -->
| AC16.16.3 | Chat page renders advisor client within suspense boundary | ⏳ | <!-- epic-owned: fe-only -->
| AC16.16.4 | Reconciliation entry pages render workbench and unmatched board components | ⏳ | <!-- epic-owned: fe-only -->
| AC16.16.5 | Journal page renders error state and retries loading entries | ⏳ | <!-- epic-owned: fe-only -->
| AC16.16.6 | Journal page filters entries by status and renders totals | ⏳ | <!-- epic-owned: fe-only -->
| AC16.16.7 | Journal page draft actions post and delete entries with API calls | ⏳ | <!-- epic-owned: fe-only -->
| AC16.16.8 | Journal page void flow submits reason and refreshes entries | ⏳ | <!-- epic-owned: fe-only -->

### AC16.17 — Stage 2 Review Queue Page and Root Layout

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.17.1 | Stage 2 review queue shows failure fallback and supports retry | ⏳ | <!-- epic-owned: fe-only -->
| AC16.17.2 | Stage 2 review queue indicates unresolved checks and disables batch approval | ⏳ | <!-- epic-owned: fe-only -->
| AC16.17.3 | Stage 2 review queue performs batch reject and approve API workflows | ⏳ | <!-- epic-owned: fe-only -->
| AC16.17.4 | Stage 2 review queue resolves consistency checks through dialog actions | ⏳ | <!-- epic-owned: fe-only -->
| AC16.17.5 | Root layout composes `Providers` and `AuthGuard` around children | ⏳ | <!-- epic-owned: fe-only -->
| AC16.17.6 | `Providers` wraps children with `QueryClientProvider` | ⏳ | <!-- epic-owned: fe-only -->
| AC16.17.7 | API catch-all handlers return JSON `503` for all HTTP methods | ⏳ | <!-- epic-owned: fe-only -->

### AC16.18 — Statement Detail and Stage 1 Review Pages

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.18.1 | Statement detail page loads statement data and renders parsed transactions summary | ⏳ | <!-- epic-owned: fe-only -->
| AC16.18.2 | Statement detail page approve and reject actions call corresponding APIs | ⏳ | <!-- epic-owned: fe-only -->
| AC16.18.3 | Statement detail page retry action posts retry API and refreshes data | ⏳ | <!-- epic-owned: fe-only -->
| AC16.18.4 | Statement review page shows error fallback and supports retry | ⏳ | <!-- epic-owned: fe-only -->
| AC16.18.5 | Statement review page disables approve when balance validation fails | ⏳ | <!-- epic-owned: fe-only -->
| AC16.18.6 | Statement review page approve and reject actions call APIs and navigate back to statements | ⏳ | <!-- epic-owned: fe-only -->

### AC16.19 — App Shell, Auth, Shared Components, and Chat

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.19.1 | App shell renders workspace providers and main content with collapse-aware layout | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.2 | Auth guard redirects unauthenticated protected routes and allows public routes | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.3 | Sidebar shows auth-aware actions and logout triggers `clearUser` plus login redirect | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.4 | Workspace tabs derive route labels and invoke add/set/remove tab handlers | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.5 | Chat page client enforces disclaimer consent and passes initial prompt into chat panel | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.6 | Chat widget hides on chat route and toggles panel visibility elsewhere | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.7 | Confirm dialog handles required input, cancel, and confirm interactions | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.8 | Confirm dialog responds to escape key and backdrop click when not loading | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.9 | Toast provider shows, dismisses, and auto-expires notifications | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.10 | Bar and pie chart components render semantic labels and filtered data | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.11 | Trend chart renders line/area paths and point labels for provided series | ⏳ | <!-- epic-owned: fe-only -->
| AC16.19.12 | sidebar nav shows Portfolio label for /assets route", async () => { | `sidebarAndTabs.test` | `__tests__/sidebarAndTabs.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.19.13 | WorkspaceTabs labels /assets tab as Portfolio from ROUTE_CONFIG", async () => { | `sidebarAndTabs.test` | `__tests__/sidebarAndTabs.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.19.14 | WorkspaceTabs section header is Open Tabs in both empty and active states", () => { | `sidebarAndTabs.test` | `__tests__/sidebarAndTabs.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.19.15 | navigates workspace pages with ArrowRight keyboard", () => { | `sidebarAndTabs.test` | `__tests__/sidebarAndTabs.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.19.16 | renders dialog with ARIA attributes", () => { | `confirmDialogComponent.test` | `__tests__/confirmDialogComponent.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.19.17 | traps focus with Tab and Shift+Tab", () => { | `confirmDialogComponent.test` | `__tests__/confirmDialogComponent.test.tsx` | P1 | <!-- epic-owned: fe-only -->

### AC16.20 — Reconciliation Workbench and Chat Panel Components

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.20.1 | Reconciliation workbench loads stats and pending queue with default selection | ⏳ | <!-- epic-owned: fe-only -->
| AC16.20.2 | Reconciliation workbench triggers run, accept, reject, and batch accept APIs | ⏳ | <!-- epic-owned: fe-only -->
| AC16.20.3 | Unmatched board loads transactions and creates journal entry for selected item | ⏳ | <!-- epic-owned: fe-only -->
| AC16.20.4 | Unmatched board flag and ignore actions update list and local state | ⏳ | <!-- epic-owned: fe-only -->
| AC16.20.5 | Chat panel sends streaming responses, loads suggestions/history, and clears session | ⏳ | <!-- epic-owned: fe-only -->
| AC16.20.6 | score distribution renders 0% height for buckets with value 0", async () => { | `reconciliationWorkbenchComponent.test` | `__tests__/reconciliationWorkbenchComponent.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.20.7 | handles missing stream reader", async () => { | `chatPanelComponent.test` | `__tests__/chatPanelComponent.test.tsx` | P1 | <!-- epic-owned: fe-only -->

### AC16.21 — Account Form, Journal Entry Form, Sankey Chart, Workspace Provider

| AC ID | Description | Status |
|-------|-------------|--------|
| AC16.21.1 | Account form modal create mode submits normalized payload and closes on success | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.2 | Account form modal edit mode pre-fills values and submits update payload | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.3 | Account form modal surfaces API errors and field validation feedback | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.4 | Journal entry form loads account options and enforces balanced double-entry totals | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.5 | Journal entry form creates draft entries with normalized line amounts and optional posting | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.6 | Journal entry form supports dynamic line add/remove and submit-time error handling | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.7 | Sankey chart builds empty-state and data-state options for inflow and outflow links | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.8 | Sankey chart recomputes theme-aware colors when root theme attributes change | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.9 | Workspace provider restores tabs from storage and persists active workspace updates | ⏳ | <!-- epic-owned: fe-only -->
| AC16.21.10 | Workspace provider handles tab deduplication, removal, and cross-tab storage sync | ⏳ | <!-- epic-owned: fe-only -->

### AC16.22 — Confirmation Workflow (cross-cutting `pending_review` state machine)

> See authoritative definition: [docs/ssot/confirmation-workflow.md](../ssot/confirmation-workflow.md)

> **Partially migrated.** *(AC16.22.3 removed and AC16.22.4 removed — this
> group's Stage-2 rows migrated to the `reconciliation` package roadmap as
> `AC-reconciliation.stage2-batch.1-2`, migration closeout continuation,
> #1663 / #1711)*. The Stage-1 statement-validation rows below stay with
> their own owner.

| AC ID | Description | Test Function | File | Priority |
|-------|-------------|---------------|------|----------|
| AC16.22.1 | Stage 1 `pending_review → approved` transition requires balance delta ≤ 0.001 USD | `test_approve_statement_invalid_balance_fails` | `review/test_statement_validation.py` | P0 | <!-- epic-owned: pending-package -->
| AC16.22.2 | Stage 1 `pending_review → rejected` transition triggers re-parse | `test_stage1_reject_triggers_reparse` | `api/test_statements_router.py` | P0 | <!-- epic-owned: pending-package -->
| AC16.22.5 | Stage 1 tolerance is 0.001 USD (not 0.10 USD from Stage 2) | `test_validate_balance_chain_within_tolerance` | `review/test_statement_validation.py` | P0 | <!-- epic-owned: pending-package -->
| AC16.22.6 | All service methods mutating `pending_review` enforce `user_id` ownership | `test_get_statement_for_update_wrong_user_raises` | `review/test_statement_validation.py` | P1 | <!-- epic-owned: pending-package -->
| AC16.22.7 | Stage 1 approval tolerance and extraction/reconciliation scoring tolerance remain separate documented policies | `test_ac16_22_7_tolerance_policy_constants_are_intentional` | `review/test_tolerance_policy.py` | P0 | <!-- epic-owned: pending-package -->

### AC16.25 — Mobile Review UX Hardening

| AC ID | Description | Test Function | File | Priority |
|-------|-------------|---------------|------|----------|
| AC16.25.1 | Review, journal details, and mobile navigation surfaces do not create document-level horizontal scrolling at phone widths | `AC16.25.1 mobile review routes avoid document horizontal scrolling` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 | <!-- epic-owned: fe-only -->
| AC16.25.2 | AI suggestion review queue exposes accept, reject, correction, and edit-accept actions directly in a mobile card layout | `AC16.25.2 AI suggestions mobile cards expose feedback actions` | `apps/frontend/src/__tests__/uiGapAudit.confidenceAndAiQueue.test.tsx` | P0 | <!-- epic-owned: fe-only -->
| AC16.25.3 | Journal entry details expose line account, direction, amount, and currency as mobile line cards | `AC16.25.3 journal entry details mobile line cards expose all line fields` | `apps/frontend/src/__tests__/detailViewComponents.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.25.4 | Root layout keeps theme color in the viewport export and avoids duplicate iOS web-app capability metadata | `AC16.25.4 root layout metadata keeps viewport-only theme color` | `apps/frontend/src/__tests__/rootLayout.test.tsx` | P1 | <!-- epic-owned: fe-only -->

### AC16.26 — Mobile Review Workflow Completion

| AC ID | Description | Test Function | File | Priority |
|-------|-------------|---------------|------|----------|
| AC16.26.1 | Stage 1 statement review shows read-only transaction cards on phone widths (inline editing was removed in EPIC-011 Stage 3; correct a mis-parse via reject + re-parse), with approve and reject actions visible without horizontal dragging | `AC16.26.1 stage 1 mobile review exposes read-only transaction cards and completion actions` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 | <!-- epic-owned: fe-only -->
| AC16.26.2 | Stage 2 pending matches use selectable mobile cards with direct reject and approve selected actions visible without horizontal dragging | `AC16.26.2 stage 2 mobile queue exposes selectable match cards and batch actions` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 | <!-- epic-owned: fe-only -->
| AC16.26.3 | Stage 2 run review keeps the run approval gate and pending match workflow usable at phone widths without document-level horizontal scrolling | `AC16.26.3 stage 2 run review preserves mobile approval gate and match workflow` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 | <!-- epic-owned: fe-only -->

### AC16.27 — Responsive Review Layout Completion

| AC ID | Description | Test Function | File | Priority |
|-------|-------------|---------------|------|----------|
| AC16.27.1 | Stage 1 and Stage 2 mobile review lists render without JavaScript breakpoint gating that can create first-paint blank content | `AC16.27.1 mobile review lists are present without matchMedia gating` | `apps/frontend/src/__tests__/TransactionTable.test.tsx`, `apps/frontend/src/__tests__/stage2ReviewQueueCoverage99.test.tsx` | P0 | <!-- epic-owned: fe-only -->
| AC16.27.2 | Stage 1 desktop review keeps the transaction review surface readable at 1440px with the sidebar visible without local horizontal clipping | `AC16.27.2 desktop stage 1 review keeps transaction table readable at 1440px` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 | <!-- epic-owned: fe-only -->
| AC16.27.3 | Stage 2 desktop review keeps pending match rows readable at 1440px with the sidebar visible without local horizontal clipping | `AC16.27.3 desktop stage 2 review keeps pending matches readable at 1440px` | `apps/frontend/playwright/mobile-ux.spec.ts` | P0 | <!-- epic-owned: fe-only -->


---

## Historical Audit Notes

The April 2026 FE/UI audit snapshot was removed from this EPIC. Current review UI scope is represented by the AC groups below and executable frontend/E2E tests.

---

## 🆕 UI Gap Audit (April 2026) — Stage 1 Refactor, Inline Edit, Conflict Resolution & Mobile Nav

**Origin**: UI gap audit against [Project Vision](../target.md) decision 4 (two-stage review must be production-grade). Stage 1 page is monolithic, has no inline edit, no conflict resolution UI, no mobile navigation. These block real-user adoption of the review flow.

### Acceptance Criteria — Feature (group 23)

- [x] **AC16.23.1** Stage 1 page split into `<PdfPreviewPane />`, `<TransactionTable />`, `<ReviewActionBar />`, `<BalanceIndicator />` components, each independently mountable <!-- epic-owned: fe-only -->
- [x] **AC16.23.2** TransactionTable supports inline edit of `amount`, `description`, `date` with optimistic update + server confirm; failed write reverts row and shows error toast <!-- epic-owned: fe-only -->
- [x] **AC16.23.3** Conflict resolution dialog `<ConflictResolutionDialog />` opens when backend returns duplicate or transfer-pair candidates; user can pick canonical row or link the pair <!-- epic-owned: fe-only -->
- [x] **AC16.23.4** Stage 2 listing exposes severity filter, check-type filter, and score-range slider; filters persist in URL query string <!-- epic-owned: fe-only -->
- [x] **AC16.23.5** Mobile navigation renders below 768 px (originally the `<MobileNav />` drawer; replaced by the `<BottomTabBar />` bottom tab bar per EPIC-022 AC22.21); the desktop sidebar is hidden on mobile <!-- epic-owned: fe-only -->
- [x] **AC16.23.6** Frontend tests mount each new component (PdfPreviewPane, TransactionTable, ConflictResolutionDialog, BottomTabBar) and assert primary affordance renders <!-- epic-owned: fe-only -->

### Acceptance Criteria — Feature (group 24, run-level Stage 2)

- [x] **AC16.24.1** Stage 2 run-level page at `/review/run/[runId]` summarizes duplicate, transfer-pair, and anomaly checks for a batch <!-- epic-owned: fe-only -->
- [x] **AC16.24.2** Stage 2 run-level page shows unresolved transfer and Processing pending counts, then disables run approval while either remains unresolved <!-- epic-owned: fe-only -->
- [x] **AC16.24.3** Stage 2 run-level approval submits all pending matches through the batch approval API after checks are resolved <!-- epic-owned: fe-only -->
- **AC16.24.4** - Stage 2 batch approval routes accepted matches through the ledger-safe acceptance path, creating missing journal entries or reconciling referenced entries without duplicating entries on retry <!-- epic-owned: pending-package -->

### Acceptance Criteria — Feature (group 31, review contract hardening)

The June 2026 UI audit found several high-line-coverage review tests that
validated mocked UI-only state rather than backend-owned review contracts.
These ACs close those gaps without changing the underlying reconciliation data
model.

| ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC16.31.1 | Stage 1 conflict dialog loads duplicate and transfer-pair candidates from `GET /api/review/conflicts/{statement_id}` instead of fake review payload fields | `AC16.23.3 opens the conflict dialog when duplicate or transfer-pair candidates exist` / `opens conflict dialog when duplicate/transfer candidates present` | `apps/frontend/src/__tests__/statementReviewPage.test.tsx`, `apps/frontend/src/__tests__/statementReviewPage.coverage.test.tsx` | P0 | <!-- epic-owned: fe-only -->
| AC16.31.2 | Stage 1 approval is disabled unless both opening and closing balance validation match | `AC16.31.2 disables approval when opening balance validation fails` | `apps/frontend/src/__tests__/statementReviewPage.test.tsx` | P0 | <!-- epic-owned: fe-only -->
| AC16.31.3 | Stage 2 run review page states that it uses the shared Stage 2 queue endpoint when no run-scoped queue API exists | `AC16.24.1 and AC16.24.2 summarizes unresolved run checks and blocks approval` | `apps/frontend/src/__tests__/reviewRunPage.test.tsx` | P0 | <!-- epic-owned: fe-only -->
| AC16.31.4 | Unmatched transaction local flag/hide actions are labeled as local-only triage and batch create requires confirmation | `AC16.20.4 supports flag and ignore actions` / `creates all entries with batch action` | `apps/frontend/src/__tests__/unmatchedBoardComponent.test.tsx` | P0 | <!-- epic-owned: fe-only -->
| AC16.33.4 | Stage 1 statement review PDF previews use short-lived presigned URLs and sandboxed iframe embedding (backend presign contract; frontend embedding superseded by AC16.33.5) | `test_AC16_33_4_get_statement_for_review_uses_short_presign_ttl` | `apps/backend/tests/api/test_statements_router.py` | P0 | <!-- epic-owned: pending-package -->
| AC16.33.5 | Stage 1 PDF preview embeds the statement document via an authenticated same-origin `GET /api/statements/{id}/document` endpoint rendered as a sandboxed `blob:` object URL (CSP `frame-src 'self' blob:`), fixing the cross-origin/blocked iframe (#963) | `test_AC16_33_5_get_statement_document_streams_bytes_same_origin`, `test_AC16_33_5_get_statement_document_404_when_no_document`, `test_AC16_33_5_get_statement_document_storage_error_maps_to_502` / `AC16.33.5 embeds the document as a same-origin sandboxed blob URL`, `AC16.33.5 shows a fallback and skips the fetch when no document exists` | `apps/backend/tests/api/test_statements_router.py`, `apps/frontend/src/__tests__/reviewPages.test.tsx` | P0 | <!-- epic-owned: pending-package -->

### AC16.32 — Review Workflow Hardening

| AC ID | Description | Tests | Files | Priority |
|-------|-------------|-------|-------|----------|
| AC16.32.1 | Stage 1 approval and edit-approval are blocked while duplicate or transfer-pair conflict candidates remain unresolved | `test_AC16_32_1_stage1_approval_blocks_unresolved_conflicts`, `AC16.32.1 disables approval while conflict candidates are unresolved` | `apps/backend/tests/api/test_statements_router.py`, `apps/frontend/src/__tests__/statementReviewPage.test.tsx` | P0 | <!-- epic-owned: pending-package -->
| AC16.32.2 | Stage 1 balance validation UI reports opening and closing checks separately so reviewers see the same gate enforced by the backend | `AC16.32.2 shows opening and closing balance validation states separately` | `apps/frontend/src/__tests__/statementReviewPage.test.tsx` | P0 | <!-- epic-owned: fe-only -->
| AC16.32.3 | Stage 2 review check lists request the full unresolved blocker set needed to unblock batch approval instead of silently truncating at the backend default page size. Backend half (`test_AC16_32_3_stage2_queue_returns_all_pending_checks`) migrated to the `reconciliation` package roadmap as `AC-reconciliation.review-hardening.1` (migration closeout continuation, #1663 / #1711); the frontend half stays here. | `AC16.32.3 requests an expanded consistency-check limit for unblockable queues` | `apps/frontend/src/__tests__/reviewQueuePage.test.tsx` | P0 | <!-- epic-owned: fe-half -->

### AC16.34 — Stage-1 Conflict Resolution ([#962](https://github.com/wangzitian0/finance_report/issues/962))

A statement with an inherent (legitimate) duplicate or transfer-pair candidate
was permanently stuck in `parsed`: the conflict guard blocked approval and there
was no way to record the reviewer's decision. These ACs add a resolution path so
the reviewer can confirm the rows are genuinely distinct (or a real transfer
pair) and unblock approval.

| AC ID | Description | Tests | Files | Priority |
|-------|-------------|-------|-------|----------|
| AC16.34.1 | `POST /api/review/conflicts/{statement_id}/resolve` records the reviewer's resolution; the Stage-1 approval guard honors it so a previously-blocked statement with duplicate/transfer-pair candidates can be approved, and an unknown statement returns 404 | `test_AC16_34_1_resolve_unblocks_stage1_approval`, `test_AC16_34_1_resolve_conflicts_404_for_unknown_statement` | `apps/backend/tests/api/test_statements_router.py` | P0 | <!-- epic-owned: pending-package -->
| AC16.34.2 | A reject/reparse clears a prior conflict resolution so the fresh transaction set must be re-reviewed | `test_AC16_34_2_reject_clears_conflict_resolution` | `apps/backend/tests/api/test_statements_router.py` | P0 | <!-- epic-owned: pending-package -->
| AC16.34.3 | The ConflictResolutionDialog `Resolve` / `Link Pair` buttons call the resolve endpoint with the matching action and disable while a resolution is in flight (previously dead, no-op buttons) | `AC16.34.3 Resolve and Link Pair buttons call onResolve with the matching action`, `AC16.34.3 disables the action buttons while a resolution is in flight` | `apps/frontend/src/__tests__/ConflictResolutionDialog.test.tsx` | P0 | <!-- epic-owned: fe-only -->

### Acceptance Criteria — Feature (group 28, frontend UI system primitives)

Issue [#612](https://github.com/wangzitian0/finance_report/issues/612)
tracks the first frontend UI-system hardening slice. EPIC-016 owns this
because the review workflow depends on consistent dense application controls,
status states, and accessible icon actions across the authenticated frontend.
This group is intentionally conservative: it creates a React-level primitive
layer while preserving the existing visual language and leaving the deeper token
and visual-regression follow-ups to issues #613 and #614.

- [x] **AC16.28.1** Shared React UI primitives live under `apps/frontend/src/components/ui/` and cover button, icon button, badge, alert, empty state, loading state, and page header usage without requiring page-local class recipes <!-- epic-owned: fe-only -->
- [x] **AC16.28.2** Icon-only actions require an accessible label through the primitive API and representative account/statement delete-edit actions use those labels <!-- epic-owned: fe-only -->
- [x] **AC16.28.3** At least two representative frontend pages are migrated to the primitive layer without changing their existing workflows or API calls <!-- epic-owned: fe-only -->
- [x] **AC16.28.4** Primitive component tests cover variants, accessibility-facing props, and the migrated loading/error/empty states <!-- epic-owned: fe-only -->

### Acceptance Criteria — Feature (group 29, frontend design tokens)

Issue [#613](https://github.com/wangzitian0/finance_report/issues/613)
tracks the second frontend UI-system hardening slice. It expands the existing
CSS-variable theme into an explicit design-token contract so authenticated
review, account, report, and AI surfaces can share semantic colors, spacing,
radius, elevation, z-index, motion, and chart palette decisions without
hardcoded Tailwind palette drift.

- [x] **AC16.29.1** Tailwind theme extension maps frontend CSS-variable tokens for semantic color, radius, shadow/elevation, z-index, motion, typography, and chart palette usage <!-- epic-owned: fe-only -->
- [x] **AC16.29.2** Frontend CSS and SSOT document the design-token model, including token usage rules and intentional page-local visual choices such as login/dashboard gradients, shadows, and radius <!-- epic-owned: fe-only -->
- [x] **AC16.29.3** Confidence and status UI components use semantic token-backed primitives instead of hardcoded Tailwind palette utilities across all confidence/status variants <!-- epic-owned: fe-only -->
- [x] **AC16.29.4** Frontend tests cover the token configuration contract and at least one tokenized semantic component across multiple variants <!-- epic-owned: fe-only -->

### Acceptance Criteria — Feature (group 30, frontend verification hardening)

Issue [#614](https://github.com/wangzitian0/finance_report/issues/614)
tracks the final frontend UI-system hardening slice for EPIC-016. It closes
the actionable follow-ups from issues #612 and #613, strengthens semantic
navigation and accessibility coverage, and adds representative visual smoke
coverage so future review, account, statement, and shell changes cannot bypass
the shared UI-system contract.

- [x] **AC16.30.1** `IconButton` keeps its required `label` as the authoritative accessible name so callers cannot override or remove it through passthrough props <!-- epic-owned: fe-only -->
- [x] **AC16.30.2** The design-token follow-ups from issues #612 and #613 are resolved: border tokens are documented, core recipes use `border-border`, alert variants use semantic status token classes, and SSOT examples use accurate fence language <!-- epic-owned: fe-only -->
- [x] **AC16.30.3** `WorkspaceTabs` uses one coherent navigation/list semantic model with `aria-current` for the active route while preserving keyboard navigation between open workspace pages <!-- epic-owned: fe-only -->
- [x] **AC16.30.4** Component tests cover keyboard and ARIA behavior for dialog, sheet, toast, workspace navigation, and icon-only controls <!-- epic-owned: fe-only -->
- [x] **AC16.30.5** Playwright visual smoke covers desktop and mobile representative app-shell, accounts, statements, and review pages with stable visual anchors and nonblank screenshots <!-- epic-owned: fe-only -->
- [x] **AC16.30.6** Frontend SSOT documents the accessibility and visual-verification workflow required for future UI-system changes <!-- epic-owned: fe-only -->

### Acceptance Criteria — Infra (group 11, test infra extension)

- [x] **AC16.11.32** Vitest harness for Stage 1 split components — shared `renderReviewComponent()` helper in `apps/frontend/src/__tests__/helpers/` <!-- epic-owned: horizontal -->
- ~~Playwright smoke covers inline-edit happy path on Stage 1~~ — **retired**: inline transaction editing was removed in EPIC-011 Stage 3 (parsed transactions are immutable; the correction path is reject + re-parse), so the inline-edit acceptance criterion and its Playwright smoke are removed.

### Acceptance Criteria — Infra (group 13, conflict resolution backend contract)

- [x] **AC16.13.13** Backend exposes `GET /api/review/conflicts/{statement_id}` returning `{duplicates: [...], transfer_pairs: [...]}` consumed by ConflictResolutionDialog <!-- epic-owned: horizontal -->
- [x] **AC16.13.14** Contract test asserts response schema and 404 when statement_id not found <!-- epic-owned: horizontal -->

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

| AC ID | Test Case | Test Function | File | Priority |
|----|-----------|---------------|------|----------|
| AC16.36.1 | The dedicated `/review` route renders the Stage-2 review queue standalone | `AC16.36.1 renders the Stage-2 review queue as a standalone page` | `__tests__/reviewLandingPage.test.tsx` | P1 | <!-- epic-owned: fe-only -->
| AC16.36.2 | The dedicated route loads the global queue (no run filter) | `AC16.36.2 loads the global queue (no run filter) on the dedicated route` | `__tests__/reviewLandingPage.test.tsx` | P2 | <!-- epic-owned: fe-only -->

---

## Historical Implementation Notes

The merged implementation plan was removed from this EPIC. Current delivery proof is represented by AC definitions, tests, SSOT docs, and issue state.
