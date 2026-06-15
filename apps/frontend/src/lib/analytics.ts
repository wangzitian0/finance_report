/**
 * Product-analytics event wrapper (EPIC-022 AC22.18, #1109).
 *
 * A small typed layer over the OpenPanel SDK `track()` that guarantees the two
 * safety contracts the page-view wrapper already gives us (see Analytics.tsx):
 *
 * 1. Non-blocking — `track()` never throws. Any SDK error (including the SDK
 *    not being initialized because no client id is configured) is swallowed, so
 *    analytics can never affect the app or a user action.
 * 2. PII guard — event properties are sanitized before they leave the app:
 *    emails, monetary amounts, and account numbers are dropped so product
 *    analytics never receives personally identifiable or financial data.
 *
 * The canonical event taxonomy lives in `ANALYTICS_EVENTS` below (and is
 * documented in apps/frontend/README.md). Only these named events are allowed,
 * which keeps the funnel legible and prevents ad-hoc event sprawl.
 */

/**
 * The product funnel events instrumented in the app. Values are the wire names
 * sent to OpenPanel. Add new events here (and to the README taxonomy) rather
 * than passing arbitrary strings to `track()`.
 */
export const ANALYTICS_EVENTS = {
  /** A new user completed signup. */
  SIGNUP: "signup",
  /** A statement upload was initiated by the user. */
  UPLOAD_STARTED: "upload_started",
  /** A statement upload completed successfully. */
  UPLOAD_SUCCEEDED: "upload_succeeded",
  /** A statement upload failed. */
  UPLOAD_FAILED: "upload_failed",
  /** A Stage-1 source review was approved. */
  REVIEW_APPROVED: "review_approved",
  /** A report / report package was generated. */
  REPORT_GENERATED: "report_generated",
} as const;

export type AnalyticsEvent = (typeof ANALYTICS_EVENTS)[keyof typeof ANALYTICS_EVENTS];

/** Property values allowed on an analytics event (no nested objects). */
export type AnalyticsPropValue = string | number | boolean | null | undefined;
export type AnalyticsProps = Record<string, AnalyticsPropValue>;

/**
 * Keys that must never be reported, regardless of value. Targets the three PII
 * classes called out in #1109 — emails, monetary amounts, and account numbers —
 * plus obvious secrets. Intentionally narrow (does not blanket-drop "name") so
 * legitimate funnel context still flows.
 */
const PII_KEY_PATTERN =
  /(e[-_]?mail|amount|balance|account[-_]?number|acct|iban|card[-_]?number|ssn|phone|password|secret|token)/i;

/** A value that looks like an email address is dropped even under a benign key. */
const EMAIL_VALUE_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * Treat a value as an account/card number only when it is *entirely* digits
 * (optionally grouped by spaces or dashes) and long. This deliberately preserves
 * opaque alphanumeric ids — e.g. UUID `statement_id`s, which contain letters —
 * so legitimate funnel context is not stripped, while real account/card strings
 * (`12345678`, `1234 5678 9012 3456`) are still dropped.
 */
function isAccountNumberLike(value: string): boolean {
  const compact = value.replace(/[\s-]/g, "");
  return /^\d{8,}$/.test(compact);
}

function isPiiValue(value: AnalyticsPropValue): boolean {
  if (typeof value !== "string") return false;
  return EMAIL_VALUE_PATTERN.test(value) || isAccountNumberLike(value);
}

/**
 * Strip PII from event properties: drop keys that name a PII field, values that
 * look like PII, and any `undefined` values. Returns a new object.
 */
export function sanitizeAnalyticsProps(props: AnalyticsProps): AnalyticsProps {
  const safe: AnalyticsProps = {};
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined) continue;
    if (PII_KEY_PATTERN.test(key)) continue;
    if (isPiiValue(value)) continue;
    safe[key] = value;
  }
  return safe;
}

/**
 * Track a named product event. Non-blocking and PII-safe (see module docs).
 *
 * Dispatches through the OpenPanel web SDK's global `window.op(...)` command
 * queue (installed by `OpenPanelComponent`). When no client id is configured the
 * global is never installed, so `track()` is a complete no-op — the same
 * config-gate the page-view wrapper relies on.
 */
export function track(event: AnalyticsEvent, props: AnalyticsProps = {}): void {
  try {
    const op =
      typeof window !== "undefined"
        ? (window as unknown as { op?: (...args: unknown[]) => void }).op
        : undefined;
    op?.("track", event, sanitizeAnalyticsProps(props));
  } catch {
    // Analytics must never affect the app: swallow any SDK error.
  }
}
