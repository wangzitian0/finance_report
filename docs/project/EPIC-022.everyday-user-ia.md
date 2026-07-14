# EPIC-022: Everyday-User Information Architecture

<!-- epic-file: design-doc -->
<!-- 0 AC rows by design (#1821 Wave B): the delivered everyday-user IA
     design record; all ACs migrated to their owning package contract.py
     roadmaps (mostly meta/fe-ia-nav, reporting/fe-ia-reports,
     reconciliation/fe-ia-reconciliation, platform/fe-ia-inbox). -->

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

> **Update (PR12, AC22.21)**: the 3-peer + Advanced-drawer model above was the
> PR1–PR11 shape. It still left the accounting machinery as nine standing nav
> verbs, so the app stayed information-overloaded. PR12 supersedes it with a
> mobile/PWA-first **bottom tab bar** (Home · Chat · ⊕ Add · Audit · More): the
> machinery folds into an on-demand `/audit` hub, Settings merge into one tabbed
> page, Portfolio moves behind `/more`, and Upload becomes the center Add sheet.
> See AC22.21 and [the design doc](./EPIC-022.pwa-bottom-tab-ia.design.md).

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

(AC22.1.1 removed and AC22.1.3 removed and AC22.1.4 removed and AC22.1.5 removed and AC22.1.6 removed and AC22.1.7 removed and AC22.1.8 removed and AC22.1.9 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.1` through `.8`, #1821 Wave B)
(AC22.1.2 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.1`, #1821 Wave B)

### AC22.2 — Unified Notification Inbox

> PR2 slice. There were two parallel "needs attention" surfaces — the workflow
> event inbox and a standalone Stage 1 / Stage 2 Review Queue page. This slice
> makes the notification center (bell + `/notifications`) the single place for
> all action items, each card deep-linking to its follow-up.

> **Partially migrated.** *(AC22.2.2 removed and AC22.2.5 removed — this
> group's backend rows migrated to the `platform` package roadmap as
> `AC-platform.36.1-2`, migration closeout continuation, #1663 / #1712)*.
> The frontend rows below remain defined in this EPIC — no owning package has
> been decided for them yet.

(AC22.2.1 removed and AC22.2.3 removed and AC22.2.6 removed, canonical: migrated to the `platform` package roadmap as `AC-platform.fe-ia-inbox.1` through `.3`, #1821 Wave B)
(AC22.2.4 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.9`, #1821 Wave B)

### AC22.3 — Report Cockpit And Source Drill-Down

> PR3 slice. `/reports` leads with the four reports an everyday user reads, and
> any amount on the Balance Sheet / Income Statement drills down to the exact
> source transactions, reusing the evidence-lineage graph.

> *(AC22.3.3 removed — the account-lineage API row migrated to the
> `reporting` package roadmap as `AC-reporting.lineage.1`, migration
> closeout continuation, #1663 / #1716.)*

(AC22.3.1 removed and AC22.3.2 removed and AC22.3.4 removed and AC22.3.5 removed and AC22.3.6 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.2` through `.6`, #1821 Wave B)

### AC22.4 — Hardening: Stage 2 Inbox, Orphan Routes, Lean Home, E2E

> PR4 slice. Closes the holistic-review findings and adds end-to-end journeys.

> This row removed — migrated to the `platform` package roadmap as
> `AC-platform.36.3` (migration closeout continuation, #1663 / #1712).

(AC22.4.3 removed and AC22.4.5 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-ia-reconciliation.1` through `.2`, #1821 Wave B)
(AC22.4.4 removed and AC22.4.6 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.7` through `.8`, #1821 Wave B)

### AC22.5 — Hardening: Everyday-User Flow Guidance And Plain Language

> PR5 slice. An everyday-user walkthrough of the core flow (upload → parse →
> review → approve → reports) found three execution gaps that survive the new IA:
> no sense of "where am I / what's next", dead-ends at blocked states with no
> in-place escape, and accountant/system jargon shown without explanation. This
> slice closes them with copy, a step indicator, in-place unblock actions, and
> plain-language hints — no backend, routing, or page-structure changes.

(AC22.5.1 removed and AC22.5.5 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.10` through `.11`, #1821 Wave B)
(AC22.5.2 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.fe-ia-extraction.1`, #1821 Wave B)
(AC22.5.3 removed and AC22.5.4 removed, canonical: migrated to the `platform` package roadmap as `AC-platform.fe-ia-inbox.4` through `.5`, #1821 Wave B)
(AC22.5.6 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.9`, #1821 Wave B)

### AC22.6 — Confidence & Attention As A First-Class Surface

> PR6 slice (#864). "What needs my attention" was scattered across statement
> confidence scores, balance validation, reconciliation review, unmatched
> transactions, and stalled processing transfers — each with its own page and
> vocabulary. This slice folds those existing read-API signals into one
> confidence-ranked queue and a Home trust meter, making the low-confidence tail
> (Axiom B) navigable. The first two rows of this group shipped the queue and
> meter; the last two add the bell connection and smoke coverage.

(AC22.6.1 removed and AC22.6.2 removed and AC22.6.4 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-ia-reconciliation.3` through `.5`, #1821 Wave B)
(AC22.6.3 removed, canonical: migrated to the `platform` package roadmap as `AC-platform.fe-ia-inbox.6`, #1821 Wave B)

### AC22.7 — Close The Traceability Loop

> PR7 slice (#866). Balance Sheet and Income Statement already drill amounts down
> to source; this slice ties the Cash Flow statement together so the period's
> change in cash is explainable, and closes the traceability loop by giving each
> cash-flow line an account anchor (#887) so its amount drills down like the
> other statements. A desktop/mobile smoke and the readable evidence-chain path
> view follow separately.

(AC22.7.1 removed and AC22.7.2 removed and AC22.7.3 removed and AC22.7.4 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.10` through `.13`, #1821 Wave B)

### AC22.8 — Readable Report Package

> PR8 slice (#867). The report package — the product's terminal deliverable —
> was the least readable surface, exposing developer-facing snake_case
> identifiers (`framework_selection`, `report_readiness`, `source_trust_summary`,
> section ids) as on-screen labels. This slice replaces those with the existing
> human section titles. The fuller readable redesign (cover + table of contents)
> and the pinned-version export follow separately; the export engine pairs with
> #705 (backend), so it is out of scope for this frontend-only slice.

(AC22.8.1 removed and AC22.8.2 removed and AC22.8.3 removed and AC22.8.4 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.14` through `.17`, #1821 Wave B)

### AC22.9 — Everyday/Advanced Boundary And Naming Unification

> PR9 slice (#865). The IA folds accounting modules into Advanced, but the
> Reports cockpit still linked an everyday user into the Advanced reconciliation
> page, and the same reconciliation match-rate was shown under three different
> names ("Data health" on Home, "Statistics Accuracy" on Reports). This slice
> keeps the cockpit in the reports context and unifies the term. (The `/assets`
> and `/events` mislabels noted in review are already handled by permanent
> redirects, so they are out of scope here.)

(AC22.9.1 removed and AC22.9.3 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.18` through `.19`, #1821 Wave B)
(AC22.9.2 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.12`, #1821 Wave B)

### AC22.10 — Provenance Labeling (Conservative Subset)

> PR10 slice (#868). The vision requires manual data to never masquerade as
> imported proof. A full Imported/Manual/Derived taxonomy needs a persisted
> provenance field across the holding creation paths (tracked in #888, where the
> ambiguity of empty `source_documents` is documented). This slice ships the
> safe subset: label a holding **Imported only when it has concrete document
> evidence**, and never infer Manual — so neither direction can be mislabeled.

(AC22.10.1 removed and AC22.10.2 removed and AC22.10.3 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.fe-ia-portfolio.1` through `.3`, #1821 Wave B)

### AC22.11 — Everyday-User UX Hardening

> PR11 slice (#836). Post-merge hardening of the everyday-user surfaces, derived
> from a UX review of the shipped IA. Two trust seams: the statement-parsing
> screen showed a **fabricated** fixed-width progress bar (dishonest in a product
> whose whole pitch is trustworthiness), and attention items showed a confidence
> score with no explanation of *why* they were flagged (Axiom B asks the human to
> look only at the low-confidence tail — so the reason must be legible). The
> `/events`→`/notifications` dedup that #865 scoped is already handled by a
> `next.config` redirect (so #865 closed); the residual `/events` page is left in
> place because it still anchors EPIC-019's event-inbox-grouping AC (now
> `AC-platform.fe-workflow.3`). The cross-surface
> attention return path is handled as a narrow follow-up: attention-origin links
> carry their source into the destination, and the destination renders an
> attention-queue return link without changing direct-entry fallbacks.

(AC22.11.1 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.fe-ia-extraction.2`, #1821 Wave B)
(AC22.11.2 removed and AC22.11.3 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-ia-reconciliation.6` through `.7`, #1821 Wave B)

### AC22.12 — Accessibility Baseline Follow-Up

> #909 first follow-up slice. The shipped everyday-user IA is functional, but
> the app shell still needs cross-cutting accessibility affordances that make
> trust surfaces usable without pointer-only navigation or motion-heavy UI:
> global reduced-motion handling, consistent keyboard focus visibility, a
> skip-to-content link, and restored contrast on attention reasons.

(AC22.12.1 removed and AC22.12.2 removed and AC22.12.3 removed and AC22.12.5 removed and AC22.12.6 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.13` through `.17`, #1821 Wave B)
(AC22.12.4 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-ia-reconciliation.8`, #1821 Wave B)

### AC22.13 — Unified Provenance Taxonomy Follow-Up

> #888 follow-up slice. AC22.10 shipped the conservative safe subset: a holding
> could be labeled Imported only when a concrete source document proved that
> claim. The remaining depth is to expose a normalized
> Imported / Manual / Derived enum on live read models and render one shared
> badge, while still avoiding guessed provenance for ambiguous historical
> position paths. This slice also carries forward two #928 accessibility review
> comments that belong to the same trust-surface baseline.

> *(AC22.13.1 removed — fully distributed; it was a three-package row: its `test_manual_valuation_snapshots.py` share migrated to `AC-pricing.provenance.1` (#1663 / #1710), its `test_portfolio_service.py` share (holdings + explicit as-of holdings) to `AC-portfolio.provenance.2` (#1663 / #1717), and its `test_reporting.py` share (report amount lines) to `AC-reporting.provenance.1` (#1663 / #1716))*

(AC22.13.2 removed, canonical: migrated to the `portfolio` package roadmap as `AC-portfolio.fe-ia-portfolio.4`, #1821 Wave B)
(AC22.13.3 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.18`, #1821 Wave B)

### AC22.14 — Grounded Chat Answers

> #912 follow-up slice. EPIC-021 gave the assistant deterministic Advisor Brief
> facts, but streamed chat answers still reached the UI as plain text. This
> slice keeps the model read-only while attaching application-owned grounding
> metadata to each personal-data answer: citations with confidence tiers and
> safe next-action chips for pending review work.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
> (AC22.14.1 removed and AC22.14.3 removed — backend halves migrated to the
> `advisor` package roadmap as `AC-advisor.grounding.1-2`, #1821 Wave A. The
> chatPanelComponent.test.tsx assertions are not tracked by this Python-only
> roadmap.)
> (AC22.14.2 removed, canonical: migrated to the `advisor` package roadmap as
> `AC-advisor.fe-ia-chat.1`, #1821 Wave B)

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

(AC22.15.1 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.19`, #1821 Wave B)
(AC22.15.2 removed, canonical: migrated to the `llm` package roadmap as `AC-llm.fe-ia-ai-settings.1`, #1821 Wave B)
(AC22.15.3 removed, canonical: migrated to the `identity` package roadmap as `AC-identity.fe-ia-identity.1`, #1821 Wave B)

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

(AC22.16.1 removed and AC22.16.2 removed and AC22.16.3 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.20` through `.22`, #1821 Wave B)

### AC22.17 — God-Component Decomposition (FE Structural Hygiene)

> #1117 follow-up slice. The FE audit flagged several oversized pages/components
> that mix data orchestration, layout, and many sub-sections in one function,
> making them hard to test and reason about. This slice decomposes the worst
> offenders into co-located, independently-testable sub-components while
> preserving the rendered surface and behavior exactly — no backend, schema, or
> UX change. (The report package page, also flagged at ~1298 lines, was
> decomposed separately by #1132, so it is out of scope here.)

(AC22.17.2 removed, canonical: migrated to the `reconciliation` package roadmap as `AC-reconciliation.fe-ia-reconciliation.9`, #1821 Wave B)
(AC22.17.3 removed, canonical: migrated to the `extraction` package roadmap as `AC-extraction.fe-ia-extraction.3`, #1821 Wave B)

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

(AC22.18.1 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.20`, #1821 Wave B)
(AC22.18.2 removed and AC22.18.3 removed, canonical: migrated to the `observability` package roadmap as `AC-observability.fe-ia-analytics.1` through `.2`, #1821 Wave B)

### AC22.19 — Reader-First Report Package With Audit Details

> #1210 follow-up slice. The Personal Report Package must read as a terminal
> user deliverable by default. Low-level proof and framework-policy internals
> remain available for audit review, but they are not the primary reading layer
> of the loaded package.

(AC22.19.1 removed and AC22.19.2 removed and AC22.19.3 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.23` through `.25`, #1821 Wave B)

### AC22.20 — Mobile Add To Home Screen Foundation

> #1247 follow-up slice. The authenticated shell already advertises basic
> install metadata, but mobile installation is not yet a product-owned
> experience: Android/Chromium users get no app-level install entry, iOS users
> need explicit Add to Home Screen guidance, and the manifest still launches via
> the legacy `/dashboard` redirect. This slice centralizes the compatibility
> handling in frontend infrastructure so business pages stay untouched. Offline
> financial-data caching, push notifications, badging, background sync, and
> native-app packaging remain out of scope.

(AC22.20.1 removed and AC22.20.2 removed and AC22.20.3 removed and AC22.20.4 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.21` through `.24`, #1821 Wave B)

### AC22.21 — Mobile/PWA Bottom-Tab IA: Audit Hub, Add Sheet, Merged Settings

> PR12 slice (continuation). EPIC-022 collapsed the accounting machinery into a
> nine-item Advanced drawer but kept each as a standing navigation verb, so the
> app stayed information-overloaded. This slice flips to a mobile/PWA-first bottom
> tab bar (Home · Chat · Add · Audit · More), pushes the machinery (Journal,
> Reconciliation, Confidence, Processing) out of navigation into an on-demand
> `/audit` hub, turns Upload into a center Add bottom sheet, merges the three
> Settings pages into one tabbed `/settings`, and gates Portfolio behind a `/more`
> overflow. Deep pages stay reachable and gain back-links; the attention inbox
> (the bell + `/attention`) is reused unchanged. See the low-fidelity design in
> [EPIC-022.pwa-bottom-tab-ia.design.md](./EPIC-022.pwa-bottom-tab-ia.design.md).

(AC22.21.1 removed and AC22.21.2 removed and AC22.21.3 removed and AC22.21.4 removed and AC22.21.5 removed and AC22.21.7 removed, canonical: migrated to the `meta` package roadmap as `AC-meta.fe-ia-nav.25` through `.30`, #1821 Wave B)
(AC22.21.6 removed, canonical: migrated to the `reporting` package roadmap as `AC-reporting.fe-ia-reports.26`, #1821 Wave B)
