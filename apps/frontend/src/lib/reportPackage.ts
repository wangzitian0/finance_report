/**
 * Pure personal-report-package date and request helpers.
 *
 * The period of a package always comes from the dimension bar of `/reports` (#2621 LC):
 * a request names its start and end. No currency means the base currency of the user.
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

/** Point-in-time sections use the period end. */
export function packagePeriodRequest(endDate: string, startDate: string) {
  const error = reportPeriodError(startDate, endDate);
  if (error) throw new Error(error);
  return { start_date: startDate, end_date: endDate, as_of_date: endDate };
}

export function packageSnapshotRequest(
  frameworkId: import("./api-schema").Schemas["PersonalReportingFrameworkId"],
  reportDate: string,
  startDate: string,
  currency?: string,
) {
  return {
    framework_id: frameworkId,
    ...packagePeriodRequest(reportDate, startDate),
    ...(currency ? { currency } : {}),
    // No include_restricted: the backend body default PACKAGE_INCLUDE_RESTRICTED is the one
    // definition of the package scope (#2645).
  };
}
