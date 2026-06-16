# EPIC-022: Everyday-User Information Architecture

> **Status**: Complete (2026-06-14) — the everyday-user IA redesign shipped
> across PR1–PR11: 3-peer nav + smart Home + route/name alignment (PR1), unified
> notification inbox (PR2), report cockpit + Balance Sheet / Income Statement /
> cash-flow drill-down (PR3 / PR7), hardening + flow guidance (PR4 / PR5), lean
> Home and review-flow fix (#860), confidence & attention surface (PR6), readable
> + printable report package (PR8 / PR8b), everyday↔Advanced boundary + naming
> unification (PR9), conservative provenance labeling (PR10), and UX-trust
> hardening (PR11). Every registered AC (AC22.1–AC22.11) is green with a CI-run
> test (traceability 100%).
>
> **Remaining depth is out of this EPIC's core IA scope** and continues as
> independent follow-ups: backend enablers — #887 (per-line cash-flow account
> anchors), #705 (snapshot/versioned-export engine), #888 (unified
> Imported/Manual/Derived provenance) plus the #894 as-of provenance bug; and
> FE depth-polish — lineage hop-badges, report-package cover + table-of-contents,
> a controlled `assets` source enum, and drill-down smokes — tracked in
> #866 / #867 / #868, which no longer gate this now-complete root.
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
lands, so every registered AC has a behavioral test in the same change. All
slices (PR1–PR11) have landed and their ACs (AC22.1–AC22.11) are registered
below.

### Slices PR6–PR11 (delivered)

The first five slices delivered the everyday-user *information architecture and
core flow*. The later slices closed the gap between that flow and the two
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

### AC22.7 — Close The Traceability Loop

> PR7 slice (#866). Balance Sheet and Income Statement already drill amounts down
> to source; this slice ties the Cash Flow statement together so the period's
> change in cash is explainable, and closes the traceability loop by giving each
> cash-flow line an account anchor (#887) so its amount drills down like the
> other statements. A desktop/mobile smoke and the readable evidence-chain path
> view follow separately.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.7.1 | Each cash-flow line carries its account anchor (`account_id`), and clicking a cash-flow amount opens the account-lineage drawer for that account's contributing journal lines | `test_reporting.py`, `cashFlowPage.test.tsx` | P1 |
| AC22.7.2 | The reusable lineage panel renders evidence nodes as an ordered source-to-report path with per-hop source, confidence, and version badges when those fields are available | `lineagePanel.test.tsx` | P1 |
| AC22.7.3 | The Cash Flow statement renders a reconciliation that ties beginning cash + net cash flow to ending cash, and explicitly flags when it does not reconcile | `cashFlowPage.test.tsx` | P1 |
| AC22.7.4 | Desktop and mobile Playwright smoke covers Cash Flow amount drill-down opening the account-lineage drawer without document horizontal overflow | `cash-flow-drilldown.spec.ts` | P1 |

### AC22.8 — Readable Report Package

> PR8 slice (#867). The report package — the product's terminal deliverable —
> was the least readable surface, exposing developer-facing snake_case
> identifiers (`framework_selection`, `report_readiness`, `source_trust_summary`,
> section ids) as on-screen labels. This slice replaces those with the existing
> human section titles. The fuller readable redesign (cover + table of contents)
> and the pinned-version export follow separately; the export engine pairs with
> #705 (backend), so it is out of scope for this frontend-only slice.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.8.1 | The report package titles its sections with human-readable labels (Reporting Framework, Report Readiness, Source Trust, Framework Policy, schedules, Traceability Appendix) rather than developer-facing snake_case identifiers | `personalReportPackagePage.test.tsx` | P1 |
| AC22.8.2 | The loaded report package starts with a readable cover sheet and table of contents that expose the package id, selected framework, report date, and linked human section titles | `personalReportPackagePage.test.tsx` | P1 |
| AC22.8.3 | The unselected-framework and framework-package loading states reserve the package layout with guidance or skeleton placeholders, never a blank text-only pre-selection or loading screen | `personalReportPackagePage.test.tsx` | P1 |
| AC22.8.4 | Desktop and mobile Playwright smoke covers report-package framework selection, cover, table of contents, readiness, and no document horizontal overflow | `report-readiness.spec.ts` | P1 |

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
| AC22.10.2 | Manual valuation capture uses a controlled source enum instead of free-text provenance, while existing historical source strings remain displayable in snapshot history | `assetsPage.test.tsx` | P1 |
| AC22.10.3 | Desktop and mobile Playwright smoke covers portfolio provenance badges only for imported holdings, with unproven holdings unlabeled and no document horizontal overflow | `portfolio-provenance.spec.ts` | P1 |

### AC22.11 — Everyday-User UX Hardening

> PR11 slice (#836). Post-merge hardening of the everyday-user surfaces, derived
> from a UX review of the shipped IA. Two trust seams: the statement-parsing
> screen showed a **fabricated** fixed-width progress bar (dishonest in a product
> whose whole pitch is trustworthiness), and attention items showed a confidence
> score with no explanation of *why* they were flagged (Axiom B asks the human to
> look only at the low-confidence tail — so the reason must be legible). The
> `/events`→`/notifications` dedup that #865 scoped is already handled by a
> `next.config` redirect (so #865 closed); the residual `/events` page is left in
> place because it still anchors EPIC-019's AC19.3.5. The cross-surface
> attention return path is handled as a narrow follow-up: attention-origin links
> carry their source into the destination, and the destination renders an
> attention-queue return link without changing direct-entry fallbacks.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.11.1 | The statement-parsing state shows an honest indeterminate indicator with a typical-duration expectation, and never renders a fabricated fixed-percentage progress bar | `statementsPage.test.tsx` | P1 |
| AC22.11.2 | Each attention-queue item surfaces a plain-language reason it was flagged — distinct per cause — alongside its confidence score | `attention.test.ts`, `attentionQueue.test.tsx` | P1 |
| AC22.11.3 | Attention-origin action links preserve `from=attention`, and the linked review/processing destinations render a return link to `/attention` while direct-entry notification/statement fallbacks remain unchanged | `attentionQueue.test.tsx`, `reviewBackLinks.test.tsx`, `statementReviewPage.test.tsx`, `stage2ReviewQueueCoverage99.test.tsx`, `uiGapAudit.processingVisibility.test.tsx`, `unmatchedBoardComponent.test.tsx`, `attention-surface.spec.ts` | P1 |

### AC22.12 — Accessibility Baseline Follow-Up

> #909 first follow-up slice. The shipped everyday-user IA is functional, but
> the app shell still needs cross-cutting accessibility affordances that make
> trust surfaces usable without pointer-only navigation or motion-heavy UI:
> global reduced-motion handling, consistent keyboard focus visibility, a
> skip-to-content link, and restored contrast on attention reasons.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.12.1 | Global styles honor `prefers-reduced-motion: reduce` by disabling non-essential animation/transition timing and smooth scrolling across the app shell | `designTokens.test.tsx` | P1 |
| AC22.12.2 | The authenticated shell exposes a skip-to-content link that targets the main landmark so keyboard users can bypass navigation chrome | `shellAndAuth.test.tsx` | P1 |
| AC22.12.3 | Global focus-visible styles cover links, form controls, and shared `.btn-*` controls with token-backed focus rings | `designTokens.test.tsx` | P1 |
| AC22.12.4 | Attention-queue reason text uses the normal muted content token, not a lower-opacity muted variant, so low-confidence explanations keep readable contrast | `attentionQueue.test.tsx` | P1 |
| AC22.12.5 | Shared toast and flow-step status affordances use Lucide icons or text instead of unicode glyph icons, and warning toast messages do not embed emoji-like status glyphs | `toastProviderComponent.test.tsx`, `flowStepBanner.test.tsx`, `assetsPage.test.tsx` | P1 |
| AC22.12.6 | Data-dense report and asset-table loading states reserve layout with token-backed skeleton placeholders instead of spinner-only or text-only states | `uiPrimitives.test.tsx`, `balanceSheetPage.test.tsx`, `incomeStatementPage.test.tsx`, `cashFlowPage.test.tsx`, `assetsPage.test.tsx` | P1 |

### AC22.13 — Unified Provenance Taxonomy Follow-Up

> #888 follow-up slice. AC22.10 shipped the conservative safe subset: a holding
> could be labeled Imported only when a concrete source document proved that
> claim. The remaining depth is to expose a normalized
> Imported / Manual / Derived enum on live read models and render one shared
> badge, while still avoiding guessed provenance for ambiguous historical
> position paths. This slice also carries forward two #928 accessibility review
> comments that belong to the same trust-surface baseline.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.13.1 | Portfolio holdings, explicit as-of holdings, manual valuation snapshots, and report amount lines expose a normalized provenance enum (`imported`, `manual`, `derived`) when the source basis is known, while ambiguous holdings remain unlabeled instead of guessed | `test_portfolio_service.py`, `test_reporting.py`, `test_manual_valuation_snapshots.py` | P1 |
| AC22.13.2 | Portfolio and report surfaces render a shared Imported / Manual / Derived provenance badge; Manual is visually distinct from Imported and unlabeled values remain silent | `provenanceBadge.test.tsx`, `holdingsTable.test.tsx`, `balanceSheetPage.test.tsx`, `incomeStatementPage.test.tsx` | P1 |
| AC22.13.3 | Carryover accessibility review fixes keep the skip-link target covered by global focus-visible styling and keep report package table-of-contents section status in the accessible link name | `designTokens.test.tsx`, `personalReportPackagePage.test.tsx` | P1 |

### AC22.14 — Grounded Chat Answers

> #912 follow-up slice. EPIC-021 gave the assistant deterministic Advisor Brief
> facts, but streamed chat answers still reached the UI as plain text. This
> slice keeps the model read-only while attaching application-owned grounding
> metadata to each personal-data answer: citations with confidence tiers and
> safe next-action chips for pending review work.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.14.1 | `POST /api/chat` exposes structured grounding metadata for personal-data answers, including source citations with confidence tiers, without sending or returning raw account numbers or transaction-level PII | `test_chat_router.py`, `test_ai_advisor_service.py` | P1 |
| AC22.14.2 | `ChatPanel` renders assistant-answer citations as safe internal links and shows pending-action chips without parsing LLM prose | `chatPanelComponent.test.tsx` | P1 |
| AC22.14.3 | A grounded chat answer that has pending reconciliation review context exposes a `Review N` action deep-link to the review queue while preserving the assistant's read-only/no-write boundary | `test_ai_advisor_service.py`, `chatPanelComponent.test.tsx` | P1 |

### AC22.15 — Settings Editor And Session Bootstrap (Surface Gaps)

> #1010 follow-up slice (part of #1000 Tier 3). The `PATCH /users/me/settings`
> capability existed on the backend but the AI Settings page only auto-toggled
> per-checkbox via inline `apiFetch`, with no typed client function, no explicit
> save action, and no submit/success/error affordance. The `/auth/me` endpoint
> was registered and backend-tested but never consumed by the frontend. This
> slice gives the user a real settings editor backed by a typed `lib/api.ts`
> client function, and consumes `/auth/me` for session bootstrap so it is no
> longer frontend-dead. The broader `users` CRUD endpoints stay deliberately
> deferred (no user-admin panel) — recorded in the backend README.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.15.1 | A typed `patchUserSettings` client function in `lib/api.ts` issues `PATCH /api/users/me/settings` through the shared `apiFetch` client (no raw `fetch`) and returns the effective `UserAiSettings` response | `apiFunctions.test.ts` | P1 |
| AC22.15.2 | The AI Settings page renders an editable form with explicit Save and Reset controls that submits the edited flags via `patchUserSettings`, surfacing loading, submitting, success, and error states using shared UI primitives | `aiSettingsPage.test.tsx` | P1 |
| AC22.15.3 | A typed `fetchCurrentUser` client function consumes `GET /api/auth/me`, and the authenticated app shell calls it on mount to bootstrap/refresh the local session identity, clearing local session state when the endpoint reports the session is invalid | `apiFunctions.test.ts`, `appShellSessionBootstrap.test.tsx` | P1 |

### AC22.16 — Home Stops Leaking Internal Pipeline; Composable Dashboard Hooks

> #1116 + #1119 follow-up slice. The shipped Home still leaked internal
> accounting/pipeline plumbing as first-class destinations, competing with the
> Trust Meter → `/attention` signal (Axiom B asks for one confidence-ranked
> queue): the getting-started guide opened the accounting-jargon `/accounts`
> route, and the analytics "Risk radar" card plus the unmatched-alerts CTA linked
> straight into Advanced reconciliation internals. This slice routes every Home
> "needs attention" affordance through the single `/attention` queue and retargets
> onboarding to everyday surfaces. It also pays down the paired FE structural
> debt: the ~294-line `useDashboardData` god-hook is decomposed into composable,
> independently-usable hooks with the aggregate contract preserved (behavior-
> preserving, no backend or schema change).

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.16.1 | The Home getting-started steps link only to everyday surfaces — the first step targets `/upload` and no step links to the accounting-jargon `/accounts` route | `dashboardPage.test.tsx` | P1 |
| AC22.16.2 | The Home presents a single confidence-ranked attention entry point: the analytics reconciliation ("Risk radar") card and the unmatched-alerts call-to-action link to the unified `/attention` queue instead of parallel Advanced reconciliation internals (`/reconciliation`, `/reconciliation/unmatched`, `/review`) | `dashboardPage.test.tsx` | P1 |
| AC22.16.3 | `useDashboardData` is composed from independently-usable hooks (`useDashboardSnapshot` for the financial/reconciliation aggregate and `useAssetTrend` for the per-account trend), each callable on its own through the shared `apiFetch` transport, while the aggregate hook preserves its existing public result contract | `useDashboardData.test.ts`, `useAssetTrend.test.ts` | P1 |

### AC22.17 — God-Component Decomposition (FE Structural Hygiene)

> #1117 follow-up slice. The FE audit flagged several oversized pages/components
> that mix data orchestration, layout, and many sub-sections in one function,
> making them hard to test and reason about. This slice decomposes the worst
> offenders into co-located, independently-testable sub-components while
> preserving the rendered surface and behavior exactly — no backend, schema, or
> UX change. (The report package page, also flagged at ~1298 lines, was
> decomposed separately by #1132, so it is out of scope here.)

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.17.2 | The Stage 2 review queue is composed from extracted sub-components (the match row/card and the queue controls) with unchanged review behavior | `reviewQueuePage.test.tsx`, `stage2ReviewQueueParts.test.tsx` | P1 |
| AC22.17.3 | The statement detail page is composed from extracted sub-components (header/summary and the transactions/section blocks) with unchanged behavior | `statementDetailPage.test.tsx`, `statementDetailParts.test.tsx` | P1 |

### AC22.18 — Nav Alias Cleanup And Product-Analytics Funnel Instrumentation

> #1118 + #1109 follow-up slice. Two leftover cleanups from the IA restructure
> plus the product-analytics gap. (a) `/events` is permanently redirected to
> `/notifications` but was still aliased in `ROUTE_CONFIG`, so the legacy label
> could leak through breadcrumbs/persisted tabs — removed so `/notifications` is
> the one canonical path/label. (b) The OpenPanel SDK was wired for page-views
> only (zero `track()` calls); this slice adds a typed, non-blocking, PII-safe
> `track()` wrapper and instruments the core product funnel. Per-environment
> `OPENPANEL_CLIENT_ID` provisioning (#1109 AC1) is an infra2 task, out of scope
> for this frontend repo.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC22.18.1 | The legacy `/events` alias is removed from `ROUTE_CONFIG` so `/notifications` is the single canonical path/label; the `/events`→`/notifications` redirect is unchanged | `navigation.test.ts`, `nextConfigRedirects.test.ts` | P1 |
| AC22.18.2 | A typed `track(event, props)` analytics wrapper dispatches through the OpenPanel command queue, is strictly non-blocking (never throws, no-op when unconfigured), exposes a taxonomy of ≥6 named product events, and strips PII (emails, monetary amounts, account numbers) from event properties before sending | `analyticsTrack.test.ts` | P1 |
| AC22.18.3 | The core product funnel is instrumented through the wrapper — signup, statement upload started/succeeded/failed, Stage-1 review approved, and report generated — with tests asserting `track()` is invoked on each action | `loginPage.test.tsx`, `StatementUploader.test.tsx`, `statementReviewPage.test.tsx`, `personalReportPackagePage.test.tsx` | P1 |
