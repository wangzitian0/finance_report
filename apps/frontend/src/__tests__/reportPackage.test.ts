import { describe, it, expect } from "vitest";

import {
  isValidReportDate,
  packageQuery,
  packageSnapshotRequest,
  reportPeriodStart,
} from "@/lib/reportPackage";

// Single-homed from hooks/usePersonalReportPackage.ts, with reports/page.tsx's
// hand-rolled packageReadinessQuery deleted in favor of the now-exported
// packageQuery (#1868 S5 PR-C).
describe("lib/reportPackage", () => {
  it("isValidReportDate accepts real calendar dates and rejects malformed/impossible ones", () => {
    expect(isValidReportDate("2026-02-28")).toBe(true);
    expect(isValidReportDate("2024-02-29")).toBe(true); // leap year
    expect(isValidReportDate("2026-02-29")).toBe(false); // not a leap year
    expect(isValidReportDate("2026-13-01")).toBe(false);
    expect(isValidReportDate("not-a-date")).toBe(false);
    expect(isValidReportDate("")).toBe(false);
  });

  it("reportPeriodStart shifts back one year, clamping Feb 29 to Feb 28", () => {
    expect(reportPeriodStart("2026-06-15")).toBe("2025-06-15");
    expect(reportPeriodStart("2024-02-29")).toBe("2023-02-28");
    expect(reportPeriodStart("")).toBe("");
  });

  it("packageSnapshotRequest builds the generate-snapshot request body", () => {
    expect(
      packageSnapshotRequest("personal_us_gaap_like", "2026-06-15"),
    ).toEqual({
      framework_id: "personal_us_gaap_like",
      start_date: "2025-06-15",
      end_date: "2026-06-15",
      as_of_date: "2026-06-15",
      currency: "SGD",
      include_restricted: false,
    });
    expect(
      packageSnapshotRequest("personal_hkfrs_like", "2026-01-01", "USD")
        .currency,
    ).toBe("USD");
  });

  it("packageQuery builds the package-scoped query string, with and without a framework id", () => {
    expect(packageQuery("2026-06-15", "personal_us_gaap_like")).toBe(
      "?framework_id=personal_us_gaap_like&start_date=2025-06-15&end_date=2026-06-15&as_of_date=2026-06-15",
    );
    expect(packageQuery("2026-06-15")).toBe(
      "?start_date=2025-06-15&end_date=2026-06-15&as_of_date=2026-06-15",
    );
  });
});
