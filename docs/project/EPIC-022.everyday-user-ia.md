# EPIC-022: Everyday-User Information Architecture

> **Status**: In Progress — PR1–PR5 landed (IA skeleton, unified inbox, report
> cockpit + Balance Sheet / Income Statement drill-down, hardening, flow
> guidance), plus the lean Home and review-flow fix (#860). Remaining everyday-user slices
> PR6–PR10 (confidence surface, cash-flow drill-down, readable report package,
> boundary/naming cleanup, manual provenance) are tracked as sub-issues of the
> root (#836).
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
| PR4 — hardening | #853 | Stage 2 inbox event, orphan-route fixes, lean Home, E2E journeys |
| PR5 — flow guidance & plain language | — | core-flow step banner, in-place unblock on review, deep-page back-links, jargon hints, single primary next-action |
| PR6 — confidence & attention surface | #864 | confidence-ranked `/attention` queue + Home trust meter (Axiom B / north-star) |
| PR7 — close traceability loop | #866 | cash-flow drill-down + linear evidence-chain view + beginning→ending cash reconciliation |
| PR8 — readable report package + export | #867 | human-readable package view + pinned-version export MVP (terminal goal); pairs with #705 |
| PR9 — boundary & naming cleanup | #865 | stop the Reports cockpit leaking into Advanced; unify the reconciliation-coverage term; fix mislabels |
| PR10 — manual provenance labeling | #868 | Imported/Manual/Derived provenance badges + controlled asset source; pairs with #706 |

Acceptance criteria for a slice are added to this document when that slice
lands, so every registered AC has a behavioral test in the same change. PR1–PR5
ACs are registered below; the planned PR6–PR10 ACs live in their sub-issues
(#864–#868) until each lands.

### Planned slices (PR6–PR10)

The first five slices delivered the everyday-user *information architecture and
core flow*. The remaining slices close the gap between that flow and the two
vision pillars it must serve — **Axiom B** (automation by default, attention only
on the low-confidence tail) and **source→ledger→report traceability** — plus the
**terminal goal** (a readable, exportable report package).

- **PR6 — confidence & attention surface** (#864): make confidence a first-class,
  navigable concept — one confidence-ranked attention queue plus a Home trust
  meter — instead of the same signal scattered across statement score, txn
  high/medium/low, match score, and balance validation. Registers AC22.6.x on
  landing.
- **PR7 — close the traceability loop** (#866): wire cash-flow amounts to the
  lineage drawer (only Balance Sheet / Income Statement have it today) and turn
  the evidence chain into a readable ordered path. Registers AC22.7.x on landing.
- **PR8 — readable report package + export** (#867): turn `reports/package` from a
  developer-facing dump into a readable, exportable package — the product's
  terminal deliverable. Pairs with #705. Registers AC22.8.x on landing.
- **PR9 — boundary & naming cleanup** (#865): stop the Reports cockpit from
  linking everyday users back into Advanced, and unify the reconciliation-coverage
  term and other mislabels. Registers AC22.9.x on landing.
- **PR10 — manual provenance labeling** (#868): give every value an honest
  Imported/Manual/Derived badge so manual data never masquerades as imported
  proof. Pairs with #706. Registers AC22.10.x on landing.

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
| AC22.3.1 | The `/reports` front section renders exactly four report blocks: Balance Sheet, Income Statement, Annualized Income, and Reconciliation coverage (reconciliation match rate / unmatched count) | `reportsCockpit.test.tsx` | P1 |
| AC22.3.2 | All other reports (Cash Flow, Personal Report Package, and any future reports) live behind a single "More" control, not the front section | `reportsCockpit.test.tsx` | P1 |
| AC22.3.3 | `GET /api/reports/account-lineage` returns the user-scoped posted/reconciled journal lines that contribute to an account's balance for the period, each carrying a `journal_line` evidence anchor, with Decimal-safe signed amounts | `test_account_lineage.py` | P1 |
| AC22.3.4 | A reusable lineage drill-down component lets a user click any amount on the Balance Sheet or Income Statement, list the contributing journal lines, and open the full evidence chain (journal line → bank statement transaction → atomic transaction → source document) | `lineagePanel.test.tsx`, `balanceSheetDrilldown.test.tsx` | P1 |
| AC22.3.5 | Accounts/amounts with no contributing lines or no graph-compatible anchor degrade gracefully with an explicit empty/"no source linked" state and no crash | `balanceSheetDrilldown.test.tsx` | P1 |
| AC22.3.6 | Desktop and mobile smoke covers the four-block cockpit and a Balance Sheet drill-down open/close without layout overflow | `reports-cockpit.spec.ts` | P1 |

### AC22.4 — Hardening: Stage 2 Inbox, Orphan Routes, Lean Home, E2E

> PR4 slice. Closes the holistic-review findings and adds end-to-end journeys.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.4.1 | A user with pending Stage 2 reconciliation matches gets a reconciliation-review attention event in the workflow inbox that deep-links to `/reconciliation/review-queue` (proven from match state through to event) | `test_workflow_events.py` | P1 |
| AC22.4.3 | `/review/ai-suggestions` is reachable from AI Settings, so the AI-suggestion review surface is not orphaned | `aiSettingsPage.test.tsx` | P1 |
| AC22.4.4 | The Home (`/`) defaults to a lean view (action-required summary, financial key numbers, quick upload) with heavy analytics/charts behind an opt-in toggle | `dashboardPage.test.tsx` | P1 |
| AC22.4.5 | E2E: a user with Stage 1 and Stage 2 attention sees both in the notification center and can open each detail surface | `epic022-attention-journey.spec.ts` | P1 |
| AC22.4.6 | E2E: an amount on the Balance Sheet drills down to its contributing journal lines and on to the source document | `epic022-drilldown-journey.spec.ts` | P1 |

### AC22.5 — Hardening: Everyday-User Flow Guidance And Plain Language

> PR5 slice. An everyday-user walkthrough of the core flow (upload → parse →
> review → approve → reports) found three execution gaps that survive the new IA:
> no sense of "where am I / what's next", dead-ends at blocked states with no
> in-place escape, and accountant/system jargon shown without explanation. This
> slice closes them with copy, a step indicator, in-place unblock actions, and
> plain-language hints — no backend, routing, or page-structure changes.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.5.1 | The upload, statement-detail, and statement-review pages render a shared step indicator showing the Upload → Review & approve → Reports path with the current step highlighted | `flowStepBanner.test.tsx` | P1 |
| AC22.5.2 | When the statement-review Approve action is blocked (balance validation failed or unresolved duplicate/transfer-pair conflicts), the page shows a visible plain-language reason and an in-place action (open the conflict-resolution dialog, or re-parse the statement) without leaving the page | `reviewActionBar.test.tsx` | P1 |
| AC22.5.3 | Deep review and reconciliation surfaces (`/review/ai-suggestions`, `/reconciliation/review-queue`, `/reconciliation`, `/reconciliation/unmatched`) render a back-link to the notification center (`/notifications`) so a user who deep-links in is never stranded | `reviewBackLinks.test.tsx` | P1 |
| AC22.5.4 | User-facing review-surface headings use plain language and do not expose internal "Stage 2" or raw score-band wording in their titles | `reviewBackLinks.test.tsx` | P1 |
| AC22.5.5 | Core jargon terms (balance "drift"/"balanced", "needs review", transfer pair, anomaly, duplicate, consistency check, match score) expose a plain-language explanation through an accessible `InfoHint` affordance | `infoHint.test.tsx` | P1 |
| AC22.5.6 | The Home surfaces a single primary next-action with overlapping reconciliation links de-duplicated, and the Chat page heading reads "AI Advisor" | `dashboardPage.test.tsx`, `ChatPageClient.test.tsx` | P1 |

### AC22.6 — Confidence & Attention As A First-Class Surface

> PR6 slice (#864). "What needs my attention" was scattered across statement
> confidence scores, balance validation, reconciliation review, unmatched
> transactions, and stalled processing transfers — each with its own page and
> vocabulary. This slice folds those existing read-API signals into one
> confidence-ranked queue and a Home trust meter, making the low-confidence tail
> (Axiom B) navigable. AC22.6.1–.2 shipped the queue and meter; AC22.6.3–.4 add
> the bell connection and smoke coverage.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.6.1 | The `/attention` page folds the open attention sources (Stage 1 statement review, reconciliation review, unmatched transactions, stalled processing transfers) into a single list sorted by ascending confidence, each row deep-linking to its action surface, with an all-clear empty state when nothing needs attention | `attention.test.ts`, `attentionQueue.test.tsx` | P1 |
| AC22.6.2 | The Home renders a trust meter (trusted / needs-confirmation / low-confidence counts) derived from the same attention model and linking to `/attention`, and stays silent when nothing needs attention | `attention.test.ts`, `dashboardTrustMeter.test.tsx` | P1 |
| AC22.6.3 | The header notification center links to the full `/attention` queue, and the bell stays quiet (no badge) when nothing needs attention | `workflowSurfaces.test.tsx` | P1 |
| AC22.6.4 | Desktop and mobile smoke covers the `/attention` queue and the Home trust meter without layout overflow | `attention-surface.spec.ts` | P1 |

### AC22.9 — Everyday/Advanced Boundary And Naming Unification

> PR9 slice (#865). The IA folds accounting modules into Advanced, but the
> Reports cockpit still linked an everyday user into the Advanced reconciliation
> page, and the same reconciliation match-rate was shown under three different
> names ("Data health" on Home, "Statistics Accuracy" on Reports). This slice
> keeps the cockpit in the reports context and unifies the term. (The `/assets`
> and `/events` mislabels noted in review are already handled by permanent
> redirects, so they are out of scope here.)

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.9.1 | The Reports cockpit's reconciliation-coverage block stays in the reports context and does not link into the Advanced `/reconciliation` surface | `reportsCockpit.test.tsx` | P1 |
| AC22.9.2 | The reconciliation match-rate is shown under a single term ("Reconciliation coverage") on both Home and Reports, backed by one shared `InfoHint` glossary entry | `dashboardPage.test.tsx`, `reportsCockpit.test.tsx`, `infoHint.test.tsx` | P1 |
| AC22.9.3 | The "Annualized Income" cockpit card's destination matches its label (it opens the report package and the caption says so), with no silent label/destination mismatch | `reportsCockpit.test.tsx` | P1 |

### AC22.10 — Provenance Labeling (Conservative Subset)

> PR10 slice (#868). The vision requires manual data to never masquerade as
> imported proof. A full Imported/Manual/Derived taxonomy needs a persisted
> provenance field across the holding creation paths (tracked in #888, where the
> ambiguity of empty `source_documents` is documented). This slice ships the
> safe subset: label a holding **Imported only when it has concrete document
> evidence**, and never infer Manual — so neither direction can be mislabeled.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.10.1 | A holding whose latest snapshot is backed by a source document is labeled "Imported"; holdings without document evidence carry no provenance label (manual data is never shown as imported, and import is never claimed without proof) | `test_portfolio_service.py`, `holdingsTable.test.tsx` | P1 |
