"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, X } from "lucide-react";

import { apiOperation } from "@/lib/api-client";
import { invalidatePortfolioQueries } from "@/lib/queryClient";
import { useBaseCurrency } from "@/hooks/useBaseCurrency";
import GuidedEvidenceForm, { SOURCE_CLASS_CONFIGS, type EvidenceSourceClass } from "@/components/assets/GuidedEvidenceForm";
import { APP_ROUTES } from "@/components/navigation";
import { PerformanceCard, AllocationChart } from "@/components/portfolio/PortfolioSummary";
import { LoadingState } from "@/components/ui";
import { Sheet } from "@/components/ui/Overlay";
import { HoldingDetail, HoldingsTable, PriceUpdateForm } from "@/components/portfolio/Holdings";
import { InvestmentPerformanceSchedule } from "@/components/portfolio/InvestmentPerformanceSchedule";
import { AccountLineageDrawer, type AccountLineageTarget } from "@/components/reports/AccountLineageDrawer";
import { ExcludedHoldingsNote } from "@/components/reports/ExcludedHoldingsNote";
import { DEFAULT_INCLUDE_RESTRICTED } from "@/hooks/useReportFilters";
import { amountToChartNumber, formatCurrencyLocale, sumAmounts } from "@/lib/audit/money";
import { clampPercentWidthFromPercentValue, formatPercentFromPercentValue } from "@/lib/audit/ratio/format";
import { allocationClassLabel } from "@/lib/statusLabels";
import type { NetWorthAllocationRow, NetWorthAllocationSourceLine } from "@/lib/types";

/**
 * One contributor of an allocation row (#2645). A ledger account opens its source transactions in
 * the lineage drawer. A manual valuation links to the evidence drawer, which lists the recorded
 * valuations. Any other contributor is plain text: its value shows in the holdings table below.
 */
function AllocationSource({
  line,
  onOpenLineage,
}: {
  line: NetWorthAllocationSourceLine;
  onOpenLineage: (accountId: string, accountName: string) => void;
}) {
  if (line.source_type === "ledger_account" && line.source_id) {
    const accountId = line.source_id;
    return (
      <button
        type="button"
        onClick={() => onOpenLineage(accountId, line.label)}
        aria-label={`View source transactions for ${line.label}`}
        className="max-w-full truncate text-left hover:text-[var(--foreground)] hover:underline"
      >
        {line.label}
      </button>
    );
  }
  if (line.source_type === "manual_valuation") {
    return (
      <Link href={APP_ROUTES.PORTFOLIO_EVIDENCE} scroll={false} className="hover:text-[var(--foreground)]">
        {line.label}
      </Link>
    );
  }
  return <>{line.label}</>;
}

export default function PortfolioPage() {
  const queryClient = useQueryClient();
  const { baseCurrency: reportCurrency } = useBaseCurrency();
  const [showDisposed, setShowDisposed] = useState(false);
  const [asOfDate, setAsOfDate] = useState("");
  const [includeRestrictedAllocation, setIncludeRestrictedAllocation] = useState(DEFAULT_INCLUDE_RESTRICTED);
  const [lineageTarget, setLineageTarget] = useState<AccountLineageTarget | null>(null);

  // The URL opens one drawer: `?ticker=` a holding, `?panel=prices` the price update, `?panel=evidence` the evidence form.
  const router = useRouter();
  const searchParams = useSearchParams();
  const ticker = searchParams?.get("ticker")?.trim() || null;
  const panel = searchParams?.get("panel");
  const drawer = ticker ? "holding" : panel === "prices" || panel === "evidence" ? panel : null;
  const rawSourceClass = searchParams?.get("source_class");
  const evidenceSourceClass = SOURCE_CLASS_CONFIGS.some((c) => c.value === rawSourceClass) ? (rawSourceClass as EvidenceSourceClass) : undefined;
  const closeDrawer = () => router.replace(APP_ROUTES.PORTFOLIO, { scroll: false });

  const { data: holdings, isLoading, error, refetch } = useQuery({
    queryKey: ["portfolio-holdings", showDisposed, asOfDate],
    queryFn: () =>
      apiOperation("get_holdings_portfolio_holdings_get", {
        query: { include_disposed: showDisposed || undefined, as_of_date: asOfDate || undefined },
      }).then((res) => res.items),
  });

  const { data: summary } = useQuery({
    queryKey: ["portfolio-summary", asOfDate],
    queryFn: () => apiOperation("get_portfolio_summary_portfolio_summary_get", { query: { as_of_date: asOfDate || undefined } }),
  });

  const { data: performanceSchedule, isLoading: isPerformanceScheduleLoading, error: performanceScheduleError } = useQuery({
    queryKey: ["portfolio-performance-report-schedule", asOfDate, reportCurrency],
    queryFn: () => {
      const yearStart = asOfDate ? `${asOfDate.slice(0, 4)}-01-01` : undefined;
      return apiOperation("get_investment_performance_report_schedule_portfolio_performance_report_schedule_get", {
        query: { period_start: yearStart, period_end: asOfDate || undefined, as_of_date: asOfDate || undefined, currency: reportCurrency },
      });
    },
  });

  const { data: netWorthAllocation, isLoading: isNetWorthAllocationLoading, error: netWorthAllocationError } = useQuery({
    queryKey: ["reports-net-worth-allocation", asOfDate, reportCurrency, includeRestrictedAllocation],
    queryFn: () =>
      apiOperation("net_worth_allocation_reports_net_worth_allocation_get", {
        query: { as_of_date: asOfDate || undefined, currency: reportCurrency, include_restricted: includeRestrictedAllocation },
      }),
  });

  const activeHoldings = useMemo(() => holdings?.filter((h) => h.status === "active") ?? [], [holdings]);
  const totalPortfolioValue = sumAmounts(activeHoldings.map((h) => h.market_value));
  const primaryCurrency = activeHoldings[0]?.currency ?? reportCurrency;
  const allocationRows = netWorthAllocation?.rows ?? [];

  return (
    <div className="p-6">
      <div className="page-header flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="page-title">Portfolio</h1>
          <p className="page-description">Track your investment holdings, performance, and allocation</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link href={APP_ROUTES.PORTFOLIO_EVIDENCE} scroll={false} className="btn-secondary">
            Add evidence
          </Link>
          <Link href={APP_ROUTES.PORTFOLIO_PRICES} scroll={false} className="btn-primary flex items-center gap-2">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            Update Prices
          </Link>
        </div>
      </div>

      <Sheet isOpen={drawer === "holding"} onClose={closeDrawer} title={ticker ?? ""} width="max-w-3xl">
        {ticker && <HoldingDetail ticker={ticker} />}
      </Sheet>
      <Sheet isOpen={drawer === "prices"} onClose={closeDrawer} title="Update Market Prices" width="max-w-2xl">
        <p className="mb-4 text-sm text-muted">Enter the latest market prices to refresh the portfolio valuations.</p>
        <PriceUpdateForm
          knownTickers={Array.from(new Set(activeHoldings.map((h) => h.asset_identifier))).sort()}
          onSuccess={() => { closeDrawer(); void invalidatePortfolioQueries(queryClient); }}
        />
      </Sheet>
      <Sheet isOpen={drawer === "evidence"} onClose={closeDrawer} title="Guided evidence intake" width="max-w-2xl">
        <p className="mb-4 text-sm text-muted">
          Record ESOP/RSU, property, and liability evidence with a structured valuation basis and source anchor. Manually entered values are clearly labelled manual-trusted across reports and the traceability appendix.
        </p>
        <GuidedEvidenceForm initialSourceClass={evidenceSourceClass} />
      </Sheet>

      {!isLoading && !error && activeHoldings.length > 0 && (
        <div className="mb-6 card p-5" data-testid="total-portfolio-value">
          <p className="text-xs text-muted uppercase tracking-wide mb-1">Total Portfolio Value</p>
          <p className="text-3xl font-bold text-[var(--accent)]">{formatCurrencyLocale(totalPortfolioValue, primaryCurrency)}</p>
          <p className="text-xs text-muted mt-1">
            Active holdings · {activeHoldings.length} position{activeHoldings.length !== 1 ? "s" : ""}
          </p>
          {summary && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded border border-[var(--border)] p-3">
                <p className="text-xs text-muted uppercase tracking-wide">Realized P&L YTD</p>
                <p className="text-lg font-semibold">{formatCurrencyLocale(summary.realized_pnl_ytd, summary.currency)}</p>
              </div>
              <div className="rounded border border-[var(--border)] p-3">
                <p className="text-xs text-muted uppercase tracking-wide">Dividend Income YTD</p>
                <p className="text-lg font-semibold">{formatCurrencyLocale(summary.dividend_income_ytd, summary.currency)}</p>
              </div>
            </div>
          )}
        </div>
      )}

      <section className="mb-6 card p-5" aria-labelledby="net-worth-allocation-title" aria-busy={isNetWorthAllocationLoading}>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs text-muted uppercase tracking-wide">Asset Class x Liquidity x Source Currency</p>
            <h2 id="net-worth-allocation-title" className="mt-1 text-base font-semibold">Net Worth Allocation</h2>
            <p className="mt-1 text-sm text-muted">
              {netWorthAllocation ? `Reconciles to net worth: ${formatCurrencyLocale(netWorthAllocation.net_worth, netWorthAllocation.currency)}` : "Reconciles allocation rows to net worth"}
            </p>
            {activeHoldings.length > 0 && (
              <p className="mt-1 text-sm text-muted">
                Portfolio value shown in {primaryCurrency}: {formatCurrencyLocale(totalPortfolioValue, primaryCurrency)}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="text-xs text-muted md:text-right">
              <p>Report currency: {netWorthAllocation?.currency ?? reportCurrency}</p>
              <p>As of {netWorthAllocation?.as_of_date ?? (asOfDate || "latest")}</p>
            </div>
            <label className="flex items-center gap-2 rounded border border-[var(--border)] px-3 py-2 text-sm text-muted cursor-pointer">
              <input
                type="checkbox"
                checked={includeRestrictedAllocation}
                onChange={(e) => setIncludeRestrictedAllocation(e.target.checked)}
                className="rounded"
              />
              <span>Include restricted holdings in allocation</span>
            </label>
          </div>
        </div>

        {netWorthAllocation && (
          <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
            {([
              ["Total assets", netWorthAllocation.total_assets],
              ["Total liabilities", netWorthAllocation.total_liabilities],
              [netWorthAllocation.include_restricted ? "Net worth" : "Liquid net worth", netWorthAllocation.net_worth],
            ] as const).map(([dt, val]) => (
              <div key={dt} className="rounded border border-[var(--border)] p-3">
                <dt className="text-xs text-muted uppercase">{dt}</dt>
                <dd className="mt-1 font-semibold">{formatCurrencyLocale(val, netWorthAllocation.currency)}</dd>
              </div>
            ))}
          </dl>
        )}
        {netWorthAllocation && (
          <ExcludedHoldingsNote
            rows={netWorthAllocation.excluded_holdings}
            currency={netWorthAllocation.currency}
            formatMoney={formatCurrencyLocale}
          />
        )}

        <div className="mt-4 overflow-hidden rounded border border-[var(--border)]">
          <div className="hidden grid-cols-[minmax(0,1.4fr)_minmax(6rem,0.6fr)_minmax(6rem,0.6fr)_minmax(5rem,0.4fr)_minmax(8rem,0.8fr)] gap-3 border-b border-[var(--border)] bg-[var(--background-muted)] px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted md:grid">
            <span>Asset class</span>
            <span className="text-right">Value</span>
            <span className="text-right">Share</span>
            <span className="text-right">Source currency</span>
            <span>Sources</span>
          </div>
          {isNetWorthAllocationLoading ? (
            <div className="px-3 py-4 text-sm text-muted">Loading net worth allocation...</div>
          ) : netWorthAllocationError ? (
            <div className="px-3 py-4 text-sm text-muted">Unable to load net worth allocation</div>
          ) : allocationRows.length === 0 ? (
            <div className="px-3 py-4 text-sm text-muted">No allocation rows available</div>
          ) : (
            allocationRows.map((row: NetWorthAllocationRow) => {
              const isNeg = amountToChartNumber(row.value) < 0;
              return (
                <div
                  key={`${row.asset_class}-${row.liquidity_class}-${row.source_currency}`}
                  className="grid gap-2 border-b border-[var(--border)] px-3 py-3 last:border-b-0 md:grid-cols-[minmax(0,1.4fr)_minmax(6rem,0.6fr)_minmax(6rem,0.6fr)_minmax(5rem,0.4fr)_minmax(8rem,0.8fr)] md:items-center"
                >
                  <div className="min-w-0">
                    <p className="font-medium text-[var(--foreground)]">{allocationClassLabel(row.asset_class)}</p>
                    <p className="mt-1 text-xs text-muted">{allocationClassLabel(row.liquidity_class)}</p>
                    <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--background-muted)]" aria-hidden="true">
                      <div
                        className={`h-full rounded-full ${isNeg ? "bg-[var(--error)]" : "bg-[var(--accent)]"}`}
                        style={{ width: clampPercentWidthFromPercentValue(row.percentage_of_net_worth) }}
                      />
                    </div>
                  </div>
                  <p className={`text-sm font-medium md:text-right ${isNeg ? "text-[var(--error)]" : "text-[var(--foreground)]"}`}>
                    {formatCurrencyLocale(row.value, netWorthAllocation?.currency ?? reportCurrency)}
                  </p>
                  <p className="text-sm text-muted md:text-right">{formatPercentFromPercentValue(row.percentage_of_net_worth, { dp: 1 })}</p>
                  <p className="text-sm text-muted md:text-right">{row.source_currency}</p>
                  <div className="min-w-0 text-sm text-muted">
                    <p className="font-medium text-[var(--foreground)]">
                      {row.source_line_count} source{row.source_line_count === 1 ? "" : "s"}
                    </p>
                    <ul className="mt-1 space-y-1">
                      {row.source_lines.slice(0, 2).map((line) => (
                        <li key={`${line.source_type}-${line.source_id ?? line.label}`} className="truncate" title={line.label}>
                          <AllocationSource
                            line={line}
                            onOpenLineage={(accountId, accountName) =>
                              setLineageTarget({
                                accountId,
                                accountName,
                                asOfDate: netWorthAllocation?.as_of_date ?? asOfDate,
                                currency: netWorthAllocation?.currency ?? reportCurrency,
                              })
                            }
                          />
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-3 mb-6">
        <PerformanceCard schedule={performanceSchedule} isLoading={isPerformanceScheduleLoading} error={performanceScheduleError} />
        <AllocationChart type="sector" title="Sector Allocation" />
        <AllocationChart type="geography" title="Geography Allocation" />
      </div>

      <InvestmentPerformanceSchedule schedule={performanceSchedule} isLoading={isPerformanceScheduleLoading} error={performanceScheduleError} />

      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
        <h2 className="text-lg font-semibold">Holdings</h2>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-muted">
            <CalendarDays className="h-4 w-4" aria-hidden="true" />
            <span>As of</span>
            <input
              type="date"
              value={asOfDate}
              onChange={(e) => setAsOfDate(e.target.value)}
              className="rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm text-[var(--foreground)]"
              aria-label="Portfolio as-of date"
            />
          </label>
          {asOfDate && (
            <button
              type="button"
              onClick={() => setAsOfDate("")}
              className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-muted hover:text-[var(--foreground)]"
              aria-label="Clear portfolio as-of date"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input type="checkbox" checked={showDisposed} onChange={(e) => setShowDisposed(e.target.checked)} className="rounded" />
            Show disposed
          </label>
        </div>
      </div>

      {isLoading ? (
        <LoadingState label="Loading holdings" />
      ) : error ? (
        <div className="card p-8 text-center" role="alert" aria-live="polite">
          <p className="text-[var(--foreground)] font-medium mb-2">Failed to load holdings</p>
          <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
          <button onClick={() => refetch()} className="btn-secondary" aria-label="Retry loading holdings">Retry</button>
        </div>
      ) : holdings && holdings.length > 0 ? (
        <HoldingsTable holdings={holdings} showDisposed={showDisposed} />
      ) : (
        <div className="card p-8 text-center">
          <p className="text-muted mb-4">No holdings found</p>
          <p className="text-sm text-muted mb-6">Upload brokerage statements and reconcile to see your portfolio here.</p>
        </div>
      )}
      <AccountLineageDrawer target={lineageTarget} onClose={() => setLineageTarget(null)} />
    </div>
  );
}
