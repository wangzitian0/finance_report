import { useEffect, useState } from "react";
import {
  queryOptions,
  useQuery,
  type QueryClient,
} from "@tanstack/react-query";

import { apiOperation } from "@/lib/api-client";
import {
  packagePeriodRequest,
  reportPeriodError,
  packageSnapshotRequest,
} from "@/lib/reportPackage";
import { SHARED_STALE_MS } from "@/lib/sharedQueries";
import {
  normalizePersonalReportPackagePreview,
  normalizePersonalReportPackageSnapshot,
} from "@/lib/types";
import type {
  PersonalReportPackageDocument,
  PersonalReportPackageContractResponse,
  PersonalReportPackageSnapshotViewModel,
  PersonalReportingFrameworkId,
} from "@/lib/types";

export async function generatePackageSnapshot(
  frameworkId: PersonalReportingFrameworkId,
  reportDate: string,
  startDate: string,
  currency?: string,
): Promise<PersonalReportPackageSnapshotViewModel> {
  const snapshot = await apiOperation(
    "generate_personal_report_package_snapshot_reports_package_generate_post",
    { body: packageSnapshotRequest(frameworkId, reportDate, startDate, currency) },
  );
  return normalizePersonalReportPackageSnapshot(snapshot);
}

async function fetchPersonalReportPackage(
  frameworkId: PersonalReportingFrameworkId | null,
  reportDate: string,
  startDate: string,
  currency: string | undefined,
  signal?: AbortSignal,
): Promise<PersonalReportPackageDocument> {
  const document = await apiOperation(
    "preview_personal_report_package_reports_package_get",
    {
      query: {
        framework_id: frameworkId ?? undefined,
        ...packagePeriodRequest(reportDate, startDate),
        currency,
      },
      signal,
    },
  );
  return normalizePersonalReportPackagePreview(document);
}

export interface PersonalReportPackageQueryParams {
  frameworkId: PersonalReportingFrameworkId | null;
  reportDate: string;
  startDate: string;
  /** No currency means the base currency of the user. */
  currency?: string;
}

/**
 * The preview of the personal report package (about 60 KB for a year of data, #2583 S8, S11).
 *
 * The Package tab and the Overview tab of `/reports` read it through this one query, so they share
 * one cache entry. A date change keeps the previous document on screen while the next one loads
 * (`isPlaceholderData`). A change of framework or currency does not: another framework gives
 * another document, and the page must never show it as the document of the new selection.
 */
export function personalReportPackageQuery({
  frameworkId,
  reportDate,
  startDate,
  currency,
}: PersonalReportPackageQueryParams) {
  return queryOptions({
    queryKey: [
      "report-package",
      "framework",
      frameworkId,
      reportDate,
      startDate,
      currency,
    ] as const,
    queryFn: ({ signal }) =>
      fetchPersonalReportPackage(frameworkId, reportDate, startDate, currency, signal),
    staleTime: SHARED_STALE_MS,
    // A preview is large. Drop an unused one after one minute.
    gcTime: SHARED_STALE_MS,
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[2] === frameworkId &&
      previousQuery?.queryKey[5] === currency
        ? previous
        : undefined,
  });
}

/**
 * After a package snapshot is generated: read the snapshot list again, and mark the cached
 * previews stale. The open page keeps its preview, so it does not read the preview again.
 */
export async function invalidateReportPackageQueries(
  queryClient: QueryClient,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["report-package", "snapshots"] }),
    queryClient.invalidateQueries({
      queryKey: ["report-package", "framework"],
      refetchType: "none",
    }),
  ]);
}

export function usePersonalReportPackage(
  selectedFrameworkId: PersonalReportingFrameworkId | null,
  reportDate: string,
  selectedSnapshotId: string | null,
  startDate: string,
  currency?: string,
  /** False while the period can still move (`ReportFilters.ready`): the preview waits. */
  ready = true,
) {
  const [lastContract, setLastContract] =
    useState<PersonalReportPackageContractResponse | null>(null);
  const packageQueryResult = useQuery({
    ...personalReportPackageQuery({
      frameworkId: selectedFrameworkId,
      reportDate,
      startDate,
      currency,
    }),
    enabled: ready && !reportPeriodError(startDate, reportDate) && !selectedSnapshotId,
  });
  const snapshotsQuery = useQuery({
    queryKey: ["report-package", "snapshots"],
    queryFn: ({ signal }) =>
      apiOperation(
        "list_personal_report_package_snapshots_reports_package_snapshots_get",
        { signal },
      ),
    staleTime: SHARED_STALE_MS,
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
    staleTime: SHARED_STALE_MS,
  });
  const selectedSnapshot = selectedSnapshotQuery.data ?? null;
  const document =
    selectedSnapshot?.document ?? packageQueryResult.data ?? null;
  // True while `document` is the previous period's preview and the requested one loads.
  const isPackageRefreshing =
    !selectedSnapshot && packageQueryResult.isPlaceholderData;

  useEffect(() => {
    if (document?.contract) setLastContract(document.contract);
  }, [document?.contract]);

  return {
    // The shell uses the last valid contract while a replacement document is
    // loading. A document of another period or framework is never presented as
    // output for the new selection: `isPackageRefreshing` marks the period case.
    contract: document?.contract ?? lastContract,
    document,
    selectedSnapshot,
    packageSnapshots: snapshotsQuery.data ?? [],
    isPackageRefreshing,
    isPackageLoading:
      (!ready && !selectedSnapshotId) || packageQueryResult.isLoading || selectedSnapshotQuery.isLoading,
    error:
      packageQueryResult.error?.message ??
      selectedSnapshotQuery.error?.message ??
      snapshotsQuery.error?.message ??
      null,
  };
}
