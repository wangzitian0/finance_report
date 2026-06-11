# EPIC-022: Everyday-User Information Architecture

> **Status**: In Progress — PR1 (IA skeleton) slice landing; unified inbox and
> report drill-down slices tracked separately.
> **Vision Anchor**: builds on EPIC-019 (`upload + reports primary, events
> notify`). EPIC-019 introduced workflow events but kept internal accounting
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
| AC22.1.1 | Primary navigation renders exactly three peers (Upload, Reports, Chat) plus a collapsible Advanced group; no accounting-jargon route (Journal, Reconciliation, Accounts, Statements) appears at the top level | `epic022Navigation.test.tsx` | P1 |
| AC22.1.2 | The authenticated Home renders financial key numbers, an action-required summary, and a quick-upload entry | `homePage.test.tsx` | P1 |
| AC22.1.3 | The sidebar brand links to `/` and the login flow redirects to `/` after authentication | `epic022Navigation.test.tsx` | P1 |
| AC22.1.4 | `/dashboard` redirects to `/` and the label "Upload Pipeline" no longer appears in the navigation model | `nextConfigRedirects.test.ts`, `epic022Navigation.test.tsx` | P1 |
| AC22.1.5 | `/events` redirects to `/notifications` and the notifications page renders the workflow event center | `nextConfigRedirects.test.ts`, `notificationsPage.test.tsx` | P1 |
| AC22.1.6 | `/assets` redirects to `/portfolio` and exactly one navigation entry is labeled "Portfolio" | `nextConfigRedirects.test.ts`, `epic022Navigation.test.tsx` | P1 |
| AC22.1.7 | Chat and AI Settings navigation entries use distinct icons | `epic022Navigation.test.tsx` | P1 |
| AC22.1.8 | `/upload` renders both the statement uploader and upload history, and `/statements/upload` redirects to `/upload` | `uploadPage.test.tsx`, `nextConfigRedirects.test.ts` | P1 |
| AC22.1.9 | Desktop and mobile smoke covers the 3-peer navigation, the Advanced toggle, and the notification bell without layout overflow | `epic022-ia-shell.spec.ts` | P1 |
