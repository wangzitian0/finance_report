import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { useApiQuery } from "@/hooks/useApiQuery";
import { isValidReportDate, packageQuery, packageSnapshotRequest } from "@/lib/reportPackage";
import type {
  AnnualizedIncomeScheduleResponse,
  FrameworkPolicyResult,
  PersonalReportPackageContractResponse,
  PersonalReportPackageNotesResponse,
  PersonalReportPackageReadinessResponse,
  PersonalReportPackageSnapshotResponse,
  PersonalReportPackageSnapshotSummary,
  PersonalReportPackageTraceabilityResponse,
} from "@/lib/types";

export async function generatePackageSnapshot(
  frameworkId: string,
  reportDate: string,
): Promise<PersonalReportPackageSnapshotResponse> {
  return apiFetch<PersonalReportPackageSnapshotResponse>(
    "/api/reports/package/generate",
    {
      method: "POST",
      body: JSON.stringify(packageSnapshotRequest(frameworkId, reportDate)),
    },
  );
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
  const snapshotsQuery = useQuery({
    queryKey: ["report-package", "snapshots"],
    queryFn: ({ signal }) =>
      apiFetch<PersonalReportPackageSnapshotSummary[]>(
        "/api/reports/package/snapshots",
        signal ? { signal } : undefined,
      ),
    enabled: Boolean(contractQuery.data),
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
    packageSnapshots: snapshotsQuery.data ?? [],
    refetchPackageSnapshots: snapshotsQuery.refetch,
    isPackageLoading: packageQueryResult.isLoading,
    error: contractQuery.error?.message ?? packageQueryResult.error?.message ?? snapshotsQuery.error?.message ?? null,
  };
}
