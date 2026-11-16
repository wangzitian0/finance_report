# Workflow Events SSOT

> **SSOT Key**: `workflow-events` — User-facing attention projection for EPIC-019. Does not replace audit logs, ledger state, reconciliation state, or PackageDocument readiness (`common/reporting/readme.md`). Cross-ref: [`EPIC-019`](../../docs/project/EPIC-019.event-driven-upload-to-report-ux.md).

## 1. Source of Truth

| Concern | Location |
|---|---|
| Models & sync state | `apps/backend/src/workflow/orm/models.py` (`workflow_sessions`, `workflow_events`, `workflow_sync_states`) |
| Schemas | `apps/backend/src/schemas/workflow.py` |
| Sync & status derivation | `apps/backend/src/workflow/extension/events.py`, `apps/backend/src/workflow/extension/source_fingerprint.py` |
| Router | `apps/backend/src/routers/workflow.py` |
| Package readiness input | `current_package_readiness` in `apps/backend/src/reporting/extension/package_document.py` |
| Frontend notifications | `apps/frontend/src/components/workflow/WorkflowNotifications.tsx`, `apps/frontend/src/components/home/HomeActionBanner.tsx`, `apps/frontend/src/hooks/useWorkflowStatus.ts` |

## 2. Purpose

Workflow events answer: what happened, does the user need to act, where to go next, and how readiness is affected. PackageDocument readiness is owned by `common/reporting/readme.md` and read strictly via `current_package_readiness` (no secondary readiness calculation).

WorkflowSession is the EPIC-019 product object for the upload-to-report journey. Each event timeline belongs to exactly one workflow session (`active-upload-to-report` synthetic session in v1). AI chat sessions are internal `/chat` UI state, not workflow session ownership.

## 3. Event Families & Severity

- Code enum `WorkflowEventFamily` (`apps/backend/src/workflow/base/types.py`): `source.*`, `record.*`, `ledger.auto_posted`, `review.*`, `reconciliation.blocked`, `report.*`.
- Severities: `info` (routine), `success` (completed), `warning`, `action_required`, `blocked`.

## 4. Lifecycle & Persistence Contract

- User lifecycle: `unread -> read -> archived` (`user_id`-scoped; deterministic sync updates mutable copy without resetting user `read`/`archived` state).
- Tables: `workflow_sessions` (`UNIQUE(user_id, dedupe_key)`, `CHECK` internal `report_href`) and `workflow_events` (`UNIQUE(user_id, dedupe_key)`, `CHECK` internal relative `action_href`, named Postgres enums `workflow_event_family_enum`, `workflow_event_severity_enum`, `workflow_event_status_enum`, `workflow_report_impact_enum`, `workflow_session_status_enum`).
- Dedupe keys use `{source_type}:{source_id}:{family}` inside `db.begin_nested()` savepoints so concurrent upserts never poison the outer transaction.
- `action_href` allows only internal relative routes starting with `/`.

## 5. Read Path Rules

Compact API (`apps/backend/src/routers/workflow.py`):
- `GET /workflow/status`
- `GET /workflow/events`
- `PATCH /workflow/events/{event_id}`

Rules:
- `GET /workflow/status` priority: `blocked > needs_action > processing > ready > empty`. Consumes `current_package_readiness` (`draft -> none`, `blocked -> blocked`, `ready -> ready`) alongside badge counts (`unread`, `action_required`, `blocked`) and `active_session`.
- `GET /workflow/events` returns `{ items, total, sessions }`, excludes archived events unless `status=archived` is requested, and reuses `workflow_status.active_session` verbatim so active session state never diverges from `GET /workflow/status`. Remaining session counts are batch-aggregated by `session_id`.
- `PATCH /workflow/events/{event_id}` updates user-owned event status or returns `404`.

## 6. In-App Notification Surfaces

Surfaces:
- `WorkflowNotificationCenter`: Header badge (uses compact `GET /api/workflow/status` via `lib/api.ts`) + Event inbox drawer (loads `GET /api/workflow/events` when opened, grouped by session).
- `WorkflowNotices` (`/upload`, `/events` redirects here): Status feed (`WorkflowStatusFeed`, summarizing routine items under `Routine automation`) + workflow timeline.
- `HomeActionBanner (/)`:
  - `/` is the authenticated home. The `/dashboard` route redirects to `/`.
  - `HomeActionBanner` shows one action at most. When workflow is blocked/needs action, it renders `workflow.status.next_action.href`, `workflow.status.next_action.label`, and `workflow.status.next_action.summary`. An empty summary shows the workflow-state sentence one time.
  - Ready actions route directly to `/reports?tab=package`. It must not hide the statement cards of Home.

## 7. Workflow Navigation

Product navigation IA is owned by EPIC-022 (`apps/frontend/frontend-patterns.md` §9, mobile/PWA bottom tab bar; the earlier multi-split nav model was superseded by EPIC-022 AC22.21). Navigation attention indicators must use `GET /api/workflow/status` through `lib/api.ts` rather than separate polling.

## 12. Initial Derivation

`source_fingerprint.py` computes a one-SQL per-table `(count, sum(timestamps))` digest + date + settings hash excluding derived workflow tables and chat/feedback/outbox/ping tables. When the fingerprint matches and `workflow_sync_states` age `< 15m` (`WORKFLOW_SYNC_STATE_MAX_AGE`), status reads reuse stored readiness with zero writes (`stored_package_readiness` reads without deriving for advisor context).

AC19.12 completes the first lightweight user-facing derivation set. Workflow events are a product attention projection, not a low-level event log; authoritative facts remain in normalized owner tables. Derivation answers only:
- What needs my action now?
- What is blocking trusted report readiness?
- Can I open a trusted report package?
- What recent automation matters enough to summarize?

Included items: Stage-1 review (`NULL` `stage1_status` on `PARSED` counts as pending), parsing failures (excluding review rejections), reconciliation blockers, Processing account blockers exposed through package readiness, and ready/blocked report states. Sync may archive mutable derived action/blocker events when the underlying condition is resolved (never unarchiving user-archived rows). Run-scoped Stage 2 review (`/audit?run_id={run_id}`) passes `run_id` through `GET /api/statements/stage2/queue?run_id={run_id}` and `POST /api/reconciliation/matches`.
