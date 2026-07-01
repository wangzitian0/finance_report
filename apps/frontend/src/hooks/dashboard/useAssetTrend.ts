"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api";
import { compareAmounts } from "@/lib/audit/money";
import type { BalanceSheetResponse, TrendResponse } from "@/lib/types";

/**
 * Per-account asset-trend hook (EPIC-022 AC22.16.3, #1119).
 *
 * Extracted from the former `useDashboardData` god-hook. Given the loaded
 * balance sheet, it resolves the selected (or top) asset account and fetches its
 * monthly trend, exposing the selection setter so the Home chart stays
 * interactive. Callable on its own with any balance sheet. No behavior change.
 */

export interface AssetTrend {
  trend: TrendResponse | null;
  trendAccountName: string;
  trendAccountId: string | null;
  setTrendAccountId: (id: string | null) => void;
}

export function useAssetTrend(balanceSheet: BalanceSheetResponse | null): AssetTrend {
  const [trend, setTrend] = useState<TrendResponse | null>(null);
  const [trendAccountId, setTrendAccountId] = useState<string | null>(null);
  const [trendAccountName, setTrendAccountName] = useState<string>("Top Asset");

  const fetchTrend = useCallback(async () => {
    if (!balanceSheet || !balanceSheet.assets) return;
    const sortedAssets = [...balanceSheet.assets].sort((a, b) => compareAmounts(b.amount, a.amount));
    const selected = trendAccountId
      ? sortedAssets.find((a) => a.account_id === trendAccountId)
      : undefined;
    // If the previously selected account is no longer in the refreshed balance
    // sheet (e.g. toggling "Include restricted holdings"), drop the stale
    // selection so the consumer <select> never shows a value missing from its
    // options. Clearing it re-runs this effect against the top asset.
    if (trendAccountId && !selected) {
      setTrendAccountId(null);
      return;
    }
    const target = selected ?? sortedAssets[0];
    if (!target) return;
    setTrendAccountName(target.name);
    try {
      const trendData = await apiFetch<TrendResponse>(
        `/api/reports/trend?account_id=${target.account_id}&period=monthly`,
      );
      setTrend(trendData);
    } catch (err) {
      console.error("Failed to fetch trend data:", err);
      setTrend(null);
    }
  }, [balanceSheet, trendAccountId]);

  useEffect(() => {
    if (balanceSheet && balanceSheet.assets) {
      fetchTrend();
    }
  }, [fetchTrend, balanceSheet]);

  return useMemo(
    () => ({ trend, trendAccountName, trendAccountId, setTrendAccountId }),
    [trend, trendAccountName, trendAccountId],
  );
}
