"use client";

import { useMemo } from "react";

import { useApiQuery } from "@/hooks/useApiQuery";
import { buildAttentionItems, type AttentionItem } from "@/lib/attention";
import {
  PROCESSING_PENDING_QUERY_KEY,
  RECONCILIATION_STATS_QUERY_KEY,
  SHARED_STALE_MS,
  STATEMENTS_LIST_QUERY_KEY,
  UNMATCHED_FIRST_QUERY_KEY,
  UNMATCHED_FIRST_REQUEST,
} from "@/lib/sharedQueries";

export interface AttentionQueue {
  /** The queue, lowest confidence first. Null until each source settles. */
  items: AttentionItem[] | null;
  /** True when a source failed. The items then hold only the sources that loaded. */
  failed: boolean;
  /** The message of a failed source. Null while a failed source fetches again. */
  error: string | null;
  /** Fetch the failed sources again. */
  retry: () => void;
}

/**
 * The confidence queue of the items that need the user (#2646).
 *
 * Home, the `/audit` tabs and the Needs Confirmation list read this one hook, so they show the
 * same count and the same first item. The sources use the shared query keys (#2583 S4). The newest
 * unmatched row loads only when the statistics report an unmatched row: its description names the
 * unmatched item. When that row fails to load, the item keeps its count title.
 */
export function useAttentionQueue(): AttentionQueue {
  const statements = useApiQuery(STATEMENTS_LIST_QUERY_KEY, "list_statements_statements_get", {}, { staleTime: SHARED_STALE_MS });
  const stats = useApiQuery(RECONCILIATION_STATS_QUERY_KEY, "reconciliation_stats_reconciliation_stats_get", {}, { staleTime: SHARED_STALE_MS });
  const processing = useApiQuery(
    PROCESSING_PENDING_QUERY_KEY,
    "list_processing_pending_accounts_processing_pending_get",
    {},
    { staleTime: SHARED_STALE_MS },
  );
  const hasUnmatched = (stats.data?.unmatched_transactions ?? 0) > 0;
  const firstUnmatched = useApiQuery(UNMATCHED_FIRST_QUERY_KEY, "list_unmatched_reconciliation_unmatched_get", UNMATCHED_FIRST_REQUEST, {
    staleTime: SHARED_STALE_MS,
    enabled: hasUnmatched,
  });

  const sources = [statements, stats, processing];
  const failedSource = sources.find((source) => source.isError);
  const retrying = sources.some((source) => source.isError && source.isFetching);
  const settled =
    sources.every((source) => source.isSuccess || source.isError) &&
    (!hasUnmatched || firstUnmatched.isSuccess || firstUnmatched.isError);

  const statementItems = statements.data?.items;
  const statsData = stats.data;
  const processingItems = processing.data?.items;
  const firstUnmatchedRow = firstUnmatched.data?.items?.[0] ?? null;
  const items = useMemo(
    () =>
      settled
        ? buildAttentionItems({
            statements: statementItems ?? [],
            stats: statsData ?? null,
            processing: processingItems ?? [],
            firstUnmatched: firstUnmatchedRow,
          })
        : null,
    [settled, statementItems, statsData, processingItems, firstUnmatchedRow],
  );

  return {
    items,
    failed: Boolean(failedSource),
    error:
      failedSource && !retrying ? (failedSource.error?.message ?? "Failed to load items that need confirmation") : null,
    retry: () => {
      for (const source of sources) if (source.isError) void source.refetch();
    },
  };
}
