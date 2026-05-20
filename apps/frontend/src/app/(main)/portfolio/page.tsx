"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { CalendarDays, X } from "lucide-react";

import { apiFetch } from "@/lib/api";
import { PortfolioHolding } from "@/lib/types";
import { PerformanceCard } from "@/components/portfolio/PerformanceCard";
import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { AllocationChart } from "@/components/portfolio/AllocationChart";
import { formatCurrencyLocale } from "@/lib/currency";

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

    const activeHoldings = holdings?.filter((h) => h.status === "active") ?? [];
    const totalPortfolioValue = activeHoldings.reduce((sum, h) => {
        const val = parseFloat(h.market_value);
        return sum + (isNaN(val) ? 0 : val);
    }, 0);
    const primaryCurrency = activeHoldings[0]?.currency ?? "USD";

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
                </div>
            )}

            <div className="grid gap-4 md:grid-cols-3 mb-6">
                <PerformanceCard />
                <AllocationChart type="sector" title="Sector Allocation" />
                <AllocationChart type="geography" title="Geography Allocation" />
            </div>

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
