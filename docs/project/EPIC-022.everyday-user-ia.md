# EPIC-022: Everyday-User Information Architecture

> **Status**: In Progress — PR1 (IA skeleton) slice landing; unified inbox and
> report drill-down slices tracked separately.
> **Vision Anchor**: `decision-2-event-middle-layer`, `decision-4-two-stage-review`.
> Builds on EPIC-019: it introduced workflow events but kept internal accounting
> modules as first-class navigation; EPIC-022 restructures the shell so an
> everyday, non-accountant user only sees what they need.
> **Phase**: Product UX simplification
> **Priority**: P1 — an AI-driven finance product should feel friendly to a
> non-accountant: upload, read trusted reports, act on what needs attention, and
> ask the AI.
> **Dependencies**: EPIC-005, EPIC-016, EPIC-019, EPIC-020

---

## Objective

Reshape the application shell around **four things an everyday user actually
needs**, and fold everything else away:

```text
1. Upload        — upload operation + upload history
2. Reports       — financial report cockpit (high level, with drill-down)
3. Notifications — one place for "what needs my attention" (the bell)
4. Chat          — ask the AI
```

Primary navigation exposes exactly three peers — **Upload**, **Reports**,
**Chat** — plus an independent **notification bell**. Every internal accounting
module (Accounts, Journal, Reconciliation, Statements internals, Portfolio,
Processing, AI Settings, Review) collapses into a single **Advanced** group that
is hidden by default. The authenticated landing page is a lightweight **Home**:
financial key numbers, an action-required summary, and a quick-upload entry.

## Why This EPIC Exists

EPIC-019 made "upload + reports" the intended primary operations and added a
workflow-event layer, but the navigation still listed the internal pipeline:

```text
Dashboard / Events / Portfolio / Statements / Review / Accounts / Journal /
Reconciliation / Processing / AI Settings
```

From a first-time, non-accountant user's perspective this surface is hostile:
twelve entries, most of them accounting jargon (Journal, Reconciliation,
Unmatched), duplicate labels (two routes labeled "Portfolio"), a name/route
mismatch (`/dashboard` labeled "Upload Pipeline"), shared icons (Chat and AI
Settings), and two parallel "needs attention" surfaces (the workflow inbox and
the Stage 1/2 Review Queue).

EPIC-022 finishes EPIC-019's intent at the navigation and report layers.

## Non-Goals

- New product capabilities. This EPIC reorganizes and renames existing surfaces;
  it does not add accounting, parsing, or AI features.
- Removing the deep accounting pages. They remain reachable via **Advanced** and
  via deep links from notification cards.
- Backend or schema changes. The work is frontend information architecture plus
  reuse of existing read APIs (`/api/workflow/*`, `/api/evidence/lineage`).

## Scope Slices

| Slice | Issue | Owns |
|---|---|---|
| PR1 — IA skeleton | #834 | 3-peer nav, smart Home, route/name/icon alignment, Upload consolidation |
| PR2 — unified inbox | #835 | merge Stage 1/2 Review Queue into the notification center |
| PR3 — report cockpit | #836 (root) | 4-block Reports hub + `/api/evidence/lineage` drill-down |

Acceptance criteria for PR2/PR3 slices are added to this document when those
slices land, so every registered AC has a behavioral test in the same change.

## Acceptance Criteria

### AC22.1 — IA Skeleton, Smart Home, And Name/Route Alignment

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.1.1 | Primary navigation renders exactly three peers (Upload, Reports, Chat) plus a collapsible Advanced group; no accounting-jargon route (Journal, Reconciliation, Accounts, Statements) appears at the top level | `navigation.test.ts` | P1 |
| AC22.1.2 | The authenticated Home renders financial key numbers, an action-required summary, and a quick-upload entry | `dashboardPage.test.tsx` | P1 |
| AC22.1.3 | The sidebar brand links to `/` and the login flow redirects to `/` after authentication | `sidebarAndTabs.test.tsx`, `loginPage.test.tsx` | P1 |
| AC22.1.4 | `/dashboard` redirects to `/` and the label "Upload Pipeline" no longer appears in the navigation model | `nextConfigRedirects.test.ts`, `navigation.test.ts` | P1 |
| AC22.1.5 | `/events` redirects to `/notifications` and the notifications page renders the workflow event center | `nextConfigRedirects.test.ts`, `notificationsPage.test.tsx` | P1 |
| AC22.1.6 | `/assets` redirects to `/portfolio` and exactly one navigation entry is labeled "Portfolio" | `nextConfigRedirects.test.ts`, `navigation.test.ts` | P1 |
| AC22.1.7 | Chat and AI Settings navigation entries use distinct icons | `navigation.test.ts` | P1 |
| AC22.1.8 | `/upload` renders both the statement uploader and upload history, and `/statements/upload` redirects to `/upload` | `statementsPage.test.tsx`, `nextConfigRedirects.test.ts` | P1 |
| AC22.1.9 | Desktop and mobile smoke covers the 3-peer navigation, the Advanced toggle, and the notification bell without layout overflow | `epic022-ia-shell.spec.ts` | P1 |

### AC22.2 — Unified Notification Inbox

> PR2 slice. There were two parallel "needs attention" surfaces — the workflow
> event inbox and a standalone Stage 1 / Stage 2 Review Queue page. This slice
> makes the notification center (bell + `/notifications`) the single place for
> all action items, each card deep-linking to its follow-up.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.2.1 | The unified inbox surfaces Stage 1 source-review and Stage 2 reconciliation-review attention as cards (deep-linking to their detail surfaces), so no separate Review Queue page is needed | `unifiedInbox.test.tsx` | P1 |
| AC22.2.2 | A Stage 1 review-required workflow event deep-links to that statement's review page (`/statements/{id}/review`), and reconciliation-review attention deep-links to `/reconciliation/review-queue` | `test_workflow_events.py` | P1 |
| AC22.2.3 | The header bell badge reflects review/reconciliation attention via the workflow event counts and stays quiet when nothing needs attention | `workflowSurfaces.test.tsx` | P1 |
| AC22.2.4 | The standalone Review Queue page is removed, `/review` redirects to `/notifications`, and "Review" is no longer a sidebar navigation entry | `nextConfigRedirects.test.ts`, `navigation.test.ts` | P1 |
| AC22.2.5 | Review-required events are deduplicated by `(user, dedupe_key)` so re-syncing the same statement does not duplicate the inbox card | `test_workflow_events.py` | P1 |
| AC22.2.6 | Desktop and mobile smoke covers the unified inbox with review attention without layout overflow | `unified-inbox.spec.ts` | P1 |

### AC22.3 — Report Cockpit And Source Drill-Down

> PR3 slice. `/reports` leads with the four reports an everyday user reads, and
> any amount on the Balance Sheet / Income Statement drills down to the exact
> source transactions, reusing the evidence-lineage graph.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.3.1 | The `/reports` front section renders exactly four report blocks: Balance Sheet, Income Statement, Annualized Income, and Statistics Accuracy (reconciliation coverage / unmatched count) | `reportsCockpit.test.tsx` | P1 |
| AC22.3.2 | All other reports (Cash Flow, Personal Report Package, and any future reports) live behind a single "More" control, not the front section | `reportsCockpit.test.tsx` | P1 |
| AC22.3.3 | `GET /api/reports/account-lineage` returns the user-scoped posted/reconciled journal lines that contribute to an account's balance for the period, each carrying a `journal_line` evidence anchor, with Decimal-safe signed amounts | `test_account_lineage.py` | P1 |
| AC22.3.4 | A reusable lineage drill-down component lets a user click any amount on the Balance Sheet or Income Statement, list the contributing journal lines, and open the full evidence chain (journal line → bank statement transaction → atomic transaction → source document) | `lineagePanel.test.tsx`, `balanceSheetDrilldown.test.tsx` | P1 |
| AC22.3.5 | Accounts/amounts with no contributing lines or no graph-compatible anchor degrade gracefully with an explicit empty/"no source linked" state and no crash | `balanceSheetDrilldown.test.tsx` | P1 |
| AC22.3.6 | Desktop and mobile smoke covers the four-block cockpit and a Balance Sheet drill-down open/close without layout overflow | `reports-cockpit.spec.ts` | P1 |
