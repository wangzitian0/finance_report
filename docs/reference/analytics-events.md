# Product Analytics Event Taxonomy

Product analytics flows through OpenPanel. Page-views are automatic
(`apps/frontend/src/components/Analytics.tsx`); product/funnel events go through
the typed, non-blocking, PII-safe wrapper `track(event, props)` in
[`apps/frontend/src/lib/analytics.ts`](../../apps/frontend/src/lib/analytics.ts).

Only the named events below are allowed (`ANALYTICS_EVENTS`) — add new events to
that module and this doc rather than passing arbitrary strings (EPIC-022
AC22.18, #1109).

## Events

| Event | Wire name | When | Allowed properties |
|---|---|---|---|
| `SIGNUP` | `signup` | A new user completes registration | _(none)_ |
| `UPLOAD_STARTED` | `upload_started` | A statement upload is initiated | `is_csv` |
| `UPLOAD_SUCCEEDED` | `upload_succeeded` | A statement upload completes | `is_csv` |
| `UPLOAD_FAILED` | `upload_failed` | A statement upload fails | `is_csv`, `error_category` |
| `REVIEW_APPROVED` | `review_approved` | A Stage-1 source review is approved | `statement_id` |
| `REPORT_GENERATED` | `report_generated` | A report / report package is generated | `framework_id` |

## PII rules

Event properties must never carry PII. The wrapper's `sanitizeAnalyticsProps`
guard drops, before any event leaves the app:

- keys naming a PII field (emails, monetary `amount`/`balance`, `account_number`
  and similar, plus obvious secrets/tokens);
- values that look like an email address;
- values that are entirely digits (optionally grouped by spaces/dashes) and long
  enough to be an account/card number — opaque alphanumeric ids such as UUID
  `statement_id`s are preserved because they contain letters.

The guard is a second line of defense, **not** a license to pass PII: callers
must still avoid sending raw emails, amounts, account numbers, or **filenames**
(the guard does not detect filenames). Keep props to safe, low-cardinality
context.

## Provisioning

Per-environment `OPENPANEL_CLIENT_ID` provisioning (staging/prod) is an infra2
concern (see #1045 / Infra-014), not this repo's.
