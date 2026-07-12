# EPIC-019: Event-Driven Upload-to-Report UX

> **Status**: In Progress — core UI/API slices complete; AC19.12 lightweight
> derivation remains before Core Complete
> **Vision Anchor**: `decision-2-event-middle-layer`, `decision-3-record-layer`,
> `decision-filter-accuracy-auditability`
> **Phase**: Product workflow hardening
> **Priority**: P0 — the product should feel like upload files, respond to
> required in-app events, and read trusted reports.
> **Dependencies**: EPIC-003, EPIC-004, EPIC-005, EPIC-013, EPIC-016, EPIC-018
> **Usable milestone**: 🎯 gating (G2). AC19.12 lightweight workflow derivation is required so a year of uploads reliably derives reports without hand-holding. Durable Prefect orchestration (AC19.13) stays deferred. See the [Usable cut](https://github.com/wangzitian0/finance_report/milestone/1).

---

## Objective

Make **Upload** and **Reports** the primary user operations. Convert parsing,
validation, reconciliation, review, and report readiness into in-app workflow
events that notify the user only when action is needed.

The intended user model is:

```text
Upload files
  -> system processes automatically
  -> in-app events notify only required action
  -> user reviews exceptions when necessary
  -> user reads trusted reports
```

This EPIC owns the product-level event experience. It does not replace the
existing audit logs, accounting event types, or AI pipeline. It turns those
lower-level facts into a user-facing workflow state.

## Why This EPIC Exists

The current UI exposes internal accounting modules as first-class navigation:

```text
Dashboard / Accounts / Journal / Statements / Review / Reconciliation /
Processing / Reports / AI Advisor
```

Those surfaces are useful, but they require users to understand the internal
pipeline. The vision expects the opposite: the system should automate the
routine path and ask for human review only when accuracy, auditability, or
reconciliation confidence requires it.

The missing product layer is:

```text
Workflow events + actionability + report readiness + drill-down details
```

Without it, the user must poll multiple pages to answer:

- Did my upload finish?
- Did the system auto-post the safe items?
- Is anything blocking the report?
- What needs my review?
- Can I trust the report now?

## Non-Goals

- External push notifications, email, Slack, browser push, or proactive
  reminders. This EPIC is in-app only and remains compatible with the existing
  passive notification decision.
- Replacing audit logs. Audit logs remain proof and replay infrastructure;
  workflow events are user-facing product state.
- Replacing deterministic bookkeeping. AI may explain, suggest, and classify,
  but ledger and report correctness remains deterministic.
- Removing advanced accounting pages. They become drill-down surfaces instead
  of primary user operations.
- Implementing a full event bus or message queue in the first slice. The first
  implementation can derive events from existing tables and audit checkpoints.

## MECE Breakdown

The EPIC is split into six mutually exclusive, collectively exhaustive slices.

### Slice 1 — Product Workflow Event Model

**Question answered:** What happened, does the user need to act, and what does
it affect?

Define a product-level event contract distinct from audit logs and accounting
`event_type` fields.

Initial event families:

```text
source.uploaded
source.parsing.started
source.parsing.completed
source.parsing.failed
record.validation.passed
record.validation.failed
ledger.auto_posted
review.required
review.completed
reconciliation.blocked
report.processing
report.ready
report.blocked
report.generated
```

Each event must expose:

- `id`
- `occurred_at`
- `family`
- `severity`: `info | success | warning | action_required | blocked`
- `status`: `unread | read | archived`
- `title`
- `summary`
- `source_type`
- `source_id`
- `action_href`
- `report_impact`
- `dedupe_key`

**Why this works:** it creates one shared language between upload, review,
reconciliation, and reports. The UI no longer needs to infer urgency from many
page-local statuses.

### Slice 2 — Workflow Status API

**Question answered:** What is the current Upload-to-Report state?

Add a compact workflow summary API that can power header badges, the event
inbox, and report readiness without forcing every page to duplicate logic.

Initial API shape:

```text
GET /workflow/status
GET /workflow/events
PATCH /workflow/events/{id}
```

Frontend callers use the existing `/api/*` proxy convention, so #637 should
call `/api/workflow/status` and `/api/workflow/events` through `lib/api.ts`.

Representative status payload:

```json
{
  "primary_state": "needs_action",
  "next_action": {
    "type": "review_required",
    "count": 2,
    "href": "/review?source=events"
  },
  "report_readiness": {
    "state": "blocked",
    "blocking_count": 2,
    "href": "/reports"
  },
  "event_counts": {
    "unread": 4,
    "action_required": 2,
    "blocked": 1
  }
}
```

**Why this works:** every primary UI surface can use the same source of truth
for whether the user should upload, wait, review, or read reports.

### Slice 3 — In-App Event Inbox, Header Badge, and Status Feed

**Question answered:** What should the user notice now?

Add a persistent in-app notification layer:

- Header badge for unread/action-required events.
- Event inbox drawer or page.
- Status feed on the upload/report home surface.
- Read/archive interactions.
- Direct links to the exact review, upload, reconciliation, or report target.

Event display rules:

- Successful automation is summarized and collapsible by default.
- `action_required` and `blocked` events are visually prominent.
- Events must explain why human input is needed.
- Each action event must have one clear next step.

**Why this works:** users no longer browse internal modules to discover work.
The system surfaces only the events that need attention.

### Slice 4 — Upload-First Entry Surface

**Question answered:** What is the simplest first action?

Make upload the first-class product entry. The user should see:

- Upload CTA.
- Recent processing status.
- Current event feed.
- Required action summary.
- Report readiness summary.

`/dashboard` is the authenticated Upload-to-Report home. Existing dashboard
metrics remain available, but they are secondary analytics below the workflow
entry surface and must not block upload, event, or report readiness actions.

**Why this works:** it aligns first-screen behavior with the core use case:
upload files and let the system work.

### Slice 5 — Report Readiness and Blocker State

**Question answered:** Can the user trust the report?

Reports must show readiness before output:

```text
Ready
Processing
Blocked
Draft
Generated
Stale
```

Report readiness must link to blockers:

- Pending review items.
- Failed parsing.
- Balance mismatch.
- Unresolved processing account balance.
- Reconciliation blockers.
- Missing source coverage.

Readiness contracts must reject unknown states, reject non-internal action
links, expose timestamps as validated datetime fields, and fail deterministically
when canonical system accounts are duplicated.

**Why this works:** the product becomes trustworthy because the UI tells users
whether a report is supported by processed, validated, and reviewed source data.

### Slice 6 — Navigation Folding and Advanced Drill-Down

**Question answered:** Which surfaces are primary, and which are details?

Target primary navigation:

```text
Upload Pipeline
Reports
AI
Advanced
```

Advanced contains:

```text
Events
Portfolio
Statements
Review
Accounts
Journal
Reconciliation
Processing
AI Settings
```

Events becomes a session-history drill-down. Review, reconciliation,
processing, portfolio, and settings remain accessible from direct event actions
or Advanced. They are not removed; they are demoted from default navigation.

WorkflowSession is the user-facing product object that joins latest landing
state with timestamped event history. Upload Pipeline shows the active session's
latest state; notifications and Events show session-scoped timelines. AI chat
sessions are only `/chat` page conversation state and do not participate in
WorkflowSession ownership.

**Why this works:** the main UI matches the user-facing workflow, while power
users and debugging workflows still have full access to accounting details.

## Issue Decomposition

| Slice | Issue | Scope | Dependencies |
|---|---|---|---|
| 1 | [#635](https://github.com/wangzitian0/finance_report/issues/635) — Define product workflow event model | SSOT and backend contract for user-facing events | None |
| 2 | [#636](https://github.com/wangzitian0/finance_report/issues/636) — Add workflow status API | Backend endpoints for status and events | Slice 1 |
| 3 | [#637](https://github.com/wangzitian0/finance_report/issues/637) — Add in-app event inbox and header badge | Frontend notification center, badge, feed | Slice 2 |
| 4 | [#638](https://github.com/wangzitian0/finance_report/issues/638) — Build upload-first entry surface | Upload/report/event home surface | Slice 2, Slice 3 |
| 5 | [#639](https://github.com/wangzitian0/finance_report/issues/639) — Add report readiness and blockers | Reports readiness state and blocker links | Slice 2 |
| 6 | [#640](https://github.com/wangzitian0/finance_report/issues/640) — Fold navigation into primary and advanced surfaces | Navigation IA change and route discoverability | Slice 3, Slice 4, Slice 5 |

## Delivery Order

1. Define the product workflow event model.
2. Add workflow status/events API using derived state from existing tables and
   audit checkpoints.
3. Add in-app event inbox, header badge, and status feed.
4. Build the upload-first entry surface.
5. Add report readiness and blocker links.
6. Fold navigation after the destination surfaces exist.

This order avoids a cosmetic navigation reshuffle before the underlying
workflow state exists.

## Acceptance Criteria

### AC19.1 — Product Workflow Event Model

> This group's rows removed — migrated to the `platform` package roadmap as
> `AC-platform.30.1-5` (migration closeout continuation, #1663 / #1712).

### AC19.2 — Workflow Status API

> This group's rows removed — migrated to the `platform` package roadmap as
> `AC-platform.31.1-7` (migration closeout continuation, #1663 / #1712).

### AC19.3 — In-App Event Inbox, Header Badge, And Status Feed

> **Partially migrated.** *(AC19.3.1 removed and AC19.3.2 removed — this
> group's backend sync/aggregation rows migrated to the `platform` package
> roadmap as `AC-platform.32.1-2`, migration closeout continuation, #1663 /
> #1712)*. The frontend rows below stay with their own owner.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.3.3 | Frontend exposes typed workflow API helpers through `lib/api.ts` for status, events, and lifecycle patching | `workflowApi.test.ts` | P0 |
| AC19.3.4 | Header/app-shell badge reflects unread/action-required/blocked counts from the compact workflow API and stays quiet when no attention is needed | `workflowSurfaces.test.tsx` | P0 |
| AC19.3.5 | Event inbox groups events by workflow session timeline, keeps blocked/action-required events prominent, and supports read/archive actions and direct action links | `workflowSurfaces.test.tsx` | P0 |
| AC19.3.6 | Dashboard status feed renders primary state, report readiness, recent automation, blocker/action severity, and an empty no-action state without raw audit-log noise | `workflowSurfaces.test.tsx`, `dashboardPage.test.tsx` | P0 |
| AC19.3.7 | Desktop and mobile Playwright smoke covers the workflow badge/inbox/feed without layout overflow | `workflow-notifications.spec.ts` | P0 |
| AC19.3.8 | Workflow notification UI contract is documented in the workflow-events SSOT and EPIC-019 | `test_AC19_3_8_workflow_notification_ssot_documents_frontend_surfaces` | P0 |

### AC19.4 — Upload-First Entry Surface

> *(AC19.4.1 removed — migrated to the `platform` package roadmap as
> `AC-platform.32.3`, migration closeout continuation, #1663 / #1712)*

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.4.2 | The first dashboard viewport renders the upload-to-report workflow home before KPI, chart, and activity content | `dashboardPage.test.tsx` | P0 |
| AC19.4.3 | The dashboard primary CTA follows `workflow.status.next_action.href` and labels upload as the default action when no higher-priority blocker/action exists | `dashboardPage.test.tsx` | P0 |
| AC19.4.4 | Report readiness state and blocker count are visible above secondary dashboard metrics and link to the readiness/report action path | `dashboardPage.test.tsx` | P0 |
| AC19.4.5 | Recent workflow events are visible, grouped by actionability, and routine automation is summarized without dominating the page | `dashboardPage.test.tsx` | P0 |
| AC19.4.6 | Secondary dashboard metric API failure does not hide the workflow home; the analytics section renders an isolated retry/error state | `dashboardPage.test.tsx` | P0 |
| AC19.4.7 | Desktop and mobile Playwright smoke covers the upload-first dashboard entry without layout overflow | `upload-first-dashboard.spec.ts` | P0 |
| AC19.4.8 | Workflow status returns cockpit-ready `next_action.label` and `next_action.summary`, routes processing to session history, and routes ready reports directly to `/reports/package` | `test_AC19_2_1_workflow_status_schema_contract`, `test_AC19_2_2_workflow_status_endpoint_returns_priority_summaries`, `workflowSurfaces.test.tsx`, `dashboardPage.test.tsx` | P0 |

### AC19.5 — Report Readiness and Blocker State

> *(AC19.5.1 removed and AC19.5.2 removed and AC19.5.3 removed and AC19.5.6 removed and AC19.5.7 removed — this group's backend readiness rows migrated to the `reporting` package roadmap as `AC-reporting.readiness.1-5`, migration closeout continuation, #1663 / #1716)*. The frontend rows below stay here.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.5.4 | Personal report package page renders readiness state and blocker links before package section output | `personalReportPackagePage.test.tsx` | P1 |
| AC19.5.5 | Personal report package page renders non-blocked readiness states without stale blocker cards | `personalReportPackagePage.test.tsx` | P1 |

### AC19.6 — Navigation Folding And Advanced Drill-Down

> **Superseded by EPIC-022 AC22.21.** AC19.6.1–AC19.6.7 below describe the
> original primary/advanced navigation model (Upload Pipeline / Reports / AI /
> Advanced + mobile drawer). EPIC-022 PR12 replaced it with a mobile/PWA bottom
> tab bar (Home · Chat · Add · Audit · More); navigation IA is now owned by
> EPIC-022 and `docs/ssot/frontend-patterns.md` §9. These rows are kept for
> history with their Verification updated to the current tests; the live
> navigation contract is AC22.21.x. Deep-link reachability (AC19.6.6) still holds.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.6.1 | The workflow-events SSOT cedes navigation-IA ownership to EPIC-022 (bottom-tab) and keeps only the workflow-attention contract; the superseded primary/advanced split is no longer documented there | `test_AC19_6_1_workflow_navigation_ia_owned_by_epic022_with_attention_contract` | P0 |
| AC19.6.2 | Frontend navigation exports separate primary workflow nav and advanced nav groups while preserving route config for all existing advanced deep links | `navigation.test.ts` | P0 |
| AC19.6.3 | Desktop sidebar renders Upload Pipeline, Reports, AI, and Advanced as the primary surface; advanced child links remain accessible and active-state aware | `sidebarAndTabs.test.tsx` | P0 |
| AC19.6.4 | Mobile navigation (now the bottom tab bar, per AC22.21) exposes the workflow surfaces and avoids overflow | `bottomTabBar.test.tsx`, `workflow-navigation.spec.ts` | P0 |
| AC19.6.5 | Sidebar attention indicators are derived from `/api/workflow/status` through `lib/api.ts`; direct `/api/statements/pending-review` and stage2 queue polling are removed from Sidebar | `sidebarAndTabs.test.tsx` | P0 |
| AC19.6.6 | Workflow event action links and workspace route labels continue to deep-link into advanced review/reconciliation/processing/report destinations | `workflowSurfaces.test.tsx`, `sidebarAndTabs.test.tsx`, `workflowActionRoutes.test.tsx` | P0 |
| AC19.6.7 | Desktop and mobile Playwright smoke covers the folded navigation and Advanced access without horizontal overflow | `workflow-navigation.spec.ts` | P0 |

### AC19.7 — Framework-Aware Evidence Readiness

Report readiness must evaluate
framework-specific evidence blockers from EPIC-020 — including
missing settlement coverage, unresolved review, stale market data,
missing valuation basis, and AI-only unreviewed policy suggestions —
before marking US/HK personal reports trusted.

> This group's row removed — migrated to the `reporting` package roadmap as
> `AC-reporting.readiness.6` (migration closeout continuation, #1663 /
> #1716).

### AC19.8 — Workflow Session IA Hardening And CR Cleanup

> **Partially migrated.** *(AC19.8.1 removed and AC19.8.2 removed and AC19.8.3 removed and AC19.8.9 removed — this group's backend session-model/API rows migrated to the `platform` package roadmap as `AC-platform.33.1-4`, migration closeout continuation, #1663 / #1712)*. The frontend, IA,
> and report-readiness rows below stay with their own owners.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.8.4 | Notification drawer and Events page group timestamped events by workflow session, while Upload Pipeline shows only active-session latest state plus recent timeline preview | `workflowSurfaces.test.tsx`, `workflow-notifications.spec.ts`, `upload-first-dashboard.spec.ts` | P0 |
| AC19.8.5 | Navigation IA (superseded by EPIC-022 AC22.21): the bottom tab bar is Home, Chat, Add, Audit, More; the accounting machinery and settings are reached via the Audit hub and More, not a primary/advanced split | `navigation.test.ts`, `sidebarAndTabs.test.tsx`, `bottomTabBar.test.tsx`, `workflow-navigation.spec.ts` | P0 |
| AC19.8.6 | `/chat` is a simple AI utility page with model selector, active conversation, and session-list drawer; it is not labeled AI Settings | `chatPanelComponent.test.tsx`, `ChatPageClient.test.tsx` | P1 |
| AC19.8.7 | Report readiness has route-level Playwright smoke coverage before package output | `report-readiness.spec.ts` | P1 |
| AC19.8.8 | CR cleanup fixes missing Processing FX readiness blocker coverage, stale SSOT paths, and stale navigation docs (the mixed-currency investment-schedule-fallback share migrated to the `portfolio` package roadmap as `AC-portfolio.schedule-fallback.1`, migration closeout continuation, #1663 / #1717) | `test_AC19_8_8_package_readiness_blocks_when_processing_fx_conversion_fails`, `report-readiness.spec.ts` | P0 |

### AC19.9 — Source Trust Readiness

> *(AC19.9.1 removed — migrated to the `reporting` package roadmap as
> `AC-reporting.source-trust.1`, migration closeout continuation, #1663 /
> #1716.)* The frontend row below stays here.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.9.2 | Personal report package page renders a compact source trust summary before detailed package output | `AC19.9.2 renders compact source trust summary before traceability details` | P0 |

### AC19.10 — Typed Package Source Anchors

> This group's row removed — migrated to the `reporting` package roadmap as
> `AC-reporting.source-anchors.1` (migration closeout continuation, #1663 /
> #1716).

### AC19.11 — Run-Scoped Stage 2 Review

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.11.1 | `/review/run/{runId}` uses run-scoped Stage 2 queue and batch-approval APIs so approving a run cannot approve pending matches from another workflow session or batch. Backend half (`test_AC19_11_1_stage2_run_queue_filters_by_run_id`) migrated to the `reconciliation` package roadmap as `AC-reconciliation.run-scoped-review.1` (migration closeout continuation, #1663 / #1711); the frontend half stays here. | `AC19.11.1 run review uses run-scoped queue and approval endpoints` | P0 |

### AC19.12 — Lightweight Workflow Derivation Completion

> **Partially migrated.** *(AC19.12.1 removed and AC19.12.2 removed and AC19.12.3 removed and AC19.12.4 removed — this group's backend derivation rows migrated to the `platform` package roadmap as `AC-platform.34.1-4`, migration closeout continuation, #1663 / #1712)*. *(AC19.12.6 removed — a coverage-summary row citing the same tests as .2-.4, a duplicate)*. The
> frontend row below stays with its own owner.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.12.5 | Dashboard status feed and event inbox render lightweight derived events as user actions while routine/internal details remain collapsed or absent | `workflowSurfaces.test.tsx` | P0 |

### AC19.13 — Durable Orchestration via Prefect

Realizes the deferred "full event bus or message queue" non-goal: upload→report
parsing migrates from in-process `asyncio.create_task` to durable Prefect flow
runs, behind a config gate so CI/local/preview keep running without any Prefect
dependency (delivery speed unaffected).

| AC | Description | Test Anchor | Priority |
|----|-------------|-------------|----------|
| AC19.13.1 | Statement parse dispatch is config-gated: with `PREFECT_API_URL` unset, `submit_parse_pipeline` runs the existing in-process `asyncio.create_task` fallback (no Prefect import) and returns the task to track | `test_AC19_13_1_dispatch_falls_back_to_asyncio_when_prefect_unset`, `test_AC19_13_1_dispatch_registers_exception_consumer_on_fallback` | P0 |
| AC19.13.2 | With `PREFECT_API_URL` set, `submit_parse_pipeline` submits a Prefect flow run with serializable params only (no raw bytes, no session maker — the worker re-fetches content and builds its own session) and returns None | `test_AC19_13_2_dispatch_submits_serializable_params_to_prefect` | P0 |

### AC19.14 — Workflow-event dedupe is transaction-safe (issue #1033)

> Migrated to the `platform` package roadmap as `AC-platform.35.1-3`
> (migration closeout continuation, #1663 / #1712).

Concurrent requests/background tasks for the same `(user_id, dedupe_key)` both miss the
pre-insert SELECT and both insert; the loser raised a `UniqueViolationError` on
`uq_workflow_events_user_dedupe_key` during autoflush, poisoning the outer request transaction so
`/chat/suggestions`, `/workflow/events`, and advisor panels cascaded into 500s. Every workflow-event
insert now runs inside a SAVEPOINT and recovers the existing row on conflict, mirroring the existing
`uq_workflow_sessions_user_dedupe_key` guard.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.14.1 | Two concurrent `upsert_workflow_event` calls for the same `(user_id, dedupe_key)` both succeed without a duplicate-key 500; exactly one row exists and both calls return it | `test_AC19_14_1_concurrent_upsert_same_dedupe_key_does_not_500` | P0 |
| AC19.14.2 | A duplicate `(user_id, dedupe_key)` insert recovers via savepoint, returns the existing row, and leaves the outer transaction usable for subsequent reads/flushes | `test_AC19_14_2_duplicate_insert_does_not_poison_outer_transaction` | P0 |
| AC19.14.3 | Concurrent `sync_workflow_events_for_user` runs over the same source state do not 500 on the workflow-event dedupe key and create the derived uploaded event exactly once | `test_AC19_14_3_sync_tolerates_concurrent_event_creation` | P0 |

### AC19.15 — Three-Entry Upload Intake (issue #1208)

The Upload page must present exactly **three** intake entries, not a per-source
checklist that forces the user to pre-classify their evidence:

1. **Statement upload (primary)** — one uploader for the majority of source
   classes (bank, brokerage, settlement, liability, …). The user never picks a
   type; the AI identifies it after upload and the rest happens passively via
   notification / chat / review.
2. **CSV import (folded)** — a separate entry because non-standard column
   headers need their own server-side mapping. Collapsed by default.
3. **Manual records (folded)** — one entry for assets no statement can verify
   (ESOP/RSU, property, …), each with its own guided UI inside. Collapsed by
   default and clearly labelled as manual-trusted.

This supersedes the earlier per-source-class "intake checklist" (and its SSOT
parity guard), which drifted from the single-entry + LLM-typed + passive design.
This slice is UI structure only; it does not introduce new parsers or change
backend source-trust decisions. Required-source-class coverage remains governed
independently by AC-extraction.112 over `docs/ssot/source-coverage-matrix.yaml`.

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.15.1 | The Upload page exposes exactly three intake entries — one primary statement uploader (the AI identifies the type; the user never pre-classifies), one CSV import, and one Manual records entry — with no per-source-class checklist | `AC19.15.1 exposes exactly three intake entries: one statement uploader plus CSV and Manual` | P1 |
| AC19.15.2 | The CSV import and Manual records entries are folded (collapsed) by default so they stay passive, the retired per-source-class checklist does not return, and the page does not fetch report readiness merely to render intake | `AC19.15.2 keeps secondary intake passive: CSV and Manual folded, no per-class checklist, no readiness fetch` | P1 |
| AC19.15.3 {tier:CODE-ONLY} | The primary statement uploader (`kind="statement"`) rejects `.csv` files by extension before setting a selected file, and the CSV import uploader (`kind="csv"`) rejects non-csv files and accepts `.csv` — each intake entry enforces its own kind's file-extension restriction, independent of the shared `all`-kind default | `AC19.15.3 statement uploader rejects csv and csv uploader rejects non-csv, each enforcing its own kind's extensions` | P1 |

Traceability note: AC19.15 is tracked in this EPIC-local product UI table.
AC19.15.3 backfills coverage the [finance_report_ui] fix(e2e) #1542 gap exposed:
`StatementUploader.test.tsx` only ever rendered the default `kind="all"`, and
`statementsPage.test.tsx` mocks `StatementUploader` out entirely, so the
per-kind extension contract that Tier-3 E2E depends on had no unit/component-tier
test — a Tier-3-only regression had to hit a real staging deploy to be caught.

## How To Build It

### Backend

- Start with derived events from existing persisted state and audit checkpoints.
- Use stable `dedupe_key` values so repeated polling does not duplicate events.
- Keep event reads user-scoped.
- Keep event payloads small; detail pages own deep payloads.
- Add repository/service tests around status derivation and actionability.

Potential service boundaries:

```text
apps/backend/src/platform/extension/workflow_events.py
apps/backend/src/routers/workflow.py
apps/backend/src/schemas/workflow.py
```

### Frontend

- Use `lib/api.ts` only; no raw `fetch()`.
- Add a small workflow client hook with React Query.
- Header badge should read the same workflow status as the inbox.
- Event drawer/page should use existing UI primitives and token classes.
- Preserve mobile behavior: inbox and status feed must work at phone widths.

Potential surfaces:

```text
components/workflow/EventInbox.tsx
components/workflow/HeaderEventBadge.tsx
components/workflow/StatusFeed.tsx
app/(main)/events/page.tsx
app/(main)/dashboard/page.tsx or app/(main)/upload/page.tsx
```

### SSOT

Add or update SSOT before implementation:

```text
docs/ssot/workflow-events.md
docs/ssot/frontend-patterns.md
docs/ssot/confirmation-workflow.md
docs/ssot/reporting.md
```

The SSOT must define:

- Event families.
- Severity/actionability rules.
- Read/archive semantics.
- Report readiness states.
- Relationship to audit logs.
- In-app-only notification policy.

### Testing

Each implementation issue must register ACs when it starts and include tests in
the same PR.

Expected proof:

- Backend unit tests for event derivation.
- API tests for workflow status/events.
- Frontend component tests for badge, inbox, status feed, and empty states.
- Playwright smoke for upload-first home, event inbox, and report readiness.
- The existing upload-to-trusted-reports hard gate is the initial macro E2E
  owner for this planned EPIC. Implementation issues #637, #638, and #639 must
  add event-specific Playwright coverage before their feature slices are
  mergeable.
- AC traceability gate passing.

## Why This Will Be Useful

This EPIC changes the product from a module browser into a workflow assistant.

Before:

```text
The user opens multiple modules to discover what happened and what to do.
```

After:

```text
The user uploads files, reacts to in-app events only when needed, and reads a
report whose readiness state is explicit.
```

That is useful because it directly matches the product promise:

- Routine processing is automated and quiet.
- Human attention is reserved for exceptions.
- Report trust is visible.
- Advanced accounting detail remains available but no longer dominates the main
  experience.

## Quality Bar

Work under this EPIC must meet current project delivery standards:

- EPIC -> AC -> failing test -> code -> SSOT.
- No direct commits to `main`.
- No raw frontend `fetch()`.
- No monetary `float`.
- No unregistered mandatory ACs.
- `moon run :lint` and relevant frontend/backend tests pass locally where the
  environment allows.
- CI must pass before merge.
- PR previews must be healthy for UI changes.
- Playwright visual smoke must cover any new primary workflow screen.

## Surrounding Improvements Required

- Clarify the existing `DECISIONS.md` passive-only notification decision to
  explicitly allow in-app event inboxes and header badges while still excluding
  external pushes.
- Decide whether the existing dashboard route becomes the upload-first home or
  whether a new `/upload` route becomes primary.
- Ensure report readiness has backend ownership in EPIC-005 or this EPIC; avoid
  duplicating readiness logic page-by-page.
- Keep EPIC-018 focused on AI pipeline capability. EPIC-019 consumes those AI
  confidence/review outputs as workflow events.
- Keep EPIC-016 focused on review interaction quality. EPIC-019 determines when
  review is surfaced to the user.
