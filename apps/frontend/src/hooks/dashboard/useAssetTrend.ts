"use client";

import { keepPreviousData } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { useApiQuery } from "@/hooks/useApiQuery";
import { compareAmounts } from "@/lib/audit/money";
import { isPageUnloading } from "@/lib/pageUnload";
import { SHARED_STALE_MS } from "@/lib/sharedQueries";
import type { BalanceSheetResponse, TrendResponse } from "@/lib/types";

/**
 * Per-account asset-trend hook (EPIC-022 AC22.16.3, #1119).
 *
 * Extracted from the former `useDashboardData` god-hook. Given the loaded
 * balance sheet, it resolves the selected (or top) asset account and reads its
 * monthly trend through the query cache (#2583 S4). The cache key holds the
 * account and the period, so a balance-sheet refetch that keeps the same top
 * account does not request the trend again. The hook exposes the selection
 * setter so the Home chart stays interactive.
 */

export interface AssetTrend {
  trend: TrendResponse | null;
  /** True while the trend of the selected account has not delivered its first data. */
  trendPending: boolean;
  trendAccountName: string;
  trendAccountId: string | null;
  setTrendAccountId: (id: string | null) => void;
}

export interface AssetTrendOptions {
  /** When false, the hook reads no trend. Default: true. */
  enabled?: boolean;
}

export function useAssetTrend(
  balanceSheet: BalanceSheetResponse | null,
  { enabled = true }: AssetTrendOptions = {},
): AssetTrend {
  const [trendAccountId, setTrendAccountId] = useState<string | null>(null);

  const sortedAssets = useMemo(
    () =>
      balanceSheet?.assets
        ? [...balanceSheet.assets].sort((a, b) =>
            compareAmounts(b.amount, a.amount),
          )
        : [],
    [balanceSheet],
  );
  const selected = trendAccountId
    ? sortedAssets.find((a) => a.account_id === trendAccountId)
    : undefined;
  const target = selected ?? sortedAssets[0];

  // If the previously selected account is no longer in the refreshed balance
  // sheet (e.g. toggling "Include restricted holdings"), drop the stale
  // selection so the consumer <select> never shows a value missing from its
  // options. Clearing it falls back to the top asset.
  useEffect(() => {
    if (balanceSheet?.assets && trendAccountId && !selected) {
      setTrendAccountId(null);
    }
  }, [balanceSheet, selected, trendAccountId]);

  const targetAccountId = target?.account_id ?? null;
  const trendQuery = useApiQuery(
    ["report", "trend", targetAccountId, "monthly"],
    "account_trend_reports_trend_get",
    { query: { account_id: targetAccountId ?? "", period: "monthly" } },
    {
      enabled: enabled && targetAccountId !== null,
      staleTime: SHARED_STALE_MS,
      // Keep the chart on screen while the next account loads.
      placeholderData: keepPreviousData,
    },
  );

  const trendError = trendQuery.error;
  useEffect(() => {
    // A fetch that the browser aborted while the page unloads is not a failure.
    if (trendError && !isPageUnloading()) {
      console.error("Failed to fetch trend data:", trendError);
    }
  }, [trendError]);

  const trendAccountName = target?.name ?? "Top Asset";
  const trend =
    enabled && targetAccountId !== null && !trendQuery.isError
      ? (trendQuery.data ?? null)
      : null;

  const trendPending =
    enabled && targetAccountId !== null && trendQuery.isPending;

  return useMemo(
    () => ({
      trend,
      trendPending,
      trendAccountName,
      trendAccountId,
      setTrendAccountId,
    }),
    [trend, trendPending, trendAccountName, trendAccountId],
  );
}
