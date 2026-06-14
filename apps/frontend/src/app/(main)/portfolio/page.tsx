"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, X } from "lucide-react";

import { apiFetch } from "@/lib/api";
import { PortfolioHolding, PortfolioSummaryResponse } from "@/lib/types";
import { PerformanceCard } from "@/components/portfolio/PerformanceCard";
import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { AllocationChart } from "@/components/portfolio/AllocationChart";
import { InvestmentPerformanceSchedule } from "@/components/portfolio/InvestmentPerformanceSchedule";
import { amountToChartNumber, formatAmount, formatCurrencyLocale, sumAmounts } from "@/lib/currency";
import type { InvestmentPerformanceAllocationRow, InvestmentPerformanceReportSchedule } from "@/lib/types";

function isAssetClassAllocation(row: InvestmentPerformanceAllocationRow): boolean {
    return row.dimension === "asset_class" || row.dimension === "asset-class";
}

function allocationBarWidth(percentage: string): string {
    try {
        const value = amountToChartNumber(percentage);
        return `${Math.min(100, Math.max(0, value))}%`;
    } catch {
        return "0%";
    }
}

function formatAllocationPercent(percentage: string): string {
    try {
        return `${formatAmount(percentage, 1)}%`;
    } catch {
        return "N/A";
    }
}

export default function PortfolioPage() {
    const [showDisposed, setShowDisposed] = useState(false);
    const [asOfDate, setAsOfDate] = useState("");

    const { data: holdings, isLoading, error, refetch } = useQuery({
        queryKey: ["portfolio-holdings", showDisposed, asOfDate],
        queryFn: () => {
            const params = new URLSearchParams();
            if (showDisposed) {
                params.set("include_disposed", "true");
            }
            if (asOfDate) {
                params.set("as_of_date", asOfDate);
            }
            const query = params.toString();
            return apiFetch<PortfolioHolding[]>(`/api/portfolio/holdings${query ? `?${query}` : ""}`);
        },
    });
    const { data: summary } = useQuery({
        queryKey: ["portfolio-summary", asOfDate],
        queryFn: () => apiFetch<PortfolioSummaryResponse>(`/api/portfolio/summary${asOfDate ? `?as_of_date=${asOfDate}` : ""}`),
    });
    const {
        data: performanceSchedule,
        isLoading: isPerformanceScheduleLoading,
        error: performanceScheduleError,
    } = useQuery({
        queryKey: ["portfolio-performance-report-schedule", asOfDate],
        queryFn: () => {
            if (!asOfDate) {
                return apiFetch<InvestmentPerformanceReportSchedule>("/api/portfolio/performance/report-schedule");
            }
            const yearStart = `${asOfDate.slice(0, 4)}-01-01`;
            const params = new URLSearchParams({
                period_start: yearStart,
                period_end: asOfDate,
                as_of_date: asOfDate,
                currency: "SGD",
            });
            return apiFetch<InvestmentPerformanceReportSchedule>(`/api/portfolio/performance/report-schedule?${params}`);
        },
    });

    const activeHoldings = holdings?.filter((h) => h.status === "active") ?? [];
    const totalPortfolioValue = sumAmounts(activeHoldings.map((holding) => holding.market_value));
    const primaryCurrency = activeHoldings[0]?.currency ?? "USD";
    const assetClassAllocationRows = performanceSchedule?.allocation.filter(isAssetClassAllocation) ?? [];
    const unifiedAllocationSchedule =
        performanceSchedule &&
        !isPerformanceScheduleLoading &&
        !performanceScheduleError &&
        activeHoldings.length > 0 &&
        assetClassAllocationRows.length > 0
            ? performanceSchedule
            : null;

    return (
        <div className="p-6">
            <div className="page-header flex items-center justify-between">
                <div>
                    <h1 className="page-title">Portfolio</h1>
                    <p className="page-description">
                        Track your investment holdings, performance, and allocation
                    </p>
                </div>
                <Link href="/portfolio/prices" className="btn-primary flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    Update Prices
                </Link>
            </div>

            {/* Total Portfolio Value Banner */}
            {!isLoading && !error && activeHoldings.length > 0 && (
                <div className="mb-6 card p-5" data-testid="total-portfolio-value">
                    <p className="text-xs text-muted uppercase tracking-wide mb-1">Total Portfolio Value</p>
                    <p className="text-3xl font-bold text-[var(--accent)]">
                        {formatCurrencyLocale(totalPortfolioValue, primaryCurrency)}
                    </p>
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

            {unifiedAllocationSchedule ? (
                <section className="mb-6 card p-5" aria-labelledby="unified-allocation-title">
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div>
                            <p className="text-xs text-muted uppercase tracking-wide">Asset Class</p>
                            <h2 id="unified-allocation-title" className="mt-1 text-base font-semibold">
                                Unified Allocation
                            </h2>
                            <p className="mt-1 text-sm text-muted">
                                Ties to portfolio value: {formatCurrencyLocale(totalPortfolioValue, primaryCurrency)}
                            </p>
                        </div>
                        <p className="text-xs text-muted md:text-right">
                            Schedule currency: {unifiedAllocationSchedule.currency}
                        </p>
                    </div>

                    <div className="mt-4 overflow-hidden rounded border border-[var(--border)]">
                        <div className="hidden grid-cols-[minmax(0,1.5fr)_minmax(7rem,0.7fr)_minmax(5rem,0.5fr)_minmax(6rem,0.5fr)] gap-3 border-b border-[var(--border)] bg-[var(--background-muted)] px-3 py-2 text-xs font-medium uppercase tracking-wide text-muted md:grid">
                            <span>Asset class</span>
                            <span className="text-right">Value</span>
                            <span className="text-right">Share</span>
                            <span className="text-right">Holdings</span>
                        </div>
                        {assetClassAllocationRows.map((row) => (
                            <div
                                key={`${row.dimension}-${row.category}`}
                                className="grid gap-2 border-b border-[var(--border)] px-3 py-3 last:border-b-0 md:grid-cols-[minmax(0,1.5fr)_minmax(7rem,0.7fr)_minmax(5rem,0.5fr)_minmax(6rem,0.5fr)] md:items-center"
                            >
                                <div className="min-w-0">
                                    <p className="font-medium text-[var(--foreground)]">{row.category}</p>
                                    <div className="mt-2 h-2 overflow-hidden rounded-full bg-[var(--background-muted)]" aria-hidden="true">
                                        <div
                                            className="h-full rounded-full bg-[var(--accent)]"
                                            style={{ width: allocationBarWidth(row.percentage) }}
                                        />
                                    </div>
                                </div>
                                <p className="text-sm font-medium md:text-right">
                                    {formatCurrencyLocale(row.value, unifiedAllocationSchedule.currency)}
                                </p>
                                <p className="text-sm text-muted md:text-right">{formatAllocationPercent(row.percentage)}</p>
                                <p className="text-sm text-muted md:text-right">
                                    {row.count} holding{row.count === 1 ? "" : "s"}
                                </p>
                            </div>
                        ))}
                    </div>
                </section>
            ) : null}

            <div className="grid gap-4 md:grid-cols-3 mb-6">
                <PerformanceCard />
                <AllocationChart type="sector" title="Sector Allocation" />
                <AllocationChart type="geography" title="Geography Allocation" />
            </div>

            <InvestmentPerformanceSchedule
                schedule={performanceSchedule}
                isLoading={isPerformanceScheduleLoading}
                error={performanceScheduleError}
            />

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
                    {asOfDate ? (
                        <button
                            type="button"
                            onClick={() => setAsOfDate("")}
                            className="inline-flex h-8 w-8 items-center justify-center rounded border border-[var(--border)] text-muted hover:text-[var(--foreground)]"
                            aria-label="Clear portfolio as-of date"
                        >
                            <X className="h-4 w-4" aria-hidden="true" />
                        </button>
                    ) : null}
                    <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
                        <input
                            type="checkbox"
                            checked={showDisposed}
                            onChange={(e) => setShowDisposed(e.target.checked)}
                            className="rounded"
                        />
                        Show disposed
                    </label>
                </div>
            </div>

            {isLoading ? (
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading holdings...</p>
                </div>
            ) : error ? (
                <div className="card p-8 text-center" role="alert" aria-live="polite">
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--error-muted)] text-[var(--error)] mb-4">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <p className="text-[var(--foreground)] font-medium mb-2">Failed to load holdings</p>
                    <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
                    <button onClick={() => refetch()} className="btn-secondary" aria-label="Retry loading holdings">
                        Retry
                    </button>
                </div>
            ) : holdings && holdings.length > 0 ? (
                <HoldingsTable holdings={holdings} showDisposed={showDisposed} />
            ) : (
                <div className="card p-8 text-center">
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--background-muted)] text-muted mb-4">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                        </svg>
                    </div>
                    <p className="text-muted mb-4">No holdings found</p>
                    <p className="text-sm text-muted mb-6">
                        Upload brokerage statements and reconcile to see your portfolio here.
                    </p>
                </div>
            )}
        </div>
    );
}
