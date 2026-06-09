# EPIC-019: Event-Driven Upload-to-Report UX

> **Status**: In Progress — core UI/API slices complete; AC19.12 lightweight
> derivation remains before Core Complete
> **Vision Anchor**: `decision-2-event-middle-layer`, `decision-3-record-layer`,
> `decision-filter-accuracy-auditability`
> **Phase**: Product workflow hardening
> **Priority**: P0 — the product should feel like upload files, respond to
> required in-app events, and read trusted reports.
> **Dependencies**: EPIC-003, EPIC-004, EPIC-005, EPIC-013, EPIC-016, EPIC-018

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

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.1.1 | Workflow event SSOT defines event families, severity/actionability, lifecycle states, dedupe rules, internal action links, indexes, and relationship to audit logs | `test_AC19_1_1_workflow_event_ssot_registers_manifest_owner` | P0 |
| AC19.1.2 | Backend model defines a user-scoped `workflow_events` read model with explicit enum names, lifecycle status, `UNIQUE(user_id, dedupe_key)`, and badge/inbox read indexes | `test_AC19_1_2_workflow_event_model_contract` | P0 |
| AC19.1.3 | Pydantic schemas validate the workflow event contract and reject external `action_href` values | `test_AC19_1_3_workflow_event_schema_rejects_external_action_href` | P0 |
| AC19.1.4 | Workflow event service deterministically upserts a derived event from existing statement/upload state without duplicating on rerun | `test_AC19_1_4_upsert_uploaded_statement_event_is_deterministic` | P0 |
| AC19.1.5 | Workflow event reads and lifecycle changes are user isolated | `test_AC19_1_5_workflow_event_lifecycle_is_user_isolated` | P0 |

### AC19.2 — Workflow Status API

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.2.1 | Workflow status schemas define stable primary state, next action, report readiness, and event count response contracts for later UI consumers | `test_AC19_2_1_workflow_status_schema_contract` | P0 |
| AC19.2.2 | `GET /workflow/status` returns user-scoped empty, processing, needs-action, blocked, and ready summaries with deterministic priority rules | `test_AC19_2_2_workflow_status_endpoint_returns_priority_summaries` | P0 |
| AC19.2.3 | `GET /workflow/events` returns bounded, user-scoped, deduplicated events, excludes archived events by default, and supports status filtering | `test_AC19_2_3_workflow_events_endpoint_lists_bounded_user_events` | P0 |
| AC19.2.4 | `PATCH /workflow/events/{id}` updates only the authenticated user's event lifecycle and returns 404 for missing or non-owned events | `test_AC19_2_4_workflow_event_patch_is_user_scoped` | P0 |
| AC19.2.5 | Status and events reads run deterministic derived sync without duplicating events or resetting read/archive lifecycle state | `test_AC19_2_5_workflow_reads_sync_derived_events_without_lifecycle_reset` | P0 |
| AC19.2.6 | Workflow API router is mounted and documented in the workflow-events SSOT as the compact read path for later UI slices | `test_AC19_2_6_workflow_router_and_ssot_document_compact_read_path` | P0 |

### AC19.3 — In-App Event Inbox, Header Badge, And Status Feed

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.3.1 | Deterministic sync refreshes mutable derived event fields for all user statements without duplicating events or resetting lifecycle state | `test_AC19_3_1_sync_refreshes_mutable_uploaded_event_fields_without_lifecycle_reset` | P0 |
| AC19.3.2 | Workflow status uses one aggregate count query and only fetches a representative event for the winning branch | `test_AC19_3_2_workflow_status_uses_single_aggregate_for_badge_counts` | P0 |
| AC19.3.3 | Frontend exposes typed workflow API helpers through `lib/api.ts` for status, events, and lifecycle patching | `workflowApi.test.ts` | P0 |
| AC19.3.4 | Header/app-shell badge reflects unread/action-required/blocked counts from the compact workflow API and stays quiet when no attention is needed | `workflowSurfaces.test.tsx` | P0 |
| AC19.3.5 | Event inbox groups events by workflow session timeline, keeps blocked/action-required events prominent, and supports read/archive actions and direct action links | `workflowSurfaces.test.tsx` | P0 |
| AC19.3.6 | Dashboard status feed renders primary state, report readiness, recent automation, blocker/action severity, and an empty no-action state without raw audit-log noise | `workflowSurfaces.test.tsx`, `dashboardPage.test.tsx` | P0 |
| AC19.3.7 | Desktop and mobile Playwright smoke covers the workflow badge/inbox/feed without layout overflow | `workflow-notifications.spec.ts` | P0 |
| AC19.3.8 | Workflow notification UI contract is documented in the workflow-events SSOT and EPIC-019 | `test_AC19_3_8_workflow_notification_ssot_documents_frontend_surfaces` | P0 |

### AC19.4 — Upload-First Entry Surface

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.4.1 | EPIC-019 and workflow-events SSOT define `/dashboard` as the upload-first authenticated home, with dashboard metrics as secondary analytics | `test_AC19_4_1_upload_first_home_ssot_documents_dashboard_contract` | P0 |
| AC19.4.2 | The first dashboard viewport renders the upload-to-report workflow home before KPI, chart, and activity content | `dashboardPage.test.tsx` | P0 |
| AC19.4.3 | The dashboard primary CTA follows `workflow.status.next_action.href` and labels upload as the default action when no higher-priority blocker/action exists | `dashboardPage.test.tsx` | P0 |
| AC19.4.4 | Report readiness state and blocker count are visible above secondary dashboard metrics and link to the readiness/report action path | `dashboardPage.test.tsx` | P0 |
| AC19.4.5 | Recent workflow events are visible, grouped by actionability, and routine automation is summarized without dominating the page | `dashboardPage.test.tsx` | P0 |
| AC19.4.6 | Secondary dashboard metric API failure does not hide the workflow home; the analytics section renders an isolated retry/error state | `dashboardPage.test.tsx` | P0 |
| AC19.4.7 | Desktop and mobile Playwright smoke covers the upload-first dashboard entry without layout overflow | `upload-first-dashboard.spec.ts` | P0 |
| AC19.4.8 | Workflow status returns cockpit-ready `next_action.label` and `next_action.summary`, routes processing to session history, and routes ready reports directly to `/reports/package` | `test_AC19_2_1_workflow_status_schema_contract`, `test_AC19_2_2_workflow_status_endpoint_returns_priority_summaries`, `workflowSurfaces.test.tsx`, `dashboardPage.test.tsx` | P0 |

### AC19.5 — Report Readiness and Blocker State

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.5.1 | Personal report package exposes a user-scoped readiness endpoint that returns deterministic package state, action link, blocker count, and source summary before report output | `test_AC19_5_1_package_readiness_returns_draft_for_empty_user` / `test_AC19_5_1_package_readiness_rejects_unknown_state_and_external_action_links` | P0 |
| AC19.5.2 | Blocked package readiness lists exact blocker categories for failed parsing, pending review, balance mismatch, reconciliation blockers, consistency checks, unresolved Processing balance, and missing source coverage | `test_AC19_5_2_package_readiness_lists_actionable_blockers` | P0 |
| AC19.5.3 | Package readiness deterministically promotes through `draft`, `processing`, `blocked`, `ready`, `generated`, and `stale` based on source state and report snapshot freshness | `test_AC19_5_3_package_readiness_state_priority_and_snapshot_freshness` | P0 |
| AC19.5.4 | Personal report package page renders readiness state and blocker links before package section output | `personalReportPackagePage.test.tsx` | P1 |
| AC19.5.5 | Personal report package page renders non-blocked readiness states without stale blocker cards | `personalReportPackagePage.test.tsx` | P1 |
| AC19.5.6 | Package readiness fails deterministically when duplicate Processing system accounts would otherwise make blockers non-deterministic | `test_AC19_5_6_package_readiness_rejects_duplicate_processing_accounts` | P0 |
| AC19.5.7 | Package readiness converts Processing Account journal lines into base reporting currency before deciding whether the in-transit balance nets to zero | `test_AC19_5_7_package_readiness_converts_processing_balance_before_zero_check` | P0 |

### AC19.6 — Navigation Folding And Advanced Drill-Down

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.6.1 | EPIC-019 and workflow-events SSOT define the canonical primary/advanced navigation IA and document `/dashboard` as the Upload Pipeline primary entry | `test_AC19_6_1_workflow_navigation_ssot_documents_primary_and_advanced_groups` | P0 |
| AC19.6.2 | Frontend navigation exports separate primary workflow nav and advanced nav groups while preserving route config for all existing advanced deep links | `navigation.test.ts` | P0 |
| AC19.6.3 | Desktop sidebar renders Upload Pipeline, Reports, AI, and Advanced as the primary surface; advanced child links remain accessible and active-state aware | `sidebarAndTabs.test.tsx` | P0 |
| AC19.6.4 | Mobile nav renders the same primary/advanced grouping, supports advanced route selection, closes the drawer on navigation, and avoids overflow | `mobileNav.coverage.test.tsx`, `workflow-navigation.spec.ts` | P0 |
| AC19.6.5 | Sidebar attention indicators are derived from `/api/workflow/status` through `lib/api.ts`; direct `/api/statements/pending-review` and stage2 queue polling are removed from Sidebar | `sidebarAndTabs.test.tsx` | P0 |
| AC19.6.6 | Workflow event action links and workspace route labels continue to deep-link into advanced review/reconciliation/processing/report destinations | `workflowSurfaces.test.tsx`, `sidebarAndTabs.test.tsx`, `workflowActionRoutes.test.tsx` | P0 |
| AC19.6.7 | Desktop and mobile Playwright smoke covers the folded navigation and Advanced access without horizontal overflow | `workflow-navigation.spec.ts` | P0 |

### AC19.7 — Framework-Aware Evidence Readiness

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.7.1 | Report readiness must evaluate framework-specific evidence blockers from EPIC-020, including missing settlement coverage, unresolved review, stale market data, missing valuation basis, and AI-only unreviewed policy suggestions before marking US/HK personal reports trusted | `test_AC19_7_1_readiness_consumes_framework_specific_evidence_blockers` | P0 |

### AC19.8 — Workflow Session IA Hardening And CR Cleanup

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.8.1 | WorkflowSession is documented as the EPIC-019 product object; AI chat sessions are documented as `/chat` UI state outside workflow ownership | `test_AC19_8_1_workflow_session_ssot_separates_chat_sessions` | P0 |
| AC19.8.2 | Backend model and migration define `workflow_sessions`, explicit `workflow_session_status_enum`, and nullable legacy-safe `workflow_events.session_id` with session timeline indexes | `test_AC19_8_2_workflow_session_model_contract` | P0 |
| AC19.8.3 | `GET /workflow/status` returns active session summary and `GET /workflow/events` returns session-scoped event timeline metadata | `test_AC19_8_3_workflow_status_and_events_expose_session_timeline` | P0 |
| AC19.8.4 | Notification drawer and Events page group timestamped events by workflow session, while Upload Pipeline shows only active-session latest state plus recent timeline preview | `workflowSurfaces.test.tsx`, `workflow-notifications.spec.ts`, `upload-first-dashboard.spec.ts` | P0 |
| AC19.8.5 | Primary IA is Upload Pipeline, Reports, AI, Advanced; Events and Portfolio are Advanced drill-downs; AI Settings points to `/settings/ai` | `navigation.test.ts`, `sidebarAndTabs.test.tsx`, `mobileNav.coverage.test.tsx`, `workflow-navigation.spec.ts` | P0 |
| AC19.8.6 | `/chat` is a simple AI utility page with model selector, active conversation, and session-list drawer; it is not labeled AI Settings | `chatPanelComponent.test.tsx`, `ChatPageClient.test.tsx` | P1 |
| AC19.8.7 | Report readiness has route-level Playwright smoke coverage before package output | `report-readiness.spec.ts` | P1 |
| AC19.8.8 | CR cleanup fixes mixed-currency investment schedule fallback, missing Processing FX readiness blocker coverage, stale SSOT paths, and stale navigation docs | `test_AC19_8_8_investment_schedule_fallback_holding_cost_basis_converts_currency`, `test_AC19_8_8_package_readiness_blocks_when_processing_fx_conversion_fails`, `report-readiness.spec.ts` | P0 |
| AC19.8.9 | Concurrent `GET /workflow/status` and `GET /workflow/events` reads create or reuse the synthetic active workflow session without duplicate-key 500s | `test_AC19_8_9_active_workflow_session_get_or_create_is_concurrency_safe`, `test_AC19_8_9_active_workflow_session_reactivates_existing_inactive_dedupe_row` | P0 |

### AC19.9 — Source Trust Readiness

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.9.1 | Personal report package readiness returns source trust summary by source class, deterministic PR proof availability, post-merge LLM/OCR coverage, manual-trusted classes, gaps, and blocker codes | `test_AC19_9_1_package_readiness_reports_source_trust_summary` | P0 |
| AC19.9.2 | Personal report package page renders a compact source trust summary before detailed package output | `AC19.9.2 renders compact source trust summary before traceability details` | P0 |

### AC19.10 — Typed Package Source Anchors

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.10.1 | Personal report package traceability resolves journal source IDs to typed source anchors, exposes amount-level source and ledger details for report lines, and blocks unknown source IDs instead of presenting them as statement transactions | `test_AC19_10_1_unknown_journal_source_ids_are_not_reported_as_statement_transactions`, `test_AC5_13_5_package_traceability_returns_dynamic_current_user_identifiers` | P0 |

### AC19.11 — Run-Scoped Stage 2 Review

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.11.1 | `/review/run/{runId}` uses run-scoped Stage 2 queue and batch-approval APIs so approving a run cannot approve pending matches from another workflow session or batch | `test_AC19_11_1_stage2_run_queue_filters_by_run_id`, `AC19.11.1 run review uses run-scoped queue and approval endpoints` | P0 |

### AC19.12 — Lightweight Workflow Derivation Completion

| AC ID | Description | Verification | Priority |
|---|---|---|---|
| AC19.12.1 | EPIC-019 and workflow-events SSOT define lightweight user-facing derivation boundaries, keep low-level source/review/reconciliation/report facts in normalized owner tables, and exclude low-level event logging from workflow events | `test_AC19_12_1_lightweight_derivation_boundary_is_documented` | P0 |
| AC19.12.2 | Workflow sync derives review-required and review-completed user action events from existing review state without duplicating events or resetting read/archive lifecycle | `test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved`, `test_AC19_12_2_review_derivation_treats_null_stage1_as_pending_without_parse_failure` | P0 |
| AC19.12.3 | Workflow sync derives report-blocked and report-ready events from package readiness without duplicating report-readiness financial logic | `test_AC19_12_3_report_readiness_events_follow_package_readiness_without_stale_blockers` | P0 |
| AC19.12.4 | Workflow sync derives reconciliation and Processing account blocker events only when they affect user action or trusted report readiness | `test_AC19_12_4_readiness_blocker_events_are_user_action_scoped` | P0 |
| AC19.12.5 | Dashboard status feed and event inbox render lightweight derived events as user actions while routine/internal details remain collapsed or absent | `workflowSurfaces.test.tsx` | P0 |
| AC19.12.6 | Lightweight derivation tests cover multi-user isolation, repeated sync idempotency, lifecycle preservation, and resolved-blocker archival | `test_AC19_12_2_review_events_are_current_user_actions_with_lifecycle_preserved`, `test_AC19_12_3_report_readiness_events_follow_package_readiness_without_stale_blockers`, `test_AC19_12_4_readiness_blocker_events_are_user_action_scoped` | P0 |

## How To Build It

### Backend

- Start with derived events from existing persisted state and audit checkpoints.
- Use stable `dedupe_key` values so repeated polling does not duplicate events.
- Keep event reads user-scoped.
- Keep event payloads small; detail pages own deep payloads.
- Add repository/service tests around status derivation and actionability.

Potential service boundaries:

```text
apps/backend/src/services/workflow_events.py
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
