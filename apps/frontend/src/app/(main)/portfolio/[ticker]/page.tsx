"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { apiFetch } from "@/lib/api";
import { DividendEvent, PortfolioHolding, RealizedLot } from "@/lib/types";
import { compareAmounts, formatAmount, formatCurrencyLocale, formatQuantity } from "@/lib/money";
import { formatDateDisplay } from "@/lib/date";

function getPnlColor(value: string): string {
    const comparison = compareAmounts(value, "0");
    if (comparison === 0) return "";
    return comparison > 0 ? "text-[var(--success)]" : "text-[var(--error)]";
}

function formatPnlPercent(value: string): string {
    const sign = compareAmounts(value, "0") > 0 ? "+" : "";
    return `${sign}${formatAmount(value, 2)}%`;
}

export default function HoldingDetailPage() {
    const params = useParams();
    const ticker = decodeURIComponent(params.ticker as string);
    const [activeTab, setActiveTab] = useState<"overview" | "dividends" | "realized">("overview");
    const [savingMethod, setSavingMethod] = useState(false);

    const { data: allHoldings, isLoading, error, refetch } = useQuery({
        queryKey: ["portfolio-holdings-all"],
        queryFn: () => apiFetch<PortfolioHolding[]>("/api/portfolio/holdings?include_disposed=true"),
    });
    const { data: dividends = [], refetch: refetchDividends } = useQuery({
        queryKey: ["portfolio-dividends", ticker],
        queryFn: () => apiFetch<DividendEvent[]>(`/api/portfolio/${encodeURIComponent(ticker)}/dividends`),
    });
    const { data: realizedLots = [], refetch: refetchRealized } = useQuery({
        queryKey: ["portfolio-realized", ticker],
        queryFn: () => apiFetch<RealizedLot[]>(`/api/portfolio/${encodeURIComponent(ticker)}/realized`),
    });

    const holdings = allHoldings?.filter((h) => h.asset_identifier === ticker) ?? [];
    const activeHoldings = holdings.filter((h) => h.status === "active");
    const disposedHoldings = holdings.filter((h) => h.status === "disposed");

    if (isLoading) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center text-muted">
                    <div className="inline-block w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin mb-2" />
                    <p className="text-sm">Loading holding details...</p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="p-6">
                <div className="card p-8 text-center" role="alert" aria-live="polite">
                    <div className="inline-flex items-center justify-center w-12 h-12 rounded-full bg-[var(--error-muted)] text-[var(--error)] mb-4">
                        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <p className="text-[var(--foreground)] font-medium mb-2">Failed to load holding</p>
                    <p className="text-sm text-muted mb-6">{error instanceof Error ? error.message : "Unknown error"}</p>
                    <button onClick={() => refetch()} className="btn-secondary">Retry</button>
                </div>
            </div>
        );
    }

    if (holdings.length === 0) {
        return (
            <div className="p-6">
                <div className="mb-4">
                    <Link href="/portfolio" className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                        </svg>
                        Back to Portfolio
                    </Link>
                </div>
                <div className="card p-8 text-center">
                    <p className="text-muted">No holdings found for <span className="font-mono font-medium">{ticker}</span></p>
                </div>
            </div>
        );
    }

    const primary = activeHoldings[0] ?? holdings[0];
    const selectedCostBasisMethod = primary.cost_basis_method ?? "FIFO";

    const updateCostBasisMethod = async (method: "FIFO" | "LIFO" | "AvgCost") => {
        setSavingMethod(true);
        try {
            await apiFetch(`/api/portfolio/${encodeURIComponent(ticker)}`, {
                method: "PATCH",
                body: JSON.stringify({ cost_basis_method: method }),
            });
            await Promise.all([refetch(), refetchRealized(), refetchDividends()]);
        } finally {
            setSavingMethod(false);
        }
    };

    return (
        <div className="p-6">
            <div className="mb-4">
                <Link href="/portfolio" className="text-sm text-muted hover:text-[var(--foreground)] flex items-center gap-1">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    Back to Portfolio
                </Link>
            </div>

            <div className="page-header">
                <h1 className="page-title font-mono">{ticker}</h1>
                <p className="page-description">
                    {primary.sector && `${primary.sector} \u00b7 `}
                    {primary.geography && `${primary.geography} \u00b7 `}
                    {primary.asset_type ?? "Equity"}
                </p>
            </div>

            <div className="mb-6 flex flex-col gap-3 border-b border-[var(--border)] pb-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex gap-2" role="tablist" aria-label="Holding detail views">
                    {[
                        ["overview", "Overview"],
                        ["dividends", "Dividends"],
                        ["realized", "Realized P&L"],
                    ].map(([value, label]) => (
                        <button
                            key={value}
                            type="button"
                            role="tab"
                            aria-selected={activeTab === value}
                            onClick={() => setActiveTab(value as "overview" | "dividends" | "realized")}
                            className={`rounded border px-3 py-1.5 text-sm ${activeTab === value ? "border-[var(--accent)] text-[var(--accent)]" : "border-[var(--border)] text-muted"}`}
                        >
                            {label}
                        </button>
                    ))}
                </div>
                <label className="flex items-center gap-2 text-sm text-muted">
                    <span>Cost basis method</span>
                    <select
                        value={selectedCostBasisMethod}
                        disabled={savingMethod}
                        onChange={(event) => updateCostBasisMethod(event.target.value as "FIFO" | "LIFO" | "AvgCost")}
                        className="rounded border border-[var(--border)] bg-[var(--background)] px-2 py-1 text-sm text-[var(--foreground)]"
                    >
                        <option value="FIFO">FIFO</option>
                        <option value="LIFO">LIFO</option>
                        <option value="AvgCost">AvgCost</option>
                    </select>
                </label>
            </div>

            {activeTab === "overview" && (
                <>
            <div className="grid gap-4 md:grid-cols-4 mb-6">
                <div className="card p-5">
                    <p className="text-xs text-muted uppercase tracking-wide">Market Value</p>
                    <p className="text-2xl font-semibold mt-1">
                        {formatCurrencyLocale(primary.market_value, primary.currency)}
                    </p>
                </div>
                <div className="card p-5">
                    <p className="text-xs text-muted uppercase tracking-wide">Cost Basis</p>
                    <p className="text-2xl font-semibold mt-1">
                        {formatCurrencyLocale(primary.cost_basis, primary.currency)}
                    </p>
                </div>
                <div className="card p-5">
                    <p className="text-xs text-muted uppercase tracking-wide">Unrealized P&L</p>
                    <p className={`text-2xl font-semibold mt-1 ${getPnlColor(primary.unrealized_pnl)}`}>
                        {formatCurrencyLocale(primary.unrealized_pnl, primary.currency)}
                    </p>
                    <p className={`text-sm mt-0.5 ${getPnlColor(primary.unrealized_pnl_percent)}`}>
                        {formatPnlPercent(primary.unrealized_pnl_percent)}
                    </p>
                </div>
                <div className="card p-5">
                    <p className="text-xs text-muted uppercase tracking-wide">Quantity</p>
                    <p className="text-2xl font-semibold mt-1 font-mono">{formatQuantity(primary.quantity)}</p>
                    <p className="text-xs text-muted mt-0.5">
                        {primary.cost_basis_method ?? "Default"} method
                    </p>
                </div>
            </div>

            {activeHoldings.length > 0 && (
                <div className="card mb-6">
                    <div className="card-header">
                        <h2 className="text-sm font-medium">Active Lots</h2>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-[var(--border)]">
                                    <th className="text-left px-4 py-2 font-medium">Account</th>
                                    <th className="text-right px-4 py-2 font-medium">Qty</th>
                                    <th className="text-right px-4 py-2 font-medium">Cost Basis</th>
                                    <th className="text-right px-4 py-2 font-medium">Market Value</th>
                                    <th className="text-right px-4 py-2 font-medium">P&L</th>
                                    <th className="text-left px-4 py-2 font-medium">Acquired</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {activeHoldings.map((h) => (
                                    <tr key={h.id} className="hover:bg-[var(--background-muted)]/50">
                                        <td className="px-4 py-2">{h.account_name ?? "Unknown"}</td>
                                        <td className="px-4 py-2 text-right font-mono">{formatQuantity(h.quantity)}</td>
                                        <td className="px-4 py-2 text-right">{formatCurrencyLocale(h.cost_basis, h.currency)}</td>
                                        <td className="px-4 py-2 text-right font-medium">{formatCurrencyLocale(h.market_value, h.currency)}</td>
                                        <td className={`px-4 py-2 text-right font-medium ${getPnlColor(h.unrealized_pnl)}`}>
                                            {formatCurrencyLocale(h.unrealized_pnl, h.currency)}
                                        </td>
                                        <td className="px-4 py-2">{formatDateDisplay(h.acquisition_date)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {disposedHoldings.length > 0 && (
                <div className="card">
                    <div className="card-header">
                        <h2 className="text-sm font-medium">Disposed Lots</h2>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-[var(--border)]">
                                    <th className="text-left px-4 py-2 font-medium">Account</th>
                                    <th className="text-right px-4 py-2 font-medium">Qty</th>
                                    <th className="text-right px-4 py-2 font-medium">Cost Basis</th>
                                    <th className="text-left px-4 py-2 font-medium">Acquired</th>
                                    <th className="text-left px-4 py-2 font-medium">Disposed</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {disposedHoldings.map((h) => (
                                    <tr key={h.id} className="hover:bg-[var(--background-muted)]/50 text-muted">
                                        <td className="px-4 py-2">{h.account_name ?? "Unknown"}</td>
                                        <td className="px-4 py-2 text-right font-mono">{formatQuantity(h.quantity)}</td>
                                        <td className="px-4 py-2 text-right">{formatCurrencyLocale(h.cost_basis, h.currency)}</td>
                                        <td className="px-4 py-2">{formatDateDisplay(h.acquisition_date)}</td>
                                        <td className="px-4 py-2">{h.disposal_date ? formatDateDisplay(h.disposal_date) : "\u2014"}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
                </>
            )}

            {activeTab === "dividends" && (
                <div className="card">
                    <div className="card-header">
                        <h2 className="text-sm font-medium">Dividend Events</h2>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-[var(--border)]">
                                    <th className="text-left px-4 py-2 font-medium">Ex Date</th>
                                    <th className="text-left px-4 py-2 font-medium">Pay Date</th>
                                    <th className="text-right px-4 py-2 font-medium">Amount</th>
                                    <th className="text-left px-4 py-2 font-medium">Currency</th>
                                    <th className="text-left px-4 py-2 font-medium">Reinvested</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {dividends.length ? dividends.map((event) => (
                                    <tr key={event.id}>
                                        <td className="px-4 py-2">{formatDateDisplay(event.ex_date)}</td>
                                        <td className="px-4 py-2">{formatDateDisplay(event.pay_date)}</td>
                                        <td className="px-4 py-2 text-right">{formatCurrencyLocale(event.amount, event.currency)}</td>
                                        <td className="px-4 py-2">{event.currency}</td>
                                        <td className="px-4 py-2">{event.reinvested ? "Yes" : "No"}</td>
                                    </tr>
                                )) : (
                                    <tr>
                                        <td className="px-4 py-6 text-center text-muted" colSpan={5}>No dividends recorded.</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {activeTab === "realized" && (
                <div className="card">
                    <div className="card-header">
                        <h2 className="text-sm font-medium">Realized P&L Lots</h2>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead>
                                <tr className="border-b border-[var(--border)]">
                                    <th className="text-left px-4 py-2 font-medium">Lot</th>
                                    <th className="text-left px-4 py-2 font-medium">Acquired</th>
                                    <th className="text-left px-4 py-2 font-medium">Sold</th>
                                    <th className="text-right px-4 py-2 font-medium">Quantity</th>
                                    <th className="text-right px-4 py-2 font-medium">Basis</th>
                                    <th className="text-right px-4 py-2 font-medium">Proceeds</th>
                                    <th className="text-right px-4 py-2 font-medium">Gain/Loss</th>
                                    <th className="text-right px-4 py-2 font-medium">Holding Period</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-[var(--border)]">
                                {realizedLots.length ? realizedLots.map((lot) => (
                                    <tr key={lot.lot_id}>
                                        <td className="px-4 py-2 font-mono">{lot.lot_id.slice(0, 8)}</td>
                                        <td className="px-4 py-2">{lot.acquired_date ? formatDateDisplay(lot.acquired_date) : "\u2014"}</td>
                                        <td className="px-4 py-2">{formatDateDisplay(lot.sold_date)}</td>
                                        <td className="px-4 py-2 text-right font-mono">{formatQuantity(lot.quantity)}</td>
                                        <td className="px-4 py-2 text-right">{formatCurrencyLocale(lot.basis, lot.currency)}</td>
                                        <td className="px-4 py-2 text-right">{formatCurrencyLocale(lot.proceeds, lot.currency)}</td>
                                        <td className={`px-4 py-2 text-right font-medium ${getPnlColor(lot.gain_loss)}`}>{formatCurrencyLocale(lot.gain_loss, lot.currency)}</td>
                                        <td className="px-4 py-2 text-right">{lot.holding_period ?? "\u2014"}</td>
                                    </tr>
                                )) : (
                                    <tr>
                                        <td className="px-4 py-6 text-center text-muted" colSpan={8}>No realized lots recorded.</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
}
