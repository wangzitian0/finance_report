import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiOperation } from "@/lib/api-client";
import {
  isValidReportDate,
  packageSnapshotRequest,
  reportPeriodStart,
} from "@/lib/reportPackage";
import {
  normalizePersonalReportPackageDocument,
  normalizePersonalReportPackageSnapshot,
} from "@/lib/types";
import type {
  PersonalReportPackageDocument,
  PersonalReportPackageContractResponse,
  PersonalReportPackageSnapshotResponse,
  PersonalReportPackageSnapshotSummary,
  PersonalReportingFrameworkId,
} from "@/lib/types";

export async function generatePackageSnapshot(
  frameworkId: PersonalReportingFrameworkId,
  reportDate: string,
): Promise<PersonalReportPackageSnapshotResponse> {
  const snapshot = await apiOperation(
    "generate_personal_report_package_snapshot_reports_package_generate_post",
    {
      body: packageSnapshotRequest(frameworkId, reportDate),
    },
  );
  return normalizePersonalReportPackageSnapshot(snapshot);
}

async function fetchPersonalReportPackage(
  frameworkId: PersonalReportingFrameworkId | null,
  reportDate: string,
  signal?: AbortSignal,
): Promise<PersonalReportPackageDocument> {
  const document = await apiOperation(
    "preview_personal_report_package_reports_package_get",
    {
      query: {
        framework_id: frameworkId ?? undefined,
        start_date: reportPeriodStart(reportDate),
        end_date: reportDate,
        as_of_date: reportDate,
      },
      signal,
    },
  );
  return normalizePersonalReportPackageDocument(document);
}

export function usePersonalReportPackage(
  selectedFrameworkId: PersonalReportingFrameworkId | null,
  reportDate: string,
  selectedSnapshotId: string | null,
) {
  const [lastContract, setLastContract] =
    useState<PersonalReportPackageContractResponse | null>(null);
  const packageQueryResult = useQuery({
    queryKey: ["report-package", "framework", selectedFrameworkId, reportDate],
    queryFn: ({ signal }) =>
      fetchPersonalReportPackage(selectedFrameworkId, reportDate, signal),
    enabled: Boolean(isValidReportDate(reportDate) && !selectedSnapshotId),
    gcTime: 0,
    staleTime: 0,
  });
  const snapshotsQuery = useQuery({
    queryKey: ["report-package", "snapshots"],
    queryFn: ({ signal }) =>
      apiOperation(
        "list_personal_report_package_snapshots_reports_package_snapshots_get",
        { signal },
      ),
    staleTime: 0,
  });
  const selectedSnapshotQuery = useQuery({
    queryKey: ["report-package", "snapshot", selectedSnapshotId],
    queryFn: async ({ signal }) =>
      normalizePersonalReportPackageSnapshot(
        await apiOperation(
          "get_personal_report_package_snapshot_reports_package_snapshots__snapshot_id__get",
          {
            path: { snapshot_id: selectedSnapshotId! },
            signal,
          },
        ),
      ),
    enabled: Boolean(selectedSnapshotId),
    staleTime: 0,
  });
  const selectedSnapshot = selectedSnapshotQuery.data ?? null;
  const document =
    selectedSnapshot?.document ?? packageQueryResult.data ?? null;

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
    isPackageLoading:
      packageQueryResult.isLoading || selectedSnapshotQuery.isLoading,
    error:
      packageQueryResult.error?.message ??
      selectedSnapshotQuery.error?.message ??
      snapshotsQuery.error?.message ??
      null,
  };
}
