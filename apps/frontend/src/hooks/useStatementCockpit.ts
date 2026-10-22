"use client";

import { keepPreviousData } from "@tanstack/react-query";
import { useCallback, useEffect, useRef } from "react";

import { useApiQuery } from "@/hooks/useApiQuery";
import type { ReportFilters } from "@/hooks/useReportFilters";
import {
  balanceSheetQueryKey,
  cashFlowQueryKey,
  incomeStatementQueryKey,
  SHARED_STALE_MS,
} from "@/lib/sharedQueries";
import {
  normalizeFxWarningRows,
  type BalanceSheetResponse,
  type CashFlowPreview,
  type IncomeStatementResponse,
} from "@/lib/types";

/**
 * The data of the three statement cards on Home and on the `/reports` Overview (#2621 LC, #2548 P1).
 *
 * Four requests, one per statement view of the dimension-bar period:
 *  - the balance sheet at the period end,
 *  - the balance sheet at the opening date (the day before the period starts), for the
 *    net worth change of the period. The `All` period has no opening date and no request,
 *  - the income statement of the period,
 *  - the cash flow statement of the period.
 * The keys come from `lib/sharedQueries`, so a statement tab with the same dimensions reads the
 * same cache entry. Each card waits only for its own source. Monetary values stay decimal strings.
 */

export interface StatementCockpitPending {
  balanceSheet: boolean;
  incomeStatement: boolean;
  cashFlow: boolean;
}

export interface StatementCockpitData {
  balanceSheet: BalanceSheetResponse | null;
  openingBalanceSheet: BalanceSheetResponse | null;
  incomeStatement: IncomeStatementResponse | null;
  cashFlow: CashFlowPreview | null;
  pending: StatementCockpitPending;
  /** The message of the first failed source, or null. */
  error: string | null;
  /** Refetch each failed source. */
  retry: () => void;
}

const QUERY_OPTIONS = { staleTime: SHARED_STALE_MS, placeholderData: keepPreviousData } as const;

/** The currency of a statement whose payload names none. It equals the old Home default. */
const FALLBACK_CURRENCY = "SGD";
const ZERO = "0";
type Payload = {
  currency?: string;
  fx_warnings?: Array<Record<string, string>>;
  opening_balance_warnings?: Array<Record<string, string>>;
};

// A statement payload with a missing list, total or currency must not break Home: the cards
// read empty lists and zero totals instead (decimal strings, never floats).
function normalizeCommon<T extends Payload>(data: T) {
  return {
    ...data,
    currency: data.currency || FALLBACK_CURRENCY,
    fx_warnings: normalizeFxWarningRows(data.fx_warnings),
  };
}

function normalizeBalanceSheet<T extends Payload & Partial<Pick<BalanceSheetResponse, "assets" | "liabilities" | "equity" | "total_assets" | "total_liabilities">>>(data: T) {
  return {
    ...normalizeCommon(data),
    assets: data.assets ?? [],
    liabilities: data.liabilities ?? [],
    equity: data.equity ?? [],
    total_assets: data.total_assets ?? ZERO,
    total_liabilities: data.total_liabilities ?? ZERO,
    opening_balance_warnings: normalizeFxWarningRows(data.opening_balance_warnings),
  };
}

function normalizeIncomeStatement<T extends Payload & Partial<Pick<IncomeStatementResponse, "income" | "expenses" | "total_income" | "total_expenses" | "net_income">>>(data: T) {
  return {
    ...normalizeCommon(data),
    income: data.income ?? [],
    expenses: data.expenses ?? [],
    total_income: data.total_income ?? ZERO,
    total_expenses: data.total_expenses ?? ZERO,
    net_income: data.net_income ?? ZERO,
  };
}

const ZERO_CASH_SUMMARY: CashFlowPreview["summary"] = {
  operating_activities: ZERO,
  investing_activities: ZERO,
  financing_activities: ZERO,
  net_cash_flow: ZERO,
  beginning_cash: ZERO,
  ending_cash: ZERO,
};

function normalizeCashFlow<T extends Payload & Partial<Pick<CashFlowPreview, "operating" | "investing" | "financing" | "summary">>>(data: T) {
  return {
    ...normalizeCommon(data),
    operating: data.operating ?? [],
    investing: data.investing ?? [],
    financing: data.financing ?? [],
    summary: { ...ZERO_CASH_SUMMARY, ...data.summary },
  };
}

export function useStatementCockpit({
  startDate,
  endDate,
  openingDate,
  currency,
  includeRestricted,
}: ReportFilters): StatementCockpitData {
  const balanceQuery = useApiQuery(
    balanceSheetQueryKey({ asOfDate: endDate, currency, includeRestricted }),
    "balance_sheet_reports_balance_sheet_get",
    { query: { as_of_date: endDate, currency, include_restricted: includeRestricted } },
    { ...QUERY_OPTIONS, select: normalizeBalanceSheet },
  );
  const openingQuery = useApiQuery(
    balanceSheetQueryKey({ asOfDate: openingDate ?? "", currency, includeRestricted }),
    "balance_sheet_reports_balance_sheet_get",
    { query: { as_of_date: openingDate ?? undefined, currency, include_restricted: includeRestricted } },
    { ...QUERY_OPTIONS, select: normalizeBalanceSheet, enabled: openingDate !== null },
  );
  const incomeQuery = useApiQuery(
    incomeStatementQueryKey({ startDate, endDate, currency }),
    "income_statement_reports_income_statement_get",
    { query: { start_date: startDate, end_date: endDate, currency } },
    { ...QUERY_OPTIONS, select: normalizeIncomeStatement },
  );
  const cashFlowQuery = useApiQuery(
    cashFlowQueryKey({ startDate, endDate, currency }),
    "cash_flow_reports_cash_flow_get",
    { query: { start_date: startDate, end_date: endDate, currency } },
    { ...QUERY_OPTIONS, select: normalizeCashFlow },
  );

  const sources = [balanceQuery, openingQuery, incomeQuery, cashFlowQuery];
  const failed = sources.find((source) => source.isError);

  // `retry` stays stable. It refetches the sources that failed in the latest committed render.
  const failedRefetchers = useRef<Array<() => unknown>>([]);
  useEffect(() => {
    failedRefetchers.current = sources.filter((source) => source.isError).map((source) => source.refetch);
  });
  const retry = useCallback(() => {
    for (const refetch of failedRefetchers.current) void refetch();
  }, []);

  return {
    balanceSheet: balanceQuery.data ?? null,
    // A delta of two periods is wrong: while a new period loads, the opening balance sheet is absent.
    openingBalanceSheet:
      openingDate === null || openingQuery.isPlaceholderData || balanceQuery.isPlaceholderData
        ? null
        : (openingQuery.data ?? null),
    incomeStatement: incomeQuery.data ?? null,
    cashFlow: cashFlowQuery.data ?? null,
    pending: {
      balanceSheet: balanceQuery.isPending,
      incomeStatement: incomeQuery.isPending,
      cashFlow: cashFlowQuery.isPending,
    },
    error: failed ? (failed.error?.message ?? "Failed to load the statements.") : null,
    retry,
  };
}
