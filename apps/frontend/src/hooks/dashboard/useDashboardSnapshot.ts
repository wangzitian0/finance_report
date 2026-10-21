"use client";

import { keepPreviousData } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";

import {
  resolvePeriodRange,
  type CockpitPeriodPreset,
} from "@/components/home/ThreeStatementNav";
import { useApiQuery } from "@/hooks/useApiQuery";
import type { components } from "@/lib/api-types";
import {
  balanceSheetQueryKey,
  incomeStatementQueryKey,
  RECONCILIATION_STATS_QUERY_KEY,
  SHARED_STALE_MS,
  STATEMENTS_LIST_QUERY_KEY,
} from "@/lib/sharedQueries";
import {
  normalizeAdvisorSuggestions,
  normalizeFxWarningRows,
} from "@/lib/types";
import type {
  AdvisorSuggestion,
  AnnualizedIncomeResponse,
  BalanceSheetResponse,
  IncomeStatementResponse,
  JournalEntryListResponse,
  ReconciliationStatsResponse,
  RestrictedHolding,
  UnmatchedTransactionsResponse,
} from "@/lib/types";

/**
 * Dashboard snapshot hook (EPIC-022 AC22.16.3, #1119).
 *
 * Reads every Home data source through the query cache (#2583 S4). Each source has its own
 * key, so a revisit inside the stale time issues no request, and a toggle refetches only the
 * sources whose parameters changed. Each source reports its own pending state, so a card
 * renders when its own data arrives. The sources that feed only the opt-in analytics panel
 * start when `analyticsOpen` is true. The advisor suggestions cost the most on the server.
 * They load off the critical path and stay cached for five minutes.
 *
 * Extracted from the former ~294-line `useDashboardData` god-hook so the
 * financial/reconciliation snapshot is testable and composable on its own; the
 * per-account trend lives in the sibling `useAssetTrend` hook. Monetary values
 * stay decimal strings.
 */

/** Stale time of the advisor suggestions. The server builds a full report package for them. */
export const ADVISOR_SUGGESTIONS_STALE_MS = 5 * 60 * 1000;

const EMPTY_BALANCE_SHEET: BalanceSheetResponse = {
  as_of_date: "",
  currency: "SGD",
  assets: [],
  liabilities: [],
  equity: [],
  total_assets: "0",
  total_liabilities: "0",
  total_equity: "0",
  net_income: "0",
  net_worth_adjustment_gain_loss: "0",
  unrealized_fx_gain_loss: "0",
  equation_delta: "0",
  cta_adjustment: "0",
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
  data?: Partial<components["schemas"]["BalanceSheetResponse"]> | null,
): BalanceSheetResponse {
  const { fx_warnings, opening_balance_warnings, ...values } = data ?? {};
  return {
    ...EMPTY_BALANCE_SHEET,
    ...values,
    assets: data?.assets ?? [],
    liabilities: data?.liabilities ?? [],
    equity: data?.equity ?? [],
    total_assets: data?.total_assets ?? "0",
    total_liabilities: data?.total_liabilities ?? "0",
    total_equity: data?.total_equity ?? "0",
    net_income: data?.net_income ?? "0",
    net_worth_adjustment_gain_loss: data?.net_worth_adjustment_gain_loss ?? "0",
    unrealized_fx_gain_loss: data?.unrealized_fx_gain_loss ?? "0",
    equation_delta: data?.equation_delta ?? "0",
    currency: data?.currency ?? "SGD",
    as_of_date: data?.as_of_date ?? "",
    is_balanced: data?.is_balanced ?? true,
    fx_warnings: normalizeFxWarningRows(fx_warnings),
    opening_balance_warnings: normalizeFxWarningRows(opening_balance_warnings),
  };
}

function normalizeIncomeStatement(
  data?: Partial<components["schemas"]["IncomeStatementResponse"]> | null,
): IncomeStatementResponse {
  const { fx_warnings, ...values } = data ?? {};
  return {
    ...EMPTY_INCOME_STATEMENT,
    ...values,
    income: data?.income ?? [],
    expenses: data?.expenses ?? [],
    trends: data?.trends ?? [],
    total_income: data?.total_income ?? "0",
    total_expenses: data?.total_expenses ?? "0",
    net_income: data?.net_income ?? "0",
    currency: data?.currency ?? "SGD",
    fx_warnings: normalizeFxWarningRows(fx_warnings),
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

/** True while the source behind a card has not delivered its first data. */
export interface DashboardPending {
  balanceSheet: boolean;
  incomeStatement: boolean;
  stats: boolean;
  annualizedIncome: boolean;
  restrictedHoldings: boolean;
  unmatched: boolean;
  recentEntries: boolean;
}

export interface DashboardSnapshotOptions {
  /**
   * Start the sources that feed only the analytics panel (annualized income, restricted
   * holdings, unmatched list, recent entries). Default: true.
   */
  analyticsOpen?: boolean;
}

export interface DashboardSnapshot {
  balanceSheet: BalanceSheetResponse | null;
  incomeStatement: IncomeStatementResponse | null;
  annualizedIncome: AnnualizedIncomeResponse | null;
  restrictedHoldings: RestrictedHolding[];
  stats: ReconciliationStatsResponse | null;
  unmatched: UnmatchedTransactionsResponse | null;
  recentEntries: JournalEntryListResponse | null;
  onboardingStatus: DashboardOnboardingStatus | null;
  advisorSuggestions: AdvisorSuggestion[];
  pending: DashboardPending;
  /** True while a source that Home needs now has not delivered its first data. */
  loading: boolean;
  /** Message of the first failed source, or null. */
  error: string | null;
  /** Refetch every failed source. */
  retry: () => void;
}

const EMPTY_PAGE = { items: [], total: 0 };
const NO_RESTRICTED_HOLDINGS: RestrictedHolding[] = [];

export function useDashboardSnapshot(
  includeRestricted: boolean,
  periodPreset: CockpitPeriodPreset = "1Y",
  currency?: string,
  { analyticsOpen = true }: DashboardSnapshotOptions = {},
): DashboardSnapshot {
  const { startDate, endDate } = useMemo(
    () => resolvePeriodRange(periodPreset, new Date()),
    [periodPreset],
  );

  // Cockpit sources: they feed the statement cards, onboarding and the trust meter.
  const balanceKey = balanceSheetQueryKey({ currency, includeRestricted });
  const balanceQuery = useApiQuery(
    balanceKey,
    "balance_sheet_reports_balance_sheet_get",
    {
      query: {
        include_restricted: includeRestricted,
        ...(currency ? { currency } : {}),
      },
    },
    {
      staleTime: SHARED_STALE_MS,
      placeholderData: keepPreviousData,
      select: normalizeBalanceSheet,
    },
  );
  const incomeKey = incomeStatementQueryKey({ startDate, endDate, currency });
  const incomeQuery = useApiQuery(
    incomeKey,
    "income_statement_reports_income_statement_get",
    {
      query: {
        start_date: startDate,
        end_date: endDate,
        ...(currency ? { currency } : {}),
      },
    },
    {
      staleTime: SHARED_STALE_MS,
      placeholderData: keepPreviousData,
      select: normalizeIncomeStatement,
    },
  );
  const statsQuery = useApiQuery(
    RECONCILIATION_STATS_QUERY_KEY,
    "reconciliation_stats_reconciliation_stats_get",
    {},
    { staleTime: SHARED_STALE_MS, select: (data) => data || EMPTY_STATS },
  );
  const statementsQuery = useApiQuery(
    STATEMENTS_LIST_QUERY_KEY,
    "list_statements_statements_get",
    {},
    { staleTime: SHARED_STALE_MS },
  );
  const accountsQuery = useApiQuery(
    ["accounts", "count"],
    "list_accounts_accounts_get",
    { query: { limit: 1 } },
    { staleTime: SHARED_STALE_MS },
  );
  const postedEntriesQuery = useApiQuery(
    ["dashboard", "posted-entry-count"],
    "list_journal_entries_journal_entries_get",
    { query: { status_filter: "posted", limit: 1 } },
    { staleTime: SHARED_STALE_MS },
  );

  // Analytics sources: they feed cards inside the opt-in analytics panel.
  const annualizedQuery = useApiQuery(
    ["dashboard", "annualized-income"],
    "get_annualized_income_income_annualized_get",
    {},
    {
      enabled: analyticsOpen,
      staleTime: SHARED_STALE_MS,
      select: normalizeAnnualizedIncome,
    },
  );
  const restrictedQuery = useApiQuery(
    ["dashboard", "restricted-holdings"],
    "list_restricted_holdings_assets_restricted_get",
    {},
    {
      enabled: analyticsOpen,
      staleTime: SHARED_STALE_MS,
      select: (data) => (Array.isArray(data) ? data : []),
    },
  );
  const unmatchedQuery = useApiQuery(
    ["reconciliation", "unmatched", { limit: 5 }],
    "list_unmatched_reconciliation_unmatched_get",
    { query: { limit: 5 } },
    {
      enabled: analyticsOpen,
      staleTime: SHARED_STALE_MS,
      select: (data) => data || EMPTY_PAGE,
    },
  );
  const recentEntriesQuery = useApiQuery(
    ["dashboard", "recent-entries", { limit: 5 }],
    "list_journal_entries_journal_entries_get",
    { query: { limit: 5, offset: 0 } },
    {
      enabled: analyticsOpen,
      staleTime: SHARED_STALE_MS,
      select: (data) => data || EMPTY_PAGE,
    },
  );

  // Advisor suggestions: the server builds a full report package for them, so they stay off the
  // critical path (no card waits for them, no failure shows) and stay cached for five minutes.
  const suggestionsQuery = useApiQuery(
    ["chat", "suggestions", { language: "en", includeStructured: true }],
    "suggestions_chat_suggestions_get",
    { query: { language: "en", include_structured: true } },
    { staleTime: ADVISOR_SUGGESTIONS_STALE_MS, retry: false },
  );
  const structuredSuggestions = suggestionsQuery.data?.structured_suggestions;
  const advisorSuggestions = useMemo(
    () => normalizeAdvisorSuggestions(structuredSuggestions),
    [structuredSuggestions],
  );

  const accountCount = accountsQuery.data?.total ?? 0;
  const statementCount = statementsQuery.data?.total ?? 0;
  const approvedStatementCount =
    statementsQuery.data?.items?.filter(
      (statement) => statement.status === "approved",
    ).length ?? 0;
  const postedEntryCount = postedEntriesQuery.data?.total ?? 0;
  const onboardingReady =
    accountsQuery.isSuccess &&
    statementsQuery.isSuccess &&
    postedEntriesQuery.isSuccess;
  const onboardingStatus = useMemo<DashboardOnboardingStatus | null>(
    () =>
      onboardingReady
        ? {
            accountCount,
            statementCount,
            approvedStatementCount,
            postedEntryCount,
          }
        : null,
    [
      accountCount,
      approvedStatementCount,
      onboardingReady,
      postedEntryCount,
      statementCount,
    ],
  );

  const cockpitSources = [
    balanceQuery,
    incomeQuery,
    statsQuery,
    statementsQuery,
    accountsQuery,
    postedEntriesQuery,
  ];
  const analyticsSources = [
    annualizedQuery,
    restrictedQuery,
    unmatchedQuery,
    recentEntriesQuery,
  ];
  const activeSources = analyticsOpen
    ? [...cockpitSources, ...analyticsSources]
    : cockpitSources;

  const loading = activeSources.some((source) => source.isPending);
  const failedSource = activeSources.find((source) => source.isError);
  const error = failedSource
    ? (failedSource.error?.message ?? "Failed to load dashboard data.")
    : null;

  // `retry` stays stable. It refetches the sources that failed in the latest committed render.
  const failedRefetchersRef = useRef<Array<() => unknown>>([]);
  useEffect(() => {
    failedRefetchersRef.current = activeSources
      .filter((source) => source.isError)
      .map((source) => source.refetch);
  });
  const retry = useCallback(() => {
    for (const refetch of failedRefetchersRef.current) void refetch();
  }, []);

  const balancePending = balanceQuery.isPending;
  const incomePending = incomeQuery.isPending;
  const statsPending = statsQuery.isPending;
  const annualizedPending = annualizedQuery.isPending;
  const restrictedPending = restrictedQuery.isPending;
  const unmatchedPending = unmatchedQuery.isPending;
  const recentEntriesPending = recentEntriesQuery.isPending;
  const pending = useMemo<DashboardPending>(
    () => ({
      balanceSheet: balancePending,
      incomeStatement: incomePending,
      stats: statsPending,
      annualizedIncome: annualizedPending,
      restrictedHoldings: restrictedPending,
      unmatched: unmatchedPending,
      recentEntries: recentEntriesPending,
    }),
    [
      annualizedPending,
      balancePending,
      incomePending,
      recentEntriesPending,
      restrictedPending,
      statsPending,
      unmatchedPending,
    ],
  );

  const balanceSheet = balanceQuery.data ?? null;
  const incomeStatement = incomeQuery.data ?? null;
  const annualizedIncome = annualizedQuery.data ?? null;
  const restrictedHoldings = restrictedQuery.data;
  const stats = statsQuery.data ?? null;
  const unmatched = unmatchedQuery.data ?? null;
  const recentEntries = recentEntriesQuery.data ?? null;

  return useMemo(
    () => ({
      balanceSheet,
      incomeStatement,
      annualizedIncome,
      restrictedHoldings: restrictedHoldings ?? NO_RESTRICTED_HOLDINGS,
      stats,
      unmatched,
      recentEntries,
      onboardingStatus,
      advisorSuggestions,
      pending,
      loading,
      error,
      retry,
    }),
    [
      advisorSuggestions,
      annualizedIncome,
      balanceSheet,
      error,
      incomeStatement,
      loading,
      onboardingStatus,
      pending,
      recentEntries,
      restrictedHoldings,
      retry,
      stats,
      unmatched,
    ],
  );
}
