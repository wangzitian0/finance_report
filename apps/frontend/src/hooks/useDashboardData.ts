"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api";
import { compareAmounts } from "@/lib/currency";
import { formatDateInput } from "@/lib/date";
import type {
  AccountListResponse,
  AdvisorSuggestion,
  AnnualizedIncomeResponse,
  BalanceSheetResponse,
  BankStatementListResponse,
  ChatSuggestionsResponse,
  IncomeStatementResponse,
  JournalEntryListResponse,
  ReconciliationStatsResponse,
  RestrictedHolding,
  TrendResponse,
  UnmatchedTransactionsResponse,
} from "@/lib/types";

/**
 * Dashboard data hook (Slice 3 of #751).
 *
 * Moves the home route's parallel API aggregation and report normalization out
 * of the route page and behind the shared `apiFetch` transport. The route now
 * composes the returned, normalized data instead of fetching and reshaping it
 * inline. Monetary values stay decimal strings; no behavior change.
 */

const EMPTY_BALANCE_SHEET: BalanceSheetResponse = {
  as_of_date: "",
  currency: "SGD",
  assets: [],
  liabilities: [],
  equity: [],
  total_assets: "0",
  total_liabilities: "0",
  total_equity: "0",
  equation_delta: "0",
  is_balanced: true,
};

const EMPTY_INCOME_STATEMENT: IncomeStatementResponse = {
  start_date: "",
  end_date: "",
  currency: "SGD",
  income: [],
  expenses: [],
  total_income: "0",
  total_expenses: "0",
  net_income: "0",
  trends: [],
};

const EMPTY_ANNUALIZED_INCOME: AnnualizedIncomeResponse = {
  annualized_salary: "0",
  annualized_bonus: "0",
  annualized_dividend: "0",
  annualized_total: "0",
  currency: "SGD",
  as_of: "",
};

const EMPTY_STATS: ReconciliationStatsResponse = {
  total_transactions: 0,
  matched_transactions: 0,
  unmatched_transactions: 0,
  pending_review: 0,
  auto_accepted: 0,
  match_rate: 0,
  score_distribution: {},
};

function normalizeBalanceSheet(
  data?: Partial<BalanceSheetResponse> | null,
): BalanceSheetResponse {
  return {
    ...EMPTY_BALANCE_SHEET,
    ...data,
    assets: data?.assets ?? [],
    liabilities: data?.liabilities ?? [],
    equity: data?.equity ?? [],
    total_assets: data?.total_assets ?? "0",
    total_liabilities: data?.total_liabilities ?? "0",
    total_equity: data?.total_equity ?? "0",
    equation_delta: data?.equation_delta ?? "0",
    currency: data?.currency ?? "SGD",
    as_of_date: data?.as_of_date ?? "",
    is_balanced: data?.is_balanced ?? true,
  };
}

function normalizeIncomeStatement(
  data?: Partial<IncomeStatementResponse> | null,
): IncomeStatementResponse {
  return {
    ...EMPTY_INCOME_STATEMENT,
    ...data,
    income: data?.income ?? [],
    expenses: data?.expenses ?? [],
    trends: data?.trends ?? [],
    total_income: data?.total_income ?? "0",
    total_expenses: data?.total_expenses ?? "0",
    net_income: data?.net_income ?? "0",
    currency: data?.currency ?? "SGD",
  };
}

function normalizeAnnualizedIncome(
  data?: Partial<AnnualizedIncomeResponse> | null,
): AnnualizedIncomeResponse {
  return {
    ...EMPTY_ANNUALIZED_INCOME,
    ...data,
    annualized_salary: data?.annualized_salary ?? "0",
    annualized_bonus: data?.annualized_bonus ?? "0",
    annualized_dividend: data?.annualized_dividend ?? "0",
    annualized_total: data?.annualized_total ?? "0",
    currency: data?.currency ?? "SGD",
    as_of: data?.as_of ?? "",
  };
}

export interface DashboardOnboardingStatus {
  accountCount: number;
  statementCount: number;
  approvedStatementCount: number;
  postedEntryCount: number;
}

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
  const [balanceSheet, setBalanceSheet] = useState<BalanceSheetResponse | null>(null);
  const [incomeStatement, setIncomeStatement] = useState<IncomeStatementResponse | null>(null);
  const [annualizedIncome, setAnnualizedIncome] = useState<AnnualizedIncomeResponse | null>(null);
  const [restrictedHoldings, setRestrictedHoldings] = useState<RestrictedHolding[]>([]);
  const [stats, setStats] = useState<ReconciliationStatsResponse | null>(null);
  const [unmatched, setUnmatched] = useState<UnmatchedTransactionsResponse | null>(null);
  const [recentEntries, setRecentEntries] = useState<JournalEntryListResponse | null>(null);
  const [onboardingStatus, setOnboardingStatus] = useState<DashboardOnboardingStatus | null>(null);
  const [advisorSuggestions, setAdvisorSuggestions] = useState<AdvisorSuggestion[]>([]);
  const [trend, setTrend] = useState<TrendResponse | null>(null);
  const [trendAccountId, setTrendAccountId] = useState<string | null>(null);
  const [trendAccountName, setTrendAccountName] = useState<string>("Top Asset");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    const today = new Date();
    const incomeStart = formatDateInput(new Date(today.getFullYear(), today.getMonth() - 11, 1));
    const incomeEnd = formatDateInput(today);
    setLoading(true);
    try {
      const [
        balanceData,
        incomeData,
        annualizedData,
        restrictedData,
        statsData,
        unmatchedData,
        journalData,
        accountData,
        statementData,
        postedJournalData,
        chatSuggestionsData,
      ] = await Promise.all([
        apiFetch<BalanceSheetResponse>(
          `/api/reports/balance-sheet?include_restricted=${includeRestricted ? "true" : "false"}`,
        ),
        apiFetch<IncomeStatementResponse>(
          `/api/reports/income-statement?start_date=${incomeStart}&end_date=${incomeEnd}`,
        ),
        apiFetch<AnnualizedIncomeResponse>("/api/income/annualized"),
        apiFetch<RestrictedHolding[]>("/api/assets/restricted"),
        apiFetch<ReconciliationStatsResponse>("/api/reconciliation/stats"),
        apiFetch<UnmatchedTransactionsResponse>("/api/reconciliation/unmatched?limit=5"),
        apiFetch<JournalEntryListResponse>("/api/journal-entries?page=1&page_size=5"),
        apiFetch<AccountListResponse>("/api/accounts?limit=1"),
        apiFetch<BankStatementListResponse>("/api/statements"),
        apiFetch<JournalEntryListResponse>("/api/journal-entries?status_filter=posted&limit=1"),
        apiFetch<ChatSuggestionsResponse>(
          "/api/chat/suggestions?language=en&include_structured=true",
        ).catch(() => ({ suggestions: [], structured_suggestions: [] })),
      ]);
      setBalanceSheet(normalizeBalanceSheet(balanceData));
      setIncomeStatement(normalizeIncomeStatement(incomeData));
      setAnnualizedIncome(normalizeAnnualizedIncome(annualizedData));
      setRestrictedHoldings(Array.isArray(restrictedData) ? restrictedData : []);
      setStats(statsData || EMPTY_STATS);
      setUnmatched(unmatchedData || { items: [], total: 0 });
      setRecentEntries(journalData || { items: [], total: 0 });
      setOnboardingStatus({
        accountCount: accountData?.total ?? 0,
        statementCount: statementData?.total ?? 0,
        approvedStatementCount:
          statementData?.items?.filter((statement) => statement.status === "approved").length ?? 0,
        postedEntryCount: postedJournalData?.total ?? 0,
      });
      setAdvisorSuggestions(chatSuggestionsData?.structured_suggestions ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load dashboard data.");
    } finally {
      setLoading(false);
    }
  }, [includeRestricted]);

  const fetchTrend = useCallback(async () => {
    if (!balanceSheet || !balanceSheet.assets) return;
    const sortedAssets = [...balanceSheet.assets].sort((a, b) => compareAmounts(b.amount, a.amount));
    const target = trendAccountId
      ? sortedAssets.find((a) => a.account_id === trendAccountId) ?? sortedAssets[0]
      : sortedAssets[0];
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
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (balanceSheet && balanceSheet.assets) {
      fetchTrend();
    }
  }, [fetchTrend, balanceSheet]);

  return useMemo(
    () => ({
      balanceSheet,
      incomeStatement,
      annualizedIncome,
      restrictedHoldings,
      stats,
      unmatched,
      recentEntries,
      onboardingStatus,
      advisorSuggestions,
      trend,
      trendAccountName,
      trendAccountId,
      setTrendAccountId,
      loading,
      error,
      retry: fetchData,
    }),
    [
      advisorSuggestions,
      annualizedIncome,
      balanceSheet,
      error,
      fetchData,
      incomeStatement,
      loading,
      onboardingStatus,
      recentEntries,
      restrictedHoldings,
      stats,
      trend,
      trendAccountId,
      trendAccountName,
      unmatched,
    ],
  );
}
