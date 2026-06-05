# Workflow Events SSOT

> **SSOT Key**: `workflow-events`
> **Authority**: This document defines the user-facing workflow event read
> model used by EPIC-019. Workflow events describe product attention state; they
> do not replace audit logs, ledger state, reconciliation state, or report
> traceability.
> **Cross-references**: [confirmation-workflow.md](./confirmation-workflow.md),
> [reconciliation.md](./reconciliation.md), [reporting.md](./reporting.md),
> [schema.md](./schema.md), [EPIC-019](../project/EPIC-019.event-driven-upload-to-report-ux.md)

---

## 1. Source of Truth

| Concern | Location |
|---|---|
| Event and session model | `apps/backend/src/models/workflow.py` |
| Event and session schemas | `apps/backend/src/schemas/workflow.py` |
| Derivation/upsert service | `apps/backend/src/services/workflow_events.py` |
| Compact status/events API | `apps/backend/src/routers/workflow.py` |
| Report package readiness fact source | `GET /api/reports/package/readiness` in `apps/backend/src/services/report_readiness.py` |
| Header badge, Event inbox, Status feed | `apps/frontend/src/components/workflow/WorkflowNotifications.tsx` |
| Upload-to-Report home | `apps/frontend/src/app/(main)/dashboard/page.tsx` |
| Events page | `apps/frontend/src/app/(main)/events/page.tsx` advanced session history surface |
| Workflow navigation IA | `apps/frontend/src/components/navigation.ts` |
| Desktop workflow navigation | `apps/frontend/src/components/Sidebar.tsx` |
| Mobile workflow navigation | `apps/frontend/src/components/MobileNav.tsx` |
| Database migrations | `apps/backend/migrations/versions/0021_add_workflow_events.py`, `apps/backend/migrations/versions/0022_harden_workflow_contract.py`, `apps/backend/migrations/versions/0024_add_workflow_sessions.py` |
| Contract tests | `apps/backend/tests/workflow/test_workflow_events.py`, `apps/backend/tests/api/test_workflow_router.py`, `apps/frontend/src/__tests__/navigation.test.ts`, `apps/frontend/src/__tests__/sidebarAndTabs.test.tsx`, `apps/frontend/src/__tests__/mobileNav.coverage.test.tsx`, `apps/frontend/src/__tests__/workflowApi.test.ts`, `apps/frontend/src/__tests__/workflowSurfaces.test.tsx`, `apps/frontend/playwright/workflow-notifications.spec.ts`, `apps/frontend/playwright/workflow-navigation.spec.ts`, `apps/frontend/playwright/report-readiness.spec.ts` |

---

## 2. Purpose

Workflow events are the product read model for the upload-to-report journey.
They answer:

- What happened?
- Does the user need to act?
- Where should the user go next?
- Does this affect report readiness?

They are intentionally separate from:

- `JournalAuditLog`, which is audit proof for journal mutations.
- `JournalLine.event_type`, which is accounting metadata.
- `BankStatement.status` and `BankStatement.stage1_status`, which are
  statement processing and Stage 1 review state.
- `ReconciliationMatch.status`, which is Stage 2 matching state.
- Report package traceability, which proves report line support.
- Report package readiness, which is owned by `docs/ssot/reporting.md` and
  exposed at `GET /api/reports/package/readiness`.

Workflow events may summarize those sources, but they do not own them.
Workflow status aggregation must consume package readiness as an input rather
than reimplementing package blocker derivation.

WorkflowSession is the EPIC-019 product object for the upload-to-report
journey. A session starts when the user uploads or binds source work into the
active upload-to-report flow and ends when the resulting report is generated or
the session is archived. The current v1 implementation uses one active
synthetic/default upload-to-report session per user so legacy records have a
stable home; future upload-batch work may split sessions by batch without
changing the event timeline contract.

AI chat sessions are internal `/chat` UI state. They support model selection
and conversation history inside the AI utility page, but they are not workflow
session ownership and must not drive upload pipeline readiness, event
actionability, or report blocker semantics.

---

## 3. Event Families

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

The code owner is `WorkflowEventFamily` in
`apps/backend/src/models/workflow.py`.

---

## 4. Severity And Actionability

| Severity | Meaning | UI treatment |
|---|---|---|
| `info` | Routine progress; no immediate user action | Low prominence |
| `success` | Automation completed successfully | Summarizable/collapsible |
| `warning` | User may need awareness, but not necessarily blocked | Medium prominence |
| `action_required` | User input is required to continue | Badge/inbox prominent |
| `blocked` | Report or workflow progress is blocked | Highest prominence |

Successful automation should not create noisy primary UI. `action_required` and
`blocked` events are the main attention drivers.

---

## 5. Lifecycle

Workflow event lifecycle is user-visible only:

```text
unread -> read -> archived
```

Rules:

- New or newly-derived events start as `unread`.
- Rerunning deterministic derivation must not reset an existing read or
  archived event to unread.
- Archive hides an event from default inbox views but does not delete proof or
  underlying business state.
- Lifecycle changes are scoped by `user_id`.

---

## 6. Persistence Contract

The session header table is `workflow_sessions`.

Required `workflow_sessions` fields:

| Field | Purpose |
|---|---|
| `id` | Session identity |
| `user_id` | Owner and isolation boundary |
| `status` | `active`, `generated`, or `archived` |
| `title` | Short UI label |
| `summary` | Plain-language session summary |
| `dedupe_key` | Stable key for synthetic/default or future batch sessions |
| `started_at` | Session start time |
| `last_event_at` | Latest timeline event time |
| `source_count` | Denormalized active event/source count for list surfaces |
| `report_href` | Internal report route when generated |
| `created_at` / `updated_at` | Model timestamps |

Required `workflow_sessions` database rules:

- `UNIQUE(user_id, dedupe_key)`
- `INDEX(user_id, status, last_event_at)`
- `CHECK(report_href)` only allows null or internal relative routes.

Each event timeline belongs to exactly one workflow session after deterministic
sync. Legacy rows may be nullable at the storage level during migration, but
read services must bind derived/upload events to the active synthetic/default
session before returning user-facing responses.

The read model table is `workflow_events`.

Required fields:

| Field | Purpose |
|---|---|
| `id` | Event identity |
| `user_id` | Owner and isolation boundary |
| `session_id` | Owning workflow session timeline |
| `occurred_at` | Product event time |
| `family` | Stable workflow family |
| `severity` | User-facing actionability |
| `status` | User-visible lifecycle |
| `title` | Short UI label |
| `summary` | Plain-language explanation |
| `source_type` | Source domain, for example `bank_statement` |
| `source_id` | Source record id |
| `action_href` | Internal route for the next action or detail view |
| `report_impact` | `none`, `processing`, `ready`, `blocked`, or `stale` |
| `dedupe_key` | Stable deterministic key for idempotent upsert |
| `created_at` / `updated_at` | Model timestamps |

Required database rules:

- `UNIQUE(user_id, dedupe_key)`
- `INDEX(user_id, status, occurred_at)`
- `INDEX(user_id, severity, occurred_at)`
- `INDEX(user_id, family, occurred_at)`
- `INDEX(user_id, source_type, source_id)`
- `INDEX(user_id, session_id, occurred_at)`
- `CHECK(action_href)` only allows internal relative routes: starts with `/`,
  does not start with `//`, and does not contain `://`.

All database enum types must have explicit names:

- `workflow_event_family_enum`
- `workflow_event_severity_enum`
- `workflow_event_status_enum`
- `workflow_report_impact_enum`
- `workflow_session_status_enum`

---

## 7. Dedupe Rules

`dedupe_key` must be deterministic for the same user-visible event. Source
derived events use:

```text
{source_type}:{source_id}:{family}
```

Examples:

```text
bank_statement:4ab1...:source.uploaded
bank_statement:4ab1...:review.required
```

Rerunning derivation updates mutable display fields, but it must not create
duplicates or reset lifecycle status.

---

## 8. Action Links

`action_href` must be an internal relative route. Valid examples:

```text
/statements/{statement_id}
/review
/reconciliation/review-queue
/reconciliation/unmatched
/reports/package
```

Invalid examples:

```text
https://example.com/review
//example.com/review
javascript:alert(1)
statements/{statement_id}
```

External push, email, Slack, browser push, and proactive reminders are out of
scope for EPIC-019.

---

## 9. Read Path Rules

Header badges and global attention indicators must not load the full event
list. They should use compact status/count APIs owned by #636.

Event inbox and status feed views may use paginated event lists. Default lists
must be user-scoped, ordered by recent `occurred_at`, and bounded by a limit.

The compact workflow API is:

```text
GET /workflow/status
GET /workflow/events
PATCH /workflow/events/{event_id}
```

`GET /workflow/status` returns:

- `primary_state`: `empty`, `processing`, `needs_action`, `blocked`, or
  `ready`.
- `next_action`: `upload`, `wait`, `review_required`, `resolve_blocker`,
  `open_report`, or `none`, plus a count, internal route, cockpit label, and
  cockpit summary.
- `report_readiness`: `none`, `processing`, `ready`, `blocked`, or `stale`,
  plus a blocking count and `/reports/package` route.
- `event_counts`: unread, action-required, and blocked counts.
- `active_session`: current active workflow session summary, or null when no
  workflow state exists.

Primary state priority is:

```text
blocked > needs_action > processing > ready > empty
```

The `report_readiness` field consumes the package readiness fact source from
`GET /api/reports/package/readiness` and collapses package states into the
compact workflow readiness vocabulary:
`draft -> none`, `processing -> processing`, `blocked -> blocked`,
`ready -> ready`, `generated -> ready`, and `stale -> stale`.

`GET /workflow/events` returns `{ items, total, sessions }`. It excludes
archived events by default, supports a `status` filter when archived events are
explicitly requested, and enforces a bounded `limit`. `items[].session_id`
links every timeline event to a session summary in `sessions[]` when available.

`PATCH /workflow/events/{event_id}` updates only the authenticated user's event
lifecycle state. Missing or non-owned events return `404`.

---

## 10. In-App Notification Surfaces

EPIC-019 notifications are in-app only. External push, email, Slack, browser
push, proactive reminders, and event bus infrastructure are out of scope.

The frontend notification surface is:

```text
WorkflowNotificationCenter
  -> Header badge
  -> Event inbox drawer

WorkflowStatusFeed
  -> Dashboard status feed
  -> Events page status summary

UploadToReportHome
  -> Dashboard first viewport
  -> Secondary analytics boundary
```

Header badge rules:

- It reads only `GET /api/workflow/status` through `lib/api.ts`.
- It displays unread/action-required/blocked counts from `event_counts`.
- It stays visually quiet when no workflow attention is required.
- It opens the in-app Event inbox drawer.

Event inbox and session history rules:

- It reads `GET /api/workflow/events` only after the user opens the drawer or
  page.
- It groups notifications by workflow session first.
- Each expanded session shows a timestamped event timeline.
- Blocked and action-required events stay visually prominent inside the
  session timeline; routine automation remains compact.
- It supports lifecycle actions through `PATCH /api/workflow/events/{id}`.
- Each event exposes exactly one primary internal action link from
  `action_href`.
- It must not show raw audit-log payloads, low-level ledger internals, or
  source-table debugging fields as primary content.

Status feed rules:

- `WorkflowStatusFeed` summarizes the current upload-to-report state and report
  readiness.
- Blocked and action-required events are prominent.
- Routine automation is summarized under `Routine automation` and is not the
  primary attention driver.
- Empty state says `No action required` and routes the user to upload when no
  workflow state exists.

Upload-to-Report home rules:

- `/dashboard` is the authenticated home for the upload-to-report workflow.
- The first viewport renders workflow state, the primary next action, report
  readiness, active workflow session state, and a recent timeline preview before
  KPI, chart, reconciliation, or activity analytics.
- The primary CTA uses `workflow.status.next_action.href`,
  `workflow.status.next_action.label`, and
  `workflow.status.next_action.summary`. Upload is the default label only when
  no higher-priority blocker or action-required state wins the workflow
  priority.
- Processing actions route to `/events` so the user sees session history rather
  than a raw statement list. Ready actions route directly to `/reports/package`.
- Report readiness appears above secondary analytics and links to the report or
  readiness action route from the workflow status contract.
- Routine automation is summarized; blocked and action-required events remain
  visually prominent.
- Secondary dashboard metric loading or failure must not hide the workflow
  home. Analytics render below the workflow surface with an isolated loading,
  empty, retry, or error state.

---

## 11. Workflow Navigation

EPIC-019 owns the product-level navigation model for the upload-to-report
journey. The primary navigation must express the workflow, not the internal
accounting pipeline.

Primary navigation:

```text
Upload Pipeline -> /dashboard
Reports -> /reports
AI -> /chat
Advanced
```

Advanced navigation:

```text
Events -> /events
Portfolio -> /portfolio
Statements -> /statements
Review -> /review
Accounts -> /accounts
Journal -> /journal
Reconciliation -> /reconciliation
Processing -> /processing
AI Settings -> /settings/ai
```

Rules:

- `/dashboard` remains the authenticated upload-to-report home and is labeled
  as Upload Pipeline in primary navigation.
- `/events` is an Advanced session-history surface, not a primary navigation
  entry.
- `/chat` is labeled AI and is an auxiliary utility, not workflow domain state.
- `/settings/ai` is the AI Settings route.
- Advanced is a navigation group, not a new backend workflow concept.
- Advanced pages are not removed. Direct routes and event `action_href` links
  into review, reconciliation, processing, statements, reports, and package
  readiness must continue to work.
- Desktop and mobile navigation must expose the same primary and advanced
  groups.
- Navigation attention indicators must use `GET /api/workflow/status` through
  `lib/api.ts`. Sidebar-local review queue polling must not calculate separate
  review badge semantics.

---

## 12. Initial Derivation

The first implementation derives `source.uploaded` from `BankStatement` upload
state. Workflow status and event reads run this deterministic sync before
returning data. Repeated reads must not duplicate events or reset read/archive
lifecycle state.

Future slices may add deterministic derivation for:

- Stage 1 review required/completed.
- Reconciliation blockers.
- Processing-account blockers.
