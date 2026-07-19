import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api";
import { isValidReportDate, packageQuery, packageSnapshotRequest } from "@/lib/reportPackage";
import type {
  PersonalReportPackageDocument,
  PersonalReportPackageContractResponse,
  PersonalReportPackageSnapshotResponse,
  PersonalReportPackageSnapshotSummary,
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

async function fetchPersonalReportPackage(
  frameworkId: string | null,
  reportDate: string,
  signal?: AbortSignal,
): Promise<PersonalReportPackageDocument> {
  const query = packageQuery(reportDate, frameworkId ?? undefined);
  return apiFetch<PersonalReportPackageDocument>(
    `/api/reports/package${query}`,
    signal ? { signal } : undefined,
  );
}

export function usePersonalReportPackage(
  selectedFrameworkId: string | null,
  reportDate: string,
  selectedSnapshotId: string | null,
) {
  const [lastContract, setLastContract] = useState<PersonalReportPackageContractResponse | null>(null);
  const packageQueryResult = useQuery({
    queryKey: ["report-package", "framework", selectedFrameworkId, reportDate],
    queryFn: ({ signal }) => fetchPersonalReportPackage(selectedFrameworkId, reportDate, signal),
    enabled: Boolean(isValidReportDate(reportDate) && !selectedSnapshotId),
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
    staleTime: 0,
  });
  const selectedSnapshotQuery = useQuery({
    queryKey: ["report-package", "snapshot", selectedSnapshotId],
    queryFn: ({ signal }) =>
      apiFetch<PersonalReportPackageSnapshotResponse>(
        `/api/reports/package/snapshots/${selectedSnapshotId}`,
        signal ? { signal } : undefined,
      ),
    enabled: Boolean(selectedSnapshotId),
    staleTime: 0,
  });
  const selectedSnapshot = selectedSnapshotQuery.data ?? null;
  const document = selectedSnapshot?.document ?? packageQueryResult.data ?? null;

  useEffect(() => {
    if (document?.contract) setLastContract(document.contract);
  }, [document?.contract]);

  return {
    // The shell uses the last valid contract while a replacement document is
    // loading. It never presents a stale document as output for the new date
    // or framework.
    contract: document?.contract ?? lastContract,
    document,
    selectedSnapshot,
    packageSnapshots: snapshotsQuery.data ?? [],
    refetchPackageSnapshots: snapshotsQuery.refetch,
    isPackageLoading: packageQueryResult.isLoading || selectedSnapshotQuery.isLoading,
    error:
      packageQueryResult.error?.message ??
      selectedSnapshotQuery.error?.message ??
      snapshotsQuery.error?.message ??
      null,
  };
}
