/**
 * Query keys that several routes share (#2583 S4).
 *
 * Home, /audit, /upload, the `/reports` tabs and the reconciliation Workbench read the same
 * endpoints with the same parameters. One key per endpoint-and-parameters pair lets react-query
 * serve a second reader from the cache and merge two readers that mount together into one request.
 * A route must build these keys here. It must not write its own key for the same request.
 * Each route still calls `useApiQuery` with the operation id, so every consumer of an operation
 * stays visible to the operation-consumer census.
 */

/** Stale time of the shared read models. It equals the default in `lib/queryClient.ts`. */
export const SHARED_STALE_MS = 60_000;

/** `GET /statements`: the lean list (no transactions). */
export const STATEMENTS_LIST_QUERY_KEY = ["statements", "list"] as const;
/** `GET /reports/coverage`: the cash coverage start that bounds a preset report period (#2646). */
export const REPORT_COVERAGE_QUERY_KEY = ["report", "coverage"] as const;
/** `GET /reconciliation/stats`. */
export const RECONCILIATION_STATS_QUERY_KEY = ["reconciliation", "stats"] as const;
/** `GET /accounts/processing/pending`. */
export const PROCESSING_PENDING_QUERY_KEY = ["accounts", "processing", "pending"] as const;
/** `GET /reconciliation/unmatched?limit=1`: the newest unmatched row that names the queue item (#2646). */
export const UNMATCHED_FIRST_QUERY_KEY = ["reconciliation", "unmatched", "first"] as const;
/** The request of `UNMATCHED_FIRST_QUERY_KEY`. */
export const UNMATCHED_FIRST_REQUEST = { query: { limit: 1 } } as const;

export interface BalanceSheetKeyParams {
  asOfDate?: string;
  currency?: string;
  includeRestricted: boolean;
}

/** Key of `GET /reports/balance-sheet`. Equal parameters give an equal key on every route. */
export function balanceSheetQueryKey({ asOfDate, currency, includeRestricted }: BalanceSheetKeyParams) {
  const search = new URLSearchParams();
  if (asOfDate) search.set("as_of_date", asOfDate);
  if (currency) search.set("currency", currency);
  search.set("include_restricted", includeRestricted ? "true" : "false");
  return ["report", "balance-sheet", search.toString()] as const;
}

export interface IncomeStatementKeyParams {
  startDate: string;
  endDate: string;
  currency?: string;
  accountType?: string;
  tags?: readonly string[];
}

/** Key of `GET /reports/income-statement`. Equal parameters give an equal key on every route. */
export function incomeStatementQueryKey({
  startDate,
  endDate,
  currency,
  accountType,
  tags,
}: IncomeStatementKeyParams) {
  const search = new URLSearchParams();
  search.set("start_date", startDate);
  search.set("end_date", endDate);
  if (currency) search.set("currency", currency);
  if (accountType) search.set("account_type", accountType);
  for (const tag of tags ?? []) search.append("tags", tag);
  return ["report", "income-statement", search.toString()] as const;
}

export interface CashFlowKeyParams {
  startDate: string;
  endDate: string;
  currency?: string;
}

/** Key of `GET /reports/cash-flow`. Home and the Cash flow tab share it. */
export function cashFlowQueryKey({ startDate, endDate, currency }: CashFlowKeyParams) {
  const search = new URLSearchParams();
  search.set("start_date", startDate);
  search.set("end_date", endDate);
  if (currency) search.set("currency", currency);
  return ["report", "cash-flow", search.toString()] as const;
}
