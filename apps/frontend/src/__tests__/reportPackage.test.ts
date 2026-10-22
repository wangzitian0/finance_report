import { describe, it, expect } from "vitest";

import {
  isValidReportDate,
  packageSnapshotRequest,
  packagePeriodRequest,
} from "@/lib/reportPackage";

describe("lib/reportPackage", () => {
  it("AC-reporting.package-document.12 uses explicit periods consistently and rejects invalid requests", () => {
    expect(packagePeriodRequest("2025-03-31", "2025-03-01")).toEqual({
      start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-03-31",
    });
    expect(packagePeriodRequest("2025-03-01", "2025-03-01").start_date).toBe("2025-03-01");
    expect(() => packagePeriodRequest("2025-03-31", "2025-04-01")).toThrow(/on or before/);
    expect(() => packagePeriodRequest("", "2025-03-01")).toThrow(/valid/);
    expect(() => packagePeriodRequest("2025-03-31", "2025-02-30")).toThrow(/valid/);
  });
  it("isValidReportDate accepts real calendar dates and rejects malformed/impossible ones", () => {
    expect(isValidReportDate("2026-02-28")).toBe(true);
    expect(isValidReportDate("2024-02-29")).toBe(true); // leap year
    expect(isValidReportDate("2026-02-29")).toBe(false); // not a leap year
    expect(isValidReportDate("2026-13-01")).toBe(false);
    expect(isValidReportDate("not-a-date")).toBe(false);
    expect(isValidReportDate("")).toBe(false);
  });

  it("packageSnapshotRequest builds the generate-snapshot request body and omits an absent currency", () => {
    expect(
      packageSnapshotRequest("personal_us_gaap_like", "2026-06-15", "2025-06-16"),
    ).toEqual({
      framework_id: "personal_us_gaap_like",
      start_date: "2025-06-16",
      end_date: "2026-06-15",
      as_of_date: "2026-06-15",
      include_restricted: false,
    });
    expect(
      packageSnapshotRequest("personal_hkfrs_like", "2026-01-01", "2025-01-01", "USD")
        .currency,
    ).toBe("USD");
  });
});
