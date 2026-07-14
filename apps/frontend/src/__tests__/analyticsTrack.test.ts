import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ANALYTICS_EVENTS,
  sanitizeAnalyticsProps,
  track,
} from "@/lib/analytics";

// The OpenPanel web SDK installs a global `window.op(...)` command queue; the
// wrapper dispatches through it. Stub it so we capture calls without the SDK.
const op = vi.fn();

describe("analytics track wrapper (EPIC-022 AC22.18.2)", () => {
  beforeEach(() => {
    op.mockReset();
    op.mockImplementation(() => {});
    (window as { op?: unknown }).op = op;
  });

  // AC-observability.fe-ia-analytics.1
  it("AC22.18.2 exposes a typed taxonomy of at least six named product events", () => {
    const names = Object.values(ANALYTICS_EVENTS);
    expect(new Set(names).size).toBe(names.length); // unique
    expect(names.length).toBeGreaterThanOrEqual(6);
    expect(names).toEqual(
      expect.arrayContaining([
        "signup",
        "upload_started",
        "upload_succeeded",
        "upload_failed",
        "review_approved",
        "report_generated",
      ]),
    );
  });

  it("AC22.18.2 forwards a sanitized payload to the OpenPanel command queue", () => {
    track(ANALYTICS_EVENTS.UPLOAD_SUCCEEDED, { institution: "dbs", count: 3, ok: true });
    expect(op).toHaveBeenCalledTimes(1);
    expect(op).toHaveBeenCalledWith("track", "upload_succeeded", {
      institution: "dbs",
      count: 3,
      ok: true,
    });
  });

  it("AC22.18.2 defaults to an empty property bag", () => {
    track(ANALYTICS_EVENTS.SIGNUP);
    expect(op).toHaveBeenCalledWith("track", "signup", {});
  });

  it("AC22.18.2 is a no-op when the SDK is not configured (no global queue)", () => {
    (window as { op?: unknown }).op = undefined;
    expect(() => track(ANALYTICS_EVENTS.REPORT_GENERATED, { format: "pdf" })).not.toThrow();
    expect(op).not.toHaveBeenCalled();
  });

  it("AC22.18.2 is non-blocking: never throws when the SDK throws", () => {
    op.mockImplementation(() => {
      throw new Error("SDK boom");
    });
    expect(() => track(ANALYTICS_EVENTS.REPORT_GENERATED, { format: "pdf" })).not.toThrow();
  });

  // AC4 (#1109): PII-bearing props are dropped before they can leave the app.
  it("AC22.18.2 drops PII keys, PII-looking values, and undefined props", () => {
    track(ANALYTICS_EVENTS.UPLOAD_FAILED, {
      email: "user@example.com", // PII key → dropped
      amount: 1234.56, // PII key → dropped
      account_number: "12345678", // PII key → dropped
      contact: "person@example.com", // benign key, email value → dropped
      iban: "DE89370400440532013000", // PII key → dropped
      ref: "987654321098", // long digit run → dropped as account number
      reason: "balance_mismatch", // safe → kept
      retry: false, // safe → kept
      skipped: undefined, // dropped (undefined)
    });
    expect(op).toHaveBeenCalledWith("track", "upload_failed", {
      reason: "balance_mismatch",
      retry: false,
    });
  });

  it("AC22.18.2 sanitizeAnalyticsProps is pure and keeps short numeric ids", () => {
    expect(sanitizeAnalyticsProps({ statement_id: "abc-123", page: 2 })).toEqual({
      statement_id: "abc-123",
      page: 2,
    });
  });

  it("AC22.18.2 keeps opaque UUID ids but still drops pure-digit account strings", () => {
    // UUID statement_ids contain letters, so the all-digit account heuristic must
    // not strip them (a UUID node segment can be 12 consecutive digits).
    expect(
      sanitizeAnalyticsProps({ statement_id: "550e8400-e29b-41d4-a716-446655440000" }),
    ).toEqual({ statement_id: "550e8400-e29b-41d4-a716-446655440000" });
    // A grouped, all-digit value is treated as an account/card number and dropped.
    expect(sanitizeAnalyticsProps({ ref: "1234 5678 9012 3456" })).toEqual({});
  });
});
