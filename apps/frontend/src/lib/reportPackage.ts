/**
 * Pure personal-report-package date/query helpers (was hand-declared inside
 * hooks/usePersonalReportPackage.ts, with reports/page.tsx unable to reuse
 * the unexported `packageQuery` and reimplementing it locally as
 * `packageReadinessQuery` instead, #1868 S5 PR-C).
 */

const REPORT_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function isValidReportDate(reportDate: string): boolean {
  if (!REPORT_DATE_PATTERN.test(reportDate)) return false;
  const [year, month, day] = reportDate.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

/** One year before `reportDate`, clamped to the last valid day of that month. */
export function reportPeriodStart(reportDate: string): string {
  const [year, month, day] = reportDate.split("-").map(Number);
  if (!year || !month || !day) return reportDate;
  const previousYear = year - 1;
  const lastDayOfMonth = new Date(
    Date.UTC(previousYear, month, 0),
  ).getUTCDate();
  const clampedDay = Math.min(day, lastDayOfMonth);
  return `${previousYear}-${String(month).padStart(2, "0")}-${String(clampedDay).padStart(2, "0")}`;
}

export function packageSnapshotRequest(
  frameworkId: import("./api-schema").Schemas["PersonalReportingFrameworkId"],
  reportDate: string,
  currency = "SGD",
) {
  return {
    framework_id: frameworkId,
    start_date: reportPeriodStart(reportDate),
    end_date: reportDate,
    as_of_date: reportDate,
    currency,
    include_restricted: false,
  };
}

/** `?start_date=...&end_date=...&as_of_date=...[&framework_id=...]` for a package-scoped GET. */
export function packageQuery(reportDate: string, frameworkId?: string): string {
  const params = new URLSearchParams(
    frameworkId ? { framework_id: frameworkId } : undefined,
  );
  params.set("start_date", reportPeriodStart(reportDate));
  params.set("end_date", reportDate);
  params.set("as_of_date", reportDate);
  return `?${params.toString()}`;
}
