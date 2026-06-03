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
| Event model | `apps/backend/src/models/workflow.py` |
| Event schemas | `apps/backend/src/schemas/workflow.py` |
| Derivation/upsert service | `apps/backend/src/services/workflow_events.py` |
| Compact status/events API | `apps/backend/src/routers/workflow.py` |
| Database migrations | `apps/backend/migrations/versions/0021_add_workflow_events.py`, `apps/backend/migrations/versions/0022_harden_workflow_contract.py` |
| Contract tests | `apps/backend/tests/workflow/test_workflow_events.py`, `apps/backend/tests/api/test_workflow_router.py` |

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

Workflow events may summarize those sources, but they do not own them.

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

The read model table is `workflow_events`.

Required fields:

| Field | Purpose |
|---|---|
| `id` | Event identity |
| `user_id` | Owner and isolation boundary |
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
- `CHECK(action_href)` only allows internal relative routes: starts with `/`,
  does not start with `//`, and does not contain `://`.

All database enum types must have explicit names:

- `workflow_event_family_enum`
- `workflow_event_severity_enum`
- `workflow_event_status_enum`
- `workflow_report_impact_enum`

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
  `open_report`, or `none`, plus a count and internal route.
- `report_readiness`: `none`, `processing`, `ready`, `blocked`, or `stale`,
  plus a blocking count and `/reports` route.
- `event_counts`: unread, action-required, and blocked counts.

Primary state priority is:

```text
blocked > needs_action > processing > ready > empty
```

`GET /workflow/events` returns `{ items, total }`. It excludes archived events
by default, supports a `status` filter when archived events are explicitly
requested, and enforces a bounded `limit`.

`PATCH /workflow/events/{event_id}` updates only the authenticated user's event
lifecycle state. Missing or non-owned events return `404`.

---

## 10. Initial Derivation

The first implementation derives `source.uploaded` from `BankStatement` upload
state. Workflow status and event reads run this deterministic sync before
returning data. Repeated reads must not duplicate events or reset read/archive
lifecycle state.

Future slices may add deterministic derivation for:

- Stage 1 review required/completed.
- Reconciliation blockers.
- Processing-account blockers.
- Report processing/ready/blocked state.
