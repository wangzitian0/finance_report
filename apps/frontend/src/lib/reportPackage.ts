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
  startDate = reportPeriodStart(reportDate),
) {
  return {
    framework_id: frameworkId,
    ...packagePeriodRequest(reportDate, startDate),
    currency,
    include_restricted: false,
  };
}

export function reportPeriodError(
  startDate: string,
  endDate: string,
): string | null {
  if (!isValidReportDate(startDate) || !isValidReportDate(endDate)) {
    return "Enter a valid period start and end date.";
  }
  return startDate > endDate
    ? "Period start must be on or before period end."
    : null;
}

/** Point-in-time sections use the period end; defaults preserve the existing year window. */
export function packagePeriodRequest(
  endDate: string,
  startDate = reportPeriodStart(endDate),
) {
  const error = reportPeriodError(startDate, endDate);
  if (error) throw new Error(error);
  return { start_date: startDate, end_date: endDate, as_of_date: endDate };
}

/** `?start_date=...&end_date=...&as_of_date=...[&framework_id=...]` for a package-scoped GET. */
export function packageQuery(
  reportDate: string,
  frameworkId?: string,
  startDate = reportPeriodStart(reportDate),
): string {
  const params = new URLSearchParams(
    frameworkId ? { framework_id: frameworkId } : undefined,
  );
  Object.entries(packagePeriodRequest(reportDate, startDate)).forEach(
    ([key, value]) => params.set(key, value),
  );
  return `?${params.toString()}`;
}
