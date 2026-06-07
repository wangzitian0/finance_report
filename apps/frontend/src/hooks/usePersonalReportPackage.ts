import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import type {
  AnnualizedIncomeScheduleResponse,
  FrameworkPolicyResult,
  PersonalReportPackageContractResponse,
  PersonalReportPackageNotesResponse,
  PersonalReportPackageReadinessResponse,
  PersonalReportPackageTraceabilityResponse,
} from "@/lib/types";

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

export function reportPeriodStart(reportDate: string): string {
  const [year, month, day] = reportDate.split("-").map(Number);
  if (!year || !month || !day) return reportDate;
  const previousYear = year - 1;
  const lastDayOfMonth = new Date(Date.UTC(previousYear, month, 0)).getUTCDate();
  const clampedDay = Math.min(day, lastDayOfMonth);
  return `${previousYear}-${String(month).padStart(2, "0")}-${String(clampedDay).padStart(2, "0")}`;
}

function packageQuery(reportDate: string, frameworkId?: string): string {
  const params = new URLSearchParams(frameworkId ? { framework_id: frameworkId } : undefined);
  params.set("start_date", reportPeriodStart(reportDate));
  params.set("end_date", reportDate);
  params.set("as_of_date", reportDate);
  return `?${params.toString()}`;
}

type PersonalReportPackageData = {
  readiness: PersonalReportPackageReadinessResponse;
  annualizedSchedule: AnnualizedIncomeScheduleResponse;
  packageNotes: PersonalReportPackageNotesResponse;
  traceabilityAppendix: PersonalReportPackageTraceabilityResponse;
  frameworkPolicy: FrameworkPolicyResult;
};

async function fetchPersonalReportPackage(
  frameworkId: string,
  reportDate: string,
  signal?: AbortSignal,
): Promise<PersonalReportPackageData> {
  const query = packageQuery(reportDate, frameworkId);
  const sectionQuery = packageQuery(reportDate);
  const requestOptions = signal ? { signal } : undefined;
  const get = <TResponse>(path: string) => apiFetch<TResponse>(path, requestOptions);
  const [
    readiness,
    frameworkPolicy,
    annualizedSchedule,
    packageNotes,
    traceabilityAppendix,
  ] = await Promise.all([
    get<PersonalReportPackageReadinessResponse>(`/api/reports/package/readiness${query}`),
    get<FrameworkPolicyResult>(`/api/reports/package/framework-policy${query}`),
    get<AnnualizedIncomeScheduleResponse>(`/api/reports/package/annualized-income-schedule${sectionQuery}`),
    get<PersonalReportPackageNotesResponse>("/api/reports/package/notes"),
    get<PersonalReportPackageTraceabilityResponse>(`/api/reports/package/traceability${sectionQuery}`),
  ]);

  return {
    readiness,
    annualizedSchedule,
    packageNotes,
    traceabilityAppendix,
    frameworkPolicy,
  };
}

export function usePersonalReportPackage(
  selectedFrameworkId: string | null,
  reportDate: string,
) {
  const contractQuery = useApiQuery<PersonalReportPackageContractResponse>(
    ["report-package", "contract"],
    "/api/reports/package/contract",
  );
  const packageQueryResult = useQuery({
    queryKey: ["report-package", "framework", selectedFrameworkId, reportDate],
    queryFn: ({ signal }) => fetchPersonalReportPackage(selectedFrameworkId ?? "", reportDate, signal),
    enabled: Boolean(selectedFrameworkId && isValidReportDate(reportDate)),
    gcTime: 0,
    staleTime: 0,
  });
  const packageData = packageQueryResult.data ?? null;

  return {
    contract: contractQuery.data ?? null,
    readiness: packageData?.readiness ?? null,
    frameworkPolicy: packageData?.frameworkPolicy ?? null,
    annualizedSchedule: packageData?.annualizedSchedule ?? null,
    packageNotes: packageData?.packageNotes ?? null,
    traceabilityAppendix: packageData?.traceabilityAppendix ?? null,
    isPackageLoading: packageQueryResult.isLoading,
    error: contractQuery.error?.message ?? packageQueryResult.error?.message ?? null,
  };
}
