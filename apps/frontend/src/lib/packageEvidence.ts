/**
 * Evidence lists of one package document: the details of each traceability line and the input
 * manifest entries (#2583 S8).
 *
 * A preview carries only their counts. The page loads a list page by page when the user opens
 * it. A frozen snapshot stores the complete lists, so the page slices them without a request.
 * Each page request reads the package contribution set again (about 0.3 s of backend CPU at
 * one year of data), so a page holds 200 entries and every reader shares one cache entry.
 */

import { infiniteQueryOptions, type QueryClient } from "@tanstack/react-query";

import { apiOperation } from "@/lib/api-client";
import { anchorFromIdentifiers, type LineageAnchor } from "@/lib/lineage";
import { SHARED_STALE_MS } from "@/lib/sharedQueries";
import type {
  PersonalReportPackageDocument,
  PersonalReportPackageLineDetailsPage,
  PersonalReportPackageManifestEntriesPage,
  PersonalReportPackageTraceabilityAnchorName,
  PersonalReportPackageTraceabilityLineSummary,
} from "@/lib/types";

/** Page size of the evidence lists. The backend maximum is 500. */
export const PACKAGE_EVIDENCE_PAGE_SIZE = 200;

export const TRACEABILITY_ANCHORS: readonly PersonalReportPackageTraceabilityAnchorName[] = [
  "source_anchor",
  "ledger_anchor",
];

/** The query key prefix of one document's evidence. Equal documents give equal keys. */
export function packageEvidenceKey(document: PersonalReportPackageDocument) {
  if (document.frozen_evidence) {
    return ["report-package", "evidence", "snapshot", document.frozen_evidence.snapshot_id] as const;
  }
  const { start_date, end_date, as_of_date, currency } = document.context;
  return ["report-package", "evidence", "preview", start_date, end_date, as_of_date, currency] as const;
}

function previewPeriod(document: PersonalReportPackageDocument) {
  const { start_date, end_date, as_of_date, currency } = document.context;
  return { start_date, end_date, as_of_date, currency };
}

function nextOffset(page: { offset: number; limit: number; total: number }): number | undefined {
  const next = page.offset + page.limit;
  return next < page.total ? next : undefined;
}

export async function fetchLineDetailsPage(
  document: PersonalReportPackageDocument,
  lineId: string,
  anchor: PersonalReportPackageTraceabilityAnchorName,
  offset: number,
  signal?: AbortSignal,
): Promise<PersonalReportPackageLineDetailsPage> {
  const limit = PACKAGE_EVIDENCE_PAGE_SIZE;
  const frozen = document.frozen_evidence;
  if (frozen) {
    const line = frozen.traceability_appendix.lines.find((item) => item.line_id === lineId);
    const details = line?.[anchor].details ?? [];
    return {
      line_id: lineId,
      anchor,
      total: details.length,
      limit,
      offset,
      details: details.slice(offset, offset + limit),
    };
  }
  return apiOperation("list_personal_report_package_line_details_reports_package_line_details_get", {
    query: { ...previewPeriod(document), line_id: lineId, anchor, limit, offset },
    signal,
  });
}

export async function fetchManifestEntriesPage(
  document: PersonalReportPackageDocument,
  offset: number,
  signal?: AbortSignal,
): Promise<PersonalReportPackageManifestEntriesPage> {
  const limit = PACKAGE_EVIDENCE_PAGE_SIZE;
  const frozen = document.frozen_evidence;
  if (frozen) {
    return {
      total: frozen.input_manifest.length,
      limit,
      offset,
      entries: frozen.input_manifest.slice(offset, offset + limit),
    };
  }
  return apiOperation("list_personal_report_package_manifest_entries_reports_package_manifest_entries_get", {
    query: { ...previewPeriod(document), limit, offset },
    signal,
  });
}

/** The one cache entry of the details of a line anchor: the list and the lineage trace share it. */
export function lineDetailsQueryOptions(
  document: PersonalReportPackageDocument,
  lineId: string,
  anchor: PersonalReportPackageTraceabilityAnchorName,
) {
  return infiniteQueryOptions({
    queryKey: [...packageEvidenceKey(document), "line-details", lineId, anchor] as const,
    queryFn: ({ pageParam, signal }) => fetchLineDetailsPage(document, lineId, anchor, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    staleTime: SHARED_STALE_MS,
  });
}

export function manifestEntriesQueryOptions(document: PersonalReportPackageDocument) {
  return infiniteQueryOptions({
    queryKey: [...packageEvidenceKey(document), "manifest-entries"] as const,
    queryFn: ({ pageParam, signal }) => fetchManifestEntriesPage(document, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: nextOffset,
    staleTime: SHARED_STALE_MS,
  });
}

/**
 * The graph anchor of one line: the first graph-compatible identifier of the first page of the
 * ledger anchor, then of the source anchor. An anchor without details issues no request, and a
 * page that the open line already loaded comes from the cache.
 */
export async function loadLineageAnchorForLine(
  queryClient: QueryClient,
  document: PersonalReportPackageDocument,
  line: PersonalReportPackageTraceabilityLineSummary,
): Promise<LineageAnchor | null> {
  for (const anchor of ["ledger_anchor", "source_anchor"] as const) {
    if (!line[anchor].detail_count) continue;
    const data = await queryClient.fetchInfiniteQuery(lineDetailsQueryOptions(document, line.line_id, anchor));
    const found = anchorFromIdentifiers(
      (data.pages[0]?.details ?? []).map((detail) => String(detail.identifier ?? "")),
    );
    if (found) return found;
  }
  return null;
}
