"use client";

import { useMemo } from "react";

import type { CockpitPeriodPreset } from "@/components/home/ThreeStatementNav";
import { useAssetTrend } from "@/hooks/dashboard/useAssetTrend";
import {
  useDashboardSnapshot,
  type DashboardOnboardingStatus,
  type DashboardPending,
  type DashboardSnapshotOptions,
} from "@/hooks/dashboard/useDashboardSnapshot";
import type {
  AdvisorSuggestion,
  AnnualizedIncomeResponse,
  BalanceSheetResponse,
  IncomeStatementResponse,
  JournalEntryListResponse,
  ReconciliationStatsResponse,
  RestrictedHolding,
  TrendResponse,
  UnmatchedTransactionsResponse,
} from "@/lib/types";

/**
 * Dashboard data hook (EPIC-022 AC22.16.3, #1119).
 *
 * Thin composition layer over two independently-usable hooks:
 * `useDashboardSnapshot` (financial + reconciliation aggregate) and
 * `useAssetTrend` (the per-account trend that depends on the loaded balance
 * sheet). Both read through the query cache (#2583 S4). The statement list
 * left this result: the trust meter reads it from the cache on its own.
 */

export type { DashboardOnboardingStatus, DashboardPending };

/** Pending flags per card. `trend` joins the snapshot flags: the trend waits for the balance sheet. */
export type DashboardCardPending = DashboardPending & { trend: boolean };

export interface UseDashboardDataResult {
  balanceSheet: BalanceSheetResponse | null;
  incomeStatement: IncomeStatementResponse | null;
  annualizedIncome: AnnualizedIncomeResponse | null;
  restrictedHoldings: RestrictedHolding[];
  stats: ReconciliationStatsResponse | null;
  unmatched: UnmatchedTransactionsResponse | null;
  recentEntries: JournalEntryListResponse | null;
  onboardingStatus: DashboardOnboardingStatus | null;
  advisorSuggestions: AdvisorSuggestion[];
  pending: DashboardCardPending;
  trend: TrendResponse | null;
  trendAccountName: string;
  trendAccountId: string | null;
  setTrendAccountId: (id: string | null) => void;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

export function useDashboardData(
  includeRestricted: boolean,
  periodPreset: CockpitPeriodPreset = "1Y",
  currency?: string,
  options: DashboardSnapshotOptions = {},
): UseDashboardDataResult {
  const snapshot = useDashboardSnapshot(
    includeRestricted,
    periodPreset,
    currency,
    options,
  );
  const { trend, trendPending, trendAccountName, trendAccountId, setTrendAccountId } =
    useAssetTrend(snapshot.balanceSheet, {
      enabled: options.analyticsOpen ?? true,
    });
  const snapshotPending = snapshot.pending;
  const pending = useMemo<DashboardCardPending>(
    () => ({
      ...snapshotPending,
      trend: snapshotPending.balanceSheet || trendPending,
    }),
    [snapshotPending, trendPending],
  );

  return useMemo(
    () => ({
      balanceSheet: snapshot.balanceSheet,
      incomeStatement: snapshot.incomeStatement,
      annualizedIncome: snapshot.annualizedIncome,
      restrictedHoldings: snapshot.restrictedHoldings,
      stats: snapshot.stats,
      unmatched: snapshot.unmatched,
      recentEntries: snapshot.recentEntries,
      onboardingStatus: snapshot.onboardingStatus,
      advisorSuggestions: snapshot.advisorSuggestions,
      pending,
      trend,
      trendAccountName,
      trendAccountId,
      setTrendAccountId,
      loading: snapshot.loading,
      error: snapshot.error,
      retry: snapshot.retry,
    }),
    [snapshot, pending, trend, trendAccountName, trendAccountId, setTrendAccountId],
  );
}
