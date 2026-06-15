"use client";

import { useMemo } from "react";

import { useAssetTrend } from "@/hooks/dashboard/useAssetTrend";
import {
  useDashboardSnapshot,
  type DashboardOnboardingStatus,
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
 * sheet). The public result contract is unchanged from the former single hook,
 * so consumers (the Home route) need no changes. No behavior change.
 */

export type { DashboardOnboardingStatus };

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
  trend: TrendResponse | null;
  trendAccountName: string;
  trendAccountId: string | null;
  setTrendAccountId: (id: string | null) => void;
  loading: boolean;
  error: string | null;
  retry: () => void;
}

export function useDashboardData(includeRestricted: boolean): UseDashboardDataResult {
  const snapshot = useDashboardSnapshot(includeRestricted);
  const { trend, trendAccountName, trendAccountId, setTrendAccountId } = useAssetTrend(
    snapshot.balanceSheet,
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
      trend,
      trendAccountName,
      trendAccountId,
      setTrendAccountId,
      loading: snapshot.loading,
      error: snapshot.error,
      retry: snapshot.retry,
    }),
    [snapshot, trend, trendAccountName, trendAccountId, setTrendAccountId],
  );
}
