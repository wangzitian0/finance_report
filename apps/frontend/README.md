# Finance Report Frontend

Next.js frontend for Finance Report.

## Local Commands

```bash
npm ci
npm run dev
npm run lint
npm test
```

Open <http://localhost:3000> for local development.

## SSOT Links

| Need | Source |
|---|---|
| Frontend architecture and UI patterns | [frontend-patterns.md](../../docs/ssot/frontend-patterns.md) |
| API client rule | [frontend-patterns.md](../../docs/ssot/frontend-patterns.md) |
| Environment contract | [environments.md](../../docs/ssot/environments.md), [.env.example](../../.env.example) |
| API endpoints and schemas | [Generated API reference](../../docs/reference/api.md), `/api/docs` |
| Test policy | [tdd.md](../../docs/ssot/tdd.md), [coverage.md](../../docs/ssot/coverage.md) |

## Product Analytics Event Taxonomy

Product analytics flows through OpenPanel. Page-views are automatic
(`components/Analytics.tsx`); product/funnel events go through the typed
non-blocking, PII-safe wrapper `track(event, props)` in
[`src/lib/analytics.ts`](src/lib/analytics.ts). Only the named events below are
allowed (`ANALYTICS_EVENTS`) — add new events here and in that module rather
than passing arbitrary strings. Event properties must never contain PII (emails,
monetary amounts, account numbers, filenames); the wrapper strips them as a
second line of defense (EPIC-022 AC22.18, #1109).

| Event | Wire name | When | Allowed properties |
|---|---|---|---|
| `SIGNUP` | `signup` | A new user completes registration | _(none)_ |
| `UPLOAD_STARTED` | `upload_started` | A statement upload is initiated | `is_csv` |
| `UPLOAD_SUCCEEDED` | `upload_succeeded` | A statement upload completes | `is_csv` |
| `UPLOAD_FAILED` | `upload_failed` | A statement upload fails | `is_csv`, `error_category` |
| `REVIEW_APPROVED` | `review_approved` | A Stage-1 source review is approved | `statement_id` |
| `REPORT_GENERATED` | `report_generated` | A report/report package is generated | `framework_id` |

Per-environment `OPENPANEL_CLIENT_ID` provisioning (staging/prod) is an infra2
concern, not this repo's.
