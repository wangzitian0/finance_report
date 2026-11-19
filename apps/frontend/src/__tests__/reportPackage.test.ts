import { describe, expect, it } from "vitest";
import { isValidReportDate, packagePeriodRequest, packageSnapshotRequest } from "@/lib/reportPackage";

describe("lib/reportPackage", () => {
  it("AC-reporting.package-document.12 validates periods and builds requests", () => {
    expect(packagePeriodRequest("2025-03-31", "2025-03-01")).toEqual({ start_date: "2025-03-01", end_date: "2025-03-31", as_of_date: "2025-03-31" });
    expect(packagePeriodRequest("2025-03-01", "2025-03-01").start_date).toBe("2025-03-01");
    for (const [end, start, err] of [["2025-03-31", "2025-04-01", /on or before/], ["", "2025-03-01", /valid/], ["2025-03-31", "2025-02-30", /valid/]] as const) {
      expect(() => packagePeriodRequest(end, start)).toThrow(err);
    }
  });
  it.each([["2026-02-28", true], ["2024-02-29", true], ["2026-02-29", false], ["2026-13-01", false], ["not-a-date", false], ["", false]])(
    "isValidReportDate(%s) === %s",
    (d, ok) => expect(isValidReportDate(d)).toBe(ok),
  );
  it("packageSnapshotRequest omits absent currency and scope", () => {
    const req = packageSnapshotRequest("personal_us_gaap_like", "2026-06-15", "2025-06-16");
    expect(req).toEqual({ framework_id: "personal_us_gaap_like", start_date: "2025-06-16", end_date: "2026-06-15", as_of_date: "2026-06-15" });
    expect(req).not.toHaveProperty("include_restricted");
    expect(packageSnapshotRequest("personal_hkfrs_like", "2026-01-01", "2025-01-01", "USD").currency).toBe("USD");
  });
}); // AC-reporting.net-worth-scope.16
